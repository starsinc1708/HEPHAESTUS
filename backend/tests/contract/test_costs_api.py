"""Contract tests for GET /api/v1/costs endpoint."""
from __future__ import annotations

import json


def test_get_costs_returns_expected_shape(client, tmp_path, monkeypatch):
    """Endpoint returns 200 with correct top-level keys."""
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    r = client.get("/api/v1/costs")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert isinstance(body["totalCostUsd"], float)
    assert isinstance(body["totalTokens"], int)
    assert isinstance(body["topTasks"], list)
    assert body["budgetUsd"] is None


def test_get_costs_zeros_on_empty_state(client, tmp_path, monkeypatch):
    """With no iter dirs and empty state, all values are zero."""
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    r = client.get("/api/v1/costs")
    assert r.status_code == 200
    body = r.json()
    assert body["totalCostUsd"] == 0.0
    assert body["totalTokens"] == 0
    assert body["topTasks"] == []


def test_get_costs_with_cost_data(client, tmp_path, monkeypatch):
    """Endpoint returns aggregated cost from iter dir JSONL."""
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    # Create an iter dir with cost data
    iter_dir = tmp_path / "iter-001"
    iter_dir.mkdir()
    jsonl = iter_dir / "events.jsonl"
    jsonl.write_text(
        json.dumps({"usage": {"input": 100, "output": 50}, "cost": 0.0123}) + "\n"
    )

    r = client.get("/api/v1/costs")
    assert r.status_code == 200
    body = r.json()
    assert body["totalCostUsd"] == 0.0123
    assert body["totalTokens"] == 150


def test_get_costs_with_budget_env(client, tmp_path, monkeypatch):
    """HEPHAESTUS_COST_BUDGET_USD env var is reflected in response."""
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    monkeypatch.setenv("HEPHAESTUS_COST_BUDGET_USD", "100.0")

    r = client.get("/api/v1/costs")
    assert r.status_code == 200
    assert r.json()["budgetUsd"] == 100.0


def test_get_costs_never_500_on_broken_state(client, tmp_path, monkeypatch):
    """Even with broken state, endpoint returns 200 with zeros."""
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    # Write corrupt state file
    state_file = tmp_path / "work-state.json"
    state_file.write_text("{{{corrupt")

    r = client.get("/api/v1/costs")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["totalCostUsd"] == 0.0
    assert body["totalTokens"] == 0


def test_get_costs_never_500_on_broken_jsonl(client, tmp_path, monkeypatch):
    """Even with corrupt JSONL files, endpoint returns 200."""
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    iter_dir = tmp_path / "iter-001"
    iter_dir.mkdir()
    (iter_dir / "events.jsonl").write_text("garbage\nnot json\n")

    r = client.get("/api/v1/costs")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["totalCostUsd"] == 0.0
    assert body["totalTokens"] == 0


def test_get_costs_with_top_tasks(client, tmp_path, monkeypatch):
    """Items with cost_usd appear in topTasks."""
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    items = [
        {"id": "t1", "title": "Expensive task", "status": "done", "cost_usd": 5.0},
        {"id": "t2", "title": "Cheap task", "status": "done", "cost_usd": 1.0},
    ]
    state_file = tmp_path / "work-state.json"
    state_file.write_text(json.dumps({"items": items}))

    r = client.get("/api/v1/costs")
    assert r.status_code == 200
    body = r.json()
    assert len(body["topTasks"]) == 2
    assert body["topTasks"][0]["id"] == "t1"
    assert body["topTasks"][1]["id"] == "t2"
