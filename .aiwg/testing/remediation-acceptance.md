# Acceptance for the remediation cycle

This is a test specification, not an execution report. It supplements the independent Sonnet findings of 16 October 2026. Publication remains blocked until the executed evidence is reviewed.

| Area | Required observable evidence |
| --- | --- |
| Secrets (A6/B1/E1) | Synthetic multiline JSON/env assignments, quoted values, URL credentials, Basic auth and known token patterns never appear in current/history/export/handoff/UI. Ordinary prose and provenance structure remain usable. Redaction remains explicitly heuristic. |
| Disabled capture (C4/D12) | In a real --no-capture server, status and every control cannot probe/open native/TAP sources or start a monitor. A source-access trap and a subprocess test both pass. |
| Recall (E2) | A real first client writes a decision, capture proposes it, a person-equivalent browser action accepts it, and a fresh MCP reader retrieves the choice, reason and ID from a paraphrased question without receiving the answer in its prompt. Filters cannot silently imply no current decisions. |
| Capture resilience (B2–7) | User text after injected context remains; hidden reasoning remains excluded. An invalid/long session cannot starve a valid second session. Malformed lines are observable. File links have honest results. Generic system/temp ancestors cannot merge independent projects. |
| Storage (A3/4/8) | One corrupt project or unrelated file cannot disable healthy projects. Damaged history is rejected clearly. Extended Windows path aliases resolve to one folder. Replacing proposed/rejected entries is atomic and cannot approve them indirectly. |
| Imports (A1/2/7) | Long bounded input is handled without a permanent watch retry loop. Repeated legitimate occurrences survive, while rescanning the same source is idempotent. Errors/truncation are explicit and indexed. |
| Performance (A5) | Report actual 3000-entry read/write/export timings. Verify caches notice external edits and another process's commits, and cannot return mutable shared internal state to callers. |
| Windows services (C1–3) | Raw UTF-8 stdin/out round trip including accents/emoji; generated TOML parses and launches from a different cwd; second server on same port fails while first stays usable. |
| UI (D1–7) | Real browser assertions plus inspected screenshots: incoming relations, detail refresh after replacement, recoverable edit conflict, accent search, 375px reachability, background project discovery, accurate native provenance, Escape draft confirmation. |
| Remaining P3 | Each confirmed P3 has a result or an explicit independently reviewed disposition. Neither human-sounding names nor possession of a local HTTP token is represented as authenticated human identity. Invalid intervals/budgets/JSON have bounded errors. |

Regression suites, package installation and the three bounded live helpers are additional requirements. They do not replace the fresh-reader E2E scenario or exploratory UI checks. Evidence must give commands, actual results, synthetic source boundaries and residual limitations. No claim of real Codex coverage without a real Codex run.
