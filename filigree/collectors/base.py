"""Shared types and bounded, read-only helpers for session collectors.

Collectors keep metadata only (ids, cwd, timestamps, model, version). Message text is never retained.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path

HEAD_BYTES = 256 * 1024


@dataclass
class SessionInfo:
    client: str
    collector: str
    native_id: str
    key: str
    cwd: str | None = None
    entrypoint: str | None = None
    model: str | None = None
    version: str | None = None
    parent_native_id: str | None = None
    started_at: str | None = None
    last_activity: str | None = None
    archived: bool = False
    transcript: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


class Roots:
    """Resolve per-user roots from an injectable environment mapping and home directory."""

    def __init__(self, env=None, home=None):
        self.env = dict(os.environ if env is None else env)
        self.home = Path(home) if home is not None else Path.home()

    def _dir(self, name: str, default: Path) -> Path:
        value = self.env.get(name)
        return Path(value).expanduser() if value else default

    @property
    def claude_config(self) -> Path:
        return self._dir("CLAUDE_CONFIG_DIR", self.home / ".claude")

    @property
    def codex_home(self) -> Path:
        return self._dir("CODEX_HOME", self.home / ".codex")

    @property
    def appdata(self) -> Path:
        return self._dir("APPDATA", self.home / "AppData" / "Roaming")

    @property
    def localappdata(self) -> Path:
        return self._dir("LOCALAPPDATA", self.home / "AppData" / "Local")


def source_hash(root) -> str:
    return hashlib.sha256(os.path.normcase(str(root)).encode("utf-8")).hexdigest()[:8]


def make_key(client: str, root, native_id: str) -> str:
    return f"{client}:{source_hash(root)}:{native_id}"


def to_iso(value) -> str | None:
    """Epoch seconds/ms (number or numeric string) or ISO text -> ISO UTC (seconds); None if unparseable."""
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                value = float(text)
            except ValueError:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
        seconds = float(value)
        if seconds > 1e11:
            seconds /= 1000.0
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds")
    except (ValueError, OverflowError, OSError):
        return None


def mtime_iso(path) -> str | None:
    try:
        return to_iso(Path(path).stat().st_mtime)
    except OSError:
        return None


def head_lines(path, limit: int = HEAD_BYTES) -> list[bytes]:
    """Complete lines of the first `limit` bytes (a truncated trailing line is dropped)."""
    with open(path, "rb") as handle:
        data = handle.read(limit)
    lines = data.split(b"\n")
    if len(data) >= limit:
        lines = lines[:-1]
    return [line for line in lines if line.strip()]


def text_or_none(value, max_len: int = 4096) -> str | None:
    return value[:max_len] if isinstance(value, str) and value else None
