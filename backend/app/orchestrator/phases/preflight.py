"""PREFLIGHT phase — branch + iter dir + (optional) isolated worktree.

Body extracted from ``OrchestratorFSM._preflight`` (ARCH-001). Both the
parallel (isolated worktree) and sequential (main checkout) branches are
preserved bit-for-bit, including the atomic ``mkdir(exist_ok=False)`` loop
that uniquely claims an iter dir when concurrent workers start the same
second.
"""

from __future__ import annotations

import logging
import pathlib
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.orchestrator.fsm import OrchestratorFSM

log = logging.getLogger("hephaestus.orchestrator")


async def preflight_phase(fsm: OrchestratorFSM, item: dict[str, Any]) -> bool:
    """Check git status, create branch, set up iter dir."""
    from app.core.helpers import _run
    from app.core.state import _read_state, _StateLock, _write_state
    from app.core.workspaces import registry

    if fsm._ws is None:
        log.error("no active workspace for preflight")
        return False

    item_id = item.get("id", "?")
    branch = f"{fsm._ws.branch_prefix}/{item_id[:40]}-{int(time.time())}"
    base_ref = f"{fsm._ws.remote}/{fsm._ws.base_branch}"

    if fsm._parallel:
        # Isolated worktree so concurrent workers don't fight over one checkout.
        import re as _re

        safe = _re.sub(r"[^A-Za-z0-9._-]", "_", branch)
        wt = str(pathlib.Path(fsm._ws.repo_path).parent / ".hephaestus-worktrees" / safe)
        _run(["git", "worktree", "remove", "--force", wt], cwd=fsm._ws.repo_path)  # clear stale
        _run(["git", "worktree", "add", "-b", branch, wt, base_ref], cwd=fsm._ws.repo_path)
        if not pathlib.Path(wt).exists():
            log.error("Failed to create worktree for %s", branch)
            return False
        fsm._worktree = wt
    else:
        rc = _run(["git", "checkout", "-b", branch, base_ref], cwd=fsm._ws.repo_path)
        if not rc:
            log.error("Failed to create branch %s", branch)
            return False

    ws_state_dir = registry.state_dir(fsm._ws)
    ts = int(time.time())
    # mkdir(exist_ok=False) atomically claims a unique dir so concurrent workers that
    # start in the same second don't share an iter dir (and clobber each other's stream).
    n = 0
    while True:
        cand = ws_state_dir / (f"iter-{ts:04d}" if n == 0 else f"iter-{ts:04d}-{n}")
        try:
            cand.mkdir(parents=True, exist_ok=False)
            break
        except FileExistsError:
            n += 1
    fsm.iter_dir = cand

    (fsm.iter_dir / "run-tag").write_text("", encoding="utf-8")

    with _StateLock():
        s = _read_state()
        for it in s.get("items", []):
            if it.get("id") == item_id:
                it["status"] = "in_progress"
                it["branch"] = branch
                it["lastIter"] = fsm.iter_dir.name
        _write_state(s)

    item["branch"] = branch
    item["lastIter"] = fsm.iter_dir.name
    return True
