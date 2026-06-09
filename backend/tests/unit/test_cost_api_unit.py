"""Unit tests for _aggregate_cost() — cost aggregation logic."""
from __future__ import annotations

import json
from typing import Any

import pytest

from app.api.v1.costs import _aggregate_cost


def test_empty_state_returns_zeros(tmp_path, monkeypatch):
    """With no iter dirs and empty state, all values should be zero."""
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    result = _aggregate_cost()
    assert result["totalCostUsd"] == 0.0
    assert result["totalTokens"] == 0
    assert result["topTasks"] == []
    assert result["budgetUsd"] is None


def test_single_iter_dir_with_cost(tmp_path, monkeypatch):
    """A single iter dir with a JSONL file containing cost data."""
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    # Create an iter dir with a JSONL file containing cost data
    iter_dir = tmp_path / "iter-001"
    iter_dir.mkdir()
    jsonl = iter_dir / "events.jsonl"
    jsonl.write_text(
        json.dumps({"usage": {"input": 100, "output": 50}, "cost": 0.0123}) + "\n"
        + json.dumps({"usage": {"input": 200, "output": 75}, "cost": 0.0456}) + "\n"
    )

    result = _aggregate_cost()
    assert result["totalCostUsd"] == pytest.approx(0.0579, abs=1e-4)
    assert result["totalTokens"] == 425  # 100+50 + 200+75
    assert result["topTasks"] == []
    assert result["budgetUsd"] is None


def test_corrupt_jsonl_never_crashes(tmp_path, monkeypatch):
    """Corrupt JSONL lines should be skipped without crashing."""
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    iter_dir = tmp_path / "iter-001"
    iter_dir.mkdir()
    jsonl = iter_dir / "events.jsonl"
    jsonl.write_text(
        "not valid json\n"
        + json.dumps({"usage": {"input": 50, "output": 25}, "cost": 0.005}) + "\n"
        + "{broken json\n"
    )

    result = _aggregate_cost()
    # The valid line should still be counted
    assert result["totalCostUsd"] == pytest.approx(0.005, abs=1e-4)
    assert result["totalTokens"] == 75
    assert result["budgetUsd"] is None


def test_budget_from_env(tmp_path, monkeypatch):
    """HEPHAESTUS_COST_BUDGET_USD env var is reflected in budgetUsd."""
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    monkeypatch.setenv("HEPHAESTUS_COST_BUDGET_USD", "50.0")

    result = _aggregate_cost()
    assert result["budgetUsd"] == 50.0


def test_budget_zero_env(tmp_path, monkeypatch):
    """HEPHAESTUS_COST_BUDGET_USD=0 should result in None."""
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    monkeypatch.setenv("HEPHAESTUS_COST_BUDGET_USD", "0")

    result = _aggregate_cost()
    assert result["budgetUsd"] is None


def test_budget_empty_env(tmp_path, monkeypatch):
    """Unset HEPHAESTUS_COST_BUDGET_USD should result in None."""
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    monkeypatch.delenv("HEPHAESTUS_COST_BUDGET_USD", raising=False)

    result = _aggregate_cost()
    assert result["budgetUsd"] is None


def test_top_tasks_from_state(tmp_path, monkeypatch):
    """Items with cost_usd appear in topTasks sorted by cost descending."""
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    items: list[dict[str, Any]] = [
        {"id": "t1", "title": "Task 1", "status": "done", "cost_usd": 1.5},
        {"id": "t2", "title": "Task 2", "status": "done", "cost_usd": 3.2},
        {"id": "t3", "title": "Task 3", "status": "pending", "cost_usd": 0.8},
        {"id": "t4", "title": "Task 4", "status": "done"},  # no cost
    ]
    state_file = tmp_path / "work-state.json"
    state_file.write_text(json.dumps({"items": items}))

    result = _aggregate_cost()
    assert len(result["topTasks"]) == 3
    assert result["topTasks"][0]["id"] == "t2"  # highest cost first
    assert result["topTasks"][1]["id"] == "t1"
    assert result["topTasks"][2]["id"] == "t3"


def test_top_tasks_limited_to_10(tmp_path, monkeypatch):
    """At most 10 tasks are returned in topTasks."""
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    items: list[dict[str, Any]] = [
        {"id": f"t{i}", "title": f"Task {i}", "status": "done", "cost_usd": float(i)}
        for i in range(20)
    ]
    state_file = tmp_path / "work-state.json"
    state_file.write_text(json.dumps({"items": items}))

    result = _aggregate_cost()
    assert len(result["topTasks"]) == 10


def test_never_crashes_on_corrupt_state(tmp_path, monkeypatch):
    """Corrupt work-state.json should not crash _aggregate_cost()."""
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    # Clear LKG cache so corrupt state doesn't fall back to previous test data
    state_mod._LKG_STATE["value"] = None
    state_mod._LKG_STATE["ts"] = 0.0

    state_file = tmp_path / "work-state.json"
    state_file.write_text("this is not valid json")

    result = _aggregate_cost()
    assert result["totalCostUsd"] == 0.0
    assert result["totalTokens"] == 0
    assert result["topTasks"] == []
    assert result["budgetUsd"] is None


def test_never_crashes_on_missing_state(tmp_path, monkeypatch):
    """No work-state.json at all should not crash _aggregate_cost()."""
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    # Don't create work-state.json
    result = _aggregate_cost()
    assert result["totalCostUsd"] == 0.0
    assert result["totalTokens"] == 0
    assert result["topTasks"] == []
    assert result["budgetUsd"] is None
