"""Contract tests for the agent-jobs router (/api/v1/agent-jobs/*)."""
from __future__ import annotations

import pathlib

import app.core.state as state_mod

_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


# ---------------------------------------------------------------------------
# GET /api/v1/agent-jobs/{id}
# ---------------------------------------------------------------------------


def test_get_agent_job_returns_job(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    from app.core.agent_jobs import AgentJob, AgentJobStore

    store = AgentJobStore()
    job = AgentJob(
        id="ajob-0001",
        kind="map",
        status="done",
        result={"count": 3},
        output_dir="ajob-0001",
    )
    store.put(job)

    r = client.get("/api/v1/agent-jobs/ajob-0001")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["id"] == "ajob-0001"
    assert data["kind"] == "map"
    assert data["status"] == "done"


def test_get_agent_job_not_found(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    r = client.get("/api/v1/agent-jobs/ajob-9999")
    assert r.status_code == 404
    assert r.json()["ok"] is False


def test_get_agent_job_invalid_id(client, tmp_path, monkeypatch):
    """job_id that doesn't match ^ajob-\\d+$ → 400."""
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    r = client.get("/api/v1/agent-jobs/not-valid-id")
    assert r.status_code == 400
    assert r.json()["ok"] is False


# ---------------------------------------------------------------------------
# POST /api/v1/insights/rebuild-map → now returns jobId
# ---------------------------------------------------------------------------


def _make_fake_ws(tmp_path: pathlib.Path):
    import types

    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    agents = types.SimpleNamespace(
        primary=types.SimpleNamespace(provider="p", model="m", agent="primary"),
        planner=None,
    )
    return types.SimpleNamespace(
        id="ws-test",
        name="test",
        repo_path=str(repo),
        base_branch="main",
        remote="origin",
        branch_prefix="auto",
        agents=agents,
        engine="opencode",
        engine_env={},
        engine_profiles=[],
        memory_dir=".hephaestus/memory",
        verify_timeout_sec=120,
    )


def test_rebuild_map_returns_job_id(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    import app.api.v1.insights as ins_api
    from app.core.agent_jobs import AgentJob

    fake_ws = _make_fake_ws(tmp_path)
    monkeypatch.setattr(ins_api, "active_workspace", lambda: fake_ws)

    fake_job = AgentJob(id="ajob-0001", kind="map", output_dir="ajob-0001")

    def _fake_start_agent_job(kind, work):
        return fake_job

    monkeypatch.setattr(ins_api, "start_agent_job", _fake_start_agent_job)

    r = client.post("/api/v1/insights/rebuild-map", json={}, headers=_CSRF)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["jobId"] == "ajob-0001"
    assert data["kind"] == "map"
    # Must NOT have old "count" key
    assert "count" not in data


def test_rebuild_map_no_workspace_409(client, monkeypatch):
    import app.api.v1.insights as ins_api

    def _boom():
        raise ins_api.NoActiveWorkspace()

    monkeypatch.setattr(ins_api, "active_workspace", _boom)
    r = client.post("/api/v1/insights/rebuild-map", json={}, headers=_CSRF)
    assert r.status_code == 409
    assert r.json()["ok"] is False


# ---------------------------------------------------------------------------
# POST /api/v1/ideas/generate → now returns jobId
# ---------------------------------------------------------------------------


def test_generate_ideas_returns_job_id(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    import app.api.v1.ideas as ideas_api
    from app.core.agent_jobs import AgentJob

    fake_ws = _make_fake_ws(tmp_path)
    monkeypatch.setattr(ideas_api, "active_workspace", lambda: fake_ws)

    fake_job = AgentJob(id="ajob-0002", kind="ideas", output_dir="ajob-0002")

    def _fake_start_agent_job(kind, work):
        return fake_job

    monkeypatch.setattr(ideas_api, "start_agent_job", _fake_start_agent_job)

    r = client.post(
        "/api/v1/ideas/generate",
        json={"categories": ["quality"]},
        headers=_CSRF,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["jobId"] == "ajob-0002"
    assert data["kind"] == "ideas"
    # Must NOT have old "ideas" key
    assert "ideas" not in data


def test_generate_ideas_no_workspace_409(client, monkeypatch):
    import app.api.v1.ideas as ideas_api

    def _boom():
        raise ideas_api.NoActiveWorkspace()

    monkeypatch.setattr(ideas_api, "active_workspace", _boom)
    r = client.post("/api/v1/ideas/generate", json={}, headers=_CSRF)
    assert r.status_code == 409
