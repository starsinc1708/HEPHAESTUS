"""Contract tests for PATCH /api/v1/tasks/{id}/reorder."""
from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient


def _seed(state_dir: pathlib.Path, items: list[dict]) -> None:
    (state_dir / "work-state.json").write_text(json.dumps({"items": items}))


@pytest.fixture
def reorder_client(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_state_dir, raising=False)
    from app.main import app
    return TestClient(app)


CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


def test_reorder_ok(reorder_client, tmp_state_dir) -> None:
    _seed(tmp_state_dir, [
        {"id": "A", "title": "A", "status": "pending", "dependsOn": [], "touches": ["a.py"], "orderIndex": 0},
        {"id": "B", "title": "B", "status": "pending", "dependsOn": [], "touches": ["b.py"], "orderIndex": 1},
    ])
    r = reorder_client.patch("/api/v1/tasks/B/reorder", json={"order": ["B", "A"]}, headers=CSRF)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["order"] == ["B", "A"]


def test_reorder_breaks_dependency(reorder_client, tmp_state_dir) -> None:
    _seed(tmp_state_dir, [
        {"id": "A", "title": "A", "status": "pending", "dependsOn": [], "touches": ["a.py"], "orderIndex": 0},
        {"id": "B", "title": "B", "status": "pending", "dependsOn": ["A"], "touches": ["b.py"], "orderIndex": 1},
    ])
    r = reorder_client.patch("/api/v1/tasks/B/reorder", json={"order": ["B", "A"]}, headers=CSRF)
    assert r.status_code == 400
    assert "breaks dependency" in r.json()["error"]


def test_reorder_conflict_order(reorder_client, tmp_state_dir) -> None:
    _seed(tmp_state_dir, [
        {"id": "A", "title": "A", "status": "pending", "dependsOn": [], "touches": ["src/x.py"], "orderIndex": 0},
        {"id": "B", "title": "B", "status": "pending", "dependsOn": [], "touches": ["src/x.py"], "orderIndex": 1},
    ])
    r = reorder_client.patch("/api/v1/tasks/A/reorder", json={"order": ["B", "A"]}, headers=CSRF)
    assert r.status_code == 400
    assert "conflict order" in r.json()["error"]
