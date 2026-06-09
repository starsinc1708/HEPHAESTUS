"""Auto-driver #3 — driver pause/resume controls + extended status payload."""

from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

import app.api.v1.loop as loop_mod
import app.core.driver as drv
import app.core.state as state_mod
from app.core.process import ProcState

_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


def _seed(sd: pathlib.Path, items: list[dict]) -> None:
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "work-state.json").write_text(json.dumps({"items": items}), encoding="utf-8")


def test_pause_sets_paused_and_soft_stops(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "a", "status": "queued"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    soft_calls: list[bool] = []
    monkeypatch.setattr(loop_mod, "_stop_loop_soft", lambda: soft_calls.append(True) or {"ok": True})

    r = client.post("/api/driver/pause", headers=_CSRF)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["paused"] is True
    assert soft_calls == [True]
    assert drv.driver_paused() is True


def test_resume_clears_paused_and_reconciles(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "a", "status": "queued"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    drv.set_driver_paused(True)

    monkeypatch.setattr(drv.pm, "status", lambda name: SimpleNamespace(state=ProcState.IDLE))
    started: list[bool] = []
    monkeypatch.setattr(drv, "_start_loop", lambda opts: started.append(True) or {"ok": True})

    r = client.post("/api/driver/resume", headers=_CSRF)
    assert r.status_code == 200
    body = r.json()
    assert body["paused"] is False
    assert drv.driver_paused() is False
    assert started == [True]  # reconcile started the loop (runnable + unpaused + stopped)


def test_pause_persist_failure_returns_ok_false_without_crashing(
    tmp_path, monkeypatch, client
) -> None:
    """If the paused flag can't be persisted (permission/disk), /pause must NOT report
    ok:true (which would let the loop auto-start after a restart, contradicting the pause)
    — and must never 500. The soft-stop is still attempted best-effort."""
    sd = tmp_path / "state"
    _seed(sd, [{"id": "a", "status": "queued"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    def _boom(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise OSError("disk full")

    monkeypatch.setattr(state_mod, "_atomic_write", _boom)

    soft_calls: list[bool] = []
    monkeypatch.setattr(loop_mod, "_stop_loop_soft", lambda: soft_calls.append(True) or {"ok": True})

    r = client.post("/api/driver/pause", headers=_CSRF)
    assert r.status_code == 200  # never a 500
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "could not persist paused flag"
    assert body["paused"] is True
    assert soft_calls == [True]  # soft-stop still attempted best-effort


def test_status_includes_paused_and_counts(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    _seed(sd, [
        {"id": "q1", "status": "queued"},
        {"id": "q2", "status": "queued"},
        {"id": "ip", "status": "in_progress"},
        {"id": "p", "status": "pending"},
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.get("/api/driver/status")
    assert r.status_code == 200
    data = r.json()
    # existing keys preserved
    assert "process" in data
    assert "tmux" in data
    assert "runSummary" in data
    # new keys
    assert data["paused"] is False
    assert data["queued"] == 2
    assert data["inProgress"] == 1
