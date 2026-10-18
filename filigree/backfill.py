"""`filigree backfill`: explicit, user-requested catch-up of the history that capture and the observer skip by design.

ADR-0003 D11: neither the capture nor the activity observer ever imports what existed before they started. This module
is the only exception, and only when the user runs it. It does not import anything itself: under the process locks it
rewinds the cursors, and the next agent or capture cycles replay the history through the very same code paths as live
activity. A record is therefore attached only when its native session id resolves to a transcript folder, otherwise it
goes pending; nothing is guessed from recency, names or timing. Replays are idempotent for the same record (store
fingerprints, stable activity event ids). Between the two capture channels, claude-tap is replayed first and an item
already held from the other channel is not imported again (ledgers, then the memory itself as witness); the only
residual risk is text the memory truncated or normalised differently in the two channels.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import time
from pathlib import Path

from . import native_index, tap_source
from .activity import MAX_FILES_PER_CYCLE, TRANSCRIPT_COLLECTORS, _read_json as _read_activity, _write_json as _write_activity
from .capture import Capture, ProcessLock, _read_json
from .collectors import all_collectors, discover_all
from .store import Store

EPOCH = "1970-01-01T00:00:00+00:00"
WARNING = "Tout l'historique encore présent est relu. Une pause passée n'a laissé aucune trace durable (la reprise avance simplement les curseurs) : son contenu est donc relu, sauf les intervalles de pause que la capture conserve encore. Les dossiers exclus, les projets en pause et les dossiers hors racines autorisées restent ignorés comme en direct."


class BackfillError(ValueError):
    """The rewind was refused; nothing was changed."""


def _agent_lock(store) -> Path:
    return store.root / ".runtime" / "agent.lock"


def _held(path: Path) -> bool:
    """True when another handle holds this lock. Never creates the file: a dry run changes nothing."""
    if not path.exists():
        return False
    probe = ProcessLock(path)
    if probe.acquire():
        probe.release()
        return False
    return True


def _peek_state(capture) -> dict:
    """The capture state without the repair side effects of _load_state (a damaged file is only reported)."""
    try:
        _read_json(capture._file("state.json"))
    except ValueError:
        return capture._fresh_state()
    return capture._load_state()


AGENT_MESSAGE = "Un agent Filigree tourne pour ce dossier de données : arrêtez-le d'abord (fermez-le, ou « filigree service uninstall » s'il démarre à l'ouverture de session), puis relancez « filigree backfill »."
CAPTURE_MESSAGE = "La capture tourne dans un autre processus (« filigree serve » ou « filigree capture run ») : arrêtez-la (« filigree capture stop ») puis relancez « filigree backfill »."


def _blockers(capture, store, settings, error, state, locks: bool = True) -> list:
    problems = []
    if locks and _held(_agent_lock(store)):
        problems.append(AGENT_MESSAGE)
    if locks and _held(capture._file("capture.lock")):
        problems.append(CAPTURE_MESSAGE)
    if error or not settings["enabled"] or settings["paused_all"]:
        problems.append("La capture est désactivée ou en pause : réactivez-la (« filigree capture enable » / « filigree capture resume ») avant de demander l'historique, sinon la reprise ignorerait le rattrapage.")
    elif state["hold"] or state["fallback_hold"] or capture._file("hold").exists() or capture._file("hold-fallback").exists():
        problems.append("Une reprise après pause est en cours de traitement : laissez la capture faire un cycle (« filigree capture run --once »), puis relancez « filigree backfill ».")
    return problems


def _tap_counts(capture, settings) -> dict:
    if not settings["tap"]["enabled"]:
        return {"status": "disabled", "sessions": 0, "records": 0}
    path = tap_source.resolve_db_path(settings, capture.env)
    connection, capability = tap_source.open_db(path)
    if connection is None:
        return {"status": capability, "sessions": 0, "records": 0}
    try:
        sessions = tap_source.list_sessions(connection)
    except Exception:  # noqa: BLE001 — an unreadable database is reported, never fatal
        return {"status": "corrupt", "sessions": 0, "records": 0}
    finally:
        tap_source.take_invalid_text()
        connection.close()
    return {"status": "ok", "sessions": len(sessions), "records": sum(info["max_index"] for info in sessions.values()), "_max": {sid: info["max_index"] for sid, info in sessions.items()}}


def _native_counts(capture, settings) -> dict:
    if not (settings["sources"]["native_fallback"] and settings["sources"]["native_index"]):
        return {"status": "disabled", "transcripts": 0, "bytes": 0, "_sizes": {}}
    sizes = {path: size for root in native_index.default_roots(settings, capture.env).values() if root.is_dir() for path, size, _mtime in native_index.iter_files(root)}
    return {"status": "ok", "transcripts": len(sizes), "bytes": sum(sizes.values()), "_sizes": sizes}


def _activity_counts(settings, env, home, collectors) -> dict:
    if not settings["activity"]["enabled"]:
        return {"status": "disabled", "transcripts": 0, "bytes": 0}
    found = discover_all(collectors=collectors if collectors is not None else all_collectors(env, home), limit=MAX_FILES_PER_CYCLE)
    paths = {info.transcript for name, outcome in found.items() if outcome["status"] == "ok" and name in TRANSCRIPT_COLLECTORS for info in outcome["sessions"] if info.transcript and info.cwd}
    total = 0
    for path in paths:
        try:
            total += Path(path).stat().st_size
        except OSError:
            pass
    return {"status": "ok", "transcripts": len(paths), "bytes": total}


def _public(section: dict) -> dict:
    return {key: value for key, value in section.items() if not key.startswith("_")}


def plan(data_dir, env=None, home=None, collectors=None) -> dict:
    """Dry run: what a backfill would replay. Reads only; writes and creates nothing."""
    store = Store(Path(data_dir).expanduser().resolve())
    capture = Capture(store, env)
    settings, error = capture.settings()
    state = _peek_state(capture)
    tap = _tap_counts(capture, settings)
    blockers = _blockers(capture, store, settings, error, state)
    if tap["status"] not in {"ok", "missing", "disabled"}:
        blockers.append(f"La base claude-tap n'est pas lisible ({tap['status']}).")
    return {"dry_run": True, "blockers": blockers, "tap": _public(tap),
            "native_fallback": _public(_native_counts(capture, settings)), "activity": _activity_counts(settings, capture.env, home, collectors), "warning": WARNING}


def rewind(data_dir, env=None, home=None, collectors=None) -> dict:
    """Rewind the capture and activity cursors so the next cycles replay the existing history. Refuses (BackfillError,
    nothing changed) while an agent or a capture process runs, or while capture is disabled or paused."""
    store = Store(Path(data_dir).expanduser().resolve())
    capture = Capture(store, env)
    agent_lock = ProcessLock(_agent_lock(store))
    if not agent_lock.acquire():
        raise BackfillError(AGENT_MESSAGE)
    try:
        if not capture.lock.acquire():
            raise BackfillError(CAPTURE_MESSAGE)
        try:
            return _rewind_locked(store, capture, home, collectors)
        finally:
            capture.lock.release()
    finally:
        agent_lock.release()


def _rewind_locked(store, capture, home, collectors) -> dict:
    with capture.mutex, store._lock:
        settings, error = capture.settings()
        try:
            _read_json(capture._file("state.json"))
        except ValueError:  # the repair _load_state would have made: keep the unreadable file before it is replaced
            with contextlib.suppress(OSError):
                shutil.copyfile(capture._file("state.json"), capture._file(f"state.corrupt-{int(time.time())}.json"))
        state, pending = _peek_state(capture), capture._load_pending()
        problems = _blockers(capture, store, settings, error, state, locks=False)
        if problems:
            raise BackfillError(problems[0])
        replay = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "at_epoch": time.time(), "tap": {}, "files": {}}
        tap_info = _tap_counts(capture, settings)
        if tap_info["status"] not in {"ok", "missing", "disabled"}:
            raise BackfillError(f"La base claude-tap n'est pas lisible ({tap_info['status']}) : l'historique claude-tap ne pourrait pas être relu. Fermez les programmes qui l'utilisent ou corrigez la base, puis relancez « filigree backfill ».")
        if tap_info["status"] == "ok":
            key = tap_source.db_key(tap_source.resolve_db_path(settings, capture.env))
            tap = state["tap"]
            if tap.get("db_key") != key:
                capture._quarantine_pending(state, pending, tap.get("db_key"))
                tap.update(db_key=key, baseline={}, recent={}, updated={}, deleted=[])
            tap.update(cursors={sid: 0 for sid in tap_info["_max"]}, baseline={}, recent={}, updated={})
            replay["tap"], replay["db_key"] = {sid: top for sid, top in tap_info["_max"].items() if top}, key
        native = _native_counts(capture, settings)
        fallback = state["fallback"]
        if native["status"] == "ok":
            # Pause gaps (fallback['gaps']) are kept and still honoured. Unseen files are read whole; moving the old-transcript guard to the epoch keeps them from being skipped as history.
            replay["baselined_at"] = fallback.get("baselined_at") if fallback["baselined"] else time.time()
            # The live ledgers are emptied: items stored before the replay are matched against the memory itself
            # (capture._without_twins), so a copy is never consumed twice, once by a ledger and once by the memory.
            fallback.update(baselined=True, baselined_at=0.0, files={}, waits={}, stalled={}, tap_seen={}, native_seen={})
            replay["files"] = {path: size for path, size in native["_sizes"].items() if size}
        activity = _activity_counts(settings, capture.env, home, collectors)
        if replay["tap"] or replay["files"]:
            state["backfill"] = replay
        capture._notice(state, "backfill_demandé", f"backfill demandé : {len(replay['tap'])} session(s) tap et {len(replay['files'])} transcription(s) natives relues depuis le début.")
        capture._save(state, pending)
        if settings["activity"]["enabled"]:
            path = store.root / ".capture" / "activity-state.json"
            observed = _read_activity(path, {})
            observed["version"] = 1
            observed["baseline_at"] = EPOCH
            observed["files"] = {name: {"offset": 0} for name in observed.get("files", {})}
            _write_activity(path, observed)
        return {"dry_run": False, "tap": _public(tap_info), "native_fallback": _public(native), "activity": activity, "warning": WARNING,
                "next": "Relancez l'agent (« filigree agent » ou « filigree service install ») : l'historique est relu par cycles successifs, avec les mêmes règles que le direct."}
