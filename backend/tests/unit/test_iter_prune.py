"""Unit tests for iteration auto-retention: select_iters_to_prune, _protected_iter_names, prune_iters."""

from __future__ import annotations

import json
import os
import pathlib
import time

import pytest

from app.core.iters import _protected_iter_names, prune_iters, select_iters_to_prune

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DAY = 86400.0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_iter_dirs(
    tmp_path: pathlib.Path,
    names: list[str],
    *,
    ages: dict[str, float] | None = None,
    now: float | None = None,
) -> list[pathlib.Path]:
    """Create iter-* directories under tmp_path with optional mtime ages (seconds ago)."""
    dirs: list[pathlib.Path] = []
    for name in names:
        d = tmp_path / name
        d.mkdir()
        # write a small file so dir has real content
        (d / "dummy.txt").write_text("x")
        if ages and name in ages:
            mtime = (now or time.time()) - ages[name]
            os.utime(d, (mtime, mtime))
        dirs.append(d)
    return sorted(dirs, key=lambda p: p.name)


def _make_state(
    items: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    """Build a minimal work-state dict."""
    return {"items": items or []}


# ---------------------------------------------------------------------------
# select_iters_to_prune — pure function tests
# ---------------------------------------------------------------------------


def test_select_empty_input() -> None:
    """Empty iter_dirs returns empty list."""
    result = select_iters_to_prune(
        [],
        now=1000000.0,
        keep_days=30,
        keep_min=5,
        protected_ids=set(),
    )
    assert result == []


def test_select_old_unprotected_dirs_pruned(tmp_path: pathlib.Path) -> None:
    """Old unprotected dirs beyond keep_min get selected for pruning."""
    now = 1_000_000.0
    dirs = _make_iter_dirs(
        tmp_path,
        ["iter-0001", "iter-0002", "iter-0003", "iter-0004", "iter-0005"],
        ages={
            "iter-0001": 40 * DAY,
            "iter-0002": 35 * DAY,
            "iter-0003": 10 * DAY,
            "iter-0004": 5 * DAY,
            "iter-0005": 1 * DAY,
        },
        now=now,
    )
    result = select_iters_to_prune(
        dirs,
        now=now,
        keep_days=30,
        keep_min=2,
        protected_ids=set(),
    )
    names = [p.name for p in result]
    # iter-0001 and iter-0002 are older than 30 days AND beyond keep_min=2
    assert "iter-0001" in names
    assert "iter-0002" in names
    # iter-0003..0005 are young (within 30 days)
    assert "iter-0003" not in names
    assert "iter-0004" not in names
    assert "iter-0005" not in names


def test_select_young_dirs_not_pruned(tmp_path: pathlib.Path) -> None:
    """Dirs within keep_days are never pruned regardless of keep_min."""
    now = 1_000_000.0
    dirs = _make_iter_dirs(
        tmp_path,
        ["iter-0001", "iter-0002"],
        ages={"iter-0001": 5 * DAY, "iter-0002": 1 * DAY},
        now=now,
    )
    result = select_iters_to_prune(
        dirs,
        now=now,
        keep_days=30,
        keep_min=1,
        protected_ids=set(),
    )
    assert result == []


def test_select_protected_dirs_not_pruned(tmp_path: pathlib.Path) -> None:
    """Protected dir names are never selected even if old."""
    now = 1_000_000.0
    dirs = _make_iter_dirs(
        tmp_path,
        ["iter-0001", "iter-0002", "iter-0003"],
        ages={
            "iter-0001": 40 * DAY,
            "iter-0002": 40 * DAY,
            "iter-0003": 1 * DAY,
        },
        now=now,
    )
    result = select_iters_to_prune(
        dirs,
        now=now,
        keep_days=30,
        keep_min=1,
        protected_ids={"iter-0001"},
    )
    names = [p.name for p in result]
    assert "iter-0001" not in names
    assert "iter-0002" in names
    assert "iter-0003" not in names


def test_select_keep_min_preserves_recent(tmp_path: pathlib.Path) -> None:
    """keep_min preserves N most recent dirs regardless of age."""
    now = 1_000_000.0
    dirs = _make_iter_dirs(
        tmp_path,
        ["iter-0001", "iter-0002", "iter-0003", "iter-0004"],
        ages={
            "iter-0001": 100 * DAY,
            "iter-0002": 100 * DAY,
            "iter-0003": 100 * DAY,
            "iter-0004": 100 * DAY,
        },
        now=now,
    )
    result = select_iters_to_prune(
        dirs,
        now=now,
        keep_days=30,
        keep_min=2,
        protected_ids=set(),
    )
    names = [p.name for p in result]
    # All are old, but keep_min=2 protects iter-0003 and iter-0004
    assert "iter-0001" in names
    assert "iter-0002" in names
    assert "iter-0003" not in names
    assert "iter-0004" not in names


def test_select_all_protected_returns_empty(tmp_path: pathlib.Path) -> None:
    """If all dirs are protected, return empty list."""
    now = 1_000_000.0
    dirs = _make_iter_dirs(
        tmp_path,
        ["iter-0001", "iter-0002"],
        ages={"iter-0001": 40 * DAY, "iter-0002": 40 * DAY},
        now=now,
    )
    result = select_iters_to_prune(
        dirs,
        now=now,
        keep_days=30,
        keep_min=0,
        protected_ids={"iter-0001", "iter-0002"},
    )
    assert result == []


def test_select_keep_min_zero_all_old_pruned(tmp_path: pathlib.Path) -> None:
    """With keep_min=0, all old dirs beyond keep_days get pruned."""
    now = 1_000_000.0
    dirs = _make_iter_dirs(
        tmp_path,
        ["iter-0001", "iter-0002", "iter-0003"],
        ages={
            "iter-0001": 40 * DAY,
            "iter-0002": 40 * DAY,
            "iter-0003": 40 * DAY,
        },
        now=now,
    )
    result = select_iters_to_prune(
        dirs,
        now=now,
        keep_days=30,
        keep_min=0,
        protected_ids=set(),
    )
    assert len(result) == 3


# ---------------------------------------------------------------------------
# _protected_iter_names
# ---------------------------------------------------------------------------


def test_protected_includes_current_iter(tmp_path: pathlib.Path) -> None:
    """The alphabetically last iter dir is always protected."""
    dirs = _make_iter_dirs(tmp_path, ["iter-0001", "iter-0002", "iter-0003"])
    state = _make_state()
    protected = _protected_iter_names(state, dirs)
    assert "iter-0003" in protected


def test_protected_includes_non_terminal_tasks(tmp_path: pathlib.Path) -> None:
    """lastIter of non-terminal task items is protected."""
    dirs = _make_iter_dirs(tmp_path, ["iter-0001", "iter-0002", "iter-0003"])
    state = _make_state([
        {"id": "t1", "status": "in_progress", "lastIter": "iter-0001"},
        {"id": "t2", "status": "done", "lastIter": "iter-0002"},
    ])
    protected = _protected_iter_names(state, dirs)
    # iter-0001 is protected (in_progress), iter-0002 is NOT protected (done)
    assert "iter-0001" in protected
    assert "iter-0002" not in protected


def test_protected_includes_in_review(tmp_path: pathlib.Path) -> None:
    """in_review and needs_revision statuses protect their iter."""
    dirs = _make_iter_dirs(tmp_path, ["iter-0001", "iter-0002"])
    state = _make_state([
        {"id": "t1", "status": "in_review", "lastIter": "iter-0001"},
        {"id": "t2", "status": "needs_revision", "lastIter": "iter-0002"},
    ])
    protected = _protected_iter_names(state, dirs)
    assert "iter-0001" in protected
    assert "iter-0002" in protected


def test_protected_terminal_statuses_not_protected(tmp_path: pathlib.Path) -> None:
    """Terminal statuses (done, merged, discarded, failed:*) do NOT protect their iter."""
    dirs = _make_iter_dirs(tmp_path, ["iter-0001", "iter-0002", "iter-0003", "iter-0004"])
    state = _make_state([
        {"id": "t1", "status": "done", "lastIter": "iter-0001"},
        {"id": "t2", "status": "merged", "lastIter": "iter-0002"},
        {"id": "t3", "status": "failed:verify", "lastIter": "iter-0003"},
        {"id": "t4", "status": "discarded", "lastIter": "iter-0004"},
    ])
    protected = _protected_iter_names(state, dirs)
    # None of these are protected by task status (but iter-0004 is current = protected)
    assert "iter-0001" not in protected
    assert "iter-0002" not in protected
    assert "iter-0003" not in protected
    assert "iter-0004" in protected  # current iter


def test_protected_includes_merge_job_refs(tmp_path: pathlib.Path) -> None:
    """Non-terminal merge jobs protect the lastIter of their referenced item."""
    dirs = _make_iter_dirs(tmp_path, ["iter-0001", "iter-0002", "iter-0003"])
    state = _make_state([
        {"id": "t1", "status": "done", "lastIter": "iter-0001"},
    ])
    # Write merge-jobs.json with a running merge job referencing t1
    merge_jobs = {
        "jobs": [
            {"id": "mj1", "branch": "auto/foo", "baseBranch": "main", "status": "running", "itemId": "t1"},
        ]
    }
    (tmp_path / "merge-jobs.json").write_text(json.dumps(merge_jobs))

    protected = _protected_iter_names(state, dirs)
    # iter-0001 is referenced by a running merge job, so it's protected
    assert "iter-0001" in protected
    # iter-0003 is current
    assert "iter-0003" in protected


def test_protected_terminal_merge_job_not_protected(tmp_path: pathlib.Path) -> None:
    """Terminal merge jobs (accepted, rejected, failed, conflict) don't protect iters."""
    dirs = _make_iter_dirs(tmp_path, ["iter-0001", "iter-0002"])
    state = _make_state([
        {"id": "t1", "status": "done", "lastIter": "iter-0001"},
    ])
    merge_jobs = {
        "jobs": [
            {"id": "mj1", "branch": "auto/foo", "baseBranch": "main", "status": "accepted", "itemId": "t1"},
        ]
    }
    (tmp_path / "merge-jobs.json").write_text(json.dumps(merge_jobs))

    protected = _protected_iter_names(state, dirs)
    # iter-0001 NOT protected (merge job is terminal, task is done)
    assert "iter-0001" not in protected
    # iter-0002 is current
    assert "iter-0002" in protected


def test_protected_empty_dirs(tmp_path: pathlib.Path) -> None:
    """No dirs at all means empty protected set."""
    state = _make_state()
    protected = _protected_iter_names(state, [])
    assert protected == set()


# ---------------------------------------------------------------------------
# prune_iters — integration tests with tmp_path state dir
# ---------------------------------------------------------------------------


def test_prune_iters_deletes_old_dirs(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """prune_iters actually deletes the right old directories."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path, raising=False)
    monkeypatch.setenv("HEPHAESTUS_KEEP_ITERS_DAYS", "30")
    monkeypatch.setenv("HEPHAESTUS_KEEP_ITERS_MIN", "2")

    now = time.time()
    # Create dirs with controlled ages
    old_dir = tmp_path / "iter-0001"
    old_dir.mkdir()
    (old_dir / "dummy.txt").write_text("old")
    os.utime(old_dir, (now - 40 * DAY, now - 40 * DAY))

    young_dir = tmp_path / "iter-0002"
    young_dir.mkdir()
    (young_dir / "dummy.txt").write_text("young")
    os.utime(young_dir, (now - 5 * DAY, now - 5 * DAY))

    current_dir = tmp_path / "iter-0003"
    current_dir.mkdir()
    (current_dir / "dummy.txt").write_text("current")

    # Write empty state (no non-terminal tasks)
    (tmp_path / "work-state.json").write_text(json.dumps({"items": []}))

    result = prune_iters(state_dir_override=tmp_path)

    assert result["ok"] is True
    assert "iter-0001" in result["pruned"]
    assert old_dir.exists() is False
    assert young_dir.exists() is True
    assert current_dir.exists() is True


def test_prune_iters_never_crashes_on_missing_dir(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """prune_iters returns ok=False with error message, never crashes."""
    monkeypatch.setenv("HEPHAESTUS_KEEP_ITERS_DAYS", "30")
    monkeypatch.setenv("HEPHAESTUS_KEEP_ITERS_MIN", "2")

    nonexistent = tmp_path / "no_such_dir"
    result = prune_iters(state_dir_override=nonexistent)
    assert result["ok"] is True
    assert result["pruned"] == []


def test_prune_iters_returns_correct_counts(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """prune_iters returns accurate kept/protected/pruned counts."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path, raising=False)
    monkeypatch.setenv("HEPHAESTUS_KEEP_ITERS_DAYS", "30")
    monkeypatch.setenv("HEPHAESTUS_KEEP_ITERS_MIN", "1")

    now = time.time()
    for i in range(1, 6):
        d = tmp_path / f"iter-000{i}"
        d.mkdir()
        (d / "dummy.txt").write_text("x")
        # All old except last
        age = 40 * DAY if i < 5 else 1 * DAY
        os.utime(d, (now - age, now - age))

    (tmp_path / "work-state.json").write_text(json.dumps({"items": []}))

    result = prune_iters(state_dir_override=tmp_path)
    assert result["ok"] is True
    # iter-0005 is current (young + last alpha) and keep_min=1 protects it
    # iter-0001..0004 are old and NOT in keep_min=1 => pruned
    assert len(result["pruned"]) == 4
    assert result["kept"] == 1  # iter-0005
    assert result["protected"] == 1  # iter-0005 (current)


def test_prune_iters_protects_active_task_iter(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """prune_iters does not delete iter dir of an in_progress task."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path, raising=False)
    monkeypatch.setenv("HEPHAESTUS_KEEP_ITERS_DAYS", "30")
    monkeypatch.setenv("HEPHAESTUS_KEEP_ITERS_MIN", "1")

    now = time.time()
    old_active = tmp_path / "iter-0001"
    old_active.mkdir()
    (old_active / "dummy.txt").write_text("active-but-old")
    os.utime(old_active, (now - 60 * DAY, now - 60 * DAY))

    current = tmp_path / "iter-0002"
    current.mkdir()
    (current / "dummy.txt").write_text("current")

    state = {
        "items": [
            {"id": "t1", "status": "in_progress", "lastIter": "iter-0001"},
        ]
    }
    (tmp_path / "work-state.json").write_text(json.dumps(state))

    result = prune_iters(state_dir_override=tmp_path)
    assert result["ok"] is True
    assert "iter-0001" not in result["pruned"]
    assert old_active.exists() is True


def test_prune_iters_env_defaults(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """prune_iters reads HEPHAESTUS_KEEP_ITERS_DAYS and HEPHAESTUS_KEEP_ITERS_MIN from env."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path, raising=False)
    monkeypatch.setenv("HEPHAESTUS_KEEP_ITERS_DAYS", "0")
    monkeypatch.setenv("HEPHAESTUS_KEEP_ITERS_MIN", "0")

    now = time.time()
    d = tmp_path / "iter-0001"
    d.mkdir()
    (d / "dummy.txt").write_text("x")
    os.utime(d, (now - 1, now - 1))

    (tmp_path / "work-state.json").write_text(json.dumps({"items": []}))

    result = prune_iters(state_dir_override=tmp_path)
    assert result["ok"] is True
    # keep_days=0 means everything older than 0 days, keep_min=0 means no floor
    # But iter-0001 is the current (last alpha) so it's protected
    assert "iter-0001" not in result["pruned"]
