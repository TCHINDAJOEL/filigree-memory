"""Codex thread index (state_*.sqlite), opened read-only. Only identity/metadata columns are selected."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3

from .base import Roots, SessionInfo, make_key, text_or_none, to_iso

REQUIRED = ("id", "cwd", "created_at", "updated_at")
OPTIONAL = ("source", "model", "cli_version", "git_branch", "archived", "rollout_path")
EDGE_COLUMNS = {"parent_thread_id", "child_thread_id"}


def source_hint(value) -> tuple[str | None, str | None]:
    """(entrypoint hint, parent thread id) from a `source` column that is text or a JSON object."""
    if isinstance(value, str) and value.lstrip().startswith("{"):
        try:
            value = json.loads(value)
        except ValueError:
            return None, None
    if isinstance(value, dict):
        sub = value.get("subagent")
        spawn = sub.get("thread_spawn") if isinstance(sub, dict) else None
        parent = spawn.get("parent_thread_id") if isinstance(spawn, dict) else None
        return "subagent", parent if isinstance(parent, str) and parent else None
    return (value[:100] if isinstance(value, str) and value else None), None


class CodexStateCollector:
    name = "codex_state"

    def __init__(self, env=None, home=None):
        self.roots = Roots(env, home)

    def _db(self) -> Path | None:
        home = self.roots.codex_home
        best, best_n = None, -1
        if home.is_dir():
            for path in home.glob("state_*.sqlite"):
                match = re.fullmatch(r"state_(\d+)\.sqlite", path.name)
                if match and int(match.group(1)) > best_n:
                    best, best_n = path, int(match.group(1))
        return best

    @staticmethod
    def _open(path: Path):
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
        connection.execute("PRAGMA query_only=ON")
        return connection

    @staticmethod
    def _columns(connection, table: str) -> set[str]:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}

    def probe(self) -> dict:
        path = self._db()
        if path is None:
            return {"status": "missing", "detail": "no state_*.sqlite", "fields": {}}
        try:
            connection = self._open(path)
        except sqlite3.Error:
            return {"status": "unsupported", "detail": "database cannot be opened read-only", "fields": {}}
        try:
            columns = self._columns(connection, "threads")
            missing = [c for c in REQUIRED if c not in columns]
            if missing:
                return {"status": "unsupported", "detail": "threads lacks required columns: " + ",".join(missing), "fields": {}}
            fields = {c: 1 for c in (*REQUIRED, *OPTIONAL) if c in columns}
            fields["threads"] = connection.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
            fields["thread_spawn_edges"] = int(self._columns(connection, "thread_spawn_edges") >= EDGE_COLUMNS)
            return {"status": "ok", "detail": path.name, "fields": fields}
        except sqlite3.Error:
            return {"status": "unsupported", "detail": "schema cannot be read", "fields": {}}
        finally:
            connection.close()

    def discover(self, since=None, limit: int = 500) -> list[SessionInfo]:
        path = self._db()
        if path is None:
            return []
        root = self.roots.codex_home
        connection = self._open(path)
        try:
            columns = self._columns(connection, "threads")
            if any(c not in columns for c in REQUIRED):
                return []
            wanted = [*REQUIRED, *(c for c in OPTIONAL if c in columns)]
            rows = connection.execute(f"SELECT {','.join(wanted)} FROM threads").fetchall()
            parents = {}
            if self._columns(connection, "thread_spawn_edges") >= EDGE_COLUMNS:
                for parent, child in connection.execute("SELECT parent_thread_id, child_thread_id FROM thread_spawn_edges"):
                    if isinstance(parent, str) and isinstance(child, str):
                        parents[child] = parent
        finally:
            connection.close()
        floor = to_iso(since) if since is not None else None
        out = []
        for row in rows:
            data = dict(zip(wanted, row))
            if not data["id"]:
                continue
            native = str(data["id"])
            last = to_iso(data["updated_at"])
            if floor and (last or "") < floor:
                continue
            hint, src_parent = source_hint(data.get("source"))
            out.append(SessionInfo(
                client="codex", collector=self.name, native_id=native, key=make_key("codex", root, native),
                cwd=text_or_none(data["cwd"]), entrypoint=hint, model=text_or_none(data.get("model"), 200),
                version=text_or_none(data.get("cli_version"), 100), parent_native_id=parents.get(native) or src_parent,
                started_at=to_iso(data["created_at"]), last_activity=last, archived=bool(data.get("archived")),
                transcript=text_or_none(data.get("rollout_path")),
            ))
        out.sort(key=lambda s: s.last_activity or "", reverse=True)
        return out[:limit]
