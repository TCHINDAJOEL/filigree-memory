"""Read-only session collectors. A failing collector becomes a visible `unsupported` entry, never an exception."""

from __future__ import annotations

from .base import SessionInfo
from .claude_code import ClaudeCodeCollector
from .claude_desktop import ClaudeDesktopCollector
from .claude_tap import ClaudeTapCollector
from .codex_rollout import CodexRolloutCollector
from .codex_state import CodexStateCollector

__all__ = ["SessionInfo", "all_collectors", "probe_all", "discover_all"]


def all_collectors(env=None, home=None) -> list:
    classes = (ClaudeCodeCollector, ClaudeDesktopCollector, CodexStateCollector, CodexRolloutCollector, ClaudeTapCollector)
    return [cls(env, home) for cls in classes]


def probe_all(env=None, home=None, collectors=None) -> dict:
    """{name: {status, detail, fields}}; a failure is reported by exception type name only."""
    out = {}
    for collector in collectors if collectors is not None else all_collectors(env, home):
        try:
            out[collector.name] = collector.probe()
        except Exception as exc:
            out[collector.name] = {"status": "unsupported", "detail": f"probe failed: {type(exc).__name__}", "fields": {}}
    return out


def discover_all(env=None, home=None, since=None, limit: int = 500, collectors=None) -> dict:
    """{name: {status, detail, sessions: [SessionInfo]}}."""
    out = {}
    for collector in collectors if collectors is not None else all_collectors(env, home):
        try:
            out[collector.name] = {"status": "ok", "detail": "", "sessions": list(collector.discover(since=since, limit=limit))}
        except Exception as exc:
            out[collector.name] = {"status": "unsupported", "detail": f"discover failed: {type(exc).__name__}", "sessions": []}
    return out
