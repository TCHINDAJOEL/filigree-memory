"""Dry-run checks of scripts/verify_live_journey.py. No model call, no browser, no server: pure helper logic only."""
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import verify_live_journey as journey  # noqa: E402
from verify_live_capture import Failure  # noqa: E402

PATHS = {"nonce": "LANTERN-ABCD1234", "folder": Path("C:/synthetic/project"), "reader_db": Path("C:/synthetic/tap-reader.sqlite3"), "memory": Path("C:/synthetic/memory"), "db": Path("C:/synthetic/tap.sqlite3"), "mcp_config": Path("C:/synthetic/mcp.json")}


class JourneyHelperTests(unittest.TestCase):
    def test_unique_tool_calls_ignore_history_repeats(self):
        use = {"type": "tool_use", "id": "toolu_1", "name": "mcp__filigree__get_handoff", "input": {}}
        result = {"type": "tool_result", "tool_use_id": "toolu_1", "content": [{"type": "text", "text": "note-42"}]}
        request = lambda messages: {"request": {"body": {"model": "claude-x", "messages": messages}}}
        payloads = [request([{"role": "user", "content": "q"}]), request([{"role": "assistant", "content": [use]}, {"role": "user", "content": [result]}]),
                    request([{"role": "assistant", "content": [use]}, {"role": "user", "content": [result]}, {"role": "assistant", "content": "done"}])]
        summary = journey.summarize_payloads(payloads)
        self.assertEqual(list(summary["calls"]), ["toolu_1"])
        self.assertIn("note-42", summary["results"]["toolu_1"])
        self.assertEqual(summary["models"], ["claude-x"])

    def test_reader_answer_is_structured_and_judged_without_a_hint(self):
        answer = journey.parse_reader_answer('```json\n{"choice": "SQLite", "reason": "single-user, offline tool", "note_id": "n1"}\n```')
        journey.judge_answer(answer, "n1")
        for bad in ('{"choice": "Postgres", "reason": "single-user offline", "note_id": "n1"}', '{"choice": "SQLite", "reason": "it is nice", "note_id": "n1"}',
                    '{"choice": "SQLite", "reason": "single-user offline", "note_id": "other"}', '{"choice": null, "reason": null, "note_id": null}'):
            with self.assertRaises(Failure):
                journey.judge_answer(journey.parse_reader_answer(bad), "n1")
        for malformed in ("", "no json", '{"choice": 1}'):
            with self.assertRaises(Failure):
                journey.parse_reader_answer(malformed)

    def test_choice_may_name_postgres_only_as_the_rejected_alternative(self):
        # Real reader reply of the first same-project run: "SQLite (instead of Postgres)" is the correct choice.
        for good in ("SQLite (instead of Postgres)", "SQLite rather than Postgres", "SQLite, not Postgres", "sqlite over postgres", "SQLite"):
            journey.judge_answer({"choice": good, "reason": "single-user offline tool", "note_id": "n1"}, "n1")
        for bad in ("Postgres", "Postgres instead of SQLite", "SQLite and Postgres", "Postgres (rather than SQLite)", "SQLite, Postgres", None, ""):
            with self.assertRaises(Failure):
                journey.judge_answer({"choice": bad, "reason": "single-user offline tool", "note_id": "n1"}, "n1")

    def test_leak_scan_reports_labels_and_counts_only(self):
        fakes = journey.fake_secrets()
        needles = journey.needles_of(fakes)
        self.assertEqual(journey.scan_text_for(needles, "rien ici [secret masqué]"), {})
        leaked = journey.scan_text_for(needles, "x " + fakes["url_credentials"][1][0] + " y")
        self.assertEqual(leaked, {"url_credentials": 1})
        self.assertEqual(len({needle for items in needles.values() for needle in items}), sum(len(items) for items in needles.values()))

    def test_prompts_carry_no_answer_and_no_shell_metacharacters(self):
        fakes = journey.fake_secrets()
        reader = journey.reader_prompt(journey.reader_folder(PATHS))
        self.assertEqual(journey.prompt_leaks(reader, ["sqlite", "postgres", "single-user", "offline", PATHS["nonce"]]), [])
        self.assertIn(journey.QUESTION, reader)
        writer = journey.writer_prompt(PATHS, fakes)
        for line, _needles in fakes.values():
            self.assertIn(line, writer)
        for prompt in (reader, writer):
            self.assertIsNone(journey._SHELL_META.search(prompt))

    def test_command_flags_isolate_both_clients(self):
        writer = journey.writer_arguments("p", "sonnet")
        reader = journey.reader_arguments("p", "sonnet", PATHS["mcp_config"])
        self.assertEqual(writer[writer.index("--tools") + 1], "")
        self.assertNotIn("--mcp-config", writer)
        self.assertNotIn("--allowedTools", writer)
        for command in (writer, reader):
            self.assertIn("--strict-mcp-config", command)
            self.assertNotIn("--safe-mode", command)
            self.assertEqual(command[command.index("--setting-sources") + 1], "")
        start = reader.index("--allowedTools") + 1
        self.assertEqual(reader[start:start + len(journey.ALLOWED)], journey.ALLOWED)
        self.assertNotIn("mcp__filigree__propose_memory", reader)
        self.assertEqual(reader[reader.index("--mcp-config") + 1], str(PATHS["mcp_config"]))

    def test_children_lose_only_the_two_nested_session_markers(self):
        with mock.patch.dict("os.environ", {"CLAUDECODE": "1", "CLAUDE_CODE_SAFE_MODE": "1", "KEEP_ME": "yes"}):
            env, removed = journey.child_environment(PATHS["db"])
        self.assertEqual(sorted(removed), ["CLAUDECODE", "CLAUDE_CODE_SAFE_MODE"])
        self.assertEqual(env["KEEP_ME"], "yes")
        self.assertEqual(env["CLOUDTAP_DB"], str(PATHS["db"]))

    def test_model_calls_are_refused_in_check_only_and_beyond_budget(self):
        with mock.patch.object(journey.subprocess, "Popen") as popen:
            with mock.patch.dict(journey.STATE, {"allow_model": False, "calls": 0}):
                with self.assertRaises(Failure):
                    journey.claude_call({}, "x", [], PATHS["db"], Path("."))
            with mock.patch.dict(journey.STATE, {"allow_model": True, "calls": journey.MAX_CALLS}):
                with self.assertRaises(Failure):
                    journey.claude_call({}, "x", [], PATHS["db"], Path("."))
            popen.assert_not_called()

    def test_reader_is_a_fresh_session_of_the_same_canonical_project_folder(self):
        folder = journey.reader_folder(PATHS)
        self.assertEqual(journey.canonical(folder), journey.canonical(PATHS["folder"]))
        prompt = journey.reader_prompt(folder)
        journey.check_same_project_scope(PATHS, prompt, folder)
        # a different folder (the previous defect), an alias spelling of the same one, a prompt naming another folder, a shared database
        with self.assertRaises(Failure):
            journey.check_same_project_scope(PATHS, prompt, Path("C:/synthetic/other-reader"))
        journey.check_same_project_scope(PATHS, prompt, Path("C:/synthetic/project/../project"))
        with self.assertRaises(Failure):
            journey.check_same_project_scope(PATHS, journey.reader_prompt(Path("C:/synthetic/other-reader")), folder)
        with self.assertRaises(Failure):
            journey.check_same_project_scope({**PATHS, "reader_db": PATHS["db"]}, prompt, folder)
        self.assertNotIn("reader_folder", PATHS)
        # reader command: clean client, readonly strict MCP, hooks and settings disabled, no inherited conversation, no answer in the prompt
        command = journey.reader_arguments(prompt, "sonnet", PATHS["mcp_config"])
        for flag in ("--strict-mcp-config", "--disable-slash-commands"):
            self.assertIn(flag, command)
        self.assertEqual(command[command.index("--settings") + 1], '{"disableAllHooks":true}')
        for inherited in ("--continue", "--resume", "-c", "-r", "--session-id", "--fork-session"):
            self.assertNotIn(inherited, command)
        self.assertEqual(journey.prompt_leaks(prompt, ["sqlite", "postgres", PATHS["nonce"]]), [])

    def test_writer_and_reader_must_be_distinct_sessions(self):
        writer = {"native_id": "native-writer-1", "banner_tap_session": "tap-writer-1"}
        journey.check_separate_sessions(writer, {"native_id": "native-reader-1", "banner_tap_session": "tap-reader-1"})
        journey.check_separate_sessions(writer, {"native_id": "native-reader-1", "banner_tap_session": None})
        for reader in ({"native_id": "native-writer-1", "banner_tap_session": "tap-reader-1"}, {"native_id": "native-reader-1", "banner_tap_session": "tap-writer-1"}, {"native_id": None}):
            with self.assertRaises(Failure):
                journey.check_separate_sessions(writer, reader)

    def test_reason_must_cover_two_parts(self):
        self.assertEqual(journey.reason_groups_covered("Offline, single user"), 2)
        self.assertEqual(journey.reason_groups_covered("because"), 0)


if __name__ == "__main__":
    unittest.main()
