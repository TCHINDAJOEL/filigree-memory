"""Loopback-only HTTP API and static UI. No third-party runtime dependencies."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import re
from urllib.parse import parse_qs, urlsplit

from . import __version__
import time

from .capture import Capture, ProcessLock
from .demo import seed_demo
from .git_sync import operate, status
from .importers import parse_import, parse_text
from .store import ConflictError, Store

MAX_BODY = 8 * 1024 * 1024
# After a response sent without reading the request body, at most this much is discarded, for at most this long,
# so the client receives the answer instead of a connection reset (Windows resets a socket closed with unread data).
DRAIN_BYTES = 1024 * 1024
DRAIN_SECONDS = 2.0
STATIC = Path(__file__).parent / "static"


def _field(data, name):
    if not isinstance(data.get(name), str) or not data[name]:
        raise ValueError(f"Champ {name} requis.")
    return data[name]


def _budget(raw):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError("Le budget doit être un entier entre 500 et 100000.") from None
    if not 500 <= value <= 100000:
        raise ValueError("Le budget doit être un entier entre 500 et 100000.")
    return value


def _public(exc):
    """Expected, user-facing message: one bounded line, never a traceback or a repr."""
    text = " ".join(str(exc.args[0] if exc.args else "").split())
    return text[:300] or "Requête invalide."


class CaptureOff(Exception):
    """The server was started with --no-capture: no control can enable capture."""


class DisabledCapture:
    """Capture capability that does not exist for this server (--no-capture).

    It starts no thread and reads no source path (claude-tap database, transcript roots, settings): every control
    except `stop` is refused. The only file it ever looks at is this memory's own `.capture/capture.lock`, to report
    a monitor that another process already runs on the same data directory, and `stop` may ask that monitor to
    stop cooperatively (a `stop` file; no process is killed). Nothing is created when no monitor exists."""
    thread = None

    def __init__(self, store=None):
        self.directory = None if store is None else store.root / ".capture"

    def external_monitor_running(self) -> bool:
        lock = None if self.directory is None else self.directory / "capture.lock"
        if lock is None or not lock.is_file():
            return False  # never create .capture just to look
        probe = ProcessLock(lock)
        if probe.acquire():
            probe.release()
            return False
        return True

    def status(self):
        external = self.external_monitor_running()
        return {
            "enabled": False, "disabled_by_server": True, "paused_all": False, "auto_create": False, "settings_error": None,
            "running": external, "external_monitor_running": external, "in_process": False, "tap": {"path": "", "capability": "disabled", "sessions": 0, "baselined": False},
            "native": {"index": False, "fallback": False, "roots": {}}, "counters": {}, "skipped": {}, "malformed": {}, "notices": [],
            "last_scan": None, "pending": [], "paused": [], "exclude": [], "mappings": 0, "mappings_other_database": 0,
        }

    def stop(self, timeout=0):
        pass

    def request_stop(self, wait=0):
        if not self.external_monitor_running():
            return "not_running"
        (self.directory / "stop").write_text("stop requested by a --no-capture server", encoding="utf-8")
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if not self.external_monitor_running():
                (self.directory / "stop").unlink(missing_ok=True)
                return "stopped"
            time.sleep(0.1)
        return "stop_requested"

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise CaptureOff()  # any control (start, set_enabled, link, scan...) is refused


KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{43,256}")


def agent_key(root) -> str:
    """<data-dir>/.runtime/agent.key: created once, then reused by every server, MCP and hook of this data folder.

    Owner-only permissions are applied where the OS supports them; any process of the same OS user can still read it."""
    path = Path(root) / ".runtime" / "agent.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(secrets.token_urlsafe(32))
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    key = path.read_text(encoding="ascii", errors="replace").strip()
    if not KEY_PATTERN.fullmatch(key):
        raise ValueError(f"Clé locale illisible ou corrompue : supprimez {path} puis relancez Filigree (une nouvelle clé sera créée).")
    return key


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    # The default backlog (5) makes Windows reset connections when a page load and its polling open several at once.
    request_queue_size = 128
    # On Windows SO_REUSEADDR lets a second process share a listening port: the exclusive option is used there instead.
    allow_reuse_address = os.name != "nt"

    def __init__(self, address, store, capture=None, capture_enabled=True, env=None):
        if address[0] != "127.0.0.1":
            raise ValueError("Filigree écoute exclusivement sur 127.0.0.1.")
        self.store = store
        if capture is not None:
            self.capture = capture
        elif capture_enabled:
            self.capture = Capture(store, env)  # not started here: serve() decides
        else:
            self.capture = DisabledCapture(store)
        self.token = agent_key(store.root)
        super().__init__(address, Handler)

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    server_version = "Filigree"

    body_consumed = False

    def log_message(self, fmt, *args):
        pass  # Never log URL query contents or imported material.

    def handle_one_request(self):
        self.body_consumed = False
        super().handle_one_request()
        if not self.body_consumed and getattr(self, "command", None) and (self.headers.get("Content-Length") or self.headers.get("Transfer-Encoding")):
            self.close_connection = True
            self.discard_unread_body()

    def discard_unread_body(self):
        """The answer is already sent. Signal the end of it, then read (bounded in bytes and time) what the client was still
        sending, so closing the socket does not turn its unread data into a reset that destroys the answer."""
        sock = self.connection
        try:
            self.wfile.flush()
            sock.shutdown(socket.SHUT_WR)
            deadline = time.monotonic() + DRAIN_SECONDS
            remaining = DRAIN_BYTES
            while remaining > 0 and time.monotonic() < deadline:
                sock.settimeout(max(0.05, deadline - time.monotonic()))
                chunk = sock.recv(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
        except (OSError, ValueError):
            pass  # the client is gone or too slow: nothing more to deliver

    def send(self, code, body, content_type="application/json; charset=utf-8", attachment=False):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if attachment:
            self.send_header("Content-Disposition", 'attachment; filename="filigree-memory.md"')
        try:
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (ConnectionError, TimeoutError):
            self.close_connection = True  # the browser navigated away mid-response: nothing left to tell it

    def body(self):
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("Transfer-Encoding non pris en charge.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Content-Length invalide.") from None
        if length < 1 or length > MAX_BODY:
            raise ValueError("Le corps JSON doit contenir entre 1 octet et 8 Mo.")
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Content-Type application/json requis.")
        self.body_consumed = True
        try:
            value = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("Corps JSON invalide.") from exc
        except RecursionError as exc:
            raise ValueError("Document JSON trop profondément imbriqué.") from exc
        if not isinstance(value, dict):
            raise ValueError("Un objet JSON est requis.")
        return value

    def allowed(self, authenticated=False):
        port = self.server.server_address[1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if (self.headers.get("Host") or "").lower() not in hosts:
            self.send(403, {"error": "Hôte non autorisé."})
            return False
        origin = self.headers.get("Origin")
        if origin and origin.lower() not in {f"http://{host}" for host in hosts}:
            self.send(403, {"error": "Origine non autorisée."})
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.send(403, {"error": "Requête intersite refusée."})
            return False
        if authenticated and not secrets.compare_digest(self.headers.get("X-Filigree-Token", ""), self.server.token):
            self.send(403, {"error": "Jeton de session absent ou périmé. Rechargez la page."})
            return False
        return True

    def dispatch(self, method):
        self.connection.settimeout(15)
        path = urlsplit(self.path).path
        # Every API route needs the local key, reads included (ADR-0003); only the bootstrap hands it to the same-origin page.
        if not self.allowed(method != "GET" or (path.startswith("/api/") and path != "/api/bootstrap")):
            return
        try:
            url = urlsplit(self.path)
            parts = [part for part in url.path.split("/") if part]
            query = {key: values[0] for key, values in parse_qs(url.query).items()}
            store = self.server.store
            data = self.body() if method != "GET" else {}
            if method == "GET" and url.path in {"/", "/app.js", "/styles.css"}:
                name = "index.html" if url.path == "/" else url.path[1:]
                mime = {"index.html": "text/html", "app.js": "text/javascript", "styles.css": "text/css"}[name]
                return self.send(200, (STATIC / name).read_bytes(), mime + "; charset=utf-8")
            if parts == ["api", "bootstrap"] and method == "GET":
                return self.send(200, {"token": self.server.token, "version": __version__})
            if parts == ["api", "demo"] and method == "POST":
                return self.send(201, seed_demo(store))
            if parts == ["api", "capture"]:
                if method == "GET":
                    return self.send(200, self.server.capture.status())
                if method == "POST":
                    return self.send(200, self.capture_action(data))
            if parts == ["api", "projects"]:
                if method == "GET":
                    return self.send(200, store.list_projects())
                if method == "POST":
                    if not isinstance(data.get("folder"), str) or not data["folder"].strip():
                        raise ValueError("Un dossier local existant (chemin absolu) est requis.")
                    return self.send(201, store.create_project(data.get("name", ""), data.get("description", ""), folder=data["folder"]))
            if len(parts) >= 3 and parts[:2] == ["api", "projects"]:
                pid = parts[2]
                project = store.get_project(pid)  # Validate identity before paths.
                tail = parts[3:]
                if not tail and method == "GET":
                    return self.send(200, project)
                if tail == ["activity"] and method == "GET":
                    return self.send(200, project_activity(store, pid, query.get("limit", "200")))
                if not tail and method == "PATCH":
                    if set(data) != {"folder"} or not isinstance(data["folder"], str):
                        raise ValueError("Seul le champ folder (chemin absolu) peut être rattaché.")
                    return self.send(200, store.attach_folder(pid, data["folder"]))
                if tail == ["entries"]:
                    if method == "GET":
                        return self.send(200, store.list_entries(pid, query.get("query", ""), query.get("status", ""), query.get("kind", "")))
                    if method == "POST":
                        # `channel` is set here, never read from the request body (unknown fields are refused by the store).
                        return self.send(201, store.create_entry(pid, data, channel="http-ui"))
                if len(tail) == 2 and tail[0] == "entries" and method == "PATCH":
                    return self.send(200, store.update_entry(pid, tail[1], data, channel="http-ui"))
                if len(tail) == 3 and tail[0] == "entries" and tail[2] == "history" and method == "GET":
                    return self.send(200, store.list_history(pid, tail[1]))
                if tail == ["diagnostics"] and method == "GET":
                    # Quarantined entry and event files: omitted from every view, so they are reported here. Names only, no paths.
                    return self.send(200, {"entries": [{"file": Path(d["file"]).name, "problem": d["problem"]} for d in store.diagnostics(pid)],
                                           "events": [{"file": Path(d["file"]).name, "problem": d["problem"]} for d in store.event_diagnostics(pid)]})
                if tail == ["events"] and method == "GET":
                    return self.send(200, store.list_events(pid))
                if tail == ["graph"] and method == "GET":
                    return self.send(200, store.graph(pid))
                if tail == ["handoff"] and method == "GET":
                    return self.send(200, store.handoff(pid, query.get("query", ""), _budget(query.get("budget", "12000"))))
                if tail == ["import"] and method == "POST":
                    source = data.get("source", "import")
                    if not isinstance(source, str) or len(source) > 160:
                        raise ValueError("Nom de source invalide.")
                    parser = parse_text if data.get("format") == "text" else parse_import
                    return self.send(200, store.import_events(pid, parser(data.get("text", ""), source), source))
                if tail == ["export"] and method == "GET":
                    return self.send(200, store.export_markdown(pid), "text/markdown; charset=utf-8", True)
                if tail == ["git"]:
                    with store._lock:
                        store._recover()
                        project_path = store.root / "projects" / pid
                        result = status(project_path) if method == "GET" else operate(project_path, data.get("action"), data.get("message", "docs(memory): checkpoint"))
                    return self.send(200, result)
            self.send(404, {"error": "Ressource introuvable."})
        except CaptureOff:
            self.send(409, {"error": "La capture est désactivée pour ce serveur (--no-capture) : redémarrez sans cette option pour l'utiliser."})
        except ConflictError as exc:
            self.send(409, {"error": _public(exc)})
        except KeyError:
            self.send(404, {"error": "Projet ou connaissance introuvable."})
        except RecursionError:
            self.send(400, {"error": "Document JSON trop profondément imbriqué."})
        except TypeError:
            self.send(400, {"error": "Requête invalide : types de champs inattendus."})
        except ValueError as exc:
            self.send(400, {"error": _public(exc)})
        except TimeoutError:
            self.send(503, {"error": "La mémoire est occupée. Réessayez dans quelques instants."})
        except Exception:
            self.send(500, {"error": "Opération interrompue. Vérifiez les permissions du dossier et son intégrité."})

    def capture_action(self, data):
        capture = self.server.capture
        action = data.get("action")
        if not isinstance(action, str):
            raise ValueError("Action de capture inconnue.")
        if isinstance(capture, DisabledCapture) and action != "stop":
            raise CaptureOff()
        if action == "enable" or action == "disable":
            capture.set_enabled(action == "enable")
        elif action in {"pause", "resume"}:
            capture.set_paused(action == "pause", data.get("project_id") or "")
        elif action in {"exclude", "include"}:
            capture.set_excluded(_field(data, "folder"), action == "exclude")
        elif action in {"fallback-on", "fallback-off"}:
            capture.set_native_fallback(action == "fallback-on")
        elif action == "link":
            capture.link(_field(data, "key"), _field(data, "project_id"), bool(data.get("import_history")))
        elif action == "unlink":
            capture.unlink(_field(data, "key"))
        elif action == "scan":
            capture.scan_if_possible()
        elif action == "start":
            capture.start()
        elif action == "stop":
            capture.stop() if capture.thread is not None else capture.request_stop(0.5)
        else:
            raise ValueError("Action de capture inconnue.")
        return {"ok": True, "status": capture.status()}

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PATCH(self):
        self.dispatch("PATCH")

    def refuse(self):
        self.send(405, {"error": "Méthode non prise en charge."})

    do_PUT = do_DELETE = do_OPTIONS = do_HEAD = refuse


def project_activity(store, project_id: str, limit="200") -> dict:
    """Unreviewed journal view of one project: recent events, sessions, active sessions and overlapping edits."""
    from .activity import ActivityLog, journal_path
    try:
        limit = max(1, min(int(limit), 1000))
    except (TypeError, ValueError):
        raise ValueError("limit doit être un entier entre 1 et 1000.") from None
    log = ActivityLog(journal_path(store, project_id))
    return {"note": "Données d'activité non revues, extraites automatiquement : ce sont des indices, pas des connaissances acceptées.",
            "stats": log.stats(), "events": log.events(limit=limit), "sessions": log.sessions()[:100], "active": log.sessions(active_minutes=15), "overlaps": log.overlaps()}


def serve(root, port=7820, capture=True, env=None):
    from .agent import running_agent
    existing = running_agent(root)
    if existing is not None:
        print(f"Un agent Filigree sert déjà ce dossier de données : {existing['url']}", flush=True)
        return
    try:
        server = LocalServer(("127.0.0.1", port), Store(Path(root)), capture_enabled=capture, env=env)
    except OSError as exc:
        raise ValueError(f"Impossible d'écouter sur 127.0.0.1:{port} (port déjà utilisé ou refusé).") from exc
    print(f"Filigree · http://127.0.0.1:{server.server_address[1]}", flush=True)
    print(f"Mémoire locale : {Path(root).resolve()}", flush=True)
    if capture:
        if server.capture.start():
            print("Capture automatique active (arrêt : filigree capture stop, ou --no-capture au démarrage).", flush=True)
        else:
            print("Capture automatique déjà active dans un autre processus ; ce serveur n'en lance pas une seconde.", flush=True)
    else:
        print("Capture automatique désactivée pour ce serveur (--no-capture).", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.capture.stop(2)
        server.server_close()
