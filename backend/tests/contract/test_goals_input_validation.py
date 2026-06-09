"""SEC-008: Input validation on goal creation — contract tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}

# Boundary lengths
_MAX_TITLE = 200
_MAX_DESC = 10_000


def _fake_workspace(tmp_path, monkeypatch):
    """Patch active_workspace so create_goal proceeds past the workspace check."""
    import types

    import app.api.v1.goals as goals_mod

    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    agents = types.SimpleNamespace(
        primary=types.SimpleNamespace(provider="p", model="m", agent="primary"),
        planner=None,
    )
    fake_ws = types.SimpleNamespace(
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
    monkeypatch.setattr(goals_mod, "active_workspace", lambda: fake_ws)

    from app.core.agent_jobs import AgentJob

    fake_job = AgentJob(id="ajob-val", kind="decompose", output_dir="ajob-val")
    monkeypatch.setattr(goals_mod, "start_agent_job", lambda kind, work: fake_job)


@pytest.fixture
def c() -> TestClient:
    return TestClient(app)


# ── 1. Valid request at boundary lengths ──────────────────────────────────


def test_valid_request_at_boundaries(c, tmp_path, monkeypatch):
    _fake_workspace(tmp_path, monkeypatch)
    import app.core.state as state_mod

    sd = tmp_path / "st_val"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = c.post(
        "/api/v1/goals",
        json={
            "title": "x" * _MAX_TITLE,
            "description": "d" * _MAX_DESC,
            "maxTasks": 50,
        },
        headers=_CSRF,
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ── 2. Title exceeds 200 chars → 422 ─────────────────────────────────────


def test_title_exceeds_max(c, tmp_path, monkeypatch):
    _fake_workspace(tmp_path, monkeypatch)

    r = c.post(
        "/api/v1/goals",
        json={"title": "t" * (_MAX_TITLE + 1), "description": "ok"},
        headers=_CSRF,
    )
    assert r.status_code == 422


# ── 3. Description exceeds 10000 chars → 422 ──────────────────────────────


def test_description_exceeds_max(c, tmp_path, monkeypatch):
    _fake_workspace(tmp_path, monkeypatch)

    r = c.post(
        "/api/v1/goals",
        json={"title": "ok", "description": "d" * (_MAX_DESC + 1)},
        headers=_CSRF,
    )
    assert r.status_code == 422


# ── 4. max_tasks < 0 → 422 ───────────────────────────────────────────────


def test_max_tasks_negative(c, tmp_path, monkeypatch):
    _fake_workspace(tmp_path, monkeypatch)

    r = c.post(
        "/api/v1/goals",
        json={"title": "ok", "maxTasks": -1},
        headers=_CSRF,
    )
    assert r.status_code == 422


# ── 5. max_tasks > 100 → 422 ──────────────────────────────────────────────


def test_max_tasks_exceeds_100(c, tmp_path, monkeypatch):
    _fake_workspace(tmp_path, monkeypatch)

    r = c.post(
        "/api/v1/goals",
        json={"title": "ok", "maxTasks": 101},
        headers=_CSRF,
    )
    assert r.status_code == 422


# ── 6. max_tasks=0 (default, no cap) → success ────────────────────────────


def test_max_tasks_zero_default(c, tmp_path, monkeypatch):
    _fake_workspace(tmp_path, monkeypatch)
    import app.core.state as state_mod

    sd = tmp_path / "st_zero"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = c.post(
        "/api/v1/goals",
        json={"title": "A goal"},
        headers=_CSRF,
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ── 7. Empty body → 422 ──────────────────────────────────────────────────


def test_empty_body(c):
    r = c.post("/api/v1/goals", json={}, headers=_CSRF)
    assert r.status_code == 422
