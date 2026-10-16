"""Run a bounded Claude task through claude-tap; retry only explicit rate limits.

Invoke again after nextRetryAt (the Codex heartbeat can do this). No busy-loop,
paid fallback, credential handling or automatic retry of ordinary failures.
"""
import argparse
import hashlib
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
STATE = RUNTIME / "claude-state.json"
KILL_GRACE = 10


class TaskTimeout(Exception):
    """The launched process tree exceeded its time limit; partial output is kept."""

    def __init__(self, stdout, stderr):
        super().__init__("timeout")
        self.stdout, self.stderr = stdout, stderr


def kill_tree(process):
    """Terminate only the process this runner launched and its descendants (never by name)."""
    if os.name == "nt":
        # /T walks the children of this exact PID; /F forces. Bounded so cleanup cannot hang.
        try:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=KILL_GRACE)
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        import signal
        try:
            os.killpg(process.pid, signal.SIGKILL)  # process.pid leads its own session group
        except (OSError, ProcessLookupError):
            pass
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=KILL_GRACE)
    except subprocess.TimeoutExpired:
        pass


def run_bounded(command, cwd, timeout):
    """Like subprocess.run(capture_output) but output goes to private temp files, not pipes.

    Grandchildren that inherit and hold a pipe open can make communicate() block forever
    after the outer process is killed; files cannot. On timeout or interrupt the whole
    launched tree is killed.
    """
    options = {"start_new_session": True} if os.name != "nt" else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=err, **options)

        def collect():
            texts = []
            for handle in (out, err):
                handle.seek(0)
                texts.append(handle.read().decode("utf-8", errors="replace"))
            return texts

        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_tree(process)
            raise TaskTimeout(*collect())
        except BaseException:
            kill_tree(process)
            raise
        stdout, stderr = collect()
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def save(value):
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(STATE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--role", choices=["review", "plan", "build", "test"], default="review")
    parser.add_argument("--new-task", action="store_true")
    args = parser.parse_args()
    # A Windows console may default to cp1252; the model result is UTF-8 text.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    RUNTIME.mkdir(exist_ok=True)
    # OS advisory lock is released even when the process is interrupted; the handle is
    # also closed deterministically so no ResourceWarning leaks from repeated calls.
    lock = (RUNTIME / "claude-runner.lock").open("a+b")
    try:
        try:
            if os.name == "nt":
                import msvcrt
                lock.seek(0); lock.write(b"0"); lock.flush(); lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("A Claude task is already running.")
            return 0
        return run_task(args)
    finally:
        lock.close()


def run_task(args):
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    if args.new_task:
        state = {}
    elif state.get("status") in {"complete", "failed", "running"}:
        print(f"No automatic restart: status={state['status']}. Inspect results; use --new-task for a new assignment.")
        return 0
    now = datetime.now(timezone.utc)
    if state.get("nextRetryAt") and now < datetime.fromisoformat(state["nextRetryAt"]):
        print(f"Waiting until {state['nextRetryAt']}")
        return 0
    attempts = state.get("attempts", 0) + 1
    if attempts > 20:
        save({**state, "status": "failed", "reason": "Retry cap reached; human review required."})
        return 1
    task = (ROOT / ".aiwg/planning/claude-task.md").read_text(encoding="utf-8")
    digest = hashlib.sha256(task.encode("utf-8")).hexdigest()
    if state.get("taskHash") and state["taskHash"] != digest:
        print("Task changed since rate limit. Inspect and use --new-task explicitly.")
        return 1
    state = {"status": "running", "attempts": attempts, "startedAt": now.isoformat(), "model": state.get("model", args.model), "role": state.get("role", args.role), "pid": os.getpid(), "taskHash": digest}
    save(state)
    editing = ",Write,Edit" if state["role"] == "build" else ",Write" if state["role"] == "plan" else ""
    command = ["claude-tap", "--tap-no-open", "--tap-no-live", "--tap-max-traces", "0", "--", "--safe-mode", "--strict-mcp-config", "--model", state["model"], "--permission-mode", "dontAsk", "--tools", "Read,Grep,Glob,Bash" + editing, "--allowedTools", "Read,Grep,Glob,Bash(python *),Bash(node *),Bash(git status*),Bash(git diff*)" + editing, "--output-format", "json", "-p", task]
    try:
        result = run_bounded(command, ROOT, 1800)
    except (OSError, TaskTimeout, KeyboardInterrupt) as exc:
        if isinstance(exc, TaskTimeout):
            # Private log only (may contain model/user content); never printed.
            (RUNTIME / "claude-last-output.txt").write_text(exc.stdout + "\n" + exc.stderr, encoding="utf-8")
        save({**state, "status": "failed", "reason": type(exc).__name__, "finishedAt": datetime.now(timezone.utc).isoformat()})
        print(f"Claude task stopped: {type(exc).__name__}. Inspect before restarting.")
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    output = result.stdout + "\n" + result.stderr
    (RUNTIME / "claude-last-output.txt").write_text(output, encoding="utf-8")
    response = None
    for line in result.stdout.splitlines():
        try:
            candidate = json.loads(line)
            if isinstance(candidate, dict) and candidate.get("type") == "result":
                response = candidate
        except json.JSONDecodeError:
            pass
    success = result.returncode == 0 and response is not None and not response.get("is_error", False)
    # A successful review can legitimately discuss quota errors. Never retry it.
    limited = not success and (
        (response or {}).get("api_error") in {"usage_limit_reached", "rate_limit_error"}
        or bool(re.search(r"you.ve hit your (?:session |weekly )?limit|usage[ _]limit[ _]reached|rate_limit_error|rate limit exceeded|out of extra usage", output, re.I))
    )
    if limited:
        delay = min(240, 15 * 2 ** min(attempts - 1, 4))
        retry = datetime.now(timezone.utc) + timedelta(minutes=delay)
        save({**state, "status": "rate_limited", "nextRetryAt": retry.isoformat(), "retryBasis": "Conservative backoff; actual reset unknown. Inspect service message in private log."})
        print(f"Claude rate limit. Next permitted retry: {retry.isoformat()} (backoff, not a claimed quota reset).")
        return 75
    save({**state, "status": "complete" if success else "failed", "exitCode": result.returncode, "sessionId": (response or {}).get("session_id"), "finishedAt": datetime.now(timezone.utc).isoformat()})
    print((response or {}).get("result") or "See .runtime/claude-last-output.txt; no valid success response.")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
