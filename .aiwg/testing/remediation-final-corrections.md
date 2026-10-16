# Final integration corrections (Sonnet)

Date: 2026-10-16. Synthetic data only. No live call, benchmark or `--check-only` was run. `personaltranscripts`, TAP and `agentC/data` were not read. No GO, commit or push. `AGENTS.md` and user agent configs untouched.
Inputs: `.runtime/remediation-independent-final-result.txt` (result field), `remediation-opus-fixes.md`, current source, `test-results/` trace of the D-7 failure.

## Executed commands (final source)

| Command | Result |
|---|---|
| `python -m unittest discover -s tests` | **292 tests, OK, skipped=1** (287 before + 5 new), 110 s |
| `python -m unittest discover -s tests -p test_remediation_final.py` | 5 tests OK |
| `node node_modules/@playwright/test/cli.js test` (run alone, nothing else running) | **28 passed**, 0 failed, 1.6 min (25 before + 3 new). An earlier run of the 25 tests after the server fix only: 25 passed, 1.6 min |
| `node --check` on `app.js`, `playwright.config.cjs`, the three `*.spec.cjs` | exit 0 |
| `python -m pip wheel . --no-deps --wheel-dir .runtime/wheels`, then `python scripts/verify_package.py` | PASS (wheel built after the last source change) |

Not run: live scripts, 3000-entry benchmark, redaction/alias/large-input probes (tester did not run them either; still open).

## 1. Browser flakiness (priority) — product defect, not harness

Diagnosis: the D-7 trace shows the last request, `GET /api/projects` after the project `<select>` change, ending with status -1 (connection failure). The server log was clean. `refresh()` then reverts `state.target`, so `#project-name` kept the old project. The same cause explains `newEntry` "Failed to fetch" at 375px and the unclickable `#new-project` in the workbench test.

Root cause: `ThreadingHTTPServer` listens with the default backlog of 5. A page load plus polling opens several connections at once and Windows resets some of them.
Reproduced deterministically (before the fix): 64 simultaneous clients × 5 requests → 33 `ConnectionResetError 10054`.

Fix: `LocalServer.request_queue_size = 128` (`filigree/server.py`).
Regression: `ConnectionBurstTests.test_a_burst_of_simultaneous_connections_is_all_served` (fails before, passes after). I did not see D-4/D-7 fail again after the fix across 3 full runs, but the original flake was intermittent, so a clean run is evidence, not proof.

## 2. HTTP 405 / WinError 10053 with an unread body

Layer: `Handler` (`filigree/server.py`).
- Defect found and reproduced: `HEAD` 405 wrote a JSON body (invalid HTTP). Fixed, `send` writes no body for HEAD.
- Unread body: the server answered and closed with request data still unread, which Windows turns into a reset that can destroy the answer. After the response, `handle_one_request` now sets `close_connection`, shuts down the write side, then drains at most `DRAIN_BYTES` (1 MiB) for at most `DRAIN_SECONDS` (2 s). No sleeps, no unbounded drain. Applies to every response sent without reading a declared body (405, 403 Host/Origin/token, 400 length/type).
- The 10053 itself did not reproduce in 4 × 7 body shapes × 6 attempts on this machine, so the drain is a bounded hardening of the identified mechanism, not a proven fix of that exact flake. The existing test passed in the 292-test run.
- Tests (`UnreadBodyTests`, raw sockets): PUT, DELETE, OPTIONS, HEAD × small / 600 kB / declared-not-sent / missing / malformed / negative length / chunked, 6 repeats each, each answered with 405 + security headers within 4 s; 403 (bad Host, missing token, wrong token) and 400 (oversized length) delivered with a 300 kB unread body; a silent client declaring 50 MB is released by the server within 5 s. Host/Origin/token/security headers unchanged.

## 3. Disabled-capture UI with an external monitor

`app.js`: for `disabled_by_server` and `external_monitor_running` the banner says "Capture désactivée pour ce serveur — un moniteur externe tourne sur cette mémoire", the pill says "Moniteur externe actif", and exactly one control is offered, "Arrêter le moniteur externe" (cooperative stop file, existing server action). Start, enable, disable, suspend remain absent.
Browser test (`final.spec.cjs`): a real Python process holds `.capture/capture.lock`; the server runs with tripwires on `Capture.__init__`, `scan_once`, tap `probe`/`resolve_db_path`, `native_index.default_roots`/`NativeIndex`, which would write a trap file. Asserts: banner, pill, one button, only `{action:'stop'}` posted, the monitor exits with code 0 (nobody killed it), banner clears, trap file never created.

## 4. Declared labels and diagnostics

- Rows show "↳ Déclaré : <agent>" (title "Nom déclaré, non authentifié"); detail shows "Déclaré par <agent> (non authentifié)" and "Canal : <canal>" (server-set); timeline shows "canal : …" and "déclaré par" if an event carries an agent; form label "Auteur ou agent (déclaré, non authentifié)". Hostile name `Dr. Martin <b>…</b>` is escaped (test: no `<b>` element).
- New `GET /api/projects/<id>/diagnostics` → `{entries, events}` (file name and reason only, no paths). A `role="alert"` banner (`#diagnostics`) lists quarantined entries/events, says nothing was modified, refreshed on project load and on each live tick. Empty for a healthy memory.
- History corruption is surfaced where it is opened: `loadHistory` already shows the backend error in a `role="alert"` block (unchanged).
- Browser tests: corrupt entry file and corrupt event file → "2 fichiers de mémoire illisibles", both names listed, the corrupt event file content unchanged; clean memory → empty.

## 5. Trust boundary and corrections

`SECURITY.md` has a new "Trust boundary" and "Corrections and recovery" part: the HTTP token/UI is not human authentication; deliberate accepted creation through the local UI remains allowed (C5 kept, not redesigned); MCP/import/capture only propose; `channel` is server-set and client values are refused or ignored; actor names are declared labels. `README.md` gets a matching line. Superseded title/body corrections stay allowed because they are append-only revisions; no status resurrection; recovery = new accepted entry that supersedes. Test `CorrectionTrailTests`: editing the title and `agent` of a superseded entry adds revision N+1, keeps revisions 1..N readable with the old title and agent, adds a change event with channel `http-ui`, and re-accepting is refused.

## Files

Product: `filigree/server.py`, `filigree/static/app.js`, `index.html`, `styles.css`. Docs: `SECURITY.md`, `README.md`. Tests: new `tests/test_remediation_final.py` (5), new `tests/browser/final.spec.cjs` (3).

## Residuals

- The new UI tests were written after the UI code; I did not run them against the old `app.js`. The burst test was run against the old server and fails there.
- The WinError 10053 flake is not reproduced on this machine; mitigation only.
- Not done: independent live/benchmark retake, 3000-entry timing with revalidation, redaction/alias/large-input probes, proof that INT-2 fails on the pre-fix `app.js`.
- `agent` is still PATCH-editable (documented, leaves revision and event).
- Old `.runtime/browser-memory`, `test-results/` and earlier `.runtime/*` runs were not deleted.
- Diagnostics are fetched in an extra request per live tick (every 6 s).
- Independent re-test and Opus final review still required. No GO.
