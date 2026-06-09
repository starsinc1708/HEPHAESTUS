"""Filesystem directory browser for the repository picker.

The onboarding wizard lets users *pick* a repository from the filesystem the server can
actually see — typing an absolute path by hand is error-prone, and under Docker the path is
the **in-container** mount (e.g. ``/projects/<repo>``), not the host path. This read-only
endpoint lists the immediate subdirectories of a server path and flags which ones are git
repositories so the UI can offer them for selection.

Scope/safety: it exposes directory *names* only (never file contents) and never raises —
unreadable entries are skipped and a bad/non-existent path falls back to the nearest existing
ancestor (or the filesystem root). It is gated by the same dashboard auth as every other
endpoint (``HEPHAESTUS_DASHBOARD_PASSWORD`` when set); see SECURITY.md for the trust model.
"""
from __future__ import annotations

import pathlib
from typing import Any

from fastapi import APIRouter

router = APIRouter()

# Cap so an enormous directory can't produce an unbounded payload.
_MAX_ENTRIES = 1000


def _fs_root() -> pathlib.Path:
    """The filesystem root the picker falls back to (``/`` on POSIX, the drive root on Windows)."""
    return pathlib.Path("/").resolve()


@router.get("/api/v1/fs/browse")
def browse_fs(path: str = "") -> dict[str, Any]:
    """Immediate subdirectories of ``path`` (default: filesystem root), for the repo picker.

    Returns ``{ok, path, parent, entries:[{name, path, isGitRepo}]}`` where ``path`` is the
    resolved directory (POSIX-style), ``parent`` is its parent (``null`` at the root), and each
    entry is a child directory marked ``isGitRepo`` when it contains a ``.git``. Hidden dot-dirs
    are skipped. Never raises — an unreadable / non-existent ``path`` resolves to the nearest
    existing ancestor, then the root, so the picker always lands somewhere browsable."""
    try:
        base = pathlib.Path(path).resolve() if path.strip() else _fs_root()
    except (OSError, ValueError):
        base = _fs_root()
    if not base.is_dir():
        # Land on the nearest existing ancestor (e.g. "/projects" on a host without it → "/")
        # so the picker degrades gracefully instead of returning an error.
        base = next((p for p in base.parents if p.is_dir()), _fs_root())

    entries: list[dict[str, Any]] = []
    try:
        children = sorted(base.iterdir(), key=lambda p: p.name.casefold())
    except OSError:
        children = []
    for child in children:
        if len(entries) >= _MAX_ENTRIES:
            break
        try:
            if not child.is_dir() or child.name.startswith("."):
                continue
            is_git = (child / ".git").exists()
        except OSError:
            continue  # permission denied / vanished mid-iteration — skip, don't fail the listing
        entries.append({"name": child.name, "path": child.as_posix(), "isGitRepo": is_git})

    parent = base.parent.as_posix() if base.parent != base else None
    return {"ok": True, "path": base.as_posix(), "parent": parent, "entries": entries}
