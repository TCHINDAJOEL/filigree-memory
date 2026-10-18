# Contributing to Filigree

Keep the central promise testable: preserve the difference between a suggestion, an accepted decision, an observation and a historical alternative.

Python 3.11+ is enough for the app and core tests. Node 20+ is needed only for browser tests.

```sh
python -m unittest discover -s tests -v
npm ci
npx playwright install chromium
npm test
```

Use synthetic fixtures. Never commit real transcripts, provider tokens, `.runtime`, `.traces`, or personal project memory. Runtime code belongs in `filigree/`, behavioral tests in `tests/`, and design/verification records in `.aiwg/`.

Before changing storage, document compatibility and recovery. Before extending a trace adapter, add a representative synthetic fixture and explain which upstream format it supports. Never silently promote imported content to accepted knowledge. Keep all UI text escaped; raw Markdown is not rendered as HTML.

Collectors, hooks and the autostart service must stay testable without the real HOME, registry or agent data: pass `env`/`home` or an injectable runner, as the existing tests do. A new collector reads metadata only, read-only and bounded, and becomes a visible `unsupported` source when its format is not recognised (ADR-0003 D14).

Submit small pull requests explaining the user-visible problem, the new behavior, tests actually run and limitations. Feedback on real workflows is more useful than expanding the stack before a measured need.

### Project map

| Path | Role |
| --- | --- |
| `filigree/store.py` | Single writer of the Markdown memory (entries, history, events, lock) |
| `filigree/capture.py`, `tap_source.py`, `native_index.py` | v0.1 per-turn capture from claude-tap and native transcripts |
| `filigree/collectors/`, `resolver.py`, `probe.py` | Read-only session discovery and folder rules |
| `filigree/extract.py`, `activity.py`, `distill.py` | Activity journal and session sheets |
| `filigree/agent.py`, `service.py`, `hooks.py` | Daemon, optional autostart, optional hooks |
| `filigree/server.py`, `static/` | Loopback API and workbench |
| `filigree/mcp.py` | MCP stdio tools (scoped, no approval) |
| `filigree/importers.py`, `chat_export.py` | Explicit imports |
