"""Unit tests for queue._reorder + _queue_move_top over task_graph (cross-platform)."""
from __future__ import annotations

import json
import pathlib

import pytest


def _seed(state_dir: pathlib.Path, items: list[dict]) -> None:
    (state_dir / "work-state.json").write_text(json.dumps({"items": items}))


def test_reorder_ok(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_state_dir, raising=False)
    from app.core.queue import _reorder
    _seed(tmp_state_dir, [
        {"id": "A", "title": "A", "status": "pending", "dependsOn": [], "touches": ["a.py"], "orderIndex": 0},
        {"id": "B", "title": "B", "status": "pending", "dependsOn": [], "touches": ["b.py"], "orderIndex": 1},
    ])
    res = _reorder(["B", "A"])
    assert res["ok"] is True
    assert res["order"] == ["B", "A"]
    s = json.loads((tmp_state_dir / "work-state.json").read_text())
    by_id = {it["id"]: it for it in s["items"]}
    assert by_id["B"]["orderIndex"] == 0
    assert by_id["A"]["orderIndex"] == 1


def test_reorder_breaks_dependency(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_state_dir, raising=False)
    from app.core.queue import _reorder
    _seed(tmp_state_dir, [
        {"id": "A", "title": "A", "status": "pending", "dependsOn": [], "touches": ["a.py"], "orderIndex": 0},
        {"id": "B", "title": "B", "status": "pending", "dependsOn": ["A"], "touches": ["b.py"], "orderIndex": 1},
    ])
    res = _reorder(["B", "A"])
    assert res["ok"] is False
    assert "breaks dependency A before B" in res["error"]


def test_move_top_blocked_by_dependency(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_state_dir, raising=False)
    from app.core.queue import _queue_move_top
    _seed(tmp_state_dir, [
        {"id": "A", "title": "A", "status": "pending", "dependsOn": [], "touches": ["a.py"], "orderIndex": 0},
        {"id": "B", "title": "B", "status": "pending", "dependsOn": ["A"], "touches": ["b.py"], "orderIndex": 1},
    ])
    res = _queue_move_top("B")
    assert res["ok"] is False
    assert "breaks dependency" in res["error"]


def test_move_top_ok(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_state_dir, raising=False)
    from app.core.queue import _queue_move_top
    _seed(tmp_state_dir, [
        {"id": "A", "title": "A", "status": "pending", "dependsOn": [], "touches": ["a.py"], "orderIndex": 0},
        {"id": "B", "title": "B", "status": "pending", "dependsOn": [], "touches": ["b.py"], "orderIndex": 1},
    ])
    res = _queue_move_top("B")
    assert res["ok"] is True
    s = json.loads((tmp_state_dir / "work-state.json").read_text())
    assert s["items"][0]["id"] == "B"
