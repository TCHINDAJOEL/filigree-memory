"""Chat exports as proposals (ADR-0003 V2.3, D6): ChatGPT `conversations.json` and claude.ai exports.

The project is always explicit; nothing is matched by title, date or similarity. Each visible message becomes a
proposal with its conversation as episode. System, tool and hidden messages are skipped. A `.zip` is read with
size limits (no extraction to disk).
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import zipfile

from .importers import _clean, content_text, decode_import_bytes
from .store import PreRedacted, redact_whole

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_MESSAGES = 100000
ROLE_LABELS = {"user": "Humain", "human": "Humain", "assistant": "Assistant"}


def _load(path: Path):
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(f"Export trop volumineux ({size // 1048576} Mio) : maximum {MAX_FILE_BYTES // 1048576} Mio.")
    data = path.read_bytes()
    if path.suffix.lower() == ".zip" or data[:4] == b"PK\x03\x04":
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise ValueError("Archive ZIP illisible.") from exc
        member = next((info for info in archive.infolist() if Path(info.filename).name == "conversations.json"), None)
        if member is None:
            raise ValueError("L'archive ne contient pas de conversations.json (export ChatGPT ou claude.ai attendu).")
        if member.file_size > MAX_MEMBER_BYTES:
            raise ValueError("conversations.json dépasse la taille autorisée une fois décompressé.")
        with archive.open(member) as handle:
            data = handle.read(MAX_MEMBER_BYTES + 1)
        if len(data) > MAX_MEMBER_BYTES:
            raise ValueError("conversations.json dépasse la taille autorisée une fois décompressé.")
    try:
        return json.loads(decode_import_bytes(data))
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("conversations.json n'est pas un JSON valide.") from exc


def _chatgpt_messages(conversation: dict) -> list[dict]:
    """Messages of the branch the user last saw: from current_node up through parents, then in order."""
    mapping = conversation.get("mapping")
    if not isinstance(mapping, dict):
        return []
    node_id = conversation.get("current_node")
    chain, seen = [], set()
    while isinstance(node_id, str) and node_id in mapping and node_id not in seen:
        seen.add(node_id)
        node = mapping[node_id] if isinstance(mapping[node_id], dict) else {}
        chain.append(node)
        node_id = node.get("parent")
    out = []
    for node in reversed(chain):
        message = node.get("message")
        if not isinstance(message, dict):
            continue
        role = (message.get("author") or {}).get("role") if isinstance(message.get("author"), dict) else None
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if role not in {"user", "assistant"} or metadata.get("is_visually_hidden_from_conversation"):
            continue
        content = message.get("content") if isinstance(message.get("content"), dict) else {}
        if content.get("content_type") not in {None, "text", "multimodal_text"}:
            continue
        parts = content.get("parts") if isinstance(content.get("parts"), list) else []
        text = "\n".join(part for part in parts if isinstance(part, str)).strip()
        if text:
            out.append({"id": str(message.get("id") or node.get("id") or len(out)), "role": role, "text": text, "time": message.get("create_time")})
    return out


def _claude_messages(conversation: dict) -> list[dict]:
    out = []
    for index, message in enumerate(conversation.get("chat_messages") or []):
        if not isinstance(message, dict) or message.get("sender") not in {"human", "assistant"}:
            continue
        text = message.get("text") if isinstance(message.get("text"), str) and message.get("text").strip() else content_text([block for block in message.get("content") or [] if isinstance(block, dict) and block.get("type") == "text"])
        if text and text.strip():
            out.append({"id": str(message.get("uuid") or index), "role": message["sender"], "text": text.strip(), "time": message.get("created_at")})
    return out


def parse_chat_export(path) -> dict:
    """{"format", "conversations", "events"} ready for Store.import_events. Raises ValueError on an unknown shape."""
    path = Path(path)
    sanitized = [0]
    data = _clean(_load(path), sanitized)
    conversations = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    if not conversations or not all(isinstance(item, dict) for item in conversations):
        raise ValueError("Format non reconnu : une liste de conversations est attendue (export ChatGPT ou claude.ai).")
    if all("mapping" in item for item in conversations):
        kind, reader, label = "chatgpt", _chatgpt_messages, "ChatGPT"
    elif all("chat_messages" in item for item in conversations):
        kind, reader, label = "claude.ai", _claude_messages, "claude.ai"
    else:
        raise ValueError("Format non reconnu : ni export ChatGPT (mapping) ni export claude.ai (chat_messages).")
    events = []
    for conversation in conversations:
        identifier = str(conversation.get("id") or conversation.get("conversation_id") or conversation.get("uuid") or "")[:120]
        title = str(conversation.get("title") or conversation.get("name") or "Conversation sans titre")[:120]
        for message in reader(conversation):
            text, found = redact_whole(message["text"])  # before any cut
            who = ROLE_LABELS.get(message["role"], message["role"])
            events.append(PreRedacted({
                "title": f"{label} · {title} · {who} · {text.splitlines()[0][:80]}"[:180], "body": text, "agent": f"{who} via {label}",
                "episode": f"{kind}:{identifier or title}", "timestamp": str(message.get("time") or "")[:80], "occurrence": f"{kind}:{identifier}:{message['id']}",
                "sources": [{"label": f"export {label} · {title}", "excerpt": text[:4000], "uri": f"{kind}:{identifier}:{message['id']}" if identifier else ""}],
                "pre_redactions": found}))
            if len(events) > MAX_MESSAGES:
                raise ValueError(f"Plus de {MAX_MESSAGES} messages : scindez l'export.")
    if not events:
        raise ValueError("Aucun message visible dans cet export.")
    return {"format": kind, "conversations": len(conversations), "events": events, "sanitized": sanitized[0]}
