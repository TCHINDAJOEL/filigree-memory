"""Git operates exclusively on a dedicated memory project directory."""

import shutil
import subprocess
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .store import redact

ADD_CHUNK_CHARS = 8000


def _safe_remote(remote: str) -> str:
    if "://" not in remote:
        return remote
    parsed = urlsplit(remote)
    return urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "", ""))


def _memory_file(name: str) -> bool:
    uid = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    return name in {"project.json", ".gitignore", ".filigree/imports.json"} or bool(re.fullmatch(rf"\.filigree/(?:entries/{uid}\.md|events/{uid}\.json|history/{uid}/[1-9][0-9]*\.md)", name))


def _run(path: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    if not shutil.which("git"):
        raise ValueError("Git n'est pas installé ou accessible dans PATH.")
    result = subprocess.run(["git", "-C", str(path), "-c", "core.quotepath=false", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
    if check and result.returncode:
        raise ValueError(_friendly(result.stderr.strip() or result.stdout.strip()))
    return result


def _friendly(message: str) -> str:
    lowered = message.lower()
    if "tell me who you are" in lowered or "empty ident" in lowered or "unable to auto-detect email" in lowered:
        return "Git ne connaît pas votre identité. Configurez-la une fois : git config --global user.name \"Votre nom\" puis git config --global user.email \"vous@exemple.org\"."
    return message or "L'opération Git a échoué."


def _changes(path: Path) -> list[str]:
    """Porcelain lines (`XY name`) for memory files only; unrelated files nearby do not make the memory dirty."""
    lines = []
    fields = iter(_run(path, "status", "--porcelain", "-z", "--untracked-files=all").stdout.split("\0"))
    for field in fields:
        if len(field) < 4:
            continue
        code, name = field[:2], field[3:]
        if "R" in code or "C" in code:
            next(fields, None)  # Original name of a rename/copy follows as its own field.
        if _memory_file(name):
            lines.append(f"{code} {name}")
    return lines


def status(path: Path) -> dict:
    available = bool(shutil.which("git"))
    initialized = (path / ".git").exists()  # A directory, or a file when the repository is a worktree/submodule.
    result = {"available": available, "initialized": initialized, "branch": "", "dirty": False, "remote": "", "changes": ""}
    if not available or not initialized:
        return result
    result["branch"] = _run(path, "branch", "--show-current").stdout.strip()
    result["changes"] = "\n".join(_changes(path))
    result["dirty"] = bool(result["changes"])
    result["remote"] = _safe_remote(_run(path, "remote", "get-url", "origin", check=False).stdout.strip())
    return result


def operate(path: Path, action: str, message: str = "docs(memory): checkpoint") -> dict:
    path = path.resolve(strict=True)
    if action == "init":
        if not (path / ".git").exists():
            _run(path, "init", "--initial-branch=main")
            (path / ".gitignore").write_text(".tmp-*\n", encoding="utf-8")
    elif action == "checkpoint":
        if not (path / ".git").exists():
            raise ValueError("Initialisez d'abord le dépôt mémoire.")
        if not isinstance(message, str) or not message.strip() or len(message) > 500:
            raise ValueError("Le message du checkpoint doit contenir entre 1 et 500 caractères.")
        message = redact(message)[0]  # same heuristic as stored text: a commit message is committed and may be pushed
        staged = _run(path, "diff", "--cached", "--name-only").stdout.splitlines()
        if any(not _memory_file(name) for name in staged):
            raise ValueError("L'index contient des fichiers étrangers à la mémoire. Retirez-les de l'index avant le checkpoint.")
        # Explicit canonical files only: never sweep arbitrary raw files placed nearby.
        tracked = _run(path, "ls-files").stdout.splitlines()
        paths = {name for name in tracked if _memory_file(name)}
        paths.update(file.relative_to(path).as_posix() for file in path.rglob("*") if file.is_file() and _memory_file(file.relative_to(path).as_posix()))
        paths = sorted(paths)
        # Chunked so a large history never exceeds the operating system's command-line limit.
        chunk, size = [], 0
        for name in paths:
            if chunk and size + len(name) + 1 > ADD_CHUNK_CHARS:
                _run(path, "add", "--", *chunk)
                chunk, size = [], 0
            chunk.append(name)
            size += len(name) + 1
        if chunk:
            _run(path, "add", "--", *chunk)
        changes = _run(path, "diff", "--cached", "--quiet", check=False)
        if changes.returncode == 1:
            _run(path, "commit", "-m", message.strip())
        elif changes.returncode != 0:
            raise ValueError(_friendly(changes.stderr.strip()) if changes.stderr.strip() else "Impossible de vérifier l'index Git.")
    elif action == "push":
        if not (path / ".git").exists():
            raise ValueError("Initialisez d'abord le dépôt mémoire.")
        remote = _run(path, "remote", "get-url", "origin").stdout.strip()
        if not remote.startswith(("https://github.com/", "git@github.com:")):
            raise ValueError("Configurez un remote origin GitHub HTTPS ou SSH dans ce dépôt mémoire.")
        _run(path, "push", "--set-upstream", "origin", "HEAD")
    else:
        raise ValueError("Action Git inconnue.")
    return status(path)
