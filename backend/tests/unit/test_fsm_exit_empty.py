"""Auto-driver #3 — queue-mode run() EXITS on a dry queue (process ends).

Ralph mode is unchanged: with no goals it keeps the original 30s idle sleep and
does NOT exit.
"""

from __future__ import annotations

import asyncio
import json
import pathlib

import app.core.state as state_mod
from app.orchestrator.fsm import OrchestratorFSM


def _seed(sd: pathlib.Path, items: list[dict]) -> None:
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "work-state.json").write_text(json.dumps({"items": items}), encoding="utf-8")


def test_queue_mode_exits_on_dry_queue(tmp_path, monkeypatch) -> None:
    """run() returns promptly when nothing is queued/in_progress (no infinite sleep)."""
    sd = tmp_path / "state"
    _seed(sd, [{"id": "p", "status": "pending"}])  # backlog only — nothing runnable
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    monkeypatch.setenv("HEPHAESTUS_RUN_MODE", "queue")
    monkeypatch.setenv("HEPHAESTUS_MAX_ITER", "0")

    fsm = OrchestratorFSM()
    fsm._ws = None

    # Guard: a 30s sleep would mean we did NOT exit — make it explode so the test fails fast.
    real_sleep = asyncio.sleep

    async def _guard_sleep(secs, *a, **k):  # noqa: ANN001, ANN202
        if secs and secs >= 10:
            raise AssertionError(f"queue mode should not sleep {secs}s on dry queue")
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _guard_sleep)

    # asyncio.wait_for so a hang fails the test instead of blocking forever.
    asyncio.run(asyncio.wait_for(fsm.run(), timeout=5))


def test_queue_mode_exits_when_pick_returns_none(tmp_path, monkeypatch) -> None:
    """Even if state were briefly inconsistent, a confirmed-empty re-check exits."""
    sd = tmp_path / "state"
    _seed(sd, [])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    monkeypatch.setenv("HEPHAESTUS_RUN_MODE", "queue")
    monkeypatch.setenv("HEPHAESTUS_MAX_ITER", "0")

    fsm = OrchestratorFSM()
    fsm._ws = None
    monkeypatch.setattr(fsm, "_pick_next_item", lambda: None)

    asyncio.run(asyncio.wait_for(fsm.run(), timeout=5))


def test_queue_mode_recheck_continues_when_item_arrives_mid_exit(tmp_path, monkeypatch) -> None:
    """Exit↔send race: _pick_next_item returns None (dry), but a /run lands mid-exit so the
    pre-exit re-read sees a queued item. The loop must NOT take the exit break — it must
    continue and process the newly-queued item.

    Drive deterministically: _pick_next_item returns None first, then the item; the state on
    disk contains a queued item so the re-check finds it runnable; _process_item sets
    _stop_requested so the loop terminates after exactly one processed item. Asserting the
    item was processed proves the exit-break was NOT taken on the dry round.
    """
    sd = tmp_path / "state"
    # State on disk has a runnable (queued) item — this is what the pre-exit re-read sees,
    # simulating a /run that arrived after _pick_next_item already returned None.
    _seed(sd, [{"id": "late", "status": "queued"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    monkeypatch.setenv("HEPHAESTUS_RUN_MODE", "queue")
    monkeypatch.setenv("HEPHAESTUS_MAX_ITER", "0")

    fsm = OrchestratorFSM()
    fsm._ws = None

    item = {"id": "late", "status": "queued"}
    pick_results = [None, item]  # dry first (triggers re-check), then the item

    def _pick():  # noqa: ANN202
        return pick_results.pop(0) if pick_results else None

    monkeypatch.setattr(fsm, "_pick_next_item", _pick)

    processed: list[str] = []

    async def _process(it):  # noqa: ANN001, ANN202
        processed.append(it["id"])
        fsm._stop_requested = True  # terminate after exactly one processed item

    monkeypatch.setattr(fsm, "_process_item", _process)

    # Collapse all sleeps (the 0-yield in the re-check + the 5s inter-iter sleep) so the test
    # is fast and deterministic — no real waits.
    real_sleep = asyncio.sleep

    async def _no_sleep(secs, *a, **k):  # noqa: ANN001, ANN202
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    asyncio.run(asyncio.wait_for(fsm.run(), timeout=5))

    # The loop continued past the dry round (did NOT exit-break) and processed the late item.
    assert processed == ["late"]


def test_ralph_mode_no_goals_does_not_exit(tmp_path, monkeypatch) -> None:
    """Ralph mode with no active goals keeps the idle 30s sleep (does NOT exit)."""
    sd = tmp_path / "state"
    _seed(sd, [])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    monkeypatch.setenv("HEPHAESTUS_RUN_MODE", "ralph")
    monkeypatch.setenv("HEPHAESTUS_COST_BUDGET_USD", "0")
    monkeypatch.setenv("HEPHAESTUS_WALLCLOCK_SEC", "0")
    monkeypatch.setenv("HEPHAESTUS_MAX_CONSEC_FAIL", "0")
    monkeypatch.setenv("HEPHAESTUS_MAX_ITER", "0")

    fsm = OrchestratorFSM()
    fsm._ws = None

    # Prove the ralph idle path is reached: the 30s idle sleep is hit. We intercept it
    # and stop the loop so the test terminates deterministically. If ralph EXITED instead
    # (the queue-mode behavior), this sentinel would never fire.
    hit_idle = {"v": False}
    real_sleep = asyncio.sleep

    async def _intercept(secs, *a, **k):  # noqa: ANN001, ANN202
        if secs and secs >= 10:
            hit_idle["v"] = True
            fsm._stop_requested = True  # break out after proving we slept
            return await real_sleep(0)
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _intercept)

    asyncio.run(asyncio.wait_for(fsm.run(), timeout=5))
    assert hit_idle["v"], "ralph mode (no goals) must hit the idle sleep, not exit"
