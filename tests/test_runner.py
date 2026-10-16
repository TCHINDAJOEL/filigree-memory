"""The development quota runner is bounded and never retries successful work."""
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from unittest.mock import patch

from scripts import claude_runner


class RunnerTests(unittest.TestCase):
    def execute(self, result, runtime_files=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".aiwg/planning").mkdir(parents=True)
            (root / ".aiwg/planning/claude-task.md").write_text("Read-only synthetic task", encoding="utf-8")
            runtime = root / ".runtime"
            state = runtime / "claude-state.json"
            with patch.multiple(claude_runner, ROOT=root, RUNTIME=runtime, STATE=state), patch("sys.argv", ["runner", "--model", "haiku"]), patch.object(claude_runner, "run_bounded", **result) as run, contextlib.redirect_stdout(io.StringIO()):
                code = claude_runner.main()
                saved = json.loads(state.read_text(encoding="utf-8"))
                if runtime_files is not None:
                    runtime_files["output"] = (runtime / "claude-last-output.txt").read_text(encoding="utf-8")
                self.assertIn("--tap-max-traces", run.call_args.args[0])
                return code, saved

    def test_success_mentioning_rate_limit_is_not_retried(self):
        response = {"type": "result", "is_error": False, "result": "Review of rate_limit_error handling"}
        code, state = self.execute(dict(return_value=subprocess.CompletedProcess([], 0, json.dumps(response), "")))
        self.assertEqual(code, 0)
        self.assertEqual(state["status"], "complete")
        self.assertNotIn("nextRetryAt", state)

    def test_actual_limit_records_bounded_retry(self):
        code, state = self.execute(dict(return_value=subprocess.CompletedProcess([], 1, "You've hit your limit", "")))
        self.assertEqual(code, 75)
        self.assertEqual(state["status"], "rate_limited")
        self.assertIn("nextRetryAt", state)
        self.assertEqual(state["attempts"], 1)

    def test_authentication_failure_is_not_automatically_retried(self):
        code, state = self.execute(dict(return_value=subprocess.CompletedProcess([], 1, "Please log in", "")))
        self.assertEqual(code, 1)
        self.assertEqual(state["status"], "failed")
        self.assertNotIn("nextRetryAt", state)

    def test_structured_session_quota_is_retried(self):
        response = {"type": "result", "is_error": True, "api_error_status": 429,
                    "api_error": "usage_limit_reached",
                    "result": "You've hit your session limit · resets 2:20am (Europe/Paris)"}
        code, state = self.execute(dict(return_value=subprocess.CompletedProcess([], 1, json.dumps(response), "")))
        self.assertEqual(code, 75)
        self.assertEqual(state["status"], "rate_limited")
        self.assertIn("nextRetryAt", state)

    def test_timeout_marks_failed_and_keeps_private_output(self):
        files = {}
        error = claude_runner.TaskTimeout("partial SECRET-OUT", "partial err")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code, state = self.execute(dict(side_effect=error), files)
        self.assertEqual(code, 1)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["reason"], "TaskTimeout")
        self.assertNotIn("nextRetryAt", state)
        self.assertIn("partial SECRET-OUT", files["output"])

    def test_interrupt_marks_failed(self):
        code, state = self.execute(dict(side_effect=KeyboardInterrupt()))
        self.assertEqual(code, 130)
        self.assertEqual(state["status"], "failed")

    def test_kill_tree_targets_only_launched_pid_on_windows(self):
        process = unittest.mock.Mock(pid=4242)
        with patch.object(claude_runner.os, "name", "nt"), patch.object(claude_runner.subprocess, "run") as run:
            claude_runner.kill_tree(process)
        self.assertEqual(run.call_args.args[0], ["taskkill", "/PID", "4242", "/T", "/F"])

    @unittest.skipIf(sys.platform == "win32", "POSIX process groups")
    def test_kill_tree_signals_only_launched_group_on_posix(self):
        process = unittest.mock.Mock(pid=4242)
        with patch.object(claude_runner.os, "killpg") as killpg:
            claude_runner.kill_tree(process)
        killpg.assert_called_once_with(4242, signal.SIGKILL)


class SyntheticTreeTests(unittest.TestCase):
    """Real subprocess tree: outer spawns a grandchild that holds inherited output open."""

    def test_timeout_kills_tree_without_hanging(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "grandchild.pid"
            grandchild = "import time;time.sleep(300)"
            outer = (
                "import subprocess,sys,time;"
                f"p=subprocess.Popen([sys.executable,'-c',{grandchild!r}],stdout=sys.stdout,stderr=sys.stderr);"
                f"open({str(marker)!r},'w').write(str(p.pid));print('started',flush=True);time.sleep(300)"
            )
            started = time.monotonic()
            with patch.object(claude_runner, "KILL_GRACE", 5):
                with self.assertRaises(claude_runner.TaskTimeout) as caught:
                    claude_runner.run_bounded([sys.executable, "-c", outer], temporary, 3)
            self.assertLess(time.monotonic() - started, 30)
            self.assertIn("started", caught.exception.stdout)
            pid = int(marker.read_text())
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and self.alive(pid):
                time.sleep(0.2)
            self.assertFalse(self.alive(pid), "grandchild survived timeout cleanup")

    @staticmethod
    def alive(pid):
        if sys.platform == "win32":
            result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
            return str(pid) in result.stdout
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def test_normal_exit_returns_output(self):
        result = claude_runner.run_bounded([sys.executable, "-c", "print('ok')"], ".", 30)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "ok"))
