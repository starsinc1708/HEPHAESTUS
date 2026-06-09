"""MergeJob domain model and related enums for Epic 1 AI-powered merge."""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class MergeJobStatus(StrEnum):
    RUNNING = "running"
    RESOLVING = "resolving"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    CONFLICT = "conflict"
    FAILED = "failed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class MergeDecision(StrEnum):
    AUTO_MERGED = "auto_merged"
    AI_MERGED = "ai_merged"
    NEEDS_HUMAN = "needs_human"
    FAILED = "failed"


class MergeJob(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    branch: str
    base_branch: str = Field(..., alias="baseBranch")
    status: MergeJobStatus
    decision: MergeDecision | None = None
    conflicts: list[str] = Field(default_factory=list)
    resolved_files: list[str] = Field(default_factory=list, alias="resolvedFiles")
    diff: str | None = None
    verify_ok: bool | None = Field(None, alias="verifyOk")
    error: str | None = None
    auto_accept: bool = Field(False, alias="autoAccept")
    push: bool = False
    worktree: str | None = None
    worktree_branch: str | None = Field(None, alias="worktreeBranch")
    base_sha: str | None = Field(None, alias="baseSha")
    item_id: str | None = Field(None, alias="itemId")
    created_at: str | None = Field(None, alias="createdAt")
    updated_at: str | None = Field(None, alias="updatedAt")
