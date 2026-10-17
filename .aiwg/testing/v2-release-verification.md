# V2 (0.2.0) — local verification before publication

Date: October 17, 2026. Executed by: orchestrator (Opus), on a Windows 10 workstation with Python 3.14 and Node 22. Reference: [ADR-0003](../architecture/ADR-0003-permanent-observer.md). Earlier increments: [v2-1-resolution-auth.md](v2-1-resolution-auth.md).

## Scope verified

| Area | Commit(s) | Module(s) |
| --- | --- | --- |
| Collectors, probe, resolution, local key | `136d391`, `c7c68b9`, `587edff` | `collectors/`, `probe.py`, `resolver.py`, `server.py` |
| Activity journal and session sheets | `d5bfecf` | `extract.py`, `activity.py`, `distill.py`, `capture.py` (`activity` settings) |
| Daemon, autostart, hooks, scoped MCP, chat exports, CLI | `5d811fe` | `agent.py`, `service.py`, `hooks.py`, `mcp.py`, `chat_export.py`, `cli.py` |
| Activité view | `052fd8d` | `static/` |
| Documentation, 0.2.0, CI, e2e script | release commit | `README.md`, `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md`, `pyproject.toml`, `ci.yml`, `scripts/` |

## Commands executed and actual results (final state, before the release commit)

| Command | Result |
| --- | --- |
| `python -m unittest discover -s tests` | **360 tests OK**, 1 skipped (POSIX only) |
| `node --check filigree/static/app.js` | OK |
| `npm test` (Playwright, Chromium) | **29 passed** (1.7 min), including `activity.spec.cjs` |
| `python -m pip wheel . --no-deps --wheel-dir .runtime/wheels` | OK |
| `python scripts/verify_package.py` | PASS: isolated install, version 0.2.0, v0.2 modules importable, HTML/JS served, bootstrap |
| `python scripts/verify_agent_e2e.py` | PASS: a real `filigree agent` process, 2 journaled events, one *proposed* session sheet, `status` reports the agent and the journal, and `serve` hands over to the running agent |
| `filigree probe` (this workstation, read-only) | 5 sources `ok`; 314 sessions, all with a `cwd` (counts only) |

Playwright regenerates `.github/assets/workbench.png`. The file was restored after each run and is not committed.

## Tests added in V2 (synthetic data only)

- `test_v2_collectors.py`: collectors and probe.
- `test_capture.AllowedRootsAndWorktreeTests` (6) and `test_http` (3): allowed roots, worktrees, local key.
- `test_v2_activity.py` (14):
  - extraction: kinds, files, tests, commits; no command line, no reasoning, nothing injected; redaction happens before the cut;
  - observer: no catch-up and deduplication on replay; no project, outside the roots, paused or disabled ⇒ nothing journaled; journal outside Git;
  - journal: overlaps, retention, newer schema refused, malformed settings;
  - sheets: wait for idle, revision while proposed, "suite" after review, `session_end` signal.
- `test_v2_services.py` (16):
  - agent: one per folder, local key, `serve` hands over, stale announcement ignored;
  - autostart plans for Windows, macOS and Linux through a fake runner;
  - Claude hooks: backup, idempotence, clean uninstall, invalid JSON left intact;
  - Codex hooks: an existing `notify` is refused;
  - `signal`: under 1 s, ids only, injection of accepted knowledge only;
  - MCP: scope, activity tools, `accepted_only`;
  - ChatGPT exports (current branch, redaction) and claude.ai `.zip` exports (idempotent);
  - CLI `setup` and `activity`.
- `tests/browser/activity.spec.cjs`: events, active sessions, overlaps, inert hostile text, 375 px.

## Behavior changes (documented in CHANGELOG)

- The local key is required on all `/api/*` routes, reads included; `/api/bootstrap` no longer lists projects.
- `filigree mcp` is scoped to the project of its working directory (`--project-folder`, `--all-projects`). `scripts/verify_live_handoff.py` now passes `--project-folder` explicitly.

## Not executed, remaining limits

- **No live call** (`verify_live_capture.py`, `verify_live_handoff.py`): they need the user's explicit authorization.
- **No real hook installation** on this workstation, and **no real autostart installation**: only `status` was read.
- macOS and Linux: autostart plans tested synthetically. The CI matrix now includes `macos-latest`, but **it has not run yet**; to be confirmed at the first push.
- Codex: compressed `.zst` rollouts are not read; the `notify` signal does not mark the end of a session (the 10 idle minutes apply).
- Claude Desktop: metadata only.
- On Windows, `agent.key` inherits the ACLs of its folder.
- The journal cannot be rebuilt after the agents purge their transcripts.
- **No independent review** of the V2 code (AGENTS.md requires one for substantial changes): to be scheduled before merging into `main`.
- The D1 amendment to `AGENTS.md` (hooks are now opt-in) remains a human decision; the file was not modified.
