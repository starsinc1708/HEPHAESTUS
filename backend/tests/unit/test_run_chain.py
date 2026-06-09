"""#4 — /run queues the task AND its whole unfinished prerequisite chain.

_run_task / _run_tasks now flip the target plus its eligible unfinished ancestors to
queued, leaving already-done ancestors and failed:* ancestors untouched.
"""

from __future__ import annotations

import json
import pathlib

import app.core.state as state_mod
from app.core.queue import _run_task, _run_tasks


def _seed(sd: pathlib.Path, items: list[dict]) -> None:
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "work-state.json").write_text(json.dumps({"items": items}), encoding="utf-8")


def _status(sd: pathlib.Path, item_id: str) -> str:
    items = json.loads((sd / "work-state.json").read_text(encoding="utf-8"))["items"]
    return next(it["status"] for it in items if it["id"] == item_id)


def test_run_task_queues_full_chain(tmp_path, monkeypatch) -> None:
    """_run_task on C of a 3-chain C->B->A queues {A,B,C}."""
    sd = tmp_path / "state"
    _seed(sd, [
        {"id": "a", "status": "pending"},
        {"id": "b", "status": "pending", "dependsOn": ["a"]},
        {"id": "c", "status": "pending", "dependsOn": ["b"]},
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    res = _run_task("c")
    assert res == {"ok": True, "id": "c", "status": "queued"}
    assert _status(sd, "a") == "queued"
    assert _status(sd, "b") == "queued"
    assert _status(sd, "c") == "queued"


def test_run_task_skips_done_ancestor(tmp_path, monkeypatch) -> None:
    """A done ancestor is not re-queued (and not walked past)."""
    sd = tmp_path / "state"
    _seed(sd, [
        {"id": "a", "status": "done"},
        {"id": "b", "status": "pending", "dependsOn": ["a"]},
        {"id": "c", "status": "pending", "dependsOn": ["b"]},
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    _run_task("c")
    assert _status(sd, "a") == "done"     # untouched
    assert _status(sd, "b") == "queued"
    assert _status(sd, "c") == "queued"


def test_run_task_leaves_failed_ancestor(tmp_path, monkeypatch) -> None:
    """A failed:* ancestor stays failed (dead-end until the user requeues it)."""
    sd = tmp_path / "state"
    _seed(sd, [
        {"id": "a", "status": "failed:verify"},
        {"id": "b", "status": "pending", "dependsOn": ["a"]},
        {"id": "c", "status": "pending", "dependsOn": ["b"]},
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    _run_task("c")
    assert _status(sd, "a") == "failed:verify"  # NOT flipped
    assert _status(sd, "b") == "queued"
    assert _status(sd, "c") == "queued"


def test_run_task_leaves_already_queued_ancestor(tmp_path, monkeypatch) -> None:
    """An already-queued/in_progress ancestor is left as-is, not re-flipped."""
    sd = tmp_path / "state"
    _seed(sd, [
        {"id": "a", "status": "in_progress"},
        {"id": "b", "status": "queued", "dependsOn": ["a"]},
        {"id": "c", "status": "pending", "dependsOn": ["b"]},
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    _run_task("c")
    assert _status(sd, "a") == "in_progress"
    assert _status(sd, "b") == "queued"
    assert _status(sd, "c") == "queued"


def test_run_task_not_found(tmp_path, monkeypatch) -> None:
    sd = tmp_path / "state"
    _seed(sd, [])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)
    assert _run_task("nope") == {"ok": False, "error": "id not found"}


def test_run_task_wrong_status_preserved(tmp_path, monkeypatch) -> None:
    """Running a done target 409s (returns status) and leaves the chain untouched."""
    sd = tmp_path / "state"
    _seed(sd, [
        {"id": "a", "status": "pending"},
        {"id": "c", "status": "done", "dependsOn": ["a"]},
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    res = _run_task("c")
    assert res == {"ok": False, "error": "cannot run item in status done", "status": "done"}
    assert _status(sd, "a") == "pending"  # ancestor untouched on a rejected target
    assert _status(sd, "c") == "done"


def test_run_tasks_queues_union(tmp_path, monkeypatch) -> None:
    """Bulk _run_tasks queues the union of each id's target + unfinished ancestors."""
    sd = tmp_path / "state"
    _seed(sd, [
        {"id": "a", "status": "pending"},
        {"id": "b", "status": "pending", "dependsOn": ["a"]},
        {"id": "c", "status": "pending", "dependsOn": ["b"]},
        {"id": "d", "status": "done"},  # ineligible target -> skipped
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    res = _run_tasks(["c", "d"])
    assert res["ok"] is True
    assert set(res["queued"]) == {"a", "b", "c"}
    assert any(s["id"] == "d" for s in res["skipped"])
    assert _status(sd, "a") == "queued"
    assert _status(sd, "b") == "queued"
    assert _status(sd, "c") == "queued"
    assert _status(sd, "d") == "done"


def test_run_tasks_missing_id_skipped(tmp_path, monkeypatch) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "a", "status": "pending"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    res = _run_tasks(["ghost", "a"])
    assert {"id": "ghost", "status": None} in res["skipped"]
    assert res["queued"] == ["a"]


def test_run_tasks_shared_ancestor_queued_once(tmp_path, monkeypatch) -> None:
    """Two requested ids sharing a common unfinished ancestor flip it once and report it
    once in `queued` (no double-flip, no duplicate id)."""
    sd = tmp_path / "state"
    _seed(sd, [
        {"id": "root", "status": "pending"},
        {"id": "b", "status": "pending", "dependsOn": ["root"]},
        {"id": "c", "status": "pending", "dependsOn": ["root"]},
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    res = _run_tasks(["b", "c"])
    assert res["ok"] is True
    assert sorted(res["queued"]) == ["b", "c", "root"]
    assert res["queued"].count("root") == 1  # shared ancestor not duplicated
    assert _status(sd, "root") == "queued"
    assert _status(sd, "b") == "queued"
    assert _status(sd, "c") == "queued"
