# Opus risk findings — fixes (Sonnet)

Date: 2026-10-16. Synthetic data only; no live client call; no authentication system, no semantic dependency added. No GO, commit or push.
Base: `remediation-opus-risk.md` R1–R9 re-checked on the current source before editing.

## Executed commands (final code)

| Command | Result |
|---|---|
| `python -m unittest discover -s tests -p test_remediation_opus.py` (before fixes) | 31 tests, ~20 failures/errors (R1, R2, R3, R4, R5, R7, R8, R9, R6) — the regressions fail on the reviewed code |
| same, after fixes | `Ran 35 tests`, OK (11 s) |
| `python -m pytest tests/test_remediation_opus.py -q -p no:cacheprovider` | 35 passed — same count as unittest discovery |
| `python -m unittest discover -s tests` | run 1: 287 tests, 1 failure (`test_minimum_handoff_budget_bounds_long_project_objective`, handoff preamble longer by 13 chars → fixed, objective limit now budget-aware); `test_store.py` re-run OK (27). Final run: 287 tests, `skipped=1`, **1 error, intermittent**: `test_unsupported_methods_get_a_json_405_with_security_headers` (`ConnectionAbortedError WinError 10053`, PUT/DELETE/HEAD with an unread body on Windows). Passed in the previous full run and alone (OK). Not touched by this work (`Handler.refuse` unchanged); not fixed. |
| `node node_modules/@playwright/test/cli.js test` | **25 passed**, 0 failed, 2.0 min (24 previous + new delayed-bootstrap regression) |
| `node --check playwright.config.cjs`, `node --check tests/browser/workbench.spec.cjs` | exit 0 |

Caveat: the final full unittest run is 286/287 green + 1 intermittent Windows socket error; I did not get a clean 287 in a single run after the last code change (the only code change after the clean-ish run was the objective limit, covered by `test_store.py` OK and the failing-then-passing test).

## Disposition per ID

| ID | Disposition | What changed | Tests |
|---|---|---|---|
| R1 | **Fixed** | `mcp.search_memory` returns `store.search()`: `{entries, matched, total, by_status, note}`; tool description and `initialize` instructions say empty ≠ no memory | `McpSearchTests` (2) |
| R2 | **Fixed** | `store.redact_whole` / `PreRedacted`: TAP events, native fallback events, and the importers (`add`, `body` records, `parse_text`) redact the full text before the 180/140/100/160 title and 4000 excerpt cuts. The redaction count survives through a `pre_redactions` field honoured **only** for `PreRedacted` objects (a client JSON cannot be one). Body-limit cut already redacted first (now tested) | `RedactBeforeTruncationTests` (5), `NativeBoundaryTests` (native transcript end to end). Checks current, history, events, export, handoff files for the token head. UI/HTTP views read those same files; not separately asserted |
| R3 | **Fixed (detection)** | `list_history` requires revisions = {1..current}, no revision above current, and newest snapshot == current entry. Clear French errors (missing revisions listed; “modifiée hors de Filigree… rien n'a été écrasé”). Healthy entries and other histories stay usable. Nothing is rewritten | `HistoryIntegrityTests` (4). Not done: the project-level `diagnostics` list does not include history problems (cost on every `get_project`); they surface when the history is opened |
| R4 | **Disposition applied** | No authentication added. Handoff preamble now says accepted = through the local review interface, person not authenticated. Server-set `channel` (`http-ui`/`mcp`/`import`/`capture`/`local`) stored on entries and on every change event; legacy entries without it still load; handoff shows `Origin: channel (declared by: label)`. Clients cannot set it: HTTP/store refuse the field (400), MCP schema refuses it, import events' `channel` key is ignored. MCP stays proposal-only; the human-name list is documented as a usability guard. README section added | `ChannelAndClaimsTests` (7), `HttpChannelTests` (1). **Not done**: C5 (force all HTTP creation to `proposed`) — not evaluated against the UI; `agent` is still PATCH-editable; UI text still shows `agent` without a “déclaré par” label (only the handoff does); `SECURITY.md`/`AGENTS.md` not edited |
| R5 | **Fixed** | `DisabledCapture(store)` probes only `<memory>/.capture/capture.lock` (never creates `.capture`), reports `external_monitor_running` and `running`, and `stop` writes the cooperative `stop` file and waits up to 0.5 s. All other controls still 409. No TAP/native/settings access | `ExternalMonitorTests` (3): real subprocess holding the lock, tripwires on `Capture.__init__`, `scan_once`, `tap_source.probe/resolve_db_path`, `native_index.*` record 0 calls. **Not done**: the UI still shows “Capture désactivée” without mentioning an external monitor |
| R6 | **Partly fixed, limits documented** | Multi-word YAML/env value (`password: my secret phrase`) masked to end of line (line-start keys only); Git checkpoint message redacted. URL password containing a raw `/` left as is (malformed per RFC 3986) and asserted as a documented limit. README lists exact limits, claims no DLP | `HeuristicGapTests` (4) incl. real `git` commit log |
| R7 | **Fixed** | Cache entries keep a content digest. Unsettled hits (mtime < 2 s old at load) are checked by content every time; settled hits are re-confirmed at most every `Store.CACHE_REVALIDATE_SECONDS` (5 s). Digest is taken before parsing (a race is caught on the next revalidation) | `CacheRevalidationTests` (3), incl. no re-parse within the interval. Not measured on 3000 entries (cost: one extra file read per file per 5 s) |
| R8 | **Fixed (messages + path proven)** | Errors rewritten in French: rejecting an accepted replacement and reactivating a superseded entry now name the recovery (new accepted entry that `supersedes` the current one); the misleading “Only an accepted entry may supersede” remains only for the real case. Recovery path proven: history of both earlier entries intact, no resurrection | `SupersessionRecoveryTests` (3). Decision not taken: editing the text of a superseded entry is still allowed |
| R9 | **Fixed** | `store.event_diagnostics()`; handoff warns “N unreadable event file(s)” and returns `event_diagnostics`; `list_history` on a quarantined entry gives the quarantine message instead of 404 | `OmittedFilesAreReportedTests`, `HistoryIntegrityTests` |
| R10 | Not in scope | Unchanged | — |

Other: `INT-2` deterministic regression added (`workbench.spec.cjs`, bootstrap route held 1.5 s, expects one `POST 201` and the new project selected while another project exists). It was not run against the pre-fix `app.js`, so I did not prove it fails there. `playwright.config.cjs` now creates `.runtime/browser-runs/<timestamp>-<pid>/{memory,projects,sources,absent-tap}` per run; nothing is deleted (old `.runtime/browser-memory` remains, unused). The explicit multi-project test creates a pre-existing project first.

## Files touched
`filigree/store.py`, `capture.py`, `importers.py`, `mcp.py`, `server.py`, `git_sync.py`, `README.md`, `playwright.config.cjs`, `tests/browser/workbench.spec.cjs`, new `tests/test_remediation_opus.py`.

## Remaining work
1. Intermittent `WinError 10053` in the 405 HTTP test (pre-existing; `refuse` does not drain the body).
2. UI: external-monitor notice in the disabled-capture banner; “déclaré par” label for `agent`; surface history/event diagnostics in the UI.
3. Decide C5 and whether `agent` stays PATCH-editable; update `SECURITY.md`/`AGENTS.md` wording.
4. Prove the INT-2 test fails on the pre-fix `app.js`; run a 3000-entry timing with the digest revalidation.
5. Separate Sonnet live E2E and Opus final review still required.
