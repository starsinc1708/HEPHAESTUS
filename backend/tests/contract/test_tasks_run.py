"""Auto-driver #3 — send-to-run / un-send task endpoints.

/run flips pending->queued (and reconciles the driver); bulk /run queues many;
/unqueue flips queued->pending. Bad statuses 409; missing 404.
"""

from __future__ import annotations

import json
import pathlib

import app.core.state as state_mod

_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


def _seed(sd: pathlib.Path, items: list[dict]) -> None:
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "work-state.json").write_text(json.dumps({"items": items}), encoding="utf-8")


def _status(sd: pathlib.Path, item_id: str) -> str:
    items = json.loads((sd / "work-state.json").read_text(encoding="utf-8"))["items"]
    return next(it["status"] for it in items if it["id"] == item_id)


def _patch_reconcile(monkeypatch) -> list[bool]:
    """Replace reconcile_driver where the tasks route imports it from (app.core.driver)."""
    calls: list[bool] = []
    import app.core.driver as drv
    monkeypatch.setattr(drv, "reconcile_driver", lambda: calls.append(True) or {"ok": True})
    return calls


def test_run_flips_pending_to_queued_and_reconciles(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "t1", "status": "pending"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    calls = _patch_reconcile(monkeypatch)

    r = client.post("/api/v1/tasks/t1/run", headers=_CSRF)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "status": "queued"}
    assert _status(sd, "t1") == "queued"
    assert calls == [True]  # reconcile fired after the mutation


def test_run_allows_needs_revision(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "t1", "status": "needs_revision"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    _patch_reconcile(monkeypatch)

    r = client.post("/api/v1/tasks/t1/run", headers=_CSRF)
    assert r.status_code == 200
    assert _status(sd, "t1") == "queued"


def test_run_409_on_bad_status(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "t1", "status": "done"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    _patch_reconcile(monkeypatch)

    r = client.post("/api/v1/tasks/t1/run", headers=_CSRF)
    assert r.status_code == 409
    assert r.json()["ok"] is False
    assert _status(sd, "t1") == "done"  # untouched


def test_run_404_on_missing(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    _seed(sd, [])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    _patch_reconcile(monkeypatch)

    r = client.post("/api/v1/tasks/nope/run", headers=_CSRF)
    assert r.status_code == 404
    assert r.json()["ok"] is False


def test_bulk_run_queues_multiple(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    _seed(sd, [
        {"id": "a", "status": "pending"},
        {"id": "b", "status": "pending"},
        {"id": "c", "status": "done"},  # ineligible -> skipped
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    calls = _patch_reconcile(monkeypatch)

    r = client.post("/api/v1/tasks/run", json={"ids": ["a", "b", "c"]}, headers=_CSRF)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert set(body["queued"]) == {"a", "b"}
    assert any(s["id"] == "c" for s in body["skipped"])
    assert _status(sd, "a") == "queued"
    assert _status(sd, "b") == "queued"
    assert _status(sd, "c") == "done"
    assert calls == [True]


def test_unqueue_flips_queued_to_pending(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "t1", "status": "queued"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.post("/api/v1/tasks/t1/unqueue", headers=_CSRF)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "status": "pending"}
    assert _status(sd, "t1") == "pending"


def test_unqueue_409_when_in_progress(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "t1", "status": "in_progress"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.post("/api/v1/tasks/t1/unqueue", headers=_CSRF)
    assert r.status_code == 409
    assert r.json()["ok"] is False
    assert _status(sd, "t1") == "in_progress"


def test_unqueue_404_on_missing(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    _seed(sd, [])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.post("/api/v1/tasks/nope/unqueue", headers=_CSRF)
    assert r.status_code == 404
    assert r.json()["ok"] is False
