"""#4 — FSM picks only READY items (queued + deps satisfied); dead-end exits.

_pick_next_item / _claim_next_item now additionally require deps_satisfied, so a
3-chain all-queued releases only the ready leaf first, then the next as each completes.
A failed prerequisite leaves dependents queued-but-not-ready → has_runnable is False.
"""

from __future__ import annotations

import json
import pathlib

import app.core.state as state_mod
from app.core.deps import has_runnable
from app.orchestrator.fsm import OrchestratorFSM


def _seed(sd: pathlib.Path, items: list[dict]) -> None:
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "work-state.json").write_text(json.dumps({"items": items}), encoding="utf-8")


def _read_items(sd: pathlib.Path) -> list[dict]:
    return json.loads((sd / "work-state.json").read_text(encoding="utf-8"))["items"]


def _set_status(sd: pathlib.Path, item_id: str, status: str) -> None:
    items = _read_items(sd)
    for it in items:
        if it["id"] == item_id:
            it["status"] = status
    (sd / "work-state.json").write_text(json.dumps({"items": items}), encoding="utf-8")


def test_pick_releases_ready_leaf_first(tmp_path, monkeypatch) -> None:
    """3-chain all queued (C deps B deps A): only A (the ready leaf) is picked first."""
    sd = tmp_path / "state"
    _seed(sd, [
        {"id": "c", "status": "queued", "dependsOn": ["b"]},
        {"id": "b", "status": "queued", "dependsOn": ["a"]},
        {"id": "a", "status": "queued", "dependsOn": []},
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    fsm = OrchestratorFSM()
    fsm._ws = None
    picked = fsm._pick_next_item()
    assert picked is not None
    assert picked["id"] == "a"


def test_pick_advances_after_dep_done(tmp_path, monkeypatch) -> None:
    """After A -> done, B becomes ready and is picked next."""
    sd = tmp_path / "state"
    _seed(sd, [
        {"id": "c", "status": "queued", "dependsOn": ["b"]},
        {"id": "b", "status": "queued", "dependsOn": ["a"]},
        {"id": "a", "status": "queued", "dependsOn": []},
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    fsm = OrchestratorFSM()
    fsm._ws = None
    _set_status(sd, "a", "done")
    picked = fsm._pick_next_item()
    assert picked is not None
    assert picked["id"] == "b"


def test_pick_skips_queued_with_unfinished_dep(tmp_path, monkeypatch) -> None:
    """A queued item whose dep is unfinished is skipped (not ready)."""
    sd = tmp_path / "state"
    _seed(sd, [
        {"id": "a", "status": "pending"},
        {"id": "c", "status": "queued", "dependsOn": ["a"]},
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    fsm = OrchestratorFSM()
    fsm._ws = None
    assert fsm._pick_next_item() is None


def test_claim_releases_ready_leaf_first(tmp_path, monkeypatch) -> None:
    """_claim_next_item flips only the ready leaf to in_progress."""
    sd = tmp_path / "state"
    _seed(sd, [
        {"id": "c", "status": "queued", "dependsOn": ["b"]},
        {"id": "b", "status": "queued", "dependsOn": ["a"]},
        {"id": "a", "status": "queued", "dependsOn": []},
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    fsm = OrchestratorFSM()
    fsm._ws = None
    claimed = fsm._claim_next_item()
    assert claimed is not None
    assert claimed["id"] == "a"
    assert claimed["status"] == "in_progress"

    statuses = {it["id"]: it["status"] for it in _read_items(sd)}
    assert statuses["a"] == "in_progress"
    assert statuses["b"] == "queued"  # not claimed — dep was just claimed, not done
    assert statuses["c"] == "queued"


def test_dead_end_pick_none_and_has_runnable_false(tmp_path, monkeypatch) -> None:
    """A failed prereq leaves B&C queued-but-not-ready: no pick, has_runnable False."""
    sd = tmp_path / "state"
    items = [
        {"id": "a", "status": "failed:verify"},
        {"id": "b", "status": "queued", "dependsOn": ["a"]},
        {"id": "c", "status": "queued", "dependsOn": ["b"]},
    ]
    _seed(sd, items)
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    fsm = OrchestratorFSM()
    fsm._ws = None
    assert fsm._pick_next_item() is None
    assert has_runnable(items) is False
