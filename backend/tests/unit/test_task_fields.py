"""Task gains Stage 3 fields with camelCase aliases (umbrella §4.2)."""

from __future__ import annotations

from app.models.domain import Item


def test_task_new_fields_defaults():
    t = Item(id="x", title="t", status="pending")
    assert t.depends_on == []
    assert t.blocks == []
    assert t.order_index == 0
    assert t.validation is None
    assert t.result_summary == ""
    assert t.diff_ref is None
    assert t.workspace_id is None


def test_task_new_fields_camelcase_dump():
    t = Item(
        id="x", title="t", status="in_review",
        depends_on=["a"], order_index=3,
        validation={"gate": "pass"}, result_summary="did X", diff_ref="iter-0001/diff.patch",
        workspace_id="ws1",
    )
    d = t.model_dump(by_alias=True)
    assert d["dependsOn"] == ["a"]
    assert d["orderIndex"] == 3
    assert d["resultSummary"] == "did X"
    assert d["diffRef"] == "iter-0001/diff.patch"
    assert d["workspaceId"] == "ws1"
    assert d["validation"] == {"gate": "pass"}


def test_task_accepts_in_review_status():
    assert Item(id="x", title="t", status="in_review").status == "in_review"
