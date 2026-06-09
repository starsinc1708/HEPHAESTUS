"""Auto-driver #3 — FSM picks `queued` (not `pending`); crash-recovery → `queued`.

The loop must only run items the user explicitly SENT (status=="queued").
Items that are merely created (status=="pending") are backlog and must be ignored.
"""

from __future__ import annotations

import json
import pathlib

import pytest

import app.core.state as state_mod
from app.orchestrator.fsm import OrchestratorFSM


def _seed(sd: pathlib.Path, items: list[dict]) -> None:
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "work-state.json").write_text(json.dumps({"items": items}), encoding="utf-8")


def _read_items(sd: pathlib.Path) -> list[dict]:
    return json.loads((sd / "work-state.json").read_text(encoding="utf-8"))["items"]


def test_pick_next_item_returns_queued_ignores_pending(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_pick_next_item returns the queued item and skips the earlier pending one."""
    sd = tmp_path / "state"
    _seed(sd, [
        {"id": "p1", "status": "pending"},
        {"id": "q1", "status": "queued"},
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    fsm = OrchestratorFSM()
    fsm._ws = None
    picked = fsm._pick_next_item()
    assert picked is not None
    assert picked["id"] == "q1"


def test_pick_next_item_none_when_only_pending(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A backlog of only pending items yields nothing to pick."""
    sd = tmp_path / "state"
    _seed(sd, [{"id": "p1", "status": "pending"}, {"id": "p2", "status": "pending"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    fsm = OrchestratorFSM()
    fsm._ws = None
    assert fsm._pick_next_item() is None


def test_claim_next_item_claims_queued_ignores_pending(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_claim_next_item atomically flips queued -> in_progress, ignoring pending."""
    sd = tmp_path / "state"
    _seed(sd, [
        {"id": "p1", "status": "pending"},
        {"id": "q1", "status": "queued"},
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    fsm = OrchestratorFSM()
    fsm._ws = None
    claimed = fsm._claim_next_item()
    assert claimed is not None
    assert claimed["id"] == "q1"
    assert claimed["status"] == "in_progress"

    items = {it["id"]: it["status"] for it in _read_items(sd)}
    assert items["q1"] == "in_progress"
    assert items["p1"] == "pending"  # untouched backlog


def test_claim_next_item_none_when_only_pending(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "p1", "status": "pending"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    fsm = OrchestratorFSM()
    fsm._ws = None
    assert fsm._claim_next_item() is None
    # pending must remain pending — not auto-run
    assert _read_items(sd)[0]["status"] == "pending"


def test_requeue_stale_in_progress_flips_to_queued(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Crash recovery resets stale in_progress -> queued (resume only sent tasks)."""
    sd = tmp_path / "state"
    _seed(sd, [
        {"id": "x", "status": "in_progress"},
        {"id": "p", "status": "pending"},
        {"id": "d", "status": "done"},
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    fsm = OrchestratorFSM()
    fsm._ws = None
    fsm._requeue_stale_in_progress()

    items = {it["id"]: it["status"] for it in _read_items(sd)}
    assert items["x"] == "queued"   # recovered to runnable, not backlog
    assert items["p"] == "pending"  # backlog untouched
    assert items["d"] == "done"
