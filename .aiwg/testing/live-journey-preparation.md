# Live journey — preparation of the real E2E helper

This documents a helper that is **prepared, not run live**. No model call has been made. A passing `--check-only` is plumbing evidence on a synthetic fixture and is **not** a live PASS. The live run must be executed separately, after the product fixes (R1–R9) are integrated and with the user's authorization. Status: **no GO claimed**.

## Files

| File | Role |
| --- | --- |
| `scripts/verify_live_journey.py` | Orchestrator (stdlib Python): isolation, writer, capture, server, reader, verdict. |
| `scripts/live_journey_browser.cjs` | Real Playwright Chromium actions (existing development dependency; nothing installed). |
| `tests/test_live_journey_helper.py` | Helper-only dry-run tests (no model, browser or server). |

No file under `filigree/`, no existing test or other helper was modified. The orchestrator imports `Failure`, `check`, `precondition`, `inside`, `git_root`, `create_baseline_db`, `isolated_capture`, `find_transcript`, `copy_metadata` and `verify` from `scripts/verify_live_capture.py` (read-only reuse of the exact-session-id copy and the tap↔native provenance assertions). A later change to those functions changes this helper's behaviour.

## Exact future command

```sh
python -X utf8 scripts/verify_live_journey.py --check-only
python -X utf8 scripts/verify_live_journey.py                 # default model: sonnet
python -X utf8 scripts/verify_live_journey.py --model haiku   # optional model alias for both clients
```

Exit codes: 0 pass, 1 assertion failed, 2 precondition/isolation missing, 3 a live call failed. All output goes under `.runtime/live-journey/<UTC stamp>/` (`debug.json`, `logs/`, `shots/`, `browser-*.json`, `memory/`, `tap/`, `tap-reader/`); nothing is deleted. Standalone commands only; there is no compound shell.

## Limits (enforced in code)

- At most **2** `claude-tap` invocations (one writer, one reader), **300 s each, no retry**; a call budget guard and an `allow_model` guard refuse any further call (unit-tested with `Popen` mocked). `--check-only` sets `allow_model = False`.
- Browser step ≤ 240 s, server start wait ≤ 20 s, every wait is bounded.
- Cleanup is limited to the server and browser processes this script started (process-tree kill of its own PID). User data and evidence are never deleted.
- No installs, no commits, no write to any user agent configuration. No user transcript or history is scanned; only `<returned session id>.jsonl` is looked up by exact name, and for the writer only `sessionId`/`cwd` are copied into the isolated native root.
- `agentC/data` and the real claude-tap database are never touched: the TAP databases (writer and reader, separate), the memory, the native Claude and Codex roots and a synthetic `HOME` are all explicit paths under `.runtime/live-journey/<stamp>/`, asserted before anything starts. The server runs with `--no-capture`, and `/api/capture` must report `disabled_by_server` with no source roots before the browser opens.

## Journey and what each stage asserts

1. **Writer** (`claude-tap`, new `filigree-journey-*` folder outside any Git root): `--tools ""`, `--setting-sources ""`, `disableAllHooks`, `--disable-slash-commands`, `--strict-mcp-config` with no MCP file. The prompt states the decision (SQLite instead of Postgres: single-user, offline, under 50 MB, no server to operate) with a random codename and five harmless fake secrets (`DB_PASSWORD=`, URL credentials, `Authorization: Basic`, `X_API_KEY=`, a quoted multi-word `"password"`).
2. **Capture** (in-process, isolated env): exact tap session claiming the returned native id, project auto-created for the writer's folder, all entries `proposed`, no accepted entry before review (nothing is seeded), provenance and tags, idempotent rescans, and no raw fake credential in any memory file.
3. **Browser review** (`review` mode): select the project, locate the chosen proposal by its entry id in the list (user-text proposal containing the codename and SQLite, else assistant text), check visible provenance (card, origin, session id, folder, "non authentifiées"), convert to *Décision* through *Modifier* when its kind differs, accept through *Accepter* with an explicit reason, screenshots at each step. Python then checks status/kind, the reason in the event journal on the `http-ui` channel, that no other entry changed, and that the handoff lists the entry as `current`.
4. **Reader** (`claude-tap`, separate TAP database, own empty folder): `--strict-mcp-config --mcp-config <temporary file>` for the Filigree MCP server on the isolated memory, `--tools ""`, `--allowedTools` limited to `list_projects`, `project_for_folder`, `search_memory`, `get_handoff`, `--permission-mode dontAsk`, no `--safe-mode`. The prompt is the question "What was our database choice and why?" plus the project folder and a JSON-shape request. It is asserted to contain no answer, no codename and no note id. The reply must be JSON with `choice`, `reason`, `note_id`; the verdict requires SQLite (not Postgres), at least two of four reason groups, and the **exact** accepted note id.
5. **Observed behaviour**: tool calls are counted as unique `tool_use` ids from the reader's TAP history (repeated history blocks are not counted); only allowed read tools may appear and `propose_memory` must not; the accepted note id must appear in at least one `search_memory`/`get_handoff` tool result. If it never does, the run fails with the count of content calls that returned without it — the false-empty behaviour is therefore judged on a real client, not on transport. The memory (entry statuses/revisions and a digest of every file except `.capture` and lock files) must be unchanged by the reader. No answer or note id is injected into the reader.
6. **Leak scan**: raw fake values (and the Base64 blob) are searched in every memory file, entries, history, export, handoff (with and without a query) and in the text of every UI view plus the accepted sheet. Only labels and counts are reported, never values.

Reported facts: requested model, models announced by Claude (`modelUsage`) and seen in TAP request bodies, call count, per-stage timings, unique tool calls by name, screenshots (private paths).

## Check-only plumbing (what it proves)

It uses one synthetic proposal shaped like a tap capture (kind *observation*, to exercise the convert path), and verifies isolation (all roots inside the work folder, baselines on empty databases, native roots), the MCP file, flags and prompts, the `--no-capture` server's disabled status, and the real browser review + scan with the resulting store. It does **not** exercise a model, the real capture of a Claude transcript, the real reader or the real redaction on model-echoed text.

## Executed results (this preparation, 16 Oct 2026)

| Command | Result |
| --- | --- |
| `python -X utf8 scripts/verify_live_journey.py --check-only` | Exit 0 after fixing one wrong assertion of mine (reason is in the event journal, not in the history snapshot). 0 Claude calls; review ≈ 5 s, scan ≈ 6 s; 9 scans, 0 leaks; entry 1→3 revisions (converted then accepted through the interface), handoff current; server process no longer running afterwards. Screenshot of the provenance sheet inspected. |
| `python -X utf8 -m unittest discover -s tests -p test_live_journey_helper.py -v` | 8 tests, OK. |
| `node --check scripts/live_journey_browser.cjs` | Exit 0. |

## Known limitations and risks for the executor

- The first live run may expose helper defects that no check-only can: the writer's prompt could be refused or paraphrased by the model, the captured proposal selection assumes a `user-text` or `assistant-text` entry containing the codename and "SQLite", and `Authorization: Basic` or URL-credential lines may make the model comment on credentials (the prompt asks it not to repeat them).
- `claude-tap` resolved through a `.cmd`/`.bat` shim would be parsed by `cmd.exe`: prompts are asserted free of `& | < > % ^` and newlines, and `claude_tap_suffix` is recorded in `debug.json`.
- The reason check is lexical (four groups of synonyms), so a correct but unusual paraphrase can fail; the failure is then reported as an assertion, not retried.
- Server-sent-event TAP records are not specifically tested; tool blocks are read from request histories, which carry earlier tool use. The reader's last tool-use block is visible only if a later request carries it (normally true because the answer follows the tool result).
- The helper reflects the product APIs as read on 16 Oct 2026 (`/api/projects/<id>/handoff` `references[].current`, `/api/capture` `disabled_by_server`, event journal `reason`/`channel`). Another builder was changing the product concurrently; re-run `--check-only` after integration before the live run.
- Real Codex is not covered. Possession of the local token or a human-sounding name is not treated as authenticated identity.
