# Independent review of the V2 code and how each finding was handled

Date: October 17, 2026. Reviewer: independent agent (Opus) with no access to the authoring. Diff reviewed: `5cb450b..26a9b97`, `filigree/`, `scripts/` and `tests/`. Contract: [ADR-0003](../architecture/ADR-0003-permanent-observer.md). The reviewer changed no files and ran the suite: 360 OK.

## Findings and fixes

| # | Severity | Finding | Fix | Regression test (`tests/test_v2_review_fixes.py`) |
| --- | --- | --- | --- | --- |
| 1 | Blocking | `extract._result` cut the test output (last 200 characters) **before** redacting it, which could leak a PEM key or `password=` | Redact the whole output, then take the tail | `test_test_output_is_redacted_before_its_tail_is_kept` |
| 2 | Blocking | Exclusions were checked only on the project folder, not on the session folder | Check both folders, plus `store.root` | `test_session_in_an_excluded_subfolder_of_a_project_is_not_journaled` |
| 3 | Major | D11 broken: lines copied by a resume or fork were journaled again, and old files outside the first baseline were read from the start | Lines dated before `baseline_at` are skipped; `event_id` = client + source element (no longer the session) | `test_forked_transcript_lines_are_one_event_and_old_history_is_skipped` |
| 4 | Major | One failing project or file blocked the whole cycle, and the cursors were never saved | Errors isolated per file and per project; state saved after ingestion; `errors` counter | `test_one_failing_project_neither_stalls_the_cursor_nor_the_others` |
| 5 | Major | After the state was lost, an accepted "suite" could be rewritten | The suite number advances as long as the existing sheet has been reviewed | `test_lost_state_never_rewrites_an_accepted_suite` |
| 6 | Major | Windows hook command broken under Git Bash (unquoted backslashes) | Every argument quoted, forward slashes; detection of our own hooks is insensitive to quoting | `test_command_runs_in_the_native_shell`, `test_command_runs_in_git_bash_on_windows` (**the generated command is actually executed**, through cmd and through Git Bash) |
| 7 | Minor | Race when creating `agent.key` (partial read) | Private file, then `os.link` (no overwrite); fallback with exclusive creation; short retried read | `test_concurrent_key_creation_yields_one_complete_key` (12 threads) |
| 8 | Minor | A worktree could escape `allowed_roots` through its main repository | The main repository must be under the roots (observer and capture) | `test_worktree_whose_repository_is_outside_the_roots_is_not_mapped` |
| 9 | Minor | Wrong label for a program given by a quoted or Windows path | `shlex` (non-POSIX), then a Windows or POSIX path name | `test_program_name_of_quoted_and_windows_paths` |
| 10 | Minor | Event index unstable after a restart | `part` = position of the block in the line | `test_event_part_is_the_block_position` |
| 11 | Minor | launchd restart loop when an agent is already running | `KeepAlive.SuccessfulExit=false`; the CLI exits with code 0 on `AgentRunning` | `test_launchd_restarts_only_on_failure_and_systemd_escapes_specifiers`, `test_already_running_agent_is_a_clean_exit` |
| 12 | Minor | `%` and `$` not escaped in systemd `ExecStart` | `%%` and `$$` | same test |

## Areas the reviewer found sound

MCP scope (all tools), hooks (invalid settings and a foreign Codex `notify` are left untouched, backup, bounded stdin, `signal` → 0), `running_agent` (the key proves the data folder), zip limits and cycle detection for ChatGPT.

## Verification after the fixes (executed)

| Command | Result |
| --- | --- |
| `python -m unittest discover -s tests` | **373 OK**, 1 skipped |
| `npm test` | **29 passed** |
| wheel + `scripts/verify_package.py` | PASS (0.2.0) |
| `scripts/verify_agent_e2e.py` | PASS. The script's synthetic rows are now dated after the baseline: with the D11 fix, a line dated before the observer's first run is ignored, which is the expected behavior. |

## Remaining

- Real installation of the Claude hook not tested with Claude Code. The generated command is executed through cmd and through Git Bash, but the shell Claude Code actually uses on Windows has not been observed.
- A second review of these fixes has not been done.
