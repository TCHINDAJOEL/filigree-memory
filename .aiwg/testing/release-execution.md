# Release execution (Sonnet) — final results

Date: 2026-10-16. Synthetic data only. No commit/push, no product change (source, helper and tests frozen). No GO/publish decision: root reviews against the Opus conditional gate.

## README (docs only)
- B2: capture line now says only the verified `max_tokens == 1` warm-up is skipped; other auxiliary/tool-less requests may become identity-filtered proposals (never auto-accepted).
- S1: redaction limits rewritten to the current bounds and best-effort wording (raw `/` in a URL password now masked; remaining limits listed).
- S2: performance limits stated (3000-entry import ~65 s; 1586 `create_entry` in 180 s; cold handoff ~2.8 s; one unexplained 14 s outlier, no cause claimed; no SLA).
- Synthetic live transcripts also reside in the normal Claude config (exact session lookup).
- Intro live claim re-qualified as historical (older build) and pointing here. Codex: synthetic only.

## Live journey — `python -X utf8 scripts/verify_live_journey.py` (current helper, unchanged)
- Result: **PASS (live)**, exit 0. Folder: `.runtime/live-journey/20261016T213653Z`.
- Claude calls: 2 (writer + reader), both model `claude-sonnet-5-5` (announced and seen by TAP). Writer 5.3 s, reader 8.7 s, total 24.0 s.
- 1 proposal captured for the right project folder, no leak; real-browser accept with reason; handoff current.
- Reader: unique MCP calls `project_for_folder` ×1, `search_memory` ×1; 1 content result with the note; exact note id; memory unchanged (reader immutability reached); persisted and browser fake-secret scans reached, 0 leak.
- Scope: Claude Code writer/reader on this machine; no Codex; no human authentication proven.
- Session ids are in the private `debug.json` (not copied here).

## Follow-up live helpers (one call each, no retry; 4 scripts of the 5 allowed)
All three PASS on the current tree, model `haiku` (these old helpers request haiku; the journey used `claude-sonnet-5-5`).
- `verify_live_capture.py` (claude-tap): PASS, 1 Claude call, 4.9 s; tap `5d9e3af1` ↔ native `0714423f`; 3 proposals, marker observed, exact provenance. Folder `.runtime/live-capture/20261016T213724Z`.
- `verify_live_capture.py --native-direct`: PASS, 1 call, 3.9 s; direct launch without claude-tap, native session `400a55e7`; 4 proposals, exact native provenance, rescans without duplicate. Folder `.runtime/live-capture/20261016T213732Z`.
- `verify_live_handoff.py`: PASS, 1 call, 11.3 s; the client retrieved the memory through MCP (`get_handoff`, `project_for_folder`) and gave the 3 exact ids (current, replaced, open question). Folder `.runtime/live-handoff/20261016T213800Z`.
- Total Claude calls this assignment: 2 (journey) + 1 + 1 + 1 = 5. Each is scoped to one client on this machine; no Codex.

## Test, package and freshness results (run sequentially, one at a time)
- `python -X utf8 -m unittest discover -s tests -v`: **Ran 301 tests, OK (skipped=1)**, 97 s. The one skip is `test_runner...test_kill_tree_signals_only_launched_group_on_posix` ("POSIX process groups", expected on Windows); its Windows counterpart `test_kill_tree_targets_only_launched_pid_on_windows` ran.
- JS syntax: `node --check filigree/static/app.js` exit 0.
- Playwright (`node node_modules/@playwright/test/cli.js test`, alone): **28 passed**, 0 failed, 0 skipped, 1.7 min.
- Wheel: `python -m pip wheel . --no-deps --wheel-dir .runtime/wheels` OK → `filigree_memory-0.1.0-py3-none-any.whl`, 116542 bytes, sha256 `756f8860…c6`. `python scripts/verify_package.py`: **PASS** (isolated install, CLI version, packaged HTML/JS, local bootstrap).
- Freshness: no file under `filigree/`, `scripts/`, `tests/` or `pyproject.toml` is newer than the wheel (checked with `find -newer`), so unit tests, live runs, Playwright and wheel cover the same frozen source. No source, helper or test change in this pass.

## Windows services / alias coverage (by actual test names)
- Alias: `test_remediation_store.py::test_extended_length_alias_is_the_same_folder`; helper alias case in `test_live_journey_helper.py` (same-project scope check). Both ran and passed. 8.3 short-name, junction and UNC spellings: no dedicated test found.
- Process handling: `test_runner.py::test_kill_tree_targets_only_launched_pid_on_windows` passed.
- Service tests: `test_remediation_services.py` (oversized line, generated config launching the module) passed.
- `scripts/install-capture-startup.ps1` / `uninstall-capture-startup.ps1` (optional Windows login shortcut): no test found in `tests/` that executes them; they were not run in this pass. The browser test only checks that startup controls stay unavailable. This stays a documented untested area.

## Notes for root
- Synthetic live transcripts of the journey also live in the normal Claude config (exact session lookup); I did not inspect other transcripts, TAP/native databases or `agentC/data`.
- Untouched, optional: S3 (permissive `choice_is_sqlite`), the untested Windows login-shortcut scripts, no commit hash (tree untracked).
- No GO/publish decision is made here.
