"""Contract tests for the goals API (B4)."""
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


def test_create_goal_returns_job_id(client, tmp_path, monkeypatch):
    """POST /goals now returns {ok, jobId, kind} (async agent-job), not taskIds."""
    import app.api.v1.goals as goals_mod
    import app.core.state as state_mod
    from app.core.agent_jobs import AgentJob

    sd = tmp_path / "stjob"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    fake_ws = _make_fake_ws(tmp_path)
    monkeypatch.setattr(goals_mod, "active_workspace", lambda: fake_ws)

    fake_job = AgentJob(id="ajob-0001", kind="decompose", output_dir="ajob-0001")
    monkeypatch.setattr(goals_mod, "start_agent_job", lambda kind, work: fake_job)

    r = client.post("/api/v1/goals", json={"title": "Add retries", "description": "retry on fail"},
                    headers=_CSRF)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["jobId"] == "ajob-0001"
    assert data["kind"] == "decompose"
    assert "taskIds" not in data


def test_list_goals(client, tmp_path, monkeypatch):
    import app.api.v1.goals as goals_mod
    import app.core.state as state_mod
    from app.core.goals import Goal, GoalStore

    sd = tmp_path / "st2"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    fake_ws = _make_fake_ws(tmp_path)
    monkeypatch.setattr(goals_mod, "active_workspace", lambda: fake_ws)

    async def _fake_plan(ws, goal, *, runner):
        return []

    monkeypatch.setattr(goals_mod, "plan_goal", _fake_plan)

    # Pre-seed a goal
    GoalStore().put(Goal(id="goal-seed", title="Seeded Goal"))

    r = client.get("/api/v1/goals")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert any(g["id"] == "goal-seed" for g in data["goals"])


def test_get_goal_by_id(client, tmp_path, monkeypatch):
    import app.core.state as state_mod
    from app.core.goals import Goal, GoalStore

    sd = tmp_path / "st3"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    GoalStore().put(Goal(id="goal-abc", title="Fetch me"))

    r = client.get("/api/v1/goals/goal-abc")
    assert r.status_code == 200
    assert r.json()["goal"]["title"] == "Fetch me"


def test_get_goal_not_found(client, tmp_path, monkeypatch):
    import app.core.state as state_mod

    sd = tmp_path / "st4"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.get("/api/v1/goals/nonexistent")
    assert r.status_code == 404
    assert r.json()["ok"] is False


def test_delete_goal_sets_abandoned(client, tmp_path, monkeypatch):
    import app.core.state as state_mod
    from app.core.goals import Goal, GoalStore

    sd = tmp_path / "st5"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    store = GoalStore()
    store.put(Goal(id="goal-del", title="Delete me"))

    r = client.delete("/api/v1/goals/goal-del", headers=_CSRF)
    assert r.status_code == 200
    assert r.json()["ok"] is True

    fetched = store.get("goal-del")
    assert fetched is not None
    assert fetched.status == "abandoned"


def test_delete_goal_not_found(client, tmp_path, monkeypatch):
    import app.core.state as state_mod

    sd = tmp_path / "st6"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.delete("/api/v1/goals/ghost", headers=_CSRF)
    assert r.status_code == 404
    assert r.json()["ok"] is False


def test_create_goal_no_workspace_returns_409(client, monkeypatch):
    import app.api.v1.goals as goals_mod

    def _boom():
        raise goals_mod.NoActiveWorkspace()

    monkeypatch.setattr(goals_mod, "active_workspace", _boom)
    r = client.post("/api/v1/goals", json={"title": "X"}, headers=_CSRF)
    assert r.status_code == 409
    assert r.json()["ok"] is False


def test_goal_templates(client):
    """FEAT-003: built-in presets are returned, each with a title + description."""
    r = client.get("/api/v1/goals/templates")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(body["templates"]) >= 3
    assert "api-endpoint" in {t["id"] for t in body["templates"]}
    assert all(t["title"] and t["description"] for t in body["templates"])


def test_templates_route_not_swallowed_by_goal_id(client, monkeypatch):
    """/goals/templates must resolve to the presets, NOT the /goals/{goal_id} path-param route
    (which would 404 it as an unknown goal)."""
    monkeypatch.setattr("app.core.goals.GoalStore.get", lambda self, gid: None)
    r = client.get("/api/v1/goals/templates")
    assert r.status_code == 200
    assert "templates" in r.json()


def _fake_goals(n):
    from app.core.goals import Goal

    return [
        Goal(id=f"goal-{i}", title=f"g{i}", description="", created_at="2026-01-01T00:00:00Z")
        for i in range(n)
    ]


def test_list_goals_returns_pagination_meta(client, monkeypatch):
    """PERF-003: list always carries total/offset/limit; default returns all."""
    monkeypatch.setattr("app.core.goals.GoalStore.list", lambda self: _fake_goals(3))
    r = client.get("/api/v1/goals")
    assert r.status_code == 200
    body = r.json()
    assert len(body["goals"]) == 3
    assert body["total"] == 3
    assert body["offset"] == 0
    assert body["limit"] >= 3


def test_list_goals_offset_limit_window(client, monkeypatch):
    """PERF-003: offset/limit slices the list while total stays the full count."""
    monkeypatch.setattr("app.core.goals.GoalStore.list", lambda self: _fake_goals(10))
    r = client.get("/api/v1/goals?offset=8&limit=5")
    assert r.status_code == 200
    body = r.json()
    # Past-end window is short (2 left), not an error.
    assert [g["id"] for g in body["goals"]] == ["goal-8", "goal-9"]
    assert body["total"] == 10
    assert body["offset"] == 8
    assert body["limit"] == 5


def test_list_goals_rejects_out_of_contract_params(client):
    """Negative offset / over-cap limit are rejected at the boundary (422), not coerced."""
    assert client.get("/api/v1/goals?offset=-1").status_code == 422
    assert client.get("/api/v1/goals?limit=99999").status_code == 422
