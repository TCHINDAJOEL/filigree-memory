# Independent storage probes, performance, Python verification (retake)

Date: 2026-10-16. Executor: Sonnet (independent). Synthetic data only. No source/test/config change, no live call, no browser, no GO/commit/push. `personaltranscripts`, real TAP/native DBs and `agentC/data` not read.
Environment: Windows 10 (10.0.19045), Python 3.14.0, 8 CPUs, temp dirs on C:. Private scripts in `.runtime/probes-retake/` (`probe.py`, `probe2.py`, `dbg.py`, `bench.py`, `bench2.py`).

## 1. Full Python suite

`python -m unittest discover -s tests -v` (run once, first action): **Ran 292 tests in 113.8 s, OK (skipped=1)**. Timing note: another worker was editing `tap_source.py`/tests at the time, so this does not verify the final code globally.

## 2. Independent probes (`probe.py`, then corrected `probe2.py`)

`probe.py` had 4 failures that were **probe bugs, not product defects** (history layout assumed wrong, `write_text` CRLF changed the file size in R7, an `internal=True` call with a token glued to a word, an over-strict R4 assertion). `probe2.py` re-ran those four properly. Results:

| ID | Result | Observation |
|---|---|---|
| R1 | PASS | Lexical miss on a 2-entry project returns `entries=[]`, `matched=0`, `total=2`, `by_status`, and a French note saying the memory is not empty |
| R2 | PASS (with limits) | Tokens (`sk-ant-…`, `ghp_…`) straddling the title cut (positions 150–180) and excerpt cut (3900–4000), via `import_events` and the TAP `PreRedacted` path: no fragment in any file, export or handoff. **Limit observed**: a token glued directly to preceding word characters (`qqqq…ghp_…`) is not recognised and is stored in clear (heuristic, as documented). |
| R2/R6 | PASS / limit | URL `user:pw@host`, `export KEY=…`, quoted env value, multiline YAML `password: a b c`, `Authorization: Basic …`, JSON `client_secret`: no leak in files/export/handoff. URL password with a raw `/` **leaks** (documented limit). Git message redaction: NOTRUN here (existing `HeuristicGapTests`, real git log, passed in the suite). |
| R3 | PASS | Deleting revision 2 of 4, deleting the newest snapshot, or overwriting the newest snapshot with an older one each gives a clear error (“Historique incomplet… / illisible”); a healthy entry's history and `list_entries` stay readable; restoring the file restores the history |
| R4 | PASS (with a caveat) | MCP proposal → `proposed`, `channel=mcp`. Client `channel` (MCP and store) and MCP `status` refused. Import ignores `channel`/`status` → `proposed`, `channel=import`. **Caveat**: MCP `agent="Human (approved)"` is accepted (stored as a declared label on a proposal with channel `mcp`); the name guard is only a usability heuristic, which the docs already say. No authentication claim. |
| R5 | NOTRUN (existing evidence) | `ExternalMonitorTests` (real subprocess lock + tripwires) passed in the 292-test run; not re-implemented |
| R7 | PASS | Same-size, same-mtime external edit (after the cache settled) was visible on the next read (0.01 s in this run; the hit was within the unsettled/revalidation logic, so I do not claim the 5 s bound was exercised); another process's committed entry visible after 0.02 s; mutating returned objects does not change later reads |
| R8 | PASS | Editing a superseded entry's title adds a revision, the old title stays in history; reactivation to accepted/proposed is refused |
| R9 | PASS | A malformed event JSON file appears in `event_diagnostics`, the handoff text warns, and the file is left untouched |

## 3. Benchmark (3000 entries, public Store API)

Text: ~120 random French-ish words per body (~800 chars), 4-word titles. Seeded (7).

**A. `create_entry` loop (`bench.py`), budget 180 s: INCOMPLETE — 1586 of 3000 entries created in 180.1 s.** Per-250 step cost rose from 17 s to 38 s (250→1500 entries: 16.9, 38.0, 63.0, 93.2, 127.2, 165.8 s cumulative), i.e. each create costs roughly proportional to the existing count. The 3000-entry setup through `create_entry` therefore exceeds the 180 s bound; this is recorded as a limitation, not a PASS. Reads on that 1587-entry project (ms): cold list 724, warm list 120, list after the 5 s revalidation window 364, in-window 105, search hit 571 / miss 349 (warm), search cold 987, handoff 12000 query-less warm **14164 (single outlier, not reproduced)**, handoff with query 1031, cold handoff 1460, export 235 (2.2 M chars), graph 98, `create_entry` 218, `update_entry` 190, list right after a write 122.

**B. `import_events` in 12 chunks of 250 (`bench2.py`): 3000 entries in 65.4 s (setup < 180 s).** Reads on the real 3000-entry project (ms): cold list 1438; warm list 183; handoff (warm) 508 / 389 / 383; handoff with query 772; search 1087; export 513; cold handoff 2834. cProfile of the cold handoff: 2.73 s in `_scan`, of which 1.69 s in `_cached` (6017 calls, `Path.relative_to` 0.85 s) and 1.02 s in `_load_entry`; i.e. cold cost is file read/parse plus path handling, and `get_project` rescans the folder (2.2 s cumulative cold). Handoff scans the project twice.

Not reproduced: the 14 s handoff in run A. Likely environmental (disk/antivirus, other workers running), but I did not prove the cause. Single runs, no repetition statistics, one machine: no general performance claim. Write timings are measured on the ~1590-entry project in A, not on 3000.

## 4. Mapping to the acceptance table

| Area | Evidence |
|---|---|
| Secrets A6/B1/E1 | probes R2/R6 + suite; limits: glued tokens, raw-slash URL password |
| Disabled capture C4/D12 | suite (`ExternalMonitorTests`, final browser spec not run by me) |
| Recall E2 (fresh-reader E2E) | NOTRUN here (live/browser) |
| Capture resilience B2–7 | suite only; not probed by me |
| Storage A3/4/8 | R3, R9, R8 probes + suite; Windows path aliases NOTRUN by me |
| Imports A1/2/7 | `import_events` 3000-entry load OK; truncation/idempotence from suite only |
| Performance A5 | §3 (setup bound failed for `create_entry`; passed via import); cache edits R7 |
| Windows services C1–3, UI D1–7 | NOTRUN (outside task) |
| R6 | partial, limits confirmed; R10 out of scope |

## 5. Package

Wheel build + `verify_package.py`: **deferred / NOTRUN** — the earlier author reported PASS on the final source (`remediation-final-corrections.md`), and the other worker was editing `tap_source.py` after that, so that result is not a verification of the current tree. It must be re-run after the other worker finishes.

## Residual findings for the owner

1. `create_entry` cost grows with the project size (3000 entries not reachable in 180 s).
2. `handoff` on a warm 1587-entry project took 14 s once; unexplained.
3. Secret detection misses tokens glued to word characters and raw-slash URL passwords.
4. `Human (approved)` is accepted as an MCP agent label.
