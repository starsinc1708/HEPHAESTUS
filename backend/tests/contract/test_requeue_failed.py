"""FEAT-004: POST /api/v1/tasks/requeue-failed flips only failed:* items."""
from __future__ import annotations

import json
import pathlib

import app.core.state as state_mod

_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


def _seed(sd: pathlib.Path, items: list[dict]) -> None:
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "work-state.json").write_text(json.dumps({"items": items}), encoding="utf-8")


def _load_items(sd: pathlib.Path) -> list[dict]:
    return json.loads((sd / "work-state.json").read_text(encoding="utf-8"))["items"]


def test_empty_queue_returns_zero(tmp_path: pathlib.Path, monkeypatch, client) -> None:
    sd = tmp_path / "st"
    _seed(sd, [])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.post("/api/v1/tasks/requeue-failed", headers=_CSRF)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["requeued"] == []
    assert data["count"] == 0


def test_only_failed_statuses_flipped(tmp_path: pathlib.Path, monkeypatch, client) -> None:
    sd = tmp_path / "st"
    _seed(sd, [
        {"id": "a", "status": "pending"},
        {"id": "b", "status": "done"},
        {"id": "c", "status": "failed:verify", "branch": "auto/c-abc"},
        {"id": "d", "status": "failed:commit", "branch": None},
        {"id": "e", "status": "in_progress"},
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.post("/api/v1/tasks/requeue-failed", headers=_CSRF)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["count"] == 2
    assert set(data["requeued"]) == {"c", "d"}

    items = {it["id"]: it for it in _load_items(sd)}
    # Non-failed statuses untouched
    assert items["a"]["status"] == "pending"
    assert items["b"]["status"] == "done"
    assert items["e"]["status"] == "in_progress"
    # Failed ones now pending
    assert items["c"]["status"] == "pending"
    assert items["d"]["status"] == "pending"


def test_no_failed_items_returns_zero(tmp_path: pathlib.Path, monkeypatch, client) -> None:
    sd = tmp_path / "st"
    _seed(sd, [
        {"id": "a", "status": "pending"},
        {"id": "b", "status": "done"},
        {"id": "c", "status": "in_progress"},
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.post("/api/v1/tasks/requeue-failed", headers=_CSRF)
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 0
    # Statuses unchanged
    items = _load_items(sd)
    assert all(it["status"] in ("pending", "done", "in_progress") for it in items)


def test_requeued_at_timestamp_set(tmp_path: pathlib.Path, monkeypatch, client) -> None:
    sd = tmp_path / "st"
    _seed(sd, [
        {"id": "f1", "status": "failed:verify"},
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.post("/api/v1/tasks/requeue-failed", headers=_CSRF)
    assert r.status_code == 200
    items = _load_items(sd)
    assert items[0]["status"] == "pending"
    assert "requeued_at" in items[0]
    assert items[0]["requeued_at"].endswith("Z")


def test_previous_branches_preserved(tmp_path: pathlib.Path, monkeypatch, client) -> None:
    sd = tmp_path / "st"
    _seed(sd, [
        {"id": "f1", "status": "failed:verify", "branch": "auto/f1-abc123"},
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.post("/api/v1/tasks/requeue-failed", headers=_CSRF)
    assert r.status_code == 200
    items = _load_items(sd)
    assert items[0]["branch"] is None
    assert items[0]["previousBranches"] == ["auto/f1-abc123"]
