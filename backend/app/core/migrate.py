"""One-shot idempotent migration of legacy state/ -> workspaces/<id>/state/ (umbrella §9).

Extended (ARCH-005) with a versioned migration system.  Migrations are numbered
functions that run in order.  Applied migrations are tracked in
``<state_dir>/.migrations.json`` as a list of IDs.

The legacy one-shot migration (``migrate_legacy_state``) is preserved as-is.
"""
from __future__ import annotations

import json
import logging
import pathlib
import shutil
from typing import Any, Protocol

log = logging.getLogger("hephaestus.backend.migrate")

# ---------------------------------------------------------------------------
# Legacy one-shot migration (original 72-line logic — untouched)
# ---------------------------------------------------------------------------

# Overridable for tests; default to real config at call time.
_LEGACY_STATE_DIR: pathlib.Path | None = None
_LEGACY_REPO: str | None = None
_HOME: pathlib.Path | None = None


def _resolve() -> tuple[pathlib.Path, str, pathlib.Path]:
    from app.config import REPO, STATE_DIR
    from app.services.hephaestus_home import hephaestus_home

    legacy = _LEGACY_STATE_DIR or STATE_DIR
    repo = _LEGACY_REPO if _LEGACY_REPO is not None else REPO
    home = _HOME or hephaestus_home()
    return legacy, repo, home


def migrate_legacy_state() -> dict[str, Any]:
    legacy, repo, home = _resolve()
    marker = home / ".migrated"
    work_state = legacy / "work-state.json"

    if marker.exists() or not work_state.exists() or not repo:
        return {"migrated": False}

    from app.core.workspaces import WorkspaceRegistry

    if not (pathlib.Path(repo) / ".git").exists():
        log.warning("migrate: legacy REPO %s is not a git repo — skipping", repo)
        return {"migrated": False}

    reg = WorkspaceRegistry(home=home)
    ws = reg.create(repo, name=pathlib.Path(repo).name)
    dest = reg.state_dir(ws)
    dest.mkdir(parents=True, exist_ok=True)

    for entry in sorted(legacy.glob("*")):
        target = dest / entry.name
        if target.exists():
            continue
        if entry.is_dir():
            shutil.copytree(entry, target)
        else:
            shutil.copy2(entry, target)

    moved_state = dest / "work-state.json"
    try:
        data = json.loads(moved_state.read_text(encoding="utf-8"))
        for item in data.get("items", []):
            item.setdefault("workspaceId", ws.id)
        from app.core.state import _atomic_write

        _atomic_write(moved_state, json.dumps(data, indent=2, ensure_ascii=False))
    except Exception:
        log.warning("migrate: failed to stamp workspaceId on items")

    reg.update(ws.id, {"onboarded": False})
    reg.activate(ws.id)
    home.mkdir(parents=True, exist_ok=True)
    marker.write_text(ws.id)
    log.info("migrate: legacy state migrated to %s", dest)
    return {"migrated": True, "workspaceId": ws.id}


# ---------------------------------------------------------------------------
# Versioned migration system (ARCH-005)
# ---------------------------------------------------------------------------


class Migration(Protocol):
    """Protocol every migration must satisfy."""

    id: str
    description: str

    def run(self, state_dir: pathlib.Path) -> dict[str, Any]: ...


_MIGRATIONS_FILE = ".migrations.json"


def _read_applied(state_dir: pathlib.Path) -> set[str]:
    """Read the set of already-applied migration IDs."""
    path = state_dir / _MIGRATIONS_FILE
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data.get("applied", []))
    except (json.JSONDecodeError, ValueError):
        log.warning("corrupt .migrations.json — starting fresh")
        return set()


def _write_applied(state_dir: pathlib.Path, applied: set[str]) -> None:
    """Write the set of applied migration IDs."""
    path = state_dir / _MIGRATIONS_FILE
    data: dict[str, Any] = {"applied": sorted(applied), "version": len(applied)}
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run_migrations(state_dir: pathlib.Path) -> dict[str, Any]:
    """Run all pending migrations in order.  Idempotent."""
    applied = _read_applied(state_dir)
    newly_applied: list[str] = []
    skipped: list[str] = []

    for migration in _ALL_MIGRATIONS:
        if migration.id in applied:
            skipped.append(migration.id)
            continue
        try:
            result = migration.run(state_dir)
            log.info("migration %s: %s", migration.id, result)
            newly_applied.append(migration.id)
            applied.add(migration.id)
        except Exception:
            log.error("migration %s FAILED — stopping", migration.id, exc_info=True)
            break  # Stop on first failure — don't skip ahead

    if newly_applied:
        _write_applied(state_dir, applied)

    return {
        "applied": newly_applied,
        "skipped": skipped,
        "total": len(_ALL_MIGRATIONS),
    }


# ---------------------------------------------------------------------------
# Migration registry — empty for now, ready for future migrations
# ---------------------------------------------------------------------------

_ALL_MIGRATIONS: list[Any] = []
