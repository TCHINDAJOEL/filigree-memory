# Remediation integration (Sonnet) — PARTIAL CHECKPOINT

Status: **partial**. Not a delivery declaration. Opus/root review and a separate bounded live-validation task follow.
Per the root override I ran no process-list/runner checks; builder completion was taken from the root's statement.

## Final executed state (all on the final code)

| Command | Result |
|---|---|
| `python -m unittest discover -s tests -v` (first action) | OK |
| `python -m unittest discover -s tests` (final, after all edits) | `Ran 244 tests`, `OK (skipped=1)`, 109 s (earlier runs: 97 s, 95 s) |
| `node --check filigree/static/app.js` | exit 0 |
| `node node_modules/@playwright/test/cli.js test` (final) | **24 passed**, 0 failed, 2.3 min (16 remediation + D12 + 7 workbench) |
| `python -m pip wheel . --no-deps --wheel-dir .runtime/wheels` | built after the last edit |
| `python scripts/verify_package.py` | PASS: isolated wheel install, CLI version, packaged HTML/JS, local bootstrap (an earlier attempt correctly refused a stale wheel) |

Not run: `npm ci`, `npx playwright install chromium` (existing `node_modules`/Chromium used). A hand-made venv + `pip install` was denied by the permission mode and not worked around; `verify_package.py` covers the isolated install.

## Failures found and fixes

| ID | Finding | Fix | Test |
|---|---|---|---|
| INT-1 | `workbench.spec` "human review…" replaced a PROPOSED hypothesis, forbidden since A8 | Accept the original first (detail → Accepter → Confirmer l’acceptation), then replace; alternative/history/graph/handoff assertions kept | workbench.spec.cjs:17 |
| INT-2 | **Product bug** behind an intermittent failure of that test: on a fresh page, a write sent before the `/api/bootstrap` answer carried an empty token → `POST /api/projects` returned **403**, the project was never created and the UI silently showed another project (confirmed by logging the network sequence: `POST 403`, then selection of the newest existing project) | `api()` now awaits the pending bootstrap before any non-GET (`filigree/static/app.js`). Network trace after the fix: `POST 201`, new project shown | workbench.spec.cjs:17 (it clicks immediately after `goto`); passed in the final full run |
| INT-3 | Defensive: an explicit `refresh(id)` could be overridden by a concurrent background refresh | `refresh()` records `state.target` before its first await. Not independently proven to be a real bug; INT-2 was the actual cause | none specific |
| D12 | UI ignored `disabled_by_server` from services: every capture control errored on click | Banner "Capture désactivée", controls replaced by an explanation naming `--no-capture`, no capture buttons | new `remediation.spec.cjs` "D12…" (real `--no-capture` server, no mock) — proves services + UI integration |

INT-2 caveat: the browser suite passed in full once after the fix (and the deterministic network trace shows 201), which is evidence, not proof, that no other timing race remains.

## Not done (no PASS claimed)

- **Live calls: 0 of 6 used.** `verify_live_capture.py` (TAP), `--native-direct`, `verify_live_handoff.py`, `scripts/verify_live_journey.py` (not created) and the E1/E2 end-to-end are all still to run in the separate live task. The model used by the preexisting helpers was not re-verified (README states `haiku`).
- Not executed: exploratory browser checks/screenshots, 3000-entry benchmark, extra synthetic Windows (TOML/UTF-8/exclusive port) and cross-process cache checks beyond the builders' own tests.
- Not done: ID→test mapping against `remediation-acceptance.md`; I did not read it or the five builder reports. Decisions on MCP claimed-agent attribution, superseded-edit rules and the C5 token threat model were not reviewed beyond "full suite green" (this includes the existing strict history test, which passes).
- Test hygiene: `.runtime/browser-memory` persists across Playwright runs (~67 projects accumulated), so browser tests are not hermetic; use a fresh data dir per run in `playwright.config.cjs`.
- README was not updated (no live outcomes yet to describe truthfully).
