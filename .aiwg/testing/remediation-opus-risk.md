# Opus independent risk review: remediation cycle (source only)

Date: 2026-10-16. Reviewer: Claude Opus. Scope: read only. Nothing was executed, so no test results appear here. Only this file was written. This review does **not** declare GO.
Inputs: independent-verification-2026-10-16.md, remediation-{store,capture,services,ui,runner,acceptance}.md.
**Stale risk:** every file is untracked (no commit, so no hash). Sonnet integration was editing at the same time. Line numbers refer to the working tree as read during this review:
store.py (1-1059), mcp.py (10-56), server.py (44-303), capture.py (800-870, 1425-1474), git_sync.py (60-109), scripts/claude_runner.py (28-87). Re-check each cited region before acting on it.

## Already addressed (seen in source, not executed)
- A-3 resilient reads: `_scan` quarantines bad files (store.py:419-437); `_project_files`/`list_projects` skip a broken project (store.py:444-493).
- A-8: the target must be `accepted`, otherwise the whole commit is refused (store.py:746-748). A replacement must itself be `accepted` (store.py:738-739).
- E-2 handoff: all current accepted entries are listed whatever the query; inventory and `filtered_out` are reported (store.py:860-862, 887-894, 922-924).
- Import ordering: an event is redacted before fingerprint, provenance and truncation (store.py:975, 993, 1011-1016). Event-index rows store hashes only.
- Shared cache state: callers get copies (`_clone_entry` store.py:317-318, 659; `deepcopy` 505, 508, 842).
- Error text: store and capture errors name fields or files, never values (store.py:229-238, 297-309; capture.py:860-864). HTTP errors go through `_public` (server.py:236-249).
- C-4 no-capture: `DisabledCapture` (server.py:48-72) has no source path. `__getattr__` raises `CaptureOff`, and `capture_action` refuses every action except `stop` (server.py:256-257).

## Ranked remaining findings

**R1 — P2, blocks the E-2 acceptance. MCP `search_memory` still returns a bare `[]`.** mcp.py:37-38 calls `store.list_entries`, not `store.search` (store.py:690-701, which returns `total`/`by_status`/`note`).
Repro: one accepted "SQLite" decision, then the MCP call `search_memory(query="database")` gives `[]` with no inventory. A fresh agent concludes there is no decision, which is the E-2 failure on the MCP surface.
Fix: return `store.search(...)`, or wrap the list with `matched/total/note`. Acceptance: an MCP test with no lexical hit shows `total>0` and the note.

**R2 — P2 privacy. Capture truncates before the store redacts, so a partial secret can survive.** capture.py:825-837 builds `title` from `_first_line(...)`, cuts it at `title[:180]`, and cuts `excerpt` at `item["text"][:4000]`. All of this happens before `import_events` redacts (store.py:975).
Mechanism: the cut can fall inside a token, leaving `sk-ant-` plus fewer than 16 characters (store.py:44 needs `{16,}`). The fragment is then not matched, and is stored in current, history, export and handoff. This applies to every length-gated pattern.
Fix: redact `item["text"]` (`store.redact`) before any slicing in `_events`. Acceptance: a synthetic token placed across the 180 and 4000 boundaries leaves no fragment in any persisted file.

**R3 — P2 integrity. A missing history revision is not detected.** store.py:822-825 rejects only *unreadable* files. Repro: create an entry, update it twice (revisions 1, 2, 3), delete `history/<id>/2.md`. `list_history` then returns [3, 1] with no error.
This contradicts the comment at store.py:823 and the acceptance line "Damaged history is rejected clearly". Also, the newest snapshot is never compared with the current entry, so an external edit at the same revision cannot be detected.
Fix: require the revision set to equal {1..current.revision}. A mismatch between the current entry and its newest snapshot becomes a diagnostic. Acceptance: tests for deletion, a gap and a mismatch.

**R4 — P2 governance claims (architectural disposition for C-5 and the MCP label).** Facts in source:
- `GET /api/bootstrap` hands out the mutation token to any local client that passes the Host/Origin checks (server.py:178-179).
- `POST entries` accepts `status:"accepted"` (server.py:207-208).
- `agent` defaults to `"human"` (store.py:723) and can be edited through PATCH (`EDITABLE` store.py:27).
- The MCP blocklist is a fixed list (mcp.py:11, 49-51); "Human (approved)" or the user's real name passes.
- Yet handoff tells agents "Accepted means human-approved" (store.py:858).

Any process running as the same user can fetch the token or write the Markdown files directly, so no identity guarantee is possible here. Disposition:
- (a) Document the token as a *local UI control channel* only, not human identity.
- (b) Change store.py:858 to "accepted through the local review interface; actor identity is not authenticated".
- (c) Record a server-set, non-editable `channel` (`http-ui` / `mcp` / `import` / `capture`) on each entry and on each status-change event. Currently there is none (grep: no `channel`/`actor` field in store.py).
- (d) Show `agent` as "declared by" text and remove `agent` from PATCH-editable fields, or record such edits as events.
- (e) Optional: `POST entries` forces `proposed` and acceptance goes only through PATCH review. This reduces accidents, not malice.
- Keep the blocklist as a usability guard only; never present it as a security control.

Acceptance: no doc, UI or handoff text claims authenticated human identity; `channel` cannot be set by the client.

**R5 — P2 integration. `--no-capture` hides a capture monitor that is already running.** `DisabledCapture.status` always reports `running: False` (server.py:55-61), and `stop` returns `not_running` (server.py:66-67, 275). A detached `capture run` for the same data dir (capture.py:1454-1466) keeps importing.
Repro: start capture in the background, then run `serve --no-capture` on the same data dir. The UI says disabled while new proposals keep appearing, and Stop does nothing.
Fix: probe only the store's own `.capture` lock (capture.py:1434-1438 style; no TAP or native path). Report `external_monitor_running`, and allow the cooperative stop file. Acceptance: a subprocess test where the source-access trap still records 0 calls.

**R6 — P3 privacy, heuristic gaps that remain.**
- Bare values stop at whitespace (store.py:48), so `password: my secret phrase` (YAML/prose) masks only `my`.
- URL credentials stop at `/` (store.py:37), so in `postgres://u:pa/ss@h` the password is not masked.
- Git checkpoint messages are not redacted, and they are committed and can be pushed (git_sync.py:77-99).

Treat these as documented heuristic limits or fix them. Acceptance should list them explicitly instead of implying full coverage.

**R7 — P3 cache staleness.** store.py:407-411: `settled` is fixed when the file is first loaded. An entry read less than 2 s after its mtime is then revalidated only by `(mtime_ns, size)` and the generation token. If an external tool rewrites the file with the same size and mtime, for example `accepted`↔`rejected` (both 8 characters) on a coarse-mtime file system (FAT/SMB), or a tool that preserves mtime, the stale value is served until the next Filigree commit.
Fix: recompute `settled` on a hit, or add a content hash for unsettled hits. Acceptance: the A-5 test "external edit noticed" includes a case with the same size and mtime.

**R8 — P3 supersession irreversibility and how it surfaces.**
- An accepted replacement cannot be rejected: store.py:735-739 raises "Only an accepted entry may supersede", and the target can never be reactivated (store.py:785-786). This is intentional but irreversible. Document the recovery path (a new accepted entry that restates the target) and replace the misleading error.
- A superseded entry can still have its title/body edited, and the replacement's history is unaffected. Decide whether that is allowed.

**R9 — P3 silent omissions.**
- `list_events` drops corrupt events without reporting them (store.py:841), so review reasons disappear from the handoff.
- `list_history` on a quarantined entry returns 404 "not found" (store.py:806-807) instead of the quarantine message used at store.py:775-776.

**R10 — Runner, bounded and as documented.**
- claude_runner.py:31-82 kills only its own PID tree. The wait is bounded, output goes to temp files, and Ctrl+C is handled (`BaseException`).
- Residual 1: on Windows, `taskkill /T` misses a re-parented descendant. The defect report's case (an outer process still alive at timeout) is covered.
- Residual 2: POSIX `killpg` has not been executed.
- Residual 3: a hard kill of the runner leaves state `running`.
- A Windows Job Object (`KILL_ON_JOB_CLOSE`) would close residual 1. Acceptance requires real POSIX evidence before any claim about POSIX.

## Acceptance requirements added by this review
1. R1–R5 are fixed or have an architect-signed disposition. Each has a test that fails on the code reviewed here.
2. R4 text and the `channel` field are verified in UI, MCP and handoff output. No claim of human identity anywhere.
3. A secret matrix including boundary positions (R2) and the R6 forms, checked in current, history, events, export, handoff, Git commit and UI.
4. Re-run the full suite after Sonnet integration and report real counts. Earlier reports show conflicting failures: services saw `test_history_validates_revision_filename_and_snapshot_identity` fail, and `workbench.spec.cjs:36` fails because of A-8. Neither has been resolved by execution.
5. Still required, not replaced by this review: fresh-reader MCP E2E (acceptance.md "Recall"), 3000-entry timings, and the 375 px screenshots.
