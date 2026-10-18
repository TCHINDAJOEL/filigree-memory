"""Explicit history catch-up (`filigree backfill`, ADR-0003 D11 amendment). Synthetic data only."""

from datetime import datetime, timezone
import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from filigree import backfill, cli
from filigree import capture as capture_module
from filigree.activity import ActivityLog, Observer, journal_path
from filigree.capture import ProcessLock
from filigree.collectors.claude_code import ClaudeCodeCollector
from filigree.collectors.codex_rollout import CodexRolloutCollector
from filigree.store import Store

try:
    from test_capture import CaptureCase
    from tap_fixtures import append_jsonl, claude_line, claude_record, write_claude_transcript
except ImportError:  # run as tests.test_v2_backfill from the repository root
    from tests.test_capture import CaptureCase
    from tests.tap_fixtures import append_jsonl, claude_line, claude_record, write_claude_transcript


class BackfillCase(CaptureCase):
    def setUp(self):
        super().setUp()
        patcher = patch.object(capture_module, "FALLBACK_GRACE", 0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tap.create()
        self.tap.add_session("T0")

    def history(self, session="S1", tap_id="T1", turns=2):
        """Pre-baseline history: a native transcript naming its folder, and tap records claiming that native id."""
        write_claude_transcript(self.claude_root, session, self.folder_a, lines=0)
        append_jsonl(self.claude_root / "-synthetic" / f"{session}.jsonl", {"type": "system", "sessionId": session, "cwd": str(self.folder_a)})
        self.tap.add_session(tap_id)
        for number in range(turns):
            self.tap.add_record(tap_id, claude_record(session, f"question {number}", f"réponse {number}"))

    def baseline(self):
        self.capture.scan_once()
        self.assertEqual(self.store.list_projects(), [])

    def run_backfill(self):
        return backfill.rewind(self.memory, env={})

    def drain(self, cycles=4):
        for _ in range(cycles):
            self.capture.scan_once()

    def projects(self):
        return self.store.list_projects()


class TapBackfillTests(BackfillCase):
    def setUp(self):
        super().setUp()
        self.configure(sources={"native_fallback": False})

    def test_baselined_session_with_resolvable_native_id_is_imported_with_native_link(self):
        self.history()
        self.baseline()
        self.drain(2)
        self.assertEqual(self.store.list_projects(), [])  # by design nothing is caught up
        result = self.run_backfill()
        self.assertEqual(result["tap"]["records"], 2)
        self.drain()
        projects = self.projects()
        self.assertEqual(len(projects), 1)
        self.assertEqual(Path(projects[0]["folder"]["path"]), self.folder_a)
        entries = self.store.list_entries(projects[0]["id"])
        self.assertEqual(sorted(entry["body"] for entry in entries if entry["body"].startswith("question")), ["question 0", "question 1"])
        self.assertEqual(len(entries), 4)
        for entry in entries:
            provenance = self.provenance(entry)
            self.assertEqual((provenance["link"], provenance["native_id"]), ("native", "S1"))
        self.assertEqual(self.state()["backfill"], {})  # closed once every source is caught up
        self.assertEqual([n["code"] for n in self.state()["notices"] if n["code"].startswith("backfill")][-1], "backfill_done")

    def test_unresolvable_session_stays_pending_and_is_never_attached(self):
        self.tap.add_session("T2")
        self.tap.add_record("T2", claude_record("S-unknown", "orpheline", "sans dossier"))
        self.baseline()
        self.run_backfill()
        self.drain()
        self.assertEqual(self.projects(), [])
        pending = self.capture.pending()
        self.assertEqual([(item["key"], item["reason"], item["count"]) for item in pending], [("S-unknown", "unknown_native", 1)])
        self.assertNotIn("orpheline", json.dumps(pending))

    def test_running_twice_never_duplicates(self):
        self.history()
        self.baseline()
        self.run_backfill()
        self.drain()
        pid = self.projects()[0]["id"]
        before = self.texts(pid)
        self.run_backfill()
        self.drain()
        self.drain(2)
        self.assertEqual(self.texts(pid), before)
        self.assertEqual(len(before), 4)

    def test_a_tap_database_never_baselined_is_replayed_whole(self):
        self.history()  # no scan yet: without backfill the first scan would baseline all of it
        self.run_backfill()
        self.drain()
        self.assertEqual(len(self.store.list_entries(self.projects()[0]["id"])), 4)

    def test_future_activity_is_still_captured_after_the_replay(self):
        self.history()
        self.baseline()
        self.run_backfill()
        self.drain()
        self.tap.add_record("T1", claude_record("S1", "nouvelle question", "nouvelle réponse"))
        self.drain(2)
        self.assertEqual(len(self.store.list_entries(self.projects()[0]["id"])), 6)


class NativeBackfillTests(BackfillCase):
    def native(self, session="S6", old=True):
        path = write_claude_transcript(self.claude_root, session, self.folder_a, lines=0)
        append_jsonl(path, {"type": "system", "sessionId": session, "cwd": str(self.folder_a)},
                     claude_line(session, self.folder_a, "user", "Q natif", "u1"), claude_line(session, self.folder_a, "assistant", [{"type": "text", "text": "A natif"}], "u2"))
        return path

    def test_tap_and_native_copies_of_the_same_items_are_imported_once(self):
        self.native()
        self.tap.add_session("T6")
        self.tap.add_record("T6", claude_record("S6", "Q natif", "A natif"))
        self.baseline()
        self.drain(2)
        self.assertEqual(self.projects(), [])
        self.run_backfill()
        self.drain()
        self.drain(2)
        entries = self.store.list_entries(self.projects()[0]["id"])
        self.assertEqual(sorted(entry["body"] for entry in entries), ["A natif", "Q natif"])

    def test_native_only_history_is_replayed_and_old_mtime_guard_is_restored(self):
        path = self.native()
        self.baseline()
        import os
        os.utime(path, (1_000_000_000, 1_000_000_000))  # an old transcript
        self.run_backfill()
        self.drain()
        entries = self.store.list_entries(self.projects()[0]["id"])
        self.assertEqual(sorted(entry["body"] for entry in entries), ["A natif", "Q natif"])
        self.assertTrue(all("repli-natif" in entry["tags"] for entry in entries))
        self.assertGreater(self.state()["fallback"]["baselined_at"], 1_000_000_000)
        self.drain()
        self.assertEqual(len(self.store.list_entries(self.projects()[0]["id"])), 2)


class ReplayOrderTests(BackfillCase):
    def live_session(self, session="S9", tap_id="T9", turns=3, tap_first=True):
        path = write_claude_transcript(self.claude_root, session, self.folder_a, lines=0)
        append_jsonl(path, {"type": "system", "sessionId": session, "cwd": str(self.folder_a)})
        self.tap.add_session(tap_id)
        for n in range(turns):
            if not tap_first:
                append_jsonl(path, claude_line(session, self.folder_a, "user", f"q{n}", f"u{n}"), claude_line(session, self.folder_a, "assistant", [{"type": "text", "text": f"a{n}"}], f"v{n}"))
                self.capture.scan_once()
            self.tap.add_record(tap_id, claude_record(session, f"q{n}", f"a{n}"))
            if tap_first:
                append_jsonl(path, claude_line(session, self.folder_a, "user", f"q{n}", f"u{n}"), claude_line(session, self.folder_a, "assistant", [{"type": "text", "text": f"a{n}"}], f"v{n}"))
        self.drain(3)

    def test_live_tap_capture_is_not_duplicated_by_a_backfill_with_a_small_tap_budget(self):
        self.baseline()
        self.live_session()
        pid = self.projects()[0]["id"]
        live = self.texts(pid)
        self.assertEqual(len(live), 6)
        self.run_backfill()
        with patch.object(capture_module, "MAX_RECORDS_PER_CYCLE", 1):
            self.drain(10)
        self.assertEqual(self.texts(pid), live)
        self.assertEqual(self.state()["backfill"], {})

    def test_live_native_capture_is_not_duplicated_by_the_tap_replay(self):
        self.baseline()
        self.live_session(tap_first=False)
        pid = self.projects()[0]["id"]
        live = self.texts(pid)
        self.run_backfill()
        with patch.object(capture_module, "MAX_RECORDS_PER_CYCLE", 1):
            self.drain(10)
        self.assertEqual(self.texts(pid), live)

    def test_ledgers_are_not_capped_during_a_replay(self):
        self.configure(sources={"native_fallback": True})
        self.baseline()
        path = write_claude_transcript(self.claude_root, "S8", self.folder_a, lines=0)
        append_jsonl(path, {"type": "system", "sessionId": "S8", "cwd": str(self.folder_a)})
        self.tap.add_session("T8")
        for n in range(4):
            append_jsonl(path, claude_line("S8", self.folder_a, "user", f"q{n}", f"u{n}"), claude_line("S8", self.folder_a, "assistant", [{"type": "text", "text": f"a{n}"}], f"v{n}"))
            self.tap.add_record("T8", claude_record("S8", f"q{n}", f"a{n}"))
        # history: forget what live capture imported by starting from a never-captured state
        self.run_backfill()
        with patch.object(capture_module, "MAX_LEDGER_ITEMS", 2):
            self.drain(6)
        self.assertEqual(len(self.store.list_entries(self.projects()[0]["id"])), 8)
        self.assertGreaterEqual(self.state()["skipped"].get("fallback_tap_duplicate", 0), 8)


class RepeatedMessageTests(BackfillCase):
    """A message really sent twice must survive the cross-channel twin check, as with the live ledger."""

    def session(self, tap_turns, native_turns):
        path = write_claude_transcript(self.claude_root, "S7", self.folder_a, lines=0)
        append_jsonl(path, {"type": "system", "sessionId": "S7", "cwd": str(self.folder_a)})
        for n, text in enumerate(native_turns):
            append_jsonl(path, claude_line("S7", self.folder_a, "user", text, f"u{n}"), claude_line("S7", self.folder_a, "assistant", [{"type": "text", "text": f"a-{n}"}], f"v{n}"))
        self.tap.add_session("T7")
        for n, text in tap_turns:
            self.tap.add_record("T7", claude_record("S7", text, f"a-{n}"))

    def replay(self, tap_budget=1000):
        self.baseline()
        self.run_backfill()
        with patch.object(capture_module, "MAX_RECORDS_PER_CYCLE", tap_budget):
            self.drain(8)
        return self.texts(self.projects()[0]["id"])

    def test_a_repeat_that_tap_missed_is_kept(self):
        self.session([(0, "continue")], ["continue", "continue"])
        texts = self.replay()
        self.assertEqual(texts.count("continue"), 2)
        self.assertEqual(sorted(t for t in texts if t.startswith("a-")), ["a-0", "a-1"])

    def test_a_repeat_seen_by_both_channels_is_kept_twice(self):
        self.session([(0, "ok"), (1, "ok")], ["ok", "ok"])
        self.assertEqual(self.replay(tap_budget=1).count("ok"), 2)

    def test_a_live_tap_copy_is_not_consumed_twice(self):
        # "continue" once before the baseline (native only), then again live through both channels.
        path = write_claude_transcript(self.claude_root, "S7", self.folder_a, lines=0)
        append_jsonl(path, {"type": "system", "sessionId": "S7", "cwd": str(self.folder_a)},
                     claude_line("S7", self.folder_a, "user", "continue", "u0"), claude_line("S7", self.folder_a, "assistant", [{"type": "text", "text": "r0"}], "v0"))
        self.tap.add_session("T7")
        self.baseline()
        append_jsonl(path, claude_line("S7", self.folder_a, "user", "continue", "u1"), claude_line("S7", self.folder_a, "assistant", [{"type": "text", "text": "r1"}], "v1"))
        self.tap.add_record("T7", claude_record("S7", "continue", "r1"))
        self.drain(3)
        self.run_backfill()
        self.drain(6)
        self.assertEqual(self.texts(self.projects()[0]["id"]), ["continue", "continue", "r0", "r1"])
        self.assertEqual(self.state()["backfill"], {})

    def test_a_session_truncated_upstream_does_not_hold_the_native_replay(self):
        self.session([(0, "q0"), (1, "q1"), (2, "q2")], ["q0", "q1", "q2"])
        self.baseline()
        self.run_backfill()
        self.tap.connection.execute("DELETE FROM records WHERE session_id = 'T7' AND record_index > 1")
        self.drain(6)
        self.assertEqual(self.state()["backfill"], {})  # closed: the tap target followed the truncation
        self.assertEqual(sorted(t for t in self.texts(self.projects()[0]["id"]) if t.startswith("q")), ["q0", "q1", "q2"])


class SafetyTests(BackfillCase):
    def test_unreadable_tap_database_is_refused_not_skipped(self):
        self.history()
        self.baseline()
        before = self.capture._file("state.json").read_text(encoding="utf-8")
        with patch("filigree.tap_source.open_db", return_value=(None, "locked")):
            with self.assertRaises(backfill.BackfillError) as context:
                self.run_backfill()
            self.assertIn("claude-tap", str(context.exception))
            self.assertTrue(any("claude-tap" in item for item in backfill.plan(self.memory, env={})["blockers"]))
        self.assertEqual(self.capture._file("state.json").read_text(encoding="utf-8"), before)

    def test_pause_gaps_are_kept_and_a_corrupt_state_is_backed_up(self):
        self.history()
        self.baseline()
        state = json.loads(self.capture._file("state.json").read_text(encoding="utf-8"))
        state["fallback"]["gaps"] = {"x.jsonl": [[0, 10]]}
        self.capture._file("state.json").write_text(json.dumps(state), encoding="utf-8")
        self.run_backfill()
        self.assertEqual(self.state()["fallback"]["gaps"], {"x.jsonl": [[0, 10]]})
        self.capture._file("state.json").write_text("{pas du json", encoding="utf-8")
        self.run_backfill()
        self.assertTrue(list(self.capture._file("x").parent.glob("state.corrupt-*.json")))

    def test_many_unresolvable_transcripts_are_all_held_during_a_replay(self):
        self.baseline()
        for number in range(3):
            session = f"G{number}"
            path = write_claude_transcript(self.claude_root, session, self.root / "disparu", lines=0)
            append_jsonl(path, {"type": "system", "sessionId": session, "cwd": str(self.root / "disparu")}, claude_line(session, self.root / "disparu", "user", "texte", f"u{number}"))
        self.run_backfill()
        with patch.object(capture_module, "MAX_STALLED", 1):
            self.drain(4)
        self.assertEqual(len(self.state()["fallback"]["stalled"]), 3)
        self.assertEqual(self.state()["skipped"].get("fallback_held_overflow", 0), 0)


    def test_refuses_while_an_agent_or_capture_holds_a_lock(self):
        self.history()
        self.baseline()
        before = (self.capture._file("state.json")).read_text(encoding="utf-8")
        for path, word in ((self.memory / ".runtime" / "agent.lock", "agent"), (self.capture._file("capture.lock"), "capture")):
            holder = ProcessLock(path)
            self.assertTrue(holder.acquire())
            try:
                with self.assertRaises(backfill.BackfillError) as context:
                    self.run_backfill()
                self.assertIn(word, str(context.exception).lower())
                self.assertTrue(backfill.plan(self.memory, env={})["blockers"])
            finally:
                holder.release()
        self.assertEqual(self.capture._file("state.json").read_text(encoding="utf-8"), before)
        self.assertEqual(self.state()["backfill"], {})

    def test_refuses_while_capture_is_paused(self):
        self.history()
        self.baseline()
        self.capture.set_paused(True)
        with self.assertRaises(backfill.BackfillError):
            self.run_backfill()

    def test_dry_run_changes_nothing(self):
        self.history()
        self.baseline()
        snapshot = {path.relative_to(self.memory).as_posix(): path.read_bytes() for path in self.memory.rglob("*") if path.is_file()}
        report = backfill.plan(self.memory, env={})
        self.assertTrue(report["dry_run"])
        self.assertEqual((report["tap"]["sessions"], report["tap"]["records"]), (2, 2))
        self.assertEqual(report["native_fallback"]["transcripts"], 1)
        self.assertEqual(report["blockers"], [])
        self.assertEqual({path.relative_to(self.memory).as_posix(): path.read_bytes() for path in self.memory.rglob("*") if path.is_file()}, snapshot)

    def test_command_line_prints_json_and_fails_with_a_french_message(self):
        self.history()
        self.baseline()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["--data-dir", str(self.memory), "backfill", "--dry-run"])
        self.assertTrue(json.loads(out.getvalue())["dry_run"])
        holder = ProcessLock(self.memory / ".runtime" / "agent.lock")
        holder.acquire()
        self.addCleanup(holder.release)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as context:
            cli.main(["--data-dir", str(self.memory), "backfill"])
        self.assertEqual(context.exception.code, 1)
        self.assertIn("arrêtez-le", err.getvalue())


class FlushCapTests(BackfillCase):
    def test_flush_sends_again_what_the_store_did_not_process(self):
        self.configure(sources={"native_fallback": False})
        self.history(turns=4)  # 8 visible items
        self.baseline()
        self.run_backfill()
        with patch.object(Store, "IMPORT_MAX_NEW_EVENTS", 3):
            self.capture.scan_once()
        entries = self.store.list_entries(self.projects()[0]["id"])
        self.assertEqual(len(entries), 8)
        self.assertEqual(self.state()["skipped"].get("import_stalled", 0), 0)


class ActivityBackfillTests(unittest.TestCase):
    def test_observer_replays_a_pre_baseline_transcript_and_writes_the_sheet(self):
        import tempfile
        with tempfile.TemporaryDirectory() as name:
            base = Path(name).resolve()
            store = Store(base / "memory")
            work = base / "work" / "app"
            work.mkdir(parents=True)
            claude = base / "claude"
            (claude / "projects" / "-w").mkdir(parents=True)
            env = {"CLAUDE_CONFIG_DIR": str(claude), "CODEX_HOME": str(base / "codex")}
            pid = store.create_project("App", folder=str(work))["id"]
            collectors = [ClaudeCodeCollector(env, base), CodexRolloutCollector(env, base)]
            settings = capture_module.default_settings()
            observer = Observer(store, env=env, home=base, collectors=collectors, settings_loader=lambda: settings)
            path = claude / "projects" / "-w" / "S1.jsonl"
            rows = [{"type": "user", "sessionId": "S1", "cwd": str(work), "uuid": "u1", "timestamp": "2020-01-01T10:00:00Z", "message": {"role": "user", "content": "historique ancien"}},
                    {"type": "assistant", "sessionId": "S1", "cwd": str(work), "uuid": "u2", "timestamp": "2020-01-01T10:01:00Z", "message": {"role": "assistant", "content": [{"type": "text", "text": "réponse ancienne"}]}}]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            observer.scan_once()
            self.assertEqual(ActivityLog(journal_path(store, pid)).stats()["events"], 0)  # D11
            plan = backfill.plan(store.root, env=env, home=base, collectors=collectors)
            self.assertEqual(plan["activity"]["transcripts"], 1)
            backfill.rewind(store.root, env=env, home=base, collectors=collectors)
            first = observer.scan_once()
            self.assertEqual(first["events"], 2)
            log = ActivityLog(journal_path(store, pid))
            self.assertEqual({event["summary"] for event in log.events()}, {"historique ancien", "réponse ancienne"})
            self.assertEqual(first["distilled"], 1)
            self.assertTrue(any("fiche-session" in entry["tags"] for entry in store.list_entries(pid)))
            backfill.rewind(store.root, env=env, home=base, collectors=collectors)
            observer.scan_once()
            self.assertEqual(log.stats()["events"], 2)  # stable ids: no duplicate


if __name__ == "__main__":
    unittest.main()
