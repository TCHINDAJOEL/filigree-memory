# Pending commit log — initial release

## Summary
Deliver Filigree 0.1.0, a local folder-bound shared project memory with a review workbench and MCP.

## Why
Keep decisions, their sources and historical alternatives available when people or coding agents resume a project.

## What Changed
- Portable revisioned memory, explicit proposal review, graph/history and bounded handoff.
- Exact-folder TAP/native capture, source isolation, resilient imports and heuristic secret masking.
- Local HTTP interface, read/propose MCP, project Git checkpoints and optional monitor startup scripts.
- Synthetic regressions, actual Playwright journeys, isolated real Claude integration helpers, CI and documentation.

## How
Python standard library runtime and static browser UI; development-only Playwright. AIWG author/reviewer/synthesis artifacts record the architecture, corrective iterations and executed acceptance.

## Files Changed
.aiwg/architecture/ADR-0001-local-portable-memory.md
.aiwg/architecture/ADR-0002-automatic-project-capture.md
.aiwg/architecture/claude-tap-integration.md
.aiwg/architecture/tap-source-study.md
.aiwg/deployment/release-gate.md
.aiwg/deployment/user-guide.md
.aiwg/planning/delivery-plan.md
.aiwg/planning/integration-findings.md
.aiwg/requirements/automatic-capture.md
.aiwg/requirements/user-stories.md
.aiwg/requirements/vision.md
.aiwg/testing/capture-acceptance.md
.aiwg/testing/final-fixes.md
.aiwg/testing/final-verification.md
.aiwg/testing/followup-capture-2026-10-16.md
.aiwg/testing/independent-verification-2026-10-16.md
.aiwg/testing/live-independent-retake.md
.aiwg/testing/live-journey-preparation.md
.aiwg/testing/privacy-retake.md
.aiwg/testing/probes-independent-retake.md
.aiwg/testing/release-execution.md
.aiwg/testing/release-review-retake.md
.aiwg/testing/release-review.md
.aiwg/testing/remediation-acceptance.md
.aiwg/testing/remediation-capture.md
.aiwg/testing/remediation-final-corrections.md
.aiwg/testing/remediation-integration.md
.aiwg/testing/remediation-opus-fixes.md
.aiwg/testing/remediation-opus-risk.md
.aiwg/testing/remediation-runner.md
.aiwg/testing/remediation-services.md
.aiwg/testing/remediation-store.md
.aiwg/testing/remediation-ui.md
.aiwg/testing/review-capture-opus.md
.aiwg/testing/review-capture-orchestrator.md
.aiwg/testing/review-domain.md
.aiwg/testing/review-interface.md
.aiwg/testing/review-product.md
.aiwg/testing/review-synthesis.md
.aiwg/testing/same-project-live-retake.md
.aiwg/testing/toolless-capture-correction.md
.aiwg/testing/verification.md
.github/ISSUE_TEMPLATE/bug_report.md
.github/assets/workbench.png
.github/pull_request_template.md
.github/workflows/ci.yml
.gitignore
AGENTS.md
CONTRIBUTING.md
LICENSE
README.md
SECURITY.md
examples/capture.json
examples/events.jsonl
examples/mcp.json
examples/tap-export.json
filigree/__init__.py
filigree/__main__.py
filigree/capture.py
filigree/cli.py
filigree/demo.py
filigree/git_sync.py
filigree/importers.py
filigree/mcp.py
filigree/native_index.py
filigree/server.py
filigree/static/app.js
filigree/static/index.html
filigree/static/styles.css
filigree/store.py
filigree/tap_source.py
package-lock.json
package.json
playwright.config.cjs
pyproject.toml
scripts/claude_runner.py
scripts/install-capture-startup.ps1
scripts/live_journey_browser.cjs
scripts/resume-claude.ps1
scripts/uninstall-capture-startup.ps1
scripts/verify_live_capture.py
scripts/verify_live_handoff.py
scripts/verify_live_journey.py
scripts/verify_package.py
tests/browser/final.spec.cjs
tests/browser/remediation.spec.cjs
tests/browser/workbench.spec.cjs
tests/tap_fixtures.py
tests/test_adapters.py
tests/test_capture.py
tests/test_folders.py
tests/test_http.py
tests/test_live_journey_helper.py
tests/test_privacy_retake.py
tests/test_remediation_capture.py
tests/test_remediation_final.py
tests/test_remediation_opus.py
tests/test_remediation_services.py
tests/test_remediation_store.py
tests/test_runner.py
tests/test_store.py
.aiwg/commits/pending-commit-log.md

## Tests
301 Python tests run, OK with one POSIX-only skip on Windows; 28 Playwright passed; JS syntax, wheel build and isolated installation PASS. Real same-project fresh-reader journey and three capture/handoff helpers PASS, five bounded model calls. Evidence: .aiwg/testing/release-execution.md; independent review: .aiwg/testing/release-review-retake.md; synthesis: .aiwg/deployment/release-gate.md. Staged diff whitespace checked. Index audit excludes runtime/traces/private memory/task files; four credential-shaped findings are deliberate synthetic test fixtures, reviewed. Remote CI is pending the initial push.

## Risk
Medium: capture relies on evolving local client formats and best-effort secret masking. Codex is fixture-tested only; optional startup scripts are not exercised. Folder identity and explicit acceptance limit accidental promotion, not all sensitive content.

## Rollback Plan
For an immediate reversal while this initial release is HEAD, run `git revert --no-edit HEAD` and push the resulting revert. This removes tracked software, not ignored local memory/traces; it does not erase already published history. For a later reversal, select this initial release SHA explicitly. Never delete personal memory as rollback.

## Related Decisions
.aiwg/architecture/ADR-0001-local-portable-memory.md; .aiwg/architecture/ADR-0002-automatic-project-capture.md.

## Related Sessions
.aiwg/testing/release-execution.md; .aiwg/testing/probes-independent-retake.md; .aiwg/testing/release-review-retake.md. Raw sessions remain private.

## Commit Message Proposal
feat: release local project memory workbench

Refs: ADR-0001, ADR-0002
