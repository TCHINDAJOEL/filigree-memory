"""Manual, opt-in live check: can one real Claude client (haiku) retrieve Filigree memory over MCP and tell what is
current from what was replaced? Not part of the unit or CI suites; run it deliberately:

    python -X utf8 scripts/verify_live_handoff.py

It builds a synthetic memory with the Store API under .runtime/live-handoff/<stamp>/ (a superseded decision, the
accepted decision that replaced it, and an open question), writes a one-off MCP configuration file there, and makes
exactly one bounded `claude-tap` invocation (300 s maximum, no retry) of a Claude Haiku client in a synthetic folder.
That client gets `--strict-mcp-config --mcp-config <that file>` and no built-in tool: only the read tools of the
Filigree MCP server are permitted (`propose_memory` is not). Unlike the other live scripts it omits `--safe-mode`
(`claude --help` says it disables MCP servers) and isolates with `--setting-sources ""`, `disableAllHooks` and
`--disable-slash-commands`; that this lets the MCP tools load is only established by running the check. No user configuration is read or written, the claude-tap
database is isolated, no browser is opened, and the prompt contains none of the answers.

Passing requires all of: an MCP read tool actually called (visible `tool_use` blocks in the isolated claude-tap
database, and the synthetic entry ids present in the tool results the client received), the right entry named for each
of the current choice, the replaced choice and the open question, and the exact entry ids cited. Private logs stay
under .runtime. This proves one client on this machine; it does not show that every client injects memory automatically.

Exit codes: 0 pass, 1 assertion failed, 2 precondition or isolation missing, 3 the live call itself failed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from verify_live_capture import ROOT, Failure, check, create_baseline_db, git_root, inside, precondition  # noqa: E402

from filigree import tap_source  # noqa: E402  (repository source, not an installed copy)
from filigree.store import Store  # noqa: E402

CLAUDE_TIMEOUT = 300
MAX_TAP_RECORDS = 500
MAX_WALK_DEPTH = 40
SERVER = "filigree"
READ_TOOLS = ("list_projects", "project_for_folder", "search_memory", "get_handoff")
ALLOWED = [f"mcp__{SERVER}__{name}" for name in READ_TOOLS]
_SESSION = re.compile(r"[A-Za-z0-9-]{8,64}")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def step(message):
    print(f"[live-handoff] {message}", flush=True)


def prepare(stamp: str) -> dict:
    work = ROOT / ".runtime" / "live-handoff" / stamp
    precondition(not work.exists(), "le dossier de travail existe déjà : une exécution fraîche est requise")
    for name in ("memory", "tap", "logs"):
        (work / name).mkdir(parents=True)
    folder = Path(tempfile.mkdtemp(prefix="filigree-handoff-")).resolve()
    precondition(git_root(folder) is None, "le dossier synthétique est dans un dépôt Git ; abandon")
    paths = {"work": work, "memory": work / "memory", "db": work / "tap" / "traces.sqlite3", "mcp_config": work / "mcp-config.json", "folder": folder}
    precondition(inside(paths["db"], ROOT / ".runtime") and inside(paths["memory"], ROOT / ".runtime"), "les emplacements de test ne sont pas isolés")
    precondition(paths["memory"].resolve() != (Path.home() / ".filigree").resolve(), "la mémoire de test n'est pas isolée")
    return paths


def build_memory(paths) -> dict:
    """Synthetic knowledge through the Store API. The tokens are random so that nothing can be answered from training data."""
    token = {name: secrets.token_hex(3).upper() for name in ("old", "new", "open")}
    store = Store(paths["memory"])
    project = store.create_project("Projet de reprise synthétique", "Mémoire fabriquée pour la vérification de reprise.", folder=str(paths["folder"]))
    source = [{"label": "Note de conception synthétique", "excerpt": "Fabriquée par scripts/verify_live_handoff.py.", "uri": ""}]
    old = store.create_entry(project["id"], {"title": f"Stockage : utiliser le moteur ANCIEN-{token['old']}", "body": f"Décision initiale : le stockage repose sur le moteur ANCIEN-{token['old']}.", "kind": "decision", "status": "accepted", "agent": "synthétique", "sources": source})
    new = store.create_entry(project["id"], {"title": f"Stockage : utiliser le moteur NOUVEAU-{token['new']}", "body": f"Décision actuelle : le stockage repose sur le moteur NOUVEAU-{token['new']}. Elle remplace le moteur ANCIEN-{token['old']}, trop lent.", "kind": "decision", "status": "accepted", "agent": "synthétique", "sources": source, "relations": [{"target": old["id"], "type": "supersedes"}]})
    question = store.create_entry(project["id"], {"title": f"Question ouverte : politique de purge QUESTION-{token['open']}", "body": f"Faut-il purger l'historique après un an ? Non tranché (QUESTION-{token['open']}).", "kind": "question", "status": "accepted", "agent": "synthétique", "sources": source})
    entries = {entry["id"]: entry for entry in store.list_entries(project["id"])}
    check(entries[old["id"]]["status"] == "superseded" and entries[new["id"]]["status"] == "accepted", "la mémoire synthétique n'a pas le statut attendu")
    return {"project_id": project["id"], "old": old["id"], "new": new["id"], "open": question["id"], "token": token, "statuses": {key: entry["status"] for key, entry in entries.items()}}


def write_mcp_config(paths):
    """A fresh file used by this one invocation only. Nothing is added to any user or project configuration."""
    config = {"mcpServers": {SERVER: {"command": str(Path(sys.executable).resolve()), "args": ["-m", "filigree", "--data-dir", str(paths["memory"].resolve()), "mcp", "--project-folder", str(paths["folder"].resolve())], "env": {"PYTHONPATH": str(ROOT), "PYTHONUTF8": "1"}}}}
    paths["mcp_config"].write_text(json.dumps(config, indent=2), encoding="utf-8")


def run_claude(paths) -> dict:
    claude_tap = shutil.which("claude-tap")
    precondition(claude_tap is not None, "claude-tap est introuvable dans PATH (aucune installation n'est tentée)")
    precondition(shutil.which("claude") is not None, "claude est introuvable dans PATH (aucune installation n'est tentée)")
    prompt = (f"Synthetic handoff check. A local project memory is available through the {SERVER} MCP tools; the project is registered for the folder {paths['folder']}. "
              "Retrieve it with those tools, then work out the current storage decision, the storage decision that was replaced, and the open question. "
              "Reply with only one JSON object and nothing else, with exactly these keys: "
              '"current_decision" (its title), "replaced_decision" (its title), "open_question" (its title), '
              '"ids" (an object with the exact entry ids under "current", "replaced" and "open_question"). Use no tool other than the memory tools.')
    # Deliberately no --safe-mode here, unlike the other live scripts: `claude --help` says it disables MCP servers, which
    # would also disable the one supplied config. Isolation comes from empty --setting-sources (no user, project or local
    # settings), disableAllHooks, --disable-slash-commands and --strict-mcp-config; managed policy and auth stay in force.
    command = [claude_tap, "--tap-no-open", "--tap-no-live", "--tap-max-traces", "0", "--",
               "--setting-sources", "", "--settings", '{"disableAllHooks":true}', "--disable-slash-commands",
               "--strict-mcp-config", "--mcp-config", str(paths["mcp_config"]), "--model", "haiku", "--permission-mode", "dontAsk",
               "--tools", "", "--allowedTools", *ALLOWED, "--output-format", "json", "-p", prompt]
    # Only this child loses the nested-session marker; the parent environment and every configuration stay untouched.
    # The test executor itself uses --safe-mode, which exports CLAUDE_CODE_SAFE_MODE=1.
    # This isolated child needs its explicitly supplied MCP server; settings/hooks remain
    # confined by the flags above, and admin-managed policy is not changed.
    env = {key: value for key, value in os.environ.items() if key not in {"CLAUDECODE", "CLAUDE_CODE_SAFE_MODE"}}
    env["CLOUDTAP_DB"] = str(paths["db"])
    options = {"creationflags": 0x00000200} if os.name == "nt" else {"start_new_session": True}
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=paths["folder"], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", **options)
    try:
        stdout, stderr = process.communicate(timeout=CLAUDE_TIMEOUT)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        else:
            process.kill()
        process.communicate()
        raise Failure(3, f"appel Claude interrompu après {CLAUDE_TIMEOUT} s (aucun nouvel essai)")
    (paths["work"] / "logs" / "claude-stdout.txt").write_text(stdout, encoding="utf-8")
    (paths["work"] / "logs" / "claude-stderr.txt").write_text(stderr, encoding="utf-8")
    result = None
    for line in stdout.splitlines():
        try:
            candidate = json.loads(line)
        except ValueError:
            continue
        if isinstance(candidate, dict) and candidate.get("type") == "result":
            result = candidate
    if process.returncode != 0 or result is None or result.get("is_error"):
        raise Failure(3, f"appel Claude en échec : code {process.returncode}, résultat {'absent' if result is None else result.get('subtype')}; détails privés dans {paths['work'] / 'logs'}")
    session_id = result.get("session_id")
    check(isinstance(session_id, str) and _SESSION.fullmatch(session_id), "session_id natif absent ou de forme inattendue")
    denied = result.get("permission_denials") or []
    check(not denied, f"{len(denied)} outil(s) refusé(s) par la politique de permissions ; la récupération MCP n'a pas pu se faire comme prévu")
    return {"answer": result.get("result"), "native_id": session_id, "seconds": round(time.monotonic() - started, 1), "turns": result.get("num_turns")}


def walk(value, visit, depth=0):
    if depth > MAX_WALK_DEPTH:
        return
    visit(value)
    if isinstance(value, dict):
        for item in value.values():
            walk(item, visit, depth + 1)
    elif isinstance(value, list):
        for item in value:
            walk(item, visit, depth + 1)


def observed_tools(db_path: Path) -> dict:
    """Tool names called by the client and ids that appeared in tool results, from the isolated claude-tap database.
    Names and ids only; no message text is kept."""
    connection, capability = tap_source.open_db(db_path)
    check(connection is not None, f"base claude-tap illisible après l'appel : {capability}")
    calls, result_ids, records = {}, set(), 0

    def visit(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "tool_use" and isinstance(node.get("name"), str):
            calls[node["name"]] = calls.get(node["name"], 0) + 1
        if node.get("type") == "tool_result":
            walk(node.get("content"), lambda leaf: result_ids.update(_UUID.findall(leaf)) if isinstance(leaf, str) else None)

    try:
        for session in tap_source.list_sessions(connection):
            for _index, _stamp, text, _size in tap_source.read_batch(connection, session, 0, MAX_TAP_RECORDS):
                if text is None:
                    continue
                try:
                    walk(tap_source.decode_payload(connection, session, text), visit)
                    records += 1
                except tap_source.RecordError:
                    continue
    finally:
        connection.close()
    return {"calls": calls, "result_ids": result_ids, "records": records}


def parse_answer(text) -> dict:
    check(isinstance(text, str) and text.strip(), "réponse du client vide")
    body = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", body, re.S)
    if fenced:
        body = fenced.group(1)
    start, end = body.find("{"), body.rfind("}")
    check(start >= 0 and end > start, "la réponse ne contient pas d'objet JSON")
    try:
        answer = json.loads(body[start:end + 1])
    except ValueError:
        raise Failure(1, "la réponse n'est pas un JSON valide")
    check(isinstance(answer, dict) and isinstance(answer.get("ids"), dict), "forme de réponse inattendue (clé « ids » absente)")
    return answer


def verify(paths, memory: dict, live: dict) -> dict:
    tools = observed_tools(paths["db"])
    check(tools["records"] > 0, "aucun enregistrement exploitable dans la base claude-tap isolée")
    used = {name for name in tools["calls"] if name.startswith(f"mcp__{SERVER}__")}
    check(used, f"aucun appel d'outil MCP {SERVER} observé dans les blocs visibles de claude-tap (appels vus : {sorted(tools['calls'])})")
    check(set(tools["calls"]) <= set(ALLOWED), f"outil(s) inattendu(s) appelé(s) : {sorted(set(tools['calls']) - set(ALLOWED))}")
    check(f"mcp__{SERVER}__propose_memory" not in tools["calls"], "le client a appelé propose_memory")
    check(used & {f"mcp__{SERVER}__search_memory", f"mcp__{SERVER}__get_handoff"}, "ni search_memory ni get_handoff n'a été appelé : le contenu n'a pas pu être récupéré")
    wanted = {memory["old"], memory["new"], memory["open"]}
    check(wanted <= tools["result_ids"], f"les résultats d'outils reçus par le client ne contiennent pas toutes les entrées ({len(wanted & tools['result_ids'])}/3)")
    answer = parse_answer(live["answer"])
    ids, token = answer["ids"], memory["token"]
    check((ids.get("current"), ids.get("replaced"), ids.get("open_question")) == (memory["new"], memory["old"], memory["open"]), "identifiants cités incorrects ou confondus")
    check(f"NOUVEAU-{token['new']}" in str(answer.get("current_decision")) and f"ANCIEN-{token['old']}" not in str(answer.get("current_decision")), "la décision actuelle est fausse ou confondue avec la décision remplacée")
    check(f"ANCIEN-{token['old']}" in str(answer.get("replaced_decision")) and f"NOUVEAU-{token['new']}" not in str(answer.get("replaced_decision")), "la décision remplacée est fausse ou confondue avec la décision actuelle")
    check(f"QUESTION-{token['open']}" in str(answer.get("open_question")), "la question ouverte est fausse")
    after = {entry["id"]: entry["status"] for entry in Store(paths["memory"]).list_entries(memory["project_id"])}
    check(after == memory["statuses"], "la mémoire synthétique a changé pendant l'appel")
    return {"tools": tools["calls"], "records": tools["records"], "ids_cited": 3}


def main():
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check-only", action="store_true", help="build the synthetic memory and the MCP file, make no Claude call")
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    debug = {"stamp": stamp}
    paths = None
    try:
        paths = prepare(stamp)
        step(f"travail isolé : {paths['work']}")
        create_baseline_db(paths["db"])
        memory = build_memory(paths)
        debug["memory"] = {key: value for key, value in memory.items() if key != "token"}
        write_mcp_config(paths)
        step("mémoire synthétique construite (décision remplacée, décision actuelle, question ouverte) ; configuration MCP temporaire écrite")
        if args.check_only:
            step("PASS (--check-only) : mémoire et configuration prêtes ; aucun appel Claude")
            return 0
        step(f"appel unique claude-tap, modèle haiku, au plus {CLAUDE_TIMEOUT} s, sans nouvel essai")
        live = run_claude(paths)
        debug["live"] = {key: value for key, value in live.items() if key != "answer"}
        step(f"réponse reçue en {live['seconds']} s")
        debug["verified"] = verify(paths, memory, live)
        print(f"PASS: un client Claude haiku a récupéré la mémoire via MCP ({', '.join(sorted(debug['verified']['tools']))}) et distingué décision actuelle, décision remplacée et question ouverte avec les 3 identifiants exacts.")
        print("Portée : un seul client sur cette machine, interrogé explicitement ; aucune preuve d'injection automatique pour d'autres clients.")
        return 0
    except Failure as failure:
        debug["failure"] = {"code": failure.code, "message": str(failure)}
        print(f"FAIL ({'assertion' if failure.code == 1 else 'précondition' if failure.code == 2 else 'appel live'}): {failure}", file=sys.stderr)
        return failure.code
    finally:
        if paths is not None:
            (paths["work"] / "debug.json").write_text(json.dumps(debug, indent=1, default=str), encoding="utf-8")
            print(f"[live-handoff] diagnostic privé : {paths['work'] / 'debug.json'} (aucun nettoyage automatique)", flush=True)


if __name__ == "__main__":
    sys.exit(main())
