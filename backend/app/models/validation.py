"""Pydantic models for the Stage 3 validation funnel and merge API.

LensVerdict / ValidationResult mirror umbrella §7; MergeRequest /
MergePreflightResponse mirror umbrella §5.4 / stage3 §4.5. camelCase JSON
contract via Field aliases (populate_by_name=True).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LensVerdict(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    lens: str          # correctness|tests|security|conventions|scope
    verdict: str       # approve|needs_revision|reject
    confidence: float
    reasoning: str


class ValidationResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    layer1: list[LensVerdict] = Field(default_factory=list)
    layer2_summary: list[dict[str, object]] = Field(default_factory=list, alias="layer2Summary")
    gate: str          # pass|needs_revision
    blocking: list[str] = Field(default_factory=list)
    revision: int = 0


class MergeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    push: bool = False
    ai_resolve: bool = Field(True, alias="aiResolve")
    auto_accept: bool = Field(False, alias="autoAccept")


class MergePreflightResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    clean_tree: bool = Field(..., alias="cleanTree")
    verify_green: bool = Field(..., alias="verifyGreen")
    # True when verify_green is False *because nothing ran* (no verify config + no test
    # files in the diff), as opposed to a real verify failure. Lets the UI say "tests
    # weren't run" instead of the misleading "verify not green". (honest gate)
    verify_unverified: bool = Field(False, alias="verifyUnverified")
    validation_passed: bool = Field(..., alias="validationPassed")
    # R11: merge forbidden while loop RUNNING — persistent, surfaced to the UI.
    loop_active: bool = Field(False, alias="loopActive")
    base_branch: str = Field(..., alias="baseBranch")
    conflicts: list[str] = Field(default_factory=list)
    ok: bool
