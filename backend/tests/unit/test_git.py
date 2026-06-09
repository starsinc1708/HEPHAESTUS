"""Unit tests for git branch safety validation and task view."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.core.git import _is_safe_auto_branch
from app.core.iters import _task_view


def test_is_safe_auto_branch_valid() -> None:
    """Valid auto/ branch names should pass."""
    assert _is_safe_auto_branch("auto/test-branch") is True
    assert _is_safe_auto_branch("auto/feature_123") is True
    assert _is_safe_auto_branch("auto/my.branch") is True
    assert _is_safe_auto_branch("auto/a/b/c") is True


def test_is_safe_auto_branch_empty() -> None:
    """Empty string is rejected."""
    assert _is_safe_auto_branch("") is False


def test_is_safe_auto_branch_wrong_prefix() -> None:
    """Branches without auto/ prefix are rejected."""
    assert _is_safe_auto_branch("main") is False
    assert _is_safe_auto_branch("feature/test") is False
    assert _is_safe_auto_branch("origin/auto/test") is False


def test_is_safe_auto_branch_path_traversal() -> None:
    """Path traversal attempts are rejected."""
    assert _is_safe_auto_branch("auto/../etc/passwd") is False
    assert _is_safe_auto_branch("auto/..") is False


def test_is_safe_auto_branch_double_slash() -> None:
    """Double slashes are rejected."""
    assert _is_safe_auto_branch("auto//test") is False


def test_is_safe_auto_branch_leading_dash() -> None:
    """Branch names starting with - are rejected (flag injection)."""
    assert _is_safe_auto_branch("auto/-flag") is False


def test_is_safe_auto_branch_whitespace() -> None:
    """Whitespace in branch names is rejected."""
    assert _is_safe_auto_branch("auto/test branch") is False
    assert _is_safe_auto_branch("auto/test\tbranch") is False
    assert _is_safe_auto_branch("auto/test\nbranch") is False


def test_is_safe_auto_branch_null_byte() -> None:
    """NUL bytes are rejected."""
    assert _is_safe_auto_branch("auto/test\x00evil") is False


def test_is_safe_auto_branch_backslash() -> None:
    """Backslashes are rejected."""
    assert _is_safe_auto_branch("auto/test\\evil") is False


def test_is_safe_auto_branch_non_string() -> None:
    """Non-string input is rejected."""
    assert _is_safe_auto_branch(123) is False  # type: ignore[arg-type]
    assert _is_safe_auto_branch(None) is False  # type: ignore[arg-type]


def test_is_safe_auto_branch_too_long() -> None:
    """Branch names over 200 chars are rejected by the regex."""
    assert _is_safe_auto_branch("auto/" + "a" * 201) is False


def test_is_safe_auto_branch_prefix_only() -> None:
    """Just 'auto/' with nothing after is rejected."""
    assert _is_safe_auto_branch("auto/") is False


def test_task_view_missing_item(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_task_view returns error for non-existent item id."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path)
    (tmp_path / "work-state.json").write_text(json.dumps({"items": []}))

    result = _task_view("nonexistent")
    assert result["ok"] is False
    assert "not found" in result["error"]


def test_task_view_found_item(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_task_view returns item data for valid item id."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path)
    items = [{"id": "item-001", "title": "Test", "status": "done", "attempts": 1}]
    (tmp_path / "work-state.json").write_text(json.dumps({"items": items}))

    result = _task_view("item-001")
    assert result["ok"] is True
    assert result["item"]["id"] == "item-001"
    assert result["item"]["status"] == "done"


def test_task_view_includes_iters_and_cost(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_task_view should include iters list and cost aggregation."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path)
    items = [{"id": "t-1", "title": "T1", "status": "done", "attempts": 1, "lastIter": "iter-0001"}]
    (tmp_path / "work-state.json").write_text(json.dumps({"items": items}))

    result = _task_view("t-1")
    assert result["ok"] is True
    assert "iters" in result
    assert "cost" in result
    assert isinstance(result["cost"]["total"], int)
