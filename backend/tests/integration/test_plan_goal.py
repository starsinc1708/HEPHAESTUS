"""Integration test for plan_goal (B3) — stub runner, no real agent CLI."""
from __future__ import annotations

import asyncio
import pathlib
import types

import app.core.state as state
from app.core.goals import Goal, plan_goal


def _make_ws(repo_path: str) -> types.SimpleNamespace:
    """Minimal RepoProfile-shaped namespace sufficient for plan_goal."""
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
        memory_dir=".hephaestus/memory",
    )


class StubRunner:
    """Writes a PLAN block to output_path; decompose falls back to 1:1 (no DECOMPOSE block)."""

    async def run(self, ref: object, *, prompt_file: pathlib.Path, cwd: str,
                  output_path: pathlib.Path, timeout_sec: int) -> object:
        output_path.write_text(
            'PLAN_BEGIN{"tasks":[{"id":"a","title":"A","proposal":"do A","rationale":"r",'
            '"acceptance":"t","touches":["x.py"],"complexity":"simple"}]}PLAN_END',
            encoding="utf-8",
        )

        class R:
            exit_code = 0
            refused = False

        return R()


def test_plan_goal_enqueues_and_decomposes(tmp_path, monkeypatch) -> None:
    sd = tmp_path / "st"
    sd.mkdir()
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)

    # Create the repo dir so decompose_proposals can mkdir under it
    repo = tmp_path / "repo"
    repo.mkdir()

    ws = _make_ws(str(repo))
    goal = Goal(id="goal-1", title="Add retries")

    ids = asyncio.run(plan_goal(ws, goal, runner=StubRunner()))

    assert "a" in ids

    from app.core.state import _read_state

    it = next(i for i in _read_state()["items"] if i["id"] == "a")
    assert it["epicId"] == "goal-1"
    assert it["proposal"] == "do A"


def test_plan_goal_returns_empty_on_bad_block(tmp_path, monkeypatch) -> None:
    """If the agent emits no valid PLAN block, plan_goal returns [] without crashing."""
    sd = tmp_path / "st2"
    sd.mkdir()
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)

    repo = tmp_path / "repo2"
    repo.mkdir()
    ws = _make_ws(str(repo))
    goal = Goal(id="goal-bad", title="Unclear goal")

    class BadRunner:
        async def run(self, ref: object, *, prompt_file: pathlib.Path, cwd: str,
                      output_path: pathlib.Path, timeout_sec: int) -> object:
            output_path.write_text("no plan here", encoding="utf-8")

            class R:
                exit_code = 0
                refused = False

            return R()

    ids = asyncio.run(plan_goal(ws, goal, runner=BadRunner()))
    assert ids == []


def test_plan_goal_updates_goal_task_ids(tmp_path, monkeypatch) -> None:
    """goal.task_ids is populated after plan_goal."""
    sd = tmp_path / "st3"
    sd.mkdir()
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)

    repo = tmp_path / "repo3"
    repo.mkdir()
    ws = _make_ws(str(repo))
    goal = Goal(id="goal-ids", title="Multi-task goal")

    class MultiRunner:
        async def run(self, ref: object, *, prompt_file: pathlib.Path, cwd: str,
                      output_path: pathlib.Path, timeout_sec: int) -> object:
            output_path.write_text(
                'PLAN_BEGIN{"tasks":['
                '{"id":"t1","title":"T1","proposal":"do T1","rationale":"r","acceptance":"ac","touches":["a.py"]},'
                '{"id":"t2","title":"T2","proposal":"do T2","rationale":"r","acceptance":"ac","touches":["b.py"]}'
                ']}PLAN_END',
                encoding="utf-8",
            )

            class R:
                exit_code = 0
                refused = False

            return R()

    asyncio.run(plan_goal(ws, goal, runner=MultiRunner()))
    assert set(goal.task_ids) == {"t1", "t2"}


class _TreeRunner:
    """Emits a 3-task PLAN block (t1, t2, t3)."""

    async def run(self, ref: object, *, prompt_file: pathlib.Path, cwd: str,
                  output_path: pathlib.Path, timeout_sec: int) -> object:
        output_path.write_text(
            'PLAN_BEGIN{"tasks":['
            '{"id":"t1","title":"T1","proposal":"do t1","rationale":"r","acceptance":"a","touches":["a.py"]},'
            '{"id":"t2","title":"T2","proposal":"do t2","rationale":"r","acceptance":"a","touches":["b.py"]},'
            '{"id":"t3","title":"T3","proposal":"do t3","rationale":"r","acceptance":"a","touches":["c.py"]}'
            ']}PLAN_END',
            encoding="utf-8",
        )

        class R:
            exit_code = 0
            refused = False

        return R()


def test_plan_goal_one_shot_pending_with_deps(tmp_path, monkeypatch) -> None:
    """3-task tree lands as `pending` (one-shot, no Ralph) carrying dependsOn."""
    import app.core.decompose as decompose_mod

    sd = tmp_path / "st-oneshot"
    sd.mkdir()
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)
    repo = tmp_path / "repo-oneshot"
    repo.mkdir()
    ws = _make_ws(str(repo))
    goal = Goal(id="goal-tree", title="Tree goal")

    async def _fake_decompose(ws, proposals, *, scan_dir, runner, decomposer_ref=None):
        deps = {"t1": [], "t2": ["t1"], "t3": ["t2"]}  # t1 -> t2 -> t3 chain
        return [
            {"id": p["id"], "dependsOn": deps.get(p["id"], []), "epicId": goal.id,
             "parent": None, "orderIndex": i, "conflictGroup": None}
            for i, p in enumerate(proposals)
        ]

    # plan_goal does `from app.core.decompose import decompose_proposals` locally,
    # so patch the source module's symbol for the fake to take effect.
    monkeypatch.setattr(decompose_mod, "decompose_proposals", _fake_decompose)

    ids = asyncio.run(plan_goal(ws, goal, runner=_TreeRunner()))
    assert set(ids) == {"t1", "t2", "t3"}

    from app.core.state import _read_state

    items = {i["id"]: i for i in _read_state()["items"]}
    # one-shot: everything pending, nothing auto-queued
    assert all(items[k]["status"] == "pending" for k in ("t1", "t2", "t3"))
    assert items["t2"]["dependsOn"] == ["t1"]
    assert items["t3"]["dependsOn"] == ["t2"]


def test_plan_goal_max_tasks_caps(tmp_path, monkeypatch) -> None:
    """max_tasks caps the proposals enqueued (only the first N land)."""
    import app.core.decompose as decompose_mod

    sd = tmp_path / "st-max"
    sd.mkdir()
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)
    repo = tmp_path / "repo-max"
    repo.mkdir()
    ws = _make_ws(str(repo))
    goal = Goal(id="goal-max", title="Max goal")

    async def _fake_decompose(ws, proposals, *, scan_dir, runner, decomposer_ref=None):
        return [
            {"id": p["id"], "dependsOn": [], "epicId": goal.id, "parent": None,
             "orderIndex": i, "conflictGroup": None}
            for i, p in enumerate(proposals)
        ]

    monkeypatch.setattr(decompose_mod, "decompose_proposals", _fake_decompose)

    ids = asyncio.run(plan_goal(ws, goal, runner=_TreeRunner(), max_tasks=2))
    assert ids == ["t1", "t2"]

    from app.core.state import _read_state

    assert {i["id"] for i in _read_state()["items"]} == {"t1", "t2"}
