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

Submit small pull requests explaining the user-visible problem, the new behavior, tests actually run and limitations. Version 0.1 is an early local application: feedback on real workflows is more useful than expanding the stack before a measured need.
