"""Claude Code transcripts: metadata from a bounded head of each JSONL file; message text is never kept."""

from __future__ import annotations

import json
from pathlib import Path

from .base import Roots, SessionInfo, head_lines, make_key, mtime_iso, text_or_none, to_iso

_KEYS = ("sessionId", "cwd", "entrypoint", "version", "gitBranch")


class ClaudeCodeCollector:
    name = "claude_code"

    def __init__(self, env=None, home=None):
        self.roots = Roots(env, home)

    @property
    def projects(self) -> Path:
        return self.roots.claude_config / "projects"

    def _files(self) -> list[tuple[float, Path, str | None]]:
        found = []
        if not self.projects.is_dir():
            return found
        for folder in sorted(p for p in self.projects.iterdir() if p.is_dir()):
            found.extend((path, None) for path in folder.glob("*.jsonl"))
            found.extend((path, path.parent.parent.name) for path in folder.glob("*/subagents/agent-*.jsonl"))
        out = []
        for path, parent in found:
            try:
                out.append((path.stat().st_mtime, path, parent))
            except OSError:
                continue
        out.sort(key=lambda item: item[0], reverse=True)
        return out

    def _read(self, path: Path, parent: str | None):
        """(SessionInfo, seen field names) or (None, ())."""
        meta: dict = {}
        first = last = model = None
        try:
            lines = head_lines(path)
        except OSError:
            return None, ()
        for raw in lines:
            try:
                record = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            for key in _KEYS:
                if key not in meta and isinstance(record.get(key), str) and record[key]:
                    meta[key] = record[key]
            stamp = to_iso(record.get("timestamp"))
            if stamp:
                first = first or stamp
                last = stamp
            message = record.get("message")
            if model is None and record.get("type") == "assistant" and isinstance(message, dict):
                model = text_or_none(message.get("model"), 200)
        session_id = meta.get("sessionId") or (path.stem if parent is None else parent)
        native_id = session_id if parent is None else f"{parent}:{path.stem}"
        info = SessionInfo(
            client="claude", collector=self.name, native_id=native_id,
            key=make_key("claude", self.roots.claude_config, native_id),
            cwd=text_or_none(meta.get("cwd")), entrypoint=text_or_none(meta.get("entrypoint"), 200),
            model=model, version=text_or_none(meta.get("version"), 100),
            parent_native_id=parent, started_at=first, last_activity=mtime_iso(path) or last,
            transcript=str(path),
        )
        seen = tuple(meta) + (("timestamp",) if first else ())
        return info, seen

    def discover(self, since=None, limit: int = 500) -> list[SessionInfo]:
        floor = to_iso(since) if since is not None else None
        out = []
        for mtime, path, parent in self._files():
            if len(out) >= limit:
                break
            if floor and (to_iso(mtime) or "") < floor:
                continue
            info, _ = self._read(path, parent)
            if info is not None:
                out.append(info)
        return out

    def probe(self) -> dict:
        if not self.projects.is_dir():
            return {"status": "missing", "detail": "no projects directory", "fields": {}}
        files = self._files()
        fields: dict[str, int] = {"files": len(files), "subagent_files": sum(1 for _, _, p in files if p)}
        for _, path, parent in files[:100]:
            _, seen = self._read(path, parent)
            for key in seen:
                fields[key] = fields.get(key, 0) + 1
        if files and not fields.get("sessionId"):
            return {"status": "unsupported", "detail": "transcripts found but no sessionId in head", "fields": fields}
        return {"status": "ok", "detail": f"{len(files)} transcript file(s)", "fields": fields}
