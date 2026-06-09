"""Unit tests for Goal model + GoalStore (B2)."""
from __future__ import annotations

import app.core.state as state
from app.core.goals import Goal, GoalStore


def test_goal_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    store = GoalStore()
    goal = Goal(id="goal-001", title="Add retries")
    store.put(goal)
    fetched = store.get("goal-001")
    assert fetched is not None
    assert fetched.title == "Add retries"
    assert fetched.status == "active"


def test_goal_store_list(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    store = GoalStore()
    store.put(Goal(id="g1", title="G1"))
    store.put(Goal(id="g2", title="G2"))
    all_goals = store.list()
    assert len(all_goals) == 2
    ids = {g.id for g in all_goals}
    assert ids == {"g1", "g2"}


def test_goal_store_active(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    store = GoalStore()
    store.put(Goal(id="g1", title="Active", status="active"))
    store.put(Goal(id="g2", title="Abandoned", status="abandoned"))
    active = store.active()
    assert len(active) == 1
    assert active[0].id == "g1"


def test_goal_store_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    store = GoalStore()
    assert store.get("nonexistent") is None


def test_goal_store_list_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    assert GoalStore().list() == []


def test_goal_store_put_update(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    store = GoalStore()
    goal = Goal(id="g1", title="Original")
    store.put(goal)
    goal.status = "abandoned"
    store.put(goal)
    fetched = store.get("g1")
    assert fetched is not None
    assert fetched.status == "abandoned"
    # Should not duplicate
    assert sum(1 for g in store.list() if g.id == "g1") == 1


def test_goal_camel_aliases(tmp_path, monkeypatch):
    """taskIds / createdAt / dryRounds aliases round-trip via model_dump(by_alias=True)."""
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    store = GoalStore()
    goal = Goal(id="g-a", title="T", task_ids=["a", "b"], created_at="2026-01-01T00:00:00Z",
                dry_rounds=2)
    store.put(goal)
    fetched = store.get("g-a")
    assert fetched is not None
    assert fetched.task_ids == ["a", "b"]
    assert fetched.created_at == "2026-01-01T00:00:00Z"
    assert fetched.dry_rounds == 2
