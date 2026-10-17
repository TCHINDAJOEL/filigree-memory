"""`filigree agent`: the permanent observer (ADR-0003). One per data folder.

It serves the workbench and API, runs the v0.1 capture and the activity pipeline, and announces itself in
`<data-dir>/.runtime/agent.json` ({pid, port, started_at, version}), removed on exit. `filigree serve` defers to a
running agent of the same data folder instead of starting a second server.
"""

from __future__ import annotations

from datetime import datetime, timezone
import http.client
import json
import os
from pathlib import Path
import threading

from . import __version__
from .activity import Observer, run_loop
from .capture import ProcessLock
from .server import LocalServer, agent_key
from .store import Store

LOG_MAX_BYTES = 512 * 1024


def info_path(root) -> Path:
    return Path(root) / ".runtime" / "agent.json"


def running_agent(root, timeout: float = 1.5) -> dict | None:
    """The agent of this data folder if it answers with this folder's key; None otherwise (stale file, other folder)."""
    try:
        info = json.loads(info_path(root).read_text(encoding="utf-8"))
        port = int(info["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        connection.request("GET", "/api/bootstrap", headers={"Host": f"127.0.0.1:{port}"})
        response = connection.getresponse()
        body = json.loads(response.read() or b"{}")
        connection.close()
    except (OSError, ValueError, http.client.HTTPException):
        return None
    try:
        expected = agent_key(Path(root).expanduser().resolve())
    except ValueError:
        return None
    if response.status != 200 or body.get("token") != expected:
        return None
    return {**info, "url": f"http://127.0.0.1:{port}"}


def _log(root: Path, message: str):
    """Bounded error log (no content, no paths of conversations): one rotation at LOG_MAX_BYTES."""
    path = root / ".runtime" / "agent.log"
    try:
        if path.exists() and path.stat().st_size > LOG_MAX_BYTES:
            os.replace(path, path.with_suffix(".log.1"))
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {message[:500]}\n")
    except OSError:
        pass


def run_agent(root, port: int = 7820, env=None, interval: float = 5.0, out=print, ready=None, stop_event=None) -> int:
    root = Path(root).expanduser().resolve()
    lock = ProcessLock(root / ".runtime" / "agent.lock")
    if not lock.acquire():
        existing = running_agent(root)
        raise ValueError("Un agent Filigree tourne déjà pour ce dossier de données" + (f" : {existing['url']}" if existing else "."))
    store = Store(root)
    server = None
    stop = stop_event or threading.Event()
    try:
        try:
            server = LocalServer(("127.0.0.1", port), store, env=env)
        except OSError as exc:
            raise ValueError(f"Impossible d'écouter sur 127.0.0.1:{port} (port déjà utilisé ou refusé).") from exc
        actual = server.server_address[1]
        server.capture.start()
        observer = Observer(store, env=env)
        worker = threading.Thread(target=run_loop, args=(observer, stop, interval, lambda exc: _log(root, f"activity: {type(exc).__name__}: {exc}")), daemon=True, name="filigree-activity")
        worker.start()
        info = {"pid": os.getpid(), "port": actual, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "version": __version__}
        path = info_path(root)
        temporary = path.with_name("agent.json.tmp")
        temporary.write_text(json.dumps(info), encoding="utf-8")
        os.replace(temporary, path)
        out(f"Filigree agent · http://127.0.0.1:{actual}")
        out(f"Mémoire locale : {root}")
        if ready is not None:
            ready(info)
        watcher = threading.Thread(target=lambda: (stop.wait(), server.shutdown()), daemon=True)
        watcher.start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    finally:
        stop.set()
        if server is not None:
            server.capture.stop(2)
            server.server_close()
        try:
            info_path(root).unlink()
        except OSError:
            pass
        lock.release()
