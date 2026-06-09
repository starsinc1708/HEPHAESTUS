"""Integration tests for config API endpoints."""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient


def _setup_config(state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Helper: point config module at temp state dir."""
    import app.api.v1.config_route as route_mod
    import app.config as config_mod
    import app.core.state as state_mod

    config_override = state_dir / "config.json"
    monkeypatch.setattr(config_mod, "STATE_DIR", state_dir)
    monkeypatch.setattr(config_mod, "CONFIG_OVERRIDE", config_override)
    monkeypatch.setattr(state_mod, "STATE_DIR", state_dir)
    # Also patch the already-imported reference in config_route.py
    monkeypatch.setattr(route_mod, "CONFIG_OVERRIDE", config_override)
    (state_dir / "work-state.json").write_text(json.dumps({"items": []}))
    (state_dir / "decisions.log").write_text("")


def test_get_config_returns_200(
    client: TestClient, tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/config returns effective and overrides keys."""
    _setup_config(tmp_state_dir, monkeypatch)
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "effective" in data
    assert "overrides" in data
    # effective config should have known keys
    assert "HEPHAESTUS_REPO" in data["effective"]
    assert "HEPHAESTUS_BASE_BRANCH" in data["effective"]


def test_put_config_updates_override(
    client: TestClient, tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PUT /api/config persists config overrides."""
    _setup_config(tmp_state_dir, monkeypatch)
    csrf = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}
    resp = client.put(
        "/api/config",
        json={"HEPHAESTUS_MAX_ITER": "25"},
        headers=csrf,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["overrides"]["HEPHAESTUS_MAX_ITER"] == "25"

    # Verify it persists to disk
    config_file = tmp_state_dir / "config.json"
    assert config_file.exists()
    persisted = json.loads(config_file.read_text())
    assert persisted["HEPHAESTUS_MAX_ITER"] == "25"


def test_config_preset_standard(
    client: TestClient, tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /api/config/preset applies a named preset."""
    _setup_config(tmp_state_dir, monkeypatch)
    csrf = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}
    resp = client.post(
        "/api/config/preset",
        json={"name": "standard"},
        headers=csrf,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["preset"] == "standard"


def test_config_preset_unknown(
    client: TestClient, tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /api/config/preset with unknown name returns error."""
    _setup_config(tmp_state_dir, monkeypatch)
    csrf = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}
    resp = client.post(
        "/api/config/preset",
        json={"name": "nonexistent"},
        headers=csrf,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "unknown" in data["error"]


def test_config_preset_disabled(
    client: TestClient, tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /api/config/preset with 'disabled' sets TIER_REVIEW off."""
    _setup_config(tmp_state_dir, monkeypatch)
    csrf = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}
    resp = client.post(
        "/api/config/preset",
        json={"name": "disabled"},
        headers=csrf,
    )
    data = resp.json()
    assert data["ok"] is True
    assert data["applied"]["HEPHAESTUS_TIER_REVIEW"] == "off"


def test_get_config_after_put_includes_override(
    client: TestClient, tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/config after PUT reflects the override in effective config."""
    _setup_config(tmp_state_dir, monkeypatch)
    csrf = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}
    client.put("/api/config", json={"HEPHAESTUS_MAX_ITER": "99"}, headers=csrf)

    resp = client.get("/api/config")
    data = resp.json()
    assert data["effective"]["HEPHAESTUS_MAX_ITER"] == "99"
