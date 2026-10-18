"""claude-tap capability only. Content stays with the v0.1 capture, so discover() returns nothing."""

from __future__ import annotations

from pathlib import Path

from .. import tap_source
from .base import Roots


class ClaudeTapCollector:
    name = "claude_tap"

    def __init__(self, env=None, home=None):
        self.roots = Roots(env, home)

    def db_path(self) -> Path:
        mapping = self.roots.env
        if mapping.get("CLOUDTAP_DB") or mapping.get("XDG_DATA_HOME"):
            return tap_source.resolve_db_path(None, mapping)
        return self.roots.home / ".local" / "share" / "claude-tap" / "traces.sqlite3"

    def probe(self) -> dict:
        result = tap_source.probe(self.db_path())
        capability = result.get("capability")
        status = "ok" if capability == "ok" else "missing" if capability == "missing" else "unsupported"
        return {"status": status, "detail": f"capability {capability}", "fields": {"sessions": int(result.get("sessions") or 0)}}

    def discover(self, since=None, limit: int = 500) -> list:
        return []
