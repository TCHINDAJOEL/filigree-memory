# Correction: capture of tool-less conversations (Sonnet author + executor)

Date: 2026-10-16. Synthetic data only. No commit/push. Opus independent review still to come.

## Defect
`filigree/tap_source.py` `extract_turn` dropped every request with missing/empty `tools` as `side_request` (seen in `.runtime/live-journey/20261016T200705Z`: `tools: []`, `max_tokens: 128000`). A legitimate session without tools was never captured.

## Fix
New `is_side_request(body)`: only explicit evidence discards a request:
- `max_tokens == 1` (warm-up), kept;
- no tools AND a structured-output format (`output_config.format`, `text.format`, `response_format` of type `json*`), the shape of title/label side calls.
Missing or empty `tools` alone no longer discards anything. Project/session identity is untouched (same link logic); hidden reasoning, system and injected text are still skipped (asserted).
Limit: the structured-output signal comes from my knowledge of auxiliary calls, not from a real trace of one; a side call without it would now be captured.

## Tests (`tests/test_capture.py`, FilteringTests)
- `test_explicit_side_requests_are_not_captured` (replaces the old tools-less test, whose "titre automatique" case now carries the explicit structured-output evidence; adds max_tokens=1): 2 skipped.
- `test_conversations_without_tools_are_captured_with_exact_identity`: `tools: []` + absent tools, linked to the exact project, nothing in the other project, no pending, no hidden/system text.
- Fail-before: with the old rule temporarily restored the new capture test FAILED (`'question sans outil vide' not found in ''`); with the fix: `tests/test_capture.py` 81 passed.
- Full Python suite (`pytest tests`, e2e excluded, no wheel): 292 passed, 1 skipped, 45 subtests.
- Browser suite not run: source does not affect it.

## Live retake (Sonnet executor; isolation re-checked by reusing the already reviewed `verify_live_journey.py`, unchanged, with `--check-only` PASS first)
- `python scripts/verify_live_journey.py --check-only`: PASS, 0 calls (`.runtime/live-journey/20261016T203948Z`). Not live evidence.
- `python scripts/verify_live_journey.py` (default sonnet, writer `--tools ""` kept): `.runtime/live-journey/20261016T204000Z`, exit 1, 2 of 2 journey calls, both `claude-sonnet-5-5`.
  - Writer 5.0 s: OK. **Capture step now PASSES**: 1 proposal, project created for the right folder, no leak. This confirms the fix on a real tool-less session.
  - Real-browser review PASSED: proposal found, provenance visible, converted and accepted through the UI with a reason; handoff current (3 revisions).
  - Reader 8.7 s, 3 API calls, FAILED the helper assertion: only `list_projects` and `project_for_folder` were called, never `search_memory`/`get_handoff`. The reader answered `{"choice": null, "reason": null, "note_id": null}`. Permission denials: 0, no error.
- Diagnosis: `list_projects` returned the project, but with the WRITER's folder path; the reader prompt names a different fresh temp folder (`reader_folder`, `verify_live_journey.py:94,133`) that has no project, so `project_for_folder` found nothing and the model chose the prompt's "no answer → null" path instead of exploring the one listed project. Likely cause: helper design (reader folder not linked to the project) and/or model caution; not proven which. I did NOT change the helper or relax any assertion, and I made no retry.
- Not run (rule: only after a journey pass): old capture helper, `--native-direct`, handoff helper. Total live calls: 2 (Sonnet). Browser suite not rerun.
- Not verified live: fresh MCP reader giving decision/reason/id; reader non-mutation and leak scan after reading are unproven.
- Owner decision: either point the reader at the project's folder (a fresh session in that folder, which is also the realistic case) or accept a prompt hint to use `list_projects`; either needs a synthetic regression for the helper and a new authorization for calls (3 of the 5 budgeted remain).
