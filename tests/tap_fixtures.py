"""Synthetic claude-tap v4 fixtures. Written by hand from the documented DDL; never imports claude_tap
and never touches a real trace database or transcript."""

import copy
import hashlib
import json
from pathlib import Path
import sqlite3

MARKER = "__claude_tap_compact_record__"
BLOB_KEY = "__claude_tap_blob_ref__"
SESSIONS = "CREATE TABLE sessions(id TEXT PRIMARY KEY, started_at TEXT, updated_at TEXT, date_key TEXT, client TEXT, proxy_mode TEXT, status TEXT, record_count INTEGER, summary_json TEXT, legacy_source_key TEXT, legacy_rel_path TEXT)"
RECORDS = "CREATE TABLE records(session_id TEXT, record_index INTEGER, turn INTEGER, timestamp TEXT, payload_json TEXT, PRIMARY KEY(session_id, record_index))"
BLOBS = "CREATE TABLE record_blobs(session_id TEXT, hash TEXT, kind TEXT, payload_json TEXT, {size}created_at TEXT, PRIMARY KEY(session_id, hash))"


class TapDB:
    def __init__(self, path):
        self.path = Path(path)
        self.connection = None
        self.counter = 0

    def create(self, version=4, wal=False, omit_size=False):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.open()
        if wal:
            self.connection.execute("PRAGMA journal_mode=WAL")
        for ddl in (SESSIONS, RECORDS, BLOBS.format(size="" if omit_size else "size_bytes INTEGER, ")):
            self.connection.execute(ddl)
        self.connection.execute(f"PRAGMA user_version={version}")
        return self

    def open(self):
        self.connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        return self

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def add_session(self, session_id, client="claude"):
        self.connection.execute("INSERT INTO sessions(id, started_at, updated_at, client, status, record_count) VALUES (?, 's', 'u0', ?, 'active', 0)", (session_id, client))

    def compact(self, session_id, record):
        record = copy.deepcopy(record)
        body = record["request"]["body"]
        refs = []
        for name in ("messages", "input"):
            for index, item in enumerate(body.get(name, [])):
                blob = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                raw = blob.encode("utf-8")
                if len(raw) < 512:
                    continue
                digest = "sha256:" + hashlib.sha256(raw).hexdigest()
                self.connection.execute("INSERT OR IGNORE INTO record_blobs(session_id, hash, kind, payload_json, size_bytes, created_at) VALUES (?, ?, 'json', ?, ?, 'c')", (session_id, digest, blob, len(raw)))
                body[name][index] = {BLOB_KEY: {"version": 1, "kind": "json", "hash": digest, "bytes": len(raw)}}
                refs.append({"path": f"/request/body/{name}/{index}", "hash": digest, "bytes": len(raw)})
        return json.dumps({MARKER: {"version": 1, "encoding": "json-blob-ref", "refs": refs}, "record": record}, ensure_ascii=False)

    def add_record(self, session_id, record, compact=False, raw_text=None):
        index = self.connection.execute("SELECT COALESCE(MAX(record_index), 0) FROM records WHERE session_id = ?", (session_id,)).fetchone()[0] + 1
        text = raw_text if raw_text is not None else self.compact(session_id, record) if compact else json.dumps(record, ensure_ascii=False)
        self.counter += 1
        self.connection.execute("INSERT INTO records(session_id, record_index, turn, timestamp, payload_json) VALUES (?, ?, ?, ?, ?)", (session_id, index, index, f"2026-10-16T10:00:{index % 60:02d}+00:00", text))
        self.connection.execute("UPDATE sessions SET record_count = ?, updated_at = ? WHERE id = ?", (index, f"u{id(self)}-{self.counter:06d}", session_id))
        return index

    def payload(self, session_id, index):
        return self.connection.execute("SELECT payload_json FROM records WHERE session_id = ? AND record_index = ?", (session_id, index)).fetchone()[0]


def claude_record(session, user_text, answer="Réponse visible", *, header=True, metadata=True, history=0, status=200, tool=None, last_blocks=None, path="/v1/messages", tools=True):
    messages = []
    for number in range(history):
        messages += [{"role": "user", "content": f"ancien message {number}"}, {"role": "assistant", "content": [{"type": "text", "text": f"ancienne réponse {number}"}]}]
    messages.append({"role": "user", "content": last_blocks if last_blocks is not None else [{"type": "text", "text": user_text}]})
    content = [{"type": "thinking", "thinking": "raisonnement caché"}, {"type": "text", "text": answer}]
    if tool:
        content.append({"type": "tool_use", "id": "toolu_1", "name": tool[0], "input": tool[1]})
    body = {"model": "synthetic", "messages": messages, "system": "consigne système privée"}
    if tools:
        body["tools"] = [{"name": "Bash"}]
    if metadata and session:
        body["metadata"] = {"user_id": json.dumps({"device_id": "d", "account_uuid": "a", "session_id": session})}
    headers = {"authorization": "[REDACTED]"}
    if header and session:
        headers["X-Claude-Code-Session-Id"] = session
    response_body = {"content": content} if status < 300 else {"error": {"type": "rate_limit_error", "message": "Slow down"}}
    return {"timestamp": "2026-10-16T10:00:00+00:00", "request": {"method": "POST", "path": path, "headers": headers, "body": body}, "response": {"status": status, "headers": {}, "body": response_body}, "capture": {"client": "claude", "proxy_mode": "forward"}}


def codex_record(session, user_text, answer="Réponse Codex"):
    body = {"model": "synthetic", "tools": [{"type": "function", "name": "shell"}],
            "input": [{"role": "user", "content": [{"type": "input_text", "text": "<environment_context>cwd secret</environment_context>"}]}, {"role": "user", "content": [{"type": "input_text", "text": user_text}]}],
            "client_metadata": {"x-codex-turn-metadata": json.dumps({"session_id": session, "thread_id": session})}}
    output = [{"type": "reasoning", "summary": []}, {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": answer}]}]
    return {"timestamp": "2026-10-16T10:00:00+00:00", "request": {"method": "POST", "path": "/v1/responses", "headers": {"session_id": session}, "body": body}, "response": {"status": 200, "headers": {}, "body": {"output": output}}, "capture": {"client": "codex", "proxy_mode": "forward"}}


def write_claude_transcript(root, session, cwd, lines=1):
    folder = Path(root) / "-synthetic"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{session}.jsonl"
    rows = [{"type": "user", "sessionId": session, "cwd": str(cwd), "uuid": f"u-{session}-{n}", "message": {"role": "user", "content": f"note locale {n}"}} for n in range(lines)]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def claude_line(session, cwd, role, content, uuid):
    """One native Claude Code transcript row (a user or assistant message)."""
    return {"type": role, "sessionId": session, "cwd": str(cwd), "uuid": uuid, "message": {"role": role, "content": content}}


def codex_message(role, text, channel=None):
    """One native Codex rollout row; `channel` marks internal reasoning ("analysis")."""
    payload = {"type": "message", "role": role, "content": [{"type": "input_text" if role == "user" else "output_text", "text": text}]}
    if channel:
        payload["channel"] = channel
    return {"type": "response_item", "payload": payload}


def append_jsonl(path, *rows, partial=None):
    """Append complete JSON lines; `partial` appends raw text with no newline (a write still in progress)."""
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        if partial:
            handle.write(partial)


def write_codex_transcript(root, session, cwd):
    folder = Path(root) / "2026" / "10" / "16"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"rollout-2026-10-16T00-00-00-{session}.jsonl"
    path.write_text(json.dumps({"type": "session_meta", "payload": {"id": session, "cwd": str(cwd)}}) + "\n", encoding="utf-8")
    return path
