"""Codex rollout files: only the first `session_meta` line is read (bounded). `.zst` needs the optional zstandard module."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .base import Roots, SessionInfo, make_key, mtime_iso, text_or_none, to_iso

META_BYTES = 128 * 1024
MAX_DEPTH = 6
_PROBE_FIELDS = ("id", "cwd", "originator", "cli_version", "parent_thread_id", "source", "timestamp", "model")


def _first_line(data: bytes, limit: int) -> bytes | None:
    if b"\n" in data:
        return data.split(b"\n", 1)[0]
    return data if len(data) < limit else None


def _zstd():
    try:
        import zstandard  # type: ignore
        return zstandard
    except ImportError:
        return None


class CodexRolloutCollector:
    name = "codex_rollout"

    def __init__(self, env=None, home=None):
        self.roots = Roots(env, home)

    def _walk(self):
        """Yield (path, archived, compressed), at most MAX_DEPTH directories below each base."""
        home = self.roots.codex_home
        for sub, archived in (("sessions", False), ("archived_sessions", True)):
            base = home / sub
            if not base.is_dir():
                continue
            for current, dirs, files in os.walk(base):
                if len(Path(current).relative_to(base).parts) >= MAX_DEPTH:
                    dirs[:] = []
                for name in files:
                    if name.startswith("rollout-") and name.endswith(".jsonl"):
                        yield Path(current) / name, archived, False
                    elif name.startswith("rollout-") and name.endswith(".jsonl.zst"):
                        yield Path(current) / name, archived, True

    @staticmethod
    def _meta(path: Path, compressed: bool):
        try:
            with open(path, "rb") as handle:
                if compressed:
                    with _zstd().ZstdDecompressor().stream_reader(handle) as reader:  # type: ignore[union-attr]
                        data = reader.read(META_BYTES)
                else:
                    data = handle.read(META_BYTES)
            line = _first_line(data, META_BYTES)
            record = json.loads(line) if line else None
        except Exception:
            return None
        if not isinstance(record, dict) or record.get("type") != "session_meta" or not isinstance(record.get("payload"), dict):
            return None
        return record

    def _info(self, path: Path, archived: bool, compressed: bool) -> SessionInfo | None:
        record = self._meta(path, compressed)
        if record is None:
            return None
        payload = record["payload"]
        native = text_or_none(payload.get("id"), 200)
        if not native:
            return None
        parent = payload.get("parent_thread_id")
        source = payload.get("source")
        sub = source.get("subagent") if isinstance(source, dict) else None
        spawn = sub.get("thread_spawn") if isinstance(sub, dict) else None
        if not parent and isinstance(spawn, dict):
            parent = spawn.get("parent_thread_id")
        return SessionInfo(
            client="codex", collector=self.name, native_id=native,
            key=make_key("codex", self.roots.codex_home, native), cwd=text_or_none(payload.get("cwd")),
            entrypoint=text_or_none(payload.get("originator"), 200), model=text_or_none(payload.get("model"), 200),
            version=text_or_none(payload.get("cli_version"), 100), parent_native_id=text_or_none(parent, 200),
            started_at=to_iso(payload.get("timestamp") or record.get("timestamp")), last_activity=mtime_iso(path),
            archived=archived, transcript=str(path),
        )

    def discover(self, since=None, limit: int = 500) -> list[SessionInfo]:
        floor = to_iso(since) if since is not None else None
        entries = []
        for path, archived, compressed in self._walk():
            if compressed and _zstd() is None:
                continue
            try:
                entries.append((path.stat().st_mtime, path, archived, compressed))
            except OSError:
                continue
        entries.sort(key=lambda e: e[0], reverse=True)
        out = []
        for mtime, path, archived, compressed in entries:
            if len(out) >= limit:
                break
            if floor and (to_iso(mtime) or "") < floor:
                continue
            info = self._info(path, archived, compressed)
            if info is not None:
                out.append(info)
        return out

    def probe(self) -> dict:
        home = self.roots.codex_home
        if not (home / "sessions").is_dir() and not (home / "archived_sessions").is_dir():
            return {"status": "missing", "detail": "no sessions directory", "fields": {}}
        entries = list(self._walk())
        plain = [p for p, _, z in entries if not z]
        zst = [p for p, _, z in entries if z]
        fields: dict[str, int] = {"files": len(plain)}
        parsed = 0
        for path in plain[:100]:
            record = self._meta(path, False)
            if record is None:
                continue
            parsed += 1
            for key in record["payload"]:
                if key in _PROBE_FIELDS:
                    fields[key] = fields.get(key, 0) + 1
        if zst:
            fields["zst_read" if _zstd() is not None else "zst_unread"] = len(zst)
        if plain and parsed == 0:
            return {"status": "unsupported", "detail": "rollouts found but no session_meta", "fields": fields}
        return {"status": "ok", "detail": f"{len(plain)} rollout file(s)", "fields": fields}
