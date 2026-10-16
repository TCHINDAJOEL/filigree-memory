# Opus independent release review — retake on frozen final changes

Date: 2026-10-16. Reviewer: Claude Opus (independent, not author). **Read-only.** I ran nothing (no tests, live calls, browser, wheel, probes). I wrote only this file. Inputs: `same-project-live-retake.md`, `privacy-retake.md`, `probes-independent-retake.md`, `remediation-final-corrections.md`, `live-independent-retake.md`, `remediation-opus-risk.md`, plus the current source cited below. I did not read private transcripts, TAP/native DBs, `agentC/data` or `.runtime` evidence. The tree is untracked (no commit hash), so line numbers refer to the working tree as I read it.

## Verdict: **NO-GO** (for now)

The product code that I reviewed is in releasable shape for a heuristic local tool. Two things block the release:

- There is **no live PASS** on the current code.
- The README makes live-verification and capture claims that the current code and evidence do not support.

Both can be fixed without changing the architecture. The prerequisites are listed at the end.

## Blockers

**B1 — P1: no successful end-to-end live journey on the current code.**
- The latest run, `20261016T211332Z`, FAILED on a helper judge bug (`same-project-live-retake.md:30`).
- Because the run aborted there, the reader non-mutation check, the post-reader leak scan and the final browser scan were never executed live (`scripts/verify_live_journey.py:628-638`: `judge_answer` runs before the digest and leak checks).
- The offline re-judge (`:31`) is a diagnostic, not a PASS, and must not be cited as one.
- The capture, real-browser accept and reader MCP retrieval steps did succeed live. That is encouraging, but it is partial.
- Required: one fresh, authorized journey that prints `PASS (live)` (`verify_live_journey.py:642`) on the current tree.

**B2 — P2: the README contradicts the current capture code.**
- `README.md:161` says: "Side requests without tools (titles, summaries) and `max_tokens: 1` probes are ignored."
- The current code drops only `max_tokens == 1` (`filigree/tap_source.py:456-463`). Tool-less and auxiliary calls (titles, summaries, structured output) are now **captured as proposals**.
- Tests confirm this: `tests/test_capture.py:737-781`.
- Users are told some traffic is not stored when it is. That is a privacy-relevant inaccuracy.
- Fix: state that only the verified one-token warm-up is skipped, and that auxiliary calls may appear as noise proposals the user can reject.

**B3 — P2: README live claims predate the changed capture path.**
- `README.md:22` says "Real Claude Code runs have verified both claude-tap and direct launch, and a real Haiku client retrieved a sourced handoff through MCP" and links `final-verification.md` (05:59).
- Since then, `tap_source.py` side filtering, redaction (`store.py:40,48-49`), `mcp.py` search and the server have all changed.
- The old capture/TAP, native-direct and handoff helpers have **not** been re-run on the current code (`same-project-live-retake.md:34`, `live-independent-retake.md:30`).
- Fix: either re-run them after B1 passes, or qualify the sentence (date, earlier build, Haiku) and point to the current evidence.

**B4 — P2: the shipped artifact is unverified.**
- The only wheel build and `verify_package.py` PASS (`remediation-final-corrections.md:14`) predate the `tap_source.py`/`store.py` edits.
- Both later reports say the wheel step was deferred (`same-project-live-retake.md:35`, `probes-independent-retake.md:52`).
- Required: rebuild the wheel and re-run `verify_package.py` after the final edit.

## Should-fix before publishing (not architectural)

**S1 — P3: the README redaction limits are stale in both directions.** `README.md:155` lists "a raw `/` inside a URL password" as not covered, but it is now masked (`store.py:40`; `tests/test_privacy_retake.py:36-43`). It also omits the limits that remain (`privacy-retake.md:19-21`):
- generic token shapes glued to word characters (`AKIA…`, `npm_`, `hf_`, `eyJ…`, bare `sk-`, `sk_live_`) are still stored in clear;
- `?`, `#` or `@` inside a URL password, or a password longer than 128 characters, is not fully masked;
- a password that starts like a port (`u:12345/x@h`, because of the `(?!\d{1,5}/)` guard at `store.py:40`) is not masked;
- a glued known-prefix match swallows the alphanumerics that follow it, and `https://host:abc/x@y` gets masked (false positives).

The README sentence "Text is redacted in full before any title/excerpt/body is cut" is consistent with the probes (R2 PASS).

**S2 — P3: the performance limits are undocumented.** Measured once, on one machine (`probes-independent-retake.md:30-34`):

| Measurement | Result |
|---|---|
| `import_events`, 3000 entries | 65 s |
| `create_entry` loop | incomplete: 1586 entries in 180 s, roughly linear per write |
| Cold handoff at 3000 entries | 2.8 s (two project scans, `_scan` / `Path.relative_to`) |
| Handoff outlier | one 14 s, not reproduced |

There is no SLO, so none of this blocks the release. Add one honest README limit: "per-entry writes slow down as a project grows; thousands of entries are best loaded by import; cold handoff takes seconds." Do not claim a cause for the 14 s outlier. An architecture overhaul is not warranted for 0.1.

**S3 — P3: the live-journey judge is permissive.** `choice_is_sqlite` (`verify_live_journey.py:338-350`) accepts any `not` or `no` before "Postgres", so an ambiguous reply such as "SQLite or not; Postgres" passes. This does not make the release unsafe, because the reason and the exact `note_id` must also match (`:356-357`). Optional tightening.

## Checked and found sound (source read, not executed)

- **Redaction boundedness:**
  - The new URL branch has a bounded password part (`{0,128}`) and character classes that exclude the delimiters.
  - Distinctive-prefix patterns drop the word boundary; generic shapes keep it (`store.py:48-49`).
  - I did not find a catastrophic-backtracking construct.
  - Git checkpoint messages are redacted (`git_sync.py:81`).
  - The flipped assertion `test_remediation_opus.py:156` (now `assertNotIn`) tracks the closed gap; it is not a weakening.
  - New tests cover current files, history, events, export and handoff (`test_privacy_retake.py:55-66`).
- **Tool-less / JSON capture honesty:**
  - The docstring states the trade-off: possible noise proposals rather than silent loss.
  - Tests assert exact-project placement, an empty other project, no hidden or system text, and `proposed` status only.
  - The tests are not weakened: the warm-up test still asserts that `side_request` is counted.
  - The only problem is the doc (B2).
- **Same-folder fresh reader** (`verify_live_journey.py:132-179, 604-630`):
  - The reader has the same canonical folder, a separate TAP DB, `--strict-mcp-config`, `--tools ""` plus the read tools only, no resume/continue, and hooks/settings disabled.
  - The prompt is checked for the id, "sqlite", "postgres" and the nonce (`:610`).
  - The writer has no tools, so it cannot write files or native memory into the folder.
  - Line `:582` asserts that nothing is accepted before the browser review, so the memory is not seeded with an accepted entry.
  - Distinct native and TAP sessions are checked (`:148-152`).
  - Residual hygiene note, not a leak path: `claude_call` (`:217-229`) does not redirect `CLAUDE_CONFIG_DIR`, so the synthetic writer and reader transcripts land in the user's real Claude config (that is how `find_transcript` finds them). The privacy report should state this.
- **Read-only MCP / proposals:**
  - `search_memory` returns `store.search` with inventory and note (`mcp.py:38-40`), so R1 is closed.
  - `propose_memory` forces `proposed` and `channel="mcp"` (`mcp.py:54-58`).
  - The handoff wording no longer claims human approval (`store.py:932`).
  - The `HUMAN_NAMES` blocklist is labelled as a usability guard (`mcp.py:10-12`).
  - `"Human (approved)"` is still accepted as a declared label; this is documented (`SECURITY.md:7`).
- **UI controls / provenance:**
  - The provenance card escapes its values and says the identifiers are not authenticated (`app.js:67`).
  - The external-monitor banner offers only the stop control, and declared labels are rendered as such (`remediation-final-corrections.md` §3-4).
  - Browser runs: 28/28, run alone (`live-independent-retake.md:23`). The UI files have not changed since then, but `store.py` and `tap_source.py` have.
- **SECURITY.md:** no Codex, automatic-monitor or identity overclaims. The trust boundary is accurate.
- **README Codex claims:** `README.md:22,152` correctly say Codex is covered by synthetic fixtures only.

## Earlier risks R1–R9 and acceptance areas A–E (current status)

| Item | Status | Evidence |
|---|---|---|
| R1 MCP empty search | Closed | `mcp.py:40` |
| R2 truncate-before-redact | Closed | probe R2 PASS; README:155 |
| R3 missing history revision | Closed | probe R3 PASS |
| R4 identity / channel | Closed by documentation | `SECURITY.md:7`, `store.py:932`; label remains declared |
| R5 external monitor | Closed | browser test + suite |
| R6 heuristic gaps | Partially closed | URL `/` and glued prefixes fixed; remaining limits need README update (S1) |
| R7 cache staleness | Closed | probe R7 (5 s bound not specifically exercised) |
| R8 supersession | Documented | README:158 |
| R9 silent omissions | Closed | diagnostics banner, probe R9 |
| E2 fresh-reader live | **Open** | B1 |
| A5 performance | Limitation, undocumented | S2 |
| Windows path aliases (A) | Not independently probed | suite only |
| C1–C3 Windows services | Not run in any retake | — |
| B2–B7 capture resilience | Suite only | — |

## Freshness

- Full Python: 300 passed, 1 skipped "after the privacy barrier" (`same-project-live-retake.md:17`). The same report also fixed `judge_answer` and its tests. From the report, I cannot confirm that the full run came **after** the last edit to `scripts/verify_live_journey.py` or `tests/test_live_journey_helper.py`, which are the newest files in the tree.
- Prerequisite: re-run the full suite once on the frozen tree and record the counts.

## GO prerequisites (all required)

1. Full Python suite and Playwright suite each run once on the frozen tree, with the reported counts.
2. A fresh wheel build plus `verify_package.py` PASS, after the last edit (B4).
3. An authorized live journey ending in `PASS (live)` on the current code, including reader non-mutation, the persisted-leak scan and the browser scan (B1). Budget: 3 calls remain; no retry beyond the policy.
4. After step 3: either re-run the capture/TAP, native-direct and handoff helpers, or qualify `README.md:22` (B3).
5. README edits: line 161 (B2), line 155 limits (S1), and a short performance limit (S2). Docs only; no product change is needed.

Root may publish only once steps 1–5 are evidenced. Items S3, the `CLAUDE_CONFIG_DIR` note and the untested Windows-service and alias areas can ship as documented known limits.
