# Same-project fresh-reader live retake (Sonnet) — FINAL

Date: 2026-10-16. Synthetic data only. No commit/push. **No GO / no publish.** Opus independent review follows.

**Result: live journey FAILED (exit 1, helper assertion), 2 of 2 journey calls spent, no retry. Follow-up live checks (old capture/TAP, native-direct, handoff) NOT run, as required after a failure. There is NO live PASS.**

## Corrections
1. `scripts/verify_live_journey.py`: the reader is a fresh Claude session whose cwd and named folder are the writer's project folder (`reader_folder(paths)` = `paths["folder"]`; the separate reader temp folder is gone). Kept: separate reader TAP database, strict MCP with the four read tools only, hooks/settings disabled, no resume/continue flags, no answer or id in the prompt, all answer/reason/id/no-mutation/secret assertions, no accepted-memory seed. New: `check_same_project_scope` (canonical folder equal, prompt names that folder, databases differ; also run in `--check-only`) and `check_separate_sessions` (distinct native ids, distinct claude-tap sessions when announced).
2. `filigree/tap_source.py` `is_side_request`: JSON-schema/structured-output heuristic removed (it came from model memory, not a trace). Only the verified `max_tokens == 1` warm-up is skipped. An auxiliary call without a verified marker is captured as a project-linked **proposal** (never auto-accepted, rejectable in review). The ambiguity is accepted deliberately: some noise proposals are possible, silent loss of a user decision is not.
3. Found by the live run (helper bug, not a product bug): `judge_answer` rejected any choice containing "postgres", so the correct reply "SQLite (instead of Postgres)" failed. Fixed with `choice_is_sqlite`: SQLite must come first; Postgres may follow only after an explicit rejected-alternative marker (instead of / rather than / plutôt que / over / vs / not…). Regression written and **seen failing before the fix**, then passing.

## Tests (synthetic)
- `tests/test_capture.py`: `test_only_the_verified_one_token_warmup_is_a_side_request` (the old auto-title test no longer fabricates a marker); `test_structured_json_conversation_without_tools_is_captured` (3 JSON-format shapes, exact project, other project empty, hidden/system text absent, all `proposed`).
- `tests/test_live_journey_helper.py`: same-canonical-project/separate-database/no-resume test, distinct-sessions test, rejected-alternative test.
- Earlier own bug (prompt period in the new scope check) fixed in the check; nothing weakened.
- Targeted: 92 passed before the live run; helper file 11 passed after the judge fix.
- **Full Python after the privacy barrier**: `pytest tests --ignore=tests/e2e` → **300 passed, 1 skipped, 45 subtests**.
- `--check-only` PASS ×3 (last `.runtime/live-journey/20261016T211616Z`), 0 model calls. NOT live evidence.

## Barrier
Privacy builder: `claude-state.json` status `complete` (finished 21:10:06Z), `.aiwg/testing/privacy-retake.md` present. The live run started 21:13:32Z, after it. The privacy report itself states it did not re-run the full suite after its last edit; my full run above does cover that state.

## Live run `.runtime/live-journey/20261016T211332Z` (private evidence under `.runtime`)
- Models: writer `claude-sonnet-5-5`, reader `claude-sonnet-5-5`, TAP request model `claude-sonnet-5-5`.
- Sessions: writer native `e7521cb1-…`, TAP `2e6a75e9-…`; reader native `b17a79d6-…`, TAP `73427743-…` (distinct; reader cwd = writer project folder, `cwd_is_writer_project_folder: true`).
- Writer 5.3 s, tool-less: OK. Capture: 1 proposal, project auto-created for the right folder, marker present, **no leak**; chosen entry kind `observation`, tags capture/claude-tap/claude-code/reponse/lien-natif.
- Real Chromium review: proposal found, provenance card, tap origin, session id and folder visible, unauthenticated notice, converted to decision and accepted through the UI with reason (3 revisions, 3 history items); handoff current.
- Reader 7.2 s, 3 turns, 0 permission denials, **fixed scope worked**: unique tool calls `project_for_folder` ×1 and `search_memory` ×1; 1 content call returned the accepted note, 0 without it. This resolves the previous run's failure (reader never searched).
- Reader reply: choice "SQLite (instead of Postgres)", reason (single-user, offline, under 50 MB, operations cost), note_id `bead2774-…`.
- Helper assertion FAILED on the choice (defect 3 above). Not executed live because the run aborted there: reader non-mutation check, post-reader leak scan over persisted data/export/handoff, and the final browser scan.
- Offline diagnostic only (not a PASS): the recorded reply re-judged with the fixed judge → choice OK, 4/4 reason groups, note id present in the isolated memory. The note id equals the accepted entry only by this offline comparison, not by the helper's own assertion.

## Not done / honest defers
- No live PASS; a new authorization is needed for another journey. Budget: 5 total, 2 used, 3 remain (only the journey may use them first; old capture/TAP, native-direct, handoff remain unrun).
- Final wheel build and install: **deferred**, not run (time; live path did not pass anyway).
- Browser Playwright suite not re-run in this task (only the helper's own review/scan browser steps in `--check-only`).
- Scope of what the live run does show: a Claude Code writer and reader on this machine; no Codex; no human authentication is proven.
