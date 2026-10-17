"""Session sheets: one reviewable proposal per agent session, distilled from its activity journal (ADR-0003).

No model is called (D3): the sheet is a deterministic digest of journal events. It stays a proposal; while it is
`proposed` it is revised in place, and once a person has accepted or rejected it, new activity produces a separate
"suite" proposal so a review decision is never rewritten.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import PurePath

from .activity import ActivityLog, journal_path

SHEET_URI = "filigree:session-sheet:"
MAX_SHEET_EVENTS = 2000
CLIENT_LABELS = {"claude": "Claude Code", "codex": "Codex"}


def _parse(text):
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def sheet_body(session: dict, events: list[dict]) -> str:
    """Markdown digest of one session. `events` are newest first, as the journal returns them."""
    ordered = list(reversed(events))
    kinds = Counter(event["kind"] for event in ordered)
    files = Counter(name for event in ordered if event["kind"] == "file_change" for name in event["files"])
    outside = sorted({name for event in ordered if event["outside_project"] for name in event["files"]})
    commands = Counter(event["summary"] for event in ordered if event["kind"] == "command")
    tests = [event for event in ordered if event["kind"] == "test_result"]
    errors = [event for event in ordered if event["kind"] == "error"]
    prompts = [event for event in ordered if event["kind"] == "user_prompt"]
    lines = [
        f"Fiche générée sans modèle à partir du journal d'activité local (données non revues). Client : {CLIENT_LABELS.get(session['client'], session['client'])}"
        + (f" · modèle {session['model']}" if session.get("model") else "") + (f" · {session['entrypoint']}" if session.get("entrypoint") else "") + ".",
        f"Période : {session.get('first_ts') or '?'} → {session.get('last_ts') or '?'} · {len(ordered)} événement(s)" + (" · session terminée." if session.get("ended") else "."),
        "", "## Demandes", *([f"- {event['summary']}" for event in prompts[:5]] or ["- (aucune demande visible)"]),
    ]
    if len(prompts) > 5:
        lines.append(f"- … et {len(prompts) - 5} autre(s)")
    lines += ["", "## Fichiers modifiés", *([f"- `{name}` ({count}×)" for name, count in files.most_common(20)] or ["- (aucun)"])]
    if len(files) > 20:
        lines.append(f"- … et {len(files) - 20} autre(s)")
    if outside:
        lines += ["", f"⚠ {len(outside)} fichier(s) modifié(s) hors du dossier du projet : " + ", ".join(f"`{PurePath(name).name}`" for name in outside[:10])]
    lines += ["", "## Commandes", *([f"- {name} ({count}×)" for name, count in commands.most_common(10)] or ["- (aucune)"])]
    if kinds["commit"]:
        lines.append(f"- git commit ({kinds['commit']}×)")
    lines += ["", "## Tests", *([f"- {event['summary']}" for event in tests[-5:]] or ["- (aucun test observé)"])]
    lines += ["", "## Erreurs", *([f"- {event['summary']}" for event in errors[-5:]] or ["- (aucune)"])]
    if len(errors) > 5:
        lines.append(f"- … {len(errors)} erreur(s) au total")
    lines += ["", "Les résumés sont expurgés puis tronqués ; les lignes de commande ne sont jamais conservées, seul le programme l'est. Une commande réussie ne prouve pas que le besoin est satisfait."]
    return "\n".join(lines)


def _title(session: dict, events: list[dict], suite: int) -> str:
    prompt = next((event["summary"] for event in reversed(events) if event["kind"] == "user_prompt"), "")
    label = CLIENT_LABELS.get(session["client"], session["client"])
    day = (session.get("first_ts") or "")[:10]
    return (f"Session {label} {day}" + (f" (suite {suite})" if suite else "") + (f" · {prompt}" if prompt else ""))[:180]


def _entry_by_uri(entries: list[dict], uri: str) -> dict | None:
    return next((entry for entry in entries if any(source.get("uri") == uri for source in entry.get("sources", []))), None)


def distill_project(store, project_id: str, sheets: dict, idle_minutes: int = 10, now: datetime | None = None) -> int:
    """Create or revise the sheets of idle or ended sessions whose journal grew. `sheets` is persisted by the caller:
    {session_key: {"count": distilled event count, "suite": n}}. Returns the number of sheets written."""
    log = ActivityLog(journal_path(store, project_id))
    now = now or datetime.now(timezone.utc)
    written = 0
    entries = None
    for session in log.sessions():
        mark = sheets.get(session["session_key"], {"count": 0, "suite": 0})
        if session["event_count"] <= mark["count"]:
            continue
        last = _parse(session.get("last_ts"))
        if not session["ended"] and last is not None and now - last < timedelta(minutes=idle_minutes):
            continue  # still active: wait for 10 idle minutes or an explicit session end
        if entries is None:
            entries = store.list_entries(project_id)
        events = log.events(limit=MAX_SHEET_EVENTS, session_key=session["session_key"])
        suite = mark["suite"]
        uri = SHEET_URI + session["session_key"] + (f"#suite-{suite}" if suite else "")
        existing = _entry_by_uri(entries, uri)
        if existing is not None and existing["status"] in {"accepted", "rejected", "superseded"}:
            # A reviewed sheet is never rewritten: new activity becomes the next free suite, even if the saved state was lost.
            while existing is not None and existing["status"] in {"accepted", "rejected", "superseded"}:
                suite += 1
                uri = SHEET_URI + session["session_key"] + f"#suite-{suite}"
                existing = _entry_by_uri(entries, uri)
            events = [event for event in events if (event.get("ts_source") or event["ts_observed"]) > (mark.get("last_ts") or "")] or events
        body = sheet_body(session, events)
        source = {"label": f"journal d'activité · {session['session_key'][-12:]}", "uri": uri, "excerpt": body[:4000]}
        if existing is None:
            created = store.create_entry(project_id, {
                "title": _title(session, events, suite), "body": body, "kind": "observation", "status": "proposed",
                "episode": session["session_key"], "agent": "Filigree (fiche de session)", "tags": ["capture", "fiche-session", session["client"]],
                "sources": [source]}, channel="capture")
            entries.append(created)
        else:
            updated = store.update_entry(project_id, existing["id"], {"title": _title(session, events, suite), "body": body, "sources": [source], "revision": existing["revision"],
                                                                     "reason": "Fiche de session mise à jour : nouvelle activité observée."}, channel="capture")
            entries = [updated if entry["id"] == updated["id"] else entry for entry in entries]
        sheets[session["session_key"]] = {"count": session["event_count"], "suite": suite, "last_ts": session.get("last_ts")}
        written += 1
    return written
