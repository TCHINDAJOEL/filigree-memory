# Independent release review: automatic capture (Opus)

Date: 16 October 2026. Reviewer: Claude Opus via claude-tap, **source review only**. I ran no tests, builds or live calls. Execution evidence comes from Haiku's reports in `.runtime/queue-1-result.txt` and `.runtime/queue-3-result.txt` (private, not published). Codex owns the gate decision.

## Executed evidence (referenced, not reproduced)

| Run | Source | Outcome reported by Haiku |
| --- | --- | --- |
| Before repairs | queue-1 | unittest 124 tests, 1 failure (`test_folders … nope\..`); Playwright 5/6 (exclusion form cleared); wheel built, `verify_package.py` PASS; live check absent |
| After repairs | queue-3 | unittest **130 OK**; `node --check` no error (exit code not shown); wheel rebuilt; `verify_package.py` PASS; Playwright **6/6**; `verify_live_capture.py` **PASS** (one Haiku exchange through claude-tap, 3 proposals, provenance matched, rescan without duplicates) |

Limits of this evidence:
- The live run calls `capture.set_native_fallback(False)` (`scripts/verify_live_capture.py:124`). It proves **tap → native index → folder** for one Claude Code client, not a direct launch.
- No Codex client and no second-model handoff scenario (capture-acceptance § « Passage à un autre agent ») were executed. They remain **unverified**.
- `install-capture-startup.ps1` was not executed.
- A green suite does not cover RC-07 below.

## P1: block release until fixed or explicitly accepted

**P1-1: RC-07 is still open (crash between `state.json` and `pending.json`).**
- `filigree/capture.py:361-363`: `_save` still writes `state.json` (advanced cursors) before `pending.json`.
- In `_scan_tap` (`capture.py:840-845`), records that became pending in this batch move the cursor forward. A crash between the two writes therefore loses their pending keys permanently and silently. `--import-history` only reaches the baseline, so it cannot recover them.
- Same ordering in the DB change path (`capture.py:811-819`). The new `db_key` can persist while `pending.json` still holds the old database's keys, and those keys are then retried against the new DB. This is the case quarantine was meant to prevent; impact is limited because the session UUIDs rarely match.
- Tests `test_capture.py:511` and `:815` patch the whole `_save`, which simulates a crash *before* both writes. They do not cover this path.
- Contradicts US-15 (« plantage ne perdent pas l'état »).
- Fix: write `pending.json` first and accept an idempotent replay, or use one atomic checkpoint file. Add a test that fails between the two `os.replace` calls with an unknown session, then links it.

**P1-2: findings tracking omits RC-07.** `.aiwg/testing/followup-capture-2026-10-16.md` lists RC-01..06 and the F-UI findings as corrected but never mentions RC-07. The orchestrator marked RC-07 « doit être traité avant livraison ». The evidence trail currently reads as complete when it is not.

## P2: correct or document before publication

**P2-1: a fallback toggle discards tap activity.** `set_native_fallback` calls `_hold()` (`capture.py:415-417`), and `scan_once` turns the hold file into both `hold` and `fallback_hold` (`:1080-1083`). Toggling the fallback, even **on**, makes the next tap scan jump its cursors to the maxima (`:807-819`, « resumed »). Every tap record since the last cycle is skipped, which can cover a whole day if the monitor was stopped. Only `fallback_hold` should be set here.

**P2-2: a global pause or disable also drops held native lines.**
- `capture.py:903-909` calls `stalled.clear()` and moves each held file's offset to EOF.
- Those lines predate the pause, and the README promises « held, not skipped … nothing lost » (`README.md:132`).
- Tap pending keys survive a pause, so the two sources behave differently.
- Fix: keep held offsets across a pause, or state this loss explicitly.

**P2-3: the Git-root ascent can merge unrelated folders.**
- `capture.py:560-570` creates the project at `_git_root(root)`, and that search has no upper bound.
- A `.git` in the home directory (dotfiles) or at a drive root files every session below it into one project.
- `verify_live_capture.py` already moves its folder to temp to avoid this.
- Fix: refuse home, drive and filesystem roots (and the data dir) as auto-create targets, falling back to the cwd itself. Add a test.

**P2-4: the README overstates direct launch.**
- `README.md:19` presents `cd … && claude` as the quickstart, and `:132` describes the fallback as the main path.
- `:152` admits the fallback has only run on synthetic transcripts, and the live run disabled it.
- Acceptance #8 says not to announce this path unless it has been executed. Mark it « non vérifié sur client réel » in the quickstart, or run a live direct-launch check.

**P2-5: an explicit project switch erases the import draft.** The import form lives in `#main`, not in a modal. Selecting a project (`app.js:273-277`) calls `refresh` then `render`, which rebuilds `importView()` (`:89-90`). No write is misdirected, because `assertStable` holds (`:28`, `:246`), but typed text is lost. Acceptance #9 requires that no draft disappear; retain or confirm before discarding.

**P2-6: the evidence docs are stale.**
- `.aiwg/testing/verification.md:24-33` still lists everything as « NON exécutés ».
- `followup…md:15` marks F-PACKAGE-01 as « Ouvert », although queue-3 shows the wheel was rebuilt and `verify_package.py` passed.
- Record queue-3 as the executed evidence, along with its limits.

**P2-7: Git checkpoint argument size.** `git_sync.py:59-63` passes every memory file to a single `git add -- …`. On Windows a large memory (many `history/` revisions) can exceed the ~32 KB command-line limit. Use `--pathspec-from-file=-` or chunk the list. The allowlist itself is sound: an exact regex, an index pre-check, and push restricted to a GitHub origin.

**P2-8 (minor): `tap:` + `--import-history` with an agreeing native mapping.**
- When a native-id mapping and a `tap:` mapping agree, `_link` returns the native key as `mapped_key` (`capture.py:590-599`).
- `_retry_pending` then filters on `require_key = tap:…` (`:884`, `:742`), so every history row is skipped and the request is deleted silently.

## Previous findings: status in source

| Finding | Assessment |
| --- | --- |
| RC-01 hidden reasoning | Resolved. `is_private` covers types and `channel`/`phase` in both channels (`tap_source.py:330-336`, `capture.py:993,1003`). Codex `reasoning` items produce no items. |
| RC-02 direct activation | Default on (`capture.py:62`), with bounded cross-channel ledgers. Live-unverified (P2-4). |
| RC-03 explicit conflict | Resolved. `tap:` mapping is read before refusal; contradictory mappings return `mapping_conflict` (`capture.py:586-602`). |
| RC-04 thread_id | Resolved, in both body and header forms; divergence becomes a conflict (`tap_source.py:289-298`). |
| RC-05 bounded reads | Resolved. Blob size is checked inside SQLite and each reference strictly (`tap_source.py:224-241`); same-size rewrites go through `_first_sight` (`native_index.py:197-205`). Remaining: a larger rewrite inside the read region is undetected (documented). |
| RC-06 provenance | Resolved. `target_folder`/`target_basis` set and `cwd` left empty for explicit links (`capture.py:651-655`, `:1049-1051`). |
| RC-07 crash ordering | **Open** (P1-1). |
| F-UI-01 | Resolved for writes: `switching`, `assertStable(pid)`, hidden `project_id` fields, and the test waits for `#project-name`. Draft loss in P2-5. |
| F-UI-02 | Resolved (`app.js:67`). |
| F-PACKAGE-01 | Resolved by queue-3 execution; the docs have not caught up (P2-6). |

## Contract checks that hold (source)

- **Folder linkage:** exact id equality only. Multiple sources lead to `ambiguous_native_session`, and divergent cwds without a common root lead to `ambiguous_cwd`. A mixed registered/unregistered pair is ambiguous. Nothing is resolved by time or name.
- **Mapping scope:** `tap:` mappings are scoped by `db_key`, and unscoped legacy keys are never applied.
- **Decoding:** the envelope, version, path regex, `MAX_REFS`, the 32 MiB materialization cap and per-record SQL size limits are enforced. Any anomaly rejects the record and is counted, and the database is opened read-only with `query_only`.
- **Injection:** injected and system blocks are stripped (`visible_text`). Content is stored as escaped data and never executed; imports are always `proposed`.
- **State and pause:** an OS lock gives one monitor per data dir. Settings and mappings writes take the store lock. The baseline skips history, and resume skips the pause window (except P2-1 and P2-2).
- **Isolation:** the Playwright and package servers use `--no-capture` and an absent `CLOUDTAP_DB`.

## ADR / SDLC review

- ADR-0002 Revision 3 correctly supersedes §5, §8 and §12 through its table. The superseded body text is kept as history, which is acceptable.
- US-15 needs RC-07 fixed or an explicit limitation; it cannot stay as written.
- `user-stories.md:57` correctly keeps unverified criteria open. The handoff comprehension check and Codex/real direct launch must appear as open at the gate.

## Gate recommendation

**Not ready.** Required before release:
1. Fix RC-07 and add the targeted crash test (P1-1).
2. Update the follow-up and verification docs with RC-07 and the queue-3 evidence (P1-2, P2-6).
3. Haiku re-runs the suites.

P2-1 and P2-3 are cheap correctness fixes and should be fixed before release. P2-2, P2-4, P2-5, P2-7 and P2-8 can ship only if they are documented as limitations. The final decision belongs to Codex.
