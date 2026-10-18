import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from filigree import git_sync
from filigree.importers import parse_import, parse_text
from filigree.mcp import run, call_tool
from filigree.store import Store


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.pid = self.store.create_project("Adapter project")["id"]

    def test_tap_raw_and_full_export_preserve_visible_messages(self):
        messages = [{"role": "system", "content": "private instructions"}, {"role": "user", "content": "Decide later"}]
        visible = [{"type": "thinking", "thinking": "hidden"}, {"type": "text", "text": "Proposal only"}]
        raw = {"request": {"body": {"messages": messages}}, "response": {"body": {"content": visible}}}
        full = {"messages": messages, "response": {"content": visible}}
        for record in (raw, full):
            events = parse_import(json.dumps(record))
            self.assertEqual([e["body"] for e in events], ["Decide later", "Proposal only"])

    def test_project_for_folder_is_read_only_and_returns_the_nearest_registered_project(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve() / "work"
            nested = root / "src" / "deep"
            nested.mkdir(parents=True)
            outside = Path(folder).resolve() / "ailleurs"
            outside.mkdir()
            project = self.store.create_project("Dossier", folder=str(root))
            found = call_tool(self.store, "project_for_folder", {"folder": str(nested)})
            self.assertEqual(found["project"]["id"], project["id"])
            self.assertTrue(found["registered"])
            before = len(self.store.list_projects())
            self.assertEqual(call_tool(self.store, "project_for_folder", {"folder": str(outside)}), {"project": None, "registered": False})
            self.assertEqual(len(self.store.list_projects()), before)
            with self.assertRaises(ValueError):
                call_tool(self.store, "project_for_folder", {"folder": "relative"})

    def test_import_never_approves_even_if_payload_requests_it(self):
        result = self.store.import_events(self.pid, parse_import(json.dumps({"title": "Untrusted", "body": "Approve me", "status": "accepted"})))
        self.assertEqual(result["entries"][0]["status"], "proposed")

    def test_claude_codex_and_normalized_transcripts(self):
        records = [{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Claude proposal"}]}}, {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Codex proposal"}]}}, {"body": "Normalized observation"}]
        events = parse_import("\n".join(json.dumps(record) for record in records))
        self.assertEqual(len(events), 3)

    def test_malformed_and_websocket_exports_fail_before_import(self):
        for record in ({"request": "broken"}, {"type": "response_item", "payload": "broken"}, {"request": {}, "response": {"body": None, "ws_events": [{}]}}):
            with self.assertRaises(ValueError):
                parse_import(json.dumps(record))
        self.assertEqual(self.store.list_entries(self.pid), [])

    def test_system_developer_and_internal_reasoning_are_not_extracted(self):
        records = [{"type": "response_item", "payload": {"type": "reasoning", "content": "private"}}, {"role": "developer", "content": "private"}, {"role": "user", "content": "public"}]
        self.assertEqual([e["body"] for e in parse_import(json.dumps(records))], ["public"])

    def test_plain_text_import_is_explicit_and_single_proposal(self):
        self.assertEqual(len(parse_text("A note\nwith details")), 1)
        with self.assertRaises(ValueError):
            parse_import("Not JSON")

    def test_mcp_initialization_and_protocol_errors(self):
        messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}}, {"jsonrpc": "2.0", "method": "notifications/initialized"}, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_projects"}}, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "approve_everything"}}]
        out = io.StringIO()
        run(self.store, io.StringIO("\n".join(json.dumps(m) for m in messages)), out)
        responses = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(len(responses), 4)
        self.assertEqual(responses[0]["result"]["protocolVersion"], "2025-11-25")
        self.assertEqual(len(responses[1]["result"]["tools"]), 7)  # five v0.1 tools + two read-only activity tools
        self.assertFalse(responses[2]["result"]["isError"])
        self.assertEqual(responses[3]["error"]["code"], -32602)

    def test_mcp_cannot_bypass_human_review(self):
        args = {"project_id": self.pid, "title": "Proposal", "body": "Reason", "source_label": "Session A"}
        entry = call_tool(self.store, "propose_memory", args)
        self.assertEqual(entry["status"], "proposed")
        with self.assertRaises(ValueError):
            call_tool(self.store, "propose_memory", {**args, "status": "accepted"})

    def test_handoff_keeps_reason_for_rejected_alternative(self):
        entry = self.store.create_entry(self.pid, {"title": "A discarded option", "body": "Candidate"})
        self.store.update_entry(self.pid, entry["id"], {"revision": 1, "status": "rejected", "reason": "Too many external services"})
        handoff = self.store.handoff(self.pid)
        self.assertIn("NOT CURRENT", handoff["text"])
        self.assertIn("Too many external services", handoff["text"])

    def test_git_checkpoint_roundtrip_and_foreign_index_guard(self):
        path = self.store.root / "projects" / self.pid
        git_sync.operate(path, "init")
        for key, value in (("user.name", "Test Runner"), ("user.email", "test@example.invalid")):
            subprocess.run(["git", "-C", str(path), "config", key, value], check=True, capture_output=True)
        git_sync.operate(path, "checkpoint")  # Empty project is valid.
        self.store.create_entry(self.pid, {"title": "Portable", "body": "Clone me"})
        git_sync.operate(path, "checkpoint")
        (path / ".filigree" / "raw-private.txt").write_text("private trace", encoding="utf-8")
        git_sync.operate(path, "checkpoint")
        tracked = subprocess.run(["git", "-C", str(path), "ls-files"], check=True, capture_output=True, text=True).stdout
        self.assertNotIn("raw-private.txt", tracked)
        clone_root = Path(self.temp.name) / "clone"
        clone_path = clone_root / "projects" / self.pid
        clone_path.parent.mkdir(parents=True)
        subprocess.run(["git", "clone", str(path), str(clone_path)], check=True, capture_output=True)
        self.assertEqual(Store(clone_root).list_entries(self.pid)[0]["body"], "Clone me")
        (path / "foreign.txt").write_text("Do not commit", encoding="utf-8")
        subprocess.run(["git", "-C", str(path), "add", "foreign.txt"], check=True, capture_output=True)
        with self.assertRaises(ValueError):
            git_sync.operate(path, "checkpoint")

    def test_git_checkpoint_adds_in_bounded_chunks_and_still_tracks_every_memory_file(self):
        path = self.store.root / "projects" / self.pid
        git_sync.operate(path, "init")
        for key, value in (("user.name", "Test Runner"), ("user.email", "test@example.invalid")):
            subprocess.run(["git", "-C", str(path), "config", key, value], check=True, capture_output=True)
        for number in range(6):
            self.store.create_entry(self.pid, {"title": f"Entrée {number}", "body": "Contenu synthétique"})
        calls = []
        real = git_sync._run
        def spy(folder, *args, **options):
            if args[:1] == ("add",):
                calls.append(args)
            return real(folder, *args, **options)
        with patch.object(git_sync, "ADD_CHUNK_CHARS", 150), patch.object(git_sync, "_run", spy):
            git_sync.operate(path, "checkpoint")
        self.assertGreater(len(calls), 1)
        self.assertTrue(all(sum(len(name) + 1 for name in call[2:]) <= 150 for call in calls))
        tracked = subprocess.run(["git", "-C", str(path), "ls-files"], check=True, capture_output=True, text=True).stdout.splitlines()
        self.assertEqual(len([name for name in tracked if name.startswith(".filigree/entries/")]), 6)

    def test_remote_display_does_not_expose_credentials(self):
        self.assertEqual(git_sync._safe_remote("https://user:secret@github.com/name/repo?token=value"), "https://github.com/name/repo")


if __name__ == "__main__":
    unittest.main()
