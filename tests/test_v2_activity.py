"""Activity journal, deterministic extraction and session sheets (ADR-0003). Synthetic data only."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from filigree import capture as capture_module
from filigree.activity import ActivityLog, Observer, journal_path
from filigree.collectors.claude_code import ClaudeCodeCollector
from filigree.collectors.codex_rollout import CodexRolloutCollector
from filigree.distill import SHEET_URI, distill_project
from filigree.extract import Extractor, extract_line, summarize
from filigree.git_sync import _memory_file
from filigree.store import Store


def claude_row(session, cwd, role, content, uuid, ts="2026-10-17T10:00:00Z"):
    return {"type": role, "sessionId": session, "cwd": str(cwd), "uuid": uuid, "timestamp": ts, "message": {"role": role, "content": content}}


class ExtractionTests(unittest.TestCase):
    def lines(self, *records, source="claude"):
        extractor, out = Extractor(), []
        for record in records:
            events, element, _ = extract_line(extractor, source, json.dumps(record).encode())
            out += [(element, event) for event in events]
        return out

    def test_kinds_files_tests_and_commits(self):
        found = self.lines(
            claude_row("S", "/w", "user", "Ajoute un cache", "u1"),
            claude_row("S", "/w", "assistant", [{"type": "thinking", "thinking": "secret reasoning"}, {"type": "text", "text": "Je modifie app.py"},
                                               {"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "/w/app.py", "old_string": "a", "new_string": "b"}},
                                               {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "TOKEN=abc python -m pytest tests -k secret_arg"}},
                                               {"type": "tool_use", "id": "t3", "name": "Bash", "input": {"command": "git commit -m 'message privé'"}}], "u2"),
            claude_row("S", "/w", "user", [{"type": "tool_result", "tool_use_id": "t2", "content": "1 failed, 3 passed"}], "u3"),
        )
        kinds = [event["kind"] for _, event in found]
        self.assertEqual(kinds, ["user_prompt", "assistant_text", "file_change", "command", "commit", "test_result"])
        self.assertEqual(found[2][1]["files"], ["/w/app.py"])
        dump = json.dumps(found)
        for private in ("secret reasoning", "secret_arg", "message privé", "abc"):
            self.assertNotIn(private, dump)
        self.assertEqual(found[3][1]["summary"], "tests · python")
        self.assertTrue(found[5][1]["summary"].startswith("échec"))
        self.assertEqual({element for element, _ in found}, {"u1", "u2", "u3"})

    def test_summary_is_redacted_before_the_cut(self):
        secret = "sk-ant-" + "A" * 60
        text = "x" * 270 + " " + secret
        summary = summarize(text)
        self.assertLessEqual(len(summary), 280)
        self.assertNotIn("sk-ant-AAAA", summary)
        self.assertNotIn(secret[:20], summarize(secret + " fin"))

    def test_injected_blocks_and_meta_rows_are_excluded(self):
        found = self.lines({**claude_row("S", "/w", "user", "<system-reminder>interne</system-reminder>", "u1")}, {**claude_row("S", "/w", "user", "méta", "u2"), "isMeta": True})
        self.assertEqual(found, [])

    def test_codex_shell_output_exit_code_and_patch_files(self):
        found = self.lines(
            {"type": "response_item", "payload": {"type": "function_call", "name": "shell", "call_id": "c1", "arguments": json.dumps({"command": ["npm", "test"]})}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": json.dumps({"output": "ok", "metadata": {"exit_code": 1}})}},
            {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "apply_patch", "call_id": "c2", "input": "*** Begin Patch\n*** Update File: src/a.py\n*** Add File: src/b.py\n"}},
            {"type": "response_item", "payload": {"type": "reasoning", "summary": [{"text": "privé"}]}},
            source="codex")
        self.assertEqual([event["kind"] for _, event in found], ["command", "test_result", "file_change"])
        self.assertTrue(found[1][1]["summary"].startswith("échec"))
        self.assertEqual(found[2][1]["files"], ["src/a.py", "src/b.py"])


class ObserverCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.store = Store(self.base / "memory")
        self.work = self.base / "work" / "app"
        self.work.mkdir(parents=True)
        self.claude = self.base / "claude"
        (self.claude / "projects" / "-w").mkdir(parents=True)
        self.env = {"CLAUDE_CONFIG_DIR": str(self.claude), "CODEX_HOME": str(self.base / "codex")}
        self.settings = capture_module.default_settings()
        self.observer = Observer(self.store, env=self.env, home=self.base, collectors=[ClaudeCodeCollector(self.env, self.base), CodexRolloutCollector(self.env, self.base)],
                                 settings_loader=lambda: self.settings)

    def transcript(self, session, rows, cwd=None, append=False):
        path = self.claude / "projects" / "-w" / f"{session}.jsonl"
        with open(path, "a" if append else "w", encoding="utf-8") as handle:
            for number, (role, content) in enumerate(rows):
                handle.write(json.dumps(claude_row(session, cwd or self.work, role, content, f"{session}-{len(path.read_text(encoding='utf-8').splitlines()) if path.exists() else 0}-{number}",
                                                   datetime.now(timezone.utc).isoformat(timespec="seconds"))) + "\n")
        return path


class ObserverTests(ObserverCase):
    def test_baseline_then_new_lines_only_and_no_duplicates(self):
        pid = self.store.create_project("App", folder=str(self.work))["id"]
        path = self.transcript("S1", [("user", "historique ancien")])
        path.write_text(path.read_text(encoding="utf-8").replace(datetime.now(timezone.utc).isoformat(timespec="seconds")[:4], "2020", 1), encoding="utf-8")
        first = self.observer.scan_once()
        self.assertEqual(first["events"], 0)  # D11: no automatic catch-up
        self.transcript("S1", [("user", "nouvelle demande"), ("assistant", "réponse")], append=True)
        self.transcript("S2", [("user", "session née après la ligne de base")])
        second = self.observer.scan_once()
        self.assertEqual(second["events"], 3)
        log = ActivityLog(journal_path(self.store, pid))
        summaries = {event["summary"] for event in log.events()}
        self.assertEqual(summaries, {"nouvelle demande", "réponse", "session née après la ligne de base"})
        state = json.loads((self.store.root / ".capture" / "activity-state.json").read_text(encoding="utf-8"))
        state["files"] = {key: {"offset": 0} for key in state["files"]}  # replay everything: stable ids dedupe
        (self.store.root / ".capture" / "activity-state.json").write_text(json.dumps(state), encoding="utf-8")
        self.observer.scan_once()
        self.assertEqual(log.stats()["events"], 3)  # replay: no duplicate, and the pre-baseline history is still not caught up
        self.assertNotIn("historique ancien", {event["summary"] for event in log.events()})

    def test_no_project_and_outside_roots_never_create_or_journal(self):
        self.observer.scan_once()
        self.transcript("S1", [("user", "aucun projet")])
        self.assertEqual(self.observer.scan_once()["skipped"], {"no_project": 1})
        self.assertEqual(self.store.list_projects(), [])
        pid = self.store.create_project("App", folder=str(self.work))["id"]
        self.settings["allowed_roots"] = [str(self.base / "ailleurs")]
        self.transcript("S1", [("user", "hors racine")], append=True)
        self.observer.scan_once()
        self.assertFalse(journal_path(self.store, pid).exists())

    def test_disabled_paused_and_journal_stays_out_of_git_memory(self):
        pid = self.store.create_project("App", folder=str(self.work))["id"]
        self.observer.scan_once()
        self.settings["activity"]["enabled"] = False
        self.transcript("S1", [("user", "désactivé")])
        self.assertFalse(self.observer.scan_once()["enabled"])
        self.settings["activity"]["enabled"] = True
        self.settings["paused"] = [pid]
        self.observer.scan_once()
        self.assertFalse(journal_path(self.store, pid).exists())
        self.assertFalse(_memory_file(".filigree/activity.sqlite"))
        self.assertNotIn("activity", self.store.export_markdown(pid))

    def test_overlaps_and_active_sessions(self):
        pid = self.store.create_project("App", folder=str(self.work))["id"]
        self.observer.scan_once()
        edit = lambda uid: [("assistant", [{"type": "tool_use", "id": uid, "name": "Write", "input": {"file_path": str(self.work / "shared.py"), "content": "x"}}])]
        self.transcript("S1", edit("a"))
        self.transcript("S2", edit("b"))
        self.observer.scan_once()
        log = ActivityLog(journal_path(self.store, pid))
        self.assertEqual(len(log.sessions(active_minutes=5)), 2)
        overlaps = log.overlaps()
        self.assertEqual(len(overlaps), 1)
        self.assertEqual(len(overlaps[0]["sessions"]), 2)

    def test_retention_purge(self):
        pid = self.store.create_project("App", folder=str(self.work))["id"]
        log = ActivityLog(journal_path(self.store, pid))
        old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat(timespec="seconds")
        log.add({"session_key": "claude:x:S", "client": "claude"}, [{"event_id": "e1", "kind": "user_prompt", "ts_observed": old, "summary": "vieux"}])
        self.assertEqual(log.purge(90), 1)
        self.assertEqual(log.stats(), {"events": 0, "sessions": 0})

    def test_newer_schema_is_refused(self):
        path = self.base / "j.sqlite"
        sqlite3.connect(path).execute("PRAGMA user_version=9").connection.close()
        with self.assertRaises(ValueError):
            ActivityLog(path).events()

    def test_malformed_activity_settings_disable_capture(self):
        for bad in ({"activity": []}, {"activity": {"retention_days": 0}}, {"activity": {"enabled": "oui"}}, {"activity": {"inconnu": True}}):
            settings, error = capture_module.normalize_settings(bad)
            self.assertFalse(settings["enabled"], bad)
            self.assertIn("activity", error)


class DistillTests(ObserverCase):
    def run_session(self, pid):
        self.observer.scan_once()
        self.transcript("S1", [("user", "Corrige le bug d'export"), ("assistant", [{"type": "tool_use", "id": "a", "name": "Edit", "input": {"file_path": str(self.work / "export.py")}}])])
        self.observer.scan_once()
        return ActivityLog(journal_path(self.store, pid))

    def test_sheet_waits_for_idle_then_is_revised_while_proposed(self):
        pid = self.store.create_project("App", folder=str(self.work))["id"]
        self.run_session(pid)
        sheets = {}
        self.assertEqual(distill_project(self.store, pid, sheets), 0)  # still active
        later = datetime.now(timezone.utc) + timedelta(minutes=11)
        self.assertEqual(distill_project(self.store, pid, sheets, now=later), 1)
        entries = [entry for entry in self.store.list_entries(pid) if "fiche-session" in entry["tags"]]
        self.assertEqual(len(entries), 1)
        sheet = entries[0]
        self.assertEqual(sheet["status"], "proposed")
        self.assertIn("export.py", sheet["body"])
        self.assertTrue(sheet["sources"][0]["uri"].startswith(SHEET_URI))
        self.assertEqual(distill_project(self.store, pid, sheets, now=later), 0)  # nothing new: no rewrite
        self.transcript("S1", [("user", "Ajoute un test")], append=True)
        self.observer.scan_once()
        distill_project(self.store, pid, sheets, now=later + timedelta(minutes=11))
        entries = [entry for entry in self.store.list_entries(pid) if "fiche-session" in entry["tags"]]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["revision"], 2)
        self.assertIn("Ajoute un test", entries[0]["body"])

    def test_reviewed_sheet_is_never_rewritten_and_gets_a_suite(self):
        pid = self.store.create_project("App", folder=str(self.work))["id"]
        self.run_session(pid)
        sheets = {}
        later = datetime.now(timezone.utc) + timedelta(minutes=11)
        distill_project(self.store, pid, sheets, now=later)
        sheet = next(entry for entry in self.store.list_entries(pid) if "fiche-session" in entry["tags"])
        self.store.update_entry(pid, sheet["id"], {"status": "accepted", "revision": sheet["revision"]}, channel="http-ui")
        self.transcript("S1", [("user", "Encore une chose")], append=True)
        self.observer.scan_once()
        distill_project(self.store, pid, sheets, now=later + timedelta(minutes=11))
        sheets_now = [entry for entry in self.store.list_entries(pid) if "fiche-session" in entry["tags"]]
        self.assertEqual(len(sheets_now), 2)
        accepted = next(entry for entry in sheets_now if entry["id"] == sheet["id"])
        self.assertEqual(accepted["revision"], sheet["revision"] + 1)  # only the human acceptance
        suite = next(entry for entry in sheets_now if entry["id"] != sheet["id"])
        self.assertEqual(suite["status"], "proposed")
        self.assertIn("suite 1", suite["title"])

    def test_session_end_signal_triggers_the_sheet_without_waiting(self):
        pid = self.store.create_project("App", folder=str(self.work))["id"]
        self.run_session(pid)
        signals = self.store.root / ".runtime" / "signals.jsonl"
        signals.parent.mkdir(parents=True, exist_ok=True)
        signals.write_text(json.dumps({"client": "claude", "session_id": "S1", "event": "session_end"}) + "\n", encoding="utf-8")
        result = self.observer.scan_once()
        self.assertEqual(result["distilled"], 1)


if __name__ == "__main__":
    unittest.main()
