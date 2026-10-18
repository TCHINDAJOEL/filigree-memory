# V2 (0.2.0) — live checks with a real model

Date: October 17, 2026, 17:47–17:50 UTC. Executed by: orchestrator (Opus), with the user's explicit authorization ("fais maintenant les tests réels et live"). Machine: Windows 10, Claude Code 2.1.302, claude-tap present. Source tested: commit `f2dce0b` plus the `verify_live_observer.py` script added here.

Each script makes **a single bounded call** to Claude Haiku (at most 300 s, no retry), in a synthetic folder, with an isolated Filigree memory under `.runtime/`. The private logs stay under `.runtime/` and are not committed.

| # | Command | What it proves | Result | Duration of the call |
| --- | --- | --- | --- | --- |
| 0 | `verify_live_capture.py --check-only` and `verify_live_handoff.py --check-only` | Isolation, baseline, synthetic memory, MCP configuration; no call | PASS | — |
| 1 | `python -X utf8 scripts/verify_live_capture.py` | Capture through claude-tap: tap session `393c881b` ↔ native session `b12f9369`; project created for the synthetic folder; 3 proposals, marker observed, exact provenance | **PASS** | 15.4 s |
| 2 | `python -X utf8 scripts/verify_live_capture.py --native-direct` | Direct launch of `claude` without claude-tap, native fallback: session `59962b0c`, 4 proposals, exact native provenance, rescans without duplicates | **PASS** | 6.8 s |
| 3 | `python -X utf8 scripts/verify_live_handoff.py` | A Haiku client retrieves the memory over **scoped MCP** (`--project-folder`) with `get_handoff` and `project_for_folder`, and distinguishes the current decision, the replaced decision and the open question with the 3 exact ids | **PASS** | 10.3 s |
| 4 | `python -X utf8 scripts/verify_live_observer.py` (new) | **V2 observer**: a real `filigree agent` (allowed root = the synthetic folder) journals a real Claude Code session `c4c24a0e`. 6 events: `user_prompt`, `tool_call`, `tool_result`, `file_change` on `notes.md` (actually modified by the model). No command line stored. One session sheet *proposed* after the `session_end` signal. `filigree status` consistent | **PASS** | 7.7 s |

Total: 4 model calls, as planned.

## Observations

- In test 4, the final assistant text was not yet journaled when the script stopped waiting: the script stops as soon as the prompt and the file change are visible. That is not a defect, but it is not proof that the final answer is captured either. The unit tests cover `assistant_text`.
- During test 4, the agent read the metadata of the user's Claude Code transcripts (its normal behavior, read-only). Only lines from the synthetic folder, which was the only allowed root, were journaled, and nothing earlier than the first cycle.

## Not covered

- Codex in real use: no live call. Codex is covered by synthetic fixtures only.
- Real installation of the hooks in the user's `~/.claude/settings.json`, and of the autostart: not done, because that would change the user's configuration.
- macOS and Linux in real use.
- Each result comes from one run on one machine and gives no guarantee for other versions.

## MCP scope without `--project-folder` (October 17, 2026, about 18:52 and 18:56 UTC)

The prise-en-main guide was going to state that `claude mcp add --scope user` is enough, because the server scopes itself to the project of the folder Claude works in. This was checked with `verify_live_handoff.py --cwd-scope`: the MCP configuration omits `--project-folder`, and Claude is launched from the project folder.

| Run | Source | Result |
| --- | --- | --- |
| 5 | Before the fix | **FAIL**. The client got 0 of 3 entries, and the server answered "outside this server's scope". When the same server is launched directly from the project folder, it does find the project. Conclusion: **Claude Code does not start MCP servers in the session folder.** The claim would have been false. |
| 6 | After the fix: the server asks the client for its MCP *roots* (`roots/list`) when no scope is explicit, and accepts only replies to requests it actually sent | **PASS** in 10.9 s. Haiku retrieves the memory without `--project-folder` and gives the 3 exact ids. |

That makes 6 model calls in total. Codex was not checked live for roots support: the guide says so and gives the `--project-folder` fallback.
