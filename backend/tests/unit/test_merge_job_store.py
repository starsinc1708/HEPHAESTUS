"""Unit tests for MergeJobStore + _next_merge_seq (Task 3)."""
from __future__ import annotations

import app.core.state as state
from app.core.merge_job import MergeJobStore, _next_merge_seq
from app.models.merge import MergeJob, MergeJobStatus


def test_next_merge_seq_monotonic(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    (tmp_path / "merge-0001").mkdir()
    (tmp_path / "merge-0007").mkdir()
    assert _next_merge_seq() == 8


def test_next_merge_seq_empty(tmp_path, monkeypatch):
    """No existing dirs → starts at 1."""
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    assert _next_merge_seq() == 1


def test_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    store = MergeJobStore()
    job = MergeJob(
        id="merge-0001",
        branch="auto/x",
        base_branch="main",
        status=MergeJobStatus.RUNNING,
    )
    store.put(job)
    assert store.get("merge-0001").branch == "auto/x"

    job.status = MergeJobStatus.RESOLVED
    store.put(job)
    assert store.get("merge-0001").status is MergeJobStatus.RESOLVED
    assert any(j.id == "merge-0001" for j in store.list())

    # active() returns the single non-terminal job — RESOLVED is non-terminal (awaiting decision)
    assert store.active() is not None
    assert store.active().id == "merge-0001"


def test_store_active_none_after_terminal(tmp_path, monkeypatch):
    """After a terminal status, active() must return None."""
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    store = MergeJobStore()
    job = MergeJob(
        id="merge-0001",
        branch="auto/x",
        base_branch="main",
        status=MergeJobStatus.RUNNING,
    )
    store.put(job)

    for terminal in (MergeJobStatus.ACCEPTED, MergeJobStatus.REJECTED,
                     MergeJobStatus.FAILED, MergeJobStatus.CONFLICT):
        job.status = terminal
        store.put(job)
        assert store.active() is None, f"active() should be None when status={terminal}"


def test_store_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    store = MergeJobStore()
    assert store.get("merge-9999") is None


def test_store_list_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    assert MergeJobStore().list() == []
