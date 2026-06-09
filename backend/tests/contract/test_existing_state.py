"""Contract test: existing work-state.json must round-trip through Pydantic Item model."""

from __future__ import annotations

import json
import os
import pathlib

import pytest

from app.models.domain import Item

# Look for real state file on Linux host path or local mirror
_STATE_CANDIDATES = [
    pathlib.Path("/home/starsinc/hephaestus-autonomous-loop/state/work-state.json"),
    pathlib.Path(os.environ.get("HEPHAESTUS_LOOP_HOME", ".")) / "state" / "work-state.json",
]


def _find_state_file() -> pathlib.Path | None:
    for p in _STATE_CANDIDATES:
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


@pytest.mark.skipif(not _find_state_file(), reason="work-state.json not available")
def test_existing_items_parse() -> None:
    state_path = _find_state_file()
    assert state_path is not None
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    items = raw.get("items", [])
    errors: list[str] = []
    for i, item_data in enumerate(items):
        try:
            Item.model_validate(item_data)
        except Exception as e:
            errors.append(f"item[{i}] id={item_data.get('id', '?')}: {e}")
    assert not errors, "Pydantic rejected items:\n" + "\n".join(errors)


def test_sample_item_roundtrip() -> None:
    """Even without real state file, verify the model works with sample data."""
    sample = {
        "id": "test-001",
        "title": "Test item",
        "status": "pending",
        "attempts": 0,
        "lastIter": None,
        "previousBranches": [],
        "selfReportedFailure": False,
        "mergeCommit": None,
        "mergedAt": None,
        "extra_future_field": "should not crash",
    }
    item = Item.model_validate(sample)
    assert item.id == "test-001"
    # extra='allow' preserves unknown fields
    dumped = item.model_dump(by_alias=True)
    assert "lastIter" in dumped
    assert "previousBranches" in dumped
    assert "selfReportedFailure" in dumped


def test_camelcase_aliases_in_dump() -> None:
    item = Item(
        id="x",
        title="y",
        status="done",
        last_iter="iter-0001",
        previous_branches=["auto/x-abc"],
        self_reported_failure=True,
        merge_commit="sha123",
        merged_at="2026-01-01T00:00:00Z",
    )
    dumped = item.model_dump(by_alias=True)
    assert dumped["lastIter"] == "iter-0001"
    assert dumped["previousBranches"] == ["auto/x-abc"]
    assert dumped["selfReportedFailure"] is True
    assert dumped["mergeCommit"] == "sha123"
    assert dumped["mergedAt"] is not None


def test_stage2_fields_default_and_alias() -> None:
    """Stage 2 additions parse from old state (defaults) and dump camelCase."""
    old = {"id": "x", "title": "y", "status": "pending"}
    item = Item.model_validate(old)
    assert item.depends_on == []
    assert item.blocks == []
    assert item.order_index == 0
    assert item.conflict_group is None
    assert item.epic_id is None
    assert item.parent is None
    assert item.validation is None
    assert item.result_summary == ""
    assert item.diff_ref is None
    assert item.workspace_id is None
    dumped = item.model_dump(by_alias=True)
    assert dumped["dependsOn"] == []
    assert dumped["orderIndex"] == 0
    assert dumped["conflictGroup"] is None
    assert dumped["epicId"] is None
    assert dumped["resultSummary"] == ""
    assert dumped["diffRef"] is None
    assert dumped["workspaceId"] is None


def test_stage2_fields_populate_by_alias() -> None:
    """camelCase JSON from frontend populates snake_case fields."""
    data = {
        "id": "a", "title": "t", "status": "pending",
        "dependsOn": ["b"], "orderIndex": 3, "conflictGroup": "cg-deadbeef",
        "epicId": "e1", "parent": "e1", "resultSummary": "done it", "diffRef": "iter-0007/diff.patch",
        "workspaceId": "9f3a1c20e4b57d61",
    }
    item = Item.model_validate(data)
    assert item.depends_on == ["b"]
    assert item.order_index == 3
    assert item.conflict_group == "cg-deadbeef"
    assert item.epic_id == "e1"
    assert item.result_summary == "done it"
