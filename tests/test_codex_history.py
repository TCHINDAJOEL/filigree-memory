"""Codex thread history import from synthetic state/thread_history databases. No real data, no network."""

import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from filigree import cli
from filigree import codex_history
from filigree.capture import Capture, default_settings
from filigree.store import ConflictError, Store

SECRET = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6"
# Codex on Windows records extended-length paths; the prefix does not exist on other systems.
EXTENDED = "\\\\?\\" if os.name == "nt" else ""


def item(kind, identifier, **fields):
    return json.dumps({"type": kind, "id": identifier, **fields})


class CodexHistoryCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "codex"
        self.home.mkdir()
        self.store = Store(self.root / "memory")
        self.work = self.root / "work"
        self.app, self.other = self.work / "app", self.work / "other"
        for folder in (self.app, self.other):
            folder.mkdir(parents=True)
        self.state = sqlite3.connect(self.home / "state_5.sqlite")
        self.state.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, cwd TEXT, updated_at INTEGER, git_branch TEXT)")
        self.history = sqlite3.connect(self.home / "thread_history_1.sqlite")
        self.history.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, item_json TEXT, item_type TEXT)")
        self.addCleanup(self.state.close)
        self.addCleanup(self.history.close)
        self.configure()

    def configure(self, **changes):
        settings = default_settings()
        settings.update(changes)
        Capture(self.store, env={})._save_settings(settings)

    def thread(self, thread_id, cwd, items=None, rollout=None, updated=1_780_000_000):
        self.state.execute("INSERT INTO threads VALUES (?,?,?,?,?)", (thread_id, str(rollout or ""), cwd, updated, "main"))
        for number, (kind, fields) in enumerate(items if items is not None else self.conversation()):
            self.history.execute("INSERT INTO thread_items VALUES (?,?,?,?,?,?,?)", (thread_id, "turn-1", f"{thread_id}-i{number}", number, 1_780_000_000_000 + number, item(kind, f"{thread_id}-i{number}", **fields), kind))
        self.state.commit()
        self.history.commit()

    def conversation(self):
        return [("userMessage", {"content": [{"type": "text", "text": "Ajoute un test pour le parseur"}]}),
                ("reasoning", {"summary": ["RAISONNEMENT CACHE"]}),
                ("agentMessage", {"text": "Je lis le parseur.", "phase": "commentary"}),
                ("commandExecution", {"command": "python -m unittest discover -s tests", "status": "completed", "exitCode": 0, "aggregatedOutput": "Ran 3 tests OK", "durationMs": 1200}),
                ("fileChange", {"changes": [{"path": "C:\\w\\app\\parser.py", "kind": {"type": "update"}, "diff": "SECRET DIFF BODY"}], "status": "completed"}),
                ("agentMessage", {"text": "Terminé.", "phase": "final_answer"})]

    def run_import(self, **kwargs):
        return codex_history.import_history(self.store, env={"CODEX_HOME": str(self.home)}, **kwargs)

    def projects(self):
        return self.store.list_projects()

    def entries(self, project_id):
        return self.store.list_entries(project_id)

    def memory_files(self):
        return sorted(path.relative_to(self.root).as_posix() for path in (self.root / "memory").rglob("*") if path.is_file())


class ImportTests(CodexHistoryCase):
    def test_proven_thread_creates_project_and_sourced_proposals(self):
        self.thread("t-1", EXTENDED + str(self.app))
        result = self.run_import()
        self.assertEqual((result["threads_imported"], result["events_imported"], result["skipped"]), (1, 5, {}))
        project, = self.projects()
        self.assertEqual(Path(project["folder"]["path"]), self.app)
        entries = self.entries(project["id"])
        self.assertEqual(len(entries), 5)
        self.assertTrue(all(entry["status"] == "proposed" and entry["episode"] == "t-1" for entry in entries))
        text = json.dumps(entries, ensure_ascii=False)
        self.assertIn("codex-thread:t-1:t-1-i0", text)
        self.assertIn("codex-history", text)
        self.assertIn("turn-1", text)
        self.assertIn("rollout_ordinal", text)
        self.assertNotIn("SECRET DIFF BODY", text)  # diffs are never stored
        self.assertNotIn("discover -s tests", text)  # a command keeps its program name only
        self.assertNotIn("RAISONNEMENT CACHE", text)  # reasoning is excluded (a marker no temp path can contain)
        self.assertIn("parser.py (update)", text)
        self.assertEqual(result["ignored_items"], {"reasoning": 1})

    def test_existing_project_is_reused(self):
        existing = self.store.create_project("Mon app", "", folder=self.app)
        self.thread("t-1", str(self.app / "."))
        result = self.run_import()
        self.assertEqual([project["id"] for project in self.projects()], [existing["id"]])
        self.assertFalse(result["projects"][0]["created"])

    def test_unprovable_cwd_is_skipped_not_attached(self):
        (self.work / "banned").mkdir()
        self.configure(allowed_roots=[str(self.app), str(self.work / "banned")], exclude=[str(self.work / "banned")])
        self.thread("missing", str(self.app / "gone"))
        self.thread("outside", str(self.other))
        self.thread("excluded", str(self.work / "banned"))
        self.thread("nocwd", "")
        self.thread("relative", "app")
        self.thread("ok", str(self.app))
        result = self.run_import()
        self.assertEqual(result["threads_imported"], 1)
        self.assertEqual(result["skipped"], {"cwd_missing": 1, "outside_roots": 1, "excluded": 1, "no_cwd": 1, "cwd_invalid": 1})
        self.assertEqual(len(self.projects()), 1)
        self.assertEqual({entry["episode"] for project in self.projects() for entry in self.entries(project["id"])}, {"ok"})
        self.assertEqual({row["thread"] for row in result["skipped_threads"]}, {"missing", "outside", "excluded", "nocwd", "relative"})

    def test_generic_folder_never_becomes_a_project(self):
        self.thread("tmp", tempfile.gettempdir())
        result = self.run_import()
        self.assertEqual((result["threads_imported"], self.projects()), (0, []))
        self.assertEqual(sum(result["skipped"].values()), 1)

    def test_auto_create_off_uses_existing_project_only(self):
        self.configure(auto_create=False)
        self.thread("new", str(self.app))
        self.thread("known", str(self.other))
        self.store.create_project("Other", "", folder=self.other)
        result = self.run_import()
        self.assertEqual(result["skipped"], {"no_project": 1})
        self.assertEqual(len(self.projects()), 1)
        self.assertEqual(result["threads_imported"], 1)

    def test_live_rollout_thread_is_left_to_live_capture(self):
        rollout = self.home / "sessions" / "rollout-x.jsonl"
        rollout.parent.mkdir()
        rollout.write_text("{}\n")
        self.thread("live", str(self.app), rollout=EXTENDED + str(rollout))
        self.thread("gone", str(self.other), rollout=self.home / "sessions" / "deleted.jsonl")
        result = self.run_import()
        self.assertEqual(result["skipped"], {"live_source": 1})
        self.assertEqual([Path(project["folder"]["path"]) for project in self.projects()], [self.other])

    def test_rerun_creates_no_duplicates(self):
        self.thread("t-1", str(self.app))
        first = self.run_import()
        second = self.run_import()
        self.assertEqual((first["events_imported"], second["events_imported"], second["duplicates"]), (5, 0, 5))
        project, = self.projects()
        self.assertEqual(len(self.entries(project["id"])), 5)

    def test_text_already_captured_live_is_not_proposed_again(self):
        project = self.store.create_project("App", "", folder=self.app)
        self.store.import_events(project["id"], [{"title": "x", "body": "Ajoute un test pour le parseur", "agent": "Humain via Codex", "episode": "t-1", "occurrence": "other"}], "claude-tap", internal=True)
        self.thread("t-1", str(self.app))
        result = self.run_import()
        self.assertEqual((result["already_captured"], result["events_imported"]), (1, 4))

    def test_long_message_captured_live_is_not_proposed_again(self):
        long_text = "mot " * 3000  # beyond the 6000-character clip
        project = self.store.create_project("App", "", folder=self.app)
        self.store.import_events(project["id"], [{"title": "x", "body": long_text.strip(), "agent": "Codex", "episode": "t-1", "occurrence": "live"}], "claude-tap", internal=True)
        self.thread("t-1", str(self.app), items=[("agentMessage", {"text": long_text})])
        result = self.run_import()
        self.assertEqual((result["already_captured"], result["events_imported"]), (1, 0))

    def test_archived_rollout_is_history_not_live(self):
        archived = self.home / "archived_sessions" / "rollout-x.jsonl"
        archived.parent.mkdir()
        archived.write_text("{}")
        self.thread("arch", str(self.app), rollout=archived)
        result = self.run_import()
        self.assertEqual((result["skipped"], result["threads_imported"]), ({}, 1))

    def test_busy_store_is_retried_then_reported_cleanly(self):
        self.thread("t-1", str(self.app))
        real = Store.import_events
        calls = []

        def flaky(store, *args, **kwargs):
            calls.append(1)
            if len(calls) <= 2:
                raise ConflictError("busy")
            return real(store, *args, **kwargs)
        with patch.object(Store, "import_events", flaky), patch.object(codex_history.time, "sleep"):
            result = self.run_import()
        self.assertEqual((result["events_imported"], "interrupted" in result), (5, False))

    def test_store_busy_for_good_reports_progress_without_traceback(self):
        self.thread("t-1", str(self.app))
        with patch.object(Store, "import_events", side_effect=ConflictError("busy")), patch.object(codex_history.time, "sleep"):
            result = self.run_import()
        self.assertIn("interrupted", result)
        self.assertEqual(result["events_imported"], 0)
        self.assertEqual(self.run_import()["events_imported"], 5)  # a rerun resumes

    def test_redaction_happens_before_truncation(self):
        long_text = "a" * 5990 + " " + SECRET + " fin"  # the secret straddles the 6000-character cut
        self.thread("t-1", str(self.app), items=[("userMessage", {"content": [{"type": "text", "text": long_text}]}),
                                                  ("commandExecution", {"command": "curl -H x", "status": "failed", "exitCode": 7, "aggregatedOutput": "boom " + SECRET})])
        result = self.run_import()
        project, = self.projects()
        dump = json.dumps(self.entries(project["id"]), ensure_ascii=False)
        self.assertNotIn(SECRET, dump)
        self.assertNotIn(SECRET[:14], dump)
        self.assertGreater(result["redactions"], 0)

    def test_dry_run_writes_nothing_and_creates_no_project(self):
        self.thread("t-1", str(self.app))
        self.thread("t-2", str(self.other), rollout=self.home / "nothing")
        before = self.memory_files()
        result = self.run_import(dry_run=True)
        self.assertEqual(before, self.memory_files())
        self.assertEqual(self.projects(), [])
        self.assertTrue(result["dry_run"] and result["events"] == 10 and result["events_imported"] == 0)
        self.assertEqual([project["created"] for project in result["projects"]], [True, True])
        self.assertEqual(self.run_import()["events_imported"], 10)

    def test_dry_run_agrees_with_real_run_on_refusals(self):
        self.thread("tmp", tempfile.gettempdir())
        self.thread("ok", str(self.app))
        self.assertEqual(self.run_import(dry_run=True)["skipped"], self.run_import()["skipped"])

    def test_caps_are_followed_not_dropped(self):
        self.thread("t-1", str(self.app), items=[("agentMessage", {"text": f"message numéro {number}"}) for number in range(30)])
        with patch.object(Store, "IMPORT_MAX_NEW_EVENTS", 7), patch.object(codex_history, "CHUNK", 12):
            result = self.run_import()
        self.assertEqual((result["events_imported"], result["unprocessed"]), (30, 0))
        project, = self.projects()
        self.assertEqual(len(self.entries(project["id"])), 30)

    def test_thread_and_since_filters(self):
        self.thread("old", str(self.app), updated=1_600_000_000)
        self.thread("new", str(self.other), updated=1_780_000_000)
        self.assertEqual(self.run_import(thread="old", dry_run=True)["threads_read"], 1)
        self.assertEqual(self.run_import(since="2025-01-01", dry_run=True)["threads_imported"], 1)
        with self.assertRaises(ValueError):
            self.run_import(since="demain")

    def test_empty_thread_creates_no_project(self):
        self.thread("only-reasoning", str(self.app), items=[("reasoning", {"summary": []}), ("contextCompaction", {})])
        self.thread("empty", str(self.other), items=[])
        result = self.run_import()
        self.assertEqual(result["skipped"], {"nothing_to_store": 1, "no_items": 1})
        self.assertEqual(self.projects(), [])

    def test_disabled_capture_refuses(self):
        self.configure(enabled=False)
        self.thread("t-1", str(self.app))
        with self.assertRaises(ValueError):
            self.run_import()
        self.assertEqual(self.projects(), [])

    def test_missing_databases_are_explained(self):
        with self.assertRaises(ValueError):
            codex_history.import_history(self.store, codex_home=self.root / "nowhere")

    def test_cli_prints_json_without_message_text(self):
        self.thread("t-1", str(self.app))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["--data-dir", str(self.root / "memory"), "import-codex-history", "--codex-home", str(self.home), "--dry-run"])
        report = json.loads(out.getvalue())
        self.assertEqual((report["dry_run"], report["events"]), (True, 5))
        self.assertNotIn("Ajoute un test", out.getvalue())


if __name__ == "__main__":
    unittest.main()
