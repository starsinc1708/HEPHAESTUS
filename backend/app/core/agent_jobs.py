"""AgentJobStore + start_agent_job — async background runner for agent tasks.

Pattern mirrors MergeJobStore / _next_merge_seq in app.core.merge_job.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.state import _atomic_write, _state_dir, _StateLock

_REGISTRY = "agent-jobs.json"
_MAX_KEEP = 50


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class AgentJob(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    kind: str
    status: str = "running"
    result: dict[str, Any] | None = None
    error: str | None = None
    output_dir: str = Field("", alias="outputDir")
    created_at: str | None = Field(None, alias="createdAt")
    updated_at: str | None = Field(None, alias="updatedAt")


# ---------------------------------------------------------------------------
# Sequencing
# ---------------------------------------------------------------------------


def _next_seq() -> int:
    """Return the next monotonically-increasing agent-job sequence number."""
    sd = _state_dir()
    nums: list[int] = []
    for p in sd.glob("ajob-*"):
        part = p.name.split("-", 1)[1] if "-" in p.name else ""
        if p.is_dir() and part.isdigit():
            nums.append(int(part))
    return (max(nums) + 1) if nums else 1


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class AgentJobStore:
    """Persist AgentJob records as a rolling JSON registry in the state dir."""

    def _path(self) -> pathlib.Path:
        return _state_dir() / _REGISTRY

    def list(self) -> list[AgentJob]:
        p = self._path()
        if not p.exists():
            return []
        raw = json.loads(p.read_text(encoding="utf-8") or '{"jobs": []}')
        return [AgentJob.model_validate(j) for j in raw.get("jobs", [])]

    def get(self, job_id: str) -> AgentJob | None:
        return next((j for j in self.list() if j.id == job_id), None)

    def put(self, job: AgentJob) -> None:
        with _StateLock():
            jobs = [j for j in self.list() if j.id != job.id]
            jobs.append(job)
            jobs = jobs[-_MAX_KEEP:]
            payload = json.dumps(
                {"jobs": [j.model_dump(by_alias=True) for j in jobs]},
                indent=2,
                ensure_ascii=False,
            )
            self._path().parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(self._path(), payload)


# ---------------------------------------------------------------------------
# Background runner
# ---------------------------------------------------------------------------


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def start_agent_job(
    kind: str,
    work: Callable[[pathlib.Path], Awaitable[dict[str, Any]]],
) -> AgentJob:
    """Create a background agent job, fire-and-forget the coroutine, return immediately.

    ``work`` receives the path to ``output.jsonl`` (already created, empty) and must
    return a result dict on success or raise on failure.
    """
    sd = _state_dir()
    seq = _next_seq()
    output_dir = f"ajob-{seq:04d}"
    job_dir = sd / output_dir
    job_dir.mkdir(parents=True, exist_ok=True)
    output_path = job_dir / "output.jsonl"
    output_path.write_text("", encoding="utf-8")

    store = AgentJobStore()
    job = AgentJob(
        id=f"ajob-{seq:04d}",
        kind=kind,
        status="running",
        output_dir=output_dir,
        created_at=_now(),
        updated_at=_now(),
    )
    store.put(job)

    async def _run() -> None:
        try:
            res = await work(output_path)
            job.status = "done"
            job.result = res
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error = str(exc)
        finally:
            job.updated_at = _now()
            AgentJobStore().put(job)

    asyncio.create_task(_run())
    return job
