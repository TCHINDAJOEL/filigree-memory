# Remediation store follow-up (2026-10-16)

Scope: filigree/store.py, importers.py, git_sync.py, demo.py, tests/test_remediation_store.py. No source file was changed.

## Commands and results
1. `python -m unittest discover -s tests -p test_remediation_store.py`
   - Before: 45 tests, 1 failure (`test_more_than_a_thousand_records_import_in_one_call`, got (11, 1), expected (12, 0)).
   - After: 45 tests, OK.
2. `python -m unittest discover -s tests -p test_store.py`: 27 tests, OK.
3. Import/adapter/folder scoped suites were not run, because only a test file changed.

## The failure
The test first imports `events[0]` with `occurrence=None` (a legacy-identity entry). It then imports `events[:12]` with occurrence keys and expects 12 new entries.
`store.py:998-1002` correctly treats the first keyed identical line as the old entry. `test_memory_imported_before_occurrence_keys_is_not_duplicated_on_rescan` (line 351) requires exactly that.
The two tests contradicted each other, so the store behavior is correct and the test data was wrong.
Fix: the final import now uses `events[1:13]`. These lines have distinct bodies and were not pre-imported. The assertion is the same (12 imported, 0 duplicates), and the occurrence-key behavior is still checked.
This is a test-data correction, not a weakened assertion. Please review it.

## Not verified / remaining
- Strict history snapshot identity and tolerance of malformed current-entry files: no test names these directly (only a quarantine test, line 187-210, which passes). I did not inspect or change `store.py` for them, so treat them as unconfirmed.
- Findings from independent-verification-2026-10-16.md that I did not re-check against the source in this pass: B-1/A-6/E-1 (secret masking), E-2 (handoff/search with no lexical match), A-3 (stray or corrupt files breaking projects/handoff/export), A-8 (auto-supersede without human validation), B-7/A-14 (auto-created projects for TEMP/Users/Windows; canonical_folder).
- Their outcomes are still untracked. The passing suites show no regression but do not prove these are fixed.
- Git sync and demo have no failing tests, and I did not review them.
