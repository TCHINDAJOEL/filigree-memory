import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from filigree.server import LocalServer
from filigree.store import Store


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name).resolve()
        self.folder = base / "projet"
        self.folder.mkdir()
        # Capture status probes a database path: keep it synthetic and absent.
        environment = patch.dict(os.environ, {"CLOUDTAP_DB": str(base / "absent" / "traces.sqlite3")})
        environment.start()
        self.addCleanup(environment.stop)
        self.server = LocalServer(("127.0.0.1", 0), Store(base / "memory"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None, token=True):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        request_headers = {"Content-Type": "application/json"}
        if token:
            request_headers["X-Filigree-Token"] = self.server.token
        request_headers.update(headers or {})
        connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=request_headers)
        response = connection.getresponse()
        data = response.read()
        code, result_headers = response.status, dict(response.getheaders())
        connection.close()
        return code, json.loads(data) if "application/json" in result_headers.get("Content-Type", "") else data, result_headers

    def test_static_and_bootstrap_work_without_network_assets(self):
        code, body, headers = self.request("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b"Filigree", body)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        code, value, _ = self.request("GET", "/api/bootstrap")
        self.assertEqual(value["projects"], [])
        self.assertTrue(value["token"])

    def test_dns_rebinding_cross_origin_and_missing_token_are_rejected(self):
        for headers, token in (({"Host": "evil.example"}, True), ({"Origin": "https://evil.example"}, True), ({"Sec-Fetch-Site": "cross-site"}, True), ({}, False)):
            code, _, _ = self.request("POST", "/api/projects", {"name": "No"}, headers, token)
            self.assertEqual(code, 403)
        self.assertEqual(self.server.store.list_projects(), [])

    def test_project_review_import_and_handoff_flow(self):
        code, project, _ = self.request("POST", "/api/projects", {"name": "Project", "description": "Human and agent continuity", "folder": str(self.folder)})
        self.assertEqual(code, 201)
        base = f"/api/projects/{project['id']}"
        code, result, _ = self.request("POST", base + "/import", {"format": "text", "source": "Meeting", "text": "A proposal"})
        self.assertEqual(code, 200)
        entry = result["entries"][0]
        code, accepted, _ = self.request("PATCH", base + "/entries/" + entry["id"], {"revision": entry["revision"], "status": "accepted"})
        self.assertEqual(code, 200)
        self.assertEqual(accepted["status"], "accepted")
        code, _, _ = self.request("PATCH", base + "/entries/" + entry["id"], {"revision": entry["revision"], "body": "Stale"})
        self.assertEqual(code, 409)
        code, handoff, _ = self.request("GET", base + "/handoff")
        self.assertIn("A proposal", handoff["text"])
        code, exported, headers = self.request("GET", base + "/export")
        self.assertIn(b"A proposal", exported)
        self.assertIn("attachment", headers["Content-Disposition"])

    def test_public_creation_requires_an_existing_absolute_folder(self):
        for body in ({"name": "Sans dossier"}, {"name": "Relatif", "folder": "relative/path"}, {"name": "Absent", "folder": str(self.folder / "nope")}, {"name": "Fichier", "folder": __file__}):
            code, _, _ = self.request("POST", "/api/projects", body)
            self.assertEqual(code, 400, body)
        self.assertEqual(self.server.store.list_projects(), [])

    def test_one_folder_belongs_to_one_project_and_legacy_projects_can_be_attached(self):
        code, first, _ = self.request("POST", "/api/projects", {"name": "Un", "folder": str(self.folder)})
        self.assertEqual(code, 201)
        self.assertEqual(first["folder_state"], "ok")
        code, _, _ = self.request("POST", "/api/projects", {"name": "Deux", "folder": str(self.folder)})
        self.assertEqual(code, 409)
        legacy = self.server.store.create_project("Ancien projet")
        self.assertEqual(legacy["folder_state"], "unbound")
        other = Path(self.temp.name).resolve() / "autre"
        other.mkdir()
        code, attached, _ = self.request("PATCH", f"/api/projects/{legacy['id']}", {"folder": str(other)})
        self.assertEqual(code, 200)
        self.assertEqual(Path(attached["folder"]["path"]), other)
        code, _, _ = self.request("PATCH", f"/api/projects/{legacy['id']}", {"folder": str(self.folder)})
        self.assertEqual(code, 409)
        code, _, _ = self.request("PATCH", f"/api/projects/{legacy['id']}", {"name": "x"})
        self.assertEqual(code, 400)

    def test_capture_status_and_controls_are_token_protected(self):
        code, status, _ = self.request("GET", "/api/capture")
        self.assertEqual(code, 200)
        self.assertEqual(status["tap"]["capability"], "missing")
        self.assertTrue(status["enabled"] and status["auto_create"])
        code, _, _ = self.request("POST", "/api/capture", {"action": "pause"}, token=False)
        self.assertEqual(code, 403)
        code, result, _ = self.request("POST", "/api/capture", {"action": "pause"})
        self.assertEqual(code, 200)
        self.assertTrue(result["status"]["paused_all"])
        code, result, _ = self.request("POST", "/api/capture", {"action": "resume"})
        self.assertFalse(result["status"]["paused_all"])
        code, result, _ = self.request("POST", "/api/capture", {"action": "exclude", "folder": str(self.folder)})
        self.assertEqual([Path(item) for item in result["status"]["exclude"]], [self.folder])
        code, _, _ = self.request("POST", "/api/capture", {"action": "exclude", "folder": str(self.folder / "absent")})
        self.assertEqual(code, 400)
        code, _, _ = self.request("POST", "/api/capture", {"action": "explode"})
        self.assertEqual(code, 400)

    def test_capture_link_validates_the_project_and_key(self):
        code, _, _ = self.request("POST", "/api/capture", {"action": "link", "key": "tap:T1", "project_id": "00000000-0000-4000-8000-000000000000"})
        self.assertEqual(code, 404)
        code, project, _ = self.request("POST", "/api/projects", {"name": "P", "folder": str(self.folder)})
        code, _, _ = self.request("POST", "/api/capture", {"action": "link", "key": "not valid!", "project_id": project["id"]})
        self.assertEqual(code, 400)
        code, result, _ = self.request("POST", "/api/capture", {"action": "link", "key": "tap:T1", "project_id": project["id"]})
        self.assertEqual(code, 200)
        self.assertEqual(result["status"]["mappings"], 1)

    def test_invalid_payload_does_not_mutate_store(self):
        code, _, _ = self.request("POST", "/api/projects", {"name": ["wrong type"]})
        self.assertEqual(code, 400)
        code, _, _ = self.request("GET", "/api/projects/../../etc/passwd")
        self.assertEqual(code, 400)
        self.assertEqual(self.server.store.list_projects(), [])


if __name__ == "__main__":
    unittest.main()
