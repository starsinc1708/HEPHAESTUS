"""Contract tests for the Ideas API (Epic 4 B2)."""
from __future__ import annotations

_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


def _make_fake_ws(tmp_path):
    """Return a minimal workspace-shaped object."""
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
    )


def test_generate_ideas_returns_job_id(client, tmp_path, monkeypatch):
    """generate now returns {ok, jobId, kind} instead of {ok, ideas:[...]}."""
    import app.api.v1.ideas as ideas_api
    import app.core.state as state_mod
    from app.core.agent_jobs import AgentJob

    sd = tmp_path / "st"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    fake_ws = _make_fake_ws(tmp_path)
    monkeypatch.setattr(ideas_api, "active_workspace", lambda: fake_ws)

    fake_job = AgentJob(id="ajob-0001", kind="ideas", output_dir="ajob-0001")

    def _fake_start(kind, work):
        return fake_job

    monkeypatch.setattr(ideas_api, "start_agent_job", _fake_start)

    r = client.post(
        "/api/v1/ideas/generate",
        json={"categories": ["performance"]},
        headers=_CSRF,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["jobId"] == "ajob-0001"
    assert data["kind"] == "ideas"
    assert "ideas" not in data


def test_generate_ideas_no_categories_returns_job_id(client, tmp_path, monkeypatch):
    import app.api.v1.ideas as ideas_api
    import app.core.state as state_mod
    from app.core.agent_jobs import AgentJob

    sd = tmp_path / "st2"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    fake_ws = _make_fake_ws(tmp_path)
    monkeypatch.setattr(ideas_api, "active_workspace", lambda: fake_ws)

    fake_job = AgentJob(id="ajob-0002", kind="ideas", output_dir="ajob-0002")

    def _fake_start(kind, work):
        return fake_job

    monkeypatch.setattr(ideas_api, "start_agent_job", _fake_start)

    r = client.post("/api/v1/ideas/generate", json={}, headers=_CSRF)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["jobId"] == "ajob-0002"


def test_generate_ideas_no_workspace_returns_409(client, monkeypatch):
    import app.api.v1.ideas as ideas_api

    def _boom():
        raise ideas_api.NoActiveWorkspace()

    monkeypatch.setattr(ideas_api, "active_workspace", _boom)
    r = client.post("/api/v1/ideas/generate", json={}, headers=_CSRF)
    assert r.status_code == 409
    assert r.json()["ok"] is False


def test_list_ideas_empty(client, tmp_path, monkeypatch):
    import app.core.state as state_mod

    sd = tmp_path / "st3"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.get("/api/v1/ideas")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["ideas"] == []


def test_list_ideas_with_seeded_data(client, tmp_path, monkeypatch):
    import app.core.state as state_mod
    from app.services.ideas import Idea, IdeaStore

    sd = tmp_path / "st4"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    IdeaStore().put(Idea(id="idea-seed", title="Seeded Idea", proposal="p"))

    r = client.get("/api/v1/ideas")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert any(i["id"] == "idea-seed" for i in data["ideas"])


def test_import_ideas_adds_to_queue(client, tmp_path, monkeypatch):
    import app.api.v1.ideas as ideas_api
    import app.core.state as state_mod

    sd = tmp_path / "st5"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    def _fake_import(ids):
        return {"added": ids}

    monkeypatch.setattr(ideas_api, "import_ideas", _fake_import)

    r = client.post(
        "/api/v1/ideas/import",
        json={"ids": ["idea-abc", "idea-def"]},
        headers=_CSRF,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert set(data["added"]) == {"idea-abc", "idea-def"}


def test_import_ideas_integration(client, tmp_path, monkeypatch):
    """End-to-end: seed an idea, import it, check it appears in the queue."""
    import app.core.state as state_mod
    from app.core.state import _read_state
    from app.services.ideas import Idea, IdeaStore

    sd = tmp_path / "st6"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    idea = Idea(
        id="idea-e2e",
        title="Improve logging",
        proposal="Add structured logging throughout the app",
        rationale="Easier debugging",
        category="quality",
        severity="medium",
        touches=["app/main.py"],
    )
    IdeaStore().put(idea)

    r = client.post(
        "/api/v1/ideas/import",
        json={"ids": ["idea-e2e"]},
        headers=_CSRF,
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "idea-e2e" in r.json()["added"]

    items = _read_state()["items"]
    assert any(i.get("id") == "idea-e2e" for i in items)
    assert any(i.get("source") == "ideas" for i in items)
