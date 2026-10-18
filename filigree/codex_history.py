"""Codex thread history as proposals (`filigree import-codex-history`).

Codex 0.16x keeps the conversation of every thread in `thread_history_N.sqlite` and deletes old rollout files, so the
transcript readers (native index, rollout collector) no longer see most past threads. This module reads that history
read-only and turns it into the same kind of proposed observations as live capture.

Folder evidence is the working directory Codex recorded for the thread in `state_N.sqlite` (the same basis as the
`cwd` of a rollout's session_meta). It is resolved by the capture's own rules (allowed roots, exclusions, generic
folders, deepest registered project, linked worktree, auto-creation): this module only supplies the folder and never
guesses one. A thread whose folder cannot be proven is skipped and counted with its reason. A thread whose rollout
file still exists belongs to the live capture/observer and is skipped. Everything stays a proposal.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path, PurePath
import re
import sqlite3
import time

from . import extract, resolver, tap_source
from .capture import Capture, _Context, _plain_path
from .collectors.base import Roots
from .collectors.codex_state import CodexStateCollector
from .store import ConflictError, PreRedacted, redact_whole

COLLECTOR = "codex-history"
SOURCE = "historique Codex"
CHUNK = 500
MAX_FILES_LISTED = 10
MAX_SKIPPED_LISTED = 200
STORED_TYPES = ("userMessage", "agentMessage", "plan", "commandExecution", "fileChange", "mcpToolCall")
REASONS = {
    "live_source": "le fichier rollout existe encore : la capture en direct s'en charge",
    "no_cwd": "aucun dossier de travail enregistré pour ce fil",
    "no_items": "aucun élément dans thread_history",
    "nothing_to_store": "aucun message ni action mémorisable (raisonnement, contexte, images…)",
    "paused": "projet en pause",
    "outside_roots": "dossier hors des dossiers autorisés",
    "excluded": "dossier exclu de la capture",
    "cwd_missing": "le dossier n'existe plus",
    "cwd_invalid": "dossier de travail invalide (chemin non absolu)",
    "cwd_refused": "dossier trop générique ou refusé pour créer un projet",
    "no_project": "aucun projet pour ce dossier et la création automatique est désactivée",
    "ambiguous_cwd": "dossier ambigu",
    "resolve_error": "dossier impossible à traiter",
}
_STATE = re.compile(r"state_(\d+)\.sqlite")
_HISTORY = re.compile(r"thread_history_(\d+)\.sqlite")


class _Resolver(Capture):
    """The capture's folder rules, fed with the thread's recorded cwd instead of a transcript index."""

    def _lookup(self, ctx, native):
        return [{"source": "codex", "file": "state.sqlite", "cwds": [native], "over": False}]


class _DryStore:
    """Read-through view of the store whose project creation is only simulated: a dry run writes nothing."""

    def __init__(self, store):
        self._store = store
        self.simulated = {}

    def __getattr__(self, name):
        return getattr(self._store, name)

    def create_project(self, name, description="", folder=None, demo=False):
        target = self._store.canonical_folder(folder)
        project = {"id": "(nouveau) " + target["path"], "name": name, "folder": target, "demo": False}
        self.simulated[project["id"]] = project
        return project

    def locate_project(self, path):
        found = self._store.locate_project(path)
        for project in self.simulated.values():
            if resolver.under_roots(path, [project["folder"]["path"]]) and (found is None or len(project["folder"]["path"]) > len((found.get("folder") or {}).get("path", ""))):
                found = project
        return found


def _newest(home: Path, pattern) -> Path | None:
    best, best_number = None, -1
    if home.is_dir():
        for path in home.iterdir():
            match = pattern.fullmatch(path.name)
            if match and path.is_file() and int(match.group(1)) > best_number:
                best, best_number = path, int(match.group(1))
    return best


def _epoch(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value / 1000 if value > 1e11 else float(value)


def parse_since(text) -> float | None:
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("--since attend une date ISO, par exemple 2026-05-01.") from None
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()


def _iso(ms) -> str:
    seconds = _epoch(ms)
    try:
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds") if seconds is not None else ""
    except (OverflowError, OSError, ValueError):
        return ""


def _threads(path: Path, thread, since) -> list[dict]:
    connection = CodexStateCollector._open(path)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(threads)")}
        if not {"id", "cwd", "rollout_path"} <= columns:
            raise ValueError(f"{path.name} n'a pas la forme attendue (colonnes id, cwd, rollout_path).")
        wanted = [name for name in ("id", "cwd", "rollout_path", "updated_at_ms", "updated_at", "created_at", "git_branch") if name in columns]
        rows = [dict(zip(wanted, row)) for row in connection.execute(f"SELECT {','.join(wanted)} FROM threads")]
    finally:
        connection.close()
    out = []
    for row in rows:
        if not isinstance(row.get("id"), str) or not row["id"] or (thread and row["id"] != thread):
            continue
        row["when"] = _epoch(row.get("updated_at_ms")) or _epoch(row.get("updated_at")) or _epoch(row.get("created_at")) or 0.0
        if since is not None and row["when"] < since:
            continue
        out.append(row)
    return sorted(out, key=lambda row: (row["when"], row["id"]))


def _rollout_exists(home: Path, value, sessions: Path) -> bool:
    """True only for a rollout the live capture still reads: an existing file below the Codex sessions root. A rollout
    that Codex moved elsewhere (archived_sessions) is not scanned by the native index, so its thread is history."""
    if not isinstance(value, str) or not value.strip():
        return False
    path = Path(_plain_path(value.strip()))
    try:
        path = path if path.is_absolute() else home / path
        return path.is_file() and resolver.under_roots(path, [sessions])
    except (OSError, ValueError):
        return False


def _first_line(text: str, limit: int = 140) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")[:limit]


def _names(changes) -> str:
    shown = []
    for change in changes[:MAX_FILES_LISTED]:
        if isinstance(change, dict) and isinstance(change.get("path"), str):
            kind = change["kind"].get("type") if isinstance(change.get("kind"), dict) else None
            shown.append(f"{PurePath(change['path'].replace(chr(92), '/')).name[:80]}" + (f" ({kind})" if isinstance(kind, str) else ""))
    more = len(changes) - MAX_FILES_LISTED
    return ", ".join(shown) + (f" … (+{more})" if more > 0 else "")


def _message_text(content) -> str:
    parts = [block.get("text") for block in content if isinstance(block, dict) and block.get("type") in {None, "text", "input_text", "output_text"} and isinstance(block.get("text"), str)] if isinstance(content, list) else []
    return "\n".join(tap_source.visible_text(tap_source.repair_text(part)) for part in parts if part).strip()


def _item_draft(item_type: str, item: dict, extractor: extract.Extractor):
    """(kind, tag, title seed, body) of one history item, or None. Text is not redacted yet; actions are already reduced."""
    identifier = item.get("id") if isinstance(item.get("id"), str) else ""
    if item_type == "userMessage":
        text = _message_text(item.get("content"))
        return ("user_text", "humain", text, text) if text else None
    if item_type in {"agentMessage", "plan"}:
        if tap_source.is_private(item):
            return None
        text = tap_source.visible_text(tap_source.repair_text(item.get("text")))
        return ("assistant_text", "reponse" if item_type == "agentMessage" else "plan", text, text) if text else None
    if item_type == "commandExecution":
        command = item.get("command")
        call = extractor._call("exec_command", {"command": command if isinstance(command, str) else ""}, identifier)
        code = item.get("exitCode") if isinstance(item.get("exitCode"), int) and not isinstance(item.get("exitCode"), bool) else None
        failed = item.get("status") == "failed" or (code is not None and code != 0)
        output = item.get("aggregatedOutput") if isinstance(item.get("aggregatedOutput"), str) else ""
        result = extractor._result(identifier, tap_source.strip_injected(output), failed)  # None for a commit: the call says it
        lines = [f"Commande : {call['summary']}", f"Statut : {'échec' if failed else 'réussi'}" + (f" (code {code})" if code is not None else "")]
        if isinstance(item.get("durationMs"), int) and not isinstance(item.get("durationMs"), bool):
            lines.append(f"Durée : {item['durationMs'] / 1000:.1f} s")
        if result and result["summary"]:
            lines.append("Résultat : " + result["summary"])
        return ("tool_result", "resultat-outil", f"Commande · {call['summary']}" + (" · échec" if failed else ""), "\n".join(lines))
    if item_type == "fileChange":
        changes = item.get("changes") if isinstance(item.get("changes"), list) else []
        failed = item.get("status") == "failed"
        names = _names(changes)
        return ("tool_call", "appel-outil", f"Modification de fichiers · {names}"[:200], f"Modification de fichiers ({len(changes)}) : {names}\nStatut : {'échec' if failed else 'réussi'}")
    if item_type == "mcpToolCall":
        name = ".".join(str(item.get(key))[:80] for key in ("server", "tool") if isinstance(item.get(key), str) and item.get(key)) or "outil"
        failed = item.get("status") == "failed" or isinstance(item.get("error"), dict)
        lines = [f"Outil : {name}", f"Statut : {'échec' if failed else 'réussi'}"]
        error = item.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            lines.append("Erreur : " + extract.summarize(error["message"]))
        return ("tool_call", "appel-outil", f"Appel d'outil {name}" + (" · échec" if failed else ""), "\n".join(lines))
    return None


def build_drafts(rows) -> tuple[list[dict], dict, int]:
    """(drafts, ignored counts by item type, malformed count) for the rows of one thread in rollout order."""
    drafts, ignored, malformed = [], {}, 0
    extractor = extract.Extractor()
    for row in rows:
        thread_id, turn_id, item_id, ordinal, created_ms, raw, item_type = row
        try:
            item = json.loads(raw)
        except (TypeError, ValueError, RecursionError):
            malformed += 1
            continue
        if not isinstance(item, dict) or item_type not in STORED_TYPES:
            ignored[str(item_type)[:40]] = ignored.get(str(item_type)[:40], 0) + 1
            continue
        draft = _item_draft(item_type, item, extractor)
        if draft is None:
            ignored[item_type + " (vide ou privé)"] = ignored.get(item_type + " (vide ou privé)", 0) + 1
            continue
        kind, tag, seed, body = draft
        drafts.append({"kind": kind, "tag": tag, "seed": seed, "body": body, "thread": thread_id, "turn": turn_id, "item": item_id, "ordinal": ordinal, "created": created_ms, "type": item_type})
    return drafts, ignored, malformed


def event_for(draft: dict, evidence: dict, thread: dict, state_name: str, history_name: str) -> PreRedacted:
    """One proposed observation. The text is redacted whole before the title, body and excerpt are cut."""
    kind = draft["kind"]
    text, found = redact_whole(draft["body"])
    if kind in {"user_text", "assistant_text"}:
        text = tap_source.clip(text, tap_source.TEXT_LIMIT)
    seed, more = redact_whole(draft["seed"])
    line = _first_line(seed)
    if kind == "user_text":
        title, who = f"Utilisateur · {line}", "Humain via Codex"
    elif kind == "assistant_text":
        title, who = f"Codex · {'plan' if draft['tag'] == 'plan' else 'réponse'} · {line}", "Codex"
    else:
        title, who = f"{line}", "Codex"
    thread_id, uri = draft["thread"], f"codex-thread:{draft['thread']}:{draft['item']}"
    provenance = {"collector": COLLECTOR, "native_source": "codex", "thread_id": thread_id, "turn_id": draft["turn"], "item_id": draft["item"], "rollout_ordinal": draft["ordinal"],
                  "item_type": draft["type"], "history_db": history_name, "state_db": state_name, "cwd": evidence.get("cwd"), "link": "native",
                  **({"worktree_of": evidence["worktree_of"]} if evidence.get("worktree_of") else {}), **({"git_branch": thread["git_branch"]} if isinstance(thread.get("git_branch"), str) and thread["git_branch"] else {}),
                  "claim": "historique Codex local, non authentifié ; dossier lu dans le fil enregistré par Codex"}
    return PreRedacted({"title": title[:180], "body": text or title, "agent": who, "episode": thread_id[:240], "timestamp": _iso(draft["created"])[:80], "occurrence": f"{thread_id}:{draft['item']}",
                        "sources": [{"label": f"{SOURCE} · {thread_id[:8]} #{draft['ordinal']}", "uri": uri, "excerpt": text[:4000]}],
                        "tags": ["historique", COLLECTOR, "codex", draft["tag"], "lien-natif"], "provenance": provenance, "pre_redactions": found + more})


KEY_PREFIX = 500


def _digest(text: str) -> str:
    """Prefix-tolerant: a copy cut at the clip limit (or not cut) of the same redacted text gives the same key."""
    return hashlib.sha256(text[:KEY_PREFIX].encode("utf-8")).hexdigest()


def _draft_key(draft: dict) -> str:
    return _digest(redact_whole(draft["body"])[0])  # the unclipped redacted text


def _known_texts(store, project_id: str) -> set:
    """(episode, digest) of the messages already proposed for a project: a thread captured live before its rollout was
    deleted must not be proposed a second time under another source uri."""
    return {(entry["episode"], _digest(entry["body"])) for entry in store.list_entries(project_id, kind="observation")
            if entry.get("episode") and not any(str(source.get("uri", "")).startswith("codex-thread:") for source in entry.get("sources", []))}  # a rerun of this import is deduplicated by the store


def _retry(call, *arguments, **options):
    """The store lock may be held by a running agent: wait a few times (0.5 s, 1 s, 2 s, 4 s) before giving up."""
    for delay in (0.5, 1.0, 2.0, 4.0, None):
        try:
            return call(*arguments, **options)
        except ConflictError:
            if delay is None:
                raise
            time.sleep(delay)


def _import(store, project_id: str, events: list, stats: dict):
    """Chunked import honouring the per-call caps: `remaining` is followed until nothing is left, never dropped."""
    for start in range(0, len(events), CHUNK):
        pending = events[start:start + CHUNK]
        while pending:
            try:
                step = _retry(store.import_events, project_id, pending, SOURCE, internal=True)
            except ConflictError:
                raise
            except (ValueError, KeyError):
                step = {"imported": 0, "duplicates": 0, "redactions": 0, "truncated": 0, "remaining": 0}
                for event in pending:  # one refused event costs that event (counted), never the rest
                    try:
                        single = _retry(store.import_events, project_id, [event], SOURCE, internal=True)
                    except ConflictError:
                        raise
                    except (ValueError, KeyError) as exc:
                        stats["rejected"] += 1
                        stats["rejected_reason"] = stats.get("rejected_reason") or str(exc)[:120]
                        continue
                    for key in ("imported", "duplicates", "redactions", "truncated"):
                        step[key] += single.get(key, 0)
            for key in ("imported", "duplicates", "redactions", "truncated"):
                stats[key] += step.get(key, 0)
            remaining = step.get("remaining", 0)
            if not remaining:
                break
            if not step.get("imported") and not step.get("duplicates"):
                stats["unprocessed"] += remaining  # no progress: reported, not looped on
                break
            pending = pending[len(pending) - remaining:]


def import_history(store, env=None, codex_home=None, dry_run: bool = False, thread: str | None = None, since=None) -> dict:
    """Import the history of Codex threads whose rollout is gone. JSON-ready report; `dry_run` writes nothing."""
    since_epoch = since if isinstance(since, (int, float)) else parse_since(since)
    view = _DryStore(store) if dry_run else store
    capture = _Resolver(view, env=env)
    settings, error = capture.settings()
    if error:
        raise ValueError(error)
    if not settings["enabled"]:
        raise ValueError("La capture est désactivée (filigree capture enable pour la réactiver) : rien n'est importé.")
    if settings["paused_all"]:
        raise ValueError("La capture est en pause globale (filigree capture resume) : rien n'est importé.")
    home = Path(codex_home).expanduser() if codex_home else Roots(env).codex_home
    state_db, history_db = _newest(home, _STATE), _newest(home, _HISTORY)
    if state_db is None or history_db is None:
        raise ValueError(f"Aucun historique Codex trouvé dans {home} (state_N.sqlite et thread_history_N.sqlite attendus).")
    threads = _threads(state_db, thread, since_epoch)
    before = {project["id"] for project in capture._project_summaries()}
    ctx = _Context(settings, {}, capture._project_summaries())
    skipped, skipped_list, ignored = {}, [], {}
    totals = {"imported": 0, "duplicates": 0, "redactions": 0, "truncated": 0, "rejected": 0, "unprocessed": 0}
    counts = {"threads_read": len(threads), "threads_imported": 0, "items_read": 0, "events": 0, "already_captured": 0, "malformed_items": 0}
    projects, known = {}, {}
    sessions = Path(settings["roots"]["codex"]).expanduser() if settings["roots"].get("codex") else home / "sessions"
    interrupted = None

    def skip(thread_id, reason):
        skipped[reason] = skipped.get(reason, 0) + 1
        if len(skipped_list) < MAX_SKIPPED_LISTED:
            skipped_list.append({"thread": thread_id, "reason": reason})

    connection = CodexStateCollector._open(history_db)
    try:
        try:
            for row in threads:
                thread_id = row["id"]
                if _rollout_exists(home, row.get("rollout_path"), sessions):
                    skip(thread_id, "live_source")
                    continue
                cwd = row.get("cwd")
                if not isinstance(cwd, str) or not cwd.strip() or "\x00" in cwd:
                    skip(thread_id, "no_cwd")
                    continue
                items = connection.execute("SELECT thread_id, turn_id, item_id, rollout_ordinal, created_at_ms, item_json, item_type FROM thread_items WHERE thread_id = ? ORDER BY rollout_ordinal, item_id", (thread_id,)).fetchall()
                if not items:
                    skip(thread_id, "no_items")
                    continue
                drafts, thread_ignored, malformed = build_drafts(items)
                if not drafts:
                    skip(thread_id, "nothing_to_store")
                    continue
                resolution = capture._resolve_native(ctx, cwd.strip())  # nothing is created before there is something to store
                if resolution["status"] != "ok":
                    skip(thread_id, resolution["status"] if resolution["status"] in REASONS else "resolve_error")
                    continue
                project_id = resolution["project_id"]
                project = ctx.projects.get(project_id) or {}
                if project.get("demo") or (project.get("folder") and capture._is_excluded(ctx, Path(project["folder"]["path"]))):
                    skip(thread_id, "excluded")
                    continue
                if project_id in ctx.paused:
                    skip(thread_id, "paused")
                    continue
                counts["items_read"] += len(items)
                counts["malformed_items"] += malformed
                for name, number in thread_ignored.items():
                    ignored[name] = ignored.get(name, 0) + number
                if project_id not in known:
                    known[project_id] = set() if dry_run and project_id not in before else _known_texts(store, project_id)
                events, already = [], 0
                for draft in drafts:
                    event = event_for(draft, resolution, row, state_db.name, history_db.name)
                    if draft["kind"] in {"user_text", "assistant_text"} and (thread_id, _draft_key(draft)) in known[project_id]:
                        already += 1
                        continue
                    events.append(event)
                entry = projects.setdefault(project_id, {"project_id": project_id if project_id in before else None, "name": project.get("name"), "folder": (project.get("folder") or {}).get("path"), "created": project_id not in before,
                                                         "threads": 0, "items": 0, "events": 0, "imported": 0, "duplicates": 0, "already_captured": 0, "rejected": 0, "unprocessed": 0})
                entry["threads"] += 1
                entry["items"] += len(items)
                entry["events"] += len(events)
                entry["already_captured"] += already
                counts["threads_imported"] += 1
                counts["events"] += len(events)
                counts["already_captured"] += already
                if not dry_run:
                    stats = {"imported": 0, "duplicates": 0, "redactions": 0, "truncated": 0, "rejected": 0, "unprocessed": 0}
                    try:
                        _import(store, project_id, events, stats)
                    finally:  # progress made before a busy store is still reported
                        for key in totals:
                            totals[key] += stats[key]
                        for key in ("imported", "duplicates", "rejected", "unprocessed"):
                            entry[key] += stats[key]
                        if stats.get("rejected_reason"):
                            entry["rejected_reason"] = stats["rejected_reason"]
        except ConflictError:
            interrupted = "La mémoire est restée occupée (agent en cours ?) : import interrompu proprement. Relancez la commande, elle reprend sans doublon."
    finally:
        connection.close()
    resume = (f"{counts['threads_imported']} fil(s) {'à importer' if dry_run else 'traité(s)'} dans {len(projects)} projet(s), {counts['events']} observation(s) proposée(s)"
              + (f", {sum(skipped.values())} fil(s) ignoré(s)" if skipped else "") + (" (simulation : rien n'a été écrit)." if dry_run else ".") + (" " + interrupted if interrupted else ""))
    return {"dry_run": dry_run, "resume": resume, "codex_home": str(home), "state_db": state_db.name, "history_db": history_db.name, **counts,
            "events_imported": totals["imported"], "duplicates": totals["duplicates"], "redactions": totals["redactions"], "truncated": totals["truncated"], "rejected": totals["rejected"], "unprocessed": totals["unprocessed"],
            "projects": sorted(projects.values(), key=lambda item: item["folder"] or ""), "skipped": skipped, "skipped_threads": skipped_list,
            "explications": {code: REASONS[code] for code in skipped}, "ignored_items": ignored, **({"interrupted": interrupted} if interrupted else {})}
