"""Insights API — Epic 4 (C2).

POST /api/v1/insights/ask                — run a read-only agentic question
GET  /api/v1/insights/sessions           — list all sessions
GET  /api/v1/insights/sessions/{id}      — fetch one session
POST /api/v1/insights/rebuild-map        — rebuild the codebase map
GET  /api/v1/insights/{iter_dir}/stream  — SSE stream for an insights run
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.core.agent_jobs import start_agent_job
from app.core.pagination import MAX_LIMIT, paginate
from app.core.scan import _build_runner
from app.core.state import _state_dir
from app.services.codebase_map import build_map
from app.services.insights import InsightsStore, ask

if TYPE_CHECKING:
    from app.models.workspace import RepoProfile

router = APIRouter()

_ITER_DIR_RE = re.compile(r"^insights-\d+$")


class _AskRequest(BaseModel):
    question: str
    sessionId: str | None = None


class NoActiveWorkspace(RuntimeError):
    """Raised when no workspace is active or the registry is unavailable."""

    def __init__(self, message: str = "no active workspace") -> None:
        super().__init__(message)


def active_workspace() -> RepoProfile:
    """Resolve the active workspace."""
    try:
        from app.core.workspaces import active_workspace as _aw
    except ImportError as exc:
        raise NoActiveWorkspace("workspace registry unavailable") from exc
    ws = _aw()
    if ws is None:
        raise NoActiveWorkspace("no active workspace")
    return ws


@router.post("/api/v1/insights/ask", response_model=None)
def insights_ask(body: _AskRequest) -> dict[str, Any] | JSONResponse:
    """Run a read-only agentic question against the codebase.

    This is a SYNC def — FastAPI runs it in a threadpool with no running event
    loop, so asyncio.run() is safe here. Do NOT convert this handler to ``async def``.
    """
    try:
        ws = active_workspace()
    except NoActiveWorkspace as exc:
        return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})

    runner = _build_runner(ws)
    result = asyncio.run(
        ask(ws, body.question, session_id=body.sessionId, runner=runner)
    )
    return {"ok": True, **result}


@router.get("/api/v1/insights/sessions", response_model=None)
def list_sessions(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=0, ge=0, le=MAX_LIMIT),
) -> dict[str, Any]:
    """List insights sessions. PERF-003: opt-in offset/limit window; omit both to
    get all (already capped on disk). ``total`` reports the full count."""
    sessions = InsightsStore().list()
    window, meta = paginate(sessions, offset, limit)
    return {"ok": True, "sessions": [s.model_dump(by_alias=True) for s in window], **meta}


@router.get("/api/v1/insights/sessions/{session_id}", response_model=None)
def get_session(session_id: str) -> dict[str, Any] | JSONResponse:
    """Fetch a single insights session by id."""
    session = InsightsStore().get(session_id)
    if session is None:
        return JSONResponse(
            status_code=404, content={"ok": False, "error": "session not found"}
        )
    return {"ok": True, **session.model_dump(by_alias=True)}


@router.post("/api/v1/insights/rebuild-map", response_model=None)
async def rebuild_map() -> dict[str, Any] | JSONResponse:
    """Kick off a background job to rebuild the codebase map.

    Returns ``{ok, jobId, kind}`` immediately; poll GET /api/v1/agent-jobs/{id}
    or stream GET /api/v1/agent-jobs/{id}/stream for progress.
    """
    try:
        ws = active_workspace()
    except NoActiveWorkspace as exc:
        return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})

    runner = _build_runner(ws)

    async def _work(output_path: object) -> dict[str, Any]:
        import pathlib

        return await build_map(ws, runner=runner, output_path=pathlib.Path(str(output_path)))

    job = start_agent_job("map", _work)
    return {"ok": True, "jobId": job.id, "kind": job.kind}


@router.get("/api/v1/insights/{iter_dir}/stream")
async def insights_stream(iter_dir: str, request: Request) -> StreamingResponse:
    """SSE stream for an insights run.

    Tails ``<state>/{iter_dir}/output.insights.jsonl`` and parses events via
    ``_summarize_event``.  Done condition: file stable (no growth) for >=2s.
    No loop-status check — insights runs terminate by file stability alone.
    Cap: 1800s.  Validates iter_dir against ``^insights-\\d+$``.
    """
    if not _ITER_DIR_RE.match(iter_dir):
        return StreamingResponse(
            _error_stream("invalid iter_dir — must match insights-NNNN"),
            media_type="text/event-stream",
            status_code=400,
        )

    from app.core.events import _summarize_event

    jp = _state_dir() / iter_dir / "output.insights.jsonl"

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
            # Done condition: file stable for >=2s (no loop-status check for insights)
            if idle >= 2.0:
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
