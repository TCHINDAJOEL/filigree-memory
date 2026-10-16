"""Behavioral coverage for portable memory, provenance, and concurrent edits."""

import json
import multiprocessing
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from filigree.store import ConflictError, Store, redact


def _edit_worker(root, project_id, entry_id, revision, ready, start, results):
    store = Store(Path(root))
    ready.put(True)
    start.wait(10)
    try:
        store.update_entry(project_id, entry_id, {"revision": revision, "body": "Concurrent edit"})
        results.put("saved")
    except ConflictError:
        results.put("conflict")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = Store(self.root)
        self.project = self.store.create_project("Mémoire", "Portable knowledge")
        self.pid = self.project["id"]

    def create(self, **fields):
        return self.store.create_entry(self.pid, {"title": "A useful choice", **fields})

    def test_markdown_is_canonical_and_reopens_without_database(self):
        entry = self.create(body="Line one\n\n```python\nprint('bonjour')\n```\n", tags=["design"])
        path = self.root / "projects" / self.pid / ".filigree" / "entries" / f"{entry['id']}.md"
        self.assertIn("# A useful choice", path.read_text(encoding="utf-8"))
        reopened = Store(self.root).list_entries(self.pid)
        self.assertEqual(reopened[0], entry)
        self.assertEqual(self.store.get_project(self.pid)["counts"]["proposed"], 1)
        self.assertFalse(list(self.root.rglob("*.sqlite*")))

    def test_external_body_edit_is_read_without_index_rebuild(self):
        entry = self.create(body="old body")
        path = self.root / "projects" / self.pid / ".filigree" / "entries" / f"{entry['id']}.md"
        path.write_text(path.read_text(encoding="utf-8").replace("old body", "new body"), encoding="utf-8")
        self.assertEqual(self.store.list_entries(self.pid, query="new body")[0]["body"], "new body")

    def test_optimistic_revision_preserves_history_and_rejects_stale_edit(self):
        first = self.create(body="original")
        second = self.store.update_entry(self.pid, first["id"], {"revision": 1, "body": "corrected"})
        self.assertEqual(second["revision"], 2)
        with self.assertRaises(ConflictError):
            self.store.update_entry(self.pid, first["id"], {"revision": 1, "body": "lost update"})
        history = self.root / "projects" / self.pid / ".filigree" / "history" / first["id"]
        self.assertIn("original", (history / "1.md").read_text(encoding="utf-8"))
        self.assertIn("corrected", (history / "2.md").read_text(encoding="utf-8"))
        self.assertEqual(len(self.store.list_events(self.pid)), 2)

    def test_history_returns_original_and_updated_snapshots_newest_first(self):
        first = self.create(body="Original proposal")
        second = self.store.update_entry(self.pid, first["id"], {"revision": 1, "body": "Clarified decision", "status": "accepted", "reason": "Reviewed the stated scope"})
        history = Store(self.root).list_history(self.pid, first["id"])
        self.assertEqual(history, [second, first])
        self.assertEqual(history[0]["status"], "accepted")
        self.assertEqual(history[1]["status"], "proposed")
        self.assertNotIn("reason", history[0])

    def test_review_reason_is_redacted_and_audited_without_becoming_entry_metadata(self):
        entry = self.create()
        updated = self.store.update_entry(self.pid, entry["id"], {"revision": 1, "status": "rejected", "reason": "Credential leaked: password=private"})
        event = self.store.list_events(self.pid)[0]
        self.assertEqual(event["reason"], "Credential leaked: password=[REDACTED]")
        self.assertEqual(event["redactions"], 1)
        self.assertNotIn("reason", updated)
        for path in self.root.rglob("*.json"):
            self.assertNotIn("password=private", path.read_text(encoding="utf-8"))

    def test_invalid_review_reason_and_unknown_history_are_rejected(self):
        entry = self.create()
        for reason in [None, "x" * 2001, "\ud800"]:
            with self.subTest(reason=repr(reason)), self.assertRaises(ValueError):
                self.store.update_entry(self.pid, entry["id"], {"revision": 1, "reason": reason})
        self.assertEqual(len(self.store.list_history(self.pid, entry["id"])), 1)
        with self.assertRaises(KeyError):
            self.store.list_history(self.pid, str(uuid4()))
        with self.assertRaises(ValueError):
            self.store.list_history(self.pid, "../escape")

    def test_history_validates_revision_filename_and_snapshot_identity(self):
        entry = self.create()
        directory = self.root / "projects" / self.pid / ".filigree" / "history" / entry["id"]
        original = directory / "1.md"
        original.rename(directory / "2.md")
        with self.assertRaises(ValueError):
            self.store.list_history(self.pid, entry["id"])

    def test_supersession_keeps_history_separate_from_current_handoff(self):
        old = self.create(title="Use Basic Memory", status="accepted", kind="decision")
        new = self.create(title="Suspend tool choice", status="accepted", kind="correction", relations=[{"target": old["id"], "type": "supersedes"}])
        entries = {entry["id"]: entry for entry in self.store.list_entries(self.pid)}
        self.assertEqual(entries[old["id"]]["status"], "superseded")
        self.assertEqual(entries[old["id"]]["revision"], 2)
        handoff = self.store.handoff(self.pid)
        self.assertIn("Suspend tool choice", handoff["text"])
        self.assertIn("[NOT CURRENT · SUPERSEDED] Use Basic Memory", handoff["text"])
        self.assertEqual([item["id"] for item in handoff["references"] if item["current"]], [new["id"]])
        self.assertEqual(handoff["excluded"], 0)

    def test_supersession_requires_accepted_replacement_and_cannot_disappear(self):
        old = self.create(status="accepted")
        relation = {"target": old["id"], "type": "supersedes"}
        with self.assertRaises(ValueError):
            self.create(relations=[relation])
        new = self.create(status="accepted", relations=[relation])
        with self.assertRaises(ValueError):
            self.store.update_entry(self.pid, new["id"], {"revision": 1, "relations": []})
        with self.assertRaises(ValueError):
            self.store.update_entry(self.pid, old["id"], {"revision": 2, "status": "accepted"})
        self.assertEqual(self.store.get_project(self.pid)["counts"]["total"], 2)

    def test_supersession_chain_retains_historical_links(self):
        first = self.create(status="accepted")
        second = self.create(status="accepted", relations=[{"target": first["id"], "type": "supersedes"}])
        third = self.create(status="accepted", relations=[{"target": second["id"], "type": "supersedes"}])
        edited = self.store.update_entry(self.pid, second["id"], {"revision": 2, "body": "Historical annotation"})
        self.assertEqual(edited["status"], "superseded")
        self.assertEqual(len(self.store.graph(self.pid)["edges"]), 2)
        self.assertEqual(self.store.handoff(self.pid)["references"][0]["id"], third["id"])

    def test_unresolved_contradictions_are_explicit_and_proposals_labeled(self):
        accepted = self.create(title="SQLite option", status="accepted")
        proposal = self.create(title="Markdown option", relations=[{"target": accepted["id"], "type": "contradicts"}])
        handoff = self.store.handoff(self.pid)
        self.assertIn("[PROPOSED] Markdown option", handoff["text"])
        self.assertIn("Relation: contradicts", handoff["text"])
        self.assertEqual(self.store.graph(self.pid)["edges"], [{"source": proposal["id"], "target": accepted["id"], "type": "contradicts"}])

    def test_import_is_deduplicated_redacted_and_never_authoritative(self):
        secret = "sk-" + "x" * 30
        events = [{"content": "decision accepted api_key=" + secret, "status": "accepted", "kind": "decision", "agent": "claude", "password": "private"}]
        first = self.store.import_events(self.pid, events, source="claude-tap")
        second = self.store.import_events(self.pid, events, source="renamed-export")
        self.assertEqual(first["imported"], 1)
        self.assertGreater(first["redactions"], 0)
        self.assertEqual(second["duplicates"], 1)
        self.assertEqual(first["entries"][0]["status"], "proposed")
        self.assertEqual(first["entries"][0]["kind"], "observation")
        for path in self.root.rglob("*"):
            if path.is_file() and path.suffix in {".md", ".json"}:
                self.assertNotIn(secret, path.read_text(encoding="utf-8"))

    def test_bad_import_batch_has_no_partial_effect(self):
        with self.assertRaises(ValueError):
            self.store.import_events(self.pid, [{"text": "valid"}, "invalid"])
        self.assertEqual(self.store.list_entries(self.pid), [])

    def test_repeated_turn_history_deduplicates_but_keeps_first_provenance(self):
        first = {"title": "Initial label", "body": "The engine is not chosen", "agent": "claude", "episode": "session-123", "timestamp": "2026-10-15T10:00:00Z", "sources": [{"label": "tap · enregistrement 1", "excerpt": "The engine is not chosen", "uri": ""}]}
        later = {**first, "title": "Another label", "timestamp": "2026-10-15T10:01:00Z", "sources": [{"label": "tap · enregistrement 2", "excerpt": "The engine is not chosen", "uri": ""}]}
        result = self.store.import_events(self.pid, [first, later], source="claude-tap")
        self.assertEqual((result["imported"], result["duplicates"]), (1, 1))
        entry = result["entries"][0]
        self.assertEqual(entry["title"], "Initial label")
        self.assertIn("tap · enregistrement 1", [source["label"] for source in entry["sources"]])
        self.assertIn("2026-10-15T10:00:00Z", [source["excerpt"] for source in entry["sources"]])
        self.assertNotIn("2026-10-15T10:01:00Z", [source["excerpt"] for source in entry["sources"]])
        replay = self.store.import_events(self.pid, [later], source="renamed export")
        self.assertEqual(replay["duplicates"], 1)
        distinct = {**first, "episode": "different-session"}
        self.assertEqual(self.store.import_events(self.pid, [distinct])["imported"], 1)

    def test_each_import_entry_keeps_its_own_redaction_count(self):
        result = self.store.import_events(self.pid, [{"body": "password=private"}, {"body": "No sensitive values"}])
        self.assertGreater(result["entries"][0]["redactions"], 0)
        self.assertEqual(result["entries"][1]["redactions"], 0)

    def test_redaction_is_idempotent(self):
        once, first_count = redact("password=private")
        twice, second_count = redact(once)
        self.assertEqual(once, twice)
        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 0)

    def test_redaction_expansion_is_validated_before_any_file_is_written(self):
        with self.assertRaises(ValueError):
            self.create(title="x" * 229 + " password=a")
        self.assertEqual(self.store.list_entries(self.pid), [])
        valid = self.create()
        with self.assertRaises(ValueError):
            self.store.update_entry(self.pid, valid["id"], {"revision": 1, "title": "x" * 229 + " password=a"})
        self.assertEqual(Store(self.root).list_entries(self.pid)[0]["revision"], 1)

    def test_unpaired_surrogates_are_validation_errors_not_poisoned_files(self):
        with self.assertRaises(ValueError):
            self.create(body="invalid \ud800")
        with self.assertRaises(ValueError):
            self.store.create_project("invalid \udfff")
        with self.assertRaises(ValueError):
            self.store.import_events(self.pid, [{"body": "invalid \ud800"}])
        self.assertEqual(self.store.list_entries(self.pid), [])
        self.assertFalse((self.root / ".filigree-transaction.json").exists())

    def test_crlf_content_round_trips_in_normalized_form(self):
        entry = self.create(body="line one\r\nline two\rfinal", sources=[{"label": "Source", "excerpt": "one\r\ntwo", "uri": ""}])
        self.assertEqual(entry["body"], "line one\nline two\nfinal")
        self.assertEqual(entry["sources"][0]["excerpt"], "one\ntwo")
        self.assertEqual(Store(self.root).list_entries(self.pid)[0], entry)

    def test_handoff_has_objective_uncertainties_and_discarded_reason(self):
        self.create(title="Current decision", status="accepted", kind="decision")
        self.create(title="Open question", kind="question", body="Does this work offline?")
        self.create(title="Discarded cache", status="rejected", body="Abandoned because it lost provenance.")
        handoff = self.store.handoff(self.pid)
        self.assertIn("Portable knowledge", handoff["text"])
        self.assertIn("Questions, hypotheses and proposals", handoff["text"])
        self.assertIn("[NOT CURRENT · REJECTED] Discarded cache", handoff["text"])
        self.assertIn("Abandoned because it lost provenance.", handoff["text"])
        historical = next(item for item in handoff["references"] if item["title"] == "Discarded cache")
        self.assertFalse(historical["current"])
        self.assertEqual(handoff["excluded"], 0)

    def test_minimum_handoff_budget_bounds_long_project_objective(self):
        project = self.store.create_project("P" * 160, "Objective " * 500)
        handoff = self.store.handoff(project["id"], budget=500)
        self.assertLessEqual(handoff["characters"], 500)
        self.assertIn("[objective excerpt]", handoff["text"])

    def test_redaction_covers_nested_tokens_bearer_and_private_key(self):
        value = {"access_token": "abc", "nested": ["Bearer abc.def", "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"]}
        clean, count = redact(value)
        self.assertEqual(count, 3)
        self.assertNotIn("secret", json.dumps(clean))
        self.assertNotIn("abc", json.dumps(clean))
        self.assertEqual(value["access_token"], "abc")

    def test_input_validation_and_project_isolation(self):
        for project_id in ["../escape", "../../project.json", "invalid", 1]:
            with self.subTest(project_id=project_id), self.assertRaises(ValueError):
                self.store.get_project(project_id)
        with self.assertRaises(ValueError):
            self.create(kind="invented")
        with self.assertRaises(ValueError):
            self.create(title="line\nbreak")
        other = self.store.create_project("Other")
        foreign = self.store.create_entry(other["id"], {"title": "Foreign"})
        with self.assertRaises(ValueError):
            self.create(relations=[{"target": foreign["id"], "type": "supports"}])
        with self.assertRaises(ValueError):
            self.create(sources=[{"label": "Bad", "excerpt": "", "uri": "javascript:alert(1)"}])
        self.assertEqual(self.store.list_entries(self.pid), [])

    def test_handoff_budget_never_silently_truncates_evidence(self):
        self.create(title="Large", body="x" * 20000)
        self.create(title="Small", body="Fits")
        handoff = self.store.handoff(self.pid, budget=1000)
        self.assertLessEqual(handoff["characters"], 1000)
        self.assertEqual(handoff["excluded"], 1)
        self.assertEqual(len(handoff["references"]), 1)
        self.assertEqual(handoff["references"][0]["title"], "Small")

    def test_failed_transaction_rolls_forward_on_reopen(self):
        original_atomic = self.store._atomic

        def fail_after_journal(path, content):
            if path.suffix == ".md":
                raise OSError("Simulated disk interruption")
            original_atomic(path, content)

        with patch.object(self.store, "_atomic", side_effect=fail_after_journal):
            with self.assertRaises(OSError):
                self.create(title="Recover me")
        self.assertTrue((self.root / ".filigree-transaction.json").exists())
        recovered = Store(self.root)
        self.assertEqual(recovered.list_entries(self.pid)[0]["title"], "Recover me")
        self.assertEqual(len(recovered.list_events(self.pid)), 1)
        self.assertFalse((self.root / ".filigree-transaction.json").exists())

    def test_recovery_rejects_path_traversal(self):
        (self.root / ".filigree-transaction.json").write_text(json.dumps({"writes": {"projects/../../escape": "bad"}}), encoding="utf-8")
        with self.assertRaises(ValueError):
            Store(self.root)

    def test_two_processes_cannot_overwrite_same_revision(self):
        entry = self.create()
        context = multiprocessing.get_context("spawn")
        ready, results = context.Queue(), context.Queue()
        start = context.Event()
        processes = [context.Process(target=_edit_worker, args=(str(self.root), self.pid, entry["id"], 1, ready, start, results)) for _ in range(2)]
        try:
            for process in processes:
                process.start()
            for _ in processes:
                ready.get(timeout=15)
            start.set()
            outcomes = [results.get(timeout=20) for _ in processes]
            self.assertCountEqual(outcomes, ["saved", "conflict"])
            for process in processes:
                process.join(timeout=10)
                self.assertEqual(process.exitcode, 0)
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            ready.close()
            results.close()
        self.assertEqual(self.store.list_entries(self.pid)[0]["revision"], 2)


if __name__ == "__main__":
    unittest.main()
