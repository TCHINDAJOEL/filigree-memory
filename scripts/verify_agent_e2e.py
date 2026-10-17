"""End-to-end check of the real `filigree agent` process. Synthetic and isolated: no model call, no real agent data.

It starts `filigree agent` from the CLI with temporary Claude/Codex/AppData roots, writes one synthetic Claude Code
transcript after the observer's baseline plus a session-end signal, then checks the activity journal, the session-sheet
proposal, `filigree status` and that `filigree serve` defers to the running agent.

    python scripts/verify_agent_e2e.py
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from filigree.store import Store

    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder)
        env = {**os.environ, "PYTHONPATH": str(ROOT), "CLAUDE_CONFIG_DIR": str(base / "claude"), "CODEX_HOME": str(base / "codex"),
               "APPDATA": str(base / "roaming"), "LOCALAPPDATA": str(base / "local"), "CLOUDTAP_DB": str(base / "absent.sqlite3")}
        data = base / "data"
        project_folder = base / "work" / "app"
        project_folder.mkdir(parents=True)

        def run(*arguments):
            return subprocess.run([sys.executable, "-m", "filigree", "--data-dir", str(data), *arguments], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)

        assert run("setup", "--root", str(base / "work")).returncode == 0
        project = json.loads(run("create", "App", "--folder", str(project_folder)).stdout)
        agent = subprocess.Popen([sys.executable, "-m", "filigree", "--data-dir", str(data), "agent", "--port", "0", "--interval", "1"],
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            line = agent.stdout.readline()
            assert "http://127.0.0.1:" in line, line + agent.stderr.read()
            transcripts = base / "claude" / "projects" / "-app"
            transcripts.mkdir(parents=True)
            time.sleep(2.5)  # the first observer cycle sets the baseline (no catch-up)
            rows = [
                {"type": "user", "sessionId": "E2E", "cwd": str(project_folder), "uuid": "e1", "timestamp": "2026-10-17T12:00:00Z", "message": {"role": "user", "content": "Ajoute la pagination"}},
                {"type": "assistant", "sessionId": "E2E", "cwd": str(project_folder), "uuid": "e2", "timestamp": "2026-10-17T12:00:05Z",
                 "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "Edit", "input": {"file_path": str(project_folder / "api.py")}}]}},
            ]
            (transcripts / "E2E.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            (data / ".runtime" / "signals.jsonl").write_text(json.dumps({"client": "claude", "session_id": "E2E", "event": "session_end"}) + "\n", encoding="utf-8")
            deadline, activity = time.time() + 20, {}
            while time.time() < deadline:
                activity = json.loads(run("activity", project["id"]).stdout)
                if activity["stats"]["events"] >= 2:
                    break
                time.sleep(1)
            assert activity["stats"]["events"] == 2, activity["stats"]
            time.sleep(2.5)  # one more cycle for the session sheet
            status = json.loads(run("status").stdout)
            assert status["agent"] and status["agent"]["url"] in line, status["agent"]
            assert project["id"] in status["journals"], status["journals"]
            handed = run("serve", "--port", "0")
            assert "sert déjà" in handed.stdout, handed.stdout + handed.stderr
            sheets = [entry for entry in Store(data).list_entries(project["id"]) if "fiche-session" in entry["tags"]]
            assert len(sheets) == 1 and sheets[0]["status"] == "proposed" and "api.py" in sheets[0]["body"], sheets
        finally:
            agent.terminate()
            agent.wait(timeout=15)
    print("PASS: agent started; journal 2 events; one proposed session sheet; status reports agent and journal; serve defers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
