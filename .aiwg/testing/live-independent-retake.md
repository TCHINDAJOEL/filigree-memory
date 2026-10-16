# Independent LIVE retake (Sonnet reviewer)

Date: 2026-10-16. Product frozen, nothing modified. Synthetic data only. No GO/commit/push. Private evidence: `.runtime/live-journey/20261016T200649Z` (check-only), `.runtime/live-journey/20261016T200705Z` (live).

## Isolation review (before any call)
`verify_live_journey.py` reviewed: separate work dir under `.runtime/live-journey/<stamp>`, new temp project folders (refuses Git folders), isolated TAP db via `CLOUDTAP_DB`, isolated native roots (only sessionId/cwd of the exact session transcript copied), server `--no-capture` with HOME/APPDATA/CLAUDE_CONFIG_DIR/CODEX_HOME redirected, reader on `--strict-mcp-config` with 4 read tools only, budget of 2 calls, no retry. Judged adequate.

## 1. `--check-only`: PASS
0 model calls. Isolation, baselines, MCP config, flags, prompts (reader prompt has no answer/ID), real Chromium review + scan on a synthetic fixture. This is NOT live evidence.

## 2. Live journey (default Sonnet): FAIL (exit 1, assertion), 1 model call
- Call 1/2 (writer): ok, 6.7 s, model reported `claude-sonnet-5-5`. Reader call NOT made (1 of 2 calls used, no retry).
- Failure at step 2 (capture): `aucun projet créé pour le dossier synthétique ; en attente : []`.
- Diagnosis (read-only on the synthetic work dir):
  - claude-tap DID record the exchange: 1 session, 1 record, and it claims the native id returned by Claude (`7fab9c72…`), so the session↔tap link is intact. Native metadata copy and cwd check passed.
  - Filigree scanned it and skipped it: `state.json` → `skipped: {side_request: 1}`, tap cursor advanced to 1, pending empty, no project, no proposal.
  - Cause: `filigree/tap_source.py:474` classifies a request as a side request when `max_tokens == 1 or not body.get("tools")`. The recorded request had `tools: []`, `max_tokens: 128000`, 2 messages. The journey's writer runs with `--tools ""` (by design), so its whole conversation is dropped as a side request.
  - So the failure is a mismatch between the product capture rule (tool-less requests are never captured) and the journey's writer configuration. It also reveals a real product limitation: a Claude session with no tool at all is not captured. Fixing either the helper (give the writer a tool, like the capture helper's `Read`) or the rule is out of my scope (frozen).
- Not verified (never reached): UI accept of a live proposal in real browser, fresh MCP reader answer, tool-call observation, reader non-mutation, leak scan on live data. Nothing about them may be claimed from the check-only run.
- The 3 older helpers were NOT run: the journey did not succeed (instruction: only on success). Total live model calls: 1 (Sonnet).

## 3. Browser suite
`node node_modules/@playwright/test/cli.js test`, run once and alone: **28 passed, 0 failed**, 1.6 min, 1 worker. No failure traces. Nothing else was running (no wheel/build/Python).

Screenshots viewed (fresh, `.runtime/remediation-ui/shots`): `layout-375-overview` (single column, no overflow, tabs scroll horizontally, selector/"+"/Git usable), `layout-768-capture` (sidebar + content, disabled-capture explanation, no overlap), `layout-1440-git` (Git modal over capture view, readable). The other six layout shots were produced by the passing D-4 tests (overlap/overflow assertions passed) but I did not view them.

## Summary / limits
- Browser: 28/28 pass on frozen source. Browser evidence only; not live evidence.
- Live: the real journey did NOT pass. Session→capture→proposal→UI accept→fresh MCP reader is unverified on a live model; leak, reader-answer and reader-no-mutation claims for live data are unproven.
- Older helpers (`verify_live_capture.py`, `--native-direct`, `verify_live_handoff.py`) not run. Remaining journey budget unused, no retry.
- Out of scope, not run: Python suite, benchmark, storage probes.
- Owner decision needed: give the journey writer one harmless tool (or decide tool-less sessions should be captured), then a fresh journey run needs new authorization for calls.
