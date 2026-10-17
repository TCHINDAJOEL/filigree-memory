# Pending commit log — portable button target

## Summary
Keep the add-project button above the minimum clickable size across font platforms.

## Why
Linux Chromium measured 23.6875px at a 768px viewport; the existing accessibility regression requires at least 24px.

## What Changed
- Give the desktop/tablet sidebar add button a 28px minimum target and prevent shrinking.
- Preserve existing mobile layout and every browser assertion.
- Record the author diagnosis, independent local execution and refreshed synthetic screenshot; archive initial commit log.

## How
A single CSS rule defines minimum dimensions and centers the glyph independently of platform font metrics. No memory, capture, MCP or agent configuration changes.

## Files Changed
filigree/static/styles.css
.github/assets/workbench.png
.aiwg/testing/ci-button-correction.md
.aiwg/testing/ci-button-verification.md
.aiwg/commits/c08a7bf.md
.aiwg/commits/pending-commit-log.md

## Tests
Independent Sonnet execution: all 28 Playwright tests passed, wheel rebuilt and isolated package check printed PASS. Evidence: .aiwg/testing/ci-button-verification.md. Initial GitHub run38971518619 passed all four Windows/Linux Python3.11/3.14 jobs; Linux browser rerun required after push. Core unchanged since the 301-test local run and five successful real Claude calls. Root reviewed CSS diff: the min-width651 media rule also applies at1440; the author's wording that1440isunchanged is imprecise, but the three viewport tests passed. No thresholds weakened.

## Risk
Low: CSS target grows by four pixels; full browser suite covers overlap and reachable controls. Linux result remains to be confirmed remotely.

## Rollback Plan
Run `git revert --no-edit HEAD` while this correction is HEAD, then push; this restores the font-dependent target and will reintroduce the Linux test failure. It does not touch personal memory.

## Related Decisions
.aiwg/architecture/ADR-0001-local-portable-memory.md.

## Related Sessions
.aiwg/testing/ci-button-correction.md; .aiwg/testing/ci-button-verification.md; .aiwg/testing/release-execution.md.

## Commit Message Proposal
fix(ui): keep project button target independent of font metrics
