"""Unit tests for AgentJobStore + _next_seq + start_agent_job."""
from __future__ import annotations

import asyncio
import pathlib

import pytest

import app.core.state as state_mod  # noqa: E402

# ---------------------------------------------------------------------------
# Store round-trip
# ---------------------------------------------------------------------------


def test_store_roundtrip(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    from app.core.agent_jobs import AgentJob, AgentJobStore

    store = AgentJobStore()
    job = AgentJob(id="ajob-0001", kind="map")
    store.put(job)

    fetched = store.get("ajob-0001")
    assert fetched is not None
    assert fetched.kind == "map"
    assert fetched.status == "running"

    job.status = "done"
    job.result = {"count": 5}
    store.put(job)

    updated = store.get("ajob-0001")
    assert updated is not None
    assert updated.status == "done"
    assert updated.result == {"count": 5}
    assert any(j.id == "ajob-0001" for j in store.list())


def test_store_missing_returns_none(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    from app.core.agent_jobs import AgentJobStore

    assert AgentJobStore().get("ajob-9999") is None


def test_store_list_empty(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    from app.core.agent_jobs import AgentJobStore

    assert AgentJobStore().list() == []


# ---------------------------------------------------------------------------
# _next_seq monotonic
# ---------------------------------------------------------------------------


def test_next_seq_monotonic(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    (tmp_path / "ajob-0001").mkdir()
    (tmp_path / "ajob-0007").mkdir()

    from app.core.agent_jobs import _next_seq

    assert _next_seq() == 8


def test_next_seq_empty(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    from app.core.agent_jobs import _next_seq

    assert _next_seq() == 1


# ---------------------------------------------------------------------------
# start_agent_job — happy path
# ---------------------------------------------------------------------------


async def test_start_agent_job_happy(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    from app.core.agent_jobs import AgentJobStore, start_agent_job

    async def work(output_path: pathlib.Path) -> dict:
        output_path.write_text('{"type":"text","text":"hi"}\n', encoding="utf-8")
        return {"x": 1}

    job = start_agent_job("map", work)
    assert job.status == "running"
    assert job.id.startswith("ajob-")

    # Drain all background tasks so _run() completes
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    store = AgentJobStore()
    done = store.get(job.id)
    assert done is not None
    assert done.status == "done"
    assert done.result == {"x": 1}

    # output.jsonl must exist (created by start_agent_job before the task runs)
    output_jsonl = tmp_path / job.output_dir / "output.jsonl"
    assert output_jsonl.exists()


# ---------------------------------------------------------------------------
# start_agent_job — failure path
# ---------------------------------------------------------------------------


async def test_start_agent_job_failure(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    from app.core.agent_jobs import AgentJobStore, start_agent_job

    async def bad_work(output_path: pathlib.Path) -> dict:
        raise ValueError("agent exploded")

    job = start_agent_job("ideas", bad_work)
    assert job.status == "running"

    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    store = AgentJobStore()
    failed = store.get(job.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error is not None
    assert "agent exploded" in failed.error
    # Must NOT re-raise — no exception from gather above
