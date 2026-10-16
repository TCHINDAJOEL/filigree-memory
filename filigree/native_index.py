"""Metadata-only index of native Claude Code / Codex transcripts.

Reads just `sessionId`+`cwd` (Claude) or `session_meta.id`+`cwd` (Codex) so that a session
claimed by a claude-tap record can be tied to a real folder by exact equality. No transcript
text is kept. Reads are incremental, bounded, and tolerate partially written lines.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re

HEAD_BYTES = 256 * 1024
CHUNK_BYTES = 2 * 1024 * 1024
MAX_LINE = 1024 * 1024
MAX_DEPTH = 6
MAX_FILES = 50000
MAX_IDS_PER_FILE = 64
MAX_CWDS = 16
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
_AVOID = ("auth", "credential", "token", "secret", "password")


def default_roots(settings=None, env=None) -> dict:
    """Transcript roots: Filigree config first, then CLAUDE_CONFIG_DIR / CODEX_HOME, then home."""
    env = os.environ if env is None else env
    configured = (settings or {}).get("roots") or {}
    claude = configured.get("claude") or (Path(env["CLAUDE_CONFIG_DIR"]) / "projects" if env.get("CLAUDE_CONFIG_DIR") else Path.home() / ".claude" / "projects")
    codex = configured.get("codex") or (Path(env["CODEX_HOME"]) / "sessions" if env.get("CODEX_HOME") else Path.home() / ".codex" / "sessions")
    return {"claude": Path(str(claude)).expanduser(), "codex": Path(str(codex)).expanduser()}


def iter_files(root: Path, limit: int = MAX_FILES):
    """Yield (path, size, mtime_ns) for *.jsonl below root; never follows symlinks, never reads."""
    count = 0
    stack = [(Path(root), 0)]
    while stack:
        folder, depth = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if depth < MAX_DEPTH:
                        stack.append((Path(entry.path), depth + 1))
                elif entry.name.endswith(".jsonl") and not any(word in entry.name.lower() for word in _AVOID):
                    status = entry.stat(follow_symlinks=False)
                    count += 1
                    if count > limit:
                        return
                    yield entry.path, status.st_size, status.st_mtime_ns
            except OSError:
                continue


def read_lines_ex(path, offset: int, limit: int = CHUNK_BYTES):
    """Complete lines after `offset` with their end offsets: ([(end_offset, line)], new_offset, oversize_skipped).

    The end offset is the position just after the line's newline, so a caller can stop at any line and
    resume from the previous end. A partial last line is left unread."""
    with open(path, "rb") as handle:
        handle.seek(offset)
        chunk = handle.read(limit)
    if not chunk:
        return [], offset, 0
    pieces = chunk.split(b"\n")
    tail = pieces.pop()
    if not pieces:
        if len(chunk) >= limit >= MAX_LINE:
            return [], offset + len(chunk), 1  # a single line longer than the chunk: skip it visibly
        return [], offset, 0
    consumed = len(chunk) - len(tail)
    lines, position, big = [], offset, 0
    for piece in pieces:
        position += len(piece) + 1
        line = piece.rstrip(b"\r")
        if not line.strip():
            continue
        if len(line) > MAX_LINE:
            big += 1
        else:
            lines.append((position, line))
    return lines, offset + consumed, big


def read_lines(path, offset: int, limit: int = CHUNK_BYTES):
    """Complete lines after `offset`: (lines, new_offset, oversize_skipped). A partial last line is left unread."""
    entries, new_offset, big = read_lines_ex(path, offset, limit)
    return [line for _end, line in entries], new_offset, big


def _valid_cwd(value) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 4096 and "\x00" not in value


class NativeIndex:
    def __init__(self, roots: dict, files: dict | None = None):
        self.roots = {name: Path(path) for name, path in roots.items() if path}
        self.files: dict = files if isinstance(files, dict) else {}
        self.dirty = False
        self.invalid_utf8 = 0  # lines read with replaced bytes since the last refresh
        self._by_id: dict = {}
        self._rebuild()

    def _rebuild(self):
        self._by_id = {}
        for path, record in self.files.items():
            for session_id in record.get("ids", {}):
                self._by_id.setdefault(session_id, []).append(path)

    def dump(self) -> dict:
        return self.files

    def lookup(self, native_id: str) -> list[dict]:
        found = []
        for path in self._by_id.get(native_id, []):
            record = self.files[path]
            item = record["ids"][native_id]
            found.append({"source": record["source"], "file": path, "cwds": list(item["cwds"]), "over": bool(item.get("over"))})
        return found

    def _add(self, record: dict, session_id, cwd):
        if not isinstance(session_id, str) or not _ID.fullmatch(session_id) or not _valid_cwd(cwd):
            return
        ids = record["ids"]
        if session_id not in ids and len(ids) >= MAX_IDS_PER_FILE:
            return
        item = ids.setdefault(session_id, {"cwds": [], "over": False})
        if cwd in item["cwds"]:
            return
        if len(item["cwds"]) >= MAX_CWDS:
            item["over"] = True
        else:
            item["cwds"].append(cwd)

    def _parse(self, record: dict, lines: list) -> int:
        """Read ids and folders from complete lines. Returns the number of lines that were not valid UTF-8:
        they are still read (undecodable bytes replaced) so one damaged byte does not hide a session's folder."""
        invalid = 0
        for line in lines:
            try:
                text = line.decode("utf-8") if isinstance(line, bytes) else line
            except UnicodeDecodeError:
                invalid += 1
                text = line.decode("utf-8", "replace")
            try:
                value = json.loads(text)
            except (ValueError, RecursionError):
                continue
            if not isinstance(value, dict):
                continue
            if record["source"] == "codex":
                payload = value.get("payload")
                if value.get("type") == "session_meta" and isinstance(payload, dict):
                    self._add(record, payload.get("id"), payload.get("cwd"))
            else:
                self._add(record, value.get("sessionId"), value.get("cwd"))
        return invalid

    def _first_sight(self, source: str, path: str, size: int, mtime: int) -> tuple[dict, int]:
        record = {"source": source, "size": size, "mtime": mtime, "off": 0, "ids": {}}
        lines, offset, skipped = read_lines(path, 0, min(size, HEAD_BYTES) or 1)
        self.invalid_utf8 += self._parse(record, lines)
        record["off"] = offset if size <= HEAD_BYTES else size
        return record, min(size, HEAD_BYTES)

    def refresh(self, wanted=(), budget: int = 8 * 1024 * 1024) -> dict:
        """Scan roots (names and stat only), then read a bounded amount of new bytes."""
        stats = {"new": 0, "grown": 0, "rewritten": 0, "deleted": 0, "oversize_lines": 0, "deferred": 0, "files": 0, "invalid_utf8": 0}
        self.invalid_utf8 = 0
        seen = {}
        for source, root in self.roots.items():
            if not root.is_dir():
                continue
            for path, size, mtime in iter_files(root):
                seen[path] = (source, size, mtime)
        stats["files"] = len(seen)
        wanted = [value for value in wanted if isinstance(value, str) and value]
        for path in [path for path, record in self.files.items() if path not in seen and self.roots.get(record["source"], Path("/nonexistent")).is_dir()]:
            del self.files[path]
            stats["deleted"] += 1
            self.dirty = True
        def priority(item):
            path, (source, size, mtime) = item
            known = self.files.get(path)
            changed = known is None or size != known["size"] or mtime != known["mtime"] or known["off"] < size
            return (0 if any(value in Path(path).name for value in wanted) and (known is None or changed) else 1 if changed else 2, -mtime)
        for path, (source, size, mtime) in sorted(seen.items(), key=priority):
            known = self.files.get(path)
            try:
                if known is None:
                    if budget <= 0:
                        stats["deferred"] += 1
                        continue
                    self.files[path], used = self._first_sight(source, path, size, mtime)
                    budget -= used
                    stats["new"] += 1
                elif size < known["off"]:
                    self.files[path], used = self._first_sight(source, path, size, mtime)
                    budget -= used
                    stats["rewritten"] += 1
                elif size == known["size"] and mtime != known["mtime"] and known["off"] >= size:
                    # Same length, new mtime: an in-place rewrite (or a touch). The old id/cwd mapping is
                    # dropped and re-read rather than trusted; a touch costs one bounded head read.
                    if budget <= 0:
                        stats["deferred"] += 1
                        continue
                    self.files[path], used = self._first_sight(source, path, size, mtime)
                    budget -= used
                    stats["rewritten"] += 1
                elif known["off"] < size:
                    if budget <= 0:
                        stats["deferred"] += 1
                        continue
                    lines, offset, skipped = read_lines(path, known["off"], min(CHUNK_BYTES, max(budget, 1)))
                    self.invalid_utf8 += self._parse(known, lines)
                    budget -= max(offset - known["off"], 1)
                    known["off"] = offset
                    known["size"], known["mtime"] = size, mtime
                    stats["grown"] += 1
                    stats["oversize_lines"] += skipped
                else:
                    known["size"], known["mtime"] = size, mtime
                    continue
                self.dirty = True
            except OSError:
                continue
        stats["invalid_utf8"] = self.invalid_utf8
        if self.dirty:
            self._rebuild()
        return stats
