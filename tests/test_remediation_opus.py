"""Regressions for the Opus risk review of the remediation cycle (R1-R9; R4 as a documented disposition).

Everything is synthetic: temporary memory roots, explicit empty capture sources, no live client and no real
claude-tap or transcript folder is read."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

try:
    from tap_fixtures import append_jsonl, write_claude_transcript
    from test_remediation_capture import Synthetic
    from test_remediation_services import ServerCase, isolated_env, synthetic_capture_env
except ImportError:  # run as tests.test_remediation_opus from the repository root
    from tests.tap_fixtures import append_jsonl, write_claude_transcript
    from tests.test_remediation_capture import Synthetic
    from tests.test_remediation_services import ServerCase, isolated_env, synthetic_capture_env

from filigree import capture as capture_module
from filigree import importers, mcp, server
from filigree.capture import Capture
from filigree.store import Store

REPO = Path(__file__).resolve().parent.parent
TOKEN_HEAD = "sk-ant-"
TOKEN = TOKEN_HEAD + "B" * 30


def everything(store: Store, project_id: str) -> str:
    """All persisted files, plus the export and handoff views, as one searchable string."""
    parts = [path.read_text(encoding="utf-8") for path in store.root.rglob("*") if path.is_file() and path.suffix in {".md", ".json"}]
    parts.append(store.export_markdown(project_id))
    parts.append(store.handoff(project_id, "", 100000)["text"])
    parts.append(json.dumps(store.list_events(project_id)))
    return "\n".join(parts)


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        (self.base / "work").mkdir()
        self.store = Store(self.base / "memory")
        self.pid = self.store.create_project("P", "", folder=str(self.base / "work"))["id"]

    def entry(self, **fields):
        data = {"title": "Choix SQLite", "body": "Base embarquée", "kind": "decision", "status": "accepted"}
        data.update(fields)
        return self.store.create_entry(self.pid, data)

    def entry_file(self, entry_id):
        return self.store.root / "projects" / self.pid / ".filigree" / "entries" / (entry_id + ".md")

    def history_dir(self, entry_id):
        return self.store.root / "projects" / self.pid / ".filigree" / "history" / entry_id


class McpSearchTests(StoreCase):
    def test_r1_zero_lexical_hits_still_report_the_memory_inventory(self):
        self.entry(body="Nous utilisons SQLite")
        result = mcp.call_tool(self.store, "search_memory", {"project_id": self.pid, "query": "database"})
        self.assertIsInstance(result, dict)
        self.assertEqual(result["entries"], [])
        self.assertEqual((result["matched"], result["total"]), (0, 1))
        self.assertEqual(result["by_status"]["accepted"], 1)
        self.assertIn("1", result["note"])
        self.assertTrue(result["note"])

    def test_r1_a_hit_keeps_entries_and_has_no_note(self):
        self.entry(body="Nous utilisons SQLite")
        result = mcp.call_tool(self.store, "search_memory", {"project_id": self.pid, "query": "sqlite"})
        self.assertEqual((result["matched"], len(result["entries"]), result["note"]), (1, 1, ""))


class RedactBeforeTruncationTests(StoreCase):
    def assertClean(self, label):
        text = everything(self.store, self.pid)
        # assertFalse, not assertNotIn: a failure must not print the whole memory.
        self.assertFalse(TOKEN_HEAD in text, f"token head survives: {label}")
        self.assertFalse("BBBBBBBB" in text, f"token body survives: {label}")

    def test_r2_tap_events_redact_the_whole_text_before_cutting_title_and_excerpt(self):
        capture = Capture(self.store, env={})
        for title_pad, excerpt_pad in ((120, 3831), (125, 3830), (129, 3825)):
            text = "a" * title_pad + " " + TOKEN + "\n" + "c" * excerpt_pad + " " + TOKEN
            events = capture._events({}, {"mode": "native", "evidence": {}, "native_id": "n1"}, "db", "session-0001", "claude", 0, "2026-01-01T00:00:00Z", "digest",
                                     [{"kind": "tool_call", "name": "Bash", "text": text}], [])
            self.store.import_events(self.pid, events, "claude-tap", internal=True)
            self.assertClean((title_pad, excerpt_pad))

    def test_r2_importers_redact_before_cutting(self):
        for pad in (100, 120, 150):
            text = "x" * pad + " " + TOKEN + "\n" + "c" * 3960 + " " + TOKEN
            for events in (importers.parse_text(text, "note"), importers.parse_import(json.dumps({"body": text, "title": "t"}), "f"),
                           importers.parse_import(json.dumps([{"type": "user", "message": {"role": "user", "content": text}}]), "f")):
                self.store.import_events(self.pid, events, "note")
                self.assertClean(pad)

    def test_r2_secret_crossing_the_body_limit_is_redacted(self):
        keep = Store.BODY_LIMIT - 120
        text = "z" * (keep - 10) + " " + TOKEN + " " + "y" * 400
        result = self.store.import_events(self.pid, [{"body": text, "title": "long"}], "note")
        self.assertEqual(result["truncated"], 1)
        self.assertClean("body limit")

    def test_r2_redaction_counter_survives_pre_redaction(self):
        capture = Capture(self.store, env={})
        events = capture._events({}, {"mode": "native", "evidence": {}, "native_id": "n1"}, "db", "session-0001", "claude", 0, "", "digest",
                                 [{"kind": "user_text", "text": "voici " + TOKEN}], [])
        result = self.store.import_events(self.pid, events, "claude-tap", internal=True)
        self.assertGreaterEqual(result["redactions"], 1)

    def test_r2_a_client_cannot_inflate_the_counter_through_a_plain_import(self):
        # Only trusted (internal) capture code may report redactions it already applied.
        result = self.store.import_events(self.pid, [{"body": "texte", "pre_redactions": 500}], "note")
        self.assertEqual(result["redactions"], 0)


class NativeBoundaryTests(Synthetic):
    def test_r2_native_fallback_does_not_persist_a_cut_secret(self):
        pid = self.project(self.folder_a)
        self.baseline()
        text = "a" * 120 + " " + TOKEN + "\n" + "c" * 3831 + " " + TOKEN
        append_jsonl(write_claude_transcript(self.claude_root, "sb", self.folder_a, lines=0), self.native_row("sb", self.folder_a, text, "u1"))
        self.capture.scan_once()
        self.assertEqual(len(self.store.list_entries(pid)), 1)
        persisted = everything(self.store, pid)
        self.assertFalse(TOKEN_HEAD in persisted)
        self.assertGreaterEqual(self.state()["counters"].get("redactions", 0), 1)


class HeuristicGapTests(StoreCase):
    def test_r6_multi_word_yaml_value_is_masked_to_the_end_of_the_line(self):
        from filigree.store import redact
        clean, count = redact("db:\n  password: my secret phrase\nnext: ok\n- passphrase = trois mots ici\n")
        self.assertFalse("secret phrase" in clean or "trois mots" in clean)
        self.assertIn("next: ok", clean)
        self.assertGreaterEqual(count, 2)

    def test_r6_ordinary_prose_about_passwords_is_left_alone(self):
        from filigree.store import redact
        prose = "The password policy is documented in the wiki.\nRotate the secret every quarter, and never reuse a password."
        self.assertEqual(redact(prose), (prose, 0))

    def test_r6_documented_limits_remain(self):
        # Heuristic limits (see README "Redaction limits"): not guarantees, asserted so a change is deliberate.
        from filigree.store import redact
        self.assertNotIn("ss@h", redact("postgres://u:pa/ss@h")[0])  # a raw "/" in userinfo is malformed (RFC 3986) but now masked (privacy retake)
        self.assertNotIn("pa%2Fss", redact("postgres://u:pa%2Fss@h")[0])

    def test_r6_git_checkpoint_message_is_redacted(self):
        import shutil
        from filigree import git_sync
        if not shutil.which("git"):
            self.skipTest("git unavailable")
        path = self.store.root / "projects" / self.pid
        git_sync.operate(path, "init")
        for key, value in (("user.name", "Test Runner"), ("user.email", "test@example.invalid")):
            subprocess.run(["git", "-C", str(path), "config", key, value], check=True, capture_output=True)
        self.entry()
        git_sync.operate(path, "checkpoint", "docs: save password=hunter2secret and " + TOKEN)
        log = subprocess.run(["git", "-C", str(path), "log", "-1", "--format=%B"], check=True, capture_output=True, text=True, encoding="utf-8").stdout
        self.assertFalse("hunter2secret" in log or TOKEN_HEAD in log)
        self.assertIn("[REDACTED]", log)


class HistoryIntegrityTests(StoreCase):
    def three_revisions(self):
        entry = self.entry()
        entry = self.store.update_entry(self.pid, entry["id"], {"body": "deux", "revision": 1})
        return self.store.update_entry(self.pid, entry["id"], {"body": "trois", "revision": 2})

    def test_r3_healthy_history_is_listed(self):
        entry = self.three_revisions()
        self.assertEqual([item["revision"] for item in self.store.list_history(self.pid, entry["id"])], [3, 2, 1])

    def test_r3_a_deleted_revision_is_reported_and_healthy_entries_stay_usable(self):
        other = self.entry(title="Autre")
        entry = self.three_revisions()
        (self.history_dir(entry["id"]) / "2.md").unlink()
        with self.assertRaises(ValueError) as caught:
            self.store.list_history(self.pid, entry["id"])
        self.assertIn("2", str(caught.exception))
        self.assertIn("manquant", str(caught.exception))
        self.assertEqual(len(self.store.list_entries(self.pid)), 2)
        self.assertEqual(len(self.store.list_history(self.pid, other["id"])), 1)

    def test_r3_current_revision_without_its_snapshot_is_reported(self):
        entry = self.three_revisions()
        (self.history_dir(entry["id"]) / "3.md").unlink()
        with self.assertRaises(ValueError):
            self.store.list_history(self.pid, entry["id"])

    def test_r3_an_external_edit_at_the_same_revision_is_a_mismatch_not_a_silent_overwrite(self):
        entry = self.entry(body="avant externe")
        path = self.entry_file(entry["id"])
        path.write_text(path.read_text(encoding="utf-8").replace("avant externe", "après externe"), encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            self.store.list_history(self.pid, entry["id"])
        self.assertIn("modifi", str(caught.exception))
        # The external correction is still what the entry shows; nothing was rewritten or discarded.
        self.assertEqual(self.store.list_entries(self.pid)[0]["body"], "après externe")
        self.assertIn("après externe", path.read_text(encoding="utf-8"))

    def test_r9_history_of_a_quarantined_entry_names_the_quarantine(self):
        entry = self.entry()
        self.entry_file(entry["id"]).write_text("not a filigree file", encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            self.store.list_history(self.pid, entry["id"])
        self.assertIn("quarantaine", str(caught.exception))


class OmittedFilesAreReportedTests(StoreCase):
    def test_r9_a_corrupt_event_is_reported_in_diagnostics_and_handoff(self):
        entry = self.entry()
        self.store.update_entry(self.pid, entry["id"], {"body": "x", "revision": 1, "reason": "raison de revue"})
        events = self.store.root / "projects" / self.pid / ".filigree" / "events"
        (events / "00000000-0000-4000-8000-000000000000.json").write_text("{broken", encoding="utf-8")
        problems = self.store.event_diagnostics(self.pid)
        self.assertEqual(len(problems), 1)
        self.assertIn("00000000-0000-4000-8000-000000000000.json", problems[0]["file"])
        handoff = self.store.handoff(self.pid)
        self.assertEqual(handoff["event_diagnostics"], 1)
        self.assertIn("unreadable event file", handoff["text"])
        self.assertIn("raison de revue", handoff["text"])
        self.assertEqual(len(self.store.list_events(self.pid)), 2)


class CacheRevalidationTests(StoreCase):
    def rewrite_same_size_and_mtime(self, path, old, new):
        status = path.stat()
        path.write_bytes(path.read_bytes().replace(old.encode(), new.encode()))  # bytes: no newline translation
        os.utime(path, ns=(status.st_atime_ns, status.st_mtime_ns))
        self.assertEqual(path.stat().st_size, status.st_size)

    def test_r7_a_fresh_file_edited_in_place_is_noticed(self):
        entry = self.entry()
        self.assertEqual(self.store.list_entries(self.pid)[0]["status"], "accepted")
        self.rewrite_same_size_and_mtime(self.entry_file(entry["id"]), '"accepted"', '"rejected"')
        self.assertEqual(self.store.list_entries(self.pid)[0]["status"], "rejected")

    def test_r7_a_settled_file_edited_in_place_is_noticed_after_revalidation(self):
        entry = self.entry()
        path = self.entry_file(entry["id"])
        old = time.time() - 3600
        os.utime(path, (old, old))
        self.store.CACHE_REVALIDATE_SECONDS = 0
        self.assertEqual(self.store.list_entries(self.pid)[0]["status"], "accepted")
        self.rewrite_same_size_and_mtime(path, '"accepted"', '"rejected"')
        self.assertEqual(self.store.list_entries(self.pid)[0]["status"], "rejected")

    def test_r7_unchanged_settled_files_are_not_parsed_again_within_the_interval(self):
        entry = self.entry()
        old = time.time() - 3600
        os.utime(self.entry_file(entry["id"]), (old, old))
        self.store.list_entries(self.pid)
        with patch.object(Store, "_load_entry", side_effect=AssertionError("parsed again")):
            for _ in range(3):
                self.assertEqual(len(self.store.list_entries(self.pid)), 1)


class SupersessionRecoveryTests(StoreCase):
    def setup_chain(self):
        a = self.entry(title="Choix A")
        b = self.entry(title="Choix B", relations=[{"target": a["id"], "type": "supersedes"}])
        return a, b

    def test_r8_rejecting_an_accepted_replacement_explains_the_recovery_path(self):
        a, b = self.setup_chain()
        with self.assertRaises(ValueError) as caught:
            self.store.update_entry(self.pid, b["id"], {"status": "rejected", "revision": 1})
        message = str(caught.exception)
        self.assertIn("supersedes", message)
        self.assertNotIn("Only an accepted entry may supersede", message)

    def test_r8_reactivating_a_superseded_entry_names_the_new_accepted_decision(self):
        a, b = self.setup_chain()
        with self.assertRaises(ValueError) as caught:
            self.store.update_entry(self.pid, a["id"], {"status": "accepted", "revision": 2})
        self.assertIn("accept", str(caught.exception).lower())
        self.assertIn("supersedes", str(caught.exception))

    def test_r8_a_new_accepted_decision_restores_the_earlier_choice_without_resurrection(self):
        a, b = self.setup_chain()
        c = self.entry(title="Retour au choix A", relations=[{"target": b["id"], "type": "supersedes"}, {"target": a["id"], "type": "relates_to"}])
        by_id = {entry["id"]: entry for entry in self.store.list_entries(self.pid)}
        self.assertEqual((by_id[a["id"]]["status"], by_id[b["id"]]["status"], by_id[c["id"]]["status"]), ("superseded", "superseded", "accepted"))
        self.assertEqual([item["revision"] for item in self.store.list_history(self.pid, a["id"])], [2, 1])
        self.assertEqual([item["revision"] for item in self.store.list_history(self.pid, b["id"])], [2, 1])
        text = self.store.handoff(self.pid)["text"]
        current = text.split("## Historical alternatives")[0]
        self.assertIn("Retour au choix A", current)
        self.assertNotIn("Choix B (", current.split("Retour au choix A")[0] + current.split("Retour au choix A")[1].split("###")[0])


class ChannelAndClaimsTests(StoreCase):
    def test_r4_mcp_proposals_carry_a_server_set_channel_even_with_a_human_looking_label(self):
        result = mcp.call_tool(self.store, "propose_memory", {"project_id": self.pid, "title": "t", "body": "b", "source_label": "s", "agent": "Human (approved)"})
        self.assertEqual(result["channel"], "mcp")
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["agent"], "Human (approved)")  # a declared label only

    def test_r4_mcp_cannot_supply_a_channel(self):
        with self.assertRaises(ValueError):
            mcp.call_tool(self.store, "propose_memory", {"project_id": self.pid, "title": "t", "body": "b", "source_label": "s", "channel": "http-ui"})

    def test_r4_store_rejects_a_client_supplied_channel(self):
        with self.assertRaises(ValueError):
            self.store.create_entry(self.pid, {"title": "t", "body": "b", "channel": "mcp"})
        entry = self.entry()
        with self.assertRaises(ValueError):
            self.store.update_entry(self.pid, entry["id"], {"channel": "mcp", "revision": 1})

    def test_r4_imports_and_capture_are_stamped_by_the_server(self):
        imported = self.store.import_events(self.pid, [{"body": "a", "channel": "http-ui"}], "note")["entries"][0]
        captured = self.store.import_events(self.pid, [{"body": "b", "channel": "http-ui"}], "claude-tap", internal=True)["entries"][0]
        self.assertEqual((imported["channel"], captured["channel"]), ("import", "capture"))

    def test_r4_status_change_events_record_the_channel(self):
        entry = self.entry(status="proposed")
        self.store.update_entry(self.pid, entry["id"], {"status": "accepted", "revision": 1}, channel="http-ui")
        self.assertEqual(self.store.list_events(self.pid)[0]["channel"], "http-ui")

    def test_r4_legacy_entries_without_a_channel_still_load(self):
        entry = self.entry()
        path = self.entry_file(entry["id"])
        text = path.read_text(encoding="utf-8")
        legacy = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith('"channel"'))
        path.write_text(legacy + "\n", encoding="utf-8")
        self.assertEqual(len(self.store.list_entries(self.pid)), 1)

    def test_r4_handoff_does_not_claim_authenticated_human_approval(self):
        self.entry()
        text = self.store.handoff(self.pid)["text"]
        self.assertNotIn("human-approved", text)
        self.assertIn("not authenticated", text)
        self.assertIn("Origin: ", text)


class HttpChannelTests(ServerCase):
    capture_enabled = False

    def test_r4_http_cannot_override_the_channel_and_stamps_http_ui(self):
        code, project, _ = self.request("POST", "/api/projects", {"name": "P", "folder": str(self.folder)})
        self.assertEqual(code, 201)
        path = f"/api/projects/{project['id']}/entries"
        code, _, _ = self.request("POST", path, {"title": "t", "body": "b", "channel": "mcp"})
        self.assertEqual(code, 400)
        code, entry, _ = self.request("POST", path, {"title": "t", "body": "b"})
        self.assertEqual((code, entry["channel"]), (201, "http-ui"))
        code, _, _ = self.request("PATCH", f"{path}/{entry['id']}", {"channel": "mcp", "revision": 1})
        self.assertEqual(code, 400)
        code, imported, _ = self.request("POST", f"/api/projects/{project['id']}/import", {"text": "une note", "format": "text", "source": "n"})
        self.assertEqual(code, 200)
        self.assertEqual(imported["entries"][0]["channel"], "import")


class ExternalMonitorTests(ServerCase):
    capture_enabled = False
    HOLDER = ("import sys,time,pathlib;sys.path.insert(0,sys.argv[1]);from filigree.capture import ProcessLock;"
              "d=pathlib.Path(sys.argv[2]);l=ProcessLock(d/'capture.lock');assert l.acquire();print('held',flush=True)\n"
              "end=time.time()+60\n"
              "while time.time()<end and not (d/'stop').exists(): time.sleep(0.05)\n"
              "l.release()\n")

    def hold(self):
        directory = self.store.root / ".capture"
        directory.mkdir(exist_ok=True)
        process = subprocess.Popen([sys.executable, "-I", "-c", self.HOLDER, str(REPO), str(directory)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   env=isolated_env(self.base))
        self.addCleanup(lambda: (process.kill(), process.wait(), process.stdout.close(), process.stderr.close()) if process.poll() is None else (process.stdout.close(), process.stderr.close()))
        self.assertEqual(process.stdout.readline().strip(), "held")
        return process

    def tripwires(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("a capture source was touched on a --no-capture server")
        targets = ["filigree.capture.Capture.__init__", "filigree.capture.Capture.scan_once", "filigree.capture.tap_source.probe", "filigree.capture.tap_source.resolve_db_path",
                   "filigree.capture.native_index.default_roots", "filigree.capture.native_index.NativeIndex", "filigree.tap_source.probe"]
        guards = [patch(target, side_effect=forbidden).start() for target in targets]
        self.addCleanup(patch.stopall)
        return guards

    def test_r5_status_reports_an_external_monitor_without_touching_any_source(self):
        guards = self.tripwires()
        code, status, _ = self.request("GET", "/api/capture")
        self.assertEqual((code, status["running"], status["external_monitor_running"]), (200, False, False))
        self.assertFalse((self.store.root / ".capture").exists())
        self.hold()
        code, status, _ = self.request("GET", "/api/capture")
        self.assertTrue(status["disabled_by_server"])
        self.assertTrue(status["external_monitor_running"])
        self.assertTrue(status["running"])
        self.assertEqual(status["tap"]["capability"], "disabled")
        self.assertTrue(all(guard.call_count == 0 for guard in guards))

    def test_r5_stop_requests_a_cooperative_stop_of_the_external_monitor(self):
        guards = self.tripwires()
        process = self.hold()
        code, result, _ = self.request("POST", "/api/capture", {"action": "stop"})
        self.assertEqual(code, 200)
        process.wait(timeout=20)
        code, status, _ = self.request("GET", "/api/capture")
        self.assertFalse(status["external_monitor_running"])
        self.assertFalse(status["running"])
        self.assertTrue(all(guard.call_count == 0 for guard in guards))

    def test_r5_other_controls_stay_refused_with_an_external_monitor(self):
        self.hold()
        for action in ("start", "enable", "scan"):
            code, _, _ = self.request("POST", "/api/capture", {"action": action})
            self.assertEqual(code, 409, action)


if __name__ == "__main__":
    unittest.main()
