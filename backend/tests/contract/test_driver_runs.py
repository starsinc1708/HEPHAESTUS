"""FEAT-005: GET /api/driver/runs — finished-run history, newest first, paginated."""

from __future__ import annotations

import pathlib

import app.core.state as state_mod
from app.core.run_summary import RunHistoryStore, RunSummary


def _seed_history(sd: pathlib.Path, n: int) -> None:
    sd.mkdir(parents=True, exist_ok=True)
    hist = RunHistoryStore()
    for i in range(n):
        hist.archive(RunSummary(run_mode="ralph", items_done=1, cost_usd=float(i)))


def test_runs_empty_when_no_history(tmp_path, monkeypatch, client) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path / "state")
    r = client.get("/api/driver/runs")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["runs"] == []
    assert body["total"] == 0


def test_runs_returns_newest_first_with_meta(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    _seed_history(sd, 3)  # cost 0,1,2 archived in order

    r = client.get("/api/driver/runs")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    # Newest first → the last archived (cost 2.0) leads.
    assert [run["costUsd"] for run in body["runs"]] == [2.0, 1.0, 0.0]
    assert "endedAtMs" in body["runs"][0]  # camelCase payload


def test_runs_offset_limit_window(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    _seed_history(sd, 5)  # newest-first costs: 4,3,2,1,0

    r = client.get("/api/driver/runs?offset=1&limit=2")
    assert r.status_code == 200
    body = r.json()
    assert [run["costUsd"] for run in body["runs"]] == [3.0, 2.0]
    assert body["total"] == 5
    assert body["offset"] == 1
    assert body["limit"] == 2


def test_runs_rejects_out_of_contract_params(tmp_path, monkeypatch, client) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path / "state")
    assert client.get("/api/driver/runs?offset=-1").status_code == 422
    assert client.get("/api/driver/runs?limit=99999").status_code == 422
