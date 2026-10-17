"""Manual, opt-in live check of the v0.2 permanent observer: one real Claude Code (haiku) session, launched directly in
a synthetic folder while a real `filigree agent` runs, must appear in that project's activity journal and become one
proposed session sheet. Not part of the unit or CI suites; run it deliberately:

    python -X utf8 scripts/verify_live_observer.py

Isolation: a fresh Filigree data folder under .runtime/live-observer/<stamp>/ whose allowed roots contain only the
synthetic folder; the claude-tap source points to an absent database. The agent reads the user's own Claude Code
transcript folder exactly as it does in normal use (read-only, metadata heads, and only new lines of sessions whose
folder is the synthetic one; history before its first cycle is never read). The child `claude` gets only the Read and
Edit tools, limited to two synthetic files. Exactly one bounded call (300 s, no retry). Nothing global is modified.

Exit codes: 0 pass, 1 assertion failed, 2 precondition missing, 3 the live call itself failed.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
CLAUDE_TIMEOUT = 300


def step(message):
    print(f"[live-observer] {message}", flush=True)


def fail(code, message):
    print(f"FAIL ({code}): {message}", flush=True)
    raise SystemExit(code)


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from filigree.activity import ActivityLog, journal_path
    from filigree.store import Store

    claude = shutil.which("claude")
    if claude is None:
        fail(2, "claude est introuvable dans PATH (aucune installation n'est tentée)")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    work = ROOT / ".runtime" / "live-observer" / stamp
    data = work / "memory"
    (work / "logs").mkdir(parents=True)
    folder = Path(tempfile.mkdtemp(prefix="filigree-observer-")).resolve()
    token = f"OBS-{os.urandom(4).hex()}"
    (folder / "marker.txt").write_text(f"marker token: {token}\n", encoding="utf-8")
    (folder / "notes.md").write_text("# Notes\n\nStatus: TODO\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT), "CLOUDTAP_DB": str(work / "absent-tap" / "traces.sqlite3")}

    def filigree(*arguments):
        return subprocess.run([sys.executable, "-m", "filigree", "--data-dir", str(data), *arguments], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)

    step(f"dossier synthétique : {folder}")
    if filigree("setup", "--root", str(folder)).returncode != 0:
        fail(2, "filigree setup a échoué")
    project = json.loads(filigree("create", "Observateur live", "--folder", str(folder)).stdout)
    agent = subprocess.Popen([sys.executable, "-m", "filigree", "--data-dir", str(data), "agent", "--port", "0", "--interval", "2"],
                             env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        line = agent.stdout.readline()
        if "http://127.0.0.1:" not in line:
            fail(2, "l'agent n'a pas démarré : " + line + agent.stderr.read()[-500:])
        step(f"agent démarré : {line.strip().split(' · ')[-1]}")
        time.sleep(5)  # first observer cycle = baseline of every existing transcript (no catch-up)

        child = dict(os.environ)
        child.pop("CLAUDECODE", None)
        for name in ("ANTHROPIC_BASE_URL", "OPENAI_BASE_URL"):
            if re.match(r"https?://(127\.0\.0\.1|localhost|\[::1\])(:|/|$)", child.get(name, "")):
                child.pop(name)
        prompt = ("Synthetic integration check. Read the file marker.txt in the current folder, then edit notes.md so that the line "
                  "'Status: TODO' becomes 'Status: ' followed by the marker token. Use only the Read and Edit tools on these two files, "
                  "then answer in one short sentence.")
        command = [claude, "--safe-mode", "--strict-mcp-config", "--model", "haiku", "--permission-mode", "dontAsk", "--tools", "Read,Edit",
                   "--allowedTools", "Read(./marker.txt)", "Read(./notes.md)", "Edit(./notes.md)", "--output-format", "json", "-p", prompt]
        step("appel unique de claude (haiku, lancement direct), au plus 300 s, sans nouvel essai")
        started = time.monotonic()
        try:
            completed = subprocess.run(command, cwd=folder, env=child, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=CLAUDE_TIMEOUT)
        except subprocess.TimeoutExpired:
            fail(3, f"appel Claude interrompu après {CLAUDE_TIMEOUT} s (aucun nouvel essai)")
        (work / "logs" / "claude-stdout.txt").write_text(completed.stdout, encoding="utf-8")
        (work / "logs" / "claude-stderr.txt").write_text(completed.stderr, encoding="utf-8")
        result = next((json.loads(text) for text in completed.stdout.splitlines() if text.strip().startswith("{") and '"type"' in text), None)
        if completed.returncode != 0 or not result or result.get("is_error"):
            fail(3, f"appel Claude en échec (code {completed.returncode}) ; détails privés dans {work / 'logs'}")
        session_id = result.get("session_id", "")
        step(f"réponse reçue en {time.monotonic() - started:.1f} s ; session {session_id[:8]}")
        edited = token in (folder / "notes.md").read_text(encoding="utf-8")

        log = ActivityLog(journal_path(Store(data), project["id"]))
        deadline, events = time.time() + 60, []
        while time.time() < deadline:
            events = [event for event in log.events(limit=500) if event["session_key"].endswith(session_id)]
            if any(event["kind"] == "user_prompt" for event in events) and (not edited or any(event["kind"] == "file_change" for event in events)):
                break
            time.sleep(2)
        kinds = sorted({event["kind"] for event in events})
        step(f"journal : {len(events)} événement(s) pour cette session, types {kinds}")
        if not any(event["kind"] == "user_prompt" for event in events):
            fail(1, "la demande de la session réelle n'apparaît pas dans le journal")
        if edited and not any(event["kind"] == "file_change" and any(name.endswith("notes.md") for name in event["files"]) for event in events):
            fail(1, "notes.md a été modifié mais aucun événement file_change ne le mentionne")
        if any(token in event["summary"] and event["kind"] == "command" for event in events):
            fail(1, "une ligne de commande a été conservée")

        filigree("signal", "--client", "claude", "--event", "session_end", "--session-id", session_id)
        deadline, sheets = time.time() + 30, []
        while time.time() < deadline:
            sheets = [entry for entry in Store(data).list_entries(project["id"]) if "fiche-session" in entry["tags"]]
            if sheets:
                break
            time.sleep(2)
        if len(sheets) != 1 or sheets[0]["status"] != "proposed":
            fail(1, f"fiche de session attendue (1 proposition), obtenu {[(s['status'], s['title']) for s in sheets]}")
        status = json.loads(filigree("status").stdout)
        if not status["agent"] or project["id"] not in status["journals"]:
            fail(1, "filigree status ne rapporte pas l'agent ou le journal")
    finally:
        agent.terminate()
        agent.wait(timeout=15)
    (work / "result.json").write_text(json.dumps({"session": session_id, "events": len(events), "kinds": kinds, "edited": edited, "sheet": sheets[0]["title"], "data": str(data), "project": project["id"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PASS: session réelle {session_id[:8]} journalisée ({len(events)} événements : {', '.join(kinds)}), "
          f"{'modification de notes.md observée, ' if edited else 'notes.md non modifié par le modèle, '}une fiche de session proposée, status cohérent.")
    print("Portée : une seule session Claude Code (haiku) lancée directement, sur cette machine ; ni Codex, ni d'autres versions.")
    step(f"données conservées (privé, .runtime) : {work}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
