# Release gate — Filigree 0.1.0

Date: 16 October 2026. Synthesizer: Codex orchestrator. Decision: **GO for initial source publication**, with remote CI still to be checked after push. This replaces the suspended gate; the earlier failed reviews remain historical evidence, not release approvals.

## Author, independent reviewers, synthesis

Sonnet builders corrected the independent exploratory findings. Separate Sonnet execution covered the browser, storage probes and 3000-entry benchmark. Opus reviewed final code and evidence in [release-review-retake.md](../testing/release-review-retake.md), identifying five concrete prerequisites. Sonnet then executed the frozen-source checks in [release-execution.md](../testing/release-execution.md). Codex checked those results against every prerequisite and inspected the successful journey's private diagnostic status (exit 0, two calls, no failure). Raw logs and synthetic trace databases remain local.

| Opus prerequisite | Closing evidence |
| --- | --- |
| Full Python and browser on frozen source | 301 Python tests run, OK with one POSIX-only skip on Windows; 28 Playwright passed |
| Fresh distribution | Wheel built after source changes; isolated installation, CLI, packaged resources and HTTP bootstrap PASS |
| Complete real same-project journey | Two distinct Sonnet sessions: tool-less writer → exact-folder capture → proposed entry → browser review/acceptance → fresh read-only MCP retrieval; exact note/decision/reason, unchanged memory, persisted and browser fake-secret scans all reached and passed |
| Revalidate earlier real-client claims | TAP capture, native direct capture, and current/historical MCP handoff each passed with one Haiku client; five total calls in this final assignment, no retry |
| Accurate documentation | README reflects auxiliary proposals, best-effort redaction, measured performance, native transcript hygiene, and synthetic-only Codex coverage |

The published software does not require Claude, claude-tap, Node or Playwright to run its memory workbench. Those tools participate in optional capture, integration or development workflows. Capture requires a running monitor and exact local folder attribution; recall requires explicit MCP configuration. Nothing imported or captured auto-approves itself.

## Traceability and accepted limits

[Remediation acceptance](../testing/remediation-acceptance.md), [independent probes](../testing/probes-independent-retake.md), [privacy fixes](../testing/privacy-retake.md), [final integration fixes](../testing/remediation-final-corrections.md) and the Opus review map the confirmed A–E/R1–R9 findings to regressions or explicit dispositions. Secret masking is heuristic, not a confidentiality guarantee. Local UI tokens and actor labels are not human authentication. Source identifiers remain declarations. No actual Codex-client compatibility or Claude Desktop/web interception is claimed.

On one Windows machine, importing 3000 entries took about 65 seconds and a cold handoff about 2.8 seconds. Sequential entry creation exceeded the 180-second setup budget at 1586 entries; an isolated 14-second handoff outlier was not explained. These are disclosed limits, not a performance SLA. Windows extended-length aliases and services ran in the suite; UNC, junction, 8.3-name variants and the optional startup installer have no dedicated executed acceptance evidence. Startup installation was not performed. The live answer judge's optional wording refinement is deferred as Opus allowed; exact entry ID, reason and observed retrieval remain required.

## Publication controls

Only source, synthetic fixtures, documentation and review evidence are eligible. Runtime folders, traces, real conversations, personal memories, credentials and local task/checkpoint files are excluded. No diagnostic data belonging to other projects is included. Remote CI results will be recorded below after publication; local success does not imply CI success.

## Published CI closure — 17 October 2026

**GO confirmed.** Public repository: https://github.com/TCHINDAJOEL/filigree-memory.

The initial CI found a Linux font-metric issue: the add-project button measured 23.6875px instead of the required minimum24px at768px. Sonnet fixed the CSS to use a28px minimum without changing test thresholds; independent local execution again passed all28browser tests and rebuilt/installed the wheel. Evidence: [correction](../testing/ci-button-correction.md) and [verification](../testing/ci-button-verification.md).

[GitHub Actions run38995801705](https://github.com/TCHINDAJOEL/filigree-memory/actions/runs/38995801705) completed **success** for source commit `a61c377a6d8f9db92938cc89fc90e3b9ce884ad9`:
- Python3.11 and3.14 on Ubuntu: success.
- Python3.11 and3.14 on Windows: success.
- Chromium/Playwright on Ubuntu: success.

The final evidence commit changes documentation only; the released runtime and tests are identical to that CI-tested source. The wheel contains21package/metadata files and no runtime memory or trace directories; SHA256 `2cf7bc14ac8b022b0e86ae4ad7a1e57880b6ce7d549b924f6329e5b1d3091181`.
