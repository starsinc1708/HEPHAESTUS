"""General-purpose helpers — ported from dashboard/server.py:84-230, 661-675, 746-749.

Subprocess wrapper, JSON loader, log tailing, iter-dir enumeration,
queue summary bucketing, and the default ad-hoc acceptance string.
"""

from __future__ import annotations

import json
import logging
import pathlib
import subprocess
from typing import Any

from app.config import STATE_DIR

log = logging.getLogger("hephaestus.backend.helpers")

LOG_TAIL_LINES = 60


def _active_git() -> tuple[str, str, str, str]:
    """(repo_path, base_branch, remote, branch_prefix) for the registry's ACTIVE workspace,
    falling back to the legacy globals. Dashboard git queries must use this — the legacy
    REPO is usually "" so `cwd=REPO` runs in the wrong directory and returns no data."""
    from app.config import BASE_BRANCH, BRANCH_PREFIX, REMOTE, REPO

    try:
        from app.core.workspaces import registry

        ws = registry.active()
        if ws is not None:
            return ws.repo_path, ws.base_branch, ws.remote, ws.branch_prefix
    except Exception:  # noqa: BLE001 — registry optional; fall back to legacy globals
        log.debug("_active_git: workspace registry unavailable", exc_info=True)
        pass
    return REPO, BASE_BRANCH, REMOTE, BRANCH_PREFIX


# ---------- helpers ----------


def _run(cmd: list[str], cwd: str | None = None, default: str = "", timeout: int = 30) -> str:
    try:
        # encoding/errors explicit: text=True defaults to the locale codec (cp125x on
        # Windows), which crashes on non-ASCII git output (e.g. UTF-8 diffs/commit msgs).
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=timeout, check=False)
        return out.stdout.strip() if out.returncode == 0 else default
    except subprocess.TimeoutExpired:
        import logging
        logging.getLogger("hephaestus.backend").warning("_run timed out after %ds: %s", timeout, " ".join(cmd[:3]))
        return default
    except Exception:
        log.debug("_run failed for %s", " ".join(cmd[:3]), exc_info=True)
        return default


def _load_json(path: pathlib.Path | str) -> dict[str, Any] | list[Any] | None:
    try:
        # Always UTF-8 — JSON we write is UTF-8; Windows' locale default (cp125x) would
        # mojibake non-ASCII (e.g. the Cyrillic scan status detail).
        obj: dict[str, Any] | list[Any] = json.loads(
            pathlib.Path(path).read_text(encoding="utf-8"))
        return obj
    except Exception:
        log.debug("_load_json failed for %s", path, exc_info=True)
        return None


# ---------- log / state surfacing ----------


def _log_tail() -> list[str]:
    log = STATE_DIR / "run.log"
    if not log.exists():
        return []
    with log.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 16384))
        chunk = f.read().decode(errors="replace")
    return chunk.splitlines()[-LOG_TAIL_LINES:]


def _all_iter_dirs() -> list[pathlib.Path]:
    from app.core.state import _state_dir  # active workspace state dir (legacy fallback)

    base = _state_dir()
    if not base.exists():
        return []
    return sorted(base.glob("iter-*"), key=lambda p: p.name)


def _active_iter_dir() -> pathlib.Path | None:
    its = _all_iter_dirs()
    return its[-1] if its else None


# ---------- summary ----------


def _summarize(state: dict[str, Any] | None) -> dict[str, Any]:
    items = state.get("items", []) if state else []
    buckets: dict[str, int] = {
        "pending": 0,
        "queued": 0,
        "in_progress": 0,
        "done": 0,
        "merged": 0,
        "needs_revision": 0,
        "discarded": 0,
    }
    failed: dict[str, int] = {}
    for it in items:
        st = it.get("status", "pending")
        if st in buckets:
            buckets[st] += 1
        elif st.startswith("failed"):
            kind = st.split(":", 1)[1] if ":" in st else "other"
            failed[kind] = failed.get(kind, 0) + 1
    ftotal = sum(failed.values())
    total = sum(buckets.values()) + ftotal
    done_or_merged = buckets["done"] + buckets["merged"]
    return {
        **buckets,
        "failed_total": ftotal,
        "failed_breakdown": failed,
        "total": total,
        "percent_done": (100 * done_or_merged // total) if total else 0,
    }


# ---------- queue editing ----------

_DEFAULT_ACCEPTANCE_ADHOC = (
    "Implement the proposal above. Add at least one unit test that exercises the new "
    "path and would fail without the production change. Verify (typecheck + lint + test) "
    "must pass."
)
