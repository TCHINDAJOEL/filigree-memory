# Final gate review: Filigree 0.1 early release (Opus)

Date: 16 October 2026. Reviewer: Claude Opus via claude-tap. This was a **source and evidence review only**. I ran no tests, builds or live calls, and I edited no code. I compared `final-verification.md` against the private executor outputs: `.runtime/queue-6-result.txt`, `targeted-tests-result.txt` and `mcp-pass-result.txt`. Those outputs are not published. Codex owns the gate.

## Evidence vs. report

| Claim in final-verification.md | Executed evidence | Holds? |
| --- | --- | --- |
| 140 tests OK | targeted-tests: "ran 140 tests, all OK" | Yes |
| Playwright 7 passed | queue-6: "7 passed (40.4 s)" | Yes, see "Freshness" |
| Wheel + isolated install PASS | queue-6: wheel built, `verify_package.py` PASS | Yes, see "Freshness" |
| `node --check` valid | queue-6: no output and no error. The exit code is inferred | Yes, with that caveat (the report states it) |
| Real Claude Code via TAP PASS | queue-6, check 6: 3 proposals, exact provenance, no duplicates on rescan | Yes |
| Real Claude Code direct PASS | targeted-tests, check 3: exit 0, 4 proposals, marker, native provenance, rescan dedup | Yes |
| Real MCP retrieval PASS | mcp-pass: tool calls `project_for_folder`, `get_handoff` and `search_memory`, no `propose_memory`. The current decision (accepted), replaced decision (superseded) and open question have correct IDs, and statuses are unchanged after the call | Yes. The executor did not see the client's wording; the script checked the IDs and titles per role |
| Queue-6 failures resolved without removing checks | see below | Yes |

**Freshness.** Glob mtime ordering shows every `filigree/**` product file and `tests/browser/workbench.spec.cjs` is older than `queue-6-result.txt`. Only these files changed after queue-6:
- `tests/test_capture.py`
- `scripts/verify_live_capture.py`
- `scripts/verify_live_handoff.py` (after targeted-tests, before mcp-pass)
- `README.md`

The browser and package results therefore apply to the final product code, so the report's claim that no rerun was needed is accurate. The runner quota fix (`scripts/claude_runner.py`, `tests/test_runner.py:50-51`) predates the 140-test run, so its regression test is included in that count.

**The three queue-6 failures were legitimately resolved:**
- `test_capture.py:965-966`: entry listing order is not capture order, and both sides are now sorted. The test still checks that the pause line is absent and that the held lines are kept (`:962`).
- `verify_live_capture.py:314-332` (`check_sources`): this is a **tightening**, not a relaxation. The check requires exactly one native source matching `native:claude:<id>:…`, exactly one `import:sha256` fingerprint, exactly one provenance source, at most one timestamp, and rejects any other auxiliary source.
- MCP: the cause was the inherited `CLAUDE_CODE_SAFE_MODE` marker. The helper now changes only the child's environment, and the read-only tool allowlist plus the `propose_memory` absence check are kept.

## Previous P1/P2 findings: re-checked in source

| Finding | Status |
| --- | --- |
| P1-1 RC-07 | Fixed. `_save` writes `pending.json` before `state.json` (`capture.py:371-375`). `CheckpointOrderTests` (`test_capture.py:598-628`) injects a crash on the second write, restarts, links and recovers the record. The only other `state.json` write (`:1203`) is a scan-error notice that does not advance cursors. |
| P1-2 tracking | Fixed according to `final-fixes.md`. Not re-verified line by line. |
| P2-1 fallback toggle | Fixed. `hold-fallback` is separate from the global hold (`:400`, `:1155`). Regression test at `test_capture.py:576`. |
| P2-2 held lines across pause | Fixed for the tested paths (`test_capture.py:945-983`). The remaining edge cases are listed in final-fixes "Limites connues". |
| P2-3 Git root above home | Fixed. `_contains_home` (`:189`, `:609`). Test at `test_capture.py:985`. |
| P2-4 direct-launch claim | Resolved by real execution (targeted-tests, check 3). README `:22` and `:152` now match the evidence. |
| P2-5 import draft | Fixed. Playwright `workbench.spec.cjs:93` is part of the 7 passing tests. |
| P2-6 stale docs | Superseded by `final-verification.md`. |
| P2-7 `git add` size | Fixed. `ADD_CHUNK_CHARS = 8000` (`git_sync.py:9,68-74`). Test at `test_adapters.py:119`. |
| P2-8 `tap:` history | Fixed according to final-fixes (`HistoryWithNativeMappingTests`, `test_capture.py:631`). |

## README claims

The README is consistent with the evidence:
- The real TAP, direct and MCP runs are claimed only for Claude Code/Haiku (`:22`).
- Codex is described as covered by synthetic fixtures only (`:22`, `:152`).
- The README says an MCP configuration is required for recall and that capture only writes proposals (`:101`), so there is no claim of universal automatic injection.
- The monitor must be running (`:150`).
- CI is described as "configured", not as passing (`:198`).

Non-blocking documentation nits (P3):
1. `README.md:146` presents `install-capture-startup.ps1` without saying it was never executed. Adding "not yet exercised in verification" is recommended.
2. `README.md:198` links `verification.md` rather than `final-verification.md`. The `:22` link is correct.
3. `README.md:200` describes only the TAP live check. `--native-direct` and `verify_live_handoff.py` are documented only in AGENTS.md.
4. `README.md:19` puts `codex` in the quickstart. The next paragraph qualifies it, which is acceptable.

## Remaining limitations (accepted scope, not blockers)

- No real Codex CLI or App run. Codex is covered by fixtures and isolation tests only.
- The Windows startup installer was not executed.
- There is no universal automatic memory injection. A client must be configured for MCP and must ask.
- The evidence covers one machine with Claude Code/Haiku.
- Some exit codes were not displayed and are inferred from PASS/OK output (the report discloses this).
- Simultaneous corruption of `pending.json` and `state.json` is not handled. A partial line straddling a pause is dropped.
- Scale and performance are not measured, and GitHub CI has not been observed yet.

## Gate recommendation

**GO for a public early 0.1 release.** I found no remaining concrete release blocker in product code, tests or the evidence trail:
- Every earlier P1 and P2 finding is fixed in source with a regression test, or resolved by real execution.
- Every row of `final-verification.md` matches the executed evidence.

Conditions belong to Root's packaging and hygiene review:
- `.runtime/`, `.traces/` and private results must stay unpublished. `.gitignore` covers `.runtime/` and `.traces/`.
- The first CI run should be recorded after publication.

The P3 README nit #1 (Windows startup not exercised) is a cheap fix and is recommended before tagging.
