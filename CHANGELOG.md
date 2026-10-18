# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [semantic versioning](https://semver.org/).

## [Unreleased]

### Added
- `filigree backfill [--dry-run]`: an explicit, user-requested catch-up of the history that capture and the activity observer skip by design (ADR-0003 D11, amended 2026-10-18). With the agent and the capture stopped, it rewinds the claude-tap cursors, the native-transcript offsets and the activity offsets; the next cycles replay the history through the same code paths as live activity, so a record is attached only when its native session id resolves to a transcript folder, and goes pending otherwise. claude-tap is replayed first, before any native transcript is read; items already in memory from the other channel are not imported a second time; and a rerun creates no duplicates. Past pauses left no durable record and are re-read, except pause intervals the capture still holds. `--dry-run` reports the counts and changes nothing.

- `filigree import-codex-history [--dry-run] [--thread ID] [--since DATE]`: reads Codex 0.16x thread history (`thread_history_N.sqlite`), which survives the deletion of old rollout files, and files it as proposals. The folder is the cwd Codex recorded in `state_N.sqlite`, resolved by the capture's own rules (allowed roots, exclusions, generic folders, deepest project, worktree, `auto_create`); an unprovable thread is skipped and counted with its reason, and a thread whose rollout still exists is left to the live capture. Commands keep their program name only, file changes their file names only, tool calls their name and status; reasoning is never read. Source uris `codex-thread:<thread>:<item>` make reruns idempotent; text already captured live is not proposed twice. No session sheet is written (they derive from the activity journal).

### Fixed
- Capture now sends again the events that the memory store declined to process in one call (5000 events or 5 MB cap) instead of dropping them silently.

## [0.2.0] — 2026-10-17

The permanent local observer ([ADR-0003](.aiwg/architecture/ADR-0003-permanent-observer.md)).

### Added
- `filigree agent`: one background process per data folder that serves the workbench, runs capture and the activity journal, and announces itself in `.runtime/agent.json`. `filigree serve` hands over to a running agent.
- Per-project activity journal `projects/<id>/.filigree/activity.sqlite`. Events are prompts, file changes, commands (program name only), tests, errors and commits, extracted deterministically from Claude Code and Codex transcripts. Retention is 90 days, and the journal never goes into Git checkpoints or exports.
- Session sheets: one proposal per session after 10 idle minutes or a session-end signal. A sheet is revised while it is proposed; once it has been reviewed, new activity becomes a separate "suite" proposal.
- **Activité** view in the workbench, plus `GET /api/projects/<id>/activity` and `filigree activity`.
- Read-only collectors for Claude Code, Claude Desktop (metadata only), Codex state and Codex rollouts, plus claude-tap. `filigree probe` reports counts and field names only.
- `filigree setup --root DIR`: allowed roots (`allowed_roots` in `capture.json`). A session outside them stays pending as `outside_roots`.
- A linked git worktree whose link is proven both ways joins its main repository's project.
- `filigree service install|uninstall|status`: start at login, per user, through the HKCU Run key, a LaunchAgent or a systemd user unit.
- `filigree hooks install|uninstall|status --client claude|codex`, with `--dry-run`, a timestamped backup and an install log. The `--inject` option adds accepted knowledge only.
- MCP tools `project_activity` and `active_sessions`, plus the `accepted_only` option for `get_handoff`.
- `filigree import-export FILE --project ID` for ChatGPT and claude.ai exports (`.json` or `.zip`).
- `filigree status`: what is installed and running, and the artifacts in the data folder.
- MCP scope from the client's **roots** (`roots/list`). Claude Code does not start MCP servers in the session folder; this was verified live.
- `filigree mcp-config --client claude-desktop`, `--project-folder`, `--all-projects`, and `--command`, which prints the one-line `claude mcp add` / `codex mcp add` command.
- French documentation in `docs/guide/`: a quick start for each application, a complete guide illustrated with real screenshots, and explanatory diagrams (`scripts/guide_diagrams.py`).

### Changed
- **The local key is now required on every `/api/*` route, reads included.** The key persists in `.runtime/agent.key` and is shared by all servers of one data folder. `GET /api/bootstrap` no longer lists projects. Scripts that read the API must send `X-Filigree-Token` (get it from `/api/bootstrap`).
- **`filigree mcp` is scoped to one project:** the projects of the client's MCP roots, otherwise that of its working directory. Use `--project-folder DIR` or `--all-projects` to set the scope explicitly.
- `capture.json` gains an `activity` section (`enabled`, `retention_days`, `turn_proposals`). Setting `turn_proposals: false` stops the v0.1 per-turn proposals.
- CI also runs on macOS.

### Security
- Command lines are never stored, and summaries are redacted before they are cut.
- A corrupt key file is refused rather than replaced.
- Hooks never overwrite invalid settings or an existing Codex `notify`.

## [0.1.0] — 2026-10-16

First release: a local Markdown memory with human review, a workbench, the CLI, MCP stdio, explicit imports and automatic capture from claude-tap and native transcripts.
