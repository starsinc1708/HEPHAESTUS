"""Contract tests for GET /api/v1/system/health — enhanced system health endpoint."""
from __future__ import annotations

import json
import pathlib
import shutil
from collections import namedtuple

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_Usage = namedtuple("_Usage", ["total", "used", "free"])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_system_health_returns_all_fields(client: TestClient) -> None:
    """Response must contain ok, diskFreeGb, diskWarn, clis, stateOk."""
    r = client.get("/api/v1/system/health")
    assert r.status_code == 200
    data = r.json()
    for key in ("ok", "diskFreeGb", "diskWarn", "clis", "stateOk"):
        assert key in data, f"missing key: {key}"
    # clis must contain all four CLI names
    for cli in ("git", "opencode", "claude", "codex"):
        assert cli in data["clis"], f"missing cli key: {cli}"
        assert isinstance(data["clis"][cli], bool)
    # scalar types
    assert isinstance(data["ok"], bool)
    assert isinstance(data["diskFreeGb"], (int, float))
    assert isinstance(data["diskWarn"], bool)
    assert isinstance(data["stateOk"], bool)


def test_system_health_disk_warn_when_low(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """diskWarn should be True when free space is below HEPHAESTUS_DISK_WARN_GB threshold."""
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda p: _Usage(100_000_000_000, 99_500_000_000, 500_000_000),
    )
    # Default threshold is 1 GB, 500 MB < 1 GB → warn
    r = client.get("/api/v1/system/health")
    data = r.json()
    assert data["diskWarn"] is True
    assert data["diskFreeGb"] < 1.0


def test_system_health_disk_warn_false_when_plenty(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """diskWarn should be False when free space is above threshold."""
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda p: _Usage(500_000_000_000, 100_000_000_000, 400_000_000_000),
    )
    r = client.get("/api/v1/system/health")
    data = r.json()
    assert data["diskWarn"] is False
    assert data["diskFreeGb"] > 1.0


def test_system_health_never_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even if disk_usage raises, endpoint returns 200 with ok=False."""
    monkeypatch.setattr(shutil, "disk_usage", lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
    r = client.get("/api/v1/system/health")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False


def test_system_health_clis_detection(client: TestClient) -> None:
    """clis dict must have all 4 entries as booleans."""
    r = client.get("/api/v1/system/health")
    data = r.json()
    assert set(data["clis"].keys()) == {"git", "opencode", "claude", "codex"}
    for cli_name, available in data["clis"].items():
        assert isinstance(available, bool), f"{cli_name} is not bool"


def _patch_state_dir(monkeypatch: pytest.MonkeyPatch, state_dir: pathlib.Path) -> None:
    """Patch STATE_DIR in both app.config and the health module (which imports it)."""
    import app.api.v1.health as health_mod
    import app.config as cfg

    monkeypatch.setattr(cfg, "STATE_DIR", state_dir)
    monkeypatch.setattr(health_mod, "STATE_DIR", state_dir)


def test_system_health_state_ok_when_valid(
    client: TestClient, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stateOk=True when work-state.json exists and is valid JSON."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "work-state.json").write_text(json.dumps({"items": []}))
    _patch_state_dir(monkeypatch, state_dir)
    r = client.get("/api/v1/system/health")
    data = r.json()
    assert data["stateOk"] is True


def test_system_health_state_ok_false_when_missing(
    client: TestClient, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stateOk=False when work-state.json does not exist."""
    state_dir = tmp_path / "empty_state"
    state_dir.mkdir()
    _patch_state_dir(monkeypatch, state_dir)
    r = client.get("/api/v1/system/health")
    data = r.json()
    assert data["stateOk"] is False


def test_system_health_state_ok_false_when_invalid_json(
    client: TestClient, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stateOk=False when work-state.json exists but contains invalid JSON."""
    state_dir = tmp_path / "bad_state"
    state_dir.mkdir()
    (state_dir / "work-state.json").write_text("{not valid json!!!")
    _patch_state_dir(monkeypatch, state_dir)
    r = client.get("/api/v1/system/health")
    data = r.json()
    assert data["stateOk"] is False


def test_existing_health_endpoints_unchanged(client: TestClient) -> None:
    """Existing endpoints must remain untouched."""
    # /healthz — plain text "ok"
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.text == "ok"

    # /api/v1/health — minimal JSON health
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["status"] == "ok"
