"""Tests for transient failure classifier."""
from __future__ import annotations

import pathlib

from app.core.transient import classify_failure


def test_empty_output_is_transient(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "output.jsonl"
    # Output doesn't exist
    r = classify_failure(1, out, None)
    assert r.is_transient is True
    assert "empty" in r.reason or "crash" in r.reason


def test_timeout_is_transient(tmp_path: pathlib.Path) -> None:
    r = classify_failure(-1, None, None)
    assert r.is_transient is True
    assert "timeout" in r.reason


def test_network_error_is_transient(tmp_path: pathlib.Path) -> None:
    stderr = tmp_path / "agent.stderr.txt"
    stderr.write_text("Error: ECONNRESET while connecting", encoding="utf-8")
    out = tmp_path / "output.jsonl"
    # Empty output file
    out.write_text("", encoding="utf-8")
    r = classify_failure(1, out, stderr)
    assert r.is_transient is True
    assert "econnreset" in r.reason.lower()


def test_worktree_lock_is_transient(tmp_path: pathlib.Path) -> None:
    stderr = tmp_path / "agent.stderr.txt"
    stderr.write_text("fatal: worktree already locked", encoding="utf-8")
    out = tmp_path / "output.jsonl"
    out.write_text("", encoding="utf-8")
    r = classify_failure(1, out, stderr)
    assert r.is_transient is True


def test_rate_limit_is_transient(tmp_path: pathlib.Path) -> None:
    stderr = tmp_path / "agent.stderr.txt"
    stderr.write_text("HTTP 429 rate limit exceeded", encoding="utf-8")
    out = tmp_path / "output.jsonl"
    out.write_text("", encoding="utf-8")
    r = classify_failure(1, out, stderr)
    assert r.is_transient is True


def test_benign_lock_mention_not_transient(tmp_path: pathlib.Path) -> None:
    """A real failure whose stderr merely mentions 'deadlock'/'worktree' must NOT be
    promoted to transient (the narrowed patterns). Output is small-but-non-empty so it
    bypasses the empty-output crash heuristic."""
    stderr = tmp_path / "agent.stderr.txt"
    stderr.write_text("Error: deadlock detected in user logic; preparing worktree", encoding="utf-8")
    out = tmp_path / "output.jsonl"
    out.write_text("partial result\n" * 5, encoding="utf-8")  # non-empty, < 500 bytes
    r = classify_failure(1, out, stderr)
    assert r.is_transient is False


def test_nonempty_output_not_transient(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "output.jsonl"
    out.write_text("x" * 1000, encoding="utf-8")  # Substantial output
    r = classify_failure(1, out, None)
    assert r.is_transient is False
    assert "output" in r.reason


def test_success_exit_not_classified(tmp_path: pathlib.Path) -> None:
    """exit_code=0 should not be passed to classify, but if it is, don't crash."""
    out = tmp_path / "output.jsonl"
    out.write_text("ok", encoding="utf-8")
    r = classify_failure(0, out, None)
    # With output, it's 'not transient'
    assert r.is_transient is False
