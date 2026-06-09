"""Integration tests for queue API endpoints (full lifecycle)."""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient


def _setup_state(state_dir: pathlib.Path, items: list[dict] | None = None, monkeypatch=None) -> None:
    """Helper: set up state dir with items."""
    if monkeypatch:
        import app.core.state as state_mod

        monkeypatch.setattr(state_mod, "STATE_DIR", state_dir)
    state_file = state_dir / "work-state.json"
    state_file.write_text(json.dumps({"items": items or []}))
    (state_dir / "decisions.log").write_text("")


def test_queue_add_via_api(client: TestClient, tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/queue/add creates a new item."""
    _setup_state(tmp_state_dir, monkeypatch=monkeypatch)
    resp = client.post(
        "/api/queue/add",
        json={"id": "api-001", "title": "API Test", "proposal": "test proposal"},
        headers={"Origin": "http://localhost:8766", "Host": "localhost:8766"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["id"] == "api-001"


def test_queue_move_top_via_api(
    client: TestClient, tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /api/queue/{id}/move-top reorders the queue."""
    items = [
        {"id": "a", "title": "A", "status": "pending", "attempts": 0},
        {"id": "b", "title": "B", "status": "pending", "attempts": 0},
    ]
    _setup_state(tmp_state_dir, items=items, monkeypatch=monkeypatch)
    resp = client.post(
        "/api/queue/b/move-top",
        headers={"Origin": "http://localhost:8766", "Host": "localhost:8766"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_queue_patch_via_api(client: TestClient, tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PATCH /api/queue/{id} updates item fields."""
    items = [{"id": "p-1", "title": "Original", "status": "pending", "attempts": 0}]
    _setup_state(tmp_state_dir, items=items, monkeypatch=monkeypatch)
    resp = client.patch(
        "/api/queue/p-1",
        json={"title": "Patched"},
        headers={"Origin": "http://localhost:8766", "Host": "localhost:8766"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_queue_delete_via_api(client: TestClient, tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DELETE /api/queue/{id} removes the item."""
    items = [{"id": "del-1", "title": "Delete Me", "status": "pending", "attempts": 0}]
    _setup_state(tmp_state_dir, items=items, monkeypatch=monkeypatch)
    resp = client.delete(
        "/api/queue/del-1",
        headers={"Origin": "http://localhost:8766", "Host": "localhost:8766"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_queue_requeue_via_api(
    client: TestClient, tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /api/queue/{id}/requeue resets item status."""
    items = [{"id": "rq-1", "title": "Failed", "status": "failed:verify", "attempts": 2}]
    _setup_state(tmp_state_dir, items=items, monkeypatch=monkeypatch)
    resp = client.post(
        "/api/queue/rq-1/requeue",
        headers={"Origin": "http://localhost:8766", "Host": "localhost:8766"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["was"] == "failed:verify"


def test_queue_full_lifecycle(client: TestClient, tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Full queue lifecycle: add → move-top → patch → requeue → delete."""
    _setup_state(tmp_state_dir, monkeypatch=monkeypatch)
    csrf = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}

    # Add
    resp = client.post("/api/queue/add", json={"id": "lc-1", "title": "Lifecycle"}, headers=csrf)
    assert resp.json()["ok"] is True

    # Add second for move-top
    client.post("/api/queue/add", json={"id": "lc-2", "title": "Second"}, headers=csrf)

    # Move top
    resp = client.post("/api/queue/lc-2/move-top", headers=csrf)
    assert resp.json()["ok"] is True

    # Patch
    resp = client.patch("/api/queue/lc-1", json={"title": "Updated"}, headers=csrf)
    assert resp.json()["ok"] is True

    # Requeue (need to make it failed first)
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_state_dir)
    state_file = tmp_state_dir / "work-state.json"
    data = json.loads(state_file.read_text())
    for it in data["items"]:
        if it["id"] == "lc-1":
            it["status"] = "failed:verify"
    state_file.write_text(json.dumps(data))

    resp = client.post("/api/queue/lc-1/requeue", headers=csrf)
    assert resp.json()["ok"] is True

    # Delete
    resp = client.delete("/api/queue/lc-1", headers=csrf)
    assert resp.json()["ok"] is True

    # Verify only lc-2 remains
    state_data = json.loads(state_file.read_text())
    assert len(state_data["items"]) == 1
    assert state_data["items"][0]["id"] == "lc-2"
