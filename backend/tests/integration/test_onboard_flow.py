"""Integration: POST /api/v1/workspaces onboards a git repo (Profiler mocked)."""
from __future__ import annotations

import pathlib
import subprocess

import pytest
from fastapi.testclient import TestClient

_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


@pytest.fixture
def _patched_home(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HEPHAESTUS_HOME", str(tmp_path / "home"))
    import app.core.workspaces as wsmod

    monkeypatch.setattr(wsmod, "registry", wsmod.WorkspaceRegistry(home=tmp_path / "home"))
    import app.api.v1.workspaces as wsapi

    # Don't actually spawn a profiler process during the onboard test.
    monkeypatch.setattr(wsapi, "_start_profiler", lambda _ws_id, _repo: None)
    monkeypatch.setattr(wsapi, "registry", wsmod.registry)
    return tmp_path


def test_onboard_creates_profile(_patched_home: pathlib.Path) -> None:
    repo = _patched_home / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, timeout=30, check=True)

    from app.main import app

    client = TestClient(app)
    r = client.post("/api/v1/workspaces", json={"repoPath": str(repo), "name": "repo"}, headers=_CSRF)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    ws_id = data["workspace"]["id"]

    r2 = client.post(f"/api/v1/workspaces/{ws_id}/activate", headers=_CSRF)
    assert r2.json()["ok"] is True

    r3 = client.get("/api/v1/workspaces")
    assert r3.json()["activeId"] == ws_id


def test_onboard_rejects_non_git(_patched_home: pathlib.Path) -> None:
    plain = _patched_home / "plain"
    plain.mkdir()
    from app.main import app

    client = TestClient(app)
    r = client.post("/api/v1/workspaces", json={"repoPath": str(plain)}, headers=_CSRF)
    assert r.json()["ok"] is False
    assert "not a git repository" in r.json()["error"]
