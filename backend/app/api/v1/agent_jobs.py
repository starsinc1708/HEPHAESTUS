"""Agent-jobs API router.

GET  /api/v1/agent-jobs/{job_id}         — fetch job status
GET  /api/v1/agent-jobs/{job_id}/stream  — SSE stream of job output
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.agent_jobs import AgentJobStore
from app.core.state import _state_dir

router = APIRouter()

_JOB_ID_RE = re.compile(r"^ajob-\d+$")


@router.get("/api/v1/agent-jobs/{job_id}", response_model=None)
def get_agent_job(job_id: str) -> dict[str, Any] | JSONResponse:
    """Fetch the status of an agent job by id."""
    if not _JOB_ID_RE.match(job_id):
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid job id"})
    job = AgentJobStore().get(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "job not found"})
    return {"ok": True, **job.model_dump(by_alias=True)}


@router.get("/api/v1/agent-jobs/{job_id}/stream")
async def agent_job_stream(job_id: str, request: Request) -> StreamingResponse:
    """SSE stream for an agent job.

    Tails ``<state>/ajob-NNNN/output.jsonl`` and emits summarized events.
    Done when job status leaves "running" and file is stable for >=2s.
    Cap: 1800s.
    """
    if not _JOB_ID_RE.match(job_id):
        return StreamingResponse(
            _error_stream("invalid job id"),
            media_type="text/event-stream",
            status_code=400,
        )

    from app.core.events import _summarize_event

    jp = _state_dir() / job_id / "output.jsonl"
    terminal = {"done", "failed"}

    async def gen() -> AsyncIterator[str]:
        idx = 0
        offset = 0
        buf = b""
        idle = 0.0
        started = time.monotonic()
        yield ": connected\n\n"
        while True:
            if await request.is_disconnected() or (time.monotonic() - started) > 1800:
                break
            grew = False
            if jp.exists() and jp.stat().st_size > offset:
                with jp.open("rb") as f:
                    f.seek(offset)
                    chunk = f.read()
                offset += len(chunk)
                buf += chunk
                parts = buf.split(b"\n")
                buf = parts.pop()
                for raw in parts:
                    line = raw.strip()
                    idx += 1
                    if not line:
                        continue
                    try:
                        obj = json.loads(line.decode("utf-8", "replace"))
                    except ValueError:
                        continue
                    yield (
                        f"data: {json.dumps(_summarize_event(obj, idx=idx - 1), ensure_ascii=False)}\n\n"
                    )
                grew = True
            idle = 0.0 if grew else idle + 0.5
            job = AgentJobStore().get(job_id)
            if idle >= 2.0 and (job is None or job.status in terminal):
                yield "event: done\ndata: {}\n\n"
                break
            if not grew:
                yield ": keepalive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _error_stream(msg: str) -> AsyncIterator[str]:
    yield f"data: {json.dumps({'error': msg})}\n\n"
