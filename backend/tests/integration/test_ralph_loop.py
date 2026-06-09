"""Integration tests for the Ralph sequential loop (C3).

All tests:
- Stub _process_item, _iter_cost, and replenish_goal so NO real git/LLM/subprocess runs.
- Are bounded: use small budgets / max_iter / dry-round limits so the loop terminates quickly.
- Seed the queue via _STATE_DIR_OVERRIDE + work-state.json.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
from unittest.mock import patch

import app.core.state as state_mod
from app.orchestrator.fsm import OrchestratorFSM

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_queue(sd: pathlib.Path, items: list[dict]) -> None:
    """Write work-state.json with given items into tmp state dir."""
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "work-state.json").write_text(
        json.dumps({"items": items}), encoding="utf-8"
    )


def _item(id_: str, status: str = "pending") -> dict:
    return {"id": id_, "title": f"Task {id_}", "status": status, "attempts": 0}


def _mark_item_status(sd: pathlib.Path, item_id: str, status: str) -> None:
    """Simulate _process_item finishing by updating item status on disk."""
    path = sd / "work-state.json"
    s = json.loads(path.read_text(encoding="utf-8"))
    for it in s.get("items", []):
        if it.get("id") == item_id:
            it["status"] = status
    path.write_text(json.dumps(s), encoding="utf-8")


def _make_fsm() -> OrchestratorFSM:
    fsm = OrchestratorFSM()
    fsm._ws = None  # no real workspace
    return fsm


# ---------------------------------------------------------------------------
# C3-1: stops when cost budget is exceeded
# ---------------------------------------------------------------------------


def test_ralph_stops_on_cost(monkeypatch, tmp_path):
    sd = tmp_path / "state"
    _seed_queue(sd, [_item("a"), _item("b")])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    # Set very low cost budget (0.001 USD) and high per-iter cost (0.01 USD)
    monkeypatch.setenv("HEPHAESTUS_RUN_MODE", "ralph")
    monkeypatch.setenv("HEPHAESTUS_COST_BUDGET_USD", "0.001")
    monkeypatch.setenv("HEPHAESTUS_WALLCLOCK_SEC", "0")
    monkeypatch.setenv("HEPHAESTUS_MAX_CONSEC_FAIL", "100")
    monkeypatch.setenv("HEPHAESTUS_MAX_ITER", "0")

    fsm = _make_fsm()

    async def _fake_process(item, ws=None):
        _mark_item_status(sd, item.get("id", ""), "done")
        # Give iter_dir a value so cost accumulation is attempted
        fsm.iter_dir = tmp_path / "iter-fake"
        fsm.iter_dir.mkdir(exist_ok=True)

    monkeypatch.setattr(fsm, "_process_item", _fake_process)

    # _iter_cost returns high cost to trigger budget
    monkeypatch.setattr(
        "app.core.events._iter_cost",
        lambda d: {"cost_usd": 0.01},
    )

    asyncio.run(fsm.run())

    from app.core.run_summary import RunSummaryStore
    summary = RunSummaryStore().get()
    assert summary is not None
    assert "cost" in summary.stopped_reason.lower()


# ---------------------------------------------------------------------------
# C3-2: stops when queue is empty and replenish returns 0 twice (dry)
# ---------------------------------------------------------------------------


def test_ralph_stops_when_dry(monkeypatch, tmp_path):
    sd = tmp_path / "state"
    # Start with empty queue
    _seed_queue(sd, [])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    monkeypatch.setenv("HEPHAESTUS_RUN_MODE", "ralph")
    monkeypatch.setenv("HEPHAESTUS_COST_BUDGET_USD", "0")
    monkeypatch.setenv("HEPHAESTUS_WALLCLOCK_SEC", "0")
    monkeypatch.setenv("HEPHAESTUS_MAX_CONSEC_FAIL", "0")
    monkeypatch.setenv("HEPHAESTUS_MAX_ITER", "0")

    # Create an active goal
    from app.core.goals import Goal, GoalStore
    goal = Goal(id="g1", title="My Goal", dry_rounds=0)
    GoalStore().put(goal)

    fsm = _make_fsm()

    # replenish_goal always returns 0 (dry); we track call count
    replenish_calls: list[int] = []

    async def _fake_replenish(ws, g, *, runner):
        replenish_calls.append(1)
        # Simulate GoalStore bumping dry_rounds (as the real impl does)
        g.dry_rounds += 1
        GoalStore().put(g)
        return 0

    monkeypatch.setattr(
        "app.orchestrator.fsm.replenish_goal",
        _fake_replenish,
    )
    # Also patch the import inside the run() closure
    with patch("app.core.goals.replenish_goal", _fake_replenish):
        asyncio.run(fsm.run())

    from app.core.run_summary import RunSummaryStore
    summary = RunSummaryStore().get()
    assert summary is not None
    assert "dry" in summary.stopped_reason.lower() or "goal" in summary.stopped_reason.lower()
    # Must have called replenish at least twice (to reach dry_rounds >= 2)
    assert len(replenish_calls) >= 2


# ---------------------------------------------------------------------------
# C3-3: stops when consecutive failures hit max_consec_fail
# ---------------------------------------------------------------------------


def test_ralph_stops_on_consec_fail(monkeypatch, tmp_path):
    sd = tmp_path / "state"
    # Enough items to fail 3 times
    _seed_queue(sd, [_item(f"fail{i}") for i in range(5)])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    monkeypatch.setenv("HEPHAESTUS_RUN_MODE", "ralph")
    monkeypatch.setenv("HEPHAESTUS_COST_BUDGET_USD", "0")
    monkeypatch.setenv("HEPHAESTUS_WALLCLOCK_SEC", "0")
    monkeypatch.setenv("HEPHAESTUS_MAX_CONSEC_FAIL", "3")
    monkeypatch.setenv("HEPHAESTUS_MAX_ITER", "0")

    fsm = _make_fsm()

    async def _fake_process(item, ws=None):
        # Mark item as failed so consec_fail increments
        _mark_item_status(sd, item.get("id", ""), "failed:test")

    monkeypatch.setattr(fsm, "_process_item", _fake_process)
    monkeypatch.setattr(
        "app.core.events._iter_cost",
        lambda d: {"cost_usd": 0.0},
    )

    asyncio.run(fsm.run())

    from app.core.run_summary import RunSummaryStore
    summary = RunSummaryStore().get()
    assert summary is not None
    assert "consec" in summary.stopped_reason.lower()
    assert summary.consec_fail >= 3


# ---------------------------------------------------------------------------
# C3-4: queue mode — behaves exactly as before; no replenish called
# ---------------------------------------------------------------------------


def test_queue_mode_unchanged(monkeypatch, tmp_path):
    sd = tmp_path / "state"
    # Auto-driver (#3): queue mode picks `queued` (user-sent), not `pending` backlog.
    _seed_queue(sd, [_item("q1", status="queued")])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    monkeypatch.setenv("HEPHAESTUS_RUN_MODE", "queue")
    monkeypatch.setenv("HEPHAESTUS_COST_BUDGET_USD", "0")
    monkeypatch.setenv("HEPHAESTUS_WALLCLOCK_SEC", "0")
    monkeypatch.setenv("HEPHAESTUS_MAX_CONSEC_FAIL", "4")
    monkeypatch.setenv("HEPHAESTUS_MAX_ITER", "1")

    fsm = _make_fsm()

    replenish_called: list[bool] = []

    async def _fake_process(item, ws=None):
        _mark_item_status(sd, item.get("id", ""), "done")

    monkeypatch.setattr(fsm, "_process_item", _fake_process)
    monkeypatch.setattr(
        "app.core.events._iter_cost",
        lambda d: {"cost_usd": 0.0},
    )

    async def _should_not_replenish(*a, **kw):
        replenish_called.append(True)
        return 0

    monkeypatch.setattr(
        "app.orchestrator.fsm.replenish_goal",
        _should_not_replenish,
    )

    asyncio.run(fsm.run())

    # replenish must NOT have been called in queue mode
    assert not replenish_called, "replenish_goal should NOT be called in queue mode"

    from app.core.run_summary import RunSummaryStore
    summary = RunSummaryStore().get()
    assert summary is not None
    assert summary.items_done == 1
    assert summary.run_mode == "queue"


# ---------------------------------------------------------------------------
# C3-5: queue mode ignores Ralph budgets (cost/consec) — only max_iter bounds it
# ---------------------------------------------------------------------------


def test_queue_mode_ignores_budgets(monkeypatch, tmp_path):
    sd = tmp_path / "state"
    # Auto-driver (#3): queue mode picks `queued` (user-sent), not `pending` backlog.
    _seed_queue(sd, [_item("q1", status="queued"), _item("q2", status="queued")])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    monkeypatch.setenv("HEPHAESTUS_RUN_MODE", "queue")
    monkeypatch.setenv("HEPHAESTUS_COST_BUDGET_USD", "0.001")  # tiny — would stop a ralph run after item 1
    monkeypatch.setenv("HEPHAESTUS_WALLCLOCK_SEC", "0")
    monkeypatch.setenv("HEPHAESTUS_MAX_CONSEC_FAIL", "1")      # tiny — would stop a ralph run
    monkeypatch.setenv("HEPHAESTUS_MAX_ITER", "2")             # the only bound in queue mode

    fsm = _make_fsm()

    async def _fake_process(item, ws=None):
        _mark_item_status(sd, item.get("id", ""), "done")
        fsm.iter_dir = tmp_path / "iter-fake"
        fsm.iter_dir.mkdir(exist_ok=True)

    monkeypatch.setattr(fsm, "_process_item", _fake_process)
    monkeypatch.setattr("app.core.events._iter_cost", lambda d: {"cost_usd": 0.01})

    asyncio.run(fsm.run())

    from app.core.run_summary import RunSummaryStore
    summary = RunSummaryStore().get()
    assert summary is not None
    # Both items processed despite cost (0.02) far exceeding the 0.001 budget — queue ignores it.
    assert summary.items_done == 2
    # Stopped via max_iter (which sets no reason), NOT a budget/consec stop.
    assert not summary.stopped_reason
