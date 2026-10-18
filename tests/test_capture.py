"""Folder-bound automatic capture from a synthetic claude-tap v4 store. No real data, no network."""

import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

try:
    from tap_fixtures import TapDB, append_jsonl, claude_line, claude_record, codex_message, codex_record, write_claude_transcript, write_codex_transcript
except ImportError:  # run as tests.test_capture from the repository root
    from tests.tap_fixtures import TapDB, append_jsonl, claude_line, claude_record, codex_message, codex_record, write_claude_transcript, write_codex_transcript

from filigree import capture as capture_module
from filigree import cli, native_index, tap_source
from filigree.capture import Capture, CaptureError, ProcessLock, default_settings
from filigree.store import Store


class CaptureCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)
        self.memory = self.root / "memory"
        self.store = Store(self.memory)
        self.work = self.root / "work"
        self.folder_a, self.folder_b = self.work / "A", self.work / "B"
        for folder in (self.folder_a, self.folder_b):
            folder.mkdir(parents=True)
        self.claude_root = self.root / "claude" / "projects"
        self.codex_root = self.root / "codex" / "sessions"
        self.db = self.root / "tap" / "traces.sqlite3"
        self.tap = TapDB(self.db)
        self.addCleanup(self.tap.close)
        self.capture = Capture(self.store, env={})
        self.capture.refresh_interval = 0
        self.capture.index_interval = 0
        self.configure()

    def configure(self, **changes):
        settings = default_settings()
        settings["tap"]["db"] = str(self.db)
        settings["roots"] = {"claude": str(self.claude_root), "codex": str(self.codex_root)}
        for key, value in changes.items():
            if isinstance(value, dict) and isinstance(settings.get(key), dict):
                settings[key].update(value)
            else:
                settings[key] = value
        self.capture._save_settings(settings)

    def project(self, folder, name="Projet"):
        return self.store.create_project(name, "", folder=str(folder))["id"]

    def texts(self, pid):
        return sorted(entry["body"] for entry in self.store.list_entries(pid))

    def state(self):
        return self.capture._load_state()

    @staticmethod
    def provenance(entry):
        source = next(item for item in entry["sources"] if item["label"] == "Provenance de capture")
        return json.loads(source["excerpt"])


class SchemaAndDecoderTests(CaptureCase):
    def test_only_schema_v4_with_required_columns_is_read(self):
        self.tap.create()
        self.assertEqual(tap_source.probe(self.db)["capability"], "ok")
        self.tap.close()
        for label, options in (("v3", {"version": 3}), ("v5", {"version": 5}), ("column", {"omit_size": True})):
            path = self.root / f"{label}.sqlite3"
            TapDB(path).create(**options).close()
            self.assertEqual(tap_source.probe(path)["capability"], "unsupported_schema", label)

    def test_unsupported_schema_reads_no_record_and_is_reported(self):
        self.tap.create(version=5)
        self.tap.add_session("T1")
        self.capture.scan_once()
        self.tap.add_record("T1", claude_record("S1", "bonjour"))
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        self.project(self.folder_a)
        self.capture.scan_once()
        self.assertEqual(self.capture.tap_status["capability"], "unsupported_schema")
        self.assertEqual(self.capture.status()["tap"]["capability"], "unsupported_schema")
        self.assertEqual(self.state()["counters"].get("imported", 0), 0)

    def decode(self, session, index):
        connection, capability = tap_source.open_db(self.db)
        self.assertEqual(capability, "ok")
        try:
            return tap_source.decode_payload(connection, session, self.tap.payload(session, index))
        finally:
            connection.close()

    def test_large_messages_are_restored_exactly_and_tampering_rejects_the_whole_record(self):
        self.tap.create()
        self.tap.add_session("T1")
        record = claude_record("S1", "x" * 700, history=2)
        index = self.tap.add_record("T1", record, compact=True)
        self.assertIn(tap_source.MARKER, self.tap.payload("T1", index))
        self.assertEqual(self.decode("T1", index), record)
        digest = json.loads(self.tap.payload("T1", index))[tap_source.MARKER]["refs"][-1]["hash"]
        connection = self.tap.connection
        connection.execute("UPDATE record_blobs SET payload_json = payload_json || ' ' WHERE hash = ?", (digest,))
        with self.assertRaises(tap_source.RecordError) as raised:
            self.decode("T1", index)
        self.assertEqual(raised.exception.code, "blob_mismatch")
        connection.execute("UPDATE record_blobs SET payload_json = rtrim(payload_json) WHERE hash = ?", (digest,))
        self.assertEqual(self.decode("T1", index), record)
        connection.execute("UPDATE record_blobs SET size_bytes = size_bytes + 1 WHERE hash = ?", (digest,))
        with self.assertRaises(tap_source.RecordError) as raised:
            self.decode("T1", index)
        self.assertEqual(raised.exception.code, "blob_mismatch")
        connection.execute("UPDATE record_blobs SET size_bytes = size_bytes - 1 WHERE hash = ?", (digest,))
        connection.execute("DELETE FROM record_blobs WHERE hash = ?", (digest,))
        with self.assertRaises(tap_source.RecordError) as raised:
            self.decode("T1", index)
        self.assertEqual(raised.exception.code, "blob_missing")

    def test_unknown_path_version_and_extra_key_are_rejected(self):
        self.tap.create()
        self.tap.add_session("T1")
        index = self.tap.add_record("T1", claude_record("S1", "y" * 700), compact=True)
        envelope = json.loads(self.tap.payload("T1", index))
        def outside_path(value):
            value[tap_source.MARKER]["refs"][-1]["path"] = "/request/headers/x"

        def future_version(value):
            value[tap_source.MARKER]["version"] = 2

        def extra_key(value):
            value["record"]["request"]["body"]["messages"][-1]["extra"] = 1

        variants = {"unsupported_ref_path": outside_path, "unsupported_record_version": future_version, "invalid_blob_ref": extra_key}
        for code, change in variants.items():
            mutated = json.loads(json.dumps(envelope))
            change(mutated)
            extra = self.tap.add_record("T1", None, raw_text=json.dumps(mutated))
            with self.assertRaises(tap_source.RecordError) as raised:
                self.decode("T1", extra)
            self.assertEqual(raised.exception.code, code)

    def test_empty_refs_fall_back_to_scanning_known_paths(self):
        self.tap.create()
        self.tap.add_session("T1")
        record = claude_record("S1", "z" * 700)
        index = self.tap.add_record("T1", record, compact=True)
        envelope = json.loads(self.tap.payload("T1", index))
        envelope[tap_source.MARKER]["refs"] = []
        legacy = self.tap.add_record("T1", None, raw_text=json.dumps(envelope))
        self.assertEqual(self.decode("T1", legacy), record)

    def test_native_ids_are_exact_and_conflicts_are_visible(self):
        both = tap_source.native_ids(claude_record("S1", "a"))
        self.assertEqual({value for _, value in both}, {"S1"})
        conflicting = claude_record("S1", "a")
        conflicting["request"]["headers"]["x-claude-code-session-id"] = "S2"
        self.assertGreater(len({value for _, value in tap_source.native_ids(conflicting)}), 1)
        cache_only = claude_record(None, "a")
        cache_only["request"]["body"]["prompt_cache_key"] = "cache-1"
        self.assertEqual(tap_source.native_ids(cache_only), set())
        self.assertEqual({value for _, value in tap_source.native_ids(codex_record("C1", "a"))}, {"C1"})

    def test_codex_session_id_and_thread_id_are_both_read_and_divergence_is_a_conflict(self):
        def values(record):
            return {value for _, value in tap_source.native_ids(record)}

        def with_turn(session, **turn):
            record = codex_record(session, "a")
            record["request"]["headers"] = {}
            record["request"]["body"]["client_metadata"]["x-codex-turn-metadata"] = json.dumps(turn)
            return record

        self.assertEqual(values(with_turn("C1", session_id="C1", thread_id="C1")), {"C1"})
        self.assertEqual(values(with_turn("C1", thread_id="C3")), {"C3"})
        self.assertEqual(values(with_turn("C1", session_id="C1", thread_id="C2")), {"C1", "C2"})
        self.assertIn("", values(with_turn("C1", session_id="C1", thread_id="bad value!")))

    def test_references_are_strict_and_a_shared_hash_cannot_misstate_its_size(self):
        self.tap.create()
        self.tap.add_session("T1")
        record = claude_record("S1", "z" * 700)
        messages = record["request"]["body"]["messages"]
        messages.insert(0, copy.deepcopy(messages[-1]))
        index = self.tap.add_record("T1", record, compact=True)
        envelope = json.loads(self.tap.payload("T1", index))
        refs = envelope[tap_source.MARKER]["refs"]
        self.assertEqual(len(refs), 2)
        self.assertEqual(refs[0]["hash"], refs[1]["hash"])
        self.assertEqual(self.decode("T1", index), record)

        def inner(value, position):
            return value["record"]["request"]["body"]["messages"][position][tap_source.BLOB_KEY]

        def missing_version(value):
            del inner(value, 0)["version"]

        def wrong_kind(value):
            inner(value, 1)["kind"] = "text"

        def second_reference_lies(value):
            value[tap_source.MARKER]["refs"][1]["bytes"] += 1
            inner(value, 1)["bytes"] += 1

        def boolean_size(value):
            inner(value, 0)["bytes"] = True

        for label, change in (("version", missing_version), ("kind", wrong_kind), ("shared size", second_reference_lies), ("bool size", boolean_size)):
            mutated = json.loads(json.dumps(envelope))
            change(mutated)
            extra = self.tap.add_record("T1", None, raw_text=json.dumps(mutated))
            with self.assertRaises(tap_source.RecordError, msg=label) as raised:
                self.decode("T1", extra)
            self.assertEqual(raised.exception.code, "blob_mismatch", label)

    def test_blob_size_is_bounded_inside_sqlite_and_by_the_materialized_total(self):
        self.tap.create()
        self.tap.add_session("T1")
        index = self.tap.add_record("T1", claude_record("S1", "w" * 700), compact=True)
        connection, _ = tap_source.open_db(self.db)
        statements = []
        connection.set_trace_callback(statements.append)
        try:
            tap_source.decode_payload(connection, "T1", self.tap.payload("T1", index))
            blob_reads = [statement for statement in statements if "record_blobs" in statement]
            self.assertTrue(blob_reads and all("LENGTH(CAST(payload_json AS BLOB))" in statement for statement in blob_reads))
            with patch.object(tap_source, "MAX_MATERIALIZED", 100), self.assertRaises(tap_source.RecordError) as raised:
                tap_source.decode_payload(connection, "T1", self.tap.payload("T1", index))
            self.assertEqual(raised.exception.code, "too_large")
        finally:
            connection.close()


class ReadOnlyAndAvailabilityTests(CaptureCase):
    def fingerprint(self):
        stat = self.db.stat()
        return hashlib.sha256(self.db.read_bytes()).hexdigest(), stat.st_mtime_ns

    def test_scan_never_modifies_the_database_or_creates_the_writer_lock(self):
        self.tap.create()
        self.tap.add_session("T0")
        self.tap.add_record("T0", claude_record("S0", "ancien"))
        self.capture.scan_once()
        self.tap.add_record("T0", claude_record("S0", "nouveau"))
        before = self.fingerprint()
        self.capture.scan_once()
        self.capture.scan_once()
        self.assertEqual(self.fingerprint(), before)
        self.assertFalse(Path(str(self.db) + ".write.lock").exists())
        connection, _ = tap_source.open_db(self.db)
        with self.assertRaises(sqlite3.OperationalError):
            connection.execute("CREATE TABLE intrusion(a)")
        connection.close()

    def test_missing_database_is_reported_without_creating_its_folder(self):
        result = self.capture.scan_once()
        self.assertEqual(result["tap"], "missing")
        self.assertFalse(self.db.parent.exists())
        self.assertEqual(self.capture.status()["tap"]["capability"], "missing")

    def test_corrupt_database_is_reported(self):
        self.db.parent.mkdir(parents=True)
        self.db.write_bytes(os.urandom(4096))
        self.assertEqual(self.capture.scan_once()["tap"], "corrupt")

    def test_locked_database_recovers_when_the_writer_finishes(self):
        self.tap.create()
        self.tap.add_session("T1")
        self.capture.scan_once()
        self.tap.connection.execute("BEGIN EXCLUSIVE")
        self.assertEqual(self.capture.scan_once()["tap"], "locked")
        self.tap.connection.execute("ROLLBACK")
        self.assertEqual(self.capture.scan_once()["tap"], "ok")

    def test_concurrent_wal_writer_yields_each_record_exactly_once(self):
        self.tap.create(wal=True)
        self.tap.add_session("T0")
        pid = self.project(self.folder_a)
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        self.capture.scan_once()
        self.tap.add_session("T1")
        errors = []

        def writer():
            try:
                mine = TapDB(self.db).open()
                for number in range(25):
                    mine.add_record("T1", claude_record("S1", f"message concurrent {number}", f"réponse {number}"))
                    time.sleep(0.002)
                mine.close()
            except Exception as exc:  # surfaced below
                errors.append(exc)

        thread = threading.Thread(target=writer)
        thread.start()
        while thread.is_alive():
            self.capture.scan_once()
        thread.join()
        self.capture.scan_once()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.store.list_entries(pid)), 50)
        self.capture.scan_once()
        self.assertEqual(len(self.store.list_entries(pid)), 50)

    def test_malformed_record_does_not_stall_its_neighbours(self):
        self.tap.create()
        self.tap.add_session("T1")
        pid = self.project(self.folder_a)
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        self.capture.scan_once()
        self.tap.add_record("T1", claude_record("S1", "avant"))
        self.tap.add_record("T1", None, raw_text="{not json")
        self.tap.add_record("T1", claude_record("S1", "après"))
        self.capture.scan_once()
        self.assertIn("Utilisateur · avant", [e["title"] for e in self.store.list_entries(pid)])
        self.assertIn("Utilisateur · après", [e["title"] for e in self.store.list_entries(pid)])
        self.assertEqual(self.state()["malformed"].get("invalid_json"), 1)

    def test_invalid_settings_disable_capture_visibly(self):
        self.tap.create()
        self.capture._file("capture.json").write_text(json.dumps({"enabled": "yes"}), encoding="utf-8")
        self.assertEqual(self.capture.scan_once()["state"], "settings_invalid")
        status = self.capture.status()
        self.assertFalse(status["enabled"])
        self.assertTrue(status["settings_error"])


class LinkingTests(CaptureCase):
    def prepare(self, *sessions):
        self.tap.create()
        self.tap.add_session("T-old")
        self.tap.add_record("T-old", claude_record("S-old", "historique ancien"))
        self.capture.scan_once()
        for session, client in sessions:
            self.tap.add_session(session, client)

    def test_exact_native_id_links_the_folder_project_with_full_provenance(self):
        pid = self.project(self.folder_a)
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        self.prepare(("T1", "claude"))
        self.tap.add_record("T1", claude_record("S1", "Choisir SQLite", "Je propose SQLite."))
        self.capture.scan_once()
        entries = self.store.list_entries(pid)
        self.assertEqual(len(entries), 2)
        user = next(entry for entry in entries if entry["title"].startswith("Utilisateur"))
        self.assertEqual(user["status"], "proposed")
        self.assertIn("claude-tap", user["tags"])
        self.assertIn("capture", user["tags"])
        self.assertEqual(user["episode"], "S1")
        provenance = self.provenance(user)
        self.assertEqual(provenance["native_id"], "S1")
        self.assertEqual(provenance["tap_session_id"], "T1")
        self.assertEqual(provenance["record_index"], 1)
        self.assertEqual(provenance["link"], "native")
        self.assertEqual(provenance["native_source"], "claude")
        self.assertEqual(Path(provenance["cwd"]), self.folder_a)
        self.assertRegex(provenance["tap_db_key"], r"^[0-9a-f]{16}$")
        self.assertRegex(provenance["payload_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn(json.dumps(str(self.db))[1:-1], json.dumps(entries))
        markdown = next((self.memory / "projects" / pid / ".filigree" / "entries").glob(f"{user['id']}.md")).read_text(encoding="utf-8")
        self.assertIn("tap_session_id", markdown)  # provenance lives in the entry file, so a Git checkpoint keeps it

    def test_unknown_missing_and_conflicting_identities_stay_pending_without_writing(self):
        pid = self.project(self.folder_a)
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        mismatch = claude_record("S1", "conflit")
        mismatch["request"]["headers"]["X-Claude-Code-Session-Id"] = "S2"
        self.prepare(("T1", "claude"), ("T2", "claude"), ("T3", "claude"))
        self.tap.add_record("T1", mismatch)
        self.tap.add_record("T2", claude_record("S404", "identifiant inconnu"))
        self.tap.add_record("T3", claude_record(None, "sans identifiant"))
        self.capture.scan_once()
        self.assertEqual(self.store.list_entries(pid), [])
        pending = {item["key"]: item["reason"] for item in self.capture.pending()}
        self.assertEqual(pending["tap:T1"], "ambiguous_native_id")
        self.assertEqual(pending["S404"], "unknown_native")
        self.assertEqual(pending["tap:T3"], "no_native_id")

    def test_one_id_in_two_files_with_different_project_folders_is_ambiguous(self):
        pa, pb = self.project(self.folder_a, "A"), self.project(self.folder_b, "B")
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        other = self.claude_root / "-other"
        other.mkdir()
        (other / "copy.jsonl").write_text(json.dumps({"type": "user", "sessionId": "S1", "cwd": str(self.folder_b)}) + "\n", encoding="utf-8")
        self.prepare(("T1", "claude"))
        self.tap.add_record("T1", claude_record("S1", "ambigu"))
        self.capture.scan_once()
        self.assertEqual((self.store.list_entries(pa), self.store.list_entries(pb)), ([], []))
        self.assertEqual([item["reason"] for item in self.capture.pending()], ["ambiguous_cwd"])

    def test_recent_native_session_with_another_id_is_never_guessed(self):
        pid = self.project(self.folder_a)
        write_claude_transcript(self.claude_root, "S-recent", self.folder_a)
        self.prepare(("T1", "claude"))
        self.tap.add_record("T1", claude_record("S-other", "pas de devinette"))
        self.capture.scan_once()
        self.assertEqual(self.store.list_entries(pid), [])
        self.assertEqual(self.capture.pending()[0]["reason"], "unknown_native")

    def test_missing_cwd_and_disabled_auto_create_stay_pending(self):
        write_claude_transcript(self.claude_root, "S1", self.root / "gone")
        write_claude_transcript(self.claude_root, "S2", self.folder_a)
        self.configure(auto_create=False)
        self.prepare(("T1", "claude"), ("T2", "claude"))
        self.tap.add_record("T1", claude_record("S1", "dossier disparu"))
        self.tap.add_record("T2", claude_record("S2", "pas de projet"))
        self.capture.scan_once()
        reasons = {item["key"]: item["reason"] for item in self.capture.pending()}
        self.assertEqual(reasons, {"S1": "cwd_missing", "S2": "no_project"})
        self.assertEqual(self.store.list_projects(), [])

    def test_auto_create_uses_the_nearest_git_root_and_both_agents_share_the_project(self):
        (self.folder_a / ".git").mkdir()
        nested = self.folder_a / "src" / "app"
        nested.mkdir(parents=True)
        write_claude_transcript(self.claude_root, "S1", nested)
        write_codex_transcript(self.codex_root, "C1", self.folder_a / "src")
        self.prepare(("T1", "claude"), ("T2", "codex"))
        self.tap.add_record("T1", claude_record("S1", "depuis Claude"))
        self.tap.add_record("T2", codex_record("C1", "depuis Codex"))
        self.capture.scan_once()
        projects = self.store.list_projects()
        self.assertEqual(len(projects), 1)
        self.assertEqual(Path(projects[0]["folder"]["path"]), self.folder_a)
        entries = self.store.list_entries(projects[0]["id"])
        self.assertEqual(len(entries), 4)
        self.assertEqual({tag for entry in entries for tag in entry["tags"]} & {"claude-code", "codex"}, {"claude-code", "codex"})
        self.assertEqual(self.provenance(next(e for e in entries if "Codex" in e["agent"] or "codex" in e["tags"]))["native_source"], "codex")

    def test_memory_folder_and_excluded_folders_never_create_projects(self):
        write_claude_transcript(self.claude_root, "S1", self.memory)
        write_claude_transcript(self.claude_root, "S2", self.folder_b)
        self.capture.set_excluded(str(self.folder_b), True)
        self.prepare(("T1", "claude"), ("T2", "claude"))
        self.tap.add_record("T1", claude_record("S1", "dans la mémoire"))
        self.tap.add_record("T2", claude_record("S2", "dossier exclu"))
        self.capture.scan_once()
        self.assertEqual(self.store.list_projects(), [])
        self.assertEqual(self.capture.pending(), [])
        self.assertGreaterEqual(self.state()["skipped"]["excluded"], 2)

    def test_two_projects_interleaved_never_cross(self):
        pa, pb = self.project(self.folder_a, "A"), self.project(self.folder_b, "B")
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        write_claude_transcript(self.claude_root, "S2", self.folder_b)
        self.prepare(("T1", "claude"), ("T2", "claude"))
        for number in range(3):
            self.tap.add_record("T1", claude_record("S1", f"alpha {number}", f"reponse alpha {number}"))
            self.tap.add_record("T2", claude_record("S2", f"beta {number}", f"reponse beta {number}"))
        self.capture.scan_once()
        self.assertEqual(len(self.texts(pa)), 6)
        self.assertTrue(all("alpha" in text for text in self.texts(pa)))
        self.assertTrue(all("beta" in text for text in self.texts(pb)))
        self.assertEqual(len(self.texts(pb)), 6)

    def test_claude_and_codex_in_the_same_folder_use_one_project(self):
        pid = self.project(self.folder_a)
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        write_codex_transcript(self.codex_root, "C1", self.folder_a)
        self.prepare(("T1", "claude"), ("T2", "codex"))
        self.tap.add_record("T1", claude_record("S1", "question Claude"))
        self.tap.add_record("T2", codex_record("C1", "question Codex"))
        self.capture.scan_once()
        self.assertEqual(len(self.store.list_projects()), 1)
        agents = {entry["agent"] for entry in self.store.list_entries(pid)}
        self.assertTrue(any("Claude Code" in agent for agent in agents) and any("Codex" in agent for agent in agents))


class AllowedRootsAndWorktreeTests(CaptureCase):
    """ADR-0003: allowed roots confine resolution; a proven linked worktree joins its repository's project."""

    def prepare(self, *sessions):
        self.tap.create()
        self.tap.add_session("T-old")
        self.tap.add_record("T-old", claude_record("S-old", "historique ancien"))
        self.capture.scan_once()
        for session, client in sessions:
            self.tap.add_session(session, client)

    def worktree(self, repo, name="wt"):
        admin = repo / ".git" / "worktrees" / name
        admin.mkdir(parents=True)
        tree = self.work / name
        tree.mkdir()
        (tree / ".git").write_text(f"gitdir: {admin}\n", encoding="utf-8")
        (admin / "gitdir").write_text(f"{tree / '.git'}\n", encoding="utf-8")
        return tree

    def test_session_outside_allowed_roots_stays_pending_without_project(self):
        self.configure(allowed_roots=[str(self.folder_a)])
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        write_claude_transcript(self.claude_root, "S2", self.folder_b)
        self.prepare(("T1", "claude"), ("T2", "claude"))
        self.tap.add_record("T1", claude_record("S1", "dans la racine"))
        self.tap.add_record("T2", claude_record("S2", "hors racine secret"))
        self.capture.scan_once()
        self.assertEqual([Path(item["folder"]["path"]) for item in self.store.list_projects()], [self.folder_a])
        self.assertEqual({item["key"]: item["reason"] for item in self.capture.pending()}, {"S2": "outside_roots"})
        self.assertNotIn("hors racine secret", json.dumps(self.capture.pending()))

    def test_outside_roots_wins_over_an_existing_project(self):
        pid = self.project(self.folder_b)
        self.configure(allowed_roots=[str(self.folder_a)])
        write_claude_transcript(self.claude_root, "S1", self.folder_b)
        self.prepare(("T1", "claude"))
        self.tap.add_record("T1", claude_record("S1", "projet hors racine"))
        self.capture.scan_once()
        self.assertEqual(self.store.list_entries(pid), [])
        self.assertEqual(self.capture.pending()[0]["reason"], "outside_roots")

    def test_null_allowed_roots_keeps_v01_behaviour(self):
        self.configure(allowed_roots=None)
        write_claude_transcript(self.claude_root, "S1", self.folder_b)
        self.prepare(("T1", "claude"))
        self.tap.add_record("T1", claude_record("S1", "comportement v0.1"))
        self.capture.scan_once()
        self.assertEqual(len(self.store.list_projects()), 1)

    def test_malformed_allowed_roots_disable_capture(self):
        for bad in ("E:/work", ["relatif/dossier"], [""], [1], ["/a\x00b"]):
            settings, error = capture_module.normalize_settings({"allowed_roots": bad})
            self.assertFalse(settings["enabled"], bad)
            self.assertIn("allowed_roots", error)
        settings, error = capture_module.normalize_settings({"allowed_roots": [str(self.folder_a)]})
        self.assertIsNone(error)
        self.assertEqual(settings["allowed_roots"], [str(self.folder_a)])

    def test_proven_worktree_joins_the_repository_project(self):
        (self.folder_a / ".git").mkdir()
        pid = self.project(self.folder_a)
        tree = self.worktree(self.folder_a)
        (tree / "src").mkdir()
        write_claude_transcript(self.claude_root, "S1", tree / "src")
        self.prepare(("T1", "claude"))
        self.tap.add_record("T1", claude_record("S1", "depuis le worktree"))
        self.capture.scan_once()
        self.assertEqual(len(self.store.list_projects()), 1)
        entries = self.store.list_entries(pid)
        self.assertTrue(entries)
        self.assertEqual(Path(self.provenance(entries[0])["worktree_of"]), self.folder_a)

    def test_unproven_worktree_link_is_not_followed(self):
        (self.folder_a / ".git").mkdir()
        pid = self.project(self.folder_a)
        tree = self.worktree(self.folder_a)
        (self.folder_a / ".git" / "worktrees" / "wt" / "gitdir").write_text(str(self.folder_b / ".git"), encoding="utf-8")
        write_claude_transcript(self.claude_root, "S1", tree)
        self.prepare(("T1", "claude"))
        self.tap.add_record("T1", claude_record("S1", "lien non prouvé"))
        self.capture.scan_once()
        self.assertEqual(self.store.list_entries(pid), [])
        self.assertEqual(len(self.store.list_projects()), 2)  # v0.1 rule applies: the worktree gets its own project


class CursorTests(CaptureCase):
    def setUp(self):
        super().setUp()
        self.pid = self.project(self.folder_a)
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        self.tap.create()
        self.tap.add_session("T1")
        for number in range(3):
            self.tap.add_record("T1", claude_record("S1", f"historique {number}"))

    def test_first_scan_is_a_baseline_then_only_new_activity_is_captured(self):
        self.capture.scan_once()
        self.assertEqual(self.store.list_entries(self.pid), [])
        self.tap.add_record("T1", claude_record("S1", "après la ligne de base"))
        self.tap.add_session("T2")
        self.tap.add_record("T2", claude_record("S1", "nouvelle session"))
        self.capture.scan_once()
        bodies = self.texts(self.pid)
        self.assertEqual(len(bodies), 4)
        self.assertTrue(all("historique" not in text for text in bodies))
        self.assertIn(1, [self.provenance(e)["record_index"] for e in self.store.list_entries(self.pid) if "nouvelle session" in e["body"]])

    def test_database_created_after_first_start_is_entirely_new(self):
        self.tap.close()
        self.db.unlink()
        self.capture.scan_once()
        self.tap.create()
        self.tap.add_session("T1")
        self.tap.add_record("T1", claude_record("S1", "tout premier"))
        self.capture.scan_once()
        self.assertEqual(len(self.store.list_entries(self.pid)), 2)

    def test_restart_and_crash_replay_create_no_duplicates(self):
        self.capture.scan_once()
        self.tap.add_record("T1", claude_record("S1", "avant le crash"))
        with patch.object(Capture, "_save", side_effect=RuntimeError("crash après import")):
            with self.assertRaises(RuntimeError):
                self.capture.scan_once()
        self.assertEqual(len(self.store.list_entries(self.pid)), 2)
        restarted = Capture(self.store, env={})
        restarted.refresh_interval = 0
        restarted.scan_once()
        restarted.scan_once()
        self.assertEqual(len(self.store.list_entries(self.pid)), 2)
        self.assertEqual(restarted._load_state()["counters"].get("duplicates"), 2)
        self.tap.add_record("T1", claude_record("S1", "après redémarrage"))
        Capture(self.store, env={}).scan_once()
        self.assertEqual(len(self.store.list_entries(self.pid)), 4)

    def test_rewritten_and_deleted_upstream_are_visible_and_never_touch_memory(self):
        self.capture.scan_once()
        self.tap.add_record("T1", claude_record("S1", "original"))
        self.capture.scan_once()
        self.capture.scan_once()
        before = self.texts(self.pid)
        self.tap.connection.execute("UPDATE records SET payload_json = ? WHERE session_id = 'T1' AND record_index = 4", (json.dumps(claude_record("S1", "réécrit")),))
        self.tap.connection.execute("UPDATE sessions SET updated_at = 'rewritten' WHERE id = 'T1'")
        self.capture.scan_once()
        self.assertEqual(self.state()["counters"].get("rewritten"), 1)
        self.assertEqual(self.texts(self.pid), before)
        self.tap.connection.execute("DELETE FROM records")
        self.tap.connection.execute("DELETE FROM sessions")
        self.capture.scan_once()
        self.assertEqual(self.state()["counters"].get("deleted_upstream"), 1)
        self.assertEqual(self.texts(self.pid), before)

    def test_pause_skips_without_replay_and_global_pause_never_catches_up(self):
        self.capture.scan_once()
        self.capture.set_paused(True, self.pid)
        self.tap.add_record("T1", claude_record("S1", "pendant la pause du projet"))
        self.capture.scan_once()
        self.assertEqual(self.store.list_entries(self.pid), [])
        self.capture.set_paused(False, self.pid)
        self.tap.add_record("T1", claude_record("S1", "reprise du projet"))
        self.capture.scan_once()
        self.assertTrue(all("pause du projet" not in text for text in self.texts(self.pid)))
        self.assertEqual(len(self.store.list_entries(self.pid)), 2)
        self.capture.set_paused(True)
        self.tap.add_record("T1", claude_record("S1", "pendant la pause globale"))
        self.assertEqual(self.capture.scan_once()["state"], "paused")
        self.capture.set_paused(False)
        self.capture.scan_once()
        self.tap.add_record("T1", claude_record("S1", "après la pause globale"))
        self.capture.scan_once()
        joined = "\n".join(self.texts(self.pid))
        self.assertNotIn("pendant la pause globale", joined)
        self.assertIn("après la pause globale", joined)

    def test_disable_then_enable_does_not_import_the_gap(self):
        self.capture.scan_once()
        self.capture.set_enabled(False)
        self.tap.add_record("T1", claude_record("S1", "capture désactivée"))
        self.assertEqual(self.capture.scan_once()["state"], "disabled")
        self.capture.set_enabled(True)
        self.capture.scan_once()
        self.assertEqual(self.store.list_entries(self.pid), [])

    def test_toggling_the_native_fallback_does_not_discard_tap_activity(self):
        self.capture.scan_once()
        self.tap.add_record("T1", claude_record("S1", "activité tap pendant le basculement"))
        self.capture.set_native_fallback(False)
        self.capture.scan_once()
        self.assertIn("activité tap pendant le basculement", "\n".join(self.texts(self.pid)))
        self.assertFalse(any(notice["code"] == "resumed" for notice in self.state()["notices"]))
        self.tap.add_record("T1", claude_record("S1", "après réactivation"))
        self.capture.set_native_fallback(True)
        self.capture.scan_once()
        self.assertIn("après réactivation", "\n".join(self.texts(self.pid)))

    def test_a_global_pause_still_skips_tap_activity(self):
        self.capture.scan_once()
        self.capture.set_paused(True)
        self.tap.add_record("T1", claude_record("S1", "pendant la pause"))
        self.capture.scan_once()
        self.capture.set_paused(False)
        self.capture.scan_once()
        self.assertEqual(self.store.list_entries(self.pid), [])


class CheckpointOrderTests(CaptureCase):
    """RC-07: whichever persisted file a crash interrupts, no pending key is lost behind an advanced cursor."""

    def test_a_crash_between_the_two_checkpoint_files_loses_no_pending_key(self):
        self.pid = self.project(self.folder_a)
        self.configure(sources={"native_fallback": False})
        self.tap.create()
        self.tap.add_session("T9")
        self.tap.add_record("T9", claude_record(None, "historique"))
        self.capture.scan_once()
        self.tap.add_record("T9", claude_record(None, "inconnu avant le crash"))
        real, seen = capture_module._write_json, []

        def crash_on_second_file(path, value):
            if Path(path).name in {"state.json", "pending.json"}:
                seen.append(Path(path).name)
                if len(seen) == 2:
                    raise RuntimeError("panne entre les deux fichiers")
            return real(path, value)

        with patch.object(capture_module, "_write_json", crash_on_second_file):
            with self.assertRaises(RuntimeError):
                self.capture.scan_once()
        self.assertEqual(seen[0], "pending.json")  # the pending keys are persisted before the cursor can advance
        restarted = Capture(self.store, env={})
        restarted.refresh_interval = 0
        restarted.scan_once()
        self.assertEqual([item["key"] for item in restarted.pending()], ["tap:T9"])
        restarted.link("tap:T9", self.pid)
        self.assertIn("inconnu avant le crash", "\n".join(self.texts(self.pid)))
        self.assertEqual(restarted.pending(), [])


class HistoryWithNativeMappingTests(CaptureCase):
    def test_tap_history_import_works_when_a_native_mapping_agrees(self):
        pid = self.project(self.folder_a)
        self.configure(sources={"native_fallback": False})
        self.tap.create()
        self.tap.add_session("T9")
        for number in range(2):
            self.tap.add_record("T9", claude_record("S1", f"historique agréé {number}"))
        self.capture.scan_once()
        self.capture.link("S1", pid)
        self.capture.link("tap:T9", pid, import_history=True)
        bodies = "\n".join(self.texts(pid))
        for number in range(2):
            self.assertIn(f"historique agréé {number}", bodies)
        self.assertEqual(self.capture.pending(), [])


class ExplicitMappingTests(CaptureCase):
    def prepare_pending(self):
        self.pid = self.project(self.folder_a)
        self.tap.create()
        self.tap.add_session("T9")
        for number in range(3):
            self.tap.add_record("T9", claude_record(None, f"historique secret {number}"))
        self.capture.scan_once()
        self.tap.add_record("T9", claude_record(None, "nouveau sans identité"))
        self.capture.scan_once()

    def test_pending_keeps_keys_only_and_link_imports_post_baseline_records(self):
        self.prepare_pending()
        self.assertEqual(self.capture.pending()[0]["key"], "tap:T9")
        self.assertEqual(self.store.list_entries(self.pid), [])
        stored = self.capture._file("pending.json").read_text(encoding="utf-8") + self.capture._file("state.json").read_text(encoding="utf-8")
        self.assertNotIn("nouveau sans identité", stored)
        self.assertNotIn("historique secret", stored)
        self.capture.link("tap:T9", self.pid)
        bodies = "\n".join(self.texts(self.pid))
        self.assertIn("nouveau sans identité", bodies)
        self.assertNotIn("historique secret", bodies)
        self.assertEqual(self.capture.pending(), [])
        provenance = self.provenance(next(e for e in self.store.list_entries(self.pid) if "nouveau" in e["body"]))
        self.assertEqual(provenance["link"], "explicit")

    def test_import_history_is_explicit_and_unlink_restores_pending_behaviour(self):
        self.prepare_pending()
        self.capture.link("tap:T9", self.pid, import_history=True)
        bodies = "\n".join(self.texts(self.pid))
        for number in range(3):
            self.assertIn(f"historique secret {number}", bodies)
        self.capture.unlink("tap:T9")
        self.tap.add_record("T9", claude_record(None, "après unlink"))
        self.capture.scan_once()
        self.assertNotIn("après unlink", "\n".join(self.texts(self.pid)))
        self.assertEqual(self.capture.pending()[0]["key"], "tap:T9")

    def test_link_rejects_malformed_key_unknown_project_and_demo(self):
        self.prepare_pending()
        with self.assertRaises(ValueError):
            self.capture.link("bad key!", self.pid)
        with self.assertRaises(KeyError):
            self.capture.link("tap:T9", "00000000-0000-4000-8000-000000000000")
        from filigree.demo import seed_demo
        (self.work / "demo").mkdir()
        demo = seed_demo(self.store, folder=str(self.work / "demo"))
        with self.assertRaises(ValueError):
            self.capture.link("tap:T9", demo["id"])


class FilteringTests(CaptureCase):
    def test_visible_text_tools_and_failures_are_kept_and_hidden_material_is_not(self):
        pid = self.project(self.folder_a)
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        self.tap.create()
        self.tap.add_session("T1")
        self.capture.scan_once()
        self.tap.add_record("T1", claude_record("S1", "", "Je lance les tests.", history=5, tool=("Bash", {"command": "pytest -q"}),
                                                last_blocks=[{"type": "text", "text": "<system-reminder>consigne injectée</system-reminder>"}, {"type": "text", "text": "<environment_context>cwd privé</environment_context>"}, {"type": "text", "text": "Lance les tests"}]))
        self.tap.add_record("T1", claude_record("S1", "", "Je corrige.", last_blocks=[{"type": "tool_result", "tool_use_id": "toolu_1", "is_error": True, "content": "2 failed: AssertionError\nAuthorization: Bearer abcdefSECRET123456"}]))
        self.tap.add_record("T1", claude_record("S1", "trop de requêtes", status=429))
        self.tap.add_record("T1", claude_record("S1", "sonde", path="/v1/models"))
        self.capture.scan_once()
        entries = self.store.list_entries(pid)
        titles = [entry["title"] for entry in entries]
        everything = json.dumps(entries, ensure_ascii=False)
        for expected in ("Utilisateur · Lance les tests", "Appel d'outil Bash", "Résultat d'outil (erreur) · 2 failed: AssertionError", "Échec · HTTP 429"):
            self.assertTrue(any(title.startswith(expected) for title in titles), expected)
        for forbidden in ("raisonnement caché", "consigne injectée", "cwd privé", "consigne système privée", "ancien message", "ancienne réponse", "abcdefSECRET123456", "sonde"):
            self.assertNotIn(forbidden, everything)
        call = next(entry for entry in entries if entry["title"].startswith("Appel d'outil"))
        self.assertIn("pytest -q", call["body"])
        self.assertIn("rate_limit_error", next(e for e in entries if e["title"].startswith("Échec"))["body"])
        self.assertEqual(self.state()["skipped"].get("non_conversation"), 1)

    def test_only_the_verified_one_token_warmup_is_a_side_request(self):
        pid = self.project(self.folder_a)
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        self.tap.create()
        self.tap.add_session("T1")
        self.capture.scan_once()
        warmup = claude_record("S1", "préchauffage")
        warmup["request"]["body"]["max_tokens"] = 1
        self.tap.add_record("T1", warmup)
        self.capture.scan_once()
        self.assertEqual(self.store.list_entries(pid), [])
        self.assertEqual(self.state()["skipped"].get("side_request"), 1)

    def test_structured_json_conversation_without_tools_is_captured(self):
        # A JSON schema is a legitimate user request; with no verified auxiliary marker it is kept as a proposal.
        pid = self.project(self.folder_a)
        other = self.project(self.folder_b)
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        self.tap.create()
        self.tap.add_session("T1")
        self.capture.scan_once()
        for index, shape in enumerate(({"output_config": {"format": {"type": "json_schema", "schema": {}}}}, {"text": {"format": {"type": "json_object"}}}, {"response_format": {"type": "json_schema"}})):
            record = claude_record("S1", f"question json {index}", f"réponse json {index}", tools=False)
            record["request"]["body"].update(shape)
            self.tap.add_record("T1", record)
        self.capture.scan_once()
        bodies = "\n".join(self.texts(pid))
        for index in range(3):
            self.assertIn(f"question json {index}", bodies)
            self.assertIn(f"réponse json {index}", bodies)
        self.assertNotIn("raisonnement caché", bodies)
        self.assertNotIn("consigne système privée", bodies)
        self.assertEqual(self.store.list_entries(other), [])
        self.assertTrue(all(entry["status"] == "proposed" for entry in self.store.list_entries(pid)))
        self.assertNotIn("side_request", self.state()["skipped"])

    def test_conversations_without_tools_are_captured_with_exact_identity(self):
        pid = self.project(self.folder_a)
        other = self.project(self.folder_b)
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        self.tap.create()
        self.tap.add_session("T1")
        self.capture.scan_once()
        empty = claude_record("S1", "question sans outil vide", "réponse sans outil vide", tools=False)
        empty["request"]["body"]["tools"] = []
        empty["request"]["body"]["max_tokens"] = 128000
        absent = claude_record("S1", "question sans outil absent", "réponse sans outil absent", tools=False)
        self.tap.add_record("T1", empty)
        self.tap.add_record("T1", absent)
        self.capture.scan_once()
        bodies = "\n".join(self.texts(pid))
        for expected in ("question sans outil vide", "réponse sans outil vide", "question sans outil absent", "réponse sans outil absent"):
            self.assertIn(expected, bodies)
        for forbidden in ("raisonnement caché", "consigne système privée"):
            self.assertNotIn(forbidden, bodies)
        self.assertEqual(self.store.list_entries(other), [])
        self.assertEqual(self.capture.pending(), [])
        self.assertNotIn("side_request", self.state()["skipped"])


class NativeFallbackTests(CaptureCase):
    def setUp(self):
        super().setUp()
        self.pid = self.project(self.folder_a)
        self.tap.create()
        self.tap.add_session("T0")
        patcher = patch.object(capture_module, "FALLBACK_GRACE", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def append_native(self, path, session, text):
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "assistant", "sessionId": session, "cwd": str(self.folder_a), "uuid": f"u-{text}", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}) + "\n")

    def test_enabled_by_default_and_explicitly_disabled_it_ingests_nothing(self):
        self.assertTrue(default_settings()["sources"]["native_fallback"])
        self.assertTrue(self.capture.status()["native"]["fallback"])
        self.configure(sources={"native_fallback": False})
        self.capture.scan_once()
        path = write_claude_transcript(self.claude_root, "S5", self.folder_a)
        self.append_native(path, "S5", "réponse native")
        self.capture.scan_once()
        self.assertEqual(self.store.list_entries(self.pid), [])

    def test_enabled_it_captures_unlinked_sessions_and_leaves_tap_sessions_alone(self):
        self.configure(sources={"native_fallback": True})
        self.capture.scan_once()
        only_native = write_claude_transcript(self.claude_root, "S5", self.folder_a, lines=0)
        self.append_native(only_native, "S5", "réponse native seule")
        via_tap = write_claude_transcript(self.claude_root, "S6", self.folder_a, lines=0)
        append_jsonl(via_tap, claude_line("S6", self.folder_a, "user", "question via tap", "u-q"), claude_line("S6", self.folder_a, "assistant", [{"type": "text", "text": "réponse via tap"}], "u-a"))
        self.tap.add_session("T6")
        self.tap.add_record("T6", claude_record("S6", "question via tap", "réponse via tap"))
        self.capture.scan_once()
        entries = self.store.list_entries(self.pid)
        fallback = [entry for entry in entries if "repli-natif" in entry["tags"]]
        self.assertEqual([entry["body"] for entry in fallback], ["réponse native seule"])
        self.assertEqual(self.provenance(fallback[0])["collector"], "native-fallback")
        self.assertEqual(sum("question via tap" in entry["body"] for entry in entries), 1)
        self.assertEqual(sum("réponse via tap" in entry["body"] for entry in entries), 1)
        self.assertTrue(any("claude-tap" in entry["tags"] for entry in entries))


class NativeCase(CaptureCase):
    """Native transcripts are read after a short grace; the tests remove it."""

    def setUp(self):
        super().setUp()
        patcher = patch.object(capture_module, "FALLBACK_GRACE", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def bodies(self, pid):
        return sorted(entry["body"] for entry in self.store.list_entries(pid))

    def fallback_entries(self, pid):
        return [entry for entry in self.store.list_entries(pid) if "repli-natif" in entry["tags"]]


class DirectNativeLaunchTests(NativeCase):
    def test_direct_claude_launch_without_tap_creates_the_project_and_proposals(self):
        write_claude_transcript(self.claude_root, "S-old", self.folder_a, lines=3)
        self.capture.scan_once()
        self.assertEqual(self.store.list_projects(), [])
        self.assertFalse(self.db.parent.exists())
        fresh = write_claude_transcript(self.claude_root, "S1", self.folder_a, lines=0)
        append_jsonl(fresh,
                     claude_line("S1", self.folder_a, "user", "Choisir SQLite", "u1"),
                     claude_line("S1", self.folder_a, "assistant", [{"type": "thinking", "thinking": "raisonnement caché"}, {"type": "text", "text": "Je propose SQLite."},
                                                                    {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest -q"}}], "u2"))
        self.capture.scan_once()
        projects = self.store.list_projects()
        self.assertEqual(len(projects), 1)
        self.assertEqual(Path(projects[0]["folder"]["path"]), self.folder_a)
        entries = self.store.list_entries(projects[0]["id"])
        self.assertEqual(len(entries), 3)
        self.assertEqual({entry["status"] for entry in entries}, {"proposed"})
        self.assertEqual(sum("pytest -q" in entry["body"] for entry in entries), 1)
        self.assertNotIn("raisonnement caché", json.dumps(entries, ensure_ascii=False))
        self.assertNotIn("note locale", json.dumps(entries, ensure_ascii=False))
        for entry in entries:
            self.assertIn("repli-natif", entry["tags"])
            provenance = self.provenance(entry)
            self.assertEqual((provenance["collector"], provenance["link"], provenance["native_id"], provenance["native_source"]), ("native-fallback", "native", "S1", "claude"))
            self.assertEqual(Path(provenance["cwd"]), self.folder_a)

    def test_first_scan_is_a_baseline_and_partial_lines_wait_for_their_newline(self):
        pid = self.project(self.folder_a)
        path = write_claude_transcript(self.claude_root, "S1", self.folder_a, lines=3)
        self.capture.scan_once()
        self.assertEqual(self.store.list_entries(pid), [])
        append_jsonl(path, claude_line("S1", self.folder_a, "user", "après la ligne de base", "u-new"))
        raw = json.dumps(claude_line("S1", self.folder_a, "assistant", [{"type": "text", "text": "réponse complète"}], "u-2"), ensure_ascii=False)
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(raw[:40])
        self.capture.scan_once()
        self.assertEqual(self.bodies(pid), ["après la ligne de base"])
        offset = next(value for key, value in self.state()["fallback"]["files"].items() if key.endswith("S1.jsonl"))
        self.capture.scan_once()
        self.assertEqual(next(value for key, value in self.state()["fallback"]["files"].items() if key.endswith("S1.jsonl")), offset)
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(raw[40:] + "\n")
        self.capture.scan_once()
        self.capture.scan_once()
        self.assertEqual(self.bodies(pid), ["après la ligne de base", "réponse complète"])

    def test_private_analysis_is_excluded_natively_and_through_tap(self):
        pid = self.project(self.folder_a)
        write_codex_transcript(self.codex_root, "C-tap", self.folder_a)
        self.tap.create()
        self.tap.add_session("T0")
        self.capture.scan_once()
        codex = write_codex_transcript(self.codex_root, "C1", self.folder_a)
        append_jsonl(codex, codex_message("user", "Question Codex"), codex_message("assistant", "analyse privée codex", channel="analysis"),
                     codex_message("assistant", "pensée privée variante", channel=" Reasoning "), codex_message("assistant", "Réponse finale Codex"))
        claude = write_claude_transcript(self.claude_root, "S1", self.folder_a, lines=0)
        append_jsonl(claude, claude_line("S1", self.folder_a, "assistant", [{"type": "text", "text": "pensée privée claude", "channel": "analysis"}, {"type": "reasoning_text", "text": "raisonnement natif"},
                                                                           {"type": "text", "text": "Réponse visible Claude"}], "u-1"))
        self.tap.add_session("T-codex", "codex")
        record = codex_record("C-tap", "Question via TAP", "Réponse finale TAP")
        record["response"]["body"]["output"].insert(0, {"type": "message", "role": "assistant", "channel": "analysis", "content": [{"type": "output_text", "text": "analyse TAP privée"}]})
        self.tap.add_record("T-codex", record)
        self.capture.scan_once()
        bodies = self.bodies(pid)
        everything = json.dumps(self.store.list_entries(pid), ensure_ascii=False)
        for visible in ("Question Codex", "Réponse finale Codex", "Réponse visible Claude", "Question via TAP", "Réponse finale TAP"):
            self.assertIn(visible, bodies)
        for private in ("analyse privée codex", "pensée privée variante", "pensée privée claude", "raisonnement natif", "analyse TAP privée", "raisonnement caché"):
            self.assertNotIn(private, everything)
        self.assertGreaterEqual(self.state()["skipped"].get("analysis", 0), 1)

    def test_same_folder_cross_agent_and_two_folders_stay_isolated_without_tap(self):
        self.capture.scan_once()
        codex = write_codex_transcript(self.codex_root, "C1", self.folder_a)
        claude_a = write_claude_transcript(self.claude_root, "S1", self.folder_a, lines=0)
        claude_b = write_claude_transcript(self.claude_root, "S2", self.folder_b, lines=0)
        for number in range(3):
            append_jsonl(claude_a, claude_line("S1", self.folder_a, "user", f"alpha claude {number}", f"a{number}"))
            append_jsonl(codex, codex_message("user", f"alpha codex {number}"))
            append_jsonl(claude_b, claude_line("S2", self.folder_b, "user", f"beta {number}", f"b{number}"))
        self.capture.scan_once()
        self.assertEqual(len(self.store.list_projects()), 2)
        pa, pb = (self.store.locate_project(str(folder))["id"] for folder in (self.folder_a, self.folder_b))
        self.assertNotEqual(pa, pb)
        self.assertEqual(len(self.bodies(pa)), 6)
        self.assertTrue(all("alpha" in body for body in self.bodies(pa)))
        self.assertEqual(len(self.bodies(pb)), 3)
        self.assertTrue(all("beta" in body for body in self.bodies(pb)))
        agents = {self.provenance(entry)["native_source"] for entry in self.store.list_entries(pa)}
        self.assertEqual(agents, {"claude", "codex"})

    def test_crash_between_import_and_offset_replays_without_duplicates(self):
        pid = self.project(self.folder_a)
        self.capture.scan_once()
        path = write_claude_transcript(self.claude_root, "S1", self.folder_a, lines=0)
        append_jsonl(path, claude_line("S1", self.folder_a, "user", "avant le crash", "u1"))
        with patch.object(Capture, "_save", side_effect=RuntimeError("crash après import")):
            with self.assertRaises(RuntimeError):
                self.capture.scan_once()
        self.assertEqual(self.bodies(pid), ["avant le crash"])
        restarted = Capture(self.store, env={})
        restarted.refresh_interval = restarted.index_interval = 0
        restarted.scan_once()
        restarted.scan_once()
        self.assertEqual(self.bodies(pid), ["avant le crash"])
        self.assertEqual(restarted._load_state()["counters"].get("duplicates"), 1)

    def test_a_file_written_continuously_is_still_read_after_the_wait_cap(self):
        pid = self.project(self.folder_a)
        self.capture.scan_once()
        path = write_claude_transcript(self.claude_root, "S1", self.folder_a, lines=0)
        append_jsonl(path, claude_line("S1", self.folder_a, "user", "écriture continue", "u1"))
        with patch.object(capture_module, "FALLBACK_GRACE", 1e12), patch.object(capture_module, "FALLBACK_MAX_WAIT", 1e9):
            self.capture.scan_once()
        self.assertEqual(self.store.list_entries(pid), [])
        self.assertTrue(self.state()["fallback"]["waits"])
        with patch.object(capture_module, "FALLBACK_GRACE", 1e12), patch.object(capture_module, "FALLBACK_MAX_WAIT", 0):
            self.capture.scan_once()
        self.assertEqual(self.bodies(pid), ["écriture continue"])
        self.assertFalse(self.state()["fallback"]["waits"])

    def test_explicit_native_id_mapping_applies_and_is_not_presented_as_native_proof(self):
        pa = self.project(self.folder_a)
        self.capture.scan_once()
        path = write_claude_transcript(self.claude_root, "S9", self.folder_b, lines=0)
        append_jsonl(path, claude_line("S9", self.folder_b, "user", "classé par choix", "u1"))
        self.capture.link("S9", pa)
        self.capture.scan_once()
        entries = self.store.list_entries(pa)
        self.assertEqual([entry["body"] for entry in entries], ["classé par choix"])
        provenance = self.provenance(entries[0])
        self.assertEqual(provenance["link"], "explicit")
        self.assertEqual(Path(provenance["target_folder"]), self.folder_a)
        self.assertIsNone(provenance["cwd"])

    def test_native_index_drops_the_old_folder_after_a_same_size_rewrite(self):
        path = write_claude_transcript(self.claude_root, "S1", self.folder_a)
        index = native_index.NativeIndex({"claude": self.claude_root})
        index.refresh()
        self.assertEqual([match["cwds"] for match in index.lookup("S1")], [[str(self.folder_a)]])
        before = path.stat()
        rewritten = write_claude_transcript(self.claude_root, "S1", self.folder_b)
        self.assertEqual(rewritten.stat().st_size, before.st_size)
        os.utime(rewritten, ns=(before.st_atime_ns, before.st_mtime_ns + 5_000_000_000))
        stats = index.refresh()
        self.assertEqual(stats["rewritten"], 1)
        self.assertEqual([match["cwds"] for match in index.lookup("S1")], [[str(self.folder_b)]])


class PauseAndHomeTests(NativeCase):
    def test_a_global_pause_keeps_lines_held_before_it_and_skips_only_the_pause(self):
        self.capture.scan_once()
        later = self.work / "plus-tard"
        path = write_claude_transcript(self.claude_root, "S1", later, lines=0)
        append_jsonl(path, claude_line("S1", later, "user", "avant la pause", "u1"), claude_line("S1", later, "assistant", [{"type": "text", "text": "retenu"}], "u2"))
        for _ in range(2):
            self.capture.scan_once()
        self.assertEqual([item["reason"] for item in self.capture.pending() if item["stalled"]], ["cwd_missing"])
        self.capture.set_paused(True)
        append_jsonl(path, claude_line("S1", later, "user", "écrit pendant la pause", "u3"))
        self.assertEqual(self.capture.scan_once()["state"], "paused")
        self.capture.set_paused(False)
        self.capture.scan_once()
        later.mkdir()
        self.capture.scan_once()
        self.capture.scan_once()
        project = self.store.locate_project(str(later))
        self.assertEqual(sorted(entry["body"] for entry in self.store.list_entries(project["id"])), ["avant la pause", "retenu"])
        append_jsonl(path, claude_line("S1", later, "user", "après la reprise", "u4"))
        self.capture.scan_once()
        bodies = sorted(entry["body"] for entry in self.store.list_entries(project["id"]))
        self.assertEqual(bodies, sorted(["avant la pause", "après la reprise", "retenu"]))
        self.assertEqual([item for item in self.capture.pending() if item["stalled"]], [])

    def test_a_pause_that_began_before_the_monitor_saw_it_still_keeps_held_lines(self):
        self.capture.scan_once()
        later = self.work / "plus-tard-2"
        path = write_claude_transcript(self.claude_root, "S2", later, lines=0)
        append_jsonl(path, claude_line("S2", later, "user", "retenu avant", "u1"))
        self.capture.scan_once()
        self.capture.set_enabled(False)  # only a hold file exists: the monitor has not run since
        append_jsonl(path, claude_line("S2", later, "user", "pendant la désactivation", "u2"))
        self.capture.set_enabled(True)
        self.capture.scan_once()
        later.mkdir()
        self.capture.scan_once()
        self.capture.scan_once()
        project = self.store.locate_project(str(later))
        self.assertEqual([entry["body"] for entry in self.store.list_entries(project["id"])], ["retenu avant"])

    def test_a_git_repository_above_the_home_folder_does_not_merge_unrelated_folders(self):
        self.capture.scan_once()
        (self.work / ".git").mkdir()
        fresh = write_claude_transcript(self.claude_root, "S1", self.folder_b, lines=0)
        append_jsonl(fresh, claude_line("S1", self.folder_b, "user", "dans B", "u1"))
        with patch.object(Path, "home", return_value=self.folder_a):
            self.capture.scan_once()
        projects = self.store.list_projects()
        self.assertEqual([Path(project["folder"]["path"]) for project in projects], [self.folder_b])

    def test_home_and_drive_roots_are_never_project_folders(self):
        with patch.object(Path, "home", return_value=self.folder_a):
            with self.assertRaises(ValueError):
                self.store.canonical_folder(str(self.folder_a))
        with self.assertRaises(ValueError):
            self.store.canonical_folder(str(Path(self.folder_a.anchor)))


class ChannelSwitchingTests(NativeCase):
    def setUp(self):
        super().setUp()
        self.pid = self.project(self.folder_a)
        self.tap.create()
        self.tap.add_session("T0")
        self.capture.scan_once()
        self.path = write_claude_transcript(self.claude_root, "S6", self.folder_a, lines=0)
        # A row that names the session and its folder (so the id resolves) but carries no message to ingest.
        append_jsonl(self.path, {"type": "system", "sessionId": "S6", "cwd": str(self.folder_a)})

    def native(self, role, text, uuid):
        content = text if role == "user" else [{"type": "text", "text": text}]
        append_jsonl(self.path, claude_line("S6", self.folder_a, role, content, uuid))

    def test_tap_then_native_does_not_duplicate_but_later_native_activity_is_captured(self):
        self.tap.add_session("T6")
        self.tap.add_record("T6", claude_record("S6", "question via tap", "réponse via tap"))
        self.native("user", "question via tap", "u1")
        self.native("assistant", "réponse via tap", "u2")
        self.capture.scan_once()
        entries = self.store.list_entries(self.pid)
        self.assertEqual(len(entries), 2)
        self.assertTrue(all("claude-tap" in entry["tags"] for entry in entries))
        self.native("assistant", "suite native seule", "u3")
        self.capture.scan_once()
        self.capture.scan_once()
        self.assertEqual(len(self.store.list_entries(self.pid)), 3)
        self.assertEqual([entry["body"] for entry in self.fallback_entries(self.pid)], ["suite native seule"])

    def test_native_activity_after_the_dedup_window_is_not_suppressed_by_old_tap_use(self):
        clock = [10_000]
        with patch.object(capture_module, "_clock", lambda: clock[0]):
            self.tap.add_session("T6")
            self.tap.add_record("T6", claude_record("S6", "continuer", "d'accord"))
            self.capture.scan_once()
            self.assertEqual(len(self.store.list_entries(self.pid)), 2)
            clock[0] += capture_module.DEDUP_WINDOW + 5
            self.native("user", "continuer", "u1")
            self.capture.scan_once()
        self.assertEqual([entry["body"] for entry in self.fallback_entries(self.pid)], ["continuer"])
        self.assertEqual(len(self.store.list_entries(self.pid)), 3)

    def test_native_then_tap_does_not_duplicate(self):
        self.native("user", "Q natif", "u1")
        self.native("assistant", "A natif", "u2")
        self.capture.scan_once()
        self.assertEqual(len(self.fallback_entries(self.pid)), 2)
        self.tap.add_session("T7")
        self.tap.add_record("T7", claude_record("S6", "Q natif", "A natif"))
        self.capture.scan_once()
        self.capture.scan_once()
        self.assertEqual(len(self.store.list_entries(self.pid)), 2)
        self.assertEqual(self.state()["skipped"].get("native_duplicate"), 2)

    def test_a_repeated_message_counts_once_per_channel_occurrence(self):
        self.tap.add_session("T6")
        self.tap.add_record("T6", claude_record("S6", "oui", "reçu"))
        self.native("user", "oui", "u1")
        self.native("user", "oui", "u2")  # a second, genuinely separate "oui" typed natively
        self.capture.scan_once()
        self.assertEqual(sum(entry["body"] == "oui" for entry in self.store.list_entries(self.pid)), 2)


class HeldNativeTests(NativeCase):
    """A native line whose session cannot be placed yet is held, never skipped; a deliberate pause or exclusion is skipped."""

    def offset(self, name):
        return next(value for key, value in self.state()["fallback"]["files"].items() if key.endswith(name))

    def test_an_unresolved_folder_holds_the_file_and_nothing_is_lost_when_it_resolves(self):
        self.capture.scan_once()
        later = self.work / "plus-tard"
        path = write_claude_transcript(self.claude_root, "S1", later, lines=0)
        append_jsonl(path, claude_line("S1", later, "user", "avant le dossier", "u1"), claude_line("S1", later, "assistant", [{"type": "text", "text": "suite"}], "u2"))
        for _ in range(2):
            self.capture.scan_once()
        self.assertEqual(self.store.list_projects(), [])
        self.assertEqual(self.offset("S1.jsonl"), 0)
        held = [item for item in self.capture.pending() if item["stalled"]]
        self.assertEqual([(item["key"], item["reason"], item["count"]) for item in held], [("S1", "cwd_missing", 0)])
        stored = "".join(self.capture._file(name).read_text(encoding="utf-8") for name in ("state.json", "pending.json"))
        self.assertNotIn("avant le dossier", stored)
        self.assertEqual(self.state()["skipped"].get("fallback_cwd_missing"), None)
        later.mkdir()
        self.capture.scan_once()
        self.capture.scan_once()
        project = self.store.locate_project(str(later))
        self.assertEqual(self.bodies(project["id"]), ["avant le dossier", "suite"])
        self.assertEqual([item for item in self.capture.pending() if item["stalled"]], [])
        self.assertEqual(self.offset("S1.jsonl"), path.stat().st_size)

    def test_a_held_session_is_placed_only_by_an_explicit_choice_and_keeps_its_order(self):
        pid = self.project(self.folder_a)
        self.capture.scan_once()
        path = write_claude_transcript(self.claude_root, "S3", self.folder_a, lines=0)
        append_jsonl(path, claude_line("S3", self.folder_a, "user", "première", "u1"), claude_line("S3", self.folder_b, "assistant", [{"type": "text", "text": "seconde"}], "u2"))
        self.capture.scan_once()
        self.assertEqual(self.store.list_entries(pid), [])
        self.assertEqual([(item["key"], item["reason"]) for item in self.capture.pending() if item["stalled"]], [("S3", "ambiguous_cwd")])
        self.capture.link("S3", pid)
        entries = self.store.list_entries(pid)
        self.assertEqual(sorted(entry["body"] for entry in entries), ["première", "seconde"])
        self.assertTrue(all(self.provenance(entry)["link"] == "explicit" for entry in entries))
        self.assertEqual(self.capture.pending(), [])

    def test_pause_and_exclusion_are_deliberate_skips_that_advance_the_offset(self):
        pid = self.project(self.folder_a)
        self.capture.scan_once()
        path = write_claude_transcript(self.claude_root, "S4", self.folder_a, lines=0)
        self.capture.set_paused(True, pid)
        append_jsonl(path, claude_line("S4", self.folder_a, "user", "pendant la pause", "u1"))
        self.capture.scan_once()
        self.assertEqual(self.store.list_entries(pid), [])
        self.assertEqual(self.offset("S4.jsonl"), path.stat().st_size)
        self.assertEqual(self.capture.pending(), [])
        self.assertEqual(self.state()["skipped"].get("paused"), 1)
        self.capture.set_paused(False, pid)
        self.capture.set_excluded(str(self.folder_a), True)
        append_jsonl(path, claude_line("S4", self.folder_a, "user", "dossier exclu", "u2"))
        self.capture.scan_once()
        self.assertEqual(self.store.list_entries(pid), [])
        self.assertEqual(self.offset("S4.jsonl"), path.stat().st_size)
        self.assertEqual(self.capture.pending(), [])

    def test_held_files_are_bounded_and_the_overflow_is_visible(self):
        self.capture.scan_once()
        with patch.object(capture_module, "MAX_STALLED", 1):
            for number in range(2):
                missing = self.work / f"absent-{number}"
                path = write_claude_transcript(self.claude_root, f"SB{number}", missing, lines=0)
                append_jsonl(path, claude_line(f"SB{number}", missing, "user", f"texte {number}", f"u{number}"))
            self.capture.scan_once()
        self.assertEqual(len([item for item in self.capture.pending() if item["stalled"]]), 1)
        self.assertEqual(self.state()["skipped"].get("fallback_held_overflow"), 1)
        self.assertTrue(any(notice["code"] == "native_held_overflow" for notice in self.state()["notices"]))


class ExplicitConflictTests(CaptureCase):
    def setUp(self):
        super().setUp()
        self.pa = self.project(self.folder_a, "A")
        self.pb = self.project(self.folder_b, "B")
        self.tap.create()
        self.tap.add_session("T0")
        self.configure(sources={"native_fallback": False})
        self.capture.scan_once()

    def conflicting(self, text="texte contradictoire"):
        record = claude_record("S1", text)
        record["request"]["headers"]["X-Claude-Code-Session-Id"] = "S2"
        return record

    def test_conflicting_ids_stay_pending_and_only_an_explicit_choice_links_them(self):
        write_claude_transcript(self.claude_root, "S1", self.folder_b)
        write_claude_transcript(self.claude_root, "S2", self.folder_b)
        self.tap.add_session("T1")
        self.tap.add_record("T1", self.conflicting())
        self.capture.scan_once()
        self.capture.scan_once()
        self.assertEqual({item["key"]: item["reason"] for item in self.capture.pending()}, {"tap:T1": "ambiguous_native_id"})
        self.assertEqual((self.store.list_entries(self.pa), self.store.list_entries(self.pb)), ([], []))
        self.capture.link("tap:T1", self.pa)
        entries = self.store.list_entries(self.pa)
        self.assertEqual(len(entries), 2)
        self.assertEqual(self.store.list_entries(self.pb), [])
        self.assertEqual(self.capture.pending(), [])
        for entry in entries:
            provenance = self.provenance(entry)
            self.assertEqual(provenance["link"], "explicit")
            self.assertIsNone(provenance["native_id"])
            self.assertIsNone(provenance["cwd"])
            self.assertEqual(provenance["claimed_native_ids"], ["S1", "S2"])
            self.assertEqual(Path(provenance["target_folder"]), self.folder_a)
            self.assertIn("aucune preuve", provenance["target_basis"])

    def test_codex_session_and_thread_divergence_stays_pending(self):
        write_codex_transcript(self.codex_root, "C1", self.folder_a)
        record = codex_record("C1", "divergence")
        record["request"]["body"]["client_metadata"]["x-codex-turn-metadata"] = json.dumps({"session_id": "C1", "thread_id": "C2"})
        self.tap.add_session("T2", "codex")
        self.tap.add_record("T2", record)
        self.capture.scan_once()
        self.assertEqual({item["key"]: item["reason"] for item in self.capture.pending()}, {"tap:T2": "ambiguous_native_id"})
        self.assertEqual(self.store.list_entries(self.pa), [])

    def test_contradictory_explicit_mappings_are_never_resolved(self):
        self.capture.link("S1", self.pa)
        self.capture.link("tap:T2", self.pb)
        self.tap.add_session("T2")
        self.tap.add_record("T2", claude_record("S1", "deux choix opposés"))
        self.capture.scan_once()
        self.assertEqual({item["key"]: item["reason"] for item in self.capture.pending()}, {"tap:T2": "mapping_conflict"})
        self.assertEqual((self.store.list_entries(self.pa), self.store.list_entries(self.pb)), ([], []))

    def test_a_rejected_link_writes_nothing_and_an_unreadable_file_is_not_overwritten(self):
        with self.assertRaises(CaptureError):
            self.capture.link("S404", self.pa, import_history=True)
        self.assertFalse(self.capture._file("mappings.json").exists())
        self.capture._file("mappings.json").write_text("{pas du json", encoding="utf-8")
        with self.assertRaises(CaptureError):
            self.capture.link("tap:T1", self.pa)
        with self.assertRaises(CaptureError):
            self.capture.unlink("tap:T1")
        self.assertEqual(self.capture._file("mappings.json").read_text(encoding="utf-8"), "{pas du json")


class SettingsLockTests(CaptureCase):
    def test_settings_write_waits_for_the_store_lock(self):
        held, release, done = threading.Event(), threading.Event(), threading.Event()

        def holder():
            with self.store._lock:
                held.set()
                release.wait(10)

        def writer():
            self.capture.set_excluded(str(self.folder_b), True)
            done.set()

        owner = threading.Thread(target=holder)
        owner.start()
        self.assertTrue(held.wait(5))
        worker = threading.Thread(target=writer)
        worker.start()
        self.assertFalse(done.wait(0.5))
        release.set()
        owner.join()
        worker.join(10)
        self.assertTrue(done.is_set())
        self.assertEqual([Path(item) for item in self.capture.settings()[0]["exclude"]], [self.folder_b])

    def test_concurrent_writers_lose_no_setting_and_no_mapping(self):
        pid = self.project(self.folder_a)
        other = Capture(self.store, env={})
        folders = []
        for number in range(24):
            folder = self.work / f"X{number}"
            folder.mkdir()
            folders.append(folder)
        errors = []

        def work(capture, subset, offset):
            try:
                for number, folder in enumerate(subset):
                    capture.set_excluded(str(folder), True)
                    capture.link(f"tap:K{offset}-{number}", pid)
            except Exception as exc:  # reported below
                errors.append(exc)

        threads = [threading.Thread(target=work, args=(self.capture, folders[::2], 0)), threading.Thread(target=work, args=(other, folders[1::2], 1))]
        with patch.object(Capture, "scan_if_possible", return_value=False):
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(60)
        self.assertEqual(errors, [])
        self.assertEqual(len(self.capture.settings()[0]["exclude"]), 24)
        self.assertEqual(len(self.capture._mappings()), 24)


class DatabaseChangeTests(CaptureCase):
    def test_pending_keys_of_another_database_are_quarantined_not_replayed(self):
        pid = self.project(self.folder_a)
        self.configure(sources={"native_fallback": False})
        self.tap.create()
        self.tap.add_session("T2")
        self.capture.scan_once()
        self.tap.add_record("T2", claude_record("S404", "contenu de la première base"))
        self.capture.scan_once()
        self.assertEqual([item["key"] for item in self.capture.pending()], ["S404"])
        other_path = self.root / "tap2" / "traces.sqlite3"
        other = TapDB(other_path).create()
        self.addCleanup(other.close)
        other.add_session("T2")
        other.add_record("T2", claude_record("S404", "contenu étranger"))
        self.configure(tap={"db": str(other_path)}, sources={"native_fallback": False})
        self.capture.scan_once()
        self.assertEqual(self.capture.pending(), [])
        quarantined = list(self.capture.directory.glob("pending.quarantine-*.json"))
        self.assertEqual(len(quarantined), 1)
        self.assertNotIn("contenu", quarantined[0].read_text(encoding="utf-8"))
        self.assertTrue(any(notice["code"] == "pending_quarantined" for notice in self.state()["notices"]))
        write_claude_transcript(self.claude_root, "S404", self.folder_a)
        self.capture.scan_once()
        self.capture.scan_once()
        self.assertEqual(self.store.list_entries(pid), [])


class ScopedMappingTests(CaptureCase):
    def test_a_tap_mapping_applies_only_to_the_database_it_was_chosen_against(self):
        pid = self.project(self.folder_a)
        self.configure(sources={"native_fallback": False})
        self.tap.create()
        self.tap.add_session("T9")
        self.tap.add_record("T9", claude_record(None, "ancien"))
        self.capture.scan_once()
        self.tap.add_record("T9", claude_record(None, "première base"))
        self.capture.scan_once()
        self.capture.link("tap:T9", pid)
        self.assertIn("première base", self.texts(pid))
        other_path = self.root / "tap2" / "traces.sqlite3"
        other = TapDB(other_path).create()
        self.addCleanup(other.close)
        other.add_session("T9")
        other.add_record("T9", claude_record(None, "ancien étranger"))
        self.configure(tap={"db": str(other_path)}, sources={"native_fallback": False})
        self.capture.scan_once()
        other.add_record("T9", claude_record(None, "contenu étranger"))
        self.capture.scan_once()
        self.assertNotIn("contenu étranger", "\n".join(self.texts(pid)))
        self.assertEqual([item["key"] for item in self.capture.pending()], ["tap:T9"])
        status = self.capture.status()
        self.assertEqual((status["mappings"], status["mappings_other_database"]), (0, 1))
        stored = json.loads(self.capture._file("mappings.json").read_text(encoding="utf-8"))
        self.assertTrue(all("@" in key for key in stored))
        # Choosing again for the new database is a separate, explicit act.
        self.capture.link("tap:T9", pid)
        self.assertIn("contenu étranger", "\n".join(self.texts(pid)))
        self.assertEqual(len(self.capture._stored_mappings()), 2)

    def test_native_id_mappings_follow_the_session_not_the_database(self):
        pid = self.project(self.folder_a)
        self.capture.link("S-native", pid)
        self.configure(tap={"db": str(self.root / "elsewhere.sqlite3")})
        self.assertEqual(self.capture._mappings(), {"S-native": pid})


class RobustnessTests(CaptureCase):
    def test_an_unexpected_record_failure_costs_one_record_not_the_monitor(self):
        pid = self.project(self.folder_a)
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        self.tap.create()
        self.tap.add_session("T1")
        self.capture.scan_once()
        self.tap.add_record("T1", claude_record("S1", "BOOM"))
        self.tap.add_record("T1", claude_record("S1", "après l'échec"))
        original = tap_source.extract_turn

        def fragile(record):
            if "BOOM" in json.dumps(record):
                raise TypeError("forme inattendue")
            return original(record)

        with patch.object(tap_source, "extract_turn", fragile):
            self.capture.scan_once()
        self.assertIn("Utilisateur · après l'échec", [entry["title"] for entry in self.store.list_entries(pid)])
        self.assertEqual(self.state()["malformed"].get("processing_error"), 1)

    def test_a_failing_native_source_is_reported_and_does_not_block_tap(self):
        pid = self.project(self.folder_a)
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        self.tap.create()
        self.tap.add_session("T1")
        self.capture.scan_once()
        self.tap.add_record("T1", claude_record("S1", "malgré la panne native"))
        with patch.object(Capture, "_scan_fallback", side_effect=OSError("disque")):
            self.capture.scan_once()
        self.assertEqual(len(self.store.list_entries(pid)), 2)
        self.assertTrue(any(notice["code"] == "source_error" for notice in self.state()["notices"]))


class IntegrityTests(CaptureCase):
    def test_agent_files_are_untouched_and_no_network_is_used(self):
        pid = self.project(self.folder_a)
        guarded = {self.folder_a / "CLAUDE.md": "règles", self.folder_a / "AGENTS.md": "règles", self.folder_a / ".claude" / "settings.json": "{}", self.folder_a / ".codex" / "config.toml": "x = 1"}
        for path, text in guarded.items():
            path.parent.mkdir(exist_ok=True)
            path.write_text(text, encoding="utf-8")
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in guarded}
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        self.tap.create()
        self.tap.add_session("T1")
        self.capture.scan_once()
        self.tap.add_record("T1", claude_record("S1", "sans réseau"))
        with patch("socket.socket.connect", side_effect=AssertionError("network used")), patch("socket.create_connection", side_effect=AssertionError("network used")):
            self.capture.scan_once()
        self.assertEqual(len(self.store.list_entries(pid)), 2)
        self.assertEqual({path: (path.read_bytes(), path.stat().st_mtime_ns) for path in guarded}, before)
        self.assertEqual({path.name for path in self.folder_a.iterdir()}, {"CLAUDE.md", "AGENTS.md", ".claude", ".codex"})


class ProcessControlTests(CaptureCase):
    def test_os_lock_is_exclusive_and_released_on_close(self):
        path = self.root / "locks" / "capture.lock"
        first, second = ProcessLock(path), ProcessLock(path)
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        first.release()
        self.assertTrue(second.acquire())
        second.release()

    def test_monitor_thread_starts_once_and_stops_cooperatively(self):
        self.tap.create()
        self.assertFalse(self.capture.is_running())
        self.assertTrue(self.capture.start(interval=0.05))
        self.addCleanup(self.capture.stop)
        other = Capture(self.store, env={})
        self.assertFalse(other.start(interval=0.05))
        self.assertTrue(other.is_running())
        self.assertEqual(self.capture.request_stop(wait=5), "stopped")
        self.assertFalse(self.capture.is_running())
        self.assertFalse(self.capture._file("stop").exists())

    def test_monitor_captures_while_running(self):
        pid = self.project(self.folder_a)
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        self.tap.create()
        self.tap.add_session("T1")
        self.capture.scan_once()
        self.assertTrue(self.capture.start(interval=0.05))
        self.addCleanup(self.capture.stop)
        self.tap.add_record("T1", claude_record("S1", "capturé par le moniteur"))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not self.store.list_entries(pid):
            time.sleep(0.05)
        self.assertEqual(len(self.store.list_entries(pid)), 2)


class CommandLineTests(CaptureCase):
    def run_cli(self, *arguments):
        output = io.StringIO()
        # Point the default database lookup at a synthetic path: tests never probe a real trace store.
        with patch.dict(os.environ, {"CLOUDTAP_DB": str(self.db)}), contextlib.redirect_stdout(output):
            cli.main(["--data-dir", str(self.memory), *arguments])
        return output.getvalue()

    def test_create_requires_a_folder_and_binds_it(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.main(["--data-dir", str(self.memory), "create", "Sans dossier"])
        created = json.loads(self.run_cli("create", "Avec dossier", "--folder", str(self.folder_a)))
        self.assertEqual(Path(created["folder"]["path"]), self.folder_a)

    def test_mcp_config_is_printed_and_nothing_is_written(self):
        before = sorted(path.name for path in self.root.rglob("*"))
        text = self.run_cli("mcp-config", "--client", "codex")
        self.assertIn("[mcp_servers.filigree]", text)
        self.assertIn(json.dumps(str(self.memory.resolve())), text)
        self.assertIn("mcpServers", self.run_cli("mcp-config", "--client", "claude"))
        self.assertEqual(sorted(path.name for path in self.root.rglob("*")), before)

    def test_capture_status_pause_exclude_and_pending_commands(self):
        status = json.loads(self.run_cli("capture", "status"))
        self.assertTrue(status["enabled"])
        self.assertTrue(status["auto_create"])
        self.run_cli("capture", "pause")
        self.assertTrue(json.loads(self.run_cli("capture", "status"))["paused_all"])
        self.run_cli("capture", "resume")
        self.run_cli("capture", "exclude", str(self.folder_b))
        self.assertEqual([Path(item) for item in json.loads(self.run_cli("capture", "status"))["exclude"]], [self.folder_b])
        self.run_cli("capture", "include", str(self.folder_b))
        self.assertEqual(json.loads(self.run_cli("capture", "pending")), [])


if __name__ == "__main__":
    unittest.main()
