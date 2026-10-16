"""Manual, opt-in live end-to-end journey: write -> capture -> human review in a real browser -> fresh reader over MCP.
Not part of the unit or CI suites. Run it deliberately, only after the product fixes are in and with explicit authorization:

    python -X utf8 scripts/verify_live_journey.py --check-only     # no model call; proves isolation and plumbing
    python -X utf8 scripts/verify_live_journey.py [--model sonnet]  # at most 2 real Claude calls

Journey (everything under .runtime/live-journey/<stamp>/, nothing is deleted afterwards):
1. A writer Claude client (no tool, no hook, no skill) runs through claude-tap in a NEW local folder and is told a
   synthetic project decision (SQLite instead of Postgres, with a concrete reason) next to harmless fake secrets.
2. Filigree captures that exact exchange from an isolated claude-tap database; only the metadata (sessionId, cwd) of the
   transcript named exactly by the returned session id is copied into an isolated native root. The project is
   auto-created for the right folder, the proposals are checked and no accepted note is seeded.
3. An isolated local server (--no-capture, explicit synthetic data/TAP/native roots) is driven by REAL Playwright Chromium
   (scripts/live_journey_browser.cjs): the captured proposal is located in the page, its visible provenance inspected, it
   is converted to a decision through the interface when needed and accepted with an explicit reason. The handoff must then
   list it as current.
4. A second, clean Claude client gets a temporary --strict-mcp-config with only the Filigree read tools and is asked
   "What was our database choice and why?" plus the project folder. The prompt holds no answer and no note id.
   The reader is a fresh session (own claude-tap database, no writer context) whose cwd and named folder are the writer's project folder. The reply
   is structured JSON, checked against the accepted note id, the choice and the reason; the MCP calls are read from the
   claude-tap history (unique tool_use ids, not repeated history blocks); the store must be unchanged by the reader.
5. The raw fake credentials must be absent from every persisted file, history, export, handoff and visible page.

Limits: 2 Claude invocations maximum, 300 s each, no retry. No user history, user agent configuration or real claude-tap
database is read or written. Inherited CLAUDECODE and CLAUDE_CODE_SAFE_MODE are removed from the two Claude children only
(safe mode would disable MCP); managed policy stays in force. Output is aggregate; private evidence stays under .runtime.

Exit codes: 0 pass, 1 assertion failed, 2 precondition or isolation missing, 3 a live call itself failed.
--check-only never starts Claude and is NOT a live PASS.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from verify_live_capture import ROOT, Failure, check, copy_metadata, create_baseline_db, find_transcript, git_root, inside, isolated_capture, precondition  # noqa: E402
from verify_live_capture import verify as verify_capture  # noqa: E402

from filigree import tap_source  # noqa: E402  (repository source, not an installed copy)
from filigree.store import Store  # noqa: E402

CLAUDE_TIMEOUT = 300
MAX_CALLS = 2
BROWSER_TIMEOUT = 240
SERVER_WAIT = 20
MAX_TAP_RECORDS = 500
MAX_WALK_DEPTH = 40
SERVER = "filigree"
READ_TOOLS = ("list_projects", "project_for_folder", "search_memory", "get_handoff")
ALLOWED = [f"mcp__{SERVER}__{name}" for name in READ_TOOLS]
CONTENT_TOOLS = {f"mcp__{SERVER}__search_memory", f"mcp__{SERVER}__get_handoff"}
QUESTION = "What was our database choice and why?"
BROWSER = SCRIPTS / "live_journey_browser.cjs"
_SESSION = re.compile(r"[A-Za-z0-9-]{8,64}")
_SHELL_META = re.compile(r"[&|<>%^\r\n]")
# Several wordings of each part of the reason written in the synthetic decision; the reader must cover at least two parts.
REASON_GROUPS = (("single-user", "single user", "one user", "solo"), ("offline", "without network", "no network", "disconnected"),
                 ("50 mb", "small", "tiny", "little data", "under 50"), ("operations", "operational", "server", "administration", "maintenance"))
STATE = {"calls": 0, "allow_model": True}


def step(message):
    print(f"[live-journey] {message}", flush=True)


def lap(timings, name, started):
    timings[name] = round(time.monotonic() - started, 1)


# ---------------------------------------------------------------------------------------------------- preparation

def prepare(stamp: str) -> dict:
    work = ROOT / ".runtime" / "live-journey" / stamp
    precondition(not work.exists(), "le dossier de travail existe déjà : une exécution fraîche est requise")
    for name in ("memory", "tap", "tap-reader", "native-claude/projects", "native-codex/sessions", "home", "logs", "shots"):
        (work / name).mkdir(parents=True)
    folder = Path(tempfile.mkdtemp(prefix="filigree-journey-")).resolve()
    precondition(git_root(folder) is None, "un dossier synthétique est dans un dépôt Git ; abandon")
    paths = {"work": work, "memory": work / "memory", "db": work / "tap" / "traces.sqlite3", "reader_db": work / "tap-reader" / "traces.sqlite3",
             "claude_config": work / "native-claude", "codex_home": work / "native-codex", "home": work / "home", "shots": work / "shots",
             "mcp_config": work / "mcp-config.json", "folder": folder, "nonce": "LANTERN-" + secrets.token_hex(4).upper()}
    real_db = tap_source.resolve_db_path({}, {k: v for k, v in os.environ.items() if k != "CLOUDTAP_DB"})
    for key in ("db", "reader_db", "memory", "claude_config", "codex_home", "home", "shots", "mcp_config"):
        precondition(inside(paths[key], ROOT / ".runtime" / "live-journey"), f"emplacement non isolé : {key}")
    precondition(paths["db"].resolve() != real_db and paths["reader_db"].resolve() != real_db, "la base de test est la base claude-tap réelle")
    precondition(paths["memory"].resolve() != (Path.home() / ".filigree").resolve(), "la mémoire de test est la mémoire réelle")
    return paths


def fake_secrets() -> dict:
    """Harmless fake credentials in shapes the redaction must catch. label -> (line as written, needles that must never persist)."""
    tokens = {name: secrets.token_hex(4) for name in ("pw", "url", "basic", "key", "quoted")}
    blob = base64.b64encode(f"svc:fakebasic{tokens['basic']}".encode()).decode()
    return {
        "env_password": (f"DB_PASSWORD=fakepw{tokens['pw']}", [f"fakepw{tokens['pw']}"]),
        "url_credentials": (f"postgres://svc_user:fakeurl{tokens['url']}@db.invalid:5432/app", [f"fakeurl{tokens['url']}"]),
        "basic_auth": (f"Authorization: Basic {blob}", [blob, f"fakebasic{tokens['basic']}"]),
        "env_api_key": (f"X_API_KEY=fakekey{tokens['key']}", [f"fakekey{tokens['key']}"]),
        "quoted_phrase": (f'"password": "fake quoted {tokens["quoted"]} words"', [tokens["quoted"]]),
    }


def needles_of(fakes) -> dict:
    return {label: needles for label, (_line, needles) in fakes.items()}


def writer_prompt(paths, fakes) -> str:
    lines = " ; ".join(line for line, _ in fakes.values())
    return (f"Synthetic project note for a test, project codename {paths['nonce']}. Decision record: we are using SQLite instead of Postgres for the {paths['nonce']} app, "
            "because it is a single-user offline desktop tool with less than 50 MB of data, and running a database server would add operations cost for no benefit. "
            f"The throwaway fake credentials of the test configuration are (not real): {lines}. "
            "Reply with one short sentence confirming the decision and the reason. Do not repeat any credential.")


def reader_folder(paths) -> Path:
    """The reader is a fresh session for the SAME project folder as the writer: the same canonical folder is its cwd and the folder named in its prompt."""
    return paths["folder"]


def canonical(path) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def check_same_project_scope(paths, prompt: str, reader_cwd) -> None:
    """Same canonical project folder for both clients, but separate TAP databases (the reader's history is its own evidence)."""
    check(canonical(reader_cwd) == canonical(paths["folder"]) == canonical(reader_folder(paths)), "le lecteur n'a pas le même dossier de projet canonique que l'écrivain")
    check(f"The project folder is {paths['folder']}. Question:" in prompt, "le prompt du lecteur ne nomme pas le dossier du projet de l'écrivain")
    check(canonical(paths["db"]) != canonical(paths["reader_db"]), "le lecteur et l'écrivain partagent la même base claude-tap")


def check_separate_sessions(writer: dict, reader: dict) -> None:
    """Two distinct Claude sessions (native ids and, when announced, claude-tap sessions): the reader inherits nothing from the writer."""
    check(writer.get("native_id") and reader.get("native_id") and writer["native_id"] != reader["native_id"], "l'écrivain et le lecteur partagent la même session Claude")
    tap_ids = [item.get("banner_tap_session") for item in (writer, reader)]
    check(not all(tap_ids) or tap_ids[0] != tap_ids[1], "l'écrivain et le lecteur partagent la même session claude-tap")


def reader_prompt(folder) -> str:
    return (f"A local project memory is available through the {SERVER} MCP tools. The project folder is {folder}. Question: {QUESTION} "
            "Use only the memory tools to find out. Reply with only one JSON object and nothing else, with exactly these keys: "
            '"choice", "reason" and "note_id" (the exact id of the memory entry your answer rests on). '
            "If the memory gives no answer, set the three values to null.")


def prompt_leaks(prompt: str, forbidden) -> list:
    low = prompt.lower()
    return [word for word in forbidden if word and word.lower() in low]


def isolation_flags(model: str) -> list:
    return ["--setting-sources", "", "--settings", '{"disableAllHooks":true}', "--disable-slash-commands", "--strict-mcp-config", "--model", model,
            "--permission-mode", "dontAsk"]


def writer_arguments(prompt: str, model: str) -> list:
    return [*isolation_flags(model), "--tools", "", "--output-format", "json", "-p", prompt]


def reader_arguments(prompt: str, model: str, mcp_config) -> list:
    flags = isolation_flags(model)
    flags[flags.index("--strict-mcp-config") + 1:flags.index("--strict-mcp-config") + 1] = ["--mcp-config", str(mcp_config)]
    return [*flags, "--tools", "", "--allowedTools", *ALLOWED, "--output-format", "json", "-p", prompt]


def child_environment(db: Path) -> tuple:
    removed = [name for name in ("CLAUDECODE", "CLAUDE_CODE_SAFE_MODE") if name in os.environ]
    env = {key: value for key, value in os.environ.items() if key not in {"CLAUDECODE", "CLAUDE_CODE_SAFE_MODE"}}
    env["CLOUDTAP_DB"] = str(db)
    return env, removed


def write_mcp_config(paths):
    config = {"mcpServers": {SERVER: {"command": str(Path(sys.executable).resolve()), "args": ["-m", "filigree", "--data-dir", str(paths["memory"].resolve()), "mcp"],
                                      "env": {"PYTHONPATH": str(ROOT), "PYTHONUTF8": "1"}}}}
    paths["mcp_config"].write_text(json.dumps(config, indent=2), encoding="utf-8")


def server_environment(paths) -> dict:
    """Every location the server (or a monitor that wrongly started) could read is explicit and synthetic."""
    home = paths["home"]
    return {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(home / "AppData"), "LOCALAPPDATA": str(home / "AppData"),
            "XDG_DATA_HOME": str(home / "xdg"), "CLOUDTAP_DB": str(paths["db"]), "CLAUDE_CONFIG_DIR": str(paths["claude_config"]),
            "CODEX_HOME": str(paths["codex_home"]), "FILIGREE_DATA_DIR": str(paths["memory"]), "PYTHONUTF8": "1"}


# ---------------------------------------------------------------------------------------------------- Claude calls

def parse_result(stdout: str):
    result = None
    for line in stdout.splitlines():
        try:
            candidate = json.loads(line)
        except ValueError:
            continue
        if isinstance(candidate, dict) and candidate.get("type") == "result":
            result = candidate
    return result


def claude_call(paths, name: str, arguments: list, db: Path, cwd: Path) -> dict:
    """The only place a model is called. Guarded by a call budget and by --check-only."""
    precondition(STATE["allow_model"], "appel modèle interdit dans ce mode")
    precondition(STATE["calls"] < MAX_CALLS, f"budget de {MAX_CALLS} appels Claude épuisé")
    claude_tap, claude = shutil.which("claude-tap"), shutil.which("claude")
    precondition(claude_tap is not None and claude is not None, "claude-tap ou claude est introuvable dans PATH (aucune installation n'est tentée)")
    env, removed = child_environment(db)
    command = [claude_tap, "--tap-no-open", "--tap-no-live", "--tap-max-traces", "0", "--", *arguments]
    options = {"creationflags": 0x00000200} if os.name == "nt" else {"start_new_session": True}
    STATE["calls"] += 1
    step(f"appel {STATE['calls']}/{MAX_CALLS} ({name}) ; au plus {CLAUDE_TIMEOUT} s, sans nouvel essai ; variables retirées : {removed or 'aucune'}")
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", **options)
    try:
        stdout, stderr = process.communicate(timeout=CLAUDE_TIMEOUT)
    except subprocess.TimeoutExpired:
        kill_tree(process)
        process.communicate()
        raise Failure(3, f"appel Claude ({name}) interrompu après {CLAUDE_TIMEOUT} s (aucun nouvel essai)")
    (paths["work"] / "logs" / f"{name}-stdout.txt").write_text(stdout, encoding="utf-8")
    (paths["work"] / "logs" / f"{name}-stderr.txt").write_text(stderr, encoding="utf-8")
    result = parse_result(stdout)
    if process.returncode != 0 or result is None or result.get("is_error"):
        raise Failure(3, f"appel Claude ({name}) en échec : code {process.returncode}, résultat {'absent' if result is None else result.get('subtype')}; détails privés dans {paths['work'] / 'logs'}")
    session_id = result.get("session_id")
    check(isinstance(session_id, str) and _SESSION.fullmatch(session_id), f"{name} : session_id natif absent ou de forme inattendue")
    denied = result.get("permission_denials") or []
    check(not denied, f"{name} : {len(denied)} outil(s) refusé(s) par la politique de permissions")
    banner = re.search(r"Trace session:\s*([A-Za-z0-9-]{8,64})", stdout)
    usage = result.get("modelUsage") if isinstance(result.get("modelUsage"), dict) else {}
    return {"answer": result.get("result"), "native_id": session_id, "banner_tap_session": banner.group(1) if banner else None, "seconds": round(time.monotonic() - started, 1),
            "turns": result.get("num_turns"), "models_reported": sorted(usage)}


def kill_tree(process):
    """Stops only the process tree this script started."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    else:
        process.kill()


# ---------------------------------------------------------------------------------------------------- observation

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


def leaf_text(value) -> str:
    parts = []
    walk(value, lambda leaf: parts.append(leaf) if isinstance(leaf, str) else None)
    return "\n".join(parts)


def summarize_payloads(payloads) -> dict:
    """UNIQUE tool calls (by tool_use id), their results (by tool_use_id) and the request models. Every API request of a
    client repeats the earlier tool blocks, so counting blocks would inflate the calls."""
    calls, results, models = {}, {}, set()

    def visit(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "tool_use" and isinstance(node.get("id"), str) and isinstance(node.get("name"), str):
            calls.setdefault(node["id"], {"name": node["name"], "input": node.get("input")})
        elif node.get("type") == "tool_result" and isinstance(node.get("tool_use_id"), str):
            results.setdefault(node["tool_use_id"], leaf_text(node.get("content")))
        if isinstance(node.get("model"), str) and "messages" in node:
            models.add(node["model"])

    for payload in payloads:
        walk(payload, visit)
    return {"calls": calls, "results": results, "models": sorted(models), "records": len(payloads)}


def tap_payloads(db_path: Path) -> list:
    connection, capability = tap_source.open_db(db_path)
    check(connection is not None, f"base claude-tap illisible : {capability}")
    payloads = []
    try:
        for session in tap_source.list_sessions(connection):
            for _index, _stamp, text, _size in tap_source.read_batch(connection, session, 0, MAX_TAP_RECORDS):
                if text is None:
                    continue
                try:
                    payloads.append(tap_source.decode_payload(connection, session, text))
                except tap_source.RecordError:
                    continue
    finally:
        connection.close()
    return payloads


def parse_reader_answer(text) -> dict:
    check(isinstance(text, str) and text.strip(), "réponse du lecteur vide")
    body = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", body, re.S)
    if fenced:
        body = fenced.group(1)
    start, end = body.find("{"), body.rfind("}")
    check(start >= 0 and end > start, "la réponse du lecteur ne contient pas d'objet JSON")
    try:
        answer = json.loads(body[start:end + 1])
    except ValueError:
        raise Failure(1, "la réponse du lecteur n'est pas un JSON valide")
    check(isinstance(answer, dict) and {"choice", "reason", "note_id"} <= set(answer), "forme de réponse inattendue (choice, reason, note_id requis)")
    return answer


def reason_groups_covered(reason) -> int:
    low = str(reason).lower()
    return sum(1 for group in REASON_GROUPS if any(word in low for word in group))


_REJECTED_ALTERNATIVE = re.compile(r"\b(?:instead of|rather than|plut[oô]t que|over|versus|vs\.?|not|and not|but not|no)[\s:]*$")


def choice_is_sqlite(choice: str) -> bool:
    """SQLite is the choice; Postgres may appear only AFTER it, introduced as the rejected alternative ("SQLite (instead of Postgres)")."""
    low = str(choice).lower()
    first = low.find("sqlite")
    if first < 0:
        return False
    for match in re.finditer("postgres", low):
        if match.start() < first or not _REJECTED_ALTERNATIVE.search(low[first:match.start()].rstrip(" (,;")):
            return False
    return True


def judge_answer(answer: dict, accepted_id: str) -> None:
    choice = str(answer.get("choice")).lower()
    check(choice_is_sqlite(choice), "le choix cité n'est pas SQLite (ou cite Postgres comme choix)")
    check(reason_groups_covered(answer.get("reason")) >= 2, "la raison citée ne reprend pas au moins deux éléments de la raison enregistrée")
    check(answer.get("note_id") == accepted_id, "l'identifiant de note cité n'est pas celui de la décision acceptée")


def scan_text_for(needles: dict, text: str) -> dict:
    """label -> number of needles present. Counts only: values are never reported."""
    return {label: sum(1 for needle in items if needle in text) for label, items in needles.items() if any(needle in text for needle in items)}


def memory_files(memory: Path):
    for path in sorted(memory.rglob("*")):
        if path.is_file() and ".capture" not in path.relative_to(memory).parts and not path.name.endswith(".lock"):
            yield path


def memory_digest(memory: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    for path in memory_files(memory):
        digest.update(str(path.relative_to(memory)).encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


# ---------------------------------------------------------------------------------------------------- server and browser

def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def http_get(origin: str, path: str):
    with urllib.request.urlopen(origin + path, timeout=20) as response:
        return response.status, response.read().decode("utf-8")


def start_server(paths) -> tuple:
    port = free_port()
    command = [sys.executable, "-m", "filigree", "--data-dir", str(paths["memory"]), "serve", "--port", str(port), "--no-capture"]
    log = open(paths["work"] / "logs" / "server.txt", "w", encoding="utf-8")
    options = {"creationflags": 0x00000200} if os.name == "nt" else {"start_new_session": True}
    env = server_environment(paths)
    process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, **options)
    origin = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + SERVER_WAIT
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise Failure(2, f"le serveur local s'est arrêté au démarrage (code {process.returncode}) ; journal privé dans {paths['work'] / 'logs' / 'server.txt'}")
        try:
            if http_get(origin, "/")[0] == 200:
                return process, origin
        except OSError:
            time.sleep(0.2)
    kill_tree(process)
    raise Failure(2, f"le serveur local n'a pas répondu en {SERVER_WAIT} s")


def verify_capture_disabled(origin: str) -> None:
    status = json.loads(http_get(origin, "/api/capture")[1])
    check(status.get("enabled") is False and status.get("disabled_by_server") is True and status.get("running") is False and not status.get("native", {}).get("roots"),
          "le serveur --no-capture annonce une capture active ou des racines de sources")
    check(status.get("tap", {}).get("capability") == "disabled", "le serveur --no-capture sonde une base claude-tap")


def run_browser(paths, mode: str, settings: dict) -> dict:
    config_file, result_file = paths["work"] / f"browser-{mode}.json", paths["work"] / f"browser-{mode}-result.json"
    config = {**settings, "mode": mode, "result": str(result_file), "shots": str(paths["shots"]), "prefix": mode}
    config_file.write_text(json.dumps(config), encoding="utf-8")
    precondition(shutil.which("node") is not None, "node est introuvable dans PATH")
    precondition((ROOT / "node_modules" / "@playwright" / "test").is_dir(), "Playwright n'est pas installé (aucune installation n'est tentée)")
    process = subprocess.Popen(["node", str(BROWSER), str(config_file)], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    try:
        stdout, stderr = process.communicate(timeout=BROWSER_TIMEOUT)
    except subprocess.TimeoutExpired:
        kill_tree(process)
        process.communicate()
        raise Failure(1, f"le navigateur ({mode}) a dépassé {BROWSER_TIMEOUT} s")
    (paths["work"] / "logs" / f"browser-{mode}-stderr.txt").write_text(stderr + stdout, encoding="utf-8")
    result = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else {"ok": False, "error": "aucun résultat écrit"}
    error = result.get("error") or ""
    precondition("Executable doesn't exist" not in error, "Chromium de Playwright est absent (aucune installation n'est tentée)")
    check(result.get("ok") is True and process.returncode == 0, f"navigateur ({mode}) en échec : {error[:200] or 'fuites ' + str(result.get('leaks'))} ; contrôles {result.get('checks')}")
    return result


# ---------------------------------------------------------------------------------------------------- verification

def pick_proposal(store: Store, project_id: str, nonce: str) -> dict:
    entries = [entry for entry in store.list_entries(project_id) if nonce in entry["body"] and "sqlite" in entry["body"].lower()]
    check(entries, "aucune proposition capturée n'énonce la décision (codename et SQLite)")
    entries.sort(key=lambda entry: (0 if "user-text" in entry["tags"] else 1 if "assistant-text" in entry["tags"] else 2, entry["id"]))
    return entries[0]


def persisted_leaks(paths, origin: str, project_id: str, needles: dict) -> dict:
    """Raw fake credentials in memory files, entries, history, export and handoff. label -> count; nothing else is returned."""
    found = {}
    def add(text):
        for label, count in scan_text_for(needles, text).items():
            found[label] = found.get(label, 0) + count
    for path in memory_files(paths["memory"]):
        add(path.read_bytes().decode("utf-8", errors="replace"))
    store = Store(paths["memory"])
    for entry in store.list_entries(project_id):
        add(json.dumps(entry, ensure_ascii=False))
        add(json.dumps(store.list_history(project_id, entry["id"]), ensure_ascii=False))
    add(http_get(origin, f"/api/projects/{project_id}/export")[1])
    add(http_get(origin, f"/api/projects/{project_id}/handoff")[1])
    add(http_get(origin, f"/api/projects/{project_id}/handoff?query={urllib.parse.quote('SQLite')}")[1])
    return found


def verify_review(paths, origin: str, project_id: str, entry_id: str, before_status: str) -> dict:
    store = Store(paths["memory"])
    entry = next((item for item in store.list_entries(project_id) if item["id"] == entry_id), None)
    check(entry is not None and entry["status"] == "accepted" and entry["kind"] == "decision", "l'entrée n'est pas une décision acceptée après l'interface")
    history = store.list_history(project_id, entry_id)
    events = [event for event in store.list_events(project_id) if entry_id in event.get("entry_ids", [])]
    accept = [event for event in events if event.get("action") == "entry.updated" and "journey-accept" in str(event.get("reason")) and event.get("revisions", {}).get(entry_id) == entry["revision"]]
    check(len(accept) == 1 and accept[0].get("channel") == "http-ui", "la raison explicite d'acceptation n'est pas dans le journal d'événements (canal interface)")
    others = [item for item in store.list_entries(project_id) if item["id"] != entry_id and item["status"] != "proposed"]
    check(not others, "une autre entrée a changé de statut pendant la revue")
    handoff = json.loads(http_get(origin, f"/api/projects/{project_id}/handoff")[1])
    reference = next((item for item in handoff.get("references", []) if item.get("id") == entry_id), None)
    check(reference is not None and reference.get("current") is True and reference.get("status") == "accepted", "la fiche de reprise ne présente pas la décision comme courante")
    return {"revisions": entry["revision"], "history_items": len(history), "status_before": before_status}


# ---------------------------------------------------------------------------------------------------- modes

def seed_fixture(paths) -> tuple:
    """--check-only only: one proposal shaped like a tap capture, to exercise the browser and API plumbing."""
    store = Store(paths["memory"])
    project = store.create_project("Projet fictif de contrôle", "", folder=str(paths["folder"]))
    native = "fixture-native-0001"
    event = {"title": "Utilisateur · Nous choisissons SQLite", "body": f"{paths['nonce']} : nous choisissons SQLite plutôt que Postgres (fixture).", "agent": "Humain via Claude Code", "episode": native,
             "timestamp": "2026-10-16T10:00:00+00:00", "sources": [{"label": "claude-tap · claude · fixture #1", "uri": "tap:fixture-0000:1:u-0", "excerpt": "fixture"}],
             "tags": ["capture", "claude-tap", "user-text"],
             "provenance": {"collector": "claude-tap", "native_id": native, "link": "native", "cwd": str(paths["folder"]), "tap_db_key": "k", "tap_session_id": "fixture-0000", "record_index": 1, "payload_sha256": "00"}}
    store.import_events(project["id"], [event], "claude-tap", internal=True)
    entry = pick_proposal(store, project["id"], paths["nonce"])
    return project["id"], entry, native


def browser_settings(origin, project_id, entry, native_id, paths, fakes) -> dict:
    return {"origin": origin, "projectId": project_id, "entryId": entry["id"], "nativeId": native_id, "folderName": paths["folder"].name,
            "needles": [needle for _line, items in fakes.values() for needle in items], "convert": entry["kind"] != "decision",
            "convertReason": "journey-convert : cette connaissance énonce une décision d'architecture.", "acceptReason": "journey-accept : acceptée par le relecteur de l'essai, la raison est vérifiée dans l'historique."}


def check_commands(paths, fakes, model: str) -> dict:
    """Plumbing facts that need no model: prompts hold no answer, commands carry the isolation flags, MCP file is read-only."""
    wprompt, rprompt = writer_prompt(paths, fakes), reader_prompt(reader_folder(paths))
    check_same_project_scope(paths, rprompt, reader_folder(paths))
    check(not prompt_leaks(rprompt, ["sqlite", "postgres", "single-user", "offline", "50 mb", paths["nonce"]]), "le prompt du lecteur contient un élément de la réponse")
    check(not _SHELL_META.search(wprompt) and not _SHELL_META.search(rprompt), "un prompt contient un métacaractère de shell (risque avec un shim .cmd)")
    wargs, rargs = writer_arguments(wprompt, model), reader_arguments(rprompt, model, paths["mcp_config"])
    check("--tools" in wargs and wargs[wargs.index("--tools") + 1] == "" and "--allowedTools" not in wargs and "--mcp-config" not in wargs, "l'écrivain doit n'avoir ni outil ni MCP")
    check("--safe-mode" not in rargs and "--safe-mode" not in wargs, "--safe-mode désactiverait MCP : interdit ici")
    check(rargs[rargs.index("--allowedTools") + 1:rargs.index("--allowedTools") + 1 + len(ALLOWED)] == ALLOWED and "--strict-mcp-config" in rargs, "le lecteur doit avoir uniquement les outils de lecture, en MCP strict")
    check(f"mcp__{SERVER}__propose_memory" not in rargs, "propose_memory ne doit pas être autorisé")
    config = json.loads(paths["mcp_config"].read_text(encoding="utf-8"))
    check(list(config["mcpServers"]) == [SERVER] and str(paths["memory"].resolve()) in config["mcpServers"][SERVER]["args"], "la configuration MCP ne vise pas la mémoire isolée")
    env, removed = child_environment(paths["db"])
    check("CLAUDECODE" not in env and "CLAUDE_CODE_SAFE_MODE" not in env and env["CLOUDTAP_DB"] == str(paths["db"]), "environnement enfant incorrect")
    shim = shutil.which("claude-tap")
    return {"claude_tap_found": shim is not None, "claude_found": shutil.which("claude") is not None, "claude_tap_suffix": Path(shim).suffix if shim else None, "markers_removed_from_children": removed}


def check_only(paths, args, timings, debug) -> int:
    STATE["allow_model"] = False
    fakes = fake_secrets()
    create_baseline_db(paths["db"])
    create_baseline_db(paths["reader_db"])
    capture = isolated_capture(paths)
    baseline = capture.scan_once()
    check(baseline.get("baseline") is True and capture.status()["tap"]["baselined"], "la ligne de base de la base vide n'est pas enregistrée")
    roots = {name: Path(root).resolve() for name, root in capture.status()["native"]["roots"].items()}
    check(roots and all(inside(root, paths["work"]) for root in roots.values()), "une racine native lue par la capture n'est pas isolée")
    write_mcp_config(paths)
    debug["commands"] = check_commands(paths, fakes, args.model)
    step("isolation, bases de départ, configuration MCP, drapeaux et prompts vérifiés")
    project_id, entry, native = seed_fixture(paths)
    process, origin = start_server(paths)
    debug["server_pid"] = process.pid
    try:
        verify_capture_disabled(origin)
        started = time.monotonic()
        review = run_browser(paths, "review", browser_settings(origin, project_id, entry, native, paths, fakes))
        lap(timings, "browser_review", started)
        debug["browser_review"] = review["checks"]
        debug["review"] = verify_review(paths, origin, project_id, entry["id"], entry["status"])
        check(not persisted_leaks(paths, origin, project_id, needles_of(fakes)), "fuite de faux secret dans les fichiers persistés")
        started = time.monotonic()
        scan = run_browser(paths, "scan", browser_settings(origin, project_id, entry, native, paths, fakes))
        lap(timings, "browser_scan", started)
        debug["browser_scan"] = {"scans": scan["scans"], "leaks": scan["leaks"], "screenshots": len(scan["screenshots"])}
    finally:
        kill_tree(process)
    check(STATE["calls"] == 0, "un appel modèle a eu lieu en --check-only")
    step(f"PASS (--check-only) : isolation et plomberie vérifiées sur une FIXTURE synthétique ; {STATE['calls']} appel modèle ; ce n'est PAS un PASS live.")
    return 0


def live(paths, args, timings, debug) -> int:
    fakes = fake_secrets()
    needles = needles_of(fakes)
    create_baseline_db(paths["db"])
    create_baseline_db(paths["reader_db"])
    capture = isolated_capture(paths)
    baseline = capture.scan_once()
    check(baseline.get("baseline") is True and capture.status()["tap"]["baselined"] and capture.status()["tap"]["sessions"] == 0, "la ligne de base de la base vide n'est pas enregistrée")
    write_mcp_config(paths)
    debug["commands"] = check_commands(paths, fakes, args.model)
    precondition(debug["commands"]["claude_tap_found"] and debug["commands"]["claude_found"], "claude ou claude-tap est introuvable dans PATH")
    # 1. writer
    started = time.monotonic()
    writer = claude_call(paths, "writer", writer_arguments(writer_prompt(paths, fakes), args.model), paths["db"], paths["folder"])
    lap(timings, "writer_call", started)
    debug["writer"] = {key: value for key, value in writer.items() if key != "answer"}
    step(f"écrivain : réponse en {writer['seconds']} s ; modèle(s) annoncé(s) {writer['models_reported']}")
    # 2. capture
    started = time.monotonic()
    cwd = copy_metadata(find_transcript(writer["native_id"]), writer["native_id"], paths)
    capture_facts = verify_capture(paths, capture, writer, cwd)
    store = Store(paths["memory"])
    check(not [entry for entry in store.list_entries(capture_facts["project_id"]) if entry["status"] != "proposed"], "une entrée acceptée existait avant la revue humaine")
    entry = pick_proposal(store, capture_facts["project_id"], paths["nonce"])
    debug["capture"] = {**capture_facts, "chosen_kind": entry["kind"], "chosen_tags": entry["tags"]}
    lap(timings, "capture", started)
    early = {}
    for path in memory_files(paths["memory"]):
        early.update(scan_text_for(needles, path.read_bytes().decode("utf-8", errors="replace")))
    check(not early, f"faux secrets bruts dans la mémoire dès la capture : {sorted(early)}")
    step(f"capture : {capture_facts['entries']} proposition(s) vérifiée(s), projet créé pour le bon dossier, aucune fuite")
    # 3. server + browser
    process, origin = start_server(paths)
    debug["server_pid"] = process.pid
    try:
        verify_capture_disabled(origin)
        started = time.monotonic()
        review = run_browser(paths, "review", browser_settings(origin, capture_facts["project_id"], entry, writer["native_id"], paths, fakes))
        lap(timings, "browser_review", started)
        debug["browser_review"] = {"checks": review["checks"], "timings_ms": review["timings"], "screenshots": review["screenshots"]}
        check(all(review["checks"].get(name) for name in ("provenance_card", "origin_tap", "session_id_visible", "folder_visible", "accepted_through_ui")), f"provenance ou acceptation non observées dans la page : {review['checks']}")
        debug["review"] = verify_review(paths, origin, capture_facts["project_id"], entry["id"], entry["status"])
        accepted_id = entry["id"]
        step("revue humaine en navigateur réel : proposition localisée, provenance visible, acceptée avec raison ; fiche de reprise : courante")
        # 4. reader
        before = {item["id"]: (item["status"], item["revision"]) for item in store.list_entries(capture_facts["project_id"])}
        digest = memory_digest(paths["memory"])
        prompt = reader_prompt(reader_folder(paths))
        reader_cwd = reader_folder(paths)
        check_same_project_scope(paths, prompt, reader_cwd)
        check(not prompt_leaks(prompt, [accepted_id, "sqlite", "postgres", paths["nonce"]]), "le prompt du lecteur contient la réponse ou l'identifiant")
        started = time.monotonic()
        reader = claude_call(paths, "reader", reader_arguments(prompt, args.model, paths["mcp_config"]), paths["reader_db"], reader_cwd)
        check_separate_sessions(writer, reader)
        lap(timings, "reader_call", started)
        observed = summarize_payloads(tap_payloads(paths["reader_db"]))
        names = {}
        for call in observed["calls"].values():
            names[call["name"]] = names.get(call["name"], 0) + 1
        debug["reader"] = {**{key: value for key, value in reader.items() if key != "answer"}, "cwd_is_writer_project_folder": canonical(reader_cwd) == canonical(paths["folder"]),"tap_models": observed["models"], "unique_tool_calls": len(observed["calls"]), "tool_names": names, "tap_records": observed["records"]}
        check(observed["calls"], "aucun appel d'outil observé dans l'historique claude-tap du lecteur")
        check(set(names) <= set(ALLOWED), f"outil(s) inattendu(s) appelé(s) : {sorted(set(names) - set(ALLOWED))}")
        check(set(names) & CONTENT_TOOLS, "ni search_memory ni get_handoff n'a été appelé : le contenu n'a pas pu être lu")
        with_id = [cid for cid, call in observed["calls"].items() if call["name"] in CONTENT_TOOLS and accepted_id in observed["results"].get(cid, "")]
        without_id = [cid for cid, call in observed["calls"].items() if call["name"] in CONTENT_TOOLS and cid not in with_id]
        debug["reader"].update({"content_calls_returning_note": len(with_id), "content_calls_without_note": len(without_id)})
        check(with_id, f"aucun résultat d'outil de contenu ne contient la décision acceptée ({len(without_id)} appel(s) de contenu sans elle) : recherche à vide côté client réel")
        answer = parse_reader_answer(reader["answer"])
        judge_answer(answer, accepted_id)
        after = {item["id"]: (item["status"], item["revision"]) for item in Store(paths["memory"]).list_entries(capture_facts["project_id"])}
        check(after == before and memory_digest(paths["memory"]) == digest, "la mémoire a changé pendant l'appel du lecteur")
        step("lecteur : choix, raison et identifiant exact corrects ; appels MCP de lecture observés ; mémoire inchangée")
        # 5. leaks
        found = persisted_leaks(paths, origin, capture_facts["project_id"], needles)
        check(not found, f"faux secrets bruts dans les données persistées/exportées : {sorted(found)}")
        started = time.monotonic()
        scan = run_browser(paths, "scan", browser_settings(origin, capture_facts["project_id"], entry, writer["native_id"], paths, fakes))
        lap(timings, "browser_scan", started)
        debug["browser_scan"] = {"scans": scan["scans"], "leaks": scan["leaks"], "screenshots": scan["screenshots"]}
    finally:
        kill_tree(process)
    debug["verified"] = {"calls": STATE["calls"], "model_requested": args.model, "writer_models": writer["models_reported"], "reader_models": reader["models_reported"], "tap_request_models": observed["models"]}
    print(f"PASS (live): {STATE['calls']} appel(s) Claude (modèle demandé {args.model} ; annoncé {sorted(set(writer['models_reported']) | set(reader['models_reported']))} ; vu par TAP {observed['models']}), "
          f"{capture_facts['entries']} proposition(s) capturée(s), acceptation par navigateur réel, lecteur MCP : {len(observed['calls'])} appel(s) unique(s) {names}, "
          f"{len(with_id)} résultat(s) de contenu avec la note, identifiant exact, mémoire inchangée, 0 fuite.")
    print("Portée : un écrivain et un lecteur Claude Code sur cette machine ; ni Codex, ni d'autres versions ; aucune authentification d'humain n'est prouvée.")
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check-only", action="store_true", help="verify isolation and plumbing with a synthetic fixture; make no model call")
    parser.add_argument("--model", default="sonnet", help="model alias for the writer and the reader (default sonnet)")
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    debug, timings, paths, started = {"stamp": stamp, "mode": "check-only" if args.check_only else "live"}, {}, None, time.monotonic()
    code = 1
    try:
        paths = prepare(stamp)
        step(f"travail isolé : {paths['work']}")
        code = check_only(paths, args, timings, debug) if args.check_only else live(paths, args, timings, debug)
        return code
    except Failure as failure:
        debug["failure"] = {"code": failure.code, "message": str(failure)}
        print(f"FAIL ({'assertion' if failure.code == 1 else 'précondition' if failure.code == 2 else 'appel live'}): {failure}", file=sys.stderr)
        code = failure.code
        return code
    finally:
        if paths is not None:
            timings["total"] = round(time.monotonic() - started, 1)
            debug.update({"timings_s": timings, "claude_calls": STATE["calls"], "exit_code": code})
            (paths["work"] / "debug.json").write_text(json.dumps(debug, indent=1, default=str), encoding="utf-8")
            print(f"[live-journey] appels Claude : {STATE['calls']} ; durées (s) : {timings} ; diagnostic privé : {paths['work'] / 'debug.json'} (aucun nettoyage automatique)", flush=True)


if __name__ == "__main__":
    sys.exit(main())
