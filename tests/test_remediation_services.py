"""Regression cases for the 2026-10-16 verification: HTTP server, MCP and CLI (C-1..C-4, D-12 and their P3).

Every server or subprocess here gets explicit synthetic capture sources inside a temporary directory; nothing reads
the real claude-tap database or the real Claude/Codex transcript folders."""

import http.client
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import unittest
from unittest.mock import patch

from filigree import cli, mcp, server
from filigree.server import LocalServer
from filigree.store import Store

REPO = Path(__file__).resolve().parent.parent
DISABLED_NOTICE = "désactivée"


def isolated_env(base: Path, **extra):
    """Process environment whose capture sources and home all point into `base` (synthetic, empty)."""
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONUTF8", "PYTHONIOENCODING", "PYTHONPATH", "FILIGREE_DATA_DIR"}}
    env.update({
        "CLOUDTAP_DB": str(base / "absent-tap" / "traces.sqlite3"), "XDG_DATA_HOME": str(base / "xdg"),
        "CLAUDE_CONFIG_DIR": str(base / "claude-home"), "CODEX_HOME": str(base / "codex-home"),
        "HOME": str(base / "home"), "USERPROFILE": str(base / "home"),
    })
    env.update(extra)
    return env


def synthetic_capture_env(base: Path):
    return {key: isolated_env(base)[key] for key in ("CLOUDTAP_DB", "XDG_DATA_HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME", "HOME", "USERPROFILE")}


class ServerCase(unittest.TestCase):
    capture_enabled = True

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.folder = self.base / "projet"
        self.folder.mkdir()
        self.store = Store(self.base / "memory")
        self.start_server()

    def start_server(self, **options):
        if self.capture_enabled:
            options.setdefault("env", synthetic_capture_env(self.base))
        self.server = LocalServer(("127.0.0.1", 0), self.store, capture_enabled=self.capture_enabled, **options)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None, token=True, raw=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=10)
        request_headers = {"Content-Type": "application/json"}
        if token:
            request_headers["X-Filigree-Token"] = self.server.token
        request_headers.update(headers or {})
        payload = raw if raw is not None else (json.dumps(body) if body is not None else None)
        connection.request(method, path, body=payload, headers=request_headers)
        response = connection.getresponse()
        data = response.read()
        result_headers = dict(response.getheaders())
        connection.close()
        return response.status, json.loads(data) if "application/json" in result_headers.get("Content-Type", "") else data, result_headers


class NoCaptureServerTests(ServerCase):
    """C-4 / D-12: --no-capture is a hard capability off, not a start-up default."""
    capture_enabled = False

    def tripwires(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("a capture source was touched on a --no-capture server")
        targets = ["filigree.server.Capture", "filigree.capture.Capture.__init__", "filigree.capture.Capture.start", "filigree.capture.Capture.scan_once",
                   "filigree.capture.Capture.scan_if_possible", "filigree.capture.tap_source.probe", "filigree.capture.tap_source.resolve_db_path",
                   "filigree.capture.native_index.default_roots", "filigree.capture.native_index.NativeIndex", "filigree.tap_source.probe"]
        return [patch(target, side_effect=forbidden) for target in targets]

    def test_status_and_every_control_leave_all_sources_untouched(self):
        guards = [guard.start() for guard in self.tripwires()]
        self.addCleanup(patch.stopall)
        code, status, _ = self.request("GET", "/api/capture")
        self.assertEqual(code, 200)
        self.assertFalse(status["enabled"])
        self.assertFalse(status["running"])
        self.assertTrue(status["disabled_by_server"])
        self.assertEqual(status["tap"]["capability"], "disabled")
        self.assertEqual(status["native"]["roots"], {})
        for body in ({"action": "start"}, {"action": "enable"}, {"action": "scan"}, {"action": "fallback-on"}, {"action": "resume"},
                     {"action": "link", "key": "tap:x", "project_id": "p"}, {"action": "exclude", "folder": str(self.folder)}, {"action": "pause"}):
            code, result, _ = self.request("POST", "/api/capture", body)
            self.assertEqual(code, 409, body)
            self.assertIn(DISABLED_NOTICE, result["error"])
        code, result, _ = self.request("POST", "/api/capture", {"action": "stop"})
        self.assertEqual(code, 200)
        self.assertFalse(result["status"]["running"])
        self.assertTrue(all(guard.call_count == 0 for guard in guards))
        self.assertNotIn("filigree-capture", [thread.name for thread in threading.enumerate()])
        self.assertFalse((self.store.root / ".capture").exists())

    def test_other_api_still_works_without_capture(self):
        code, projects, _ = self.request("GET", "/api/projects")
        self.assertEqual((code, projects), (200, []))
        code, value, _ = self.request("GET", "/api/bootstrap")
        self.assertEqual(code, 200)
        self.assertTrue(value["token"])


class HTTPRemediationTests(ServerCase):
    def project(self):
        _, project, _ = self.request("POST", "/api/projects", {"name": "P", "folder": str(self.folder)})
        return project["id"]

    def test_expected_errors_are_sanitized(self):
        pid = self.project()
        probes = [
            ("GET", f"/api/projects/{pid}/handoff?budget=abc", None),
            ("GET", f"/api/projects/{pid}/handoff?budget=1", None),
            ("POST", "/api/capture", {"action": ["start"]}),
            ("POST", "/api/capture", {"action": {"a": 1}}),
            ("POST", "/api/projects", {"folder": 5}),
            ("PATCH", f"/api/projects/{pid}/entries/00000000-0000-4000-8000-000000000000", {"revision": 1}),
        ]
        for method, path, body in probes:
            code, result, _ = self.request(method, path, body)
            self.assertIn(code, {400, 404}, (path, body))
            message = result["error"]
            for leak in ("invalid literal", "unhashable", "Traceback", "object", "KeyError", "TypeError", "int()", "'"):
                self.assertNotIn(leak, message, (path, body, message))

    def test_bad_content_length_is_a_clean_400(self):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=10)
        connection.putrequest("POST", "/api/projects")
        for key, value in (("Content-Type", "application/json"), ("X-Filigree-Token", self.server.token), ("Content-Length", "abc")):
            connection.putheader(key, value)
        connection.endheaders()
        response = connection.getresponse()
        body = json.loads(response.read())
        connection.close()
        self.assertEqual(response.status, 400)
        self.assertNotIn("invalid literal", body["error"])

    def test_deeply_nested_json_is_a_400_not_a_500(self):
        depth = 200000
        code, result, _ = self.request("POST", "/api/projects", raw="[" * depth + "]" * depth)
        self.assertEqual(code, 400)
        self.assertIn("imbriqué", result["error"])
        pid = self.project()
        code, result, _ = self.request("POST", f"/api/projects/{pid}/import", {"text": "[" * depth + "]" * depth, "source": "deep"})
        self.assertEqual(code, 400, result)
        self.assertNotIn("recursion", json.dumps(result).lower())

    def test_unsupported_methods_get_a_json_405_with_security_headers(self):
        for method in ("PUT", "DELETE", "OPTIONS"):
            code, result, headers = self.request(method, "/api/projects", {})
            self.assertEqual(code, 405, method)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            self.assertIn("error", result)

    def test_host_and_origin_comparison_ignores_case_but_not_the_name(self):
        port = self.server.server_address[1]
        code, _, _ = self.request("GET", "/api/bootstrap", headers={"Host": f"LOCALHOST:{port}"})
        self.assertEqual(code, 200)
        code, _, _ = self.request("GET", "/api/bootstrap", headers={"Host": f"evil.example:{port}"})
        self.assertEqual(code, 403)

    def test_a_second_listener_cannot_share_an_occupied_port(self):
        port = self.server.server_address[1]
        with self.assertRaises(OSError):
            LocalServer(("127.0.0.1", port), Store(self.base / "other"), capture_enabled=False)

    def test_serve_reports_an_occupied_port_without_traceback(self):
        port = self.server.server_address[1]
        with self.assertRaises(ValueError) as caught:
            server.serve(self.base / "other", port, capture=False)
        self.assertIn(str(port), str(caught.exception))


class MCPRemediationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name).resolve()
        (base / "dossier").mkdir()
        self.store = Store(base / "memory")
        self.project = self.store.create_project("P", "", folder=base / "dossier")["id"]

    def call(self, messages):
        out = io.StringIO()
        mcp.run(self.store, io.StringIO("\n".join(json.dumps(m) if not isinstance(m, str) else m for m in messages) + "\n"), out)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def tool(self, name, arguments):
        handshake = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, {"jsonrpc": "2.0", "method": "notifications/initialized"}]
        return self.call(handshake + [{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": arguments}}])[-1]

    def propose(self, **overrides):
        arguments = {"project_id": self.project, "title": "Titre", "body": "Corps", "source_label": "test"}
        arguments.update(overrides)
        return self.tool("propose_memory", arguments)

    def test_proposals_reject_empty_body_and_title(self):
        for overrides in ({"body": ""}, {"body": "  \n\t "}, {"title": "   "}):
            response = self.propose(**overrides)
            self.assertTrue(response["result"]["isError"], overrides)
        self.assertEqual(self.store.list_entries(self.project), [])

    def test_proposals_cannot_claim_a_human_author_and_stay_proposed(self):
        for name in ("human", "Human", " HUMAIN ", "utilisateur", "user", "reviewer", ""):
            self.assertTrue(self.propose(agent=name)["result"]["isError"], name)
        self.assertEqual(self.store.list_entries(self.project), [])
        ok = self.propose(agent="codex")
        self.assertFalse(ok["result"]["isError"])
        entry = self.store.list_entries(self.project)[0]
        self.assertEqual((entry["status"], entry["agent"]), ("proposed", "codex"))

    def test_there_is_no_approval_tool(self):
        names = {tool["name"] for tool in mcp.TOOLS}
        self.assertEqual(names, {"list_projects", "project_for_folder", "search_memory", "get_handoff", "propose_memory", "project_activity", "active_sessions"})
        self.assertTrue(self.tool("accept_memory", {"project_id": self.project})["error"])

    def test_tool_errors_are_plain_text_not_reprs_or_internals(self):
        missing = self.tool("get_handoff", {"project_id": "00000000-0000-4000-8000-000000000000"})
        text = missing["result"]["content"][0]["text"]
        self.assertTrue(missing["result"]["isError"])
        self.assertFalse(text.startswith("'"), text)
        listed = self.tool(["list_projects"], {})
        self.assertNotIn("unhashable", json.dumps(listed))
        self.assertIn("error", listed)
        self.assertTrue(self.tool("get_handoff", {"project_id": self.project, "budget": 5})["result"]["isError"])

    def test_invalid_ids_are_rejected_and_the_server_keeps_going(self):
        replies = self.call([
            {"jsonrpc": "2.0", "id": None, "method": "ping"}, {"jsonrpc": "2.0", "id": [1], "method": "ping"},
            {"jsonrpc": "2.0", "id": True, "method": "ping"}, {"jsonrpc": "2.0", "id": 7, "method": "ping"}])
        self.assertEqual([reply.get("error", {}).get("code") for reply in replies], [-32600, -32600, -32600, None])
        self.assertEqual(replies[-1]["id"], 7)

    def test_oversized_line_is_refused_then_discarded_and_service_continues(self):
        huge = '{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":"' + "a" * (mcp.MAX_LINE + 10) + '"}}'
        replies = self.call([huge, {"jsonrpc": "2.0", "id": 2, "method": "ping"}])
        self.assertEqual(replies[0]["error"]["code"], -32600)
        self.assertEqual(replies[1], {"jsonrpc": "2.0", "id": 2, "result": {}})


class CLIRemediationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.env = isolated_env(self.base)
        for name in ("home", "claude-home", "codex-home"):
            (self.base / name).mkdir()

    def run_cli(self, *arguments, input_bytes=None, timeout=60, env=None, cwd=None):
        return subprocess.run([sys.executable, "-m", "filigree", *arguments], input=input_bytes, capture_output=True, timeout=timeout,
                              env={**(env or self.env), "PYTHONPATH": str(REPO)}, cwd=str(cwd or self.base))

    def argparse_rejects(self, *arguments):
        error = io.StringIO()
        with patch("sys.stderr", error), self.assertRaises(SystemExit) as caught:
            cli.main(["--data-dir", str(self.base / "memory"), *arguments])
        self.assertEqual(caught.exception.code, 2, arguments)
        return error.getvalue()

    def test_codex_toml_is_valid_with_platform_newlines_and_no_double_cr(self):
        emoji_dir = self.base / "mémoire 😀 日本"
        emoji_dir.mkdir()
        result = self.run_cli("--data-dir", str(emoji_dir), "mcp-config", "--client", "codex")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(b"\r\r", result.stdout)
        parsed = tomllib.loads(result.stdout.decode("utf-8"))["mcp_servers"]["filigree"]
        self.assertEqual(parsed["args"][parsed["args"].index("--data-dir") + 1], str(emoji_dir))
        self.assertEqual(parsed["command"], sys.executable)
        self.assertNotIn(b"\\ud83d", result.stdout.lower())

    def test_toml_strings_roundtrip_for_awkward_characters(self):
        for value in ('C:\\a "b"\\', "tab\there", "nl\nx", "\x01\x7f", "émoji 😀 日本", "a\\\\b"):
            self.assertEqual(tomllib.loads("v = " + cli._toml_string(value))["v"], value)

    def test_claude_config_is_valid_utf8_json(self):
        emoji_dir = self.base / "dé 😀"
        emoji_dir.mkdir()
        result = self.run_cli("--data-dir", str(emoji_dir), "mcp-config", "--client", "claude")
        entry = json.loads(result.stdout.decode("utf-8"))["mcpServers"]["filigree"]
        self.assertEqual(entry["args"][entry["args"].index("--data-dir") + 1], str(emoji_dir))

    def test_generated_config_launches_the_module_from_any_directory_when_not_installed(self):
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir()
        claude = json.loads(self.run_cli("--data-dir", str(self.base / "memory"), "mcp-config", "--client", "claude").stdout)["mcpServers"]["filigree"]
        codex = tomllib.loads(self.run_cli("--data-dir", str(self.base / "memory"), "mcp-config", "--client", "codex").stdout.decode("utf-8"))["mcp_servers"]["filigree"]
        for entry in (claude, codex):
            env = {key: value for key, value in self.env.items() if key != "PYTHONPATH"}
            env.update(entry.get("env", {}))
            request = b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
            launched = subprocess.run([entry["command"], *entry["args"]], input=request, capture_output=True, timeout=60, env=env, cwd=str(elsewhere))
            self.assertEqual(launched.returncode, 0, launched.stderr)
            self.assertEqual(json.loads(launched.stdout)["result"]["serverInfo"]["name"], "filigree")

    def test_mcp_over_real_stdio_keeps_utf8_in_and_out(self):
        folder = self.base / "projé 日本"
        folder.mkdir()
        memory = self.base / "memory"
        project = Store(memory).create_project("Projet", "", folder=folder)["id"]
        title = "Décision café 日本語 😀"
        lines = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "propose_memory", "arguments": {"project_id": project, "title": title, "body": "Corps é", "source_label": "séance 😀", "agent": "codex"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "project_for_folder", "arguments": {"folder": str(folder)}}},
        ]
        raw = "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines).encode("utf-8")
        result = self.run_cli("--data-dir", str(memory), "mcp", "--project-folder", str(folder), input_bytes=raw)  # MCP is scoped to one project
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(b"\r\n", result.stdout)
        replies = [json.loads(line) for line in result.stdout.decode("utf-8").splitlines()]
        self.assertEqual(Store(memory).list_entries(project)[0]["title"], title)
        found = json.loads(replies[-1]["result"]["content"][0]["text"])
        self.assertTrue(found["registered"])
        self.assertEqual(found["project"]["id"], project)

    def test_non_finite_and_out_of_range_numbers_are_rejected_by_argparse(self):
        for arguments in (("watch", "p", "f", "--interval", "nan"), ("watch", "p", "f", "--interval", "inf"), ("watch", "p", "f", "--interval", "-inf"),
                          ("capture", "run", "--interval", "nan"), ("capture", "run", "--interval", "inf"), ("capture", "run", "--interval", "1e999"),
                          ("serve", "--port", "70000"), ("serve", "--port", "-1"), ("serve", "--port", "x")):
            self.assertNotIn("Traceback", self.argparse_rejects(*arguments))

    def test_unknown_project_and_bad_budget_give_one_clean_line(self):
        for arguments in (("handoff", "00000000-0000-4000-8000-000000000000"), ("handoff", "x", "--budget", "3"), ("export", "../nope")):
            result = self.run_cli("--data-dir", str(self.base / "memory"), *arguments)
            error = result.stderr.decode("utf-8")
            self.assertEqual(result.returncode, 1, arguments)
            self.assertTrue(error.startswith("Filigree: "), error)
            self.assertNotIn("Traceback", error)
            self.assertNotIn("'Project", error)

    def test_import_of_a_non_utf8_file_is_a_clean_error(self):
        memory = self.base / "memory"
        folder = self.base / "dossier"
        folder.mkdir()
        project = Store(memory).create_project("P", "", folder=folder)["id"]
        bad = self.base / "bad.json"
        bad.write_bytes(b"\xff\xfe\x00bad")
        result = self.run_cli("--data-dir", str(memory), "import", project, str(bad))
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(b"Traceback", result.stderr)
        self.assertNotIn(b"codec", result.stderr)

    def test_watch_reports_an_unreadable_export_once_then_waits_for_a_change(self):
        memory = self.base / "memory"
        folder = self.base / "dossier"
        folder.mkdir()
        project = Store(memory).create_project("P", "", folder=folder)["id"]
        bad = self.base / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        process = subprocess.Popen([sys.executable, "-m", "filigree", "--data-dir", str(memory), "watch", project, str(bad), "--interval", "1"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**self.env, "PYTHONPATH": str(REPO)}, cwd=str(self.base))
        try:
            time.sleep(4.5)
        finally:
            process.terminate()
            out, err = process.communicate(timeout=20)
        self.assertEqual(err.decode("utf-8", "replace").count("Waiting for a complete readable export"), 1, err)
        self.assertNotIn(b"Traceback", err)


class SubprocessServerTests(unittest.TestCase):
    """Real `filigree serve` processes with synthetic, isolated sources."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.env = {**isolated_env(self.base), "PYTHONPATH": str(REPO)}
        self.processes = []
        self.addCleanup(self.stop_all)
        # A synthetic transcript a live monitor would import: it must stay untouched when capture is off.
        transcripts = self.base / "claude-home" / "projects" / "-synthetic"
        transcripts.mkdir(parents=True)
        (transcripts / "sess.jsonl").write_text(json.dumps({"type": "user", "sessionId": "s1", "cwd": str(self.base), "message": {"role": "user", "content": "Synthetic decision"}}) + "\n", encoding="utf-8")

    def stop_all(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
            for stream in (process.stdout, process.stderr):
                if stream:
                    stream.close()

    def launch(self, *arguments):
        process = subprocess.Popen([sys.executable, "-m", "filigree", "--data-dir", str(self.base / "memory"), "serve", *arguments],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, cwd=str(self.base))
        self.processes.append(process)
        return process

    def wait_port(self, process):
        line = process.stdout.readline().decode("utf-8")
        self.assertIn("http://127.0.0.1:", line, process.stderr.read1(2000) if process.poll() is not None else line)
        return int(line.rsplit(":", 1)[1])

    def call(self, port, method, path, body=None, token=None):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Filigree-Token"] = token
        connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        response = connection.getresponse()
        value = json.loads(response.read())
        connection.close()
        return response.status, value

    def test_no_capture_serve_cannot_be_turned_on_over_http_and_reads_no_source(self):
        process = self.launch("--port", "0", "--no-capture")
        port = self.wait_port(process)
        _, bootstrap = self.call(port, "GET", "/api/bootstrap")
        token = bootstrap["token"]
        self.assertEqual(self.call(port, "GET", "/api/capture", token=token)[1]["tap"]["capability"], "disabled")
        for action in ("enable", "start", "scan", "fallback-on"):
            code, value = self.call(port, "POST", "/api/capture", {"action": action}, token)
            self.assertEqual(code, 409, action)
        time.sleep(1.0)
        self.assertEqual(self.call(port, "GET", "/api/projects", token=token)[1], [])
        self.assertFalse((self.base / "memory" / ".capture").exists())
        self.assertFalse((self.base / "absent-tap").exists())

    def test_second_serve_on_the_same_port_fails_cleanly(self):
        first = self.launch("--port", "0", "--no-capture")
        port = self.wait_port(first)
        second = self.launch("--port", str(port), "--no-capture")
        _, err = second.communicate(timeout=30)
        self.assertEqual(second.returncode, 1)
        self.assertIn("Impossible d'écouter", err.decode("utf-8"))
        self.assertNotIn(b"Traceback", err)
        token = self.call(port, "GET", "/api/bootstrap")[1]["token"]
        self.assertEqual(self.call(port, "GET", "/api/capture", token=token)[0], 200)  # the first server still owns the port


if __name__ == "__main__":
    unittest.main()
