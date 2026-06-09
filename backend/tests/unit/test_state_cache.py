"""PERF-002: build_state() cache with mtime-based invalidation."""

from __future__ import annotations

import pathlib
import time

import pytest

import app.core.iters as iters_mod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iter_dirs_from(base: pathlib.Path) -> list[pathlib.Path]:
    """Return sorted iter-* dirs under *base*."""
    return sorted(base.glob("iter-*"), key=lambda p: p.name)


def _setup_state_dir(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point _state_dir() at tmp_path, patch _all_iter_dirs, and reset cache."""
    monkeypatch.setattr(iters_mod, "_state_dir", lambda: tmp_path)
    # _all_iter_dirs is imported from helpers — patch on iters_mod so both
    # _compute_cache_key and _build_state_uncached use tmp_path.
    monkeypatch.setattr(iters_mod, "_all_iter_dirs", lambda: _iter_dirs_from(tmp_path))
    # Reset module-level cache between tests
    iters_mod._state_cache = None  # type: ignore[attr-defined]
    iters_mod._cache_key = None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 1. Cache hit on repeat call
# ---------------------------------------------------------------------------


def test_cache_hit_on_repeat_call(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two consecutive build_state() calls — second returns cached result."""
    _setup_state_dir(tmp_path, monkeypatch)

    call_count = 0

    def _fake_uncached() -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        return {"updatedAt": "t", "items": []}

    monkeypatch.setattr(iters_mod, "_build_state_uncached", _fake_uncached)

    # Populate an iter dir so the cache key is stable
    (tmp_path / "iter-0001").mkdir()

    result1 = iters_mod.build_state()
    result2 = iters_mod.build_state()

    assert call_count == 1, "Expected exactly one _build_state_uncached call"
    assert result1 is result2, "Second call should return the same cached object"


# ---------------------------------------------------------------------------
# 2. Cache miss when new iter dir is created
# ---------------------------------------------------------------------------


def test_cache_miss_on_new_iter_dir(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After new iter dir is created, next build_state() rebuilds."""
    _setup_state_dir(tmp_path, monkeypatch)

    call_count = 0

    def _fake_uncached() -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        return {"updatedAt": f"t{call_count}", "items": []}

    monkeypatch.setattr(iters_mod, "_build_state_uncached", _fake_uncached)

    (tmp_path / "iter-0001").mkdir()
    iters_mod.build_state()
    assert call_count == 1

    # Create a new iter dir — changes the iter dir list + mtime
    time.sleep(0.05)  # ensure mtime differs on slow filesystems
    (tmp_path / "iter-0002").mkdir()

    iters_mod.build_state()
    assert call_count == 2, "Should rebuild after new iter dir"


# ---------------------------------------------------------------------------
# 3. Cache miss when work-state.json is modified
# ---------------------------------------------------------------------------


def test_cache_miss_on_work_state_change(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After work-state.json is modified, next build_state() rebuilds."""
    _setup_state_dir(tmp_path, monkeypatch)

    call_count = 0

    def _fake_uncached() -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        return {"updatedAt": f"t{call_count}", "items": []}

    monkeypatch.setattr(iters_mod, "_build_state_uncached", _fake_uncached)

    (tmp_path / "iter-0001").mkdir()
    ws = tmp_path / "work-state.json"
    ws.write_text('{"items": []}', encoding="utf-8")

    iters_mod.build_state()
    assert call_count == 1

    # Modify work-state.json — changes its mtime
    time.sleep(0.05)
    ws.write_text('{"items": [{"id": "x"}]}', encoding="utf-8")

    iters_mod.build_state()
    assert call_count == 2, "Should rebuild after work-state.json change"


# ---------------------------------------------------------------------------
# 4. Explicit invalidation forces rebuild
# ---------------------------------------------------------------------------


def test_invalidate_state_cache_forces_rebuild(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """invalidate_state_cache() → next build_state() rebuilds regardless."""
    _setup_state_dir(tmp_path, monkeypatch)

    call_count = 0

    def _fake_uncached() -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        return {"updatedAt": f"t{call_count}", "items": []}

    monkeypatch.setattr(iters_mod, "_build_state_uncached", _fake_uncached)

    (tmp_path / "iter-0001").mkdir()

    iters_mod.build_state()
    assert call_count == 1

    # Nothing changed on disk, but explicit invalidation
    iters_mod.invalidate_state_cache()

    iters_mod.build_state()
    assert call_count == 2, "Should rebuild after explicit invalidation"


# ---------------------------------------------------------------------------
# 5. Empty state dir — cache still works
# ---------------------------------------------------------------------------


def test_cache_works_with_empty_state_dir(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cache hit even when no iter dirs exist."""
    _setup_state_dir(tmp_path, monkeypatch)

    call_count = 0

    def _fake_uncached() -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        return {"updatedAt": "t", "items": [], "totals": {"tokens": 0, "iters": 0}}

    monkeypatch.setattr(iters_mod, "_build_state_uncached", _fake_uncached)

    # No iter dirs, no work-state.json
    result1 = iters_mod.build_state()
    result2 = iters_mod.build_state()

    assert call_count == 1
    assert result1 is result2


# ---------------------------------------------------------------------------
# 6. Never stale: returned state reflects actual changes
# ---------------------------------------------------------------------------


def test_never_stale_after_iter_dir_added(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Adding an iter dir causes build_state() to return updated iter count."""
    _setup_state_dir(tmp_path, monkeypatch)

    # Use the real _build_state_uncached but mock its expensive sub-calls
    monkeypatch.setattr(iters_mod, "_read_state", lambda: {"items": []})
    monkeypatch.setattr(iters_mod, "_load_json", lambda p: None)
    monkeypatch.setattr(iters_mod, "_current_iter_block", lambda: None)
    monkeypatch.setattr(iters_mod, "_summarize", lambda s: {})
    monkeypatch.setattr(iters_mod, "_log_tail", lambda: "")
    monkeypatch.setattr(iters_mod, "_read_decisions", lambda limit=20: [])
    monkeypatch.setattr(iters_mod, "_run", lambda *a, **kw: "")
    monkeypatch.setattr(iters_mod, "_git_branches", lambda: [])
    monkeypatch.setattr(iters_mod, "_git_recent_commits", lambda: [])
    monkeypatch.setattr(iters_mod, "_loop_status", lambda: {})
    monkeypatch.setattr(iters_mod, "_config_effective", lambda: {})
    monkeypatch.setattr(
        iters_mod, "_active_git", lambda: (str(tmp_path), "main", "origin", "auto")
    )
    # _iter_cost returns token totals per iter dir
    monkeypatch.setattr(
        iters_mod,
        "_iter_cost",
        lambda d: {"total": 0, "input": 0, "output": 0, "reasoning": 0},
    )

    # Initially: 1 iter dir
    (tmp_path / "iter-0001").mkdir()

    state1 = iters_mod.build_state()
    assert state1["totals"]["iters"] == 1

    # Add another iter dir
    time.sleep(0.05)
    (tmp_path / "iter-0002").mkdir()

    state2 = iters_mod.build_state()
    assert state2["totals"]["iters"] == 2, "Cache should not return stale data"
