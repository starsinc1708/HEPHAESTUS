"""Git operations helpers — worktree management and branch restoration."""

from __future__ import annotations

import contextlib
import shutil


def get_working_dir(worktree: str | None, repo_path: str) -> str:
    """Resolve the working directory for git/agent operations.

    Returns the worktree path if one is active, otherwise the main repo path.
    """
    if worktree:
        return worktree
    return repo_path


def drop_worktree(worktree: str, repo_path: str) -> None:
    """Remove a worktree from the filesystem and git registry.

    Uses ``git worktree remove --force`` followed by ``git worktree prune`` and
    a ``shutil.rmtree`` fallback for Windows handle issues.
    """
    from app.core.helpers import _run

    _run(["git", "worktree", "remove", "--force", worktree], cwd=repo_path)
    _run(["git", "worktree", "prune"], cwd=repo_path)
    with contextlib.suppress(Exception):
        shutil.rmtree(worktree, ignore_errors=True)


def restore_base_branch(repo_path: str, base_branch: str) -> None:
    """Force-checkout ``base_branch`` in the main repo working tree.

    Used after sequential-mode iterations so a crash/failure never leaves the
    repo stranded on an ``auto/`` branch.  No-op if already on ``base_branch``.
    """
    from app.core.helpers import _run

    cur = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path).strip()
    if cur and cur != base_branch:
        _run(["git", "checkout", "-f", base_branch], cwd=repo_path)
