"""Pure path-proof helpers: no subprocess, bounded reads, files only."""

from __future__ import annotations

import os
from pathlib import Path

MAX_READ = 4096


def _read_line(path: Path) -> str | None:
    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_READ)
    except OSError:
        return None
    lines = data.decode("utf-8", "replace").splitlines()
    return lines[0].strip() if lines else None


def _canon(path) -> str:
    return os.path.normcase(os.path.realpath(path))


def proven_worktree_main(folder: Path) -> Path | None:
    """Main repository of a linked git worktree, only if the gitdir link is proven in both directions."""
    folder = Path(folder)
    marker = folder / ".git"
    if not marker.is_file():
        return None
    line = _read_line(marker)
    if not line or not line.lower().startswith("gitdir:"):
        return None
    target = Path(line[7:].strip())
    admin = Path(os.path.realpath(target if target.is_absolute() else folder / target))
    if not admin.is_dir() or admin.parent.name != "worktrees" or admin.parent.parent.name != ".git":
        return None
    repo = admin.parent.parent.parent
    if not (repo / ".git").is_dir():
        return None
    back = _read_line(admin / "gitdir")
    if not back:
        return None
    back_path = Path(back)
    if not back_path.is_absolute():
        back_path = admin / back_path
    if _canon(back_path) != _canon(marker):
        return None
    return repo


def under_roots(path, roots) -> bool:
    """True if canonical `path` equals or lies inside any root (case-insensitive on Windows)."""
    candidate = _canon(path)
    for root in roots:
        base = _canon(root)
        if candidate == base or candidate.startswith(base.rstrip(os.sep) + os.sep):
            return True
    return False
