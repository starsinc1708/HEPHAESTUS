"""Unit tests for helper functions: _summarize, _all_iter_dirs, _load_json."""

from __future__ import annotations

import pathlib

import pytest

from app.core.helpers import _all_iter_dirs, _load_json, _summarize


def test_summarize_with_empty_state() -> None:
    """_summarize with None state returns zero counts."""
    result = _summarize(None)
    assert result["total"] == 0
    assert result["pending"] == 0
    assert result["percent_done"] == 0


def test_summarize_with_empty_items() -> None:
    """_summarize with empty items list returns zero counts."""
    result = _summarize({"items": []})
    assert result["total"] == 0


def test_summarize_with_mixed_statuses() -> None:
    """_summarize correctly buckets items by status."""
    state = {
        "items": [
            {"status": "pending"},
            {"status": "pending"},
            {"status": "in_progress"},
            {"status": "done"},
            {"status": "merged"},
            {"status": "failed:verify"},
            {"status": "failed:opencode"},
            {"status": "discarded"},
            {"status": "needs_revision"},
        ]
    }
    result = _summarize(state)
    assert result["pending"] == 2
    assert result["in_progress"] == 1
    assert result["done"] == 1
    assert result["merged"] == 1
    assert result["discarded"] == 1
    assert result["needs_revision"] == 1
    assert result["failed_total"] == 2
    assert result["failed_breakdown"]["verify"] == 1
    assert result["failed_breakdown"]["opencode"] == 1
    assert result["total"] == 9


def test_summarize_percent_done() -> None:
    """_summarize computes percent_done as (done+merged)/total."""
    state = {"items": [{"status": "done"}, {"status": "done"}, {"status": "pending"}]}
    result = _summarize(state)
    assert result["percent_done"] == 66  # 2/3 * 100 = 66


def test_summarize_percent_done_100() -> None:
    """_summarize with all done returns 100%."""
    state = {"items": [{"status": "done"}, {"status": "merged"}]}
    result = _summarize(state)
    assert result["percent_done"] == 100


def test_all_iter_dirs_no_state_dir(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_all_iter_dirs returns empty list when state dir doesn't exist."""
    import app.core.helpers as helpers_mod

    monkeypatch.setattr(helpers_mod, "STATE_DIR", tmp_path / "nonexistent")
    assert _all_iter_dirs() == []


def test_all_iter_dirs_with_iters(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_all_iter_dirs finds and sorts iter directories."""
    import app.core.state as state_mod

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "iter-0003").mkdir()
    (state_dir / "iter-0001").mkdir()
    (state_dir / "iter-0002").mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", state_dir, raising=False)

    dirs = _all_iter_dirs()
    assert len(dirs) == 3
    assert dirs[0].name == "iter-0001"
    assert dirs[2].name == "iter-0003"


def test_load_json_valid_file(tmp_path: pathlib.Path) -> None:
    """_load_json parses a valid JSON file."""
    p = tmp_path / "test.json"
    p.write_text('{"key": "value"}')
    result = _load_json(p)
    assert result == {"key": "value"}


def test_load_json_missing_file(tmp_path: pathlib.Path) -> None:
    """_load_json returns None for missing file."""
    result = _load_json(tmp_path / "nonexistent.json")
    assert result is None


def test_load_json_invalid_json(tmp_path: pathlib.Path) -> None:
    """_load_json returns None for invalid JSON."""
    p = tmp_path / "bad.json"
    p.write_text("not json {{{")
    result = _load_json(p)
    assert result is None


def test_load_json_empty_file(tmp_path: pathlib.Path) -> None:
    """_load_json returns None for empty file."""
    p = tmp_path / "empty.json"
    p.write_text("")
    result = _load_json(p)
    assert result is None


def test_summarize_default_status_is_pending() -> None:
    """Items without status field default to pending."""
    state = {"items": [{"id": "x"}]}
    result = _summarize(state)
    assert result["pending"] == 1


def test_summarize_counts_queued() -> None:
    """Auto-driver #3: queued items get their own bucket and count toward total."""
    state = {
        "items": [
            {"status": "queued"},
            {"status": "queued"},
            {"status": "pending"},
        ]
    }
    result = _summarize(state)
    assert result["queued"] == 2
    assert result["pending"] == 1
    assert result["total"] == 3
