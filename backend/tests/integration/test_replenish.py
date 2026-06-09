"""Integration test for replenish_goal (C2) — stub runner, no real agent CLI."""

from __future__ import annotations

import asyncio
import pathlib
import types

import app.core.state as state
from app.core.goals import Goal, GoalStore, replenish_goal


def _make_ws(repo_path: str) -> types.SimpleNamespace:
    agents = types.SimpleNamespace(
        primary=types.SimpleNamespace(provider="p", model="m", agent="primary"),
        planner=None,
    )
    return types.SimpleNamespace(
        id="ws-test",
        name="test",
        repo_path=repo_path,
        base_branch="main",
        remote="origin",
        branch_prefix="auto",
        agents=agents,
    )


class _PlanRunner:
    """Writes a PLAN block to output_path. decompose falls back to 1:1."""

    def __init__(self, tasks: list[dict]) -> None:
        import json
        self._block = "PLAN_BEGIN" + json.dumps({"tasks": tasks}) + "PLAN_END"

    async def run(
        self, ref: object, *, prompt_file: pathlib.Path, cwd: str,
        output_path: pathlib.Path, timeout_sec: int,
    ) -> object:
        output_path.write_text(self._block, encoding="utf-8")

        class R:
            exit_code = 0
            refused = False

        return R()


class _EmptyRunner:
    """Returns an empty plan."""

    async def run(
        self, ref: object, *, prompt_file: pathlib.Path, cwd: str,
        output_path: pathlib.Path, timeout_sec: int,
    ) -> object:
        output_path.write_text('PLAN_BEGIN{"tasks":[]}PLAN_END', encoding="utf-8")

        class R:
            exit_code = 0
            refused = False

        return R()


def _task(id_: str) -> dict:
    return {
        "id": id_,
        "title": f"Task {id_}",
        "proposal": f"do {id_}",
        "rationale": "r",
        "acceptance": "a",
        "touches": ["x.py"],
        "complexity": "simple",
    }


def test_replenish_non_empty_plan_enqueues_tasks(tmp_path, monkeypatch):
    sd = tmp_path / "st"
    sd.mkdir()
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)

    repo = tmp_path / "repo"
    repo.mkdir()
    ws = _make_ws(str(repo))
    goal = Goal(id="g1", title="My Goal")

    runner = _PlanRunner([_task("t1"), _task("t2")])
    n = asyncio.run(replenish_goal(ws, goal, runner=runner))

    assert n > 0

    from app.core.state import _read_state
    items = _read_state()["items"]
    ids = [it["id"] for it in items]
    assert "t1" in ids or "t2" in ids


def test_replenish_non_empty_resets_dry_rounds(tmp_path, monkeypatch):
    sd = tmp_path / "st2"
    sd.mkdir()
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)

    repo = tmp_path / "repo2"
    repo.mkdir()
    ws = _make_ws(str(repo))
    goal = Goal(id="g2", title="Goal2")
    goal.dry_rounds = 3  # pre-set

    runner = _PlanRunner([_task("u1")])
    asyncio.run(replenish_goal(ws, goal, runner=runner))

    assert goal.dry_rounds == 0
    # Also check it was persisted
    stored = GoalStore().get("g2")
    assert stored is not None and stored.dry_rounds == 0


def test_replenish_empty_plan_bumps_dry_rounds(tmp_path, monkeypatch):
    sd = tmp_path / "st3"
    sd.mkdir()
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)

    repo = tmp_path / "repo3"
    repo.mkdir()
    ws = _make_ws(str(repo))
    goal = Goal(id="g3", title="Goal3")

    n = asyncio.run(replenish_goal(ws, goal, runner=_EmptyRunner()))

    assert n == 0
    assert goal.dry_rounds == 1
    stored = GoalStore().get("g3")
    assert stored is not None and stored.dry_rounds == 1


def test_replenish_caps_at_max(tmp_path, monkeypatch):
    sd = tmp_path / "st4"
    sd.mkdir()
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)
    monkeypatch.setenv("HEPHAESTUS_REPLENISH_MAX", "2")

    repo = tmp_path / "repo4"
    repo.mkdir()
    ws = _make_ws(str(repo))
    goal = Goal(id="g4", title="Goal4")

    runner = _PlanRunner([_task("r1"), _task("r2"), _task("r3"), _task("r4")])
    n = asyncio.run(replenish_goal(ws, goal, runner=runner))

    assert n == 2  # capped at HEPHAESTUS_REPLENISH_MAX=2

    from app.core.state import _read_state
    items = _read_state()["items"]
    assert len(items) == 2
