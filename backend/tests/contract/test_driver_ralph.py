"""Contract: driver start with Ralph parameters + status runSummary (C4)."""

from __future__ import annotations

import pathlib
from types import SimpleNamespace

import app.core.driver as drv

_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


def test_driver_start_ralph_sets_env(tmp_git_repo: pathlib.Path, monkeypatch, client):
    """POST /api/driver/start with runMode/costBudgetUsd/wallclockSec → env has correct vars."""
    import app.core.workspaces as wsmod

    ws = wsmod.registry.create(str(tmp_git_repo))
    wsmod.registry.activate(ws.id)

    # Capture env passed to pm.start
    captured_env: dict[str, str] = {}

    def _fake_status(name):
        return SimpleNamespace(state=SimpleNamespace(value="stopped"))

    def _fake_start(name, cmd, *, cwd, env, output_path=None, timeout_sec=None):
        captured_env.update(env)
        return SimpleNamespace(pid=1234, children=[])

    monkeypatch.setattr(drv.pm, "status", _fake_status)
    monkeypatch.setattr(drv.pm, "start", _fake_start)

    r = client.post(
        "/api/driver/start",
        json={"runMode": "ralph", "costBudgetUsd": 2.5, "wallclockSec": 3600},
        headers=_CSRF,
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    assert captured_env.get("HEPHAESTUS_RUN_MODE") == "ralph"
    assert captured_env.get("HEPHAESTUS_COST_BUDGET_USD") == "2.5"
    assert captured_env.get("HEPHAESTUS_WALLCLOCK_SEC") == "3600"


def test_driver_start_max_consec_fail_sets_env(tmp_git_repo: pathlib.Path, monkeypatch, client):
    """maxConsecFail is threaded into HEPHAESTUS_MAX_CONSEC_FAIL."""
    import app.core.workspaces as wsmod

    ws = wsmod.registry.create(str(tmp_git_repo))
    wsmod.registry.activate(ws.id)

    captured_env: dict[str, str] = {}

    monkeypatch.setattr(
        drv.pm, "status",
        lambda name: SimpleNamespace(state=SimpleNamespace(value="stopped")),
    )
    monkeypatch.setattr(
        drv.pm, "start",
        lambda name, cmd, *, cwd, env, output_path=None, timeout_sec=None: (
            captured_env.update(env) or SimpleNamespace(pid=999, children=[])
        ),
    )

    r = client.post(
        "/api/driver/start",
        json={"maxConsecFail": 6},
        headers=_CSRF,
    )
    assert r.status_code == 200
    assert captured_env.get("HEPHAESTUS_MAX_CONSEC_FAIL") == "6"


def test_driver_status_includes_run_summary(tmp_path, monkeypatch, client):
    """GET /api/driver/status returns runSummary field when run-summary.json exists."""
    import app.core.state as state_mod
    from app.core.run_summary import RunSummary, RunSummaryStore

    sd = tmp_path / "state"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    # Seed a RunSummary
    summary = RunSummary(run_mode="ralph", cost_usd=1.5, items_done=3)
    RunSummaryStore().put(summary)

    r = client.get("/api/driver/status")
    assert r.status_code == 200
    data = r.json()
    assert "runSummary" in data
    rs = data["runSummary"]
    assert rs is not None
    assert rs["runMode"] == "ralph"
    assert abs(rs["costUsd"] - 1.5) < 1e-9
    assert rs["itemsDone"] == 3


def test_driver_status_run_summary_none_when_absent(tmp_path, monkeypatch, client):
    """GET /api/driver/status returns runSummary=null when no run-summary.json exists."""
    import app.core.state as state_mod

    sd = tmp_path / "state2"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.get("/api/driver/status")
    assert r.status_code == 200
    data = r.json()
    assert "runSummary" in data
    assert data["runSummary"] is None


def test_allowed_config_keys_contains_ralph_keys():
    """ALLOWED_CONFIG_KEYS must include all Ralph env vars."""
    from app.config import ALLOWED_CONFIG_KEYS

    assert "HEPHAESTUS_RUN_MODE" in ALLOWED_CONFIG_KEYS
    assert "HEPHAESTUS_COST_BUDGET_USD" in ALLOWED_CONFIG_KEYS
    assert "HEPHAESTUS_WALLCLOCK_SEC" in ALLOWED_CONFIG_KEYS
    assert "HEPHAESTUS_REPLENISH_MAX" in ALLOWED_CONFIG_KEYS


def test_driver_start_none_run_mode_no_env(tmp_git_repo: pathlib.Path, monkeypatch, client):
    """Not providing runMode → HEPHAESTUS_RUN_MODE not overridden in env (keeps config default)."""
    import app.core.workspaces as wsmod

    ws = wsmod.registry.create(str(tmp_git_repo))
    wsmod.registry.activate(ws.id)

    captured_env: dict[str, str] = {}

    monkeypatch.setattr(
        drv.pm, "status",
        lambda name: SimpleNamespace(state=SimpleNamespace(value="stopped")),
    )
    monkeypatch.setattr(
        drv.pm, "start",
        lambda name, cmd, *, cwd, env, output_path=None, timeout_sec=None: (
            captured_env.update(env) or SimpleNamespace(pid=555, children=[])
        ),
    )

    r = client.post("/api/driver/start", json={}, headers=_CSRF)
    assert r.status_code == 200
    # runMode not explicitly passed → env comes from _config_effective() default
    # (which may include HEPHAESTUS_RUN_MODE=queue if set in the effective config)
    # The key point: no crash, and if present it's the default "queue"
    if "HEPHAESTUS_RUN_MODE" in captured_env:
        assert captured_env["HEPHAESTUS_RUN_MODE"] == "queue"
