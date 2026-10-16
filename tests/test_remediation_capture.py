"""Regressions for the independent verification of 2026-10-16 (capture: B-2..B-7 and capture P3).

Every Capture here names an explicit synthetic claude-tap database and synthetic transcript roots inside a
temporary folder: no default (real) source is ever instantiated, read or probed."""

import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

try:
    from tap_fixtures import TapDB, append_jsonl, claude_line, claude_record, codex_message, codex_record, write_claude_transcript, write_codex_transcript
except ImportError:  # run as tests.test_remediation_capture from the repository root
    from tests.tap_fixtures import TapDB, append_jsonl, claude_line, claude_record, codex_message, codex_record, write_claude_transcript, write_codex_transcript

from filigree import capture as capture_module
from filigree import cli, native_index, tap_source
from filigree.capture import Capture, CaptureError, default_settings
from filigree.store import Store, folder_key


class Synthetic(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.root / "memory")
        self.work = self.root / "work"
        self.folder_a = self.work / "A"
        self.folder_a.mkdir(parents=True)
        self.claude_root = self.root / "claude" / "projects"
        self.codex_root = self.root / "codex" / "sessions"
        self.db = self.root / "tap" / "traces.sqlite3"
        self.tap = TapDB(self.db)
        self.addCleanup(self.tap.close)
        self.tap.create()
        self.tap.add_session("T0")
        self.capture = Capture(self.store, env={})
        self.capture.refresh_interval = 0
        self.capture.index_interval = 0
        settings = default_settings()
        settings["tap"]["db"] = str(self.db)
        settings["roots"] = {"claude": str(self.claude_root), "codex": str(self.codex_root)}
        self.capture._save_settings(settings)
        patcher = patch.object(capture_module, "FALLBACK_GRACE", 0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.assertEqual(self.capture.status()["native"]["roots"]["claude"], str(self.claude_root))

    def bodies(self, pid):
        return sorted(entry["body"] for entry in self.store.list_entries(pid))

    def all_bodies(self):
        return sorted(body for project in self.store.list_projects() for body in self.bodies(project["id"]))

    def state(self):
        return self.capture._load_state()

    def baseline(self):
        self.capture.scan_once()
        self.capture.scan_once()

    def project(self, folder, name="Projet"):
        return self.store.create_project(name, "", folder=str(folder))["id"]

    def native_row(self, session, cwd, text, uuid):
        return claude_line(session, cwd, "user", [{"type": "text", "text": text}], uuid)

    def raw_user_line(self, session, cwd, content_json, uuid):
        return '{"type":"user","sessionId":"%s","cwd":%s,"uuid":"%s","message":{"role":"user","content":%s}}' % (session, json.dumps(str(cwd)), uuid, content_json)


class InjectedContextTests(Synthetic):
    """B-2: injected XML blocks are stripped, the user's own text around them is kept."""

    def test_visible_text_keeps_the_user_text_around_injected_blocks(self):
        cases = {
            "<system-reminder>règle cachée</system-reminder>\nQuelle base choisir ?": "Quelle base choisir ?",
            "<ide_selection>The user selected lines 1-3</ide_selection>Explique ce code": "Explique ce code",
            "<environment_context>\n<cwd>/x</cwd>\n</environment_context>\nFais le plan": "Fais le plan",
            "Avant <system-reminder>caché</system-reminder> après": "Avant  après",
            "<ide_opened_file>a.py</ide_opened_file>\n<system-reminder>x</system-reminder>\nQuestion": "Question",
            "<command-name>/model</command-name><command-args>haiku</command-args>": "",
            "<system-reminder>jamais fermé, texte caché": "",
            "<system-reminder>a</system-reminder>": "",
            "# AGENTS.md instructions for /x\n\n<INSTRUCTIONS>consignes</INSTRUCTIONS>": "",
            "Garde <b>le gras</b> et a < b": "Garde <b>le gras</b> et a < b",
        }
        for text, expected in cases.items():
            self.assertEqual(" ".join(tap_source.visible_text(text).split()), " ".join(expected.split()), text)
        for hidden in ("règle cachée", "caché", "consignes", "cwd"):
            for text in cases:
                self.assertNotIn(hidden, tap_source.visible_text(text)) if hidden in text and "Avant" not in text else None

    def test_tap_turn_with_a_leading_reminder_still_captures_the_question(self):
        pid = self.project(self.folder_a)
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        self.baseline()
        self.tap.add_record("T0", claude_record("S1", "", "Réponse", last_blocks=[{"type": "text", "text": "<system-reminder>consigne interne</system-reminder>\nQuelle base choisir ?"}]))
        self.capture.scan_once()
        bodies = self.bodies(pid)
        self.assertIn("Quelle base choisir ?", bodies)
        self.assertFalse(any("consigne interne" in body for body in bodies))
        self.assertFalse(any("raisonnement caché" in body for body in bodies))

    def test_native_row_with_a_leading_reminder_captures_the_question(self):
        pid = self.project(self.folder_a)
        self.baseline()
        path = write_claude_transcript(self.claude_root, "S2", self.folder_a, lines=0)
        append_jsonl(path, self.native_row("S2", self.folder_a, "<ide_selection>sélection</ide_selection>\nPourquoi ce choix ?", "u1"),
                     claude_line("S2", self.folder_a, "assistant", [{"type": "thinking", "thinking": "SECRET-RAISONNEMENT"}, {"type": "text", "text": "Parce que."}], "u2"))
        self.capture.scan_once()
        self.assertEqual(self.bodies(pid), ["Parce que.", "Pourquoi ce choix ?"])
        self.assertNotIn("SECRET-RAISONNEMENT", json.dumps(self.store.list_entries(pid)))

    def test_codex_environment_context_prefix_keeps_the_real_request(self):
        pid = self.project(self.folder_a)
        self.baseline()
        path = write_codex_transcript(self.codex_root, "cx-1", self.folder_a)
        append_jsonl(path, codex_message("user", "<environment_context><cwd>x</cwd></environment_context>\nRenomme la fonction"), codex_message("assistant", "Fait", channel="analysis"))
        self.capture.scan_once()
        self.assertEqual(self.bodies(pid), ["Renomme la fonction"])


class IsolationTests(Synthetic):
    """B-3: a hostile folder never starves the sessions after it."""

    def long_folder(self):
        folder = self.work / ("L" * 170)
        folder.mkdir()
        return folder

    def test_native_session_in_a_very_long_folder_does_not_block_the_next_sessions(self):
        good = self.work / "good"
        good.mkdir()
        long_folder = self.long_folder()
        self.baseline()
        append_jsonl(write_claude_transcript(self.claude_root, "a-long", long_folder, lines=0), self.native_row("a-long", long_folder, "dans le dossier long", "l1"))
        append_jsonl(write_claude_transcript(self.claude_root, "b-good", good, lines=0), self.native_row("b-good", good, "dans le dossier normal", "g1"))
        for _ in range(3):
            self.capture.scan_once()
        self.assertIn("dans le dossier normal", self.all_bodies())
        self.assertEqual(self.all_bodies().count("dans le dossier long"), 1)  # placed (name shortened) or held, never an error loop
        self.assertTrue(all(len(project["name"]) <= 160 for project in self.store.list_projects()))
        self.assertEqual(self.state()["malformed"].get("native_fallback"), None)

    def test_tap_session_in_a_very_long_folder_does_not_block_the_next_sessions(self):
        good = self.work / "good"
        good.mkdir()
        long_folder = self.long_folder()
        write_claude_transcript(self.claude_root, "S-long", long_folder)
        write_claude_transcript(self.claude_root, "S-good", good)
        self.tap.add_session("T1")
        self.baseline()
        self.tap.add_record("T0", claude_record("S-long", "question dossier long"))
        self.tap.add_record("T1", claude_record("S-good", "question dossier normal"))
        for _ in range(2):
            self.capture.scan_once()
        self.assertIn("question dossier normal", self.all_bodies())
        self.assertEqual(self.state()["malformed"].get("tap"), None)

    def test_one_failing_line_costs_one_line_and_is_counted(self):
        pid = self.project(self.folder_a)
        self.baseline()
        path = write_claude_transcript(self.claude_root, "S3", self.folder_a, lines=0)
        append_jsonl(path, self.native_row("S3", self.folder_a, "BOOM", "u1"), self.native_row("S3", self.folder_a, "après", "u2"))
        real = tap_source.content_items

        def fragile(role, content, skipped, private=False):
            if "BOOM" in json.dumps(content):
                raise TypeError("hostile shape")
            return real(role, content, skipped, private)
        with patch.object(tap_source, "content_items", fragile):
            self.capture.scan_once()
            self.capture.scan_once()
        self.assertEqual(self.bodies(pid), ["après"])
        self.assertEqual(self.state()["malformed"].get("native_line_error"), 1)


class GenericRootTests(Synthetic):
    """B-7: no automatic project for generic roots, no merging below them, legitimate subprojects stay possible."""

    def setUp(self):
        super().setUp()
        self.fake_temp = self.root / "fake_temp"
        self.fake_home = self.root / "fake_users" / "me"
        for folder in (self.fake_temp, self.fake_home):
            folder.mkdir(parents=True)
        for patcher in (patch.object(capture_module.tempfile, "gettempdir", return_value=str(self.fake_temp)), patch.object(Path, "home", return_value=self.fake_home)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_session(self, session, cwd, text):
        append_jsonl(write_claude_transcript(self.claude_root, session, cwd, lines=0), self.native_row(session, cwd, text, f"u-{session}"))
        self.capture.scan_once()
        self.capture.scan_once()

    def test_system_temp_and_user_folders_never_become_projects(self):
        self.baseline()
        for session, folder in (("S-tmp", self.fake_temp), ("S-users", self.fake_home.parent), ("S-home", self.fake_home)):
            self.run_session(session, folder, f"dans {session}")
        self.assertEqual(self.store.list_projects(), [])
        self.assertEqual(self.all_bodies(), [])
        reasons = {item["key"]: item["reason"] for item in self.capture.pending() if item["stalled"]}
        self.assertEqual(reasons, {"S-tmp": "cwd_refused", "S-users": "cwd_refused", "S-home": "cwd_refused"})

    def test_subfolders_of_temp_get_their_own_project_and_are_never_merged(self):
        self.baseline()
        one, two = self.fake_temp / "one", self.fake_temp / "two"
        one.mkdir(), two.mkdir()
        self.run_session("S1", one, "dans un")
        self.run_session("S2", two, "dans deux")
        projects = {project["name"]: project for project in self.store.list_projects()}
        self.assertEqual(sorted(projects), ["one", "two"])
        self.assertEqual(self.bodies(projects["one"]["id"]), ["dans un"])
        self.assertEqual(self.bodies(projects["two"]["id"]), ["dans deux"])

    def test_a_legacy_project_bound_to_temp_does_not_absorb_subfolders(self):
        # The store now refuses such a project, but data created by an older version may still hold one.
        legacy = self.project(self.work / "A", "Temp")
        manifest = self.store.root / "projects" / legacy / "project.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["folder"] = {"path": str(self.fake_temp), "key": folder_key(self.fake_temp)}
        manifest.write_text(json.dumps(data), encoding="utf-8")
        self.baseline()
        sub = self.fake_temp / "sub"
        sub.mkdir()
        self.run_session("S1", sub, "dans sub")
        self.assertEqual(self.bodies(legacy), [])
        self.assertEqual(sorted(project["name"] for project in self.store.list_projects()), ["Temp", "sub"])

    def test_a_git_repository_at_a_generic_root_does_not_merge_its_subfolders(self):
        (self.fake_temp / ".git").mkdir()
        sub = self.fake_temp / "app"
        sub.mkdir()
        self.baseline()
        self.run_session("S1", sub, "dans app")
        self.assertEqual([project["folder"]["path"] for project in self.store.list_projects()], [str(sub)])

    def test_legitimate_subprojects_of_home_and_a_nested_git_repository_still_work(self):
        repo = self.fake_home / "code" / "repo"
        (repo / ".git").mkdir(parents=True)
        (repo / "pkg").mkdir()
        self.baseline()
        self.run_session("S1", repo / "pkg", "dans le paquet")
        projects = self.store.list_projects()
        self.assertEqual([project["folder"]["path"] for project in projects], [str(repo)])
        self.assertEqual(self.bodies(projects[0]["id"]), ["dans le paquet"])

    def test_tap_sessions_follow_the_same_rule(self):
        write_claude_transcript(self.claude_root, "S-tap", self.fake_temp)
        self.baseline()
        self.tap.add_record("T0", claude_record("S-tap", "dans temp via tap"))
        self.capture.scan_once()
        self.assertEqual(self.store.list_projects(), [])
        self.assertEqual([(item["key"], item["reason"]) for item in self.capture.pending() if not item["stalled"]], [("S-tap", "cwd_refused")])


class FileLinkTests(Synthetic):
    """B-4: a file: key either places the held rollout or is rejected clearly."""

    def message(self, role, text):
        return codex_message(role, text)

    def test_linking_a_held_rollout_without_session_meta_replays_it_in_order(self):
        pid = self.project(self.folder_a)
        self.baseline()
        path = self.codex_root / "2026" / "10" / "16" / "rollout-sans-meta.jsonl"
        path.parent.mkdir(parents=True)
        append_jsonl(path, self.message("user", "premier"), self.message("assistant", "second"))
        self.capture.scan_once()
        held = [item for item in self.capture.pending() if item["stalled"]]
        self.assertEqual(len(held), 1)
        key = held[0]["key"]
        self.assertTrue(key.startswith("file:"))
        self.assertEqual(self.bodies(pid), [])
        result = self.capture.link(key, pid)
        self.assertTrue(result["replayed"])
        self.assertEqual(self.bodies(pid), ["premier", "second"])
        self.assertEqual([item for item in self.capture.pending() if item["stalled"]], [])
        provenance = json.loads(next(item for item in self.store.list_entries(pid)[0]["sources"] if item["label"] == "Provenance de capture")["excerpt"])
        self.assertEqual((provenance["link"], provenance["native_id"]), ("explicit", key))
        self.capture.scan_once()
        self.assertEqual(len(self.bodies(pid)), 2)

    def test_linking_a_rollout_with_two_session_meta_places_both_halves(self):
        pid = self.project(self.folder_a)
        self.baseline()
        path = self.codex_root / "2026" / "10" / "16" / "rollout-fork.jsonl"
        path.parent.mkdir(parents=True)
        meta = lambda name: {"type": "session_meta", "payload": {"id": name, "cwd": str(self.folder_a)}}
        append_jsonl(path, meta("cx-1"), self.message("user", "avant fork"), meta("cx-2"), self.message("user", "après fork"))
        self.capture.scan_once()
        key = next(item["key"] for item in self.capture.pending() if item["stalled"])
        self.assertTrue(key.startswith("file:"))
        self.capture.link(key, pid)
        self.assertEqual(self.bodies(pid), sorted(["avant fork", "après fork"]))

    def test_a_file_key_that_matches_no_held_transcript_is_rejected_without_a_mapping(self):
        pid = self.project(self.folder_a)
        self.baseline()
        with self.assertRaises(CaptureError):
            self.capture.link("file:rollout-inexistant.jsonl", pid)
        self.assertEqual(self.capture._stored_mappings(), {})

    def test_link_validations_name_the_problem_in_french(self):
        pid = self.project(self.folder_a)
        self.baseline()
        for call in (lambda: self.capture.link("S1", "00000000-0000-4000-8000-000000000000"),
                     lambda: self.capture.link("S1", "pas-un-uuid"),
                     lambda: self.capture.link("tap:absente", pid, True),
                     lambda: self.capture.unlink("x" * 300),
                     lambda: self.capture.set_paused(True, "00000000-0000-4000-8000-000000000000")):
            with self.assertRaises(CaptureError) as caught:
                call()
            self.assertNotIn("Project not found", str(caught.exception))
            self.assertNotEqual(str(caught.exception), "Invalid ID")
        self.assertEqual(self.capture._stored_mappings(), {})
        self.assertFalse(self.capture._load_pending())


class InvalidTextTests(Synthetic):
    """B-5 / B-6: NUL, lone surrogates and invalid UTF-8 are surfaced and never lose another line or session."""

    def test_nul_and_lone_surrogate_lines_are_repaired_and_counted_not_lost(self):
        pid = self.project(self.folder_a)
        self.baseline()
        path = write_claude_transcript(self.claude_root, "sn", self.folder_a, lines=0)
        backslash = chr(92)
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            for number, content in enumerate(('"avec NUL ' + backslash + 'u0000 binaire"', '"coupé ' + backslash + 'ud83d fin"', '"normale"')):
                handle.write(self.raw_user_line("sn", self.folder_a, content, f"u{number}") + "\n")
        append_jsonl(path, claude_line("sn", self.folder_a, "user", [{"type": "tool_result", "tool_use_id": "t", "content": "\x00\x01sortie\x00"}], "ub"))
        self.capture.scan_once()
        bodies = self.bodies(pid)
        self.assertEqual(len(bodies), 4, bodies)
        self.assertIn("normale", bodies)
        self.assertTrue(any("avec NUL" in body and "\x00" not in body for body in bodies))
        state = self.state()
        self.assertGreaterEqual(state["skipped"].get("fallback_invalid_text_repaired", 0), 3)
        self.assertEqual(state["counters"].get("rejected"), None)

    def test_invalid_utf8_native_line_is_counted_once_and_neighbours_survive(self):
        pid = self.project(self.folder_a)
        self.baseline()
        path = write_claude_transcript(self.claude_root, "su", self.folder_a, lines=0)
        append_jsonl(path, self.native_row("su", self.folder_a, "avant", "u1"))
        with open(path, "ab") as handle:
            handle.write(b'{"type":"user","sessionId":"su","cwd":' + json.dumps(str(self.folder_a)).encode() + b',"uuid":"u2","message":{"role":"user","content":"cass\xe9 \xff fin"}}\n')
        append_jsonl(path, self.native_row("su", self.folder_a, "après", "u3"))
        for _ in range(3):
            self.capture.scan_once()
        bodies = self.bodies(pid)
        self.assertEqual(len(bodies), 3, bodies)
        self.assertIn("avant", bodies)
        self.assertIn("après", bodies)
        self.assertEqual(self.state()["malformed"].get("native_invalid_utf8"), 1)

    def test_invalid_utf8_in_the_tap_database_does_not_block_other_records_or_sessions(self):
        pid = self.project(self.folder_a)
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        write_claude_transcript(self.claude_root, "S2", self.folder_a)
        self.tap.add_session("T1")
        self.baseline()
        broken = json.dumps(claude_record("S1", "cassé", "ok"), ensure_ascii=False).encode("utf-8").replace("cassé".encode("utf-8"), b"cass\xe9\xff")
        self.tap.connection.execute("INSERT INTO records(session_id, record_index, turn, timestamp, payload_json) VALUES ('T0', 1, 1, 't', CAST(? AS TEXT))", (broken,))
        self.tap.connection.execute("UPDATE sessions SET record_count = 1, updated_at = 'u1' WHERE id = 'T0'")
        self.tap.add_record("T1", claude_record("S2", "autre session"))
        for _ in range(3):
            self.capture.scan_once()
        self.assertEqual(self.capture.tap_status["capability"], "ok")
        self.assertIn("autre session", self.bodies(pid))
        self.assertGreaterEqual(self.state()["malformed"].get("tap_invalid_utf8", 0), 1)
        self.assertEqual(self.state()["tap"]["cursors"]["T0"], 1)

    def test_tap_text_with_nul_and_surrogates_is_repaired_and_counted(self):
        pid = self.project(self.folder_a)
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        self.baseline()
        # SQLite stores no raw surrogate: it arrives as a JSON escape, like a client would send it.
        self.tap.add_record("T0", None, raw_text=json.dumps(claude_record("S1", "avec\x00NUL et MARQUE seul")).replace("MARQUE", chr(92) + "ud83d"))
        self.capture.scan_once()
        bodies = self.bodies(pid)
        self.assertEqual(len(bodies), 2, bodies)
        self.assertTrue(any(body.startswith("avec") and "\x00" not in body for body in bodies))
        self.assertGreaterEqual(self.state()["skipped"].get("invalid_text_repaired", 0), 1)
        self.assertEqual(self.state()["counters"].get("rejected"), None)

    def test_rejected_events_leave_a_notice(self):
        pid = self.project(self.folder_a)
        write_claude_transcript(self.claude_root, "S1", self.folder_a)
        self.baseline()
        self.tap.add_record("T0", claude_record("S1", "x"))
        original = self.store.import_events

        def refuse(project_id, events, source="import", **options):
            raise ValueError("title is invalid")
        with patch.object(self.store, "import_events", refuse):
            self.capture.scan_once()
        self.assertGreaterEqual(self.state()["counters"].get("rejected", 0), 1)
        self.assertIn("event_rejected", [notice["code"] for notice in self.state()["notices"]])


class BaselineTests(Synthetic):
    """First-scan baseline: only activity after the capture started is captured; an old transcript discovered
    later (restored, copied with its date, root changed) is history, a transcript born after the start is new."""

    def test_an_old_transcript_discovered_after_the_baseline_is_ignored_and_counted(self):
        pid = self.project(self.folder_a)
        self.baseline()
        old = write_claude_transcript(self.claude_root, "old", self.folder_a, lines=40)
        os.utime(old, (old.stat().st_atime - 7200, old.stat().st_mtime - 7200))
        self.capture.scan_once()
        self.assertEqual(self.bodies(pid), [])
        self.assertEqual(self.state()["skipped"].get("native_history_ignored"), 1)
        append_jsonl(old, self.native_row("old", self.folder_a, "nouvelle ligne", "u-new"))
        self.capture.scan_once()
        self.assertEqual(self.bodies(pid), ["nouvelle ligne"])

    def test_a_transcript_born_after_the_baseline_is_captured_from_its_first_line(self):
        pid = self.project(self.folder_a)
        self.baseline()
        write_claude_transcript(self.claude_root, "born", self.folder_a, lines=3)
        self.capture.scan_once()
        self.assertEqual(len(self.bodies(pid)), 3)
        self.assertEqual(self.state()["skipped"].get("native_history_ignored"), None)


class RedactionCounterTests(Synthetic):
    def test_the_redactions_counter_reports_what_the_store_masked(self):
        pid = self.project(self.folder_a)
        self.baseline()
        append_jsonl(write_claude_transcript(self.claude_root, "sr", self.folder_a, lines=0), self.native_row("sr", self.folder_a, "ma config : password=hunter2secret fin", "u1"))
        self.capture.scan_once()
        self.assertNotIn("hunter2secret", json.dumps(self.store.list_entries(pid)))
        self.assertGreaterEqual(self.state()["counters"].get("redactions", 0), 1)


class IntervalAndPathTests(Synthetic):
    def test_non_finite_or_tiny_intervals_are_replaced(self):
        for value in (float("nan"), float("inf"), float("-inf"), 1e400, 0, -5, None, "x"):
            interval = capture_module._safe_interval(value)
            self.assertTrue(math.isfinite(interval) and 0.5 <= interval <= 3600, value)
        self.assertEqual(capture_module._safe_interval(7), 7)

    @unittest.skipUnless(os.name == "nt", "extended-length paths exist on Windows only")
    def test_an_extended_length_cwd_is_resolved_like_the_plain_one(self):
        pid = self.project(self.folder_a)
        self.baseline()
        extended = "\\\\?\\" + str(self.folder_a)
        append_jsonl(write_claude_transcript(self.claude_root, "sx", self.folder_a, lines=0), self.native_row("sx", extended, "chemin étendu", "u1"))
        self.capture.scan_once()
        self.assertEqual(self.bodies(pid), ["chemin étendu"])
        self.assertEqual(len(self.store.list_projects()), 1)


if __name__ == "__main__":
    unittest.main()
