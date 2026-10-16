import tempfile
import unittest
from pathlib import Path

from filigree.store import Store, redact

GHP = "ghp_" + "Zy9Xw8Vv7Uu6Tt5Ss4Rr3Qq2Pp1Oo0Nn"
ANT = "sk-ant-" + "Zy9Xw8Vv7Uu6Tt5Ss4Rr3Qq2Pp1"
URL_PASSWORD = "pa55/Zq7Lm2Xc9Vb"
FRAGMENTS = (GHP[4:20], ANT[7:23], URL_PASSWORD, "Zq7Lm2Xc9Vb")


def all_text(root):
    return "\n".join(path.read_text("utf8", "replace") for path in Path(root).rglob("*") if path.is_file())


class PrivacyRetakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        (self.base / "work").mkdir()
        self.store = Store(self.base / "memory")
        self.pid = self.store.create_project("P", "", folder=str(self.base / "work"))["id"]

    def assertNoFragment(self, text, label):
        leaked = [index for index, fragment in enumerate(FRAGMENTS) if fragment in text]
        self.assertFalse(leaked, f"fragment survives in {label}: {leaked}")  # never print the text

    def test_known_prefix_glued_to_word_characters_is_masked(self):
        for glued in ("qqqq" + GHP, "token:" + GHP, "xx" + ANT, "foo-" + ANT):
            clean, count = redact("avant " + glued + " apres")
            self.assertNoFragment(clean, glued[:6])
            self.assertGreaterEqual(count, 1)

    def test_url_password_with_raw_slash_is_masked(self):
        for url in (f"postgres://admin:{URL_PASSWORD}@db.example.test/app", f"https://u:{URL_PASSWORD}@host.test:8443/x"):
            clean, count = redact("voir " + url + " ok")
            self.assertNoFragment(clean, url[:8])
            self.assertIn("@", clean)
            self.assertIn("host" if "host" in url else "db.example.test", clean)
            self.assertGreaterEqual(count, 1)
            self.assertEqual(redact(clean)[0], clean)  # idempotent

    def test_benign_text_and_links_are_preserved(self):
        for prose in (
            "see https://medium.com/@someone/post and https://example.test:8080/@name/page",
            "risk-assessment-framework-document and task-list-with-long-name-here",
            "mail me at a@b.test, path https://example.test/a/b?x=a@b",
            "the ghp prefix and sk-ant naming are documented; xox is short",
            "https://example.test:443/path/file.txt then user@host",
        ):
            self.assertEqual(redact(prose), (prose, 0), prose)

    def test_persisted_current_history_events_export_and_handoff_are_clean(self):
        text = f"note qqqq{GHP} et foo{ANT} lien postgres://admin:{URL_PASSWORD}@db.example.test/app fin. Prose sure."
        entry = self.store.create_entry(self.pid, {"title": "t " + text, "body": text, "kind": "observation", "status": "proposed"})
        self.store.update_entry(self.pid, entry["id"], {"revision": entry["revision"], "body": text + " revision deux", "reason": "r " + text})
        self.store.import_events(self.pid, [{"title": "ev", "body": text}], "claude-tap", internal=True)
        self.store.import_events(self.pid, [{"title": "ev2", "body": text}], "claude-tap")
        self.assertNoFragment(all_text(self.base / "memory"), "files (current, history, events)")
        self.assertNoFragment(self.store.export_markdown(self.pid), "export")
        handoff = self.store.handoff(self.pid, "", 100000)["text"]
        self.assertNoFragment(handoff, "handoff")
        self.assertIn("Prose sure.", all_text(self.base / "memory"))
        self.assertIn("db.example.test", all_text(self.base / "memory"))


if __name__ == "__main__":
    unittest.main()
