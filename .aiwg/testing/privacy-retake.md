# Privacy retake: targeted redaction hardening (Sonnet, final)

Date: 2026-10-16. Synthetic data only. No live call, browser, wheel, commit or push. TAP/helper files untouched. Model completion is not objective evidence: independent Opus review still required.

## Changes
- `filigree/store.py` `_URL_CREDENTIALS`: second branch masks `scheme://user:pass/with/slash@host`. The password part is bounded to 128 chars, excludes whitespace, quotes, `?`, `#`, `@`. It is skipped when the text after the colon looks like `port/` (`host:8080/@name` stays).
- `filigree/store.py` `_SECRET_PATTERNS`: distinctive prefixes (`sk-ant-`, `sk-proj-`, `ghp_/gho_/ghu_/ghs_/ghr_`, `github_pat_`, `glpat-`, `xox?-`, `whsec_`) no longer need a word boundary, so they are masked when glued to preceding word characters. Generic shapes (`sk-…`, `AKIA…`, `npm_`, `hf_`, `eyJ…`, etc.) keep the boundary, so prose like `risk-assessment-framework` is not touched.
- `tests/test_privacy_retake.py` (new, 4 tests): glued tokens, raw-slash URL (including idempotence), benign prose/links unchanged, and persisted files (current, history, events), export and handoff free of fake fragments while safe prose and host stay.
- `tests/test_remediation_opus.py:156`: the old assertion that a raw-slash password is NOT masked asserted the gap now closed; flipped to `assertNotIn`.

## Evidence (actual)
- Pre-fix reproduction (old regexes evaluated inline, not by running the new test file against old code): `qqqqghp_…` not matched; `postgres://admin:pa55/Zq7@db.test/app` unchanged. I did not run the new tests against the old code.
- `test_privacy_retake.py`: Ran 4, OK.
- Full `unittest discover -s tests`: first run 298 tests, 1 failure (`test_r6_documented_limits_remain`, the stale assertion above), 1 skipped. After the fix, `test_remediation_opus.py` re-run: 35 OK. I did NOT re-run the full suite after that edit.

## Findings
Closed: glued known-prefix tokens (list above); URL password with raw `/`.
Remaining (honest limits):
- Glued tokens with generic or boundary-requiring shapes (`AKIA…`, `npm_`, `hf_`, JWT `eyJ`, bare `sk-`, `sk_live_`) are still clear.
- A glued token also swallows following alphanumerics (`[A-Za-z0-9]` body), so adjacent prose can be masked.
- URL passwords containing `?`, `#`, `@` or whitespace, or longer than 128 chars, are not fully masked. A benign link like `https://host:abc/x@y` (non-numeric after the colon) would be masked (false positive).
- `README.md:155` "Redaction limits" may still describe the raw-slash limit; not edited (outside my scope). `SECURITY.md` not changed. Owner should check wording.
- Not addressed by design: `create_entry` write cost, the 14 s handoff outlier, `Human (approved)` agent label.
