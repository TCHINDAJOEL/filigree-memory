"""Deterministic extraction of activity events from native transcript lines (ADR-0003).

One transcript line gives zero or more events. Summaries are redacted *before* they are cut to 280 characters.
Reasoning, system prompts and injected blocks are excluded as in v0.1, and command lines are never stored: a
command keeps only its program name (S-15). The event id is derived from the source element id, so a resumed,
forked or re-read transcript never duplicates an event.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePath

from . import tap_source
from .store import redact_whole

SUMMARY_LIMIT = 280
KINDS = frozenset({"user_prompt", "assistant_text", "tool_call", "tool_result", "file_change", "command", "test_result", "error", "commit", "session_start", "session_end"})
EDIT_TOOLS = frozenset({"edit", "write", "multiedit", "notebookedit", "apply_patch", "str_replace_editor", "create_file"})
SHELL_TOOLS = frozenset({"bash", "shell", "exec_command", "local_shell", "local_shell_call", "powershell", "run_shell_command"})
_TEST = re.compile(r"(?:^|[\s;&|/\\])(?:pytest|unittest|tox|nox|jest|vitest|mocha|playwright\s+test|(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test|go\s+test|cargo\s+test|dotnet\s+test|mvn\s+test|gradle\w*\s+test|rspec|phpunit)\b", re.I)
_COMMIT = re.compile(r"(?:^|[\s;&|])git\s+(?:-\S+\s+)*commit\b", re.I)
_PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.M)
MAX_PENDING_CALLS = 512


def summarize(text) -> str:
    """Redact the whole text, then keep its first non-empty lines within SUMMARY_LIMIT characters."""
    if not isinstance(text, str):
        return ""
    clean, _ = redact_whole(tap_source.repair_text(text))
    flat = " ".join(clean.split())
    return flat if len(flat) <= SUMMARY_LIMIT else flat[:SUMMARY_LIMIT - 1] + "…"


def _program(command: str) -> str:
    """Program name only: arguments may hold secrets, paths or data and are never kept."""
    for token in re.split(r"\s+", command.strip()):
        if not token or "=" in token.split("/")[-1] and not token.startswith(("./", "/")):
            continue  # skip leading VAR=value assignments
        return PurePath(token.strip("\"'")).name[:60] or "commande"
    return "commande"


def _command_text(arguments) -> str:
    if isinstance(arguments, dict):
        for key in ("command", "cmd", "script"):
            value = arguments.get(key)
            if isinstance(value, list):
                return " ".join(str(part) for part in value)
            if isinstance(value, str):
                return value
    if isinstance(arguments, str):
        try:
            return _command_text(json.loads(arguments))
        except (ValueError, RecursionError):
            return arguments
    return ""


def _files(name: str, arguments) -> list[str]:
    if isinstance(arguments, str):
        if name == "apply_patch":
            return sorted(set(m.strip() for m in _PATCH_FILE.findall(arguments)))[:50]
        try:
            arguments = json.loads(arguments)
        except (ValueError, RecursionError):
            return []
    if not isinstance(arguments, dict):
        return []
    found = []
    for key in ("file_path", "path", "notebook_path", "filename"):
        if isinstance(arguments.get(key), str) and arguments[key]:
            found.append(arguments[key][:500])
    if isinstance(arguments.get("input"), str):
        found += _PATCH_FILE.findall(arguments["input"])
    return sorted(set(found))[:50]


def _result_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_result_text(item) for item in value if not isinstance(item, dict) or item.get("type") in {None, "text", "output_text", "input_text"})
    if isinstance(value, dict):
        return value["text"] if isinstance(value.get("text"), str) else (value["output"] if isinstance(value.get("output"), str) else "")
    return ""


class Extractor:
    """Stateful per transcript: remembers recent tool calls so a result can be read as a test outcome."""

    def __init__(self):
        self.calls: dict[str, tuple[str, str]] = {}

    def _remember(self, call_id, kind, label):
        if isinstance(call_id, str) and call_id:
            if len(self.calls) >= MAX_PENDING_CALLS:
                self.calls.pop(next(iter(self.calls)))
            self.calls[call_id] = (kind, label)

    def _call(self, name, arguments, call_id) -> dict:
        lowered = (name or "outil").lower()
        if lowered in EDIT_TOOLS:
            files = _files(lowered, arguments)
            self._remember(call_id, "file_change", lowered)
            return {"kind": "file_change", "summary": f"{name} · {', '.join(PurePath(f).name for f in files)[:200]}" if files else str(name), "files": files}
        if lowered in SHELL_TOOLS:
            command = _command_text(arguments)
            if _COMMIT.search(command):
                self._remember(call_id, "commit", "git commit")
                return {"kind": "commit", "summary": "git commit", "files": []}
            program = _program(command)
            if _TEST.search(command):
                self._remember(call_id, "test", program)
                return {"kind": "command", "summary": f"tests · {program}", "files": []}
            self._remember(call_id, "command", program)
            return {"kind": "command", "summary": program, "files": []}
        self._remember(call_id, "tool_call", str(name)[:80])
        return {"kind": "tool_call", "summary": str(name)[:80], "files": []}

    def _result(self, call_id, text, is_error) -> dict | None:
        kind, label = self.calls.pop(call_id, ("tool_call", "")) if isinstance(call_id, str) else ("tool_call", "")
        if kind == "test":
            failed = is_error or bool(re.search(r"\b(?:FAILED|failures?=\d*[1-9]|[1-9]\d* failed|ERROR|Traceback)\b", text or ""))
            return {"kind": "test_result", "summary": summarize(f"{'échec' if failed else 'réussi'} · {label} · {(text or '').strip()[-200:]}"), "files": []}
        if is_error:
            return {"kind": "error", "summary": summarize(text or label or "erreur"), "files": []}
        if kind in {"file_change", "commit"}:
            return None  # the call already carries the meaningful event
        return {"kind": "tool_result", "summary": summarize(text), "files": []}

    def claude(self, record: dict) -> list[dict]:
        """Events of one Claude Code transcript row; each carries a local `part` index."""
        message = record.get("message")
        if record.get("type") not in {"user", "assistant"} or record.get("isMeta") or not isinstance(message, dict) or tap_source.is_private(message):
            return []
        role = record["type"]
        content = message.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list):
            return []
        out = []
        for block in content:
            if not isinstance(block, dict) or tap_source.is_private(block):
                continue
            kind = block.get("type")
            if kind == "text":
                text = tap_source.visible_text(block.get("text"))
                if text:
                    out.append({"kind": "user_prompt" if role == "user" else "assistant_text", "summary": summarize(text), "files": []})
            elif kind == "tool_use":
                out.append(self._call(block.get("name"), block.get("input"), block.get("id")))
            elif kind == "tool_result":
                event = self._result(block.get("tool_use_id"), tap_source.strip_injected(_result_text(block.get("content"))), bool(block.get("is_error")))
                if event:
                    out.append(event)
        return out

    def codex(self, record: dict) -> list[dict]:
        payload = record.get("payload")
        if record.get("type") != "response_item" or not isinstance(payload, dict) or tap_source.is_private(payload):
            return []
        kind = payload.get("type")
        if kind == "message" and payload.get("role") in {"user", "assistant"}:
            return [{"kind": "user_prompt" if item["kind"] == "user_text" else "assistant_text", "summary": summarize(item["text"]), "files": []}
                    for item in tap_source.content_items(payload["role"], payload.get("content"), {}) if item["kind"] in {"user_text", "assistant_text"}]
        if kind in {"function_call", "custom_tool_call", "local_shell_call"}:
            arguments = payload.get("arguments", payload.get("input", payload.get("action")))
            name = payload.get("name") or ("local_shell" if kind == "local_shell_call" else "outil")
            return [self._call(name, arguments, payload.get("call_id"))]
        if kind in {"function_call_output", "custom_tool_call_output", "local_shell_call_output"}:
            output = payload.get("output")
            text, failed = _result_text(output), False
            if isinstance(output, str):
                try:
                    parsed = json.loads(output)
                except (ValueError, RecursionError):
                    parsed = None
                if isinstance(parsed, dict):
                    text = _result_text(parsed.get("output", "")) or text
                    code = (parsed.get("metadata") or {}).get("exit_code") if isinstance(parsed.get("metadata"), dict) else None
                    failed = isinstance(code, int) and code != 0
            event = self._result(payload.get("call_id"), tap_source.strip_injected(text), failed)
            return [event] if event else []
        return []


def element_id(source: str, record: dict, raw: bytes) -> str:
    """Stable id of the source element: Claude's uuid, else a hash of the raw line."""
    if source == "claude" and isinstance(record.get("uuid"), str) and record["uuid"]:
        return record["uuid"][:100]
    return hashlib.sha256(raw.strip()).hexdigest()[:24]


def extract_line(extractor: Extractor, source: str, raw: bytes) -> tuple[list[dict], str | None, str | None]:
    """(events, element id, source timestamp) for one raw JSONL line; malformed lines give no event."""
    try:
        record = json.loads(raw)
    except (ValueError, RecursionError, UnicodeDecodeError):
        return [], None, None
    if not isinstance(record, dict):
        return [], None, None
    events = extractor.claude(record) if source == "claude" else extractor.codex(record)
    stamp = record.get("timestamp") if isinstance(record.get("timestamp"), str) else None
    return events, element_id(source, record, raw), stamp
