"""Request body models for API endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class QueueAddRequest(BaseModel):
    id: str | None = None
    title: str | None = None
    proposal: str = ""
    why: str = ""
    acceptance: str = ""
    touches: list[str] = []


class DriverStartRequest(BaseModel):
    maxIter: int | None = None
    tierReview: bool | None = None
    primaryAgent: str | None = None
    fallbackAgent: str | None = None
    # C4: Ralph run-mode parameters
    runMode: str | None = None
    costBudgetUsd: float | None = None
    wallclockSec: int | None = None
    maxConsecFail: int | None = None


class StateCleanupRequest(BaseModel):
    kinds: list[str] | None = None
    reset_orphan_in_progress: bool = False


class ConfigPresetRequest(BaseModel):
    name: str


class ScanStartRequest(BaseModel):
    scanners: int | None = None
    reviewers: int | None = None
    scope: str | None = None


class ScanImportRequest(BaseModel):
    ids: list[str] = []


class BranchActionRequest(BaseModel):
    pass  # No body needed for branch actions


class CreateIssueRequest(BaseModel):
    title: str
    body: str = ""
    labels: list[str] = []


class UpdateIssueRequest(BaseModel):
    labels: list[str] | None = None
    state: str | None = None
    title: str | None = None
    body: str | None = None


class UpdatePromptRequest(BaseModel):
    content: str


class RenderPromptRequest(BaseModel):
    variables: dict[str, str] = {}


class AddCommentRequest(BaseModel):
    body: str


class DecomposeTaskRequest(BaseModel):
    title: str
    description: str = ""
    context: str = ""


class OnboardRequest(BaseModel):
    repoPath: str
    name: str | None = None


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = None
    baseBranch: str | None = None
    remote: str | None = None
    branchPrefix: str | None = None
    strictness: str | None = None
    agents: dict[str, Any] | None = None
    review: dict[str, Any] | None = None
    verifySource: str | None = None
    verifyCommandsOverride: list[str] | None = None
    verifyTimeoutSec: int | None = None
    autopush: bool | None = None
    engine: str | None = None
    engineEnv: dict[str, str] | None = None
    engineProfiles: list[dict[str, Any]] | None = None
    roleConnections: dict[str, Any] | None = None


class ReorderRequest(BaseModel):
    order: list[str]


class TaskRunRequest(BaseModel):
    ids: list[str] = []


class DepsPatchRequest(BaseModel):
    dependsOn: list[str] = []


class TagsPatchRequest(BaseModel):
    tags: list[str] = []


class MemoryWriteRequest(BaseModel):
    content: str
