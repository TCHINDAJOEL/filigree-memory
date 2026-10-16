"""Manual, opt-in live smoke check: one real Claude Code (haiku) exchange through claude-tap, captured by Filigree.

Not part of the unit or CI suites; run it deliberately:  python -X utf8 scripts/verify_live_capture.py
It makes exactly one bounded `claude-tap` invocation (300 s maximum, no retry) in a synthetic folder, against a
fresh claude-tap database and a fresh Filigree memory under .runtime/live-capture/<stamp>/. It never reads or
writes the user's own claude-tap database or Filigree memory, and it reads only the transcript of the session it
just created, copying nothing but `sessionId` and `cwd` into an isolated native-index root.

It asserts, with no guessing: the tap session that claims the returned native session id, the project folder
created for the synthetic folder, a synthetic marker seen through the real agent exchange, the `proposed` status
and the provenance. It does not claim support for any other client, version or platform.

`--native-direct` is a second, separate mode (also one bounded Haiku call): it launches the real `claude` command
WITHOUT claude-tap, in a new synthetic folder, with the native fallback enabled and the tap source disabled. A
baseline of the empty isolated native root is taken first; afterwards only the one transcript file named exactly
<session_id>.jsonl is copied, byte for byte, into the isolated native root (no other transcript is listed or
opened, and no raw transcript text is printed). The inherited CLAUDECODE nested-session marker, and a loopback
ANTHROPIC_BASE_URL that a parent claude-tap would have injected, are removed from that one child's environment
only; nothing global is modified.

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
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from filigree import tap_source  # noqa: E402  (repository source, not an installed copy)
from filigree.capture import Capture  # noqa: E402
from filigree.store import Store  # noqa: E402

CLAUDE_TIMEOUT = 300
TRANSCRIPT_WAIT = 15
HEAD_BYTES = 256 * 1024
MAX_TAP_RECORDS = 500
MAX_TRANSCRIPT_BYTES = 8 * 1024 * 1024
DIRECT_SCAN_WAIT = 90  # the native fallback waits FALLBACK_GRACE (20 s) for claude-tap before it reads a fresh file
_SESSION = re.compile(r"[A-Za-z0-9-]{8,64}")
_BANNER = re.compile(r"Trace session:\s*([A-Za-z0-9-]{8,64})")
# The documented empty claude-tap schema v4 (claude_tap/trace_store.py), written by hand with the stdlib.
BASELINE_DDL = (
    "CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at TEXT NOT NULL, updated_at TEXT NOT NULL, date_key TEXT NOT NULL, client TEXT NOT NULL DEFAULT '', proxy_mode TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active', record_count INTEGER NOT NULL DEFAULT 0, summary_json TEXT, legacy_source_key TEXT NOT NULL DEFAULT '', legacy_rel_path TEXT)",
    "CREATE TABLE records (session_id TEXT NOT NULL, record_index INTEGER NOT NULL, turn INTEGER, timestamp TEXT, payload_json TEXT NOT NULL, PRIMARY KEY (session_id, record_index), FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE)",
    "CREATE TABLE proxy_logs (session_id TEXT NOT NULL, line_no INTEGER NOT NULL, logged_at TEXT, level TEXT, message TEXT NOT NULL, PRIMARY KEY (session_id, line_no), FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE)",
    "CREATE TABLE migration_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE record_blobs (session_id TEXT NOT NULL, hash TEXT NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL, size_bytes INTEGER NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (session_id, hash), FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE)",
    "CREATE INDEX idx_sessions_updated_at ON sessions(updated_at)",
    "CREATE INDEX idx_sessions_date_key ON sessions(date_key)",
    "CREATE INDEX idx_records_session_id ON records(session_id)",
    "CREATE UNIQUE INDEX idx_sessions_legacy_source_rel_path ON sessions(legacy_source_key, legacy_rel_path) WHERE legacy_rel_path IS NOT NULL",
)


class Failure(Exception):
    """A bounded, content-free reason. `code` is the process exit code."""

    def __init__(self, code: int, message: str):
        super().__init__(message[:400])
        self.code = code


def precondition(condition, message):
    if not condition:
        raise Failure(2, message)


def check(condition, message):
    if not condition:
        raise Failure(1, message)


def step(message):
    print(f"[live-capture] {message}", flush=True)


def inside(path: Path, parent: Path) -> bool:
    return parent.resolve() in [path.resolve(), *path.resolve().parents]


def git_root(folder: Path):
    return next((candidate for candidate in [folder, *folder.parents] if (candidate / ".git").exists()), None)


def prepare(stamp: str) -> dict:
    """Fresh, private locations. The synthetic project folder lives outside this repository on purpose:
    Filigree files a new project under the nearest Git root, and the repository root must not become one."""
    work = ROOT / ".runtime" / "live-capture" / stamp
    precondition(not work.exists(), "le dossier de travail existe déjà : une exécution fraîche est requise")
    for name in ("memory", "tap", "native-claude/projects", "native-codex/sessions", "logs"):
        (work / name).mkdir(parents=True)
    folder = Path(tempfile.mkdtemp(prefix="filigree-live-")).resolve()
    precondition(git_root(folder) is None, "le dossier synthétique est dans un dépôt Git ; abandon (aucune création de projet à la racine d'un dépôt)")
    nonce = "FILIGREE-LIVE-" + secrets.token_hex(8)
    (folder / "marker.txt").write_text(f"Synthetic marker: {nonce}\n", encoding="utf-8")
    paths = {"work": work, "memory": work / "memory", "db": work / "tap" / "traces.sqlite3", "claude_config": work / "native-claude", "codex_home": work / "native-codex", "folder": folder, "nonce": nonce}
    default_db = tap_source.resolve_db_path({}, {k: v for k, v in os.environ.items() if k != "CLOUDTAP_DB"})
    precondition(paths["db"].resolve() != default_db and inside(paths["db"], ROOT / ".runtime"), "la base de test n'est pas isolée")
    precondition(inside(paths["memory"], ROOT / ".runtime") and paths["memory"].resolve() != (Path.home() / ".filigree").resolve(), "la mémoire de test n'est pas isolée")
    return paths


def create_baseline_db(path: Path):
    connection = sqlite3.connect(path)
    try:
        for statement in BASELINE_DDL:
            connection.execute(statement)
        connection.execute("PRAGMA user_version = 4")
        connection.commit()
    finally:
        connection.close()
    probe = tap_source.probe(path)
    precondition(probe["capability"] == "ok" and probe["sessions"] == 0, f"base de départ invalide : {probe['capability']}")


def isolated_capture(paths, direct=False) -> Capture:
    # This environment is for Filigree only; the Claude child process keeps the user's real configuration.
    env = {"CLOUDTAP_DB": str(paths["db"]), "CLAUDE_CONFIG_DIR": str(paths["claude_config"]), "CODEX_HOME": str(paths["codex_home"])}
    capture = Capture(Store(paths["memory"]), env=env)
    capture.refresh_interval = capture.index_interval = 0
    if direct:
        # Direct launch: no claude-tap, so the tap source is off and the native fallback (enabled by default) is the only path.
        settings, error = capture.settings()
        precondition(error is None, "réglages de capture invalides")
        settings["tap"]["enabled"] = False
        capture._save_settings(settings)
    else:
        capture.set_native_fallback(False)  # this check is about the exact tap ↔ native identifier link
    return capture


def direct_environment() -> tuple:
    """Environment of the one direct `claude` child: the nested-session marker and any loopback proxy URL injected by a
    parent claude-tap are dropped, so that the call really bypasses TAP. Returns (env, names removed); values are never kept."""
    env, removed = dict(os.environ), []
    if "CLAUDECODE" in env:
        removed.append("CLAUDECODE")
    for name in ("ANTHROPIC_BASE_URL", "OPENAI_BASE_URL"):
        if re.match(r"https?://(127\.0\.0\.1|localhost|\[::1\])(:|/|$)", env.get(name, "")):
            removed.append(name)
    for name in removed:
        env.pop(name, None)
    return env, removed


def run_claude(paths, direct=False) -> dict:
    claude_tap = shutil.which("claude-tap")
    precondition(direct or claude_tap is not None, "claude-tap est introuvable dans PATH (aucune installation n'est tentée)")
    claude = shutil.which("claude")
    precondition(claude is not None, "claude est introuvable dans PATH (aucune installation n'est tentée)")
    prompt = ("Synthetic integration check. Use the Read tool exactly once on the file marker.txt in the current folder, then answer in one short "
              "sentence quoting the marker token written in that file. Use no other tool and read no other file.")
    arguments = ["--safe-mode", "--strict-mcp-config", "--model", "haiku", "--permission-mode", "dontAsk",
                 "--tools", "Read", "--allowedTools", "Read(./marker.txt)", "--output-format", "json", "-p", prompt]
    if direct:
        command = [claude, *arguments]
        env, removed = direct_environment()
        step(f"lancement direct de claude (sans claude-tap) ; variables retirées pour ce seul enfant : {removed or 'aucune'}")
    else:
        command = [claude_tap, "--tap-no-open", "--tap-no-live", "--tap-max-traces", "0", "--", *arguments]
        env = {**os.environ, "CLOUDTAP_DB": str(paths["db"])}
    options = {"creationflags": 0x00000200} if os.name == "nt" else {"start_new_session": True}
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=paths["folder"], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", **options)
    try:
        stdout, stderr = process.communicate(timeout=CLAUDE_TIMEOUT)
    except subprocess.TimeoutExpired:
        # Stop only the process tree this script started; there is no retry.
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
    denied = result.get("permission_denials") or []
    session_id = result.get("session_id")
    check(isinstance(session_id, str) and _SESSION.fullmatch(session_id), "session_id natif absent ou de forme inattendue")
    check(not denied, f"{len(denied)} outil(s) refusé(s) par la politique de permissions ; le marqueur n'a pas pu être lu comme prévu")
    banner = _BANNER.search(stdout)
    check(not direct or banner is None, "une bannière claude-tap est apparue : l'appel direct est passé par TAP")
    return {"native_id": session_id, "banner_tap_session": banner.group(1) if banner else None, "seconds": round(time.monotonic() - started, 1), "turns": result.get("num_turns")}


def find_transcript(session_id: str) -> Path:
    """Only a file named exactly <session_id>.jsonl is considered; no other transcript is opened or listed."""
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    projects = config / "projects"
    deadline = time.monotonic() + TRANSCRIPT_WAIT
    while True:
        matches = [Path(entry.path) / f"{session_id}.jsonl" for entry in os.scandir(projects) if entry.is_dir(follow_symlinks=False)] if projects.is_dir() else []
        matches = [path for path in matches if path.is_file()]
        if matches or time.monotonic() >= deadline:
            break
        time.sleep(1)
    precondition(projects.is_dir(), f"répertoire de transcriptions Claude introuvable : {projects}")
    precondition(len(matches) == 1, f"transcription native de la session introuvable ou ambiguë ({len(matches)} fichier(s) nommé(s) d'après la session sous {projects})")
    return matches[0]


def copy_metadata(transcript: Path, session_id: str, paths, full=False) -> str:
    with open(transcript, "rb") as handle:
        head = handle.read(HEAD_BYTES)
    cwds = []
    for raw in head.split(b"\n")[:-1] if len(head) == HEAD_BYTES else head.split(b"\n"):
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("sessionId") == session_id and isinstance(row.get("cwd"), str) and row["cwd"] not in cwds:
            cwds.append(row["cwd"])
    check(len(cwds) == 1, f"la transcription nomme {len(cwds)} dossier(s) pour la session ; rien n'est deviné")
    check(os.path.exists(cwds[0]) and os.path.samefile(cwds[0], paths["folder"]), "le dossier de la transcription n'est pas le dossier synthétique de l'essai")
    target = paths["claude_config"] / "projects" / "-live" / f"{session_id}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    if full:
        # Direct launch: the adapter needs the real lines. Exactly this test's transcript, copied unread, never printed.
        check(transcript.stat().st_size <= MAX_TRANSCRIPT_BYTES, "la transcription de l'essai dépasse la taille bornée ; non copiée")
        shutil.copyfile(transcript, target)
    else:
        target.write_text(json.dumps({"sessionId": session_id, "cwd": cwds[0]}) + "\n", encoding="utf-8")
    return cwds[0]


def tap_claims(db_path: Path, native_id: str) -> dict:
    """{tap_session: claimed native ids} for the sessions of the isolated database; ids only, no text kept."""
    connection, capability = tap_source.open_db(db_path)
    check(connection is not None, f"base claude-tap illisible après l'appel : {capability} (CLOUDTAP_DB ignoré ou schéma différent)")
    claims = {}
    try:
        for session, _info in tap_source.list_sessions(connection).items():
            claimed = set()
            for _index, _stamp, text, _size in tap_source.read_batch(connection, session, 0, MAX_TAP_RECORDS):
                if text is None:
                    continue
                try:
                    claimed |= {value for _kind, value in tap_source.native_ids(tap_source.decode_payload(connection, session, text))}
                except tap_source.RecordError:
                    continue
            claims[session] = claimed
    finally:
        connection.close()
    return claims


def provenance(entry: dict) -> dict:
    source = next((item for item in entry["sources"] if item["label"] == "Provenance de capture"), None)
    check(source is not None, "une entrée capturée n'a pas de provenance")
    return json.loads(source["excerpt"])


def verify(paths, capture: Capture, live: dict, cwd: str) -> dict:
    native_id = live["native_id"]
    store = capture.store
    claims = tap_claims(paths["db"], native_id)
    check(claims, "aucune session claude-tap dans la base isolée après l'appel")
    claimants = [session for session, ids in claims.items() if native_id in ids]
    check(len(claimants) == 1, f"{len(claimants)} session(s) claude-tap déclarent l'identifiant natif retourné (une seule attendue)")
    tap_session = claimants[0]
    check(claims[tap_session] == {native_id}, "la session claude-tap déclare des identifiants natifs contradictoires")
    if live["banner_tap_session"]:
        check(live["banner_tap_session"] == tap_session, "la session annoncée par claude-tap diffère de celle qui déclare l'identifiant natif")
    check(store.locate_project(str(paths["folder"])) is None, "un projet existait déjà pour le dossier synthétique")
    capture.scan_once()
    capture.scan_once()
    check(Path(capture.tap_status["path"]).resolve() == paths["db"].resolve(), "la capture n'a pas lu la base isolée")
    check(capture.tap_status["capability"] == "ok", f"capacité tap inattendue : {capture.tap_status['capability']}")
    project = store.locate_project(str(paths["folder"]))
    check(project is not None, f"aucun projet créé pour le dossier synthétique ; en attente : {[(p['key'][:12], p['reason']) for p in capture.pending()]}")
    check(os.path.samefile(project["folder"]["path"], paths["folder"]), "le projet créé ne pointe pas sur le dossier synthétique")
    check([item["id"] for item in store.list_projects()] == [project["id"]], "la mémoire isolée contient un autre projet")
    check(not capture.pending(), "des sessions restent en attente")
    entries = store.list_entries(project["id"])
    check(entries, "le projet ne contient aucune proposition")
    check({entry["status"] for entry in entries} == {"proposed"}, "une entrée capturée n'est pas à l'état proposé")
    key = tap_source.db_key(paths["db"].resolve())
    for entry in entries:
        found = provenance(entry)
        check((found.get("collector"), found.get("tap_session_id"), found.get("native_id"), found.get("link"), found.get("native_source")) == ("claude-tap", tap_session, native_id, "native", "claude"), "provenance incohérente avec la session tap et l'identifiant natif")
        check(found.get("tap_db_key") == key and found.get("cwd") and os.path.samefile(found["cwd"], cwd), "provenance : base ou dossier incohérent")
        check({"capture", "claude-tap", "lien-natif"} <= set(entry["tags"]), "étiquettes de capture manquantes")
    marked = [entry for entry in entries if paths["nonce"] in entry["body"]]
    check(marked, "le marqueur synthétique n'apparaît dans aucune proposition (lecture réelle non observée)")
    count = len(entries)
    capture.scan_once()
    check(len(store.list_entries(project["id"])) == count, "un nouveau scan a dupliqué des propositions")
    return {"tap_session": tap_session, "project_id": project["id"], "entries": count, "marker_entries": len(marked), "marker_in_tool_result": any("resultat-outil" in entry["tags"] for entry in marked)}


def check_sources(entry: dict, native_id: str) -> None:
    """Exactly one native source for this session, plus only the auxiliary sources Store.import_events documents:
    the canonical `import:sha256:<hex>` fingerprint, the optional original event timestamp and the capture provenance (both without URI)."""
    native = [item for item in entry["sources"] if item["uri"].startswith("native:")]
    check(len(native) == 1, "une proposition doit avoir exactement une source native")
    check(re.fullmatch(rf"native:claude:{re.escape(native_id)}:[^:]+:\d+", native[0]["uri"]) is not None, "adresse de source native inattendue")
    counts = {"import": 0, "timestamp": 0, "provenance": 0}
    for item in entry["sources"]:
        if item is native[0]:
            continue
        if re.fullmatch(r"import:sha256:[0-9a-f]{64}", item["uri"]):
            counts["import"] += 1
        elif item["label"] == "Original event timestamp" and item["uri"] == "" and item.get("excerpt"):
            counts["timestamp"] += 1
        elif item["label"] == "Provenance de capture" and item["uri"] == "":
            counts["provenance"] += 1
        else:
            check(False, "source auxiliaire non documentée")
    check(counts["import"] == 1 and counts["provenance"] == 1 and counts["timestamp"] <= 1, "sources auxiliaires incohérentes (import, horodatage, provenance)")


def verify_direct(paths, capture: Capture, live: dict, cwd: str) -> dict:
    """Native-direct assertions. Only counts, identifiers and tags are inspected or printed, never transcript text."""
    native_id, store = live["native_id"], capture.store
    check(store.locate_project(str(paths["folder"])) is None, "un projet existait déjà pour le dossier synthétique")
    roots = {name: Path(root).resolve() for name, root in capture.status()["native"]["roots"].items()}
    check(all(inside(root, paths["work"]) for root in roots.values()), "une racine native lue par la capture n'est pas isolée")
    # The real fallback grace applies: a fresh file is read only after FALLBACK_GRACE, so scan until the project appears.
    deadline, project = time.monotonic() + DIRECT_SCAN_WAIT, None
    while project is None and time.monotonic() < deadline:
        capture.scan_once()
        project = store.locate_project(str(paths["folder"]))
        if project is None:
            time.sleep(3)
    check(project is not None, f"aucun projet créé pour le dossier synthétique après {DIRECT_SCAN_WAIT} s ; en attente : {[(p['key'][:12], p['reason']) for p in capture.pending()]}")
    capture.scan_once()
    check(os.path.samefile(project["folder"]["path"], paths["folder"]), "le projet créé ne pointe pas sur le dossier synthétique")
    check([item["id"] for item in store.list_projects()] == [project["id"]], "la mémoire isolée contient un autre projet")
    check(not capture.pending(), "des sessions restent en attente")
    entries = store.list_entries(project["id"])
    check(entries, "le projet ne contient aucune proposition")
    check({entry["status"] for entry in entries} == {"proposed"}, "une entrée capturée n'est pas à l'état proposé")
    for entry in entries:
        found = provenance(entry)
        expected = ("native-fallback", native_id, "claude", f"{native_id}.jsonl", "native")
        check((found.get("collector"), found.get("native_id"), found.get("native_source"), found.get("native_file"), found.get("link")) == expected, "provenance native incohérente avec la session retournée par Claude")
        check(found.get("cwd") and os.path.samefile(found["cwd"], cwd), "provenance : dossier incohérent")
        check(not found.get("tap_session_id") and not found.get("tap_db_key"), "provenance : une trace claude-tap est annoncée pour un lancement direct")
        check({"capture", "repli-natif", "claude-code"} <= set(entry["tags"]) and "claude-tap" not in entry["tags"], "étiquettes de capture natives manquantes ou inattendues")
        check(entry.get("episode") == native_id, "épisode différent de l'identifiant natif")
        check_sources(entry, native_id)
    marked = [entry for entry in entries if paths["nonce"] in entry["body"]]
    check(marked, "le marqueur synthétique n'apparaît dans aucune proposition (lecture réelle non observée)")
    state = capture._load_state()
    check(not state["fallback"]["stalled"], "des transcriptions restent retenues")
    count = len(entries)
    check(state["counters"].get("fallback_imported", 0) == count, "le compteur du repli natif ne correspond pas aux propositions")
    for _ in range(2):
        capture.scan_once()
    check(len(store.list_entries(project["id"])) == count, "un nouveau scan a dupliqué des propositions")
    return {"project_id": project["id"], "entries": count, "marker_entries": len(marked), "kinds": sorted({tag for entry in entries for tag in entry["tags"] if tag in {"user-text", "assistant-text", "tool-call", "tool-result"}})}


def main():
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check-only", action="store_true", help="prepare and verify isolation and the baseline; make no Claude call")
    parser.add_argument("--native-direct", action="store_true", help="launch `claude` directly, without claude-tap, and verify the native fallback (one bounded Haiku call)")
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    debug = {"stamp": stamp}
    paths = None
    try:
        paths = prepare(stamp)
        step(f"travail isolé : {paths['work']}")
        step(f"dossier synthétique : {paths['folder']}")
        direct = args.native_direct
        if direct:
            capture = isolated_capture(paths, direct=True)
            capture.scan_once()
            fallback = capture._load_state()["fallback"]
            check(fallback["baselined"] and not fallback["files"], "la ligne de base de la racine native vide n'est pas enregistrée")
            debug["baseline"] = {"native_files": 0, "tap": "disabled"}
            step("ligne de base enregistrée sur la racine native isolée vide ; source claude-tap désactivée")
        else:
            create_baseline_db(paths["db"])
            capture = isolated_capture(paths)
            baseline = capture.scan_once()
            check(baseline.get("baseline") is True and capture.status()["tap"]["baselined"] and capture.status()["tap"]["sessions"] == 0, "la ligne de base de la base vide n'est pas enregistrée")
            debug["baseline"] = {"tap": capture.tap_status["capability"], "sessions": 0}
            step("ligne de base enregistrée sur la base vide (schéma v4)")
        if args.check_only:
            step("PASS (--check-only) : isolation et ligne de base vérifiées ; aucun appel Claude")
            return 0
        if direct:
            step(f"appel unique claude direct, modèle haiku, au plus {CLAUDE_TIMEOUT} s, sans nouvel essai")
            live = run_claude(paths, direct=True)
            debug["live"] = live
            step(f"réponse reçue en {live['seconds']} s ; identifiant natif {live['native_id']}")
            transcript = find_transcript(live["native_id"])
            cwd = copy_metadata(transcript, live["native_id"], paths, full=True)
            step("transcription exacte de l'essai copiée dans la racine native isolée (contenu non affiché)")
            debug["verified"] = verify_direct(paths, capture, live, cwd)
            print(f"PASS (native-direct): lancement direct sans claude-tap, session {live['native_id'][:8]}, projet créé pour {paths['folder'].name}, "
                  f"{debug['verified']['entries']} proposition(s), marqueur observé ({debug['verified']['marker_entries']}), provenance native exacte, rescans sans doublon.")
            print("Portée : un seul lancement direct de Claude Code (haiku) sur cette machine, transcription copiée dans une racine isolée ; ni Codex, ni d'autres versions.")
            return 0
        step(f"appel unique claude-tap, modèle haiku, au plus {CLAUDE_TIMEOUT} s, sans nouvel essai")
        live = run_claude(paths)
        debug["live"] = live
        step(f"réponse reçue en {live['seconds']} s ; identifiant natif {live['native_id']}")
        transcript = find_transcript(live["native_id"])
        cwd = copy_metadata(transcript, live["native_id"], paths)
        step("métadonnées sessionId/cwd copiées dans la racine native isolée (aucun autre contenu)")
        debug["verified"] = verify(paths, capture, live, cwd)
        print(f"PASS: tap {debug['verified']['tap_session'][:8]} ↔ natif {live['native_id'][:8]}, projet créé pour {paths['folder'].name}, "
              f"{debug['verified']['entries']} proposition(s), marqueur observé ({debug['verified']['marker_entries']}), provenance exacte.")
        print("Portée : un seul échange Claude Code (haiku) via claude-tap sur cette machine ; aucune garantie pour d'autres clients ou versions.")
        return 0
    except Failure as failure:
        debug["failure"] = {"code": failure.code, "message": str(failure)}
        print(f"FAIL ({'assertion' if failure.code == 1 else 'précondition' if failure.code == 2 else 'appel live'}): {failure}", file=sys.stderr)
        return failure.code
    finally:
        if paths is not None:
            (paths["work"] / "debug.json").write_text(json.dumps(debug, indent=1, default=str), encoding="utf-8")
            print(f"[live-capture] diagnostic privé : {paths['work'] / 'debug.json'} (aucun nettoyage automatique)", flush=True)


if __name__ == "__main__":
    sys.exit(main())
