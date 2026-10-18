# Import of the real history: claude-tap, Claude Code, Codex (2026-10-18)

The user asked for every existing trace to be imported, with the real projects of the machine created and linked.

**Machine.** Windows 10, data folder `C:\Users\Admin\.filigree`, agent `filigree agent` (0.2.0 plus the commits on `feat/v2-observateur`).

**What was recorded.** Only counts and paths. No conversation text was read or copied into this document.

## 1. Incident: claude-tap traces pruned, then fully recovered

**What happened.**
- A one-off launch of `claude-tap` during the investigation applied its default setting, `--tap-max-traces 50`.
- That launch deleted the oldest sessions from the live database: `deleted_upstream` = 51 seen by the capture.
- The setting has no environment or configuration alternative. Only the command-line option exists, and `0` means unlimited.

**Recovery.**
1. Raw copy of `traces.sqlite3`, its `-wal` and `-shm` files to `E:\filigree-rescue\raw\`.
2. The main file read without its WAL still held the state before the prune.
3. `sqlite3 .recover` rebuilt `E:\filigree-rescue\recovered\traces.sqlite3`:
   - 100 sessions, 12 688 records ;
   - `integrity_check` returns ok.

**Not done by the agent.** Writing back into the live claude-tap database was refused by the Claude Code safeguard, rightly so. The restore is given to the user as a copy-paste command (claude-tap closed, backup first, `INSERT OR IGNORE`).

**Lesson.** Never launch `claude-tap` without `--tap-max-traces 0` on a machine whose history matters.

## 2. Codex history: `filigree import-codex-history`

Source: `~/.codex/thread_history_1.sqlite` and `state_5.sqlite` (Codex 0.162.1).

| Run | Threads imported | Proposals created | Duplicates recognized | Interrupted |
|---|---|---|---|---|
| 1 | 90 | 14 706 | 0 | yes (memory busy) |
| 2 | 95 | 707 | 14 706 | yes (memory busy) |
| 3 | 100 | 411 | 15 413 | no |

- **Totals:**
  - 187 threads read, 17 108 items, 15 824 observations, spread over 28 projects ;
  - 1 154 redactions in total (1 140, then 12, then 2) ;
  - 0 malformed, 0 rejected.
- **Skipped (87):**

  | Reason | Threads |
  |---|---|
  | `no_items` | 54 |
  | `outside_roots` | 12 |
  | `live_source` | 10 |
  | `cwd_missing` | 6 |
  | `excluded` | 5 |

- **Why runs 1 and 2 were interrupted.** The store was in contention with the running agent; the cause is identified in §4.
  - The importer's interruption behaved as designed: a clean stop, then a resume without duplicates.

## 3. Catch-up: `filigree backfill`

**Rewind** (agent stopped), then replay by the agent:
- tap: 50 sessions, 1 930 records ;
- native: 122 transcripts, 176.8 MB ;
- activity: 122 transcripts.

**Timeline.** The replay closed at 2026-10-18T11:55:21Z, with the notice `backfill_done`.

**Cumulative capture counters at closing:**
- `imported` (claude-tap) 10 266 ;
- `fallback_imported` (native) 4 779 ;
- `duplicates` 592 ;
- `redactions` 619.

**Main skipped counters:**

| Counter | Value | Meaning |
|---|---|---|
| `fallback_tap_duplicate` | 4 086 | native copies already captured through claude-tap |
| `analysis` / `fallback_analysis` | 3 343 / 1 711 | client analysis requests, not conversation |
| `injected` / `fallback_injected` | 934 / 38 | context injected by the clients |
| `web_search_tool_result` | 551 | |
| `non_conversation` | 157 | |
| `side_request` | 91 | |
| `excluded` | 26 | |
| `backfill_twin` | 4 | same item already present through the other channel |

## 4. Defect found by the real import, then fixed

**Symptoms.**
- After the Codex import (21 496 entries in 29 projects), the replay stayed stuck at 282 tap records for several minutes.
- `ConflictError` appeared in a loop in `.runtime/agent.log` and in the capture notices.

**Cause, measured on that memory.**
- `list_projects` counts every entry. The activity observer calls it every cycle, and the workbench calls it on every project switch.
- The LRU cache of 20 000 files was smaller than the memory, so every pass was a cold read.
- The workspace lock was therefore held more than 15 s, the capture timed out, and it restarted its cycle without progress.

| Full scan of the entries | Duration |
|---|---|
| cache 20 000, revalidation 5 s | 15.3 s, then 16.9 s |
| cache 200 000, revalidation 5 s | 6.2 s |
| cache 200 000, revalidation 60 s | 2.0 s |

**Fixes.**
- Commit `1c90554`: cache sized at 200 000 files, revalidation every 60 s.
- Next commit: project counts cached per `entries/` folder, keyed on the folder's mtime. It is not trusted while the folder is younger than 2 s, and is revalidated every 60 s.
  - 6 tests in `tests/test_store_counts.py`.

**Result on the real memory** (agent restarted):

| Call | Before | After |
|---|---|---|
| `GET /api/projects` (31 projects) | about 14 s | 0.63 s, then 0.49 s, then 0.22 s |
| `GET …/entries` for the largest project (9 167 entries, 33 MB) | | 3.4 s |

**Workbench** (`app.js`):
- lists and timeline in pages of 100 ;
- excerpts of at most 600 characters ;
- retry of reads on a busy memory ;
- no reload of the project list when switching to a project already listed ;
- browser test « a large captured history renders a page at a time… ».

**Navigation.** The first page opened by a link from another site answered « Requête intersite refusée ».
- A top-level navigation to a page is now allowed, following the Fetch Metadata policy.
- The API keeps refusing every cross-site request.
- Test: `test_a_link_from_another_site_opens_the_page_but_never_the_api`.

## 5. Final state of the memory

The figures were counted on disk, from the sources of each entry.

**Totals:** 31 projects, 26 363 proposals.

| Origin | Proposals |
|---|---|
| Codex history | 15 824 |
| claude-tap | 6 014 |
| native transcripts | 4 435 |
| session sheets | 90 |

**Largest projects:**

| Project | Folder | Proposals | Origin |
|---|---|---|---|
| test_memoire | `E:\test_memoire` | 9 230 | tap 6 005, native 3 149, sheets 76 |
| wecare_site | `E:\wecare\wecare_site` | 4 889 | Codex |
| sci-wecare | `E:\wecare\sci-wecare` | 2 384 | Codex |
| module_estimation | `E:\module_estimation` | 2 062 | Codex |
| ceyna-tests | `C:\MAESTRO\TEST\ceyna-tests\ceyna-tests` | 1 609 | Codex |
| veille_concurent | `E:\CEYNA\veille_concurent` | 1 317 | Codex |
| time manager | `E:\epitech_project\time_manager\T-DEV-700-MAR-7-1-time_manager-8` | 1 287 | native 1 265, sheets 13, tap 9 |

Each project is attached to the folder its sessions declare (cwd), proven by the native session id or the Codex thread. No project was created by name similarity or by recency.

### Sessions left pending (56)

None of them is attached by guesswork.

| Reason | Sessions | Explanation |
|---|---|---|
| `outside_roots` | 49 | Claude Code launched in temporary test folders (`AppData\Local\Temp\filigree-*`), outside the allowed roots, so not attaching them is correct |
| `ambiguous_native_session` | 6 | Codex rollouts without a usable session identifier |
| `cwd_missing` | 1 | folder deleted since the session |

## 6. Not covered, or left to the user

- **The 51 pruned claude-tap sessions** sit in the recovered database until the user restores them.
  - The native transcripts cover their content wherever those transcripts still exist.
  - After the restore, a new `filigree backfill` (agent stopped) replays them.
- **Claude Desktop (chat)** is not captured: no local transcript.
- **Refused by the Claude Code safeguard**, to be done by the user through the copy-paste commands of the final message:
  - autostart (`filigree service install`) ;
  - the PowerShell profile that routes `claude` and `codex` through `claude-tap --tap-max-traces 0` ;
  - MCP registration with Claude and Codex ;
  - the hooks.
- **Usefulness of the volume.** Each message or tool call is one proposal, so the « À examiner » queue is a stream of raw traces.
  - A distillation (episode sheets, decisions, tickets) is proposed but not decided; see the open question in the final message.

## Verification

- `python -m unittest discover -s tests`: 430 tests OK (1 skipped).
- `node --check filigree/static/app.js`: OK.
- `npm test`: 30 passed, the new paging test included.
- CI de la PR #1 (commit `7530151`) : verte sur Windows, Linux et macOS (Python 3.11 et 3.14) et en navigateur. Deux tests de `import-codex-history` ne passaient que sous Windows (préfixe `\?\` ajouté sur tous les systèmes ; marqueur « private » présent dans le dossier temporaire de macOS) : corrigés.
