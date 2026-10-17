"""Agent daemon, autostart plans, opt-in hooks, MCP scope and chat exports (ADR-0003). No real HOME, registry or network."""

import contextlib
import http.client
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import zipfile

from filigree import cli, hooks, mcp, service
from filigree.agent import info_path, run_agent, running_agent
from filigree.chat_export import parse_chat_export
from filigree.store import Store


class Temp(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.data = self.base / "data"
        self.store = Store(self.data)
        self.folder = self.base / "projet"
        self.folder.mkdir()


class AgentTests(Temp):
    def test_agent_announces_itself_serves_with_the_key_and_cleans_up(self):
        stop, ready = threading.Event(), threading.Event()
        holder = {}
        env = {"CLAUDE_CONFIG_DIR": str(self.base / "c"), "CODEX_HOME": str(self.base / "x"), "CLOUDTAP_DB": str(self.base / "absent.sqlite3"),
               "APPDATA": str(self.base / "roaming"), "LOCALAPPDATA": str(self.base / "local")}  # no real user source is read
        thread = threading.Thread(target=lambda: holder.setdefault("code", run_agent(self.data, 0, env=env, interval=1, out=lambda _: None, ready=lambda info: (holder.update(info=info), ready.set()), stop_event=stop)), daemon=True)
        thread.start()
        self.assertTrue(ready.wait(15))
        try:
            found = running_agent(self.data)
            self.assertIsNotNone(found)
            self.assertEqual(found["port"], holder["info"]["port"])
            with self.assertRaises(ValueError):
                run_agent(self.data, 0, env=env, out=lambda _: None)  # one agent per data folder
            connection = http.client.HTTPConnection("127.0.0.1", found["port"], timeout=5)
            connection.request("GET", "/api/projects", headers={"Host": f"127.0.0.1:{found['port']}"})
            self.assertEqual(connection.getresponse().status, 403)
            connection.close()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                from filigree.server import serve
                serve(self.data, 0, capture=False)
            self.assertIn(found["url"], output.getvalue())  # serve defers to the running agent
        finally:
            stop.set()
            thread.join(15)
        self.assertEqual(holder.get("code"), 0)
        self.assertFalse(info_path(self.data).exists())
        self.assertIsNone(running_agent(self.data))

    def test_stale_announcement_is_ignored(self):
        info_path(self.data).parent.mkdir(parents=True, exist_ok=True)
        info_path(self.data).write_text(json.dumps({"pid": 1, "port": 1}), encoding="utf-8")
        self.assertIsNone(running_agent(self.data, timeout=0.3))


class FakeRunner:
    def __init__(self):
        self.files, self.registry, self.commands = {}, {}, []

    def write(self, path, text):
        self.files[path] = text

    def read(self, path):
        return self.files.get(path)

    def delete(self, path):
        self.files.pop(path, None)

    def run(self, command):
        self.commands.append(command)

    def reg_get(self, key, name):
        return self.registry.get((key, name))

    def reg_set(self, key, name, value):
        self.registry[(key, name)] = value

    def reg_delete(self, key, name):
        self.registry.pop((key, name), None)


class ServiceTests(Temp):
    def test_windows_plan_uses_the_user_run_key_and_pythonw(self):
        planned = service.plan("Windows", r"C:\Py\python.exe", r"C:\Users\x\.filigree data", self.base)
        self.assertEqual(planned["key"], service.RUN_KEY)
        self.assertIn("pythonw.exe", planned["command"])
        self.assertIn('"C:\\Users\\x\\.filigree data" agent', planned["command"])
        runner = FakeRunner()
        self.assertFalse(service.status(planned, runner)["installed"])
        service.apply(planned, runner)
        self.assertEqual(service.status(planned, runner), {"installed": True, "up_to_date": True, "location": planned["description"]})
        service.remove(planned, runner)
        self.assertEqual(runner.registry, {})

    def test_macos_and_linux_plans_write_only_under_the_given_home(self):
        mac = service.plan("Darwin", "/usr/bin/python3", "/Users/x/.filigree", self.base)
        self.assertTrue(mac["path"].startswith(str(self.base)))
        self.assertIn("<key>KeepAlive</key>", mac["text"])
        linux = service.plan("Linux", "/usr/bin/python3", "/home/x/.filigree", self.base, env={"XDG_CONFIG_HOME": str(self.base / "cfg")})
        self.assertTrue(linux["path"].startswith(str(self.base / "cfg")))
        self.assertIn("Restart=on-failure", linux["text"])
        runner = FakeRunner()
        service.apply(linux, runner)
        self.assertIn(["systemctl", "--user", "enable", "--now", "filigree-agent.service"], runner.commands)
        service.remove(linux, runner)
        self.assertEqual(runner.files, {})
        self.assertIn(["systemctl", "--user", "disable", "--now", "filigree-agent.service"], runner.commands)

    def test_source_checkout_launcher_and_unknown_system(self):
        planned = service.plan("Linux", "/usr/bin/python3", "/d", self.base, checkout="/src/filigree")
        self.assertIn("sys.path.insert(0,'/src/filigree')", planned["text"])
        with self.assertRaises(ValueError):
            service.plan("Plan9", "python", "/d", self.base)


class HookTests(Temp):
    def setUp(self):
        super().setUp()
        self.env = {"CLAUDE_CONFIG_DIR": str(self.base / "claude"), "CODEX_HOME": str(self.base / "codex")}
        self.launcher = ["python", "-m", "filigree"]

    def test_claude_install_keeps_user_hooks_backs_up_and_uninstalls_cleanly(self):
        settings = self.base / "claude" / "settings.json"
        settings.parent.mkdir()
        original = {"model": "x", "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}
        settings.write_text(json.dumps(original), encoding="utf-8")
        dry = hooks.change("claude", "install", self.data, self.launcher, env=self.env, dry_run=True)
        self.assertTrue(dry["changed"])
        self.assertIn("+", dry["diff"])
        self.assertEqual(json.loads(settings.read_text(encoding="utf-8")), original)  # dry run writes nothing
        done = hooks.change("claude", "install", self.data, self.launcher, env=self.env, inject=True)
        self.assertTrue(Path(done["backup"]).exists())
        current = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(current["model"], "x")
        commands = [hook["command"] for group in current["hooks"]["SessionStart"] for hook in group["hooks"]]
        self.assertIn("echo mine", commands)
        self.assertTrue(any("signal --client claude --event session_start --inject" in command.replace('"', "").replace("'", "") for command in commands))
        self.assertTrue(hooks.status(self.data, env=self.env)["claude"]["inject"])
        again = hooks.change("claude", "install", self.data, self.launcher, env=self.env, inject=True)
        self.assertFalse(again["changed"])  # idempotent
        hooks.change("claude", "uninstall", self.data, self.launcher, env=self.env)
        self.assertEqual(json.loads(settings.read_text(encoding="utf-8")), original)
        log = (self.data / ".runtime" / "install-log.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["action"] for line in log], ["install", "uninstall"])

    def test_invalid_claude_settings_are_never_overwritten(self):
        settings = self.base / "claude" / "settings.json"
        settings.parent.mkdir()
        settings.write_text("{pas du json", encoding="utf-8")
        with self.assertRaises(ValueError):
            hooks.change("claude", "install", self.data, self.launcher, env=self.env)
        self.assertEqual(settings.read_text(encoding="utf-8"), "{pas du json")

    def test_codex_refuses_an_existing_notify_and_round_trips_otherwise(self):
        config = self.base / "codex" / "config.toml"
        config.parent.mkdir()
        config.write_text('model = "o3"\n\n[profiles.x]\nmodel = "y"\n', encoding="utf-8")
        hooks.change("codex", "install", self.data, self.launcher, env=self.env)
        text = config.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("notify = ["))
        self.assertTrue(hooks.status(self.data, env=self.env)["codex"]["installed"])
        hooks.change("codex", "uninstall", self.data, self.launcher, env=self.env)
        self.assertEqual(config.read_text(encoding="utf-8"), 'model = "o3"\n\n[profiles.x]\nmodel = "y"\n')
        config.write_text('notify = ["mine"]\n', encoding="utf-8")
        with self.assertRaises(ValueError):
            hooks.change("codex", "install", self.data, self.launcher, env=self.env)

    def test_signal_records_only_ids_never_fails_and_injects_accepted_knowledge(self):
        pid = self.store.create_project("App", folder=str(self.folder))["id"]
        self.store.create_entry(pid, {"title": "Choix accepté", "body": "SQLite local", "status": "accepted", "sources": [{"label": "revue", "excerpt": "", "uri": ""}]}, channel="http-ui")
        self.store.create_entry(pid, {"title": "Idée proposée", "body": "Peut-être Redis", "status": "proposed", "sources": [{"label": "agent", "excerpt": "", "uri": ""}]}, channel="mcp")
        payload = io.StringIO(json.dumps({"session_id": "S-42", "cwd": str(self.folder), "prompt": "secret du prompt"}))
        out = io.StringIO()
        started = time.monotonic()
        self.assertEqual(hooks.signal(self.data, "claude", "session_start", inject=True, stdin=payload, out=out), 0)
        self.assertLess(time.monotonic() - started, 1.0)
        recorded = (self.data / ".runtime" / "signals.jsonl").read_text(encoding="utf-8")
        self.assertIn("S-42", recorded)
        self.assertNotIn("secret du prompt", recorded)
        self.assertIn("Choix accepté", out.getvalue())
        self.assertNotIn("Peut-être Redis", out.getvalue())  # D4: accepted knowledge only
        self.assertEqual(hooks.signal(self.base / "inexistant" / "\0bad", "claude", "x", stdin=io.StringIO("{")), 0)


class McpScopeTests(Temp):
    def test_default_scope_is_the_current_folder_project(self):
        mine = self.store.create_project("Mine", folder=str(self.folder))["id"]
        other_folder = self.base / "autre"
        other_folder.mkdir()
        other = self.store.create_project("Other", folder=str(other_folder))["id"]
        scope = mcp.scope_for(self.store, self.folder / "src")
        self.assertEqual(scope, {mine})
        self.assertEqual([p["id"] for p in mcp.call_tool(self.store, "list_projects", {}, scope)], [mine])
        with self.assertRaises(ValueError):
            mcp.call_tool(self.store, "search_memory", {"project_id": other}, scope)
        self.assertIsNone(mcp.call_tool(self.store, "project_for_folder", {"folder": str(other_folder)}, scope)["project"])
        self.assertIsNone(mcp.scope_for(self.store, all_projects=True))
        self.assertEqual(mcp.scope_for(self.store, self.base), set())

    def test_activity_tools_and_accepted_only_handoff(self):
        pid = self.store.create_project("Mine", folder=str(self.folder))["id"]
        self.store.create_entry(pid, {"title": "Proposition", "body": "à revoir", "status": "proposed", "sources": [{"label": "a", "excerpt": "", "uri": ""}]}, channel="mcp")
        result = mcp.call_tool(self.store, "project_activity", {"project_id": pid}, {pid})
        self.assertEqual(result["events"], [])
        self.assertIn("non revues", result["note"])
        self.assertEqual(mcp.call_tool(self.store, "active_sessions", {"project_id": pid, "minutes": 5}, {pid})["overlaps"], [])
        with self.assertRaises(ValueError):
            mcp.call_tool(self.store, "active_sessions", {"project_id": pid, "minutes": 0}, {pid})
        text = mcp.call_tool(self.store, "get_handoff", {"project_id": pid, "accepted_only": True}, {pid})["text"]
        self.assertNotIn("Proposition", text)
        with self.assertRaises(ValueError):
            mcp.call_tool(self.store, "get_handoff", {"project_id": pid, "accepted_only": "yes"}, {pid})


class McpRootsTests(Temp):
    """Claude Code does not start MCP servers in the session folder: the scope comes from the client's MCP roots."""

    def converse(self, roots_reply, capabilities=None, auto_roots=True):
        mine = self.store.create_project("Mine", folder=str(self.folder))["id"]
        other_folder = self.base / "autre"
        other_folder.mkdir()
        self.store.create_project("Other", folder=str(other_folder))
        lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"capabilities": capabilities if capabilities is not None else {"roots": {}}}},
                 {"jsonrpc": "2.0", "method": "notifications/initialized"}, roots_reply,
                 {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_projects", "arguments": {}}}]
        out = io.StringIO()
        mcp.run(self.store, io.StringIO("\n".join(json.dumps(line) for line in lines) + "\n"), out, scope=mcp.scope_for(self.store, self.base), auto_roots=auto_roots)
        replies = [json.loads(line) for line in out.getvalue().splitlines()]
        listed = json.loads(replies[-1]["result"]["content"][0]["text"])
        return mine, replies, [project["id"] for project in listed]

    def test_roots_of_the_client_define_the_scope(self):
        uri = self.folder.as_uri()
        mine, replies, listed = self.converse({"jsonrpc": "2.0", "id": "filigree-roots-1", "result": {"roots": [{"uri": uri}]}})
        self.assertEqual(replies[1]["method"], "roots/list")  # the server asked
        self.assertEqual(listed, [mine])

    def test_no_roots_capability_no_request_and_scope_stays_empty(self):
        _, replies, listed = self.converse({"jsonrpc": "2.0", "method": "notifications/cancelled"}, capabilities={})
        self.assertFalse(any(reply.get("method") == "roots/list" for reply in replies))
        self.assertEqual(listed, [])

    def test_foreign_uris_are_ignored(self):
        _, _, listed = self.converse({"jsonrpc": "2.0", "id": "filigree-roots-1", "result": {"roots": [{"uri": "https://example.com/x"}, {"uri": "file://server/share"}]}})
        self.assertEqual(listed, [])

    def test_explicit_scope_never_asks_for_roots(self):
        _, replies, listed = self.converse({"jsonrpc": "2.0", "id": "filigree-roots-1", "result": {"roots": [{"uri": self.folder.as_uri()}]}}, auto_roots=False)
        self.assertFalse(any(reply.get("method") == "roots/list" for reply in replies))
        self.assertEqual(listed, [])

class ChatExportTests(Temp):
    def chatgpt(self):
        return [{"id": "conv-1", "title": "Choix de base", "current_node": "n3", "mapping": {
            "root": {"id": "root", "message": None, "parent": None},
            "n0": {"id": "n0", "parent": "root", "message": {"id": "m0", "author": {"role": "system"}, "content": {"content_type": "text", "parts": ["prompt système"]}}},
            "n1": {"id": "n1", "parent": "n0", "message": {"id": "m1", "author": {"role": "user"}, "content": {"content_type": "text", "parts": ["SQLite ou Postgres ?"]}, "create_time": 1700000000}},
            "n2x": {"id": "n2x", "parent": "n1", "message": {"id": "m2x", "author": {"role": "assistant"}, "content": {"content_type": "text", "parts": ["branche abandonnée"]}}},
            "n2": {"id": "n2", "parent": "n1", "message": {"id": "m2", "author": {"role": "assistant"}, "content": {"content_type": "text", "parts": ["SQLite pour commencer. sk-ant-" + "B" * 40]}}},
            "n3": {"id": "n3", "parent": "n2", "message": {"id": "m3", "author": {"role": "tool"}, "content": {"content_type": "text", "parts": ["sortie outil"]}}}}}]

    def test_chatgpt_current_branch_only_and_redacted(self):
        path = self.base / "conversations.json"
        path.write_text(json.dumps(self.chatgpt()), encoding="utf-8")
        parsed = parse_chat_export(path)
        self.assertEqual(parsed["format"], "chatgpt")
        bodies = [event["body"] for event in parsed["events"]]
        self.assertEqual(len(bodies), 2)
        self.assertNotIn("branche abandonnée", json.dumps(bodies))
        self.assertNotIn("prompt système", json.dumps(bodies))
        self.assertNotIn("BBBBBBBB", json.dumps(parsed["events"]))

    def test_claude_zip_import_through_the_cli_is_idempotent(self):
        pid = self.store.create_project("App", folder=str(self.folder))["id"]
        data = [{"uuid": "c1", "name": "Architecture", "chat_messages": [
            {"uuid": "a", "sender": "human", "text": "On garde le stockage local ?"},
            {"uuid": "b", "sender": "assistant", "text": "", "content": [{"type": "text", "text": "Oui, fichiers Markdown."}, {"type": "tool_use", "name": "x"}]}]}]
        archive = self.base / "export.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("export/conversations.json", json.dumps(data))
        for expected in (2, 0):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                cli.main(["--data-dir", str(self.data), "import-export", str(archive), "--project", pid])
            self.assertEqual(json.loads(output.getvalue())["imported"], expected)
        entries = self.store.list_entries(pid)
        self.assertEqual({entry["status"] for entry in entries}, {"proposed"})
        self.assertEqual(len(entries), 2)

    def test_unknown_shapes_and_oversized_members_are_refused(self):
        path = self.base / "x.json"
        path.write_text(json.dumps([{"foo": 1}]), encoding="utf-8")
        with self.assertRaises(ValueError):
            parse_chat_export(path)
        empty = self.base / "empty.zip"
        with zipfile.ZipFile(empty, "w") as handle:
            handle.writestr("autre.json", "[]")
        with self.assertRaises(ValueError):
            parse_chat_export(empty)


class CliTests(Temp):
    def run_cli(self, *argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cli.main(["--data-dir", str(self.data), *argv])
        return json.loads(output.getvalue())

    def test_setup_roots_and_status_artifacts(self):
        result = self.run_cli("setup", "--root", str(self.folder))
        self.assertEqual(result["allowed_roots"], [str(self.folder)])
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                cli.main(["--data-dir", str(self.data), "setup"])
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                cli.main(["--data-dir", str(self.data), "setup", "--root", "relatif"])
        self.assertIsNone(self.run_cli("setup", "--any-folder")["allowed_roots"])

    def test_activity_command_reads_an_empty_journal(self):
        pid = self.store.create_project("App", folder=str(self.folder))["id"]
        result = self.run_cli("activity", pid)
        self.assertEqual(result["stats"], {"events": 0, "sessions": 0})



class McpConfigTests(Temp):
    def config(self, *argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cli.main(["--data-dir", str(self.data), "mcp-config", *argv])
        return output.getvalue()

    def test_claude_desktop_requires_an_explicit_scope(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["--data-dir", str(self.data), "mcp-config", "--client", "claude-desktop"])
        entry = json.loads(self.config("--client", "claude-desktop", "--project-folder", str(self.folder)))["mcpServers"]["filigree"]
        self.assertEqual(entry["args"][-2:], ["--project-folder", str(self.folder)])
        self.assertIn("--all-projects", json.loads(self.config("--client", "claude-desktop", "--all-projects"))["mcpServers"]["filigree"]["args"])

    def test_one_line_commands_for_claude_code_and_codex(self):
        claude = self.config("--client", "claude", "--command")
        self.assertTrue(claude.startswith("claude mcp add --scope user filigree"))
        self.assertIn(" -- ", claude)
        self.assertTrue(claude.rstrip().endswith("mcp"))
        codex = self.config("--client", "codex", "--command")
        self.assertTrue(codex.startswith("codex mcp add filigree"))
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["--data-dir", str(self.data), "mcp-config", "--client", "claude-desktop", "--all-projects", "--command"])


if __name__ == "__main__":
    unittest.main()
