# CI button verification

Executed in E:/test_memoire, no product edits. Commands run separately, exactly as given.

1. `node node_modules/@playwright/test/cli.js test`
   - Result: 28 passed (1.7m), 1 worker, 0 failed, 0 skipped. Command ended normally (no failure output).
   - Specs: final (3), remediation (17), workbench (8).
2. `python -m pip wheel . --no-deps --wheel-dir .runtime/wheels`
   - Result: built filigree_memory-0.1.0-py3-none-any.whl, size 116607,
     sha256 2cf7bc14ac8b022b0e86ae4ad7a1e57880b6ce7d549b924f6329e5b1d3091181.
   - Only a pip upgrade notice; no errors.
3. `python scripts/verify_package.py`
   - Output: `PASS: isolated wheel install, CLI version, packaged HTML/JS, local bootstrap`
   - Only a pip upgrade notice; no errors.

Exit codes were not printed by the tool. Success is inferred from the absence of failure output and the PASS line. No GUI inferences were made. Linux CI was not run here.
