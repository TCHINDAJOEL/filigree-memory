"""Project counts are cached per entries folder: listing projects must not re-parse every entry, yet stay exact."""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from filigree.store import Store


class ProjectCountsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.store.CACHE_SETTLE_SECONDS = 0
        self.project = self.store.create_project("Comptes")
        self.entry = self.store.create_entry(self.project["id"], {"title": "Une proposition", "body": "texte"})
        self.entries = self.store.root / "projects" / self.project["id"] / ".filigree" / "entries"

    def tearDown(self):
        self.temp.cleanup()

    def settle(self):
        """Age the entries folder past the settle window, as real time would."""
        old = time.time() - 60
        os.utime(self.entries, (old, old))

    def test_an_unchanged_project_is_not_reparsed(self):
        self.settle()
        self.assertEqual(self.store.get_project(self.project["id"])["counts"]["total"], 1)
        with patch.object(Store, "_entries_checked", side_effect=AssertionError("re-parsed")):
            self.assertEqual(self.store.list_projects()[0]["counts"]["proposed"], 1)

    def test_a_status_change_is_counted_at_once(self):
        self.settle()
        self.store.get_project(self.project["id"])
        self.store.update_entry(self.project["id"], self.entry["id"], {"status": "accepted", "revision": self.entry["revision"]})
        counts = self.store.get_project(self.project["id"])["counts"]
        self.assertEqual((counts["proposed"], counts["accepted"], counts["total"]), (0, 1, 1))

    def test_a_new_entry_is_counted_at_once(self):
        self.settle()
        self.store.get_project(self.project["id"])
        self.store.create_entry(self.project["id"], {"title": "Une autre", "body": "texte"})
        self.assertEqual(self.store.get_project(self.project["id"])["counts"]["total"], 2)

    def test_a_young_folder_is_never_trusted(self):
        self.store.CACHE_SETTLE_SECONDS = 3600
        self.store.get_project(self.project["id"])
        self.assertNotIn(self.project["id"], self.store._counts)

    def test_an_in_place_edit_is_seen_after_the_revalidation_window(self):
        self.settle()
        self.store.get_project(self.project["id"])
        path = self.entries / f"{self.entry['id']}.md"
        stat = path.stat()
        path.write_text(path.read_text(encoding="utf-8").replace("\"status\": \"proposed\"", "\"status\": \"rejected\""), encoding="utf-8")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.settle()
        self.store.CACHE_REVALIDATE_SECONDS = 0
        self.assertEqual(self.store.get_project(self.project["id"])["counts"]["rejected"], 1)

    def test_returned_counts_are_copies(self):
        self.settle()
        self.store.get_project(self.project["id"])["counts"]["total"] = 99
        self.assertEqual(self.store.get_project(self.project["id"])["counts"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
