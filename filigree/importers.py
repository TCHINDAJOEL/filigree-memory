"""Loss-aware adapters. Imported text is evidence, never an approved decision."""

import json
import re
from typing import Any

from .store import PreRedacted, redact_whole

MAX_RECORDS = 100000  # Hard parse limit; Store.import_events additionally bounds (and reports) each call.
MAX_DEPTH = 60
_SURROGATES = re.compile("[\ud800-\udfff]")


def decode_import_bytes(data: bytes) -> str:
    """Decode a file for import: UTF-8 (BOM allowed), UTF-16 with BOM, else Windows-1252 as a last resort."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return data.decode("cp1252")
        except UnicodeDecodeError as exc:
            raise ValueError("Encodage du fichier non reconnu : enregistrez-le en UTF-8.") from exc


def _clean(value: Any, counter: list) -> Any:
    """Untrusted records: drop NUL and replace lone surrogates instead of failing the whole import."""
    if isinstance(value, str):
        clean = _SURROGATES.sub("�", value.replace("\x00", ""))
        counter[0] += clean != value
        return clean
    if isinstance(value, list):
        return [_clean(item, counter) for item in value]
    if isinstance(value, dict):
        return {(_clean(key, counter) if isinstance(key, str) else key): _clean(item, counter) for key, item in value.items()}
    return value


def _kind(value: Any) -> str:
    return value if isinstance(value, str) else ""


def content_text(value: Any, _depth: int = 0) -> str:
    if _depth > MAX_DEPTH:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (content_text(item, _depth + 1) for item in value)))
    if isinstance(value, dict):
        kind = _kind(value.get("type"))
        if kind in {"thinking", "redacted_thinking", "reasoning", "reasoning_text", "summary_text"}:
            return ""  # Do not treat private/internal reasoning as project knowledge.
        if kind in {"tool_use", "function_call"}:
            return f"Tool: {value.get('name', 'unknown')}\n{json.dumps(value.get('input', value.get('arguments', {})), ensure_ascii=False)}"
        if kind in {"tool_result", "function_call_output"}:
            return content_text(value.get("content", value.get("output", "")), _depth + 1)
        return content_text(value.get("text", value.get("content", "")), _depth + 1)
    return ""


def parse_import_detailed(text: str, source: str = "import") -> dict:
    """Like parse_import, plus what was cleaned: {"events", "sanitized"} (records touched by NUL/surrogate cleanup)."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Le fichier est vide.")
    try:
        return _parse(text, source)
    except RecursionError as exc:
        raise ValueError("Structure JSON trop profondément imbriquée pour être importée.") from exc


def parse_import(text: str, source: str = "import") -> list[dict]:
    """Accept normalized events, tap full JSON/legacy JSONL and agent transcripts."""
    return parse_import_detailed(text, source)["events"]


def _parse(text: str, source: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = [json.loads(line) for line in text.splitlines() if line.strip()]
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON ou JSONL invalide : {exc.msg} (ligne {exc.lineno}).") from exc
    sanitized = [0]
    data = _clean(data, sanitized)
    if isinstance(data, dict) and ("blobs" in data or "content_table" in data or data.get("format") == "claude-tap"):
        raise ValueError("Export compact claude-tap non pris en charge. Réexportez avec --format json.")
    records = data if isinstance(data, list) else [data]
    if len(records) > MAX_RECORDS:
        raise ValueError(f"Maximum {MAX_RECORDS} enregistrements par import.")
    events: list[dict] = []

    def add(body: Any, role: Any, record: dict, label: str, occurrence: str = "") -> None:
        role = role if isinstance(role, str) and role else "message"
        if role in {"system", "developer"}:
            return
        rendered, found = redact_whole(content_text(body).strip())  # before the title/excerpt cuts below
        if not rendered:
            return
        event = PreRedacted({
            "title": f"{role} · {rendered.splitlines()[0][:100]}",
            "body": rendered, "agent": str(record.get("model") or role),
            "episode": str(record.get("session_id") or record.get("sessionId") or source),
            "timestamp": str(record.get("timestamp", "")),
            "sources": [{"label": label + (f" · {record['timestamp']}" if record.get('timestamp') else ''), "excerpt": rendered[:4000], "uri": ""}],
            "pre_redactions": found,
        })
        if occurrence:
            event["occurrence"] = occurrence  # A transcript line is one utterance: "yes" twice stays two events.
        events.append(event)

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"L'enregistrement {index + 1} doit être un objet JSON.")
        label = f"{source} · enregistrement {index + 1}"
        occurrence = f"record-{index + 1}"
        rtype = _kind(record.get("type"))
        if "body" in record and isinstance(record["body"], str):
            # The client's own record: the excerpt we derive is redacted before it is cut. The record stays a plain dict,
            # so the store does the counting for it and a client cannot supply a redaction count.
            excerpt, _found = redact_whole(record["body"])
            events.append({**record, "sources": record.get("sources") or [{"label": label, "excerpt": excerpt[:4000], "uri": ""}]})
            continue
        if "request" in record or "messages" in record:
            request = record.get("request") or {}
            if not isinstance(request, dict):
                raise ValueError("La requête doit être un objet JSON.")
            request = request.get("body", request)
            if not isinstance(request, dict):
                raise ValueError("Le corps de requête doit être un objet JSON.")
            messages = record.get("messages", request.get("messages", request.get("input", [])))
            if isinstance(messages, str):
                messages = [{"role": "user", "content": messages}]
            if not isinstance(messages, list):
                raise ValueError("Le champ messages doit être une liste.")
            for message in messages:
                if isinstance(message, dict) and message.get("role") != "system":
                    add(message.get("content", message.get("output", "")), message.get("role", "message"), record, label)
            response = record.get("response") or {}
            if record.get("ws_events") or (isinstance(response, dict) and response.get("ws_events")):
                raise ValueError("Traces WebSocket non prises en charge. Utilisez le transcript JSONL du client ; aucun import partiel n'a été enregistré.")
            response = response.get("body", response) if isinstance(response, dict) else {}
            if isinstance(response, dict):
                add(response.get("content", response.get("output", "")), "assistant", record, label)
            continue
        if rtype in {"user", "assistant"} and isinstance(record.get("message"), dict):
            message = record["message"]
            add(message.get("content", ""), message.get("role", rtype), record, label, occurrence)
            continue
        if rtype == "response_item":
            payload = record.get("payload", {})
            if not isinstance(payload, dict):
                raise ValueError("Le payload Codex doit être un objet JSON.")
            if _kind(payload.get("type")) in {"reasoning", "thinking", "redacted_thinking"}:
                continue
            add(payload.get("content", payload.get("output", "")), payload.get("role", "tool"), record, label, occurrence)
            continue
        if "content" in record:
            add(record["content"], record.get("role", "message"), record, label, occurrence)
    if not events:
        raise ValueError("Aucun échange exploitable. Formats : événements normalisés, export claude-tap --format json, JSONL Claude/Codex.")
    if len(events) > MAX_RECORDS:
        raise ValueError(f"Maximum {MAX_RECORDS} événements extraits par import.")
    return {"events": events, "sanitized": sanitized[0]}


def parse_text(text: str, source: str = "note") -> list[dict]:
    """Explicit plain-text import: one unapproved observation, no invented extraction."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("La note est vide.")
    text = _SURROGATES.sub("�", text.replace("\x00", ""))
    text, found = redact_whole(text)  # before the title/excerpt cuts below
    return [PreRedacted({"title": text.strip().splitlines()[0][:160], "body": text, "episode": source[:240], "agent": "Note importée", "sources": [{"label": source[:240], "excerpt": text[:4000], "uri": ""}], "pre_redactions": found})]
