"""Projects belong to real local folders; legacy projects stay usable; provenance survives in the entry."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from filigree.demo import seed_demo
from filigree.store import ConflictError, Store, canonical_folder, folder_key


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.store = Store(self.base / "memory")
        self.work = self.base / "work"
        (self.work / "app" / "src").mkdir(parents=True)
        (self.work / "other").mkdir()

    def test_canonical_folder_requires_an_existing_absolute_directory(self):
        for bad in ("", "relative/dir", str(self.work / "missing"), str(self.work / "app" / "nope" / "..")):
            with self.assertRaises(ValueError, msg=bad):
                canonical_folder(bad)
        file = self.work / "file.txt"
        file.write_text("x", encoding="utf-8")
        with self.assertRaises(ValueError):
            canonical_folder(str(file))
        with self.assertRaises(ValueError):
            canonical_folder(Path.cwd().anchor)
        with self.assertRaises(ValueError):
            canonical_folder(str(Path.home()))
        with self.assertRaises(ValueError):
            self.store.canonical_folder(str(self.store.root))
        with self.assertRaises(ValueError):
            self.store.canonical_folder(str(self.store.root / "projects"))

    def test_same_folder_gives_the_same_key_however_it_is_spelled(self):
        spelled = str(self.work / "app" / "src" / "..")
        first = canonical_folder(str(self.work / "app"))
        self.assertEqual(canonical_folder(spelled), first)
        self.assertEqual(first["key"], folder_key(self.work / "app"))

    def test_one_folder_one_project_nested_projects_allowed_and_nearest_wins(self):
        outer = self.store.create_project("Dépôt", folder=str(self.work / "app"))
        with self.assertRaises(ConflictError):
            self.store.create_project("Doublon", folder=str(self.work / "app" / "src" / ".."))
        inner = self.store.create_project("Sous-projet", folder=str(self.work / "app" / "src"))
        self.assertEqual(self.store.project_for_path(str(self.work / "app" / "src"))["id"], inner["id"])
        (self.work / "app" / "src" / "pkg").mkdir()
        self.assertEqual(self.store.project_for_path(str(self.work / "app" / "src" / "pkg"))["id"], inner["id"])
        self.assertEqual(self.store.project_for_path(str(self.work / "app"))["id"], outer["id"])
        self.assertIsNone(self.store.project_for_path(str(self.work / "other")))
        with self.assertRaises(ValueError):
            self.store.project_for_path("relative")

    def test_legacy_project_is_unbound_until_a_folder_is_attached(self):
        legacy = self.store.create_project("Ancien")
        self.assertEqual(legacy["folder_state"], "unbound")
        self.assertNotIn("folder", legacy)
        attached = self.store.attach_folder(legacy["id"], str(self.work / "other"))
        self.assertEqual(Path(attached["folder"]["path"]), self.work / "other")
        self.assertEqual(self.store.attach_folder(legacy["id"], str(self.work / "other"))["folder"], attached["folder"])
        with self.assertRaises(ConflictError):
            self.store.attach_folder(legacy["id"], str(self.work / "app"))
        taken = self.store.create_project("Pris", folder=str(self.work / "app"))
        spare = self.store.create_project("Libre")
        with self.assertRaises(ConflictError):
            self.store.attach_folder(spare["id"], str(self.work / "app"))
        self.assertEqual(self.store.get_project(taken["id"])["folder_state"], "ok")

    def test_deleted_folder_is_reported_and_project_stays_readable(self):
        project = self.store.create_project("Éphémère", folder=str(self.work / "other"))
        shutil.rmtree(self.work / "other")
        self.assertEqual(self.store.get_project(project["id"])["folder_state"], "missing")
        self.assertEqual(Store(self.store.root).get_project(project["id"])["folder"]["key"], project["folder"]["key"])

    def test_demo_gets_its_own_real_empty_folder_and_is_flagged(self):
        first = seed_demo(self.store, folder=str(self.work / "other"))
        self.assertTrue(first["demo"])
        self.assertTrue(Path(first["folder"]["path"]).is_dir())
        second = seed_demo(self.store)
        self.addCleanup(shutil.rmtree, second["folder"]["path"], True)
        self.assertNotEqual(first["folder"]["key"], second["folder"]["key"])
        self.assertEqual(list(Path(second["folder"]["path"]).iterdir()), [])

    def test_captured_provenance_and_tags_live_inside_the_entry_file(self):
        project = self.store.create_project("Capture", folder=str(self.work / "app"))
        event = {"title": "Observation", "body": "Une commande a échoué", "agent": "Claude Code", "episode": "S1",
                 "sources": [{"label": "claude-tap · T1 #1", "uri": "tap:T1:1:user-0", "excerpt": "extrait"}],
                 "tags": ["capture", "claude-tap"], "provenance": {"tap_session_id": "T1", "record_index": 1, "native_id": "S1", "api_key": "sk-secret-value"}}
        imported = self.store.import_events(project["id"], [event], "claude-tap", internal=True)["entries"][0]
        self.assertEqual(imported["status"], "proposed")
        self.assertEqual(imported["tags"], ["imported", "capture", "claude-tap"])
        reopened = Store(self.store.root).list_entries(project["id"])[0]
        provenance = json.loads(next(item for item in reopened["sources"] if item["label"] == "Provenance de capture")["excerpt"])
        self.assertEqual((provenance["tap_session_id"], provenance["record_index"], provenance["native_id"]), ("T1", 1, "S1"))
        self.assertNotIn("sk-secret-value", json.dumps(reopened))
        # Untrusted imports cannot inject tags or provenance.
        plain = self.store.import_events(project["id"], [dict(event, body="Autre", sources=[])], "import")["entries"][0]
        self.assertEqual(plain["tags"], ["imported"])
        self.assertFalse(any(item["label"] == "Provenance de capture" for item in plain["sources"]))

    def test_replayed_capture_event_is_deduplicated_even_if_provenance_differs(self):
        project = self.store.create_project("Capture", folder=str(self.work / "app"))
        event = {"title": "T", "body": "Corps", "agent": "Codex", "sources": [{"label": "l", "uri": "tap:T1:2:assistant-0", "excerpt": "Corps"}], "provenance": {"link": "native"}}
        self.assertEqual(self.store.import_events(project["id"], [event], "claude-tap", internal=True)["imported"], 1)
        again = self.store.import_events(project["id"], [dict(event, provenance={"link": "explicit"})], "claude-tap", internal=True)
        self.assertEqual((again["imported"], again["duplicates"]), (0, 1))


if __name__ == "__main__":
    unittest.main()
