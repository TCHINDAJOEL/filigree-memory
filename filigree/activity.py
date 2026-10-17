"""Per-project activity journal and the observer that fills it (ADR-0003, decisions D2, D10, D11, D13, D14).

The journal is `<data-dir>/projects/<id>/.filigree/activity.sqlite`: kept data, never in a Git checkpoint (the
`git_sync` whitelist leaves it out) and never exported. The observer only reads agent transcripts, only for sessions
whose folder already belongs to a registered project inside the allowed roots; it never creates a project and never
calls a model. The journal is written first and the transcript cursor advances only afterwards, so a crash replays
lines and the stable event ids absorb the replay.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import threading
import time

from . import resolver
from .collectors import all_collectors, discover_all
from .extract import KINDS, Extractor, extract_line, summarize

SCHEMA_VERSION = 1
CHUNK_BYTES = 1024 * 1024
MAX_FILES_PER_CYCLE = 200
OVERLAP_MINUTES = 15
IDLE_MINUTES = 10
SIGNALS_MAX_BYTES = 1024 * 1024
IGNORED_OVERLAP = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Cargo.lock", ".DS_Store")
TRANSCRIPT_COLLECTORS = {"claude_code": "claude", "codex_rollout": "codex"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  event_id TEXT PRIMARY KEY, session_key TEXT NOT NULL, client TEXT NOT NULL, kind TEXT NOT NULL,
  ts_source TEXT, ts_observed TEXT NOT NULL, cwd TEXT, summary TEXT NOT NULL, files TEXT NOT NULL,
  provenance TEXT NOT NULL, outside_project INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS events_session ON events(session_key, ts_observed);
CREATE INDEX IF NOT EXISTS events_time ON events(ts_observed);
CREATE TABLE IF NOT EXISTS sessions(
  session_key TEXT PRIMARY KEY, client TEXT NOT NULL, entrypoint TEXT, model TEXT, parent_key TEXT,
  first_ts TEXT, last_ts TEXT, cwd TEXT, event_count INTEGER NOT NULL DEFAULT 0, ended INTEGER NOT NULL DEFAULT 0);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _parse(text) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def journal_path(store, project_id: str) -> Path:
    return store.root / "projects" / project_id / ".filigree" / "activity.sqlite"


class ActivityLog:
    """One project's journal. Short-lived connections: the daemon, the API and MCP may read it concurrently."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _connect(self, create: bool = False) -> sqlite3.Connection | None:
        if not create and not self.path.exists():
            return None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            connection.close()
            raise ValueError(f"Journal d'activité créé par une version plus récente de Filigree (schéma {version}).")
        if version < SCHEMA_VERSION:
            connection.executescript(_SCHEMA)
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.commit()
        return connection

    def add(self, session: dict, events: list[dict]) -> int:
        """Insert events (duplicates ignored) and refresh the session row. Returns the number of new events."""
        connection = self._connect(create=True)
        try:
            with connection:
                before = connection.total_changes
                connection.executemany(
                    "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [(e["event_id"], session["session_key"], session["client"], e["kind"], e.get("ts_source"), e["ts_observed"], session.get("cwd"),
                      e["summary"], json.dumps(e.get("files", []), ensure_ascii=False), json.dumps(e.get("provenance", {}), ensure_ascii=False), int(bool(e.get("outside_project")))) for e in events])
                added = connection.total_changes - before
                row = connection.execute("SELECT COUNT(*), MIN(COALESCE(ts_source, ts_observed)), MAX(COALESCE(ts_source, ts_observed)) FROM events WHERE session_key=?", (session["session_key"],)).fetchone()
                connection.execute(
                    "INSERT INTO sessions(session_key, client, entrypoint, model, parent_key, first_ts, last_ts, cwd, event_count, ended) VALUES (?,?,?,?,?,?,?,?,?,0) "
                    "ON CONFLICT(session_key) DO UPDATE SET entrypoint=COALESCE(excluded.entrypoint, entrypoint), model=COALESCE(excluded.model, model), "
                    "parent_key=COALESCE(excluded.parent_key, parent_key), first_ts=excluded.first_ts, last_ts=excluded.last_ts, cwd=COALESCE(excluded.cwd, cwd), event_count=excluded.event_count",
                    (session["session_key"], session["client"], session.get("entrypoint"), session.get("model"), session.get("parent_key"), row[1], row[2], session.get("cwd"), row[0]))
            return added
        finally:
            connection.close()

    def mark_ended(self, session_key: str) -> bool:
        connection = self._connect()
        if connection is None:
            return False
        try:
            with connection:
                return connection.execute("UPDATE sessions SET ended=1 WHERE session_key=?", (session_key,)).rowcount > 0
        finally:
            connection.close()

    def events(self, limit: int = 100, session_key: str | None = None, since: str | None = None) -> list[dict]:
        connection = self._connect()
        if connection is None:
            return []
        try:
            clauses, values = [], []
            if session_key:
                clauses.append("session_key=?")
                values.append(session_key)
            if since:
                clauses.append("ts_observed>=?")
                values.append(since)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = connection.execute(f"SELECT * FROM events {where} ORDER BY COALESCE(ts_source, ts_observed) DESC, rowid DESC LIMIT ?", (*values, max(1, min(int(limit), 5000)))).fetchall()
            return [dict(row, files=json.loads(row["files"]), provenance=json.loads(row["provenance"]), outside_project=bool(row["outside_project"])) for row in rows]
        finally:
            connection.close()

    def sessions(self, active_minutes: int | None = None) -> list[dict]:
        connection = self._connect()
        if connection is None:
            return []
        try:
            rows = [dict(row, ended=bool(row["ended"])) for row in connection.execute("SELECT * FROM sessions ORDER BY last_ts DESC").fetchall()]
        finally:
            connection.close()
        if active_minutes is None:
            return rows
        floor = _now() - timedelta(minutes=active_minutes)
        return [row for row in rows if not row["ended"] and (_parse(row["last_ts"]) or floor) > floor]

    def overlaps(self, minutes: int = OVERLAP_MINUTES, ignored=IGNORED_OVERLAP) -> list[dict]:
        """Files changed by at least two sessions in the last `minutes` (a warning, never a proposal)."""
        floor = _iso(_now() - timedelta(minutes=minutes))
        by_file: dict[str, set] = {}
        for event in self.events(limit=5000, since=floor):
            if event["kind"] != "file_change":
                continue
            for name in event["files"]:
                if Path(name).name not in ignored:
                    by_file.setdefault(os.path.normcase(name), set()).add(event["session_key"])
        return [{"file": name, "sessions": sorted(keys)} for name, keys in sorted(by_file.items()) if len(keys) > 1]

    def purge(self, retention_days: int) -> int:
        connection = self._connect()
        if connection is None:
            return 0
        floor = _iso(_now() - timedelta(days=retention_days))
        try:
            with connection:
                removed = connection.execute("DELETE FROM events WHERE ts_observed<?", (floor,)).rowcount
                connection.execute("DELETE FROM sessions WHERE session_key NOT IN (SELECT DISTINCT session_key FROM events)")
            return removed
        finally:
            connection.close()

    def stats(self) -> dict:
        connection = self._connect()
        if connection is None:
            return {"events": 0, "sessions": 0}
        try:
            return {"events": connection.execute("SELECT COUNT(*) FROM events").fetchone()[0], "sessions": connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]}
        finally:
            connection.close()


def _read_json(path: Path, default):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporary, path)


def read_signals(data_dir: Path, offset: int) -> tuple[list[dict], int]:
    """New hook signals since `offset` in `.runtime/signals.jsonl`; a rotated file restarts at zero."""
    path = Path(data_dir) / ".runtime" / "signals.jsonl"
    try:
        size = path.stat().st_size
    except OSError:
        return [], 0
    if size < offset:
        offset = 0
    with open(path, "rb") as handle:
        handle.seek(offset)
        data = handle.read(SIGNALS_MAX_BYTES)
    end = data.rfind(b"\n") + 1
    signals = []
    for line in data[:end].splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and isinstance(value.get("session_id"), str):
            signals.append(value)
    return signals, offset + end


class Observer:
    """Reads new transcript lines of registered projects into their journals, then distills idle sessions."""

    def __init__(self, store, env=None, home=None, collectors=None, settings_loader=None):
        self.store = store
        self.env = env
        self.home = home
        self.collectors = collectors
        self.settings_loader = settings_loader
        self.state_path = store.root / ".capture" / "activity-state.json"
        self.lock = threading.Lock()
        self.extractors: dict[str, Extractor] = {}

    def _settings(self) -> dict:
        if self.settings_loader is not None:
            return self.settings_loader()
        from .capture import Capture
        settings, _ = Capture(self.store, self.env).settings()
        return settings

    def _project_for(self, cwd: str, roots) -> dict | None:
        """Registered project for a session folder (create=False): allowed roots first, then the folder, then a proven worktree."""
        try:
            folder = Path(cwd)
            if not folder.is_absolute():
                return None
            if roots is not None and not resolver.under_roots(folder, roots):
                return None
            project = self.store.locate_project(str(folder))
            if project is None:
                main = None
                for candidate in [folder, *folder.parents]:
                    if (candidate / ".git").exists():
                        main = resolver.proven_worktree_main(candidate)
                        break
                if main is not None and (roots is None or resolver.under_roots(main, roots)):
                    located = self.store.locate_project(str(main))
                    if located and located.get("folder") and os.path.normcase(os.path.realpath(located["folder"]["path"])) == os.path.normcase(os.path.realpath(main)):
                        project = located
        except (OSError, ValueError):
            return None
        if not project or project.get("demo") or not project.get("folder"):
            return None
        return project

    def scan_once(self) -> dict:
        with self.lock:
            return self._scan()

    def _scan(self) -> dict:
        settings = self._settings()
        result = {"enabled": False, "files": 0, "events": 0, "sessions": 0, "skipped": {}, "distilled": 0, "purged": 0, "unsupported": [], "errors": 0}
        activity = settings.get("activity", {})
        if not settings.get("enabled") or settings.get("paused_all") or not activity.get("enabled", True):
            return result
        result["enabled"] = True
        state = _read_json(self.state_path, {})
        state.setdefault("version", 1)
        files_state = state.setdefault("files", {})
        first_run = "baseline_at" not in state
        now = _now()
        state.setdefault("baseline_at", _iso(now))
        paused = set(settings.get("paused", []))
        excluded = [Path(item) for item in settings.get("exclude", [])]
        found = discover_all(collectors=self.collectors if self.collectors is not None else all_collectors(self.env, self.home), limit=MAX_FILES_PER_CYCLE)
        touched_projects = {}
        for name, outcome in found.items():
            if outcome["status"] != "ok":
                result["unsupported"].append(name)  # D14: visible, never an approximate read
                continue
            source = TRANSCRIPT_COLLECTORS.get(name)
            if source is None:
                continue
            for info in outcome["sessions"]:
                if not info.transcript or not info.cwd:
                    continue
                path = info.transcript
                cursor = files_state.get(path)
                try:
                    size = Path(path).stat().st_size
                except OSError:
                    continue
                if cursor is None:
                    # D11: no automatic catch-up. Files present at the first run start at their current end.
                    files_state[path] = {"offset": size if first_run else 0}
                    if first_run:
                        continue
                    cursor = files_state[path]
                if size < cursor["offset"]:
                    cursor["offset"] = 0  # rewritten transcript: stable ids absorb the replay
                if size == cursor["offset"]:
                    continue
                project = self._project_for(info.cwd, settings.get("allowed_roots"))
                if project is None:
                    result["skipped"]["no_project"] = result["skipped"].get("no_project", 0) + 1
                    continue
                folder = Path(project["folder"]["path"])
                session_folder = Path(info.cwd)
                blocked = [*excluded, self.store.root]
                if project["id"] in paused or any(place == item or item in place.parents for place in (folder, session_folder) for item in blocked):
                    cursor["offset"] = size  # deliberate pause or exclusion (project or session folder): skipped, not replayed later
                    result["skipped"]["paused"] = result["skipped"].get("paused", 0) + 1
                    continue
                try:
                    added, offset = self._ingest(source, info, path, cursor["offset"], project, folder, now, state["baseline_at"])
                except Exception as exc:  # noqa: BLE001 — one unreadable file or busy journal must not stall the others
                    result["errors"] += 1
                    result["skipped"]["error_" + type(exc).__name__] = result["skipped"].get("error_" + type(exc).__name__, 0) + 1
                    continue
                cursor["offset"] = offset  # only after the journal write succeeded
                result["files"] += 1
                result["events"] += added
                touched_projects[project["id"]] = project
        _write_json(self.state_path, state)  # progress is kept even if a later step fails
        signals, state["signal_offset"] = read_signals(self.store.root, int(state.get("signal_offset", 0)))
        ended = {item["session_id"] for item in signals if item.get("event") in {"session_end", "stop"}}
        projects = {project["id"]: project for project in self.store.list_projects() if project.get("folder") and not project.get("demo")}
        from .distill import distill_project
        sheets = state.setdefault("sheets", {})
        purge_today = state.get("purged_on") != now.date().isoformat()
        retention = int(activity.get("retention_days", 90))
        for project_id in projects:
            if not journal_path(self.store, project_id).exists():
                continue
            try:  # each project is isolated: a busy or newer journal, or a conflicting sheet, never blocks the others
                log = ActivityLog(journal_path(self.store, project_id))
                if ended:
                    for session in log.sessions():
                        if session["session_key"].rsplit(":", 1)[-1] in ended:
                            log.mark_ended(session["session_key"])
                result["distilled"] += distill_project(self.store, project_id, sheets, idle_minutes=IDLE_MINUTES)
                if purge_today:
                    result["purged"] += log.purge(retention)
            except Exception as exc:  # noqa: BLE001
                result["errors"] += 1
                result["skipped"]["error_" + type(exc).__name__] = result["skipped"].get("error_" + type(exc).__name__, 0) + 1
        if purge_today:
            state["purged_on"] = now.date().isoformat()
        result["sessions"] = len({key for key in sheets})
        _write_json(self.state_path, state)
        return result

    def _ingest(self, source: str, info, path: str, offset: int, project: dict, folder: Path, now: datetime, baseline_at: str = "") -> tuple[int, int]:
        with open(path, "rb") as handle:
            handle.seek(offset)
            data = handle.read(CHUNK_BYTES)
        end = data.rfind(b"\n") + 1
        if end == 0:
            return 0, offset  # no complete line yet
        extractor = self.extractors.setdefault(path, Extractor())
        events = []
        observed = _iso(now)
        floor = _parse(baseline_at)
        for raw in data[:end].splitlines():
            if not raw.strip():
                continue
            found, element, stamp = extract_line(extractor, source, raw)
            moment = _parse(stamp) if stamp else None
            if floor is not None and moment is not None and moment < floor:
                continue  # D11: history older than the observer's first run (resumed or forked transcripts) is not caught up
            for number, event in enumerate(found):
                if event["kind"] not in KINDS or not event["summary"] and event["kind"] not in {"commit"}:
                    continue
                outside = any(Path(name).is_absolute() and not resolver.under_roots(name, [folder]) for name in event["files"])
                part = event.pop("part", number)
                # The id names the source element, not the session: a line copied into a fork or resume is one event.
                events.append({**event, "event_id": f"{info.client}:{element}:{part}", "ts_source": stamp, "ts_observed": observed, "outside_project": outside,
                               "provenance": {"collector": info.collector, "native_id": info.native_id, "file": Path(path).name, "claim": "transcription locale, non authentifiée"}})
        session = {"session_key": info.key, "client": info.client, "entrypoint": info.entrypoint, "model": info.model, "cwd": info.cwd,
                   "parent_key": f"{info.key.rsplit(':', 1)[0]}:{info.parent_native_id}" if info.parent_native_id else None}
        added = ActivityLog(journal_path(self.store, project["id"])).add(session, events) if events else 0
        return added, offset + end


def run_loop(observer: Observer, stop: threading.Event, interval: float = 5.0, on_error=None):
    """Daemon loop: one failing cycle is reported and retried at the next interval; it never stops the daemon."""
    while not stop.is_set():
        try:
            observer.scan_once()
        except Exception as exc:  # noqa: BLE001 — isolation boundary of a background service
            if on_error:
                on_error(exc)
        stop.wait(interval)


__all__ = ["ActivityLog", "Observer", "journal_path", "read_signals", "run_loop", "summarize"]
