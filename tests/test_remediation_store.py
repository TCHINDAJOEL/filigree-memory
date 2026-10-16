"""Regression coverage for the independent-verification findings in store / importers / git_sync / demo.

Everything here uses synthetic data in temporary directories; fake credentials are obviously invented.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from filigree import git_sync
from filigree.demo import seed_demo
from filigree.importers import content_text, decode_import_bytes, parse_import, parse_import_detailed
from filigree.store import ConflictError, Store, canonical_folder, folder_key, redact

# (text containing a synthetic secret, the fragment that must never survive)
SECRET_CASES = [
    ("X_API_KEY=fakevalue123456", "fakevalue123456"),
    ("DB_PASSWORD=hunter2hunter2", "hunter2hunter2"),
    ("postgres://user:fakepass123@db.example.org:5432/app", "fakepass123"),
    ("mysql://admin:p%40ssfake@host/db", "p%40ssfake"),
    ("https://faketokenonly@example.org/repo.git", "faketokenonly"),
    ("export AWS_SECRET_ACCESS_KEY=wJalrFAKEKEY/K7MDENG/bPxRfiCY", "wJalrFAKEKEY"),
    ("AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
    ("xoxb-123456789012-abcdefghijkl", "abcdefghijkl"),
    ("AIzaSyA1234567890abcdefghijklmnopqrstuvw", "AIzaSyA1234567890"),
    ("sk_live_abcdefghijklmnop", "abcdefghijklmnop"),
    ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJmYWtlIn0.c2lnbmF0dXJl", "eyJzdWIiOiJmYWtlIn0"),
    ("Authorization: Basic dXNlcjpwYXNzd29yZA==", "dXNlcjpwYXNzd29yZA"),
    ("Authorization: Bearer fake.token.value", "fake.token.value"),
    ("client_secret = fakeclientsecret99", "fakeclientsecret99"),
    ("secret_key: fakesecretkey99", "fakesecretkey99"),
    ('{"password": "fake pass phrase"}', "pass phrase"),
    ('{\\"password\\": \\"fake pass phrase\\"}', "pass phrase"),
    ("TOKEN='two words here'", "words here"),
    ("ghp_abcdefghijklmnopqrstuvwxyz0123", "abcdefghijklmnopqrstuvwxyz0123"),
    ("https://hooks.slack.com/services/T000/B000/fakefakefake", "fakefakefake"),
    ("Cookie: session=fakecookievalue1", "fakecookievalue1"),
    ("?access_token=fakeaccess99&page=2", "fakeaccess99"),
]


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.store = Store(self.base / "memory")
        self.work = self.base / "work"
        self.work.mkdir()
        self.project = self.store.create_project("Projet", "Objectif", folder=str(self.work))
        self.pid = self.project["id"]

    def entries_dir(self, pid=None):
        return self.store.root / "projects" / (pid or self.pid) / ".filigree" / "entries"

    def create(self, **data):
        return self.store.create_entry(self.pid, {"title": "Titre", **data})


class RedactionTests(Base):  # B-1 / A-6 / E-1
    def test_secrets_never_reach_any_stored_text_field_or_file(self):
        for text, fragment in SECRET_CASES:
            with self.subTest(text=text):
                self.assertLessEqual(len(text), 80)
                entry = self.create(title="t " + text, body=text, episode=text, agent=text, tags=[text],
                                    sources=[{"label": text, "excerpt": text, "uri": ""}])
                self.assertNotIn(fragment, json.dumps(entry, ensure_ascii=False))
                self.assertIn("[REDACTED]", entry["body"])
                project = self.store.create_project(text, text)
                self.assertNotIn(fragment, json.dumps(project, ensure_ascii=False))
                result = self.store.import_events(self.pid, [{"body": text, "sources": [{"label": text, "excerpt": text, "uri": text}]}], text)
                self.assertNotIn(fragment, json.dumps(result["entries"], ensure_ascii=False))
        for path in self.store.root.rglob("*"):
            if path.is_file() and path.name != ".filigree.lock":
                content = path.read_text(encoding="utf-8")
                for _, fragment in SECRET_CASES:
                    self.assertNotIn(fragment, content, path.name)

    def test_secret_in_url_field_and_review_reason_is_masked(self):
        entry = self.create(sources=[{"label": "l", "excerpt": "", "uri": "https://user:fakepass123@example.org/x"}])
        self.assertNotIn("fakepass123", json.dumps(entry))
        updated = self.store.update_entry(self.pid, entry["id"], {"revision": 1, "reason": "leak DB_PASSWORD=fakepass456"})
        self.assertNotIn("fakepass456", json.dumps(self.store.list_events(self.pid)))
        self.assertEqual(updated["revision"], 2)

    def test_redaction_is_idempotent_and_does_not_inflate_counts(self):
        for text, _ in SECRET_CASES:
            once, count = redact(text)
            twice, again = redact(once)
            self.assertGreaterEqual(count, 1, text)
            self.assertEqual((twice, again), (once, 0), text)

    def test_ordinary_prose_and_plural_names_are_not_over_redacted(self):
        for text in ("Bearer of bad news", "max_tokens: 100", "Author: Ana", "Le token est expliqué plus bas", "tokenizer = fast"):
            self.assertEqual(redact(text), (text, 0), text)

    def test_dictionary_keys_with_prefixes_are_masked(self):
        clean, count = redact({"DB_PASSWORD": "x", "X_API_KEY": "y", "max_tokens": 5, "nested": {"client_secret": "z"}})
        self.assertEqual((clean["DB_PASSWORD"], clean["X_API_KEY"], clean["max_tokens"], clean["nested"]["client_secret"]), ("[REDACTED]", "[REDACTED]", 5, "[REDACTED]"))
        self.assertEqual(count, 3)

    def test_long_inputs_are_processed_in_bounded_time(self):
        started = time.monotonic()
        for text in ("a" * 300000, "token" * 60000, "password=" + "x" * 300000, "-----BEGIN PRIVATE KEY-----" + "A" * 100000):
            redact(text)
        self.assertLess(time.monotonic() - started, 10)

    def test_unterminated_private_key_block_is_masked_to_the_end(self):
        clean, count = redact("before -----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk")
        self.assertEqual((clean, count), ("before [REDACTED]", 1))


class FolderTests(Base):  # A-4 / A-14 / B-7
    @unittest.skipUnless(os.name == "nt", "Windows extended-length paths")
    def test_extended_length_alias_is_the_same_folder(self):
        folder = self.work / "x"
        folder.mkdir()
        plain = canonical_folder(str(folder))
        extended = canonical_folder("\\\\?\\" + str(folder))
        self.assertEqual(plain, extended)
        self.assertEqual(folder_key("\\\\?\\" + str(folder)), folder_key(folder))
        self.store.create_project("A", folder=str(folder))
        with self.assertRaises(ConflictError):
            self.store.create_project("B", folder="\\\\?\\" + str(folder))

    @unittest.skipUnless(os.name == "nt", "Windows extended-length paths")
    def test_legacy_project_stored_with_extended_prefix_still_owns_its_folder(self):
        folder = self.work / "legacy"
        folder.mkdir()
        legacy = self.store.create_project("Legacy")
        path = self.store.root / "projects" / legacy["id"] / "project.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        extended = "\\\\?\\" + str(folder)
        data["folder"] = {"path": extended, "key": "stale-" + folder_key(extended)}
        path.write_text(json.dumps(data), encoding="utf-8")
        fresh = Store(self.store.root)
        with self.assertRaises(ConflictError):
            fresh.create_project("Duplicate", folder=str(folder))
        self.assertEqual(fresh.project_for_path(str(folder))["id"], legacy["id"])

    def test_generic_system_roots_are_rejected_but_temp_subfolders_are_fine(self):
        unsafe = [tempfile.gettempdir(), str(Path.home().parent)]
        if os.environ.get("SystemRoot"):
            unsafe += [os.environ["SystemRoot"], str(Path(os.environ["SystemRoot"]) / "System32")]
        for candidate in unsafe:
            if Path(candidate).is_dir():
                with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                    canonical_folder(candidate)
        allowed = self.work / "sous-projet de test"
        allowed.mkdir()
        self.assertEqual(Path(canonical_folder(str(allowed))["path"]), allowed)

    def test_folder_containing_the_memory_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.canonical_folder(str(self.base))
        with self.assertRaises(ValueError):
            self.store.create_project("Racine", folder=str(self.base))

    def test_project_names_must_be_one_line(self):
        for name in ("a\nb", "a\rb", "tab\there", "nul\x00"):
            with self.subTest(name=repr(name)), self.assertRaises(ValueError):
                self.store.create_project(name)


class QuarantineTests(Base):  # A-3
    def test_stray_and_damaged_files_are_quarantined_and_healthy_data_stays_accessible(self):
        good = self.create(title="Sain", body="reste visible", status="accepted", kind="decision")
        edited = self.create(title="Titre d'origine", body="x")
        broken_event = self.store.root / "projects" / self.pid / ".filigree" / "events" / "bad.json"
        broken_event.write_text("{not json", encoding="utf-8")
        (self.entries_dir() / "README.md").write_text("# notes de l'équipe\n", encoding="utf-8")
        edited_path = self.entries_dir() / (edited["id"] + ".md")
        edited_path.write_bytes(edited_path.read_bytes().replace(b"# Titre d'origine", b"# Titre modifie"))
        second_folder = self.work / "second"
        second_folder.mkdir()
        second = self.store.create_project("Deuxieme", folder=str(second_folder))
        (self.store.root / "projects" / second["id"] / "project.json").write_text("{corrompu", encoding="utf-8")
        (self.store.root / "projects" / "pas-un-projet").mkdir()
        (self.store.root / "projects" / "pas-un-projet" / "project.json").write_text("{}", encoding="utf-8")
        (self.store.root / "projects" / "README.md").write_text("stray", encoding="utf-8")
        def snapshot():
            return {path: path.read_bytes() for path in self.store.root.rglob("*") if path.is_file() and path.name not in {".filigree.lock", ".filigree-generation"}}

        before = snapshot()

        for store in (self.store, Store(self.store.root)):
            self.assertEqual([entry["id"] for entry in store.list_entries(self.pid)], [good["id"]])
            self.assertEqual([project["id"] for project in store.list_projects()], [self.pid])
            project = store.get_project(self.pid)
            self.assertEqual(project["counts"]["total"], 1)
            files = {item["file"].rsplit("/", 1)[-1] for item in project["diagnostics"]}
            self.assertEqual(files, {"README.md", edited["id"] + ".md"})
            self.assertTrue(all(item["problem"] for item in project["diagnostics"]))
            self.assertIn("reste visible", store.handoff(self.pid)["text"])
            self.assertIn("quarantined", store.handoff(self.pid)["text"])
            self.assertIn("reste visible", store.export_markdown(self.pid))
            self.assertEqual(len(store.list_events(self.pid)), 2)  # The unreadable event file is skipped.
            names = {item["file"] for item in store.project_diagnostics()}
            self.assertEqual(names, {f"projects/{second['id']}/project.json", "projects/pas-un-projet", "projects/README.md"})
            with self.assertRaises(ValueError):
                store.get_project(second["id"])
            with self.assertRaises(ValueError):
                store.create_entry(second["id"], {"title": "Nope"})
        self.assertEqual(before, snapshot(), "quarantined files must be left byte-for-byte untouched")

    def test_a_quarantined_entry_is_never_overwritten_by_an_update(self):
        entry = self.create(title="Titre d'origine", body="x")
        path = self.entries_dir() / (entry["id"] + ".md")
        path.write_bytes(path.read_bytes().replace(b"# Titre d'origine", b"# Autre titre"))
        before = path.read_bytes()
        with self.assertRaises(ValueError) as caught:
            self.store.update_entry(self.pid, entry["id"], {"revision": 1, "body": "y"})
        self.assertIn("quarantaine", str(caught.exception))
        self.assertEqual(path.read_bytes(), before)

    def test_utf8_bom_in_an_entry_file_is_tolerated(self):
        entry = self.create(body="avec BOM")
        path = self.entries_dir() / (entry["id"] + ".md")
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        self.assertEqual(Store(self.store.root).list_entries(self.pid)[0]["body"], "avec BOM")

    def test_corrupt_import_index_is_reported_and_left_untouched(self):
        self.store.import_events(self.pid, [{"body": "premier"}])
        index = self.store.root / "projects" / self.pid / ".filigree" / "imports.json"
        index.write_text("{corrompu", encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            self.store.import_events(self.pid, [{"body": "second"}])
        self.assertIn("imports.json", str(caught.exception))
        self.assertEqual(index.read_text(encoding="utf-8"), "{corrompu")
        self.assertEqual(len(self.store.list_entries(self.pid)), 1)


class SupersessionTests(Base):  # A-8
    def event_count(self):
        return len(list((self.store.root / "projects" / self.pid / ".filigree" / "events").glob("*.json")))

    def test_only_accepted_targets_can_be_superseded_and_failure_is_atomic(self):
        accepted = self.create(title="Accepte", status="accepted")
        for status in ("rejected", "proposed"):
            with self.subTest(status=status):
                target = self.create(title="Cible " + status, status=status)
                before, events = len(self.store.list_entries(self.pid)), self.event_count()
                with self.assertRaises(ValueError):
                    self.create(title="Remplacant", status="accepted", relations=[{"target": accepted["id"], "type": "supersedes"}, {"target": target["id"], "type": "supersedes"}])
                after = {entry["id"]: entry for entry in self.store.list_entries(self.pid)}
                self.assertEqual(len(after), before)
                self.assertEqual((after[target["id"]]["status"], after[target["id"]]["revision"]), (status, 1))
                self.assertEqual((after[accepted["id"]]["status"], after[accepted["id"]]["revision"]), ("accepted", 1))
                self.assertEqual(self.event_count(), events)
        replacement = self.create(title="Remplacant", status="accepted", relations=[{"target": accepted["id"], "type": "supersedes"}])
        states = {entry["id"]: entry["status"] for entry in self.store.list_entries(self.pid)}
        self.assertEqual((states[accepted["id"]], states[replacement["id"]]), ("superseded", "accepted"))

    def test_an_update_adding_a_link_to_a_proposal_is_refused_without_effect(self):
        proposal = self.create(title="Proposition", status="proposed")
        newer = self.create(title="Nouveau", status="accepted")
        with self.assertRaises(ValueError):
            self.store.update_entry(self.pid, newer["id"], {"revision": 1, "relations": [{"target": proposal["id"], "type": "supersedes"}]})
        entries = {entry["id"]: entry for entry in self.store.list_entries(self.pid)}
        self.assertEqual((entries[proposal["id"]]["status"], entries[newer["id"]]["revision"]), ("proposed", 1))


class SearchAndHandoffTests(Base):  # E-2 / D-3
    def test_search_ignores_accents_case_and_surrounding_spaces(self):
        self.create(title="Élève et café", body="Une école à Zürich")
        for query in ("eleve", "CAFE", "  ecole  ", "zurich", "éLÈVE", "ELEVE cafe"):
            with self.subTest(query=query):
                self.assertEqual(len(self.store.list_entries(self.pid, query=query)), 1)
        self.create(title="Eleve sans accent")
        self.assertEqual(len(self.store.list_entries(self.pid, query="élève")), 2)
        self.assertEqual(self.store.list_entries(self.pid, query="absent"), [])

    def seed(self):
        self.accepted = self.create(title="Stockage local", body="Nous gardons SQLite pour les petites équipes.", kind="decision", status="accepted")
        self.second = self.create(title="Reprise", body="La fiche de reprise liste les décisions.", kind="procedure", status="accepted")
        self.proposal = self.create(title="Cache distribué", body="Idée en attente.", kind="observation", status="proposed")
        self.rejected = self.create(title="Postgres partagé", body="Écarté : trop de services.", kind="decision", status="rejected")

    def test_zero_lexical_hits_keep_current_decisions_and_say_so(self):
        self.seed()
        result = self.store.handoff(self.pid, query="database")
        self.assertEqual(result["matched"], 0)
        self.assertIn("Nous gardons SQLite", result["text"])
        self.assertIn("La fiche de reprise liste", result["text"])
        self.assertEqual({item["id"] for item in result["references"] if item["current"]}, {self.accepted["id"], self.second["id"]})
        self.assertEqual(result["filtered_out"], 2)  # proposal + rejected are hidden by the query, and reported
        self.assertEqual((result["excluded"], result["total"]), (0, 4))
        self.assertIn("Memory inventory: 4 entries", result["text"])
        self.assertIn("2 accepted", result["text"])
        self.assertIn("does NOT mean the memory is empty", result["text"])
        self.assertIn("2 uncertain or historical", result["text"])
        # No hidden synonym table: "database" really does not lexically match SQLite.
        self.assertEqual(self.store.list_entries(self.pid, query="database"), [])

    def test_matching_query_marks_hits_and_keeps_history_labelled(self):
        self.seed()
        result = self.store.handoff(self.pid, query="postgres reprise")
        self.assertEqual(result["matched"], 2)
        self.assertEqual(result["filtered_out"], 1)
        titles = [item["title"] for item in result["references"]]
        self.assertEqual(titles[0], "Reprise")  # Matching accepted knowledge first.
        self.assertIn("Stockage local", titles)
        self.assertNotIn("Cache distribué", titles)
        self.assertIn("[NOT CURRENT · REJECTED] Postgres partagé", result["text"])
        self.assertIn("matches query", result["text"])
        full = self.store.handoff(self.pid)
        self.assertEqual((full["filtered_out"], len(full["references"])), (0, 4))

    def test_search_reports_what_exists_when_nothing_matches(self):
        self.seed()
        result = self.store.search(self.pid, "database")
        self.assertEqual((result["entries"], result["matched"], result["total"]), ([], 0, 4))
        self.assertEqual(result["by_status"]["accepted"], 2)
        self.assertIn("4 connaissance", result["note"])
        self.assertEqual(self.store.search(self.pid, "sqlite")["note"], "")

    def test_current_and_historical_stay_separate_after_replacement(self):
        old = self.create(title="Ancien choix", status="accepted", kind="decision")
        new = self.create(title="Nouveau choix", status="accepted", kind="decision", relations=[{"target": old["id"], "type": "supersedes"}])
        result = self.store.handoff(self.pid, query="zzz")
        flags = {item["title"]: item["current"] for item in result["references"]}
        self.assertEqual(flags, {"Nouveau choix": True})
        self.assertEqual(result["filtered_out"], 1)
        self.assertTrue(new)


class ImportTests(Base):  # A-1 / A-2 / A-7 / A-9 / A-10
    def test_identical_words_in_separate_transcript_lines_are_kept_but_rescans_deduplicate(self):
        lines = [{"type": "user", "sessionId": "S1", "timestamp": f"2026-10-16T10:0{n}:00Z", "message": {"role": "user", "content": "oui"}} for n in range(3)]
        text = "\n".join(json.dumps(line) for line in lines)
        first = self.store.import_events(self.pid, parse_import(text, "t.jsonl"), "t.jsonl")
        self.assertEqual((first["imported"], first["duplicates"]), (3, 0))
        again = self.store.import_events(self.pid, parse_import(text, "renamed.jsonl"), "renamed.jsonl")
        self.assertEqual((again["imported"], again["duplicates"]), (0, 3))
        grown = text + "\n" + json.dumps(dict(lines[0], timestamp="2026-10-16T10:09:00Z"))
        third = self.store.import_events(self.pid, parse_import(grown, "t.jsonl"), "t.jsonl")
        self.assertEqual((third["imported"], third["duplicates"]), (1, 3))
        self.assertEqual(len(self.store.list_entries(self.pid)), 4)

    def test_repeated_history_without_an_occurrence_key_is_still_one_event(self):
        events = [{"body": "même tour", "agent": "a", "episode": "e"}, {"body": "même tour", "agent": "a", "episode": "e"}]
        result = self.store.import_events(self.pid, events)
        self.assertEqual((result["imported"], result["duplicates"]), (1, 1))

    def test_memory_imported_before_occurrence_keys_is_not_duplicated_on_rescan(self):
        old = {"body": "oui", "agent": "a", "episode": "S"}
        self.assertEqual(self.store.import_events(self.pid, [old])["imported"], 1)
        rescan = [dict(old, occurrence="record-1"), dict(old, occurrence="record-5")]
        result = self.store.import_events(self.pid, rescan)
        self.assertEqual((result["imported"], result["duplicates"]), (1, 1))  # Only the repeat is new.
        again = self.store.import_events(self.pid, rescan)
        self.assertEqual((again["imported"], again["duplicates"]), (0, 2))

    def test_deleted_entry_can_be_imported_again(self):
        event = {"body": "à réimporter"}
        entry = self.store.import_events(self.pid, [event])["entries"][0]
        self.assertEqual(self.store.import_events(self.pid, [event])["duplicates"], 1)
        (self.entries_dir() / (entry["id"] + ".md")).unlink()
        again = self.store.import_events(self.pid, [event])
        self.assertEqual((again["imported"], again["duplicates"]), (1, 0))
        self.assertEqual(self.store.import_events(self.pid, [event])["duplicates"], 1)

    def test_oversized_record_is_truncated_visibly_not_fatal_and_rescan_deduplicates(self):
        events = [{"body": "x" * 150000, "agent": "a"}, {"body": "petit"}]
        result = self.store.import_events(self.pid, events, "gros.jsonl")
        self.assertEqual((result["imported"], result["truncated"], result["remaining"], result["complete"]), (2, 1, 0, True))
        big = next(entry for entry in result["entries"] if entry["body"].startswith("xxx"))
        self.assertLessEqual(len(big["body"]), 100000)
        self.assertIn("tronqué à l'import", big["body"])
        self.assertIn("tronqué", big["tags"])
        again = self.store.import_events(self.pid, events, "gros.jsonl")
        self.assertEqual((again["imported"], again["duplicates"]), (0, 2))

    def test_large_inputs_progress_in_bounded_windows_and_never_loop(self):
        events = [{"body": f"message {number}"} for number in range(23)]
        with patch.object(Store, "IMPORT_MAX_NEW_EVENTS", 5), patch.object(Store, "IMPORT_BATCH", 2):
            imported, calls = 0, 0
            while True:
                result = self.store.import_events(self.pid, events)
                calls += 1
                imported += result["imported"]
                self.assertLessEqual(result["imported"], 5)
                if result["complete"]:
                    break
                self.assertGreater(result["imported"], 0, "a window must always make progress")
                self.assertGreater(result["remaining"], 0)
            self.assertEqual((imported, calls), (23, 5))
            final = self.store.import_events(self.pid, events)
            self.assertEqual((final["imported"], final["duplicates"], final["remaining"]), (0, 23, 0))
        self.assertEqual(len(self.store.list_entries(self.pid)), 23)

    def test_more_than_a_thousand_records_import_in_one_call(self):
        text = "\n".join(json.dumps({"type": "user", "sessionId": "S", "message": {"role": "user", "content": f"ligne {n}"}}) for n in range(1500))
        events = parse_import(text, "long.jsonl")
        self.assertEqual(len(events), 1500)
        # Identical bodies collapse to one entry, which keeps this check fast while still passing >1000 events through the store.
        result = self.store.import_events(self.pid, [dict(events[0], occurrence=None)] * 1500, "long.jsonl")
        self.assertEqual((result["imported"], result["duplicates"], result["complete"]), (1, 1499, True))
        # events[0] was just stored without a key, so a keyed rescan rightly treats it as that old entry; use other lines.
        final = self.store.import_events(self.pid, events[1:13], "long.jsonl")
        self.assertEqual((final["imported"], final["duplicates"]), (12, 0))  # Transcript lines carry their own occurrence key.

    def test_unexpected_schemas_and_depth_are_value_errors_not_tracebacks(self):
        self.assertTrue(parse_import(json.dumps({"type": ["user"], "message": {"content": "x"}, "content": "texte"})))
        self.assertTrue(parse_import(json.dumps({"role": ["x"], "content": "texte"})))
        self.assertTrue(parse_import(json.dumps({"type": "response_item", "payload": {"type": ["reasoning"], "role": "assistant", "content": "ok"}})))
        self.assertEqual(content_text({"type": ["tool_use"], "text": "visible"}), "visible")
        with self.assertRaises(ValueError):
            parse_import("[" * 5000 + "]" * 5000)
        deep = {"content": "bas"}
        for _ in range(500):
            deep = {"content": deep}
        self.assertEqual(content_text(deep), "")

    def test_nul_and_lone_surrogates_are_cleaned_and_counted_by_the_parser(self):
        text = '{"content": "a\\u0000b \\ud800 fin", "role": "user"}'
        detail = parse_import_detailed(text, "x.json")
        self.assertEqual(detail["sanitized"], 1)
        self.assertEqual(detail["events"][0]["body"], "ab � fin")
        self.assertEqual(self.store.import_events(self.pid, detail["events"])["imported"], 1)

    def test_decoding_helper_handles_utf16_utf8_bom_and_cp1252(self):
        self.assertEqual(decode_import_bytes("é".encode("utf-16")), "é")
        self.assertEqual(decode_import_bytes(b"\xef\xbb\xbfcaf\xc3\xa9"), "café")
        self.assertEqual(decode_import_bytes(b"caf\xe9"), "café")

    def test_validation_error_names_the_event_and_writes_nothing(self):
        bad = {"body": "fine", "sources": [{"label": "x", "excerpt": "", "uri": "javascript:alert(1)"}]}
        with self.assertRaises(ValueError) as caught:
            self.store.import_events(self.pid, [{"body": "ok"}, bad])
        self.assertIn("Événement 2", str(caught.exception))
        self.assertEqual(self.store.list_entries(self.pid), [])

    def test_overlong_titles_agents_and_episodes_are_clipped_not_fatal(self):
        result = self.store.import_events(self.pid, [{"title": "t\n" + "x" * 500, "body": "ok", "agent": "a" * 400, "episode": "e" * 400}])
        entry = result["entries"][0]
        self.assertEqual((len(entry["title"]), len(entry["agent"]), len(entry["episode"])), (240, 240, 240))
        self.assertNotIn("\n", entry["title"])


class CacheTests(Base):  # A-5
    def settle(self, store):
        store.CACHE_SETTLE_SECONDS = 0.05
        time.sleep(0.25)

    def counting(self):
        return patch.object(Store, "_load_entry", autospec=True, side_effect=Store._load_entry)

    def test_repeated_full_reads_parse_each_unchanged_file_once(self):
        self.store.import_events(self.pid, [{"body": f"message {number}"} for number in range(60)])
        self.settle(self.store)
        self.store.list_entries(self.pid)
        with self.counting() as spy:
            for _ in range(4):
                self.assertEqual(len(self.store.list_entries(self.pid)), 60)
                self.store.get_project(self.pid)
                self.store.handoff(self.pid, "message")
                self.store.export_markdown(self.pid)
            self.assertEqual(spy.call_count, 0)

    def test_changes_from_another_store_instance_and_external_edits_are_seen(self):
        entries = [self.create(title=f"Entrée {n}", body="alpha") for n in range(6)]
        self.settle(self.store)
        self.store.list_entries(self.pid)
        other = Store(self.store.root)  # Stands for another process: separate in-memory state, same files.
        other.update_entry(self.pid, entries[0]["id"], {"revision": 1, "body": "modifié ailleurs"})
        with self.counting() as spy:
            bodies = {entry["id"]: entry["body"] for entry in self.store.list_entries(self.pid)}
            self.assertEqual(bodies[entries[0]["id"]], "modifié ailleurs")
            self.assertEqual(spy.call_count, 1)  # Only the changed file is parsed again.
        created = other.create_entry(self.pid, {"title": "Neuf"})
        self.assertIn(created["id"], [entry["id"] for entry in self.store.list_entries(self.pid)])
        path = self.entries_dir() / (entries[1]["id"] + ".md")
        time.sleep(0.05)
        path.write_bytes(path.read_bytes().replace(b"alpha", b"bravo"))  # Same size, outside Filigree.
        self.assertEqual(next(e for e in self.store.list_entries(self.pid) if e["id"] == entries[1]["id"])["body"], "bravo")
        path.unlink()
        self.assertNotIn(entries[1]["id"], [entry["id"] for entry in self.store.list_entries(self.pid)])

    def test_two_updates_in_a_row_from_different_instances_are_never_hidden_by_the_cache(self):
        entry = self.create(body="v0")
        other = Store(self.store.root)
        revision = 1
        for number in range(8):
            writer = other if number % 2 else self.store
            writer.update_entry(self.pid, entry["id"], {"revision": revision, "body": f"v{number + 1}"})
            revision += 1
            self.assertEqual(self.store.list_entries(self.pid)[0]["body"], f"v{number + 1}")
            self.assertEqual(other.list_entries(self.pid)[0]["body"], f"v{number + 1}")

    def test_returned_objects_are_copies_and_cache_is_bounded(self):
        for number in range(12):
            self.create(title=f"E{number}", tags=["a"], relations=[])
        self.settle(self.store)
        first = self.store.list_entries(self.pid)
        first[0]["tags"].append("pollution")
        first[0]["title"] = "pollué"
        self.assertEqual(self.store.list_entries(self.pid)[0]["tags"], ["a"])
        self.assertNotEqual(self.store.list_entries(self.pid)[0]["title"], "pollué")
        with patch.object(Store, "CACHE_MAX_FILES", 5):
            fresh = Store(self.store.root)
            for _ in range(2):
                self.assertEqual(len(fresh.list_entries(self.pid)), 12)
                self.assertLessEqual(len(fresh._cache), 5)


@unittest.skipUnless(shutil.which("git"), "git not installed")
class GitTests(Base):  # A-15
    def git(self, *args, cwd=None):
        return subprocess.run(["git", "-C", str(cwd or self.project_path), *args], capture_output=True, text=True, encoding="utf-8")

    def setUp(self):
        super().setUp()
        self.project_path = self.store.root / "projects" / self.pid
        git_sync.operate(self.project_path, "init")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")

    def test_dirty_reflects_memory_files_only_and_paths_are_not_octal_escaped(self):
        self.create(title="Premier")
        self.assertTrue(git_sync.status(self.project_path)["dirty"])
        git_sync.operate(self.project_path, "checkpoint")
        (self.project_path / "é-notes.txt").write_text("hors mémoire", encoding="utf-8")
        (self.project_path / "dossier-étranger").mkdir()
        (self.project_path / "dossier-étranger" / "x.md").write_text("x", encoding="utf-8")
        status = git_sync.status(self.project_path)
        self.assertFalse(status["dirty"])
        self.assertEqual(status["changes"], "")
        entry = self.create(title="Second")
        status = git_sync.status(self.project_path)
        self.assertTrue(status["dirty"])
        self.assertIn(f".filigree/entries/{entry['id']}.md", status["changes"])
        self.assertNotIn("\\3", status["changes"])
        self.assertNotIn("é-notes", status["changes"])
        git_sync.operate(self.project_path, "checkpoint")
        self.assertFalse(git_sync.status(self.project_path)["dirty"])
        self.assertNotIn("é-notes.txt", self.git("show", "--name-only", "--format=", "HEAD").stdout)

    def test_a_gitfile_repository_counts_as_initialized(self):
        folder = self.base / "gitfile"
        folder.mkdir()
        separate = self.base / "separate.git"
        subprocess.run(["git", "init", "--quiet", f"--separate-git-dir={separate}", str(folder)], check=True, capture_output=True)
        self.assertTrue((folder / ".git").is_file())
        status = git_sync.status(folder)
        self.assertTrue(status["initialized"])
        self.assertIsInstance(status["branch"], str)

    def test_missing_git_identity_is_explained_in_plain_words(self):
        self.git("config", "--unset", "user.email")
        self.git("config", "--unset", "user.name")
        self.create(title="Sans identité")
        environment = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "user.useConfigOnly", "GIT_CONFIG_VALUE_0": "true"}
        with patch.dict(os.environ, environment):
            for name in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL"):
                os.environ.pop(name, None)
            with self.assertRaises(ValueError) as caught:
                git_sync.operate(self.project_path, "checkpoint")
        self.assertIn("identité", str(caught.exception))
        self.assertNotIn("fatal", str(caught.exception).lower())

    def test_friendly_translation_keeps_other_messages(self):
        self.assertIn("identité", git_sync._friendly("*** Please tell me who you are."))
        self.assertEqual(git_sync._friendly("fatal: autre"), "fatal: autre")


class DemoTests(Base):  # A-12
    def test_default_demo_is_idempotent_and_does_not_litter_the_temp_directory(self):
        before = {path.name for path in Path(tempfile.gettempdir()).glob("filigree-demo-*")}
        first = seed_demo(self.store)
        self.addCleanup(shutil.rmtree, first["folder"]["path"], True)
        second = seed_demo(self.store)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len([project for project in self.store.list_projects() if project["demo"]]), 1)
        self.assertEqual(self.store.get_project(first["id"])["counts"]["total"], 6)
        after = {path.name for path in Path(tempfile.gettempdir()).glob("filigree-demo-*")}
        self.assertEqual(len(after - before), 1)
        self.assertEqual(list(Path(first["folder"]["path"]).iterdir()), [])

    def test_explicit_folder_still_creates_a_separate_demo(self):
        explicit = self.work / "demo"
        explicit.mkdir()
        demo = seed_demo(self.store, folder=str(explicit))
        self.assertEqual(Path(demo["folder"]["path"]), explicit)
        self.assertNotEqual(demo["id"], self.pid)


if __name__ == "__main__":
    unittest.main()
