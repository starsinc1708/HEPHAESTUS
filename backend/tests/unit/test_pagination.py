"""PERF-003: offset/limit pagination helper."""

from __future__ import annotations

from app.core.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    clamp_limit,
    clamp_offset,
    paginate,
)


def test_default_returns_everything_with_meta():
    items = list(range(10))
    window, meta = paginate(items)
    assert window == items
    assert meta == {"total": 10, "offset": 0, "limit": DEFAULT_LIMIT}


def test_window_slices_offset_and_limit():
    items = list(range(100))
    window, meta = paginate(items, offset=20, limit=5)
    assert window == [20, 21, 22, 23, 24]
    assert meta == {"total": 100, "offset": 20, "limit": 5}


def test_offset_past_end_yields_empty_window_not_error():
    window, meta = paginate(list(range(5)), offset=999, limit=10)
    assert window == []
    assert meta["total"] == 5  # total still reflects the full list


def test_negative_offset_clamped_to_zero():
    assert clamp_offset(-3) == 0
    assert clamp_offset(None) == 0
    assert clamp_offset(7) == 7


def test_limit_clamping():
    assert clamp_limit(None) == DEFAULT_LIMIT
    assert clamp_limit(0) == DEFAULT_LIMIT
    assert clamp_limit(-5) == DEFAULT_LIMIT
    assert clamp_limit(10) == 10
    assert clamp_limit(99_999) == MAX_LIMIT


def test_does_not_mutate_input():
    items = [1, 2, 3]
    paginate(items, offset=1, limit=1)
    assert items == [1, 2, 3]
