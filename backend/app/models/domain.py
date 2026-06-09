"""Domain models for HEPHAESTUS loop state."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.workspace import AgentRef


class Item(BaseModel):
    """A work item in the HEPHAESTUS loop queue.

    Uses extra='allow' so bash-side fields we haven't modeled yet don't crash parsing.
    Uses populate_by_name=True + by_alias=True to preserve camelCase JSON contract.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    title: str
    status: str  # NOT Literal — failed:X variants not enumerable
    attempts: int = 0
    proposal: str = ""
    why: str = ""
    acceptance: str = ""
    touches: list[str] = []
    branch: str | None = None
    last_iter: str | None = Field(None, alias="lastIter")
    previous_branches: list[str] = Field(default_factory=list, alias="previousBranches")
    commit: str | None = None
    plan_file: str = ""
    plan_section: str = ""
    wave: str = ""
    severity: str | None = None
    category: str | None = None
    source_scan: str | None = None
    self_reported_failure: bool = Field(False, alias="selfReportedFailure")
    requeued_at: str | None = Field(None, alias="requeuedAt")
    review: str | dict[str, Any] | None = None
    merge_commit: str | None = Field(None, alias="mergeCommit")
    merged_at: str | None = Field(None, alias="mergedAt")
    recovered_at: str | None = Field(None, alias="recoveredAt")
    merged_into: str | None = Field(None, alias="mergedInto")
    merge_sha: str | None = Field(None, alias="mergeSha")
    merge_resolution: str | None = Field(None, alias="mergeResolution")  # "auto"|"ai"|"manual"
    push: str | None = None
    agreement_count: int | None = Field(None, alias="agreementCount")
    source_issue: int | None = Field(None, alias="sourceIssue")

    # --- Stage 1 field reservations (D5/D10/D11 expansion points) ---
    workspace_id: str | None = Field(None, alias="workspaceId")
    depends_on: list[str] = Field(default_factory=list, alias="dependsOn")
    blocks: list[str] = Field(default_factory=list)
    order_index: int = Field(0, alias="orderIndex")
    epic_id: str | None = Field(None, alias="epicId")
    parent: str | None = None
    conflict_group: str | None = Field(None, alias="conflictGroup")
    validation: dict[str, Any] | None = None
    result_summary: str = Field("", alias="resultSummary")
    diff_ref: str | None = Field(None, alias="diffRef")

    # --- Epic 2: per-task model override + advisory complexity ---
    model_override: AgentRef | None = Field(None, alias="modelOverride")
    complexity: str | None = None

    # --- Tags ---
    tags: list[str] = Field(default_factory=list)
