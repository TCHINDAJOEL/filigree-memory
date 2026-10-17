"""Claude Desktop code sessions (Roaming and MSIX): whitelisted metadata only; titles etc. are never kept."""

from __future__ import annotations

import json
from pathlib import Path

from .base import Roots, SessionInfo, make_key, text_or_none, to_iso

MAX_BYTES = 1024 * 1024
_KEEP = ("sessionId", "cliSessionId", "cwd", "model", "createdAt", "lastActivityAt", "isArchived")


class ClaudeDesktopCollector:
    name = "claude_desktop"

    def __init__(self, env=None, home=None):
        self.roots = Roots(env, home)

    def _dirs(self) -> list[Path]:
        dirs = [self.roots.appdata / "Claude" / "claude-code-sessions"]
        packages = self.roots.localappdata / "Packages"
        if packages.is_dir():
            for pkg in sorted(packages.glob("Claude_*")):
                dirs.append(pkg / "LocalCache" / "Roaming" / "Claude" / "claude-code-sessions")
        return [d for d in dirs if d.is_dir()]

    def _files(self) -> list[Path]:
        files = []
        for directory in self._dirs():
            files.extend(directory.glob("**/local_*.json"))
        return files

    def _read(self, path: Path):
        """(SessionInfo, seen field names) or (None, reason)."""
        try:
            if path.stat().st_size > MAX_BYTES:
                return None, "skipped_large"
            data = json.loads(path.read_bytes())
        except (OSError, ValueError):
            return None, "unreadable"
        if not isinstance(data, dict):
            return None, "unreadable"
        kept = {k: data.get(k) for k in _KEEP}
        del data
        native = text_or_none(kept["cliSessionId"], 200) or text_or_none(kept["sessionId"], 200)
        if not native:
            return None, "no_id"
        # Same key root as the Claude Code transcript of that session, so both collectors yield one key.
        info = SessionInfo(
            client="claude", collector=self.name, native_id=native,
            key=make_key("claude", self.roots.claude_config, native),
            cwd=text_or_none(kept["cwd"]), entrypoint="claude-desktop", model=text_or_none(kept["model"], 200),
            started_at=to_iso(kept["createdAt"]), last_activity=to_iso(kept["lastActivityAt"]),
            archived=kept["isArchived"] is True,
        )
        return info, tuple(k for k in _KEEP if kept[k] not in (None, ""))

    def discover(self, since=None, limit: int = 500) -> list[SessionInfo]:
        floor = to_iso(since) if since is not None else None
        out = []
        for path in self._files():
            info, _ = self._read(path)
            if info is None or (floor and (info.last_activity or info.started_at or "") < floor):
                continue
            out.append(info)
        out.sort(key=lambda s: s.last_activity or "", reverse=True)
        return out[:limit]

    def probe(self) -> dict:
        dirs = self._dirs()
        if not dirs:
            return {"status": "missing", "detail": "no claude-code-sessions directory", "fields": {}}
        files = self._files()
        fields: dict[str, int] = {"files": len(files)}
        parsed = 0
        for path in files:
            info, seen = self._read(path)
            if info is None:
                fields[seen] = fields.get(seen, 0) + 1
                continue
            parsed += 1
            for key in seen:
                fields[key] = fields.get(key, 0) + 1
        if files and parsed == 0 and not fields.get("skipped_large"):
            return {"status": "unsupported", "detail": "session files found but none readable with an id", "fields": fields}
        return {"status": "ok", "detail": f"{len(files)} session file(s) in {len(dirs)} location(s)", "fields": fields}
