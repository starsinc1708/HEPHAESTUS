"""Auto-driver #3 — driver reconciler + persisted pause flag.

reconcile_driver() is the single source of truth for "should the loop be running":
start the loop iff there is something runnable AND not paused AND not already running.
"""

from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

import app.core.driver as drv
import app.core.state as state_mod
from app.core.process import ProcState


def _seed(sd: pathlib.Path, items: list[dict]) -> None:
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "work-state.json").write_text(json.dumps({"items": items}), encoding="utf-8")


# ---------- _has_runnable ----------


def test_has_runnable_true_for_queued(tmp_path, monkeypatch) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "a", "status": "queued"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    assert drv._has_runnable() is True


def test_has_runnable_true_for_in_progress(tmp_path, monkeypatch) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "a", "status": "in_progress"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    assert drv._has_runnable() is True


def test_has_runnable_false_for_pending_and_done(tmp_path, monkeypatch) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "a", "status": "pending"}, {"id": "b", "status": "done"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    assert drv._has_runnable() is False


def test_has_runnable_false_when_empty(tmp_path, monkeypatch) -> None:
    sd = tmp_path / "state"
    _seed(sd, [])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    assert drv._has_runnable() is False


# ---------- driver_paused / set_driver_paused ----------


def test_driver_paused_default_false_on_missing_file(tmp_path, monkeypatch) -> None:
    sd = tmp_path / "state"
    sd.mkdir(parents=True)
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    assert drv.driver_paused() is False


def test_set_driver_paused_round_trip(tmp_path, monkeypatch) -> None:
    sd = tmp_path / "state"
    sd.mkdir(parents=True)
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    drv.set_driver_paused(True)
    assert drv.driver_paused() is True
    drv.set_driver_paused(False)
    assert drv.driver_paused() is False


def test_driver_paused_corrupt_file_returns_false(tmp_path, monkeypatch) -> None:
    sd = tmp_path / "state"
    sd.mkdir(parents=True)
    (sd / "driver.json").write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    assert drv.driver_paused() is False


# ---------- reconcile_driver ----------


def _stub_pm_status(monkeypatch, running: bool) -> None:
    state = ProcState.RUNNING if running else ProcState.IDLE
    monkeypatch.setattr(drv.pm, "status", lambda name: SimpleNamespace(state=state))


def test_reconcile_starts_when_runnable_unpaused_stopped(tmp_path, monkeypatch) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "a", "status": "queued"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    _stub_pm_status(monkeypatch, running=False)

    calls: list[dict] = []
    monkeypatch.setattr(drv, "_start_loop", lambda opts: calls.append(opts) or {"ok": True})

    res = drv.reconcile_driver()
    assert res["ok"] is True
    assert len(calls) == 1  # _start_loop invoked exactly once


def test_reconcile_noop_when_paused(tmp_path, monkeypatch) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "a", "status": "queued"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    _stub_pm_status(monkeypatch, running=False)
    drv.set_driver_paused(True)

    calls: list[dict] = []
    monkeypatch.setattr(drv, "_start_loop", lambda opts: calls.append(opts) or {"ok": True})

    res = drv.reconcile_driver()
    assert not calls
    assert res["ok"] is True  # no-op is still ok


def test_reconcile_noop_when_already_running(tmp_path, monkeypatch) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "a", "status": "queued"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    _stub_pm_status(monkeypatch, running=True)

    calls: list[dict] = []
    monkeypatch.setattr(drv, "_start_loop", lambda opts: calls.append(opts) or {"ok": True})

    drv.reconcile_driver()
    assert not calls


def test_reconcile_noop_when_nothing_runnable(tmp_path, monkeypatch) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "a", "status": "pending"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    _stub_pm_status(monkeypatch, running=False)

    calls: list[dict] = []
    monkeypatch.setattr(drv, "_start_loop", lambda opts: calls.append(opts) or {"ok": True})

    drv.reconcile_driver()
    assert not calls


def test_reconcile_already_running_race_returns_ok(tmp_path, monkeypatch) -> None:
    """Race: pm.status reads not-running, but _start_loop's own check sees the loop already
    RUNNING and returns ok:false 'loop already running'. That IS the desired state, so
    reconcile must report ok:true (a no-op) — not surface ok:false to /resume."""
    sd = tmp_path / "state"
    _seed(sd, [{"id": "a", "status": "queued"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    _stub_pm_status(monkeypatch, running=False)  # not-running at the pre-check

    monkeypatch.setattr(
        drv, "_start_loop", lambda opts: {"ok": False, "error": "loop already running"}
    )

    res = drv.reconcile_driver()
    assert res["ok"] is True  # already-running collapses to a success no-op
