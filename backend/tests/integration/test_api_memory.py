"""Contract tests for memory routes."""
from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def memory_client(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import types

    import app.core.ws_shim as shim
    from app.models.workspace import AgentRef, AgentsConfig
    agents = AgentsConfig(primary=AgentRef(provider="p", model="m"), fallback=AgentRef(provider="p", model="m"))
    prof = types.SimpleNamespace(
        id="ws01", name="repo", repo_path=str(tmp_path), base_branch="main", remote="origin",
        branch_prefix="auto", memory_dir=".hephaestus/memory", agents=agents,
    )
    monkeypatch.setattr(shim, "get_active_profile", lambda: prof)
    from app.main import app
    return TestClient(app)


CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


def test_get_unknown_doc_400(memory_client) -> None:
    r = memory_client.get("/api/v1/workspaces/ws01/memory/nope")
    assert r.status_code == 400


def test_put_then_get_roundtrip(memory_client) -> None:
    r = memory_client.put(
        "/api/v1/workspaces/ws01/memory/conventions",
        json={"content": "# C\nuse tabs\n"},
        headers=CSRF,
    )
    assert r.status_code == 200 and r.json()["ok"] is True
    r2 = memory_client.get("/api/v1/workspaces/ws01/memory/conventions")
    assert r2.status_code == 200
    assert "use tabs" in r2.json()["content"]
