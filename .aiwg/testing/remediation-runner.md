# Runner timeout remediation

Defect: `subprocess.run(capture_output=True, timeout=1800)` killed only the outer `claude-tap.exe` on Windows. Grandchild Claude processes kept the stdout pipe open, so `communicate()` never returned, state stayed `running`, and the orphan kept editing.

Fix (`scripts/claude_runner.py`):
- `run_bounded` launches with `Popen`, output going to private temp files instead of pipes, so an inherited handle can never block collection.
- New process group (Windows `CREATE_NEW_PROCESS_GROUP`) or session (POSIX `start_new_session`).
- On timeout or any interrupt, `kill_tree` kills only the launched PID's tree: `taskkill /PID <pid> /T /F` on Windows, `killpg(pid, SIGKILL)` on POSIX. Never by name. Each wait is bounded by `KILL_GRACE` (10 s).
- Timeout raises `TaskTimeout` carrying partial output. It is written to `.runtime/claude-last-output.txt` and never printed. State becomes `failed` (reason `TaskTimeout`, or `KeyboardInterrupt` with exit 130).
- Quota/auth retry logic, task file handling and ordinary-failure behavior are unchanged.

Tests (`tests/test_runner.py`, `python -m pytest tests/test_runner.py`): 9 passed, 1 skipped (POSIX killpg test, skipped on Windows). They cover mocked timeout and interrupt state, the exact taskkill argv, and a real synthetic tree (outer plus grandchild sharing output, 3 s timeout) in which the grandchild is verified dead. No Claude or model call.

Limitations:
- Windows `taskkill /T` follows parent links. A descendant already re-parented after its parent exited is not found. Job objects would close this gap.
- The POSIX path was not run here (Windows host). Only the mocked call is covered, and it was skipped on Windows.
- A grandchild that outlives a normally exiting outer process is not killed (deliberate, to avoid acting on a reused PID/group).
- A hard kill of the runner itself (not Ctrl+C) leaves state `running`.
