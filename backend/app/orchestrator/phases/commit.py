"""COMMIT phase — commit agent changes to the auto/ branch.

Body extracted from ``OrchestratorFSM._commit`` (ARCH-001). Behavior is
identical, including the REL-003 ``intermediate_results["commit"]`` persistence
used by crash recovery.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.orchestrator.fsm import OrchestratorFSM

log = logging.getLogger("hephaestus.orchestrator")


async def commit_phase(fsm: OrchestratorFSM, item: dict[str, Any]) -> bool:
    """Commit changes to the auto/ branch."""
    from app.core.helpers import _run

    if fsm._ws is None:
        return False

    branch = item.get("branch")
    if not branch:
        return False

    repo = fsm._get_repo()  # worktree in parallel mode, else the main checkout
    ahead = _run(
        ["git", "rev-list", "--count", f"{fsm._ws.remote}/{fsm._ws.base_branch}..{branch}"],
        cwd=repo,
    )
    if ahead and ahead.strip() != "0":
        log.info("Agent already committed — skipping git add+commit")
        head_sha = _run(["git", "rev-parse", "--short", "HEAD"], cwd=repo)
        item["commit"] = head_sha
        return True

    _run(["git", "add", "-A"], cwd=repo)

    diff = _run(["git", "diff", "--cached", "--stat"], cwd=repo)
    if not diff:
        log.warning("No changes to commit")
        return False

    msg = f"iter: {item.get('title', '?')} ({item.get('id', '?')})"
    _run(["git", "commit", "-m", msg], cwd=repo)

    head_sha = _run(["git", "rev-parse", "--short", "HEAD"], cwd=repo)
    item["commit"] = head_sha
    # REL-003: persist commit hash in checkpoint for crash recovery
    fsm._intermediate_results["commit"] = head_sha

    if fsm.iter_dir:
        (fsm.iter_dir / "commit-msg.txt").write_text(msg, encoding="utf-8")

    return True
