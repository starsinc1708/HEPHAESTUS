"""Contract tests for the Insights API (Epic 4 C2)."""

from __future__ import annotations

import types

_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


def _make_fake_ws(tmp_path):
    """Return a minimal workspace-shaped object."""
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / ".hephaestus" / "memory").mkdir(parents=True, exist_ok=True)
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


def test_ask_returns_ok_session_and_answer(client, tmp_path, monkeypatch):
    import app.api.v1.insights as ins_api
    import app.core.state as state_mod

    sd = tmp_path / "st"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    fake_ws = _make_fake_ws(tmp_path)
    monkeypatch.setattr(ins_api, "active_workspace", lambda: fake_ws)

    async def _fake_ask(ws, question, *, session_id, runner):
        return {
            "sessionId": "ins-abc123",
            "iterDir": "insights-0001",
            "answer": "It uses FastAPI",
            "modifiedFiles": [],
        }

    monkeypatch.setattr(ins_api, "ask", _fake_ask)

    r = client.post(
        "/api/v1/insights/ask",
        json={"question": "What web framework?"},
        headers=_CSRF,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["sessionId"] == "ins-abc123"
    assert data["iterDir"] == "insights-0001"
    assert "FastAPI" in data["answer"]


def test_ask_with_session_id(client, tmp_path, monkeypatch):
    import app.api.v1.insights as ins_api
    import app.core.state as state_mod

    sd = tmp_path / "st2"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    fake_ws = _make_fake_ws(tmp_path)
    monkeypatch.setattr(ins_api, "active_workspace", lambda: fake_ws)

    captured = {}

    async def _fake_ask(ws, question, *, session_id, runner):
        captured["session_id"] = session_id
        return {
            "sessionId": session_id or "ins-new",
            "iterDir": "insights-0002",
            "answer": "Follow-up answer",
            "modifiedFiles": [],
        }

    monkeypatch.setattr(ins_api, "ask", _fake_ask)

    r = client.post(
        "/api/v1/insights/ask",
        json={"question": "Follow up", "sessionId": "ins-existing"},
        headers=_CSRF,
    )
    assert r.status_code == 200
    assert captured["session_id"] == "ins-existing"


def test_ask_no_workspace_returns_409(client, monkeypatch):
    import app.api.v1.insights as ins_api

    def _boom():
        raise ins_api.NoActiveWorkspace()

    monkeypatch.setattr(ins_api, "active_workspace", _boom)
    r = client.post(
        "/api/v1/insights/ask",
        json={"question": "X"},
        headers=_CSRF,
    )
    assert r.status_code == 409
    assert r.json()["ok"] is False


def test_list_sessions_empty(client, tmp_path, monkeypatch):
    import app.core.state as state_mod

    sd = tmp_path / "st3"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.get("/api/v1/insights/sessions")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["sessions"] == []


def test_list_sessions_with_seeded_data(client, tmp_path, monkeypatch):
    import app.core.state as state_mod
    from app.services.insights import InsightsSession, InsightsStore

    sd = tmp_path / "st4"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    InsightsStore().put(
        InsightsSession(id="ins-seed", title="Seeded session")
    )

    r = client.get("/api/v1/insights/sessions")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert any(s["id"] == "ins-seed" for s in data["sessions"])


def test_get_session_by_id(client, tmp_path, monkeypatch):
    import app.core.state as state_mod
    from app.services.insights import InsightsSession, InsightsStore

    sd = tmp_path / "st5"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    InsightsStore().put(
        InsightsSession(id="ins-fetch", title="Fetchable session")
    )

    r = client.get("/api/v1/insights/sessions/ins-fetch")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["id"] == "ins-fetch"
    assert data["title"] == "Fetchable session"


def test_get_session_not_found(client, tmp_path, monkeypatch):
    import app.core.state as state_mod

    sd = tmp_path / "st6"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.get("/api/v1/insights/sessions/ins-ghost")
    assert r.status_code == 404
    assert r.json()["ok"] is False


def test_rebuild_map_returns_job_id(client, tmp_path, monkeypatch):
    """rebuild-map now returns {ok, jobId, kind} instead of {ok, count}."""
    import app.api.v1.insights as ins_api
    import app.core.state as state_mod
    from app.core.agent_jobs import AgentJob

    sd = tmp_path / "st7"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    fake_ws = _make_fake_ws(tmp_path)
    monkeypatch.setattr(ins_api, "active_workspace", lambda: fake_ws)

    fake_job = AgentJob(id="ajob-0001", kind="map", output_dir="ajob-0001")

    def _fake_start(kind, work):
        return fake_job

    monkeypatch.setattr(ins_api, "start_agent_job", _fake_start)

    r = client.post("/api/v1/insights/rebuild-map", json={}, headers=_CSRF)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["jobId"] == "ajob-0001"
    assert data["kind"] == "map"
    assert "count" not in data


def test_rebuild_map_no_workspace_returns_409(client, monkeypatch):
    import app.api.v1.insights as ins_api

    def _boom():
        raise ins_api.NoActiveWorkspace()

    monkeypatch.setattr(ins_api, "active_workspace", _boom)
    r = client.post("/api/v1/insights/rebuild-map", json={}, headers=_CSRF)
    assert r.status_code == 409
    assert r.json()["ok"] is False


def test_stream_invalid_iter_dir(client, tmp_path, monkeypatch):
    import app.core.state as state_mod

    sd = tmp_path / "st8"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.get("/api/v1/insights/../../etc/passwd/stream")
    assert r.status_code in (400, 404)


def test_stream_bad_iter_dir_pattern(client, tmp_path, monkeypatch):
    import app.core.state as state_mod

    sd = tmp_path / "st9"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.get("/api/v1/insights/merge-0001/stream")
    assert r.status_code == 400
