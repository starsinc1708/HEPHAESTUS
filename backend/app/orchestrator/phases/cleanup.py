"""CLEANUP phase — final per-item teardown after successful validation.

Body extracted from ``OrchestratorFSM._cleanup`` (ARCH-001). Behavior is
identical; the FSM method is now a thin delegate that forwards ``self`` here.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.orchestrator.fsm import OrchestratorFSM


async def cleanup_phase(fsm: OrchestratorFSM, item: dict[str, Any]) -> None:
    """Clean up after iteration."""
    from app.core.helpers import _run
    from app.core.workspaces import registry

    branch = item.get("branch")
    if branch and fsm._ws is not None and fsm._ws.autopush:
        _run(["git", "push", fsm._ws.remote, branch], cwd=fsm._get_repo())
    # Drop the isolated worktree (the branch stays for review/merge).
    fsm._drop_worktree()
    if fsm._ws is not None:
        cp_path = registry.state_dir(fsm._ws) / "fsm-checkpoint.json"
        with contextlib.suppress(Exception):
            cp_path.unlink(missing_ok=True)
    fsm.current_item = None
    fsm.iter_dir = None
