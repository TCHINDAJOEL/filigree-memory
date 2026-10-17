"""Automatic capture of agent sessions, bound to real local project folders.

Collector: claude-tap's SQLite store, read-only (tap_source). Folder evidence: exact equality
between a native session identifier claimed by a tap record and a native transcript that names
its working directory (native_index). Nothing is guessed from recency, names or free text.
Identifiers are claims, not authentication. Unresolved or ambiguous records stay pending
(keys only, never content) until the user maps them explicitly.

State lives in <data-dir>/.capture, outside every project and every Git-versioned memory.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone

from . import native_index, resolver, tap_source
from .store import ConflictError, PreRedacted, redact_whole

CAPTURE_DIR = ".capture"
MAX_RECORDS_PER_CYCLE = 1000
MAX_PENDING_INDEXES = 5000
MAX_PENDING_SESSIONS = 50
MAX_NOTICES = 30
MAX_TAP_SEEN = 5000
MAX_LEDGER_ITEMS = 400
DEDUP_WINDOW = 900
MAX_QUARANTINES = 5
FALLBACK_GRACE = 20.0
FALLBACK_MAX_WAIT = 60.0
MAX_GAPS = 20  # skipped pause intervals remembered per held transcript
REFRESH_INTERVAL = 3.0
_KEY = re.compile(r"(?:tap:)?[A-Za-z0-9_.:-]{1,128}")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]")
MAX_STALLED = 100
BASELINE_TOLERANCE = 2.0  # seconds: coarse file timestamps must not turn a new transcript into history
_SCOPED_KEY =re.compile(r"(tap:[A-Za-z0-9_.:-]{1,128})@([0-9a-f]{16})")
_SLOTS = {"user_text": "user", "assistant_text": "assistant", "tool_call": "call", "tool_result": "result", "http_error": "error"}


class CaptureError(ValueError):
    pass


class UnknownProject(CaptureError, KeyError):
    """Still a KeyError for callers that map it to "not found"; the message is readable rather than a quoted repr."""

    def __str__(self):
        return str(self.args[0]) if self.args else ""


class _Transient(Exception):
    """The memory store was busy; nothing is advanced and the cycle is retried."""


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_settings() -> dict:
    return {"enabled": True, "auto_create": True, "paused_all": False, "tap": {"enabled": True, "db": None}, "sources": {"native_index": True, "native_fallback": True}, "roots": {"claude": None, "codex": None}, "exclude": [], "paused": [], "allowed_roots": None, "activity": {"enabled": True, "retention_days": 90, "turn_proposals": True}}


def normalize_settings(raw):
    """(settings, error). A malformed value disables capture instead of guessing."""
    settings = default_settings()
    if raw is None:
        return settings, None
    try:
        if not isinstance(raw, dict):
            raise ValueError("objet attendu")
        for key in ("enabled", "auto_create", "paused_all"):
            if key in raw:
                if type(raw[key]) is not bool:
                    raise ValueError(key)
                settings[key] = raw[key]
        sections = {"tap": {"enabled": bool, "db": str}, "sources": {"native_index": bool, "native_fallback": bool}, "roots": {"claude": str, "codex": str}}
        for section, fields in sections.items():
            if section in raw:
                if not isinstance(raw[section], dict):
                    raise ValueError(section)
                for key, value in raw[section].items():
                    expected = fields.get(key)
                    if expected is None or not ((type(value) is bool) if expected is bool else (value is None or (isinstance(value, str) and "\x00" not in value))):
                        raise ValueError(f"{section}.{key}")
                    settings[section][key] = value
        for key in ("exclude", "paused"):
            if key in raw:
                if not isinstance(raw[key], list) or len(raw[key]) > 200 or any(not isinstance(item, str) or not item or "\x00" in item for item in raw[key]):
                    raise ValueError(key)
                settings[key] = list(dict.fromkeys(raw[key]))
        if raw.get("allowed_roots") is not None:
            roots = raw["allowed_roots"]
            # null keeps the v0.1 behaviour; a list confines resolution and project creation to those folders (ADR-0003)
            if not isinstance(roots, list) or len(roots) > 200 or any(not isinstance(item, str) or not item or "\x00" in item or not Path(item).is_absolute() for item in roots):
                raise ValueError("allowed_roots")
            settings["allowed_roots"] = list(dict.fromkeys(roots))
        if "activity" in raw:
            section = raw["activity"]
            if not isinstance(section, dict):
                raise ValueError("activity")
            for key, value in section.items():
                if key in {"enabled", "turn_proposals"} and type(value) is bool:
                    settings["activity"][key] = value
                elif key == "retention_days" and type(value) is int and 1 <= value <= 3650:
                    settings["activity"][key] = value
                else:
                    raise ValueError(f"activity.{key}")
        return settings, None
    except ValueError as exc:
        settings["enabled"] = False
        return settings, f"Réglage invalide ({exc}). La capture est désactivée jusqu'à correction de capture.json."


def _read_json(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ValueError(f"JSON illisible : {path.name}") from exc


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=1, sort_keys=True, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(8):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.05)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ProcessLock:
    """Exclusive OS lock held for the whole capture run; released by the OS if the process dies."""

    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        if self.handle is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        return True

    def release(self):
        handle, self.handle = self.handle, None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()


def _git_root(folder: Path):
    """Nearest ancestor (or self) holding .git, or None."""
    for candidate in [folder, *folder.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _contains_home(folder: Path) -> bool:
    try:
        home = Path.home().resolve()
        return folder.resolve() == home or folder.resolve() in home.parents
    except (OSError, RuntimeError):
        return False


def _plain_path(text: str) -> str:
    """Drop the Windows extended-length prefix so `\\\\?\\C:\\x` and `C:\\x` name one folder."""
    if text.startswith("\\\\?\\UNC\\"):
        return "\\\\" + text[8:]
    if text.startswith(("\\\\?\\", "\\\\.\\")) and len(text) > 5 and text[5] == ":":
        return text[4:]
    return text


def _parts(path) -> tuple:
    return tuple(os.path.normcase(part) for part in Path(_plain_path(str(path))).parts)


def _generic_locations(env) -> tuple:
    """(anchors, exact, tree): places that are shared by every project and so can never be one.
    A folder equal to, or above, an anchor (temp, home) is generic; `exact` only when equal; `tree` it and everything below."""
    anchors, exact, tree = [], [], []
    candidates = [tempfile.gettempdir(), *(env.get(name) for name in ("TMPDIR", "TEMP", "TMP"))]
    for candidate in candidates:
        if candidate:
            anchors.append(candidate)
    with contextlib.suppress(RuntimeError, OSError):
        anchors.append(Path.home())
    for name in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData", "PUBLIC", "ALLUSERSPROFILE"):
        if os.environ.get(name):
            exact.append(os.environ[name])
    exact += ["/tmp", "/var", "/var/tmp", "/home", "/Users", "/usr", "/opt", "/srv", "/mnt", "/media", "/root", "/Library", "/Applications"]
    for name in ("SystemRoot", "windir"):
        if os.environ.get(name):
            tree.append(os.environ[name])
    tree += ["/etc", "/bin", "/sbin", "/lib", "/boot", "/dev", "/proc", "/sys", "/System"]

    def resolved(values):
        found = []
        for value in values:
            try:
                found.append(_parts(Path(value).resolve()))
            except (OSError, RuntimeError, ValueError):
                continue
        return found
    return resolved(anchors), resolved(exact), resolved(tree)


def _is_generic(folder, env) -> bool:
    try:
        mine = _parts(Path(folder).resolve())
    except (OSError, RuntimeError, ValueError):
        return True
    anchors, exact, tree = _generic_locations(env)
    return (any(mine == anchor[:len(mine)] for anchor in anchors)
            or any(mine == item for item in exact)
            or any(mine == item[:len(mine)] and len(mine) <= len(item) or item == mine[:len(item)] for item in tree))


def _safe_interval(value) -> float:
    """A polling interval is finite and bounded: nan would spin, inf would never wake."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 3.0
    if not math.isfinite(number):
        return 3.0
    return min(max(number, 0.5), 3600.0)


def _first_line(text: str, limit: int = 140) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")[:limit]


def _clock() -> int:
    return int(time.time())


# Cross-channel ledgers: a bounded, expiring multiset of content digests per native session. A visible
# item captured through one channel (claude-tap or the native transcript) consumes one matching digest
# when the other channel meets it, so switching channels never duplicates a message, while an identical
# message sent later, or after the window, is new activity.
_DIGEST_KIND = {"user_text": "u", "assistant_text": "a", "tool_call": "c", "tool_result": "r"}


def _item_digest(item):
    kind = _DIGEST_KIND.get(item.get("kind"))
    if kind is None:
        return None
    return hashlib.sha256(f"{kind}\n{item.get('name', '')}\n{item.get('text', '').strip()}".encode("utf-8", "surrogatepass")).hexdigest()[:16]


def _clean_ledger(value) -> dict:
    if not isinstance(value, dict):
        return {}
    clean = {}
    for native, entries in value.items():
        if isinstance(native, str) and isinstance(entries, list):
            kept = [[entry[0], entry[1]] for entry in entries if isinstance(entry, list) and len(entry) == 2 and isinstance(entry[0], str) and type(entry[1]) is int]
            if kept:
                clean[native] = kept[-MAX_LEDGER_ITEMS:]
    return clean


def _ledger_add(ledger: dict, native: str, digest: str, now: int):
    entries = ledger.setdefault(native, [])
    entries.append([digest, now])
    del entries[:-MAX_LEDGER_ITEMS]
    if len(ledger) > MAX_TAP_SEEN:
        for stale in sorted(ledger, key=lambda name: ledger[name][-1][1])[:len(ledger) - MAX_TAP_SEEN]:
            del ledger[stale]


def _ledger_take(ledger: dict, native: str, digest: str, now: int) -> bool:
    entries = ledger.get(native)
    if not entries:
        return False
    entries[:] = [entry for entry in entries if entry[1] >= now - DEDUP_WINDOW]
    for position, entry in enumerate(entries):
        if entry[0] == digest:
            del entries[position]
            if not entries:
                del ledger[native]
            return True
    if not entries:
        del ledger[native]
    return False


class _Context:
    def __init__(self, settings, mappings, projects):
        self.settings = settings
        self.mappings = mappings
        self.projects = {project["id"]: project for project in projects}
        self.resolved = {}
        self.refreshed = set()
        self.events = {}
        self.excluded = [Path(item) for item in settings["exclude"]]
        self.paused = set(settings["paused"])


class Capture:
    def __init__(self, store, env=None):
        self.store = store
        self.env = os.environ if env is None else env
        self.directory = store.root / CAPTURE_DIR
        self.mutex = threading.RLock()
        self.lock = ProcessLock(self.directory / "capture.lock")
        self.thread = None
        self.stop_event = threading.Event()
        self.index = None
        self.last_refresh = -1e9
        self.refresh_interval = REFRESH_INTERVAL
        self.index_interval = 30.0
        self.index_roots = None
        self.last_cycle = None
        self.tap_status = {"capability": "unknown"}

    # ------------------------------------------------------------------ files
    def _file(self, name: str) -> Path:
        return self.directory / name

    def settings(self):
        try:
            return normalize_settings(_read_json(self._file("capture.json")))
        except ValueError as exc:
            settings = default_settings()
            settings["enabled"] = False
            return settings, f"{exc}. La capture est désactivée jusqu'à correction."

    def _save_settings(self, settings: dict):
        _write_json(self._file("capture.json"), settings)

    def _stored_mappings(self, strict: bool = False) -> dict:
        try:
            value = _read_json(self._file("mappings.json"))
        except ValueError:
            if strict:  # a read-modify-write must not overwrite what it cannot read
                raise CaptureError("mappings.json est illisible : corrigez ou retirez ce fichier avant de modifier les rattachements.")
            return {}
        return {key: pid for key, pid in value.items() if isinstance(key, str) and isinstance(pid, str)} if isinstance(value, dict) else {}

    def _current_db_key(self) -> str:
        settings, _error = self.settings()
        return tap_source.db_key(tap_source.resolve_db_path(settings, self.env))

    def _stored_key(self, key: str) -> str:
        """A tap:ID key names a session of one claude-tap database, so it is stored with that database's identity."""
        return f"{key}@{self._current_db_key()}" if key.startswith("tap:") else key

    def _mappings(self, strict: bool = False) -> dict:
        """Mappings in force. Native session ids always apply; a tap:ID mapping applies only to the database it was
        chosen against. Mappings of another database stay stored (reapplied if that database returns) but never match."""
        current = self._current_db_key()
        active = {}
        for key, project_id in self._stored_mappings(strict).items():
            scoped = _SCOPED_KEY.fullmatch(key)
            if scoped:
                if scoped.group(2) == current:
                    active[scoped.group(1)] = project_id
            elif not key.startswith("tap:"):  # an unscoped tap: key cannot be tied to a database: it is never applied
                active[key] = project_id
        return active

    def _fresh_state(self) -> dict:
        return {"version": 1, "tap": {"db_key": None, "cursors": {}, "baseline": {}, "recent": {}, "updated": {}, "deleted": []}, "fallback": {"baselined": False, "files": {}, "waits": {}, "stalled": {}, "tap_seen": {}, "native_seen": {}}, "hold": False, "fallback_hold": False, "counters": {}, "skipped": {}, "malformed": {}, "notices": [], "last_scan": None}

    def _load_state(self, notices=None) -> dict:
        state = self._fresh_state()
        try:
            value = _read_json(self._file("state.json"))
        except ValueError:
            # Re-baselining is the safe recovery: it never imports history.
            try:
                os.replace(self._file("state.json"), self._file(f"state.corrupt-{int(time.time())}.json"))
            except OSError:
                pass
            value = None
            state["notices"].append({"at": _utc(), "code": "state_corrupt", "detail": "L'état de capture était illisible : nouvelle ligne de base, aucun historique importé."})
        if isinstance(value, dict) and value.get("version") == 1:
            for key, item in value.items():
                if key not in state:
                    continue
                if key in {"tap", "fallback"} and isinstance(item, dict):
                    state[key].update(item)
                elif key == "last_scan" and (item is None or isinstance(item, dict)):
                    state[key] = item
                elif key != "last_scan" and isinstance(item, type(state[key])):
                    state[key] = item
        fallback = state["fallback"]
        fallback["tap_seen"], fallback["native_seen"] = _clean_ledger(fallback.get("tap_seen")), _clean_ledger(fallback.get("native_seen"))
        for name in ("files", "waits", "stalled"):
            if not isinstance(fallback.get(name), dict):
                fallback[name] = {}
        fallback["stalled"] = {path: held for path, held in fallback["stalled"].items() if isinstance(held, dict) and path in fallback["files"]}
        return state

    def _load_pending(self) -> dict:
        try:
            value = _read_json(self._file("pending.json"))
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    def _save(self, state: dict, pending: dict):
        # Pending keys first: a crash between the two files replays records (idempotent: indexes and dedup),
        # whereas the reverse order would advance a cursor past records whose pending keys were never stored.
        _write_json(self._file("pending.json"), pending)
        _write_json(self._file("state.json"), state)
        if self.index is not None and self.index.dirty:
            _write_json(self._file("native-index.json"), self.index.dump())
            self.index.dirty = False

    def _notice(self, state, code, detail=""):
        state["notices"] = (state["notices"] + [{"at": _utc(), "code": code, "detail": detail[:200]}])[-MAX_NOTICES:]

    def _count(self, state, name, amount=1, bucket="counters"):
        state[bucket][name] = state[bucket].get(name, 0) + amount

    # ---------------------------------------------------------------- settings
    def _update(self, change):
        # The store's workspace lock is the cross-process writer lock (server, CLI and monitor share it).
        with self.mutex, self.store._lock:
            settings, error = self.settings()
            if error:
                raise CaptureError(error)
            change(settings)
            self._save_settings(settings)
            return settings

    def _hold(self, fallback_only: bool = False):
        """Ask the monitor to skip what happens from now on. The file also records the size of every held-back
        native transcript, so that lines written before the pause are still caught up and only the gap is skipped."""
        name = "hold-fallback" if fallback_only else "hold"
        self._file(name).parent.mkdir(parents=True, exist_ok=True)
        sizes = {}
        try:  # read-only: the monitor owns state.json, and a damaged file must not be renamed from here
            stalled = _read_json(self._file("state.json")).get("fallback", {}).get("stalled", {})
            for path in stalled if isinstance(stalled, dict) else ():
                with contextlib.suppress(OSError):
                    sizes[path] = os.stat(path).st_size
        except (OSError, ValueError, AttributeError):
            pass
        self._file(name).write_text(json.dumps({"at": _utc(), "sizes": sizes}), encoding="utf-8")

    def _take_hold(self, state, name) -> bool:
        path = self._file(name)
        if not path.exists():
            return False
        try:
            sizes = json.loads(path.read_text(encoding="utf-8")).get("sizes", {})
        except (OSError, ValueError, AttributeError):
            sizes = {}
        self._mark_held(state, sizes if isinstance(sizes, dict) else {})
        path.unlink(missing_ok=True)
        return True

    def _mark_held(self, state, sizes=None):
        """Remember where each held-back transcript ended when a pause began (the earliest mark wins until the pause ends)."""
        for path, held in state["fallback"]["stalled"].items():
            if "open" in held:
                continue
            size = (sizes or {}).get(path)
            if not isinstance(size, int):
                try:
                    size = os.stat(path).st_size
                except OSError:
                    continue
            held["open"] = size

    def set_enabled(self, enabled: bool):
        self._update(lambda s: s.update(enabled=bool(enabled)))
        if not enabled:
            self._hold()

    def set_paused(self, paused: bool, project_id: str = ""):
        if project_id:
            self._existing_project(project_id)
            self._update(lambda s: s.update(paused=[p for p in s["paused"] if p != project_id] + ([project_id] if paused else [])))
        else:
            self._update(lambda s: s.update(paused_all=bool(paused)))
            if paused:
                self._hold()

    def set_excluded(self, folder, excluded: bool):
        try:
            path = self.store.canonical_folder(folder)["path"]
        except ValueError:
            if excluded:
                raise
            path = str(folder)
        def change(settings):
            kept = [p for p in settings["exclude"] if os.path.normcase(p) != os.path.normcase(path)]
            settings["exclude"] = kept + ([path] if excluded else [])
        self._update(change)

    def set_allowed_roots(self, roots):
        """None keeps the v0.1 behaviour; a list of existing absolute folders confines resolution and creation."""
        if roots is not None:
            clean = []
            for root in roots:
                path = Path(root).expanduser()
                if not path.is_absolute() or not path.is_dir():
                    raise ValueError(f"Racine autorisée invalide (dossier absolu existant attendu) : {root}")
                clean.append(str(path.resolve()))
            roots = list(dict.fromkeys(clean))

        def change(settings):
            settings["allowed_roots"] = roots
        self._update(change)
        return roots

    def set_native_fallback(self, enabled: bool):
        self._update(lambda s: s["sources"].update(native_fallback=bool(enabled)))
        self._hold(fallback_only=True)  # the tap cursors are unaffected: tap activity is never discarded by this toggle

    def _existing_project(self, project_id) -> dict:
        try:
            return self.store.get_project(project_id)
        except (KeyError, FileNotFoundError):
            raise UnknownProject("Projet introuvable.") from None
        except ValueError:
            raise CaptureError("Identifiant de projet invalide.") from None

    def _tap_session_known(self, session_id: str) -> bool:
        settings, _error = self.settings()
        connection, capability = tap_source.open_db(tap_source.resolve_db_path(settings, self.env))
        if connection is None:
            raise CaptureError(f"La base claude-tap n'est pas lisible ({capability}) : impossible de vérifier la session.")
        try:
            return connection.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone() is not None
        except sqlite3.Error:
            raise CaptureError("La base claude-tap n'est pas lisible : impossible de vérifier la session.") from None
        finally:
            connection.close()

    def link(self, key: str, project_id: str, import_history: bool = False) -> dict:
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise CaptureError("Clé de session invalide.")
        project = self._existing_project(project_id)
        if project.get("demo"):
            raise CaptureError("Le projet de démonstration ne reçoit pas de capture.")
        with self.mutex:
            # Refuse before any write: a rejected request leaves neither a mapping nor a history request.
            if key.startswith("file:") and not any(item["stalled"] and item["key"] == key for item in self.pending()):
                raise CaptureError("Aucune transcription en attente ne porte cette clé file: (voir « capture pending »).")
            if import_history:
                if key.startswith("file:") or (not key.startswith("tap:") and key not in self._load_pending()):
                    raise CaptureError("L'historique ne peut être importé que pour une session en attente ou une clé tap:ID.")
                if key.startswith("tap:") and key not in self._load_pending() and not self._tap_session_known(key[4:]):
                    raise CaptureError("Cette session tap est inconnue de la base claude-tap actuelle : aucun historique à importer.")
                self._request_history(key)
            with self.store._lock:
                mappings = self._stored_mappings(strict=True)
                mappings[self._stored_key(key)] = project_id
                _write_json(self._file("mappings.json"), mappings)
            replayed = self.scan_if_possible()
            still_pending = replayed and any(item["key"] == key and item["stalled"] for item in self.pending())
            return {"key": key, "project_id": project_id, "replayed": replayed, "still_pending": bool(still_pending)}

    def _request_history(self, key: str):
        owned = self.lock.handle is not None
        if not owned and not self.lock.acquire():
            raise CaptureError("La capture tourne dans un autre processus : demandez l'historique depuis ce processus (interface ou CLI après arrêt).")
        try:
            self._write_history_request(key)
        finally:
            if not owned:
                self.lock.release()

    def _write_history_request(self, key: str):
        pending = self._load_pending()
        entry = pending.setdefault(key, {"key": key, "client": "", "reason": "mappé", "count": 0, "sessions": {}, "first_ts": "", "last_ts": ""})
        if key.startswith("tap:"):
            entry["history"] = {key[4:]: 0}
        else:
            entry["history"] = {sid: 0 for sid in entry["sessions"]}
        _write_json(self._file("pending.json"), pending)

    def unlink(self, key: str) -> dict:
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise CaptureError("Clé de session invalide.")
        with self.mutex, self.store._lock:
            mappings = self._stored_mappings(strict=True)
            existed = mappings.pop(self._stored_key(key), None) is not None
            existed = (mappings.pop(key, None) is not None) or existed  # also a legacy unscoped entry
            _write_json(self._file("mappings.json"), mappings)
            return {"key": key, "unlinked": existed}

    def scan_if_possible(self) -> bool:
        """Replay immediately when this process may run captures; otherwise the runner will."""
        owned = self.lock.handle is not None
        if not owned and not self.lock.acquire():
            return False
        try:
            self.scan_once()
            return True
        finally:
            if not owned:
                self.lock.release()

    # ------------------------------------------------------------------ linking
    def _project_summaries(self) -> list:
        with self.store._lock:
            self.store._recover()
            return self.store._raw_projects()

    def _is_excluded(self, ctx, folder: Path) -> bool:
        blocked = [*ctx.excluded, self.store.root]
        blocked += [Path(project["folder"]["path"]) for project in ctx.projects.values() if project.get("demo") and project.get("folder")]
        return any(folder == item or item in folder.parents for item in blocked)

    def _native(self, settings):
        if not settings["sources"]["native_index"]:
            return None
        roots = native_index.default_roots(settings, self.env)
        if self.index is None or self.index_roots != roots:
            try:
                files = _read_json(self._file("native-index.json"))
            except ValueError:
                files = None
            self.index = native_index.NativeIndex(roots, files)
            self.index_roots = roots
        return self.index

    def _lookup(self, ctx, native):
        index = self._native(ctx.settings)
        if index is None:
            return None
        found = index.lookup(native)
        if not found and native not in ctx.refreshed and time.monotonic() - self.last_refresh >= self.refresh_interval:
            ctx.refreshed.add(native)
            self.last_refresh = time.monotonic()
            index.refresh(wanted=[native])
            found = index.lookup(native)
        return found

    def _resolve_native(self, ctx, native: str) -> dict:
        if native in ctx.resolved:
            return ctx.resolved[native]
        try:
            result = self._resolve_native_uncached(ctx, native)
        except ConflictError:
            raise  # the store is busy: the cycle is retried, nothing is decided
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError):
            # One session whose folder cannot be handled is held for the user; it never stops the sessions after it.
            result = {"status": "resolve_error"}
        if result["status"] not in {"unknown_native"}:
            ctx.resolved[native] = result
        return result

    def _resolve_native_uncached(self, ctx, native: str) -> dict:
        matches = self._lookup(ctx, native)
        if matches is None:
            return {"status": "native_index_off"}
        if not matches:
            return {"status": "unknown_native"}
        if len({match["source"] for match in matches}) > 1:
            return {"status": "ambiguous_native_session"}
        if any(match["over"] for match in matches):
            return {"status": "ambiguous_cwd"}
        resolved = []
        for cwd in dict.fromkeys(cwd for match in matches for cwd in match["cwds"]):
            path = Path(_plain_path(cwd))
            try:
                if not path.is_absolute():
                    return {"status": "cwd_invalid"}
                canonical = Path(_plain_path(str(path.resolve(strict=True))))
            except (OSError, RuntimeError, ValueError):
                return {"status": "cwd_missing"}
            if not canonical.is_dir():
                return {"status": "cwd_missing"}
            if canonical not in resolved:
                resolved.append(canonical)
        root = next((candidate for candidate in resolved if all(candidate == other or candidate in other.parents for other in resolved)), None)
        if root is None:
            return {"status": "ambiguous_cwd"}
        roots = ctx.settings["allowed_roots"]
        if roots is not None and not resolver.under_roots(root, roots):
            return {"status": "outside_roots"}  # key only: no folder, no text, no project
        evidence = {"native_source": matches[0]["source"], "native_file": Path(matches[0]["file"]).name, "cwd": str(root)}
        if self._is_excluded(ctx, root):
            return {"status": "excluded", **evidence}
        projects = []
        for path in resolved:
            project = self.store.locate_project(str(path))
            if project and project.get("folder") and _is_generic(project["folder"]["path"], self.env):
                project = None  # a project bound to a shared location (temp, users, system) must not absorb what lies below it
            if project is None:
                project = self._worktree_project(path)
                if project is not None:
                    evidence["worktree_of"] = project["folder"]["path"]
            projects.append(project["id"] if project else None)
        if any(projects):
            if len(set(projects)) != 1:
                return {"status": "ambiguous_cwd", **evidence}
            return {"status": "ok", "project_id": projects[0], **evidence}
        if not ctx.settings["auto_create"]:
            return {"status": "no_project", **evidence}
        if _is_generic(root, self.env):
            return {"status": "cwd_refused", **evidence}
        git = _git_root(root)
        if git is not None and (_contains_home(git) or _is_generic(git, self.env)):
            git = None  # a repository above the home folder or at a shared location must not merge unrelated folders
        target = None
        for candidate in ([git] if git else []) + [root]:
            try:
                target = self.store.canonical_folder(str(candidate))
            except ValueError:
                continue
            if self._is_excluded(ctx, Path(target["path"])):
                target = None
                continue
            break
        if target is None:
            return {"status": "cwd_refused", **evidence}
        try:
            project = self.store.create_project((Path(target["path"]).name or "Projet")[:160].strip() or "Projet", "Projet créé automatiquement : dossier détecté par une session d'agent.", folder=target["path"])
        except ConflictError:
            project = self.store.locate_project(target["path"])
            if project is None:
                return {"status": "no_project", **evidence}
        except ValueError:
            return {"status": "cwd_refused", **evidence}
        ctx.projects[project["id"]] = project
        return {"status": "ok", "project_id": project["id"], **evidence}

    def _worktree_project(self, path: Path):
        """Project registered exactly at the main repository of a proven linked worktree, else None."""
        git = _git_root(path)
        main = resolver.proven_worktree_main(git) if git is not None else None
        if main is None or _is_generic(main, self.env):
            return None
        project = self.store.locate_project(str(main))
        if not project or not project.get("folder"):
            return None
        if os.path.normcase(str(Path(_plain_path(project["folder"]["path"])))) != os.path.normcase(str(Path(_plain_path(str(main.resolve()))))):
            return None  # only the repository's own project, never an ancestor that happens to contain it
        return project

    def _link(self, ctx, session_id: str, ids: set) -> dict:
        values = {value for _, value in ids}
        real = values - {""}
        tap_key = f"tap:{session_id}"
        conflict = len(real) > 1 or ("" in values and bool(real))
        # Under a conflict no claimed id is trustworthy, so only the user's explicit choice for this exact
        # tap session can link it. The conflict is never resolved by the software, and it stays in the provenance.
        native = None if conflict else next(iter(real), None)
        mapped = {key: ctx.mappings[key] for key in ([native] if native else []) + [tap_key] if key in ctx.mappings}
        if conflict and not mapped:
            return {"status": "pending", "key": tap_key, "reason": "ambiguous_native_id"}
        if len(set(mapped.values())) > 1:
            return {"status": "pending", "key": tap_key, "reason": "mapping_conflict"}
        for key, project_id in mapped.items():
            if project_id not in ctx.projects:
                return {"status": "pending", "key": key, "reason": "mapping_project_missing"}
            folder = (ctx.projects[project_id].get("folder") or {}).get("path")
            outcome = {"status": "linked", "project_id": project_id, "mode": "explicit", "native_id": native, "mapped_key": key, "mapped_keys": sorted(mapped), "target_folder": folder}
            if conflict:
                outcome["claimed_ids"] = sorted(real)
            return outcome
        if native is None:
            return {"status": "pending", "key": tap_key, "reason": "no_native_id"}
        resolution = self._resolve_native(ctx, native)
        if resolution["status"] == "ok":
            return {"status": "linked", "project_id": resolution["project_id"], "mode": "native", "native_id": native, "evidence": resolution}
        if resolution["status"] == "excluded":
            return {"status": "skip", "reason": "excluded"}
        return {"status": "pending", "key": native, "reason": resolution["status"], "native_id": native}

    # ------------------------------------------------------------------ pending
    def _add_pending(self, pending, key, session_id, client, index, timestamp, reason):
        entry = pending.setdefault(key, {"key": key, "client": client, "reason": reason, "count": 0, "sessions": {}, "first_ts": timestamp or "", "last_ts": timestamp or ""})
        entry["reason"], entry["client"] = reason, client or entry.get("client", "")
        sessions = entry["sessions"]
        if session_id not in sessions and len(sessions) >= MAX_PENDING_SESSIONS:
            entry["overflow"] = True
            return
        indexes = sessions.setdefault(session_id, [])
        if index in indexes:
            return
        if len(indexes) >= MAX_PENDING_INDEXES:
            entry["overflow"] = True
            return
        indexes.append(index)
        entry["count"] = sum(len(item) for item in sessions.values())
        if timestamp:
            entry["first_ts"] = min(entry["first_ts"] or timestamp, timestamp)
            entry["last_ts"] = max(entry["last_ts"], timestamp)

    def pending(self) -> list:
        """Unlinked tap sessions, then native transcripts held back at an unresolved session. Keys and reasons only, never text."""
        result = [{"key": entry["key"], "client": entry.get("client", ""), "reason": entry.get("reason", ""), "count": entry.get("count", 0), "sessions": len(entry.get("sessions", {})), "first_ts": entry.get("first_ts", ""), "last_ts": entry.get("last_ts", ""), "history": bool(entry.get("history")), "overflow": bool(entry.get("overflow")), "stalled": False} for entry in self._load_pending().values() if isinstance(entry, dict) and "key" in entry]
        held_keys = set()
        for path, held in self._load_state()["fallback"]["stalled"].items():
            key = held.get("native") or self._file_key(path)
            if key in held_keys:
                continue
            held_keys.add(key)
            result.append({"key": key, "client": str(held.get("source", "")), "reason": str(held.get("reason", "")), "count": 0, "sessions": 1, "first_ts": "", "last_ts": str(held.get("since", "")), "history": False, "overflow": False, "stalled": True})
        return result

    # ------------------------------------------------------------------ events
    def _events(self, state, outcome, db_key, session_id, client, index, timestamp, digest, items, ids):
        kinds = {kind for kind, value in ids if value}
        agent = tap_source.agent_label(kinds, client)
        slug = "codex" if agent == "Codex" else "claude-code"
        evidence = outcome.get("evidence", {})
        provenance = {"collector": "claude-tap", "tap_db_key": db_key, "tap_session_id": session_id, "record_index": index, "payload_sha256": digest, "native_id": outcome.get("native_id"), "link": outcome["mode"], "native_source": evidence.get("native_source"), "native_file": evidence.get("native_file"), "cwd": evidence.get("cwd"), **({"worktree_of": evidence["worktree_of"]} if evidence.get("worktree_of") else {}), "claim": "identifiants déclaratifs, non authentifiés"}
        if outcome["mode"] == "explicit":
            # The folder is where the user chose to file this session; it is not evidence from a native transcript.
            provenance.update(target_folder=outcome.get("target_folder"), target_basis="dossier du projet choisi explicitement par l'utilisateur ; aucune preuve de dossier natif")
            if outcome.get("claimed_ids"):
                provenance["claimed_native_ids"] = outcome["claimed_ids"]
        episode = outcome.get("native_id") or session_id
        events, counters = [], {}
        for item in items:
            kind = item["kind"]
            slot = f"{_SLOTS[kind]}-{counters.get(kind, 0)}"
            counters[kind] = counters.get(kind, 0) + 1
            text, found = redact_whole(item["text"])  # before the title/excerpt cuts below
            line = _first_line(text)
            if kind == "user_text":
                title, body, who, tag = f"Utilisateur · {line}", text, f"Humain via {agent}", "humain"
            elif kind == "assistant_text":
                title, body, who, tag = f"{agent} · réponse · {line}", text, agent, "reponse"
            elif kind == "tool_call":
                title, body, who, tag = f"Appel d'outil {item['name']} · {line}", f"Outil : {item['name']}\n{text}", agent, "appel-outil"
            elif kind == "tool_result":
                title, body, who, tag = ("Résultat d'outil (erreur) · " if item.get("error") else "Résultat d'outil · ") + line, text, agent, "resultat-outil"
            else:
                title, body, who, tag = f"Échec · {line}", text, agent, "echec-http"
            title, more = redact_whole(title)
            events.append(PreRedacted({"title": title[:180], "body": body or title, "agent": who[:240], "episode": episode[:240], "timestamp": tap_source.repair_text(timestamp or "")[:80],
                           "sources": [{"label": f"claude-tap · {client or 'client'} · {session_id[:8]} #{index}", "uri": f"tap:{session_id}:{index}:{slot}", "excerpt": text[:4000]}],
                           "tags": ["capture", "claude-tap", slug, tag, "lien-natif" if outcome["mode"] == "native" else "lien-explicite"], "provenance": provenance, "pre_redactions": found + more}))
        return events

    def _flush(self, state, ctx):
        if not ctx.settings["activity"]["turn_proposals"]:
            # Per-turn proposals are off (ADR-0003): only the activity journal and session sheets remain.
            dropped = sum(len(events) for events in ctx.events.values())
            if dropped:
                self._count(state, "turn_proposals_off", dropped, bucket="skipped")
            ctx.events.clear()
            return
        for project_id, events in list(ctx.events.items()):
            for start in range(0, len(events), 500):
                chunk = events[start:start + 500]
                try:
                    result = self.store.import_events(project_id, chunk, "claude-tap", internal=True)
                except (ConflictError, OSError, TimeoutError) as exc:
                    raise _Transient(type(exc).__name__) from exc
                except (ValueError, KeyError):
                    result = {"imported": 0, "duplicates": 0, "redactions": 0}
                    refusals = []
                    for event in chunk:
                        try:
                            single = self.store.import_events(project_id, [event], "claude-tap", internal=True)
                            result["imported"] += single["imported"]
                            result["duplicates"] += single["duplicates"]
                            result["redactions"] += single.get("redactions", 0)
                        except ConflictError as exc:
                            raise _Transient(type(exc).__name__) from exc
                        except (ValueError, KeyError) as exc:
                            self._count(state, "rejected")
                            refusals.append(str(exc)[:120])
                    if refusals:  # reasons only, never the refused content
                        self._notice(state, "event_rejected", f"{len(refusals)} événement(s) refusé(s) par la mémoire : {refusals[0]}")
                self._count(state, "imported", result["imported"])
                self._count(state, "duplicates", result["duplicates"])
                if result.get("redactions"):
                    self._count(state, "redactions", result["redactions"])
        ctx.events.clear()

    # --------------------------------------------------------------- processing
    def _process_rows(self, ctx, state, pending, connection, db_key, session_id, client, rows, require_key=None, track=True):
        recent = state["tap"]["recent"].setdefault(session_id, {})
        for index, timestamp, text, _size in rows:
            if text is None:
                self._count(state, "oversize", bucket="malformed")
                continue
            try:
                record = tap_source.decode_payload(connection, session_id, text)
                ids = tap_source.native_ids(record)
                turn = tap_source.extract_turn(record)
            except tap_source.RecordError as exc:
                self._count(state, exc.code, bucket="malformed")
                continue
            except sqlite3.Error:
                raise  # busy or unreadable database: nothing advances, the cycle is retried
            except Exception:
                # A hostile or unforeseen record shape must cost one record, never the monitor.
                self._count(state, "processing_error", bucket="malformed")
                continue
            digest = tap_source.payload_hash(text)
            if track:
                recent[str(index)] = digest[:16]
                for stale in sorted(recent, key=int)[:-5]:
                    del recent[stale]
            for reason, number in turn["skipped"].items():
                self._count(state, reason, number, bucket="skipped")
            try:
                self._place_record(ctx, state, pending, db_key, session_id, client, index, timestamp, digest, turn, ids, track, require_key)
            except ConflictError:
                raise
            except (ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError):
                # A record whose handling fails costs that record (counted), never the rest of the session.
                self._count(state, "processing_error", bucket="malformed")

    def _place_record(self, ctx, state, pending, db_key, session_id, client, index, timestamp, digest, turn, ids, track, require_key=None):
        fallback = state["fallback"]
        real = {value for _, value in ids if value}
        if len(real) == 1:
            native, now, kept = next(iter(real)), _clock(), []
            for item in turn["items"]:
                mark = _item_digest(item)
                if mark and _ledger_take(fallback["native_seen"], native, mark, now):
                    self._count(state, "native_duplicate", bucket="skipped")  # already captured from the native transcript
                    continue
                if mark and track:
                    _ledger_add(fallback["tap_seen"], native, mark, now)
                kept.append(item)
            turn["items"] = kept
        if not turn["items"]:
            return
        outcome = self._link(ctx, session_id, ids)
        if require_key and require_key not in outcome.get("mapped_keys", ()):
            return
        if outcome["status"] == "pending":
            self._add_pending(pending, outcome["key"], session_id, client, index, str(timestamp or ""), outcome["reason"])
            return
        if outcome["status"] == "skip":
            self._count(state, outcome["reason"], len(turn["items"]), bucket="skipped")
            return
        project = ctx.projects.get(outcome["project_id"])
        if project is None:
            return
        if project.get("demo") or (project.get("folder") and self._is_excluded(ctx, Path(project["folder"]["path"]))):
            self._count(state, "excluded", len(turn["items"]), bucket="skipped")
            return
        if outcome["project_id"] in ctx.paused:
            self._count(state, "paused", len(turn["items"]), bucket="skipped")
            return
        ctx.events.setdefault(outcome["project_id"], []).extend(self._events(state, outcome, db_key, session_id, client, index, str(timestamp or ""), digest, turn["items"], ids))

    def _check_rewrites(self, state, connection, session_id, info):
        tap = state["tap"]
        recent = tap["recent"].get(session_id)
        if not recent or tap["updated"].get(session_id) == info["updated_at"]:
            tap["updated"][session_id] = info["updated_at"]
            return
        tap["updated"][session_id] = info["updated_at"]
        for index, _timestamp, text, _size in tap_source.read_rows(connection, session_id, sorted(int(i) for i in recent)):
            digest = tap_source.payload_hash(text)[:16] if text is not None else "oversize"
            if recent.get(str(index)) not in {None, digest}:
                recent[str(index)] = digest
                self._count(state, "rewritten")
                self._notice(state, "rewritten", f"session {session_id[:8]} #{index} : contenu modifié après capture ; aucune entrée réimportée.")

    def _quarantine_pending(self, state, pending, old_key):
        """Pending keys name sessions and record indexes of one database; they must never be replayed
        against another. They are set aside (keys only, no content) and the live set is cleared."""
        if not pending:
            return
        stamp = f"{int(time.time())}-{old_key or 'none'}"
        _write_json(self._file(f"pending.quarantine-{stamp}.json"), {"db_key": old_key, "pending": pending})
        self._notice(state, "pending_quarantined", f"{len(pending)} clé(s) en attente d'une autre base claude-tap mises de côté (pending.quarantine-*.json) ; elles ne sont pas rejouées.")
        pending.clear()
        old = sorted(self.directory.glob("pending.quarantine-*.json"), key=lambda path: path.stat().st_mtime_ns)
        for path in old[:-MAX_QUARANTINES]:
            path.unlink(missing_ok=True)

    def _scan_tap(self, ctx, state, pending, result):
        settings = ctx.settings
        path = tap_source.resolve_db_path(settings, self.env)
        key = tap_source.db_key(path)
        connection, capability = tap_source.open_db(path)
        self.tap_status = {"path": str(path), "capability": capability}
        if connection is None:
            result["tap"] = capability
            tap = state["tap"]
            if capability == "missing" and tap.get("db_key") != key and not state["hold"]:
                # Nothing existed at first start: everything that appears later is new.
                self._quarantine_pending(state, pending, tap.get("db_key"))
                tap.update(db_key=key, cursors={}, baseline={}, recent={}, updated={}, deleted=[])
                self._save(state, pending)
            return
        try:
            tap = state["tap"]
            tap_source.take_invalid_text()
            sessions = tap_source.list_sessions(connection)
            tap_source.take_invalid_text()
            self.tap_status["sessions"] = len(sessions)
            if tap.get("db_key") != key or state["hold"]:
                first = tap.get("db_key") != key
                maxima = {sid: info["max_index"] for sid, info in sessions.items()}
                tap["cursors"] = {**tap["cursors"], **maxima} if not first else dict(maxima)
                if first:
                    self._quarantine_pending(state, pending, tap.get("db_key"))
                    tap.update(db_key=key, baseline=dict(maxima), recent={}, updated={}, deleted=[])
                    self._notice(state, "baseline", f"{len(maxima)} session(s) existante(s) ignorée(s) : seule l'activité future est capturée.")
                else:
                    self._notice(state, "resumed", "Reprise après pause ou désactivation : l'activité de la pause n'est pas capturée.")
                state["hold"] = False
                result["baseline"] = True
                self._save(state, pending)
                return
            cursors = tap["cursors"]
            for gone in [sid for sid in cursors if sid not in sessions and sid not in tap["deleted"]]:
                tap["deleted"].append(gone)
                self._count(state, "deleted_upstream")
                self._notice(state, "deleted_upstream", f"session tap {gone[:8]} supprimée en amont ; la mémoire est conservée.")
            budget = MAX_RECORDS_PER_CYCLE
            for session_id, info in sessions.items():
                cursor = cursors.get(session_id, 0)
                if info["max_index"] < cursor:
                    self._count(state, "rewritten")
                    self._notice(state, "truncated", f"session tap {session_id[:8]} tronquée en amont.")
                    cursors[session_id] = cursor = info["max_index"]
                self._check_rewrites(state, connection, session_id, info)
                tap_source.take_invalid_text()  # re-reads of already counted rows are not counted again
                while cursor < info["max_index"] and budget > 0:
                    rows = tap_source.read_batch(connection, session_id, cursor, min(tap_source.BATCH, budget), upto=info["max_index"])
                    damaged = tap_source.take_invalid_text()
                    if damaged:
                        self._count(state, "tap_invalid_utf8", damaged, bucket="malformed")  # decoded with replacement characters
                    if not rows:
                        cursor = info["max_index"]
                        cursors[session_id] = cursor
                        break
                    self._process_rows(ctx, state, pending, connection, key, session_id, info["client"], rows)
                    self._flush(state, ctx)
                    cursor = cursors[session_id] = rows[-1][0]
                    budget -= len(rows)
                    result["records"] = result.get("records", 0) + len(rows)
                    self._save(state, pending)
            self._retry_pending(ctx, state, pending, connection, key, sessions)
            result["tap"] = "ok"
        except sqlite3.Error as exc:
            self.tap_status["capability"] = "locked" if "locked" in str(exc).lower() or "busy" in str(exc).lower() else "corrupt"
            result["tap"] = self.tap_status["capability"]
        finally:
            tap_source.take_invalid_text()
            connection.close()

    def _retry_pending(self, ctx, state, pending, connection, db_key, sessions):
        for key in list(pending):
            entry = pending[key]
            if not isinstance(entry, dict):
                del pending[key]
                continue
            if key in ctx.mappings:
                if ctx.mappings[key] not in ctx.projects:
                    entry["reason"] = "mapping_project_missing"
                    continue
            elif key.startswith("tap:") or self._resolve_native(ctx, key)["status"] != "ok":
                if not key.startswith("tap:"):
                    entry["reason"] = self._resolve_native(ctx, key)["status"]
                continue
            sessions_map = entry.get("sessions", {})
            for session_id in list(sessions_map):
                indexes = sorted(sessions_map.pop(session_id))
                if session_id not in sessions:
                    continue
                client = sessions[session_id]["client"]
                for start in range(0, len(indexes), 200):
                    rows = tap_source.read_rows(connection, session_id, indexes[start:start + 200])
                    self._process_rows(ctx, state, pending, connection, db_key, session_id, client, rows, track=False)
                    self._flush(state, ctx)
            for session_id, nxt in list((entry.get("history") or {}).items()):
                limit = state["tap"]["baseline"].get(session_id, 0)
                rows = tap_source.read_batch(connection, session_id, nxt, tap_source.BATCH, upto=limit) if session_id in sessions else []
                if not rows:
                    del entry["history"][session_id]
                    continue
                self._process_rows(ctx, state, pending, connection, db_key, session_id, sessions[session_id]["client"], rows, require_key=key if key in ctx.mappings else None, track=False)
                self._flush(state, ctx)
                entry["history"][session_id] = rows[-1][0]
                if rows[-1][0] >= limit:
                    del entry["history"][session_id]
            entry["count"] = sum(len(item) for item in entry.get("sessions", {}).values())
            if not entry.get("sessions") and not entry.get("history"):
                del pending[key]
            self._save(state, pending)

    # ----------------------------------------------------------------- fallback
    def _scan_fallback(self, ctx, state, pending, result):
        index = self._native(ctx.settings)
        if index is None:
            return
        fallback = state["fallback"]
        files = fallback["files"]
        listing = {path: (source, size, mtime) for source, root in index.roots.items() if root.is_dir() for path, size, mtime in native_index.iter_files(root)}
        stalled = fallback["stalled"]
        if not fallback["baselined"] or state["fallback_hold"]:
            # An explicit pause or disablement skips what was written meanwhile. Lines held back before it began
            # predate the pause and are still caught up: only the interval [open, now) of each held file is skipped.
            kept = {path: held for path, held in stalled.items() if "open" in held and path in listing} if fallback["baselined"] else {}
            gaps = fallback["gaps"] = {path: list(ranges) for path, ranges in fallback.get("gaps", {}).items() if path in kept} if isinstance(fallback.get("gaps"), dict) else {}
            for path, held in kept.items():
                ranges = gaps.setdefault(path, [])
                ranges.append([held.pop("open"), listing[path][1]])
                del ranges[:-MAX_GAPS]
            fallback["files"] = {path: files[path] if path in kept else size for path, (_s, size, _m) in listing.items()}
            fallback["baselined"] = True
            stalled.clear()
            stalled.update(kept)
            state["fallback_hold"] = False
            fallback["baselined_at"] = time.time()
            return
        index.refresh()
        waits = fallback["waits"]
        gaps = fallback["gaps"] = fallback["gaps"] if isinstance(fallback.get("gaps"), dict) else {}
        now = time.time()
        if not isinstance(fallback.get("baselined_at"), (int, float)):
            fallback["baselined_at"] = now  # state of an earlier version: the distinction starts here
        ignored = 0
        for path, (source, size, mtime) in listing.items():
            if path not in files and mtime / 1e9 < fallback["baselined_at"] - BASELINE_TOLERANCE:
                # First seen now, but last written before capture began: an old transcript (restored, copied with its
                # date, or only now reachable). It is history, like the transcripts present at the baseline: only
                # what is written to it from now on is captured. A transcript born after the baseline is read whole.
                files[path] = size
                ignored += 1
                continue
            offset = files.setdefault(path, 0)
            if size < offset:
                files[path] = offset = 0
                stalled.pop(path, None)
                gaps.pop(path, None)
                self._count(state, "native_rewritten")
            if size <= offset:
                waits.pop(path, None)
                stalled.pop(path, None)
                gaps.pop(path, None)
                continue
            held = stalled.get(path)
            if held and held.get("native"):
                # Re-read a held-back file only once its session resolves (or is deliberately excluded).
                status = self._fallback_resolution(ctx, held["native"])["status"]
                if status not in {"ok", "excluded"}:
                    held["reason"] = status
                    continue
            if now - mtime / 1e9 < FALLBACK_GRACE:
                # Give claude-tap a moment to record the same turn first, but never starve a file that is
                # written continuously: after FALLBACK_MAX_WAIT its complete lines are read regardless.
                if now - waits.setdefault(path, now) < FALLBACK_MAX_WAIT:
                    continue
            waits.pop(path, None)
            try:
                entries, new_offset, oversize = native_index.read_lines_ex(path, offset, 1024 * 1024)
            except OSError:
                continue  # removed or locked between the listing and the read; retried next cycle
            ranges = gaps.get(path, [])
            start, block, previous = offset, None, offset
            for end, line in entries:
                begin, previous = previous, end
                if any(begin < stop and end > first for first, stop in ranges):
                    self._count(state, "paused", bucket="skipped")  # written while capture was paused
                    start = end
                    continue
                try:
                    text, damaged = line.decode("utf-8"), False
                except UnicodeDecodeError:
                    text, damaged = line.decode("utf-8", "replace"), True
                try:
                    block = self._fallback_line(ctx, state, source, path, line, index, text)
                except ConflictError:
                    raise
                except (ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError):
                    block = None  # a line that cannot be handled costs that line (counted), never the rest of the file
                    self._count(state, "native_line_error", bucket="malformed")
                if block:
                    break  # unresolved session: nothing from this line on is consumed, order is kept
                if damaged:
                    self._count(state, "native_invalid_utf8", bucket="malformed")  # read with replacement characters
                start = end
            self._flush(state, ctx)
            if block is None:
                if oversize:
                    self._count(state, "native_oversize_line", oversize, bucket="malformed")
                files[path] = new_offset
                stalled.pop(path, None)
            elif path in stalled or len(stalled) < MAX_STALLED:
                files[path] = start
                known = stalled.get(path, {})
                if not known:
                    self._notice(state, "native_held", f"transcription {source} en attente d'une session résolue ({block['reason']}) ; rien n'est perdu.")
                stalled[path] = {**{name: known[name] for name in ("open",) if name in known}, "source": source, "native": block["native"], "reason": block["reason"], "since": known.get("since") or _utc()}
            else:
                # Bounded retention: past the cap the loss is explicit, never silent.
                files[path] = new_offset
                self._count(state, "fallback_held_overflow", bucket="skipped")
                self._notice(state, "native_held_overflow", f"plus de {MAX_STALLED} transcriptions en attente : celle-ci est ignorée.")
            if path in gaps:
                gaps[path] = [span for span in gaps[path] if span[1] > files[path]]
                if not gaps[path]:
                    del gaps[path]
            self._save(state, pending)
        for path in [path for path in files if path not in listing]:
            del files[path]
            waits.pop(path, None)
            stalled.pop(path, None)
            gaps.pop(path, None)
            self._count(state, "native_deleted")
        for path in [path for path in waits if path not in listing]:
            del waits[path]
        if ignored:
            self._count(state, "native_history_ignored", ignored, bucket="skipped")
            self._notice(state, "native_history_ignored", f"{ignored} transcription(s) antérieure(s) au démarrage de la capture découverte(s) tardivement : ignorées (historique).")

    @staticmethod
    def _file_key(path) -> str:
        """Key of a held transcript that names no session (the one `pending` shows and `link` accepts)."""
        return "file:" + _SAFE_NAME.sub("_", Path(path).name)[:120]

    def _fallback_resolution(self, ctx, native: str) -> dict:
        if native in ctx.mappings:
            return {"status": "ok" if ctx.mappings[native] in ctx.projects else "mapping_project_missing", "project_id": ctx.mappings[native], "explicit": True}
        return self._resolve_native(ctx, native)

    def _fallback_line(self, ctx, state, source, path, line, index, text=None):
        """Consume one native line. Returns None, or {"native", "reason"} when its session cannot be placed yet:
        the caller then keeps the file offset at this line. Only an explicit exclusion or pause is a deliberate skip."""
        try:
            value = json.loads(line if text is None else text)
        except (ValueError, RecursionError):
            self._count(state, "native_invalid_json", bucket="malformed")
            return None
        if not isinstance(value, dict):
            return None
        skipped = {}
        items = []
        if source == "claude":
            native = value.get("sessionId")
            message = value.get("message")
            if value.get("type") not in {"user", "assistant"} or value.get("isMeta") or not isinstance(message, dict):
                return None
            items = tap_source.content_items("user" if value["type"] == "user" else "assistant", message.get("content"), skipped, private=tap_source.is_private(message))
            stamp = value.get("uuid") if isinstance(value.get("uuid"), str) else hashlib.sha256(line).hexdigest()[:16]
        else:
            payload = value.get("payload")
            owners = list(index.files.get(path, {}).get("ids", {}))
            native = owners[0] if len(owners) == 1 else None
            if native is None and self._file_key(path) in ctx.mappings:
                native = self._file_key(path)  # a rollout without a usable session_meta, placed by the user's explicit choice
            if value.get("type") != "response_item" or not isinstance(payload, dict):
                return None
            kind = payload.get("type")
            if kind == "message" and payload.get("role") in {"user", "assistant"}:
                items = tap_source.content_items(payload["role"], payload.get("content"), skipped, private=tap_source.is_private(payload))
            elif kind in tap_source._CALL_TYPES:
                items = [tap_source._call_item(payload, skipped)]
            elif kind in tap_source._RESULT_TYPES:
                items = [tap_source._result_item(payload, skipped)]
            stamp = hashlib.sha256(line).hexdigest()[:16]
        if not items:
            for reason, number in skipped.items():
                self._count(state, "fallback_" + reason, number, bucket="skipped")
            return None
        if not isinstance(native, str) or not native:
            if source == "claude":
                return None  # a Claude row names its own session; without one it is malformed, not pending
            # Codex names the session in its first row: the index may simply not have read it yet.
            owners = len(index.files.get(path, {}).get("ids", {}))
            return {"native": None, "reason": "ambiguous_native_session" if owners > 1 else "unknown_native"}
        # Resolve before touching any ledger or counter: a held line is read again, so it must leave no trace.
        resolution = self._fallback_resolution(ctx, native)
        if resolution["status"] not in {"ok", "excluded"}:
            return {"native": native, "reason": resolution["status"]}
        for reason, number in skipped.items():
            self._count(state, "fallback_" + reason, number, bucket="skipped")
        ledgers, now, kept = state["fallback"], _clock(), []
        for number, item in enumerate(items):
            mark = _item_digest(item)
            if mark and _ledger_take(ledgers["tap_seen"], native, mark, now):
                self._count(state, "fallback_tap_duplicate", bucket="skipped")  # already captured through claude-tap
                continue
            kept.append((number, item, mark))
        if not kept:
            return None
        if resolution["status"] == "excluded":
            self._count(state, "excluded", len(kept), bucket="skipped")
            return None
        project_id = resolution["project_id"]
        project = ctx.projects.get(project_id)
        if project is None or project.get("demo") or (project.get("folder") and self._is_excluded(ctx, Path(project["folder"]["path"]))):
            self._count(state, "excluded", len(kept), bucket="skipped")
            return None
        if project_id in ctx.paused:
            self._count(state, "paused", len(kept), bucket="skipped")
            return None
        agent = "Codex" if source == "codex" else "Claude Code"
        for number, item, mark in kept:
            text, found = redact_whole(item["text"])  # before the title/excerpt cuts below
            who = f"Humain via {agent}" if item["kind"] == "user_text" else agent
            provenance = {"collector": "native-fallback", "native_id": native, "native_source": source, "native_file": Path(path).name, "cwd": resolution.get("cwd"), "link": "explicit" if resolution.get("explicit") else "native", **({"worktree_of": resolution["worktree_of"]} if resolution.get("worktree_of") else {}), "claim": "transcription locale, non authentifiée"}
            if resolution.get("explicit"):
                provenance.update(target_folder=(project.get("folder") or {}).get("path"), target_basis="dossier du projet choisi explicitement par l'utilisateur ; aucune preuve de dossier natif")
            ctx.events.setdefault(project_id, []).append(PreRedacted({
                "title": f"{agent} · {_first_line(text)}"[:180], "body": text or agent, "agent": who, "episode": native, "timestamp": tap_source.repair_text(str(value.get("timestamp", "")))[:80],
                "sources": [{"label": f"transcription native {source} · {native[:8]}", "uri": f"native:{source}:{native}:{stamp}:{number}", "excerpt": text[:4000]}],
                "tags": ["capture", "repli-natif", "codex" if source == "codex" else "claude-code", item["kind"].replace("_", "-")],
                "provenance": provenance, "pre_redactions": found}))
            if mark:
                _ledger_add(ledgers["native_seen"], native, mark, now)
        self._count(state, "fallback_imported", len(kept))
        return None

    # ----------------------------------------------------------------- scanning
    def _isolated(self, state, name, step, *arguments):
        try:
            return step(*arguments)
        except (_Transient, sqlite3.Error):
            raise
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError) as exc:
            self._notice(state, "source_error", f"{name} : {type(exc).__name__}")
            self._count(state, name, bucket="malformed")
            return None

    def scan_once(self) -> dict:
        """One bounded capture cycle. Imports first, state afterwards: a crash replays into dedup."""
        with self.mutex:
            result = {"state": "ok"}
            settings, error = self.settings()
            state = self._load_state()
            pending = self._load_pending()
            if self._take_hold(state, "hold"):
                state["hold"] = True
                state["fallback_hold"] = True
            if self._take_hold(state, "hold-fallback"):
                state["fallback_hold"] = True
            if error or not settings["enabled"] or settings["paused_all"]:
                state["hold"] = True
                state["fallback_hold"] = True
                self._mark_held(state)
                result["state"] = "settings_invalid" if error else "disabled" if not settings["enabled"] else "paused"
                self._save(state, pending)
                self.last_cycle = {"at": _utc(), **result}
                return result
            ctx = _Context(settings, self._mappings(), self._project_summaries())
            try:
                # One failing source is reported and never blocks the others.
                if settings["tap"]["enabled"]:
                    self._isolated(state, "tap", self._scan_tap, ctx, state, pending, result)
                else:
                    self.tap_status = {"capability": "disabled"}
                if settings["sources"]["native_index"] and self._native(settings) is not None and time.monotonic() - self.last_refresh >= self.index_interval:
                    self.last_refresh = time.monotonic()
                    stats = self._isolated(state, "native_index", self.index.refresh)
                    for name in ("rewritten", "deleted"):
                        if stats and stats[name]:
                            self._count(state, "native_" + name, stats[name])
                if settings["sources"]["native_fallback"] and settings["sources"]["native_index"]:
                    self._isolated(state, "native_fallback", self._scan_fallback, ctx, state, pending, result)
            except _Transient as exc:
                result["state"] = "busy"
                result["detail"] = str(exc)
                self.last_cycle = {"at": _utc(), **result}
                return result
            state["last_scan"] = {"at": _utc(), **{key: value for key, value in result.items() if isinstance(value, (str, int, bool))}}
            self._save(state, pending)
            self.last_cycle = state["last_scan"]
            return result

    # ------------------------------------------------------------- run / control
    def _stop_requested(self) -> bool:
        return self._file("stop").exists()

    def _loop(self, interval: float):
        interval = _safe_interval(interval)
        while not self.stop_event.is_set() and not self._stop_requested():
            try:
                self.scan_once()
            except Exception as exc:  # the monitor must survive one bad cycle
                try:
                    with self.mutex:
                        state = self._load_state()
                        self._notice(state, "scan_error", type(exc).__name__)
                        _write_json(self._file("state.json"), state)
                except Exception:
                    pass  # even reporting may fail (full disk, locked file); the next cycle retries
            self.stop_event.wait(interval)

    def start(self, interval: float = 3.0) -> bool:
        """Start the monitor thread when no other process holds the capture lock."""
        with self.mutex:
            if self.thread is not None and self.thread.is_alive():
                return True
            if not self.lock.acquire():
                return False
            self._file("stop").unlink(missing_ok=True)
            _write_json(self._file("runner.json"), {"pid": os.getpid(), "started_at": _utc()})
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._thread_main, args=(interval,), name="filigree-capture", daemon=True)
            self.thread.start()
            return True

    def _thread_main(self, interval):
        try:
            self._loop(interval)
        finally:
            self.lock.release()

    def stop(self, timeout: float = 10.0):
        self.stop_event.set()
        thread = self.thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        if thread is None or not thread.is_alive():
            self.lock.release()

    def run_foreground(self, interval: float = 3.0, once: bool = False, out=None) -> int:
        out = out or sys.stdout
        if not self.lock.acquire():
            print("La capture est déjà active dans un autre processus.", file=out, flush=True)
            return 0
        try:
            self._file("stop").unlink(missing_ok=True)
            _write_json(self._file("runner.json"), {"pid": os.getpid(), "started_at": _utc()})
            print(f"Capture active · mémoire {self.store.root}", file=out, flush=True)
            if once:
                print(json.dumps(self.scan_once(), ensure_ascii=False), file=out, flush=True)
                return 0
            try:
                self._loop(interval)
            except KeyboardInterrupt:
                pass
            return 0
        finally:
            self.lock.release()

    def is_running(self) -> bool:
        if self.thread is not None and self.thread.is_alive():
            return True
        if self.lock.handle is not None:
            return True
        probe = ProcessLock(self._file("capture.lock"))
        if probe.acquire():
            probe.release()
            return False
        return True

    def request_stop(self, wait: float = 10.0) -> str:
        """Cooperative stop: never kills a process."""
        if not self.is_running():
            return "not_running"
        self.directory.mkdir(parents=True, exist_ok=True)
        self._file("stop").write_text(_utc(), encoding="utf-8")
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if not self.is_running():
                self._file("stop").unlink(missing_ok=True)
                return "stopped"
            time.sleep(0.2)
        return "stop_requested"

    def start_background(self, wait: float = 5.0) -> str:
        if self.is_running():
            return "already_running"
        command = [sys.executable, "-m", "filigree", "--data-dir", str(self.store.root), "capture", "run"]
        options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
        if os.name == "nt":
            executable = Path(sys.executable).with_name("pythonw.exe")
            if executable.exists():
                command[0] = str(executable)
            options["creationflags"] = 0x00000008 | 0x08000000 | 0x00000200  # DETACHED | NO_WINDOW | NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        subprocess.Popen(command, **options)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if self.is_running():
                return "started"
            time.sleep(0.2)
        return "start_failed"

    def status(self) -> dict:
        settings, error = self.settings()
        try:
            state = self._load_state()
        except Exception:
            state = self._fresh_state()
        path = tap_source.resolve_db_path(settings, self.env)
        tap = tap_source.probe(path) if settings["tap"]["enabled"] and not error else {"path": str(path), "capability": "disabled", "sessions": 0}
        tap["baselined"] = state["tap"].get("db_key") == tap_source.db_key(path)
        roots = native_index.default_roots(settings, self.env)
        running = self.is_running()
        return {
            "enabled": settings["enabled"], "paused_all": settings["paused_all"], "auto_create": settings["auto_create"], "settings_error": error,
            "running": running, "in_process": self.thread is not None and self.thread.is_alive(), "tap": tap,
            "native": {"index": settings["sources"]["native_index"], "fallback": settings["sources"]["native_fallback"], "roots": {name: str(root) for name, root in roots.items()}},
            "counters": state["counters"], "skipped": state["skipped"], "malformed": state["malformed"], "notices": state["notices"][-10:],
            "last_scan": state["last_scan"], "pending": self.pending(), "paused": settings["paused"], "exclude": settings["exclude"], "mappings": len(self._mappings()), "mappings_other_database": len(self._stored_mappings()) - len(self._mappings()),
        }
