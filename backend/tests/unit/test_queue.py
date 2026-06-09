"""Unit tests for queue CRUD operations."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.core.queue import _queue_add, _queue_delete, _queue_move_top, _queue_patch, _queue_requeue


def _write_state(state_dir: pathlib.Path, items: list[dict]) -> None:
    """Helper: write a state file with given items."""
    (state_dir / "work-state.json").write_text(json.dumps({"items": items}))


def _read_items(state_dir: pathlib.Path) -> list[dict]:
    """Helper: read items from state file."""
    return json.loads((state_dir / "work-state.json").read_text())["items"]


def test_queue_add_creates_item(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_queue_add should create an item with pending status."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_state_dir)
    _write_state(tmp_state_dir, [])

    result = _queue_add({"id": "test-001", "title": "Test item"})
    assert result["ok"] is True
    assert result["id"] == "test-001"

    items = _read_items(tmp_state_dir)
    assert len(items) == 1
    assert items[0]["status"] == "pending"
    assert items[0]["attempts"] == 0


def test_queue_add_generates_id_if_missing(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_queue_add auto-generates an id when none provided."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_state_dir)
    _write_state(tmp_state_dir, [])

    result = _queue_add({"title": "No-id item"})
    assert result["ok"] is True
    assert result["id"].startswith("adhoc-")


def test_queue_add_sets_default_acceptance(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_queue_add should set default acceptance if not provided."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_state_dir)
    _write_state(tmp_state_dir, [])

    _queue_add({"id": "acc-test"})
    items = _read_items(tmp_state_dir)
    assert items[0]["acceptance"]  # non-empty default


def test_queue_delete_removes_item(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_queue_delete removes the matching item."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_state_dir)
    _write_state(tmp_state_dir, [{"id": "del-1", "title": "To delete", "status": "pending", "attempts": 0}])

    result = _queue_delete("del-1")
    assert result["ok"] is True
    assert len(_read_items(tmp_state_dir)) == 0


def test_queue_delete_missing_returns_error(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_queue_delete with non-existent id returns error."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_state_dir)
    _write_state(tmp_state_dir, [])

    result = _queue_delete("nonexistent")
    assert result["ok"] is False
    assert "not found" in result["error"]


def test_queue_move_top_reorders(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_queue_move_top moves item to position 0."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_state_dir)
    items = [
        {"id": "a", "title": "A", "status": "pending", "attempts": 0},
        {"id": "b", "title": "B", "status": "pending", "attempts": 0},
        {"id": "c", "title": "C", "status": "pending", "attempts": 0},
    ]
    _write_state(tmp_state_dir, items)

    result = _queue_move_top("c")
    assert result["ok"] is True
    reordered = _read_items(tmp_state_dir)
    assert reordered[0]["id"] == "c"


def test_queue_move_top_missing_returns_error(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_queue_move_top with non-existent id returns error."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_state_dir)
    _write_state(tmp_state_dir, [])

    result = _queue_move_top("nonexistent")
    assert result["ok"] is False


def test_queue_patch_updates_editable_fields(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_queue_patch should update title and other editable fields on pending items."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_state_dir)
    _write_state(tmp_state_dir, [{"id": "p-1", "title": "Old", "status": "pending", "attempts": 0}])

    result = _queue_patch("p-1", {"title": "New title", "proposal": "updated proposal"})
    assert result["ok"] is True
    items = _read_items(tmp_state_dir)
    assert items[0]["title"] == "New title"
    assert items[0]["proposal"] == "updated proposal"


def test_queue_patch_non_editable_status_rejected(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_queue_patch should refuse to edit items not in pending/needs_revision status."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_state_dir)
    _write_state(tmp_state_dir, [{"id": "done-1", "title": "Done", "status": "done", "attempts": 1}])

    result = _queue_patch("done-1", {"title": "Hacked"})
    assert result["ok"] is False
    assert "cannot edit" in result["error"]


def test_queue_requeue_resets_status(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_queue_requeue flips status back to pending and tracks old status."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_state_dir)
    _write_state(
        tmp_state_dir,
        [{"id": "rq-1", "title": "Failed", "status": "failed:verify", "attempts": 2, "branch": "auto/rq-1-abc"}],
    )

    result = _queue_requeue("rq-1")
    assert result["ok"] is True
    assert result["was"] == "failed:verify"
    items = _read_items(tmp_state_dir)
    assert items[0]["status"] == "pending"
    assert items[0]["branch"] is None
    assert "auto/rq-1-abc" in items[0].get("previousBranches", [])


def test_queue_requeue_missing_returns_error(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_queue_requeue with non-existent id returns error."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_state_dir)
    _write_state(tmp_state_dir, [])

    result = _queue_requeue("nonexistent")
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# FIX C1: modelOverride validation in _queue_patch
# ---------------------------------------------------------------------------

def test_queue_patch_invalid_model_override_raises_value_error(
    tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Patching modelOverride with a bad value (a plain string) must raise ValueError."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_state_dir)
    _write_state(tmp_state_dir, [{"id": "mo-1", "title": "T", "status": "pending", "attempts": 0}])

    with pytest.raises(ValueError, match="modelOverride"):
        _queue_patch("mo-1", {"modelOverride": "bad-string"})


def test_queue_patch_valid_model_override_succeeds(
    tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Patching modelOverride with {provider, model} must succeed."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_state_dir)
    _write_state(tmp_state_dir, [{"id": "mo-2", "title": "T", "status": "pending", "attempts": 0}])

    result = _queue_patch("mo-2", {"modelOverride": {"provider": "a", "model": "m"}})
    assert result["ok"] is True
    items = _read_items(tmp_state_dir)
    assert items[0]["modelOverride"] == {"provider": "a", "model": "m"}


def test_queue_patch_null_model_override_clears_it(
    tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Patching modelOverride to null (None) must succeed and clear the field."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_state_dir)
    _write_state(
        tmp_state_dir,
        [{"id": "mo-3", "title": "T", "status": "pending", "attempts": 0,
          "modelOverride": {"provider": "x", "model": "y"}}],
    )

    result = _queue_patch("mo-3", {"modelOverride": None})
    assert result["ok"] is True
    items = _read_items(tmp_state_dir)
    assert items[0].get("modelOverride") is None
