"""Regression tests for the independent V2 review findings (see .aiwg/testing/v2-review-code.md). Synthetic data only."""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from filigree import hooks, service
from filigree.activity import ActivityLog, journal_path
from filigree.distill import SHEET_URI, distill_project
from filigree.extract import Extractor, _program, extract_line
from filigree.server import agent_key

try:
    from test_v2_activity import ObserverCase, claude_row
except ImportError:
    from tests.test_v2_activity import ObserverCase, claude_row

ROOT = Path(__file__).resolve().parents[1]


class ExtractionFindings(unittest.TestCase):
    def test_test_output_is_redacted_before_its_tail_is_kept(self):
        pem = "-----BEGIN PRIVATE KEY-----\n" + "A" * 300 + "\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n-----END PRIVATE KEY-----"
        for output, secret in ((pem, "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC"), ("x" * 50 + " prefix password=hunter2Secret", "hunter2Secret")):
            extractor = Extractor()
            extract_line(extractor, "claude", json.dumps(claude_row("S", "/w", "assistant", [{"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": "pytest"}}], "u1")).encode())
            events, _, _ = extract_line(extractor, "claude", json.dumps(claude_row("S", "/w", "user", [{"type": "tool_result", "tool_use_id": "t", "content": output}], "u2")).encode())
            self.assertEqual(events[0]["kind"], "test_result")
            self.assertNotIn(secret, events[0]["summary"])

    def test_program_name_of_quoted_and_windows_paths(self):
        self.assertEqual(_program('"C:\\Program Files\\Py\\python.exe" -c x'), "python.exe")
        self.assertEqual(_program("C:\\Py\\python.exe -m x"), "python.exe")
        self.assertEqual(_program("TOKEN=abc /usr/bin/git status"), "git")

    def test_event_part_is_the_block_position(self):
        events, _, _ = extract_line(Extractor(), "claude", json.dumps(claude_row("S", "/w", "assistant", [{"type": "thinking", "thinking": "x"}, {"type": "text", "text": "visible"}], "u")).encode())
        self.assertEqual(events[0]["part"], 1)


class ObserverFindings(ObserverCase):
    def test_session_in_an_excluded_subfolder_of_a_project_is_not_journaled(self):
        pid = self.store.create_project("App", folder=str(self.work))["id"]
        sandbox = self.work / "sandbox"
        sandbox.mkdir()
        self.settings["exclude"] = [str(sandbox)]
        self.observer.scan_once()
        self.transcript("S1", [("user", "dans le bac à sable")], cwd=sandbox)
        self.observer.scan_once()
        self.assertFalse(journal_path(self.store, pid).exists())

    def test_forked_transcript_lines_are_one_event_and_old_history_is_skipped(self):
        pid = self.store.create_project("App", folder=str(self.work))["id"]
        self.observer.scan_once()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        shared = claude_row("ORIG", self.work, "user", "demande partagée", "uuid-shared", now)
        old = claude_row("FORK", self.work, "user", "très vieille ligne recopiée", "uuid-old", "2020-01-01T00:00:00Z")
        folder = self.claude / "projects" / "-w"
        (folder / "ORIG.jsonl").write_text(json.dumps(shared) + "\n", encoding="utf-8")
        (folder / "FORK.jsonl").write_text(json.dumps(old) + "\n" + json.dumps({**shared, "sessionId": "FORK"}) + "\n", encoding="utf-8")
        self.observer.scan_once()
        summaries = [event["summary"] for event in ActivityLog(journal_path(self.store, pid)).events()]
        self.assertEqual(summaries, ["demande partagée"])

    def test_one_failing_project_neither_stalls_the_cursor_nor_the_others(self):
        pid = self.store.create_project("App", folder=str(self.work))["id"]
        self.observer.scan_once()
        self.transcript("S1", [("user", "première")])
        with patch("filigree.distill.distill_project", side_effect=RuntimeError("boom")):
            result = self.observer.scan_once()
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["events"], 1)
        state = json.loads((self.store.root / ".capture" / "activity-state.json").read_text(encoding="utf-8"))
        self.assertTrue(all(cursor["offset"] > 0 for cursor in state["files"].values()))
        self.assertEqual(self.observer.scan_once()["events"], 0)  # progress was saved: nothing is re-read
        self.assertEqual(ActivityLog(journal_path(self.store, pid)).stats()["events"], 1)

    def test_worktree_whose_repository_is_outside_the_roots_is_not_mapped(self):
        repo = self.base / "outside" / "repo"
        (repo / ".git" / "worktrees" / "wt").mkdir(parents=True)
        tree = self.base / "work" / "wt"
        tree.mkdir(parents=True)
        (tree / ".git").write_text(f"gitdir: {repo / '.git' / 'worktrees' / 'wt'}\n", encoding="utf-8")
        (repo / ".git" / "worktrees" / "wt" / "gitdir").write_text(f"{tree / '.git'}\n", encoding="utf-8")
        pid = self.store.create_project("Repo", folder=str(repo))["id"]
        self.settings["allowed_roots"] = [str(self.base / "work")]
        self.assertIsNone(self.observer._project_for(str(tree), self.settings["allowed_roots"]))
        self.settings["allowed_roots"] = None
        self.assertEqual(self.observer._project_for(str(tree), None)["id"], pid)


class DistillFindings(ObserverCase):
    def test_lost_state_never_rewrites_an_accepted_suite(self):
        pid = self.store.create_project("App", folder=str(self.work))["id"]
        log = ActivityLog(journal_path(self.store, pid))
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
        key = "claude:x:S1"
        log.add({"session_key": key, "client": "claude"}, [{"event_id": "e1", "kind": "user_prompt", "ts_observed": old, "summary": "début"}])
        for uri in (SHEET_URI + key, SHEET_URI + key + "#suite-1"):
            entry = self.store.create_entry(pid, {"title": "fiche", "body": "revue", "status": "proposed", "tags": ["fiche-session"], "sources": [{"label": "j", "uri": uri, "excerpt": ""}]}, channel="capture")
            self.store.update_entry(pid, entry["id"], {"status": "accepted", "revision": entry["revision"]}, channel="http-ui")
        log.add({"session_key": key, "client": "claude"}, [{"event_id": "e2", "kind": "user_prompt", "ts_observed": old, "summary": "suite"}])
        self.assertEqual(distill_project(self.store, pid, {}), 1)  # state lost: {} instead of the saved suite number
        entries = self.store.list_entries(pid)
        self.assertEqual({entry["body"] for entry in entries if entry["status"] == "accepted"}, {"revue"})
        suite = [entry for entry in entries if entry["status"] == "proposed"]
        self.assertEqual(len(suite), 1)
        self.assertTrue(suite[0]["sources"][0]["uri"].endswith("#suite-2"))


class ServiceAndKeyFindings(unittest.TestCase):
    def test_concurrent_key_creation_yields_one_complete_key(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            keys, errors = [], []

            def create():
                try:
                    keys.append(agent_key(Path(folder)))
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=create) for _ in range(12)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            self.assertEqual(len(set(keys)), 1)
            self.assertEqual([path.name for path in (Path(folder) / ".runtime").iterdir()], ["agent.key"])  # no temporary left

    def test_launchd_restarts_only_on_failure_and_systemd_escapes_specifiers(self):
        mac = service.plan("Darwin", "/usr/bin/python3", "/Users/x/100%", Path("/h"))
        self.assertIn("<key>SuccessfulExit</key>", mac["text"])
        linux = service.plan("Linux", "/usr/bin/python3", "/home/x/$HOME/100%", Path("/h"), env={})
        self.assertIn("$$HOME", linux["text"])
        self.assertIn("100%%", linux["text"])
        self.assertNotIn("$HOME" + chr(92), linux["text"].replace("$$HOME", ""))

    def test_already_running_agent_is_a_clean_exit(self):
        from filigree.agent import AgentRunning
        self.assertTrue(issubclass(AgentRunning, ValueError))


class HookCommandFindings(unittest.TestCase):
    """The generated hook command must run as written by the shell that executes hooks."""

    def run_through(self, shell_command, data):
        launcher = [sys.executable, "-c", f"import sys;sys.path.insert(0,{ROOT.as_posix()!r});from filigree.cli import main;main()"]
        command = hooks._shell_join(hooks._command(launcher, data, "claude", "session_start"))
        completed = subprocess.run(shell_command(command), input=json.dumps({"session_id": "HOOK-1"}), capture_output=True, text=True, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return (Path(data) / ".runtime" / "signals.jsonl").read_text(encoding="utf-8")

    def test_command_runs_in_the_native_shell(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            recorded = self.run_through(lambda command: command if os.name == "nt" else ["/bin/sh", "-c", command], Path(folder) / "data dir")
            self.assertIn("HOOK-1", recorded)

    @unittest.skipUnless(os.name == "nt" and shutil.which("bash"), "Git Bash on Windows only")
    def test_command_runs_in_git_bash_on_windows(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            recorded = self.run_through(lambda command: [shutil.which("bash"), "-c", command], Path(folder) / "data")
            self.assertIn("HOOK-1", recorded)


if __name__ == "__main__":
    unittest.main()
