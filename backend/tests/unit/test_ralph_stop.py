"""Unit tests for RunSummary + should_stop predicate (C1)."""

from __future__ import annotations

import app.core.state as state
from app.core.run_summary import RunSummary, RunSummaryStore, should_stop


def test_stop_on_cost_budget():
    stop, reason = should_stop(
        RunSummary(cost_usd=5.0),
        cost_budget=4.0,
        deadline_ms=None,
        max_consec_fail=4,
        now_ms=0,
    )
    assert stop and "cost" in reason


def test_stop_on_consec_fail():
    stop, reason = should_stop(
        RunSummary(consec_fail=4),
        cost_budget=0,
        deadline_ms=None,
        max_consec_fail=4,
        now_ms=0,
    )
    assert stop and "consec" in reason


def test_stop_on_wallclock():
    stop, reason = should_stop(
        RunSummary(),
        cost_budget=0,
        deadline_ms=100,
        max_consec_fail=4,
        now_ms=200,
    )
    assert stop and ("wall" in reason or "time" in reason)


def test_no_stop_under_limits():
    stop, _ = should_stop(
        RunSummary(cost_usd=1.0, consec_fail=1),
        cost_budget=4.0,
        deadline_ms=1000,
        max_consec_fail=4,
        now_ms=200,
    )
    assert not stop


def test_cost_off_when_zero():
    stop, _ = should_stop(
        RunSummary(cost_usd=999.0),
        cost_budget=0,
        deadline_ms=None,
        max_consec_fail=0,
        now_ms=0,
    )
    assert not stop


def test_consec_off_when_zero():
    stop, _ = should_stop(
        RunSummary(consec_fail=999),
        cost_budget=0,
        deadline_ms=None,
        max_consec_fail=0,
        now_ms=0,
    )
    assert not stop


def test_deadline_none_means_off():
    stop, _ = should_stop(
        RunSummary(),
        cost_budget=0,
        deadline_ms=None,
        max_consec_fail=0,
        now_ms=999999,
    )
    assert not stop


def test_run_summary_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    store = RunSummaryStore()
    assert store.get() is None

    summary = RunSummary(run_mode="ralph", cost_usd=1.23, items_done=5, consec_fail=1)
    store.put(summary)

    loaded = store.get()
    assert loaded is not None
    assert loaded.run_mode == "ralph"
    assert abs(loaded.cost_usd - 1.23) < 1e-9
    assert loaded.items_done == 5
    assert loaded.consec_fail == 1


def test_run_summary_camel_aliases():
    """model_dump(by_alias=True) uses camelCase keys."""
    s = RunSummary(run_mode="ralph", items_done=3, consec_fail=2, cost_usd=0.5)
    d = s.model_dump(by_alias=True)
    assert "runMode" in d
    assert "itemsDone" in d
    assert "consecFail" in d
    assert "costUsd" in d
    assert "stoppedReason" in d
    assert "endedAtMs" in d  # FEAT-005


def test_run_history_archive_and_list(tmp_path, monkeypatch):
    """FEAT-005: archived runs persist append-order (newest last) and round-trip."""
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    from app.core.run_summary import RunHistoryStore

    hist = RunHistoryStore()
    assert hist.list() == []
    assert hist.archive(RunSummary(run_mode="ralph", items_done=2)) is True
    assert hist.archive(RunSummary(run_mode="queue", items_failed=1)) is True

    runs = hist.list()
    assert len(runs) == 2
    assert runs[0].run_mode == "ralph"      # append order: first archived is first
    assert runs[1].items_failed == 1


def test_run_history_skips_noop_runs(tmp_path, monkeypatch):
    """A run that processed nothing (empty driver cycle) must not pollute history."""
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    from app.core.run_summary import RunHistoryStore

    hist = RunHistoryStore()
    assert hist.archive(RunSummary(run_mode="queue", items_done=0, items_failed=0)) is False
    assert hist.list() == []


def test_run_history_rolling_cap(tmp_path, monkeypatch):
    """History is bounded by _MAX_HISTORY; the oldest records drop off."""
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    from app.core.run_summary import _MAX_HISTORY, RunHistoryStore

    hist = RunHistoryStore()
    for i in range(_MAX_HISTORY + 10):
        hist.archive(RunSummary(run_mode="queue", items_done=1, cost_usd=float(i)))

    runs = hist.list()
    assert len(runs) == _MAX_HISTORY
    # Newest retained, oldest dropped.
    assert abs(runs[-1].cost_usd - float(_MAX_HISTORY + 10 - 1)) < 1e-9
    assert abs(runs[0].cost_usd - 10.0) < 1e-9
