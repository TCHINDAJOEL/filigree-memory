"""Final integration regressions: response delivery when a request body is left unread (synthetic data only)."""

import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from filigree.server import LocalServer
from filigree.store import Store


class UnreadBodyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name).resolve()
        environment = patch.dict(os.environ, {"CLOUDTAP_DB": str(base / "absent" / "traces.sqlite3")})
        environment.start()
        self.addCleanup(environment.stop)
        self.server = LocalServer(("127.0.0.1", 0), Store(base / "memory"), capture_enabled=False)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def raw(self, method, length_header, payload=b"", extra="", path="/api/projects", host=None):
        """One raw request; returns (status, headers text, body). Reads to EOF within a hard 5 s bound."""
        head = f"{method} {path} HTTP/1.1\r\nHost: {host or f'127.0.0.1:{self.port}'}\r\nContent-Type: application/json\r\nConnection: close\r\n{length_header}{extra}\r\n"
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(head.encode() + payload)
            chunks = []
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                data = sock.recv(65536)
                if not data:
                    break
                chunks.append(data)
        raw = b"".join(chunks)
        header, _, body = raw.partition(b"\r\n\r\n")
        status = int(header.split(b" ", 2)[1]) if header else 0
        return status, header.decode("latin-1"), body

    def test_405_is_delivered_for_every_body_shape_repeatedly(self):
        shapes = {
            "small": ("Content-Length: 2\r\n", b"{}"),
            "large": ("Content-Length: 600000\r\n", b"x" * 600000),
            "declared-not-sent": ("Content-Length: 5000000\r\n", b""),
            "missing": ("", b""),
            "malformed": ("Content-Length: abc\r\n", b"{}"),
            "negative": ("Content-Length: -4\r\n", b"{}"),
            "chunked": ("Transfer-Encoding: chunked\r\n", b"2\r\n{}\r\n0\r\n\r\n"),
        }
        for method in ("PUT", "DELETE", "OPTIONS", "HEAD"):
            for name, (length, payload) in shapes.items():
                for attempt in range(6):
                    started = time.monotonic()
                    status, header, body = self.raw(method, length, payload)
                    label = f"{method} {name} #{attempt}"
                    self.assertEqual(status, 405, label)
                    self.assertIn("Content-Security-Policy", header, label)
                    self.assertLess(time.monotonic() - started, 4, label)
                    if method == "HEAD":
                        self.assertEqual(body, b"", label)
                    else:
                        self.assertIn(b"error", body, label)

    def test_403_and_400_are_delivered_when_the_body_was_not_read(self):
        token = f"X-Filigree-Token: {self.server.token}\r\n"
        for attempt in range(6):
            status, _, body = self.raw("POST", "Content-Length: 300000\r\n", b"x" * 300000, host="evil.example")
            self.assertEqual(status, 403, attempt)
            self.assertIn(b"error", body)
            status, _, _ = self.raw("POST", "Content-Length: 300000\r\n", b"x" * 300000)  # no token
            self.assertEqual(status, 403, attempt)
            status, _, _ = self.raw("POST", "Content-Length: 300000\r\n", b"x" * 300000, extra="X-Filigree-Token: nope\r\n")
            self.assertEqual(status, 403, attempt)
            status, _, _ = self.raw("POST", "Content-Length: 99999999\r\n", b"{}", extra=token)
            self.assertEqual(status, 400, attempt)

    def test_the_drain_is_bounded_when_the_client_never_finishes(self):
        head = f"PUT /api/projects HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nContent-Length: 50000000\r\n\r\n".encode()
        with socket.create_connection(("127.0.0.1", self.port), timeout=8) as sock:
            sock.sendall(head)
            started = time.monotonic()
            self.assertIn(b" 405 ", sock.recv(65536))
            while sock.recv(65536):  # the server must close by itself although the client stays silent
                pass
        self.assertLess(time.monotonic() - started, 5)


class ConnectionBurstTests(unittest.TestCase):
    def test_a_burst_of_simultaneous_connections_is_all_served(self):
        """A page load plus polling opens many connections at once; none may be refused or reset (listen backlog)."""
        import http.client
        with tempfile.TemporaryDirectory() as temp:
            server = LocalServer(("127.0.0.1", 0), Store(Path(temp) / "memory"), capture_enabled=False)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            failures, gate = [], threading.Barrier(64)

            def hit():
                try:
                    gate.wait(10)
                    for _ in range(5):
                        connection = http.client.HTTPConnection(*server.server_address, timeout=10)
                        connection.request("GET", "/api/bootstrap")
                        response = connection.getresponse()
                        response.read()
                        if response.status != 200:
                            failures.append(response.status)
                        connection.close()
                except Exception as exc:  # noqa: BLE001 - every failure kind is a finding
                    failures.append(repr(exc))

            workers = [threading.Thread(target=hit) for _ in range(64)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(60)
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(failures, [])
        self.assertGreaterEqual(LocalServer.request_queue_size, 64)


class CorrectionTrailTests(unittest.TestCase):
    """Corrections on a superseded entry and actor-label edits stay append-only: revisions and events remain, no status resurrection."""

    def test_title_body_and_actor_label_edits_leave_a_readable_trail(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            (base / "dossier").mkdir()
            store = Store(base / "memory")
            project = store.create_project("Projet", "", folder=base / "dossier")
            pid = project["id"]
            make = lambda title, **more: store.create_entry(pid, {"title": title, "body": "Corps", "kind": "decision", "status": "proposed", "agent": "Alice", "tags": [], "sources": [], "relations": [], **more}, channel="http-ui")
            old = make("Choix initial")
            old = store.update_entry(pid, old["id"], {"revision": old["revision"], "status": "accepted"}, channel="http-ui")
            new = make("Remplaçant")
            new = store.update_entry(pid, new["id"], {"revision": new["revision"], "status": "accepted", "relations": [{"target": old["id"], "type": "supersedes"}]}, channel="http-ui")
            current = next(e for e in store.list_entries(pid) if e["id"] == old["id"])
            self.assertEqual(current["status"], "superseded")
            before = len(store.list_events(pid))
            fixed = store.update_entry(pid, old["id"], {"revision": current["revision"], "title": "Choix initial (titre corrigé)", "agent": "Bob"}, channel="http-ui")
            self.assertEqual(fixed["status"], "superseded")
            self.assertEqual(fixed["revision"], current["revision"] + 1)
            history = store.list_history(pid, old["id"])
            self.assertEqual([h["revision"] for h in history], list(range(fixed["revision"], 0, -1)))
            self.assertEqual(history[1]["title"], "Choix initial")
            self.assertEqual(history[1]["agent"], "Alice")
            self.assertEqual(len(store.list_events(pid)), before + 1)
            self.assertEqual({e["channel"] for e in store.list_events(pid)}, {"http-ui"})
            with self.assertRaises(ValueError):  # no resurrection
                store.update_entry(pid, old["id"], {"revision": fixed["revision"], "status": "accepted"}, channel="http-ui")
            self.assertEqual(next(e for e in store.list_entries(pid) if e["id"] == old["id"])["status"], "superseded")


if __name__ == "__main__":
    unittest.main()
