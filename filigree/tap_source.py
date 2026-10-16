"""Read-only adapter for a claude-tap SQLite trace store (schema v4).

Never imports claude_tap, never migrates or writes the database, never creates its folder.
Trace content is data: it is decoded, bounded and filtered, never executed or trusted.
Identifiers found in records are claims, not authenticated identities.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

SCHEMA_VERSION = 4
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
MAX_REFS = 4096
MAX_MATERIALIZED = 32 * 1024 * 1024
BATCH = 200
MARKER = "__claude_tap_compact_record__"
BLOB_KEY = "__claude_tap_blob_ref__"
FIXED_PATHS = ("/request/body/instructions", "/request/body/tools", "/response/body/instructions", "/response/body/tools")
_PATH = re.compile(r"/request/body/(?:input|messages)/(?:0|[1-9][0-9]{0,5})")
_HASH = re.compile(r"sha256:[0-9a-f]{64}")
_NATIVE_VALUE = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
REQUIRED_COLUMNS = {
    "sessions": {"id", "client", "started_at", "updated_at", "record_count"},
    "records": {"session_id", "record_index", "timestamp", "payload_json"},
    "record_blobs": {"session_id", "hash", "kind", "payload_json", "size_bytes"},
}
TEXT_LIMIT, CALL_LIMIT, RESULT_LIMIT, ERROR_LIMIT = 6000, 1500, 2000, 300
# Context a client injects around the user's own words. Only the tagged blocks are removed: what the user wrote
# next to them is kept. A block that never closes is dropped up to the end (its extent is unknown, so none of it is trusted).
_INJECTED_TAG = r"(?:environment_context|user_instructions|system[-_]reminder|permissions|collaboration_mode|developer|instructions|local-command-[\w-]+|command-[\w-]+|ide_[\w-]+)"
_BLOCK = re.compile(r"<(?P<tag>" + _INJECTED_TAG + r")(?:\s[^>]*)?>.*?</(?P=tag)(?:\s[^>]*)?>", re.S | re.I)
_UNCLOSED = re.compile(r"<" + _INJECTED_TAG + r"(?:\s[^>]*)?>.*", re.S | re.I)
_STRAY_CLOSE = re.compile(r"</" + _INJECTED_TAG + r"(?:\s[^>]*)?>", re.I)
_AGENTS_HEADER = "# agents.md instructions"
_BAD_TEXT = re.compile("[\x00\ud800-\udfff]")
_CALL_TYPES = {"tool_use", "server_tool_use", "function_call", "custom_tool_call", "local_shell_call"}
_RESULT_TYPES = {"tool_result", "function_call_output", "custom_tool_call_output"}
# Internal reasoning, however a client labels it: by channel/phase on a message, or by block type.
_PRIVATE_CHANNELS = {"analysis", "reasoning", "thinking", "thought", "thoughts", "scratchpad", "chain_of_thought", "cot", "internal"}
_PRIVATE_TYPES = {"thinking", "redacted_thinking", "reasoning", "reasoning_text", "reasoning_summary", "analysis"}


class RecordError(ValueError):
    """A record cannot be decoded safely; the whole record is rejected."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def resolve_db_path(settings=None, env=None) -> Path:
    """Same order as upstream, preceded by the Filigree override."""
    env = os.environ if env is None else env
    configured = ((settings or {}).get("tap") or {}).get("db")
    if configured:
        return Path(str(configured)).expanduser().resolve()
    if env.get("CLOUDTAP_DB"):
        return Path(env["CLOUDTAP_DB"]).expanduser().resolve()
    if env.get("XDG_DATA_HOME"):
        return Path(env["XDG_DATA_HOME"]).expanduser() / "claude-tap" / "traces.sqlite3"
    return Path.home() / ".local" / "share" / "claude-tap" / "traces.sqlite3"


def db_key(path) -> str:
    """Stable, non-reversible identifier of the database file for provenance."""
    return hashlib.sha256(os.path.normcase(str(path)).encode("utf-8")).hexdigest()[:16]


_invalid_text = [0]


def _tolerant_text(raw: bytes) -> str:
    """One undecodable byte must not make the whole database unreadable: it is replaced and counted."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        _invalid_text[0] += 1
        return raw.decode("utf-8", "replace")


def take_invalid_text() -> int:
    """Texts that needed replacement since the last call (read, then reset)."""
    count, _invalid_text[0] = _invalid_text[0], 0
    return count


def open_db(path):
    """Return (connection | None, capability). Capability is ok, missing, locked, corrupt or unsupported_schema."""
    path = Path(path)
    if not path.is_file():
        return None, "missing"
    connection = None
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
        connection.execute("PRAGMA query_only=ON")
        connection.text_factory = _tolerant_text
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            connection.close()
            return None, "unsupported_schema"
        for table, wanted in REQUIRED_COLUMNS.items():
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            if not wanted <= columns:
                connection.close()
                return None, "unsupported_schema"
        return connection, "ok"
    except sqlite3.OperationalError as exc:
        if connection is not None:
            connection.close()
        return None, "locked" if "locked" in str(exc).lower() or "busy" in str(exc).lower() else "corrupt"
    except sqlite3.DatabaseError:
        if connection is not None:
            connection.close()
        return None, "corrupt"


def probe(path) -> dict:
    """Capability report without reading any record."""
    connection, capability = open_db(path)
    result = {"path": str(path), "capability": capability, "sessions": 0}
    if connection is not None:
        try:
            result["sessions"] = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        finally:
            connection.close()
    return result


def list_sessions(connection) -> dict:
    """{session_id: {client, max_index, updated_at}}; one bounded aggregate query."""
    rows = connection.execute("SELECT s.id, s.client, s.updated_at, (SELECT MAX(record_index) FROM records r WHERE r.session_id = s.id) FROM sessions s ORDER BY s.id").fetchall()
    return {row[0]: {"client": repair_text(row[1]) if isinstance(row[1], str) else "", "updated_at": row[2], "max_index": int(row[3] or 0)} for row in rows if isinstance(row[0], str)}


def read_batch(connection, session_id: str, after: int, limit: int = BATCH, upto: int | None = None) -> list[tuple]:
    """Rows (record_index, timestamp, payload_text | None, byte_length). None text means oversize."""
    sql = ("SELECT record_index, timestamp, CASE WHEN LENGTH(CAST(payload_json AS BLOB)) <= ? THEN payload_json END, LENGTH(CAST(payload_json AS BLOB)) "
           "FROM records WHERE session_id = ? AND record_index > ? " + ("AND record_index <= ? " if upto is not None else "") + "ORDER BY record_index LIMIT ?")
    parameters = [MAX_PAYLOAD_BYTES, session_id, after] + ([upto] if upto is not None else []) + [limit]
    return connection.execute(sql, parameters).fetchall()


def read_rows(connection, session_id: str, indexes: list[int]) -> list[tuple]:
    rows = []
    for start in range(0, len(indexes), 100):
        chunk = indexes[start:start + 100]
        marks = ",".join("?" * len(chunk))
        rows += connection.execute(f"SELECT record_index, timestamp, CASE WHEN LENGTH(CAST(payload_json AS BLOB)) <= ? THEN payload_json END, LENGTH(CAST(payload_json AS BLOB)) FROM records WHERE session_id = ? AND record_index IN ({marks}) ORDER BY record_index", [MAX_PAYLOAD_BYTES, session_id, *chunk]).fetchall()
    return rows


def payload_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def _is_blob_ref(node) -> bool:
    return isinstance(node, dict) and len(node) == 1 and BLOB_KEY in node and isinstance(node[BLOB_KEY], dict)


def _walk(root, path: str):
    """Return (container, key) for a pointer made of dict keys and list indexes."""
    parts = path.strip("/").split("/")
    node = root
    for part in parts[:-1]:
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            raise RecordError("unsupported_ref_path")
    last = parts[-1]
    if isinstance(node, dict) and last in node:
        return node, last
    if isinstance(node, list) and last.isdigit() and int(last) < len(node):
        return node, int(last)
    raise RecordError("unsupported_ref_path")


def _candidate_paths(record) -> list[str]:
    paths = [path for path in FIXED_PATHS]
    body = ((record.get("request") or {}).get("body") if isinstance(record.get("request"), dict) else None)
    if isinstance(body, dict):
        for name in ("input", "messages"):
            if isinstance(body.get(name), list):
                paths += [f"/request/body/{name}/{index}" for index in range(min(len(body[name]), MAX_REFS))]
    return paths


def decode_payload(connection, session_id: str, text: str):
    """Decode a raw or compact record. Any anomaly rejects the whole record (RecordError)."""
    try:
        outer = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise RecordError("invalid_json") from exc
    if not isinstance(outer, dict):
        raise RecordError("invalid_record")
    if MARKER not in outer:
        return outer
    meta, record = outer.get(MARKER), outer.get("record")
    if set(outer) != {MARKER, "record"} or not isinstance(meta, dict) or not isinstance(record, dict):
        raise RecordError("invalid_envelope")
    if meta.get("version") != 1 or meta.get("encoding") != "json-blob-ref":
        raise RecordError("unsupported_record_version")
    refs = meta.get("refs", [])
    if not isinstance(refs, list):
        raise RecordError("invalid_envelope")
    if len(refs) > MAX_REFS:
        raise RecordError("too_many_refs")
    plan = []
    if refs:
        seen = set()
        for ref in refs:
            if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or ref["path"] in seen:
                raise RecordError("unsupported_ref_path")
            if ref["path"] not in FIXED_PATHS and not _PATH.fullmatch(ref["path"]):
                raise RecordError("unsupported_ref_path")
            if not isinstance(ref.get("hash"), str) or not _HASH.fullmatch(ref["hash"]) or type(ref.get("bytes")) is not int or ref["bytes"] < 0:
                raise RecordError("blob_mismatch")
            seen.add(ref["path"])
            plan.append((ref["path"], ref["hash"], ref["bytes"]))
    else:
        for path in _candidate_paths(record):
            try:
                container, key = _walk(record, path)
            except RecordError:
                continue
            node = container[key]
            if _is_blob_ref(node):
                inner = node[BLOB_KEY]
                if not isinstance(inner.get("hash"), str) or not _HASH.fullmatch(inner["hash"]) or type(inner.get("bytes")) is not int or inner["bytes"] < 0:
                    raise RecordError("blob_mismatch")
                plan.append((path, inner["hash"], inner["bytes"]))
    total = 0
    values = {}
    for path, digest, size in plan:
        container, key = _walk(record, path)
        node = container[key]
        if not _is_blob_ref(node):
            raise RecordError("invalid_blob_ref")
        inner = node[BLOB_KEY]
        # Every reference must state its own version, kind, hash and size, and agree with the plan,
        # even when several references share one hash.
        if inner.get("version") != 1 or inner.get("kind") != "json" or inner.get("hash") != digest or type(inner.get("bytes")) is not int or inner["bytes"] != size:
            raise RecordError("blob_mismatch")
        # The logical size counts once per reference: shared objects still expand when walked or serialized.
        total += size
        if total > MAX_MATERIALIZED:
            raise RecordError("too_large")
        if digest not in values:
            # The size test runs inside SQLite so an oversized blob is never loaded into memory.
            row = connection.execute("SELECT CASE WHEN LENGTH(CAST(payload_json AS BLOB)) <= ? THEN payload_json END, size_bytes, LENGTH(CAST(payload_json AS BLOB)) FROM record_blobs WHERE session_id = ? AND hash = ? AND kind = 'json'", (size, session_id, digest)).fetchone()
            if row is None:
                raise RecordError("blob_missing")
            if row[0] is None and isinstance(row[2], int) and row[2] > size:
                raise RecordError("blob_mismatch")
            if not isinstance(row[0], str):
                raise RecordError("blob_missing")
            raw = row[0].encode("utf-8", "surrogatepass")
            if "sha256:" + hashlib.sha256(raw).hexdigest() != digest or row[1] != len(raw) or len(raw) != size:
                raise RecordError("blob_mismatch")
            try:
                values[digest] = (json.loads(row[0]), len(raw))
            except (ValueError, RecursionError) as exc:
                raise RecordError("blob_mismatch") from exc
        elif values[digest][1] != size:
            raise RecordError("blob_mismatch")
        container[key] = values[digest][0]
    return record


def _clean_value(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if _NATIVE_VALUE.fullmatch(value) else ""


def native_ids(record) -> set:
    """Exact native identifiers claimed by a decoded record: {(kind, value)}.

    An empty value means "present but unusable", which callers treat as a conflict signal.
    prompt_cache_key and capture.client are deliberately ignored.
    """
    found = set()
    if not isinstance(record, dict):
        return found
    request = record.get("request") if isinstance(record.get("request"), dict) else {}
    headers = request.get("headers") if isinstance(request.get("headers"), dict) else {}
    lowered = {str(key).lower(): value for key, value in headers.items()}
    body = request.get("body") if isinstance(request.get("body"), dict) else {}
    for name, kind in (("x-claude-code-session-id", "claude"), ("session_id", "codex"), ("session-id", "codex"), ("x-codex-app-session-id", "codexapp")):
        if name in lowered:
            found.add((kind, _clean_value(lowered[name]) or ""))
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    user_id = metadata.get("user_id")
    if isinstance(user_id, str) and user_id.lstrip().startswith("{"):
        try:
            user_id = json.loads(user_id)
        except ValueError:
            user_id = None
    if isinstance(user_id, dict) and "session_id" in user_id:
        found.add(("claude", _clean_value(user_id["session_id"]) or ""))
    if "codex_app_session_id" in metadata:
        found.add(("codexapp", _clean_value(metadata["codex_app_session_id"]) or ""))
    client_metadata = body.get("client_metadata") if isinstance(body.get("client_metadata"), dict) else {}
    # Codex announces both session_id and thread_id; they are two claims about one identity, so any
    # divergence (or an unusable value) surfaces as a conflict instead of being resolved.
    for turn in (client_metadata.get("x-codex-turn-metadata"), lowered.get("x-codex-turn-metadata")):
        if isinstance(turn, str):
            try:
                turn = json.loads(turn)
            except ValueError:
                turn = None
        if isinstance(turn, dict):
            for name in ("session_id", "thread_id"):
                if name in turn:
                    found.add(("codex", _clean_value(turn[name]) or ""))
    return found


def agent_label(kinds, client: str = "") -> str:
    kinds = {kind for kind in kinds if kind}
    if kinds & {"codex", "codexapp"} and not kinds & {"claude"}:
        return "Codex"
    if "claude" in kinds and not kinds & {"codex", "codexapp"}:
        return "Claude Code"
    lowered = (client or "").lower()
    return "Codex" if lowered.startswith("codex") else "Claude Code" if lowered.startswith("claude") else "Agent"


def clip(text: str, limit: int, tail: bool = False) -> str:
    if len(text) <= limit:
        return text
    if tail:
        head = limit * 2 // 5
        return text[:head] + "\n[…tronqué…]\n" + text[-(limit - head):]
    return text[:limit] + " […tronqué]"


def repair_text(text, skipped: dict | None = None):
    """NUL and lone surrogates cannot be stored: they become U+FFFD, and the repair is counted."""
    if not isinstance(text, str) or not _BAD_TEXT.search(text):
        return text
    if skipped is not None:
        skipped["invalid_text_repaired"] = skipped.get("invalid_text_repaired", 0) + 1
    return _BAD_TEXT.sub("�", text)


def strip_injected(text: str) -> str:
    """Remove the injected tagged blocks and keep everything else."""
    return _STRAY_CLOSE.sub("", _UNCLOSED.sub("", _BLOCK.sub("", text)))


def visible_text(text) -> str:
    if not isinstance(text, str) or text.lstrip().lower().startswith(_AGENTS_HEADER):
        return ""
    return strip_injected(text).strip()


def is_private(node) -> bool:
    """True for a message or block that carries the model's internal reasoning rather than a visible answer."""
    if not isinstance(node, dict):
        return False
    if isinstance(node.get("type"), str) and node["type"].lower() in _PRIVATE_TYPES:
        return True
    return any(isinstance(node.get(key), str) and node[key].strip().lower() in _PRIVATE_CHANNELS for key in ("channel", "phase"))


def _text_of(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(part for part in (_text_of(item) for item in value) if part)
    if isinstance(value, dict) and value.get("type") in {None, "text", "output_text", "input_text"}:
        return value.get("text") if isinstance(value.get("text"), str) else ""
    return ""


def _call_item(block, skipped: dict | None = None) -> dict:
    name = repair_text(block.get("name") if isinstance(block.get("name"), str) else str(block.get("type", "outil")), skipped)
    arguments = block.get("input", block.get("arguments", block.get("action", {})))
    if not isinstance(arguments, str):
        try:
            arguments = json.dumps(arguments, ensure_ascii=False)
        except (TypeError, ValueError):
            arguments = ""
    return {"kind": "tool_call", "name": name[:80], "text": clip(strip_injected(repair_text(arguments, skipped)).strip(), CALL_LIMIT)}


def _result_item(block, skipped: dict | None = None) -> dict:
    value = block.get("content", block.get("output"))
    text = strip_injected(repair_text(_text_of(value) if not isinstance(value, dict) else json.dumps(value, ensure_ascii=False), skipped)).strip()
    return {"kind": "tool_result", "text": clip(text, RESULT_LIMIT, tail=True), "error": bool(block.get("is_error"))}


def content_items(role: str, content, skipped: dict, private: bool = False) -> list[dict]:
    """Visible items of one message. `private` marks the whole message as internal reasoning."""
    items = []
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    if not isinstance(content, list):
        return items
    if private:
        skipped["analysis"] = skipped.get("analysis", 0) + 1
        return items
    for block in content:
        if isinstance(block, str):
            block = {"type": "text", "text": block}
        if not isinstance(block, dict):
            continue
        if is_private(block):
            skipped["analysis"] = skipped.get("analysis", 0) + 1
            continue
        kind = block.get("type")
        if kind in {"text", "input_text", "output_text"}:
            text = visible_text(repair_text(block.get("text"), skipped))
            if text:
                items.append({"kind": "user_text" if role == "user" else "assistant_text", "text": clip(text, TEXT_LIMIT)})
            else:
                skipped["injected"] = skipped.get("injected", 0) + 1
        elif kind in _CALL_TYPES:
            items.append(_call_item(block, skipped))
        elif kind in _RESULT_TYPES:
            items.append(_result_item(block, skipped))
        else:
            skipped[str(kind or "unknown")[:40]] = skipped.get(str(kind or "unknown")[:40], 0) + 1
    return items


def _http_error(response) -> dict | None:
    status = response.get("status")
    failed = response.get("error") is not None
    if type(status) is int and not (200 <= status < 300 or status == 101):
        failed = True
    if not failed:
        return None
    detail = ""
    body = response.get("body")
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        detail = " ".join(str(error.get(key)) for key in ("type", "code", "message") if isinstance(error.get(key), (str, int)))
    elif isinstance(error, str):
        detail = error
    elif isinstance(response.get("error"), str):
        detail = response["error"]
    label = f"HTTP {status}" if type(status) is int else "Erreur de transport"
    return {"kind": "http_error", "text": clip(repair_text(label + (" · " + detail if detail else "")).strip(), ERROR_LIMIT)}


def is_side_request(body: dict) -> bool:
    """Verified auxiliary traffic only: the one-token warm-up (`max_tokens == 1`).

    Nothing else is verified. Missing or empty `tools` and a structured-output (JSON schema) format are legitimate in a
    user's conversation, so neither discards anything: an auxiliary call without a verified marker is captured as a
    project-linked proposal that the human review can reject, rather than silently losing a possible user decision.
    """
    return body.get("max_tokens") == 1


def extract_turn(record) -> dict:
    """The new visible turn of one exchange: {"items": [...], "skipped": {...}}.

    Only the trailing user turn of the request is read (histories repeat everything). Thinking,
    reasoning, system/developer and injected instruction blocks are skipped and counted.
    """
    skipped: dict = {}
    result = {"items": [], "skipped": skipped}
    request = record.get("request") if isinstance(record, dict) and isinstance(record.get("request"), dict) else None
    response = record.get("response") if isinstance(record, dict) and isinstance(record.get("response"), dict) else {}
    if request is None:
        skipped["non_conversation"] = 1
        return result
    path = str(request.get("path", "")).split("?")[0].rstrip("/")
    body = request.get("body")
    if not path.endswith(("/messages", "/responses")) or not isinstance(body, dict):
        skipped["non_conversation"] = 1
        return result
    if is_side_request(body):
        skipped["side_request"] = 1
        return result
    items = result["items"]
    messages = body.get("messages")
    if isinstance(messages, list) and messages and isinstance(messages[-1], dict) and messages[-1].get("role") == "user":
        items += content_items("user", messages[-1].get("content"), skipped)
    entries = body.get("input")
    if isinstance(entries, str):
        entries = [{"role": "user", "content": entries}]
    if isinstance(entries, list):
        trailing = []
        for entry in reversed(entries):
            if isinstance(entry, dict) and (entry.get("type") in _RESULT_TYPES or (entry.get("role") == "user" and entry.get("type") in {None, "message"})):
                trailing.append(entry)
            else:
                break
        for entry in reversed(trailing):
            if entry.get("type") in _RESULT_TYPES:
                items.append(_result_item(entry, skipped))
            else:
                items += content_items("user", entry.get("content"), skipped)
    failure = _http_error(response)
    if failure:
        items.append(failure)
        skipped["non_2xx"] = 1
        return result
    answer = response.get("body")
    if isinstance(answer, dict):
        if isinstance(answer.get("content"), list):
            items += content_items("assistant", answer["content"], skipped, private=is_private(answer))
        if isinstance(answer.get("output"), list):
            for entry in answer["output"]:
                if not isinstance(entry, dict):
                    continue
                if entry.get("type") == "message" and entry.get("role") == "assistant":
                    items += content_items("assistant", entry.get("content"), skipped, private=is_private(entry))
                elif entry.get("type") in _CALL_TYPES:
                    items.append(_call_item(entry, skipped))
                else:
                    skipped[str(entry.get("type", "unknown"))[:40]] = skipped.get(str(entry.get("type", "unknown"))[:40], 0) + 1
    return result
