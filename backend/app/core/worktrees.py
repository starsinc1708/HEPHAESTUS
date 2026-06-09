"""Worktree enumeration (sub-project #6) — every auto/* branch as a "worktree".

Reuses Epic-1 plumbing: GitService.branches() / merge_preflight(), state items,
and a single `git diff --name-only` per branch (cached) for changedFiles +
pairwise file-overlap ("conflictsWith"). NO new AI/merge logic lives here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from app.core.git import GitService
from app.core.helpers import _run
from app.core.state import _read_state
from app.models.validation import MergePreflightResponse

if TYPE_CHECKING:
    from app.models.workspace import RepoProfile


class WorktreeTask(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    status: str


class ConflictRef(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    branch: str
    task: WorktreeTask | None = None
    files: list[str] = Field(default_factory=list)


class Worktree(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    branch: str
    task: WorktreeTask | None = None
    changed_files: list[str] = Field(default_factory=list, alias="changedFiles")
    changed_count: int = Field(0, alias="changedCount")
    preflight: MergePreflightResponse
    conflicts_with: list[ConflictRef] = Field(default_factory=list, alias="conflictsWith")


def _branch_task_map() -> dict[str, WorktreeTask]:
    """branch → WorktreeTask for every state item that links a branch. Read state
    ONCE per request (the spec's "cache within the request" principle) so the O(n²)
    overlap pass never re-reads work-state.json."""
    out: dict[str, WorktreeTask] = {}
    for it in _read_state().get("items", []):
        b = it.get("branch")
        if b:
            out[b] = WorktreeTask(
                id=str(it.get("id", "")),
                title=str(it.get("title", "")),
                status=str(it.get("status", "")),
            )
    return out


def _changed_files(ws: RepoProfile, branch: str) -> list[str]:
    """`git diff --name-only origin/base..branch` — never crashes (→ [] on failure)."""
    raw = _run(
        ["git", "diff", "--name-only", f"{ws.remote}/{ws.base_branch}..{branch}"],
        cwd=ws.repo_path,
        default="",
    )
    return [line for line in raw.splitlines() if line.strip()]


def list_worktrees(ws: RepoProfile) -> list[Worktree]:
    """Enumerate every auto/* branch as a Worktree linked to its task, with
    changedFiles, merge-preflight, and pairwise file-overlap ("conflictsWith").
    """
    gs = GitService(ws)
    branches = [b["name"] for b in gs.branches() if b.get("name")]

    # Cache the changedFiles set per branch — compute git diff ONCE, reuse for overlap.
    changed_sets: dict[str, set[str]] = {b: set(_changed_files(ws, b)) for b in branches}
    # Read work-state ONCE; the O(n²) overlap pass reuses this map (no re-reads).
    task_map = _branch_task_map()

    out: list[Worktree] = []
    for branch in branches:
        files_i = changed_sets[branch]
        conflicts: list[ConflictRef] = []
        for other in branches:
            if other == branch:
                continue
            shared = files_i & changed_sets[other]
            if shared:
                conflicts.append(
                    ConflictRef(branch=other, task=task_map.get(other), files=sorted(shared))
                )
        out.append(
            Worktree(
                branch=branch,
                task=task_map.get(branch),
                changed_files=sorted(files_i),
                changed_count=len(files_i),
                preflight=gs.merge_preflight(branch),
                conflicts_with=conflicts,
            )
        )
    return out
