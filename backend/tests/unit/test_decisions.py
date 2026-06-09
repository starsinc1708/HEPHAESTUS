"""Unit tests for decisions log functions."""

from __future__ import annotations

import pathlib

import pytest

from app.core.decisions import _append_decision, _read_decisions


def test_append_decision_creates_log_file(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_append_decision creates the decisions.log file if it doesn't exist."""
    import app.core.state as state_mod

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", state_dir, raising=False)

    _append_decision("human", "merge", "auto/test-branch", "ok", "merged successfully")

    log_path = state_dir / "decisions.log"
    assert log_path.exists()
    content = log_path.read_text()
    assert "human" in content
    assert "merge" in content
    assert "auto/test-branch" in content
    assert "ok" in content
    assert "merged successfully" in content


def test_append_decision_appends_multiple(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Multiple _append_decision calls append lines to the log."""
    import app.core.state as state_mod

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", state_dir, raising=False)

    _append_decision("human", "merge", "branch-a", "ok")
    _append_decision("machine", "requeue", "branch-b", "ok", "retry")

    content = (state_dir / "decisions.log").read_text()
    lines = [ln for ln in content.splitlines() if ln.strip()]
    assert len(lines) == 2


def test_read_decisions_returns_entries(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_read_decisions returns parsed decision entries."""
    import app.core.state as state_mod

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", state_dir, raising=False)

    _append_decision("human", "merge", "auto/x", "ok", "test")
    _append_decision("machine", "requeue", "auto/y", "ok", "retry")

    entries = _read_decisions(limit=10)
    assert len(entries) == 2
    assert entries[0]["actor"] == "human"
    assert entries[0]["action"] == "merge"
    assert entries[1]["actor"] == "machine"


def test_read_decisions_with_no_log_file(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_read_decisions returns empty list when no log file exists."""
    import app.core.state as state_mod

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", state_dir, raising=False)

    entries = _read_decisions()
    assert entries == []


def test_read_decisions_respects_limit(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_read_decisions returns at most `limit` entries."""
    import app.core.state as state_mod

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", state_dir, raising=False)

    for i in range(10):
        _append_decision("actor", f"action-{i}", f"branch-{i}", "ok")

    entries = _read_decisions(limit=3)
    assert len(entries) == 3
    # Should return the LAST 3 entries
    assert entries[-1]["branch"] == "branch-9"


def test_read_decisions_ignores_malformed_lines(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_read_decisions silently skips lines with fewer than 5 tab-separated fields."""
    import app.core.state as state_mod

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", state_dir, raising=False)

    _append_decision("human", "merge", "auto/x", "ok", "good")
    # Manually append a malformed line
    with (state_dir / "decisions.log").open("a") as f:
        f.write("bad_line_no_tabs\n")

    entries = _read_decisions()
    assert len(entries) == 1
    assert entries[0]["actor"] == "human"
