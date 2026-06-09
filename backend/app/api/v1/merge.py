"""Stage 3 — merge preflight + merge-job endpoints (umbrella §6, D11).

Follows the codebase convention (see branches.py): return JSONResponse directly
on error and a plain dict on success — no app.main import (avoids a circular import
and keeps this module self-typed for `mypy --strict`).
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING
from urllib.parse import unquote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.git import GitService, _is_safe_auto_branch
from app.models.validation import MergeRequest

if TYPE_CHECKING:
    from app.models.workspace import RepoProfile

router = APIRouter()


class NoActiveWorkspace(RuntimeError):
    """Raised when no workspace is active or the Stage 1 registry is unavailable."""

    def __init__(self, message: str = "no active workspace") -> None:
        super().__init__(message)


def active_workspace() -> RepoProfile:
    """Resolve the active workspace (R4: single source — app.core.workspaces).

    Returns a RepoProfile or raises NoActiveWorkspace. NEVER imports the
    non-existent app.core.workspace_registry.
    """
    try:
        from app.core.workspaces import active_workspace as _aw
    except ImportError as exc:  # registry unavailable
        raise NoActiveWorkspace("workspace registry unavailable") from exc
    ws = _aw()
    if ws is None:
        raise NoActiveWorkspace("no active workspace")
    return ws


def _guard(name: str) -> str | None:
    decoded = unquote(name)
    if len(decoded) > 250 or not _is_safe_auto_branch(decoded):
        return None
    return decoded


@router.get("/api/v1/branches/{name:path}/merge-preflight", response_model=None)
def merge_preflight(name: str) -> dict[str, object] | JSONResponse:
    decoded = _guard(name)
    if decoded is None:
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid branch name"})
    try:
        ws = active_workspace()
    except NoActiveWorkspace as exc:
        return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})
    pf = GitService(ws).merge_preflight(decoded)
    return {"ok": True, **pf.model_dump(by_alias=True)}


@router.post("/api/v1/branches/{name:path}/merge", response_model=None)
async def merge_branch(name: str, body: MergeRequest) -> dict[str, object] | JSONResponse:
    decoded = _guard(name)
    if decoded is None:
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid branch name"})
    try:
        ws = active_workspace()
    except NoActiveWorkspace as exc:
        return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})
    from app.core.merge_job import MergeJobRunner, MergeJobStore
    if MergeJobStore().active() is not None:
        return JSONResponse(status_code=409, content={"ok": False, "error": "merge already in progress"})
    gs = GitService(ws)
    if gs._loop_active():
        return JSONResponse(status_code=409, content={"ok": False, "error": "loop active, stop it before merge"})
    pf = gs.merge_preflight(decoded)
    if not pf.ok and not pf.conflicts:
        return JSONResponse(
            status_code=409,
            content={"ok": False, "error": "preflight failed", "preflight": pf.model_dump(by_alias=True)},
        )
    runner = MergeJobRunner(ws)
    job = await runner.start(
        branch=decoded,
        push=body.push,
        ai_resolve=body.ai_resolve,
        auto_accept=body.auto_accept,
    )
    return {"ok": True, "jobId": job.id, "status": job.status.value}


@router.get("/api/v1/active-merge-job", response_model=None)
def active_merge_job() -> dict[str, object]:
    """The single non-terminal merge job (running/resolving/verifying/resolved/conflict),
    or null. Lets the UI re-attach a merge panel after a page refresh instead of stranding
    an in-flight merge."""
    from app.core.merge_job import MergeJobStore

    job = MergeJobStore().active()
    return {"ok": True, "job": job.model_dump(by_alias=True) if job is not None else None}


@router.get("/api/v1/merge-jobs/{job_id}", response_model=None)
def get_merge_job(job_id: str) -> dict[str, object] | JSONResponse:
    from app.core.merge_job import MergeJobStore

    job = MergeJobStore().get(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "job not found"})
    return {"ok": True, **job.model_dump(by_alias=True)}


@router.get("/api/v1/merge-jobs/{job_id}/verify-log", response_model=None)
def merge_job_verify_log(job_id: str) -> dict[str, object] | JSONResponse:
    """The verify-on-merged-tree log (ruff/mypy/tests · vue-tsc/vitest). For an auto-merge no
    resolver agent runs, so this log is the merge's only 'history' — and it's where a
    `verify failed on merged tree` reason actually lives. Resolving job_id through the store
    first both 404s unknown ids and blocks path traversal."""
    from app.core.merge_job import MergeJobStore
    from app.core.state import _state_dir

    if MergeJobStore().get(job_id) is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "job not found"})
    p = _state_dir() / job_id / "verify.log"
    try:
        text = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
    except OSError:
        text = ""
    # ruff/vitest emit ANSI colour codes even into the log file; strip them so the <pre>
    # shows clean text instead of `\x1b[2m…` garbage.
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    if len(text) > 50_000:  # never bloat the response on a runaway log — keep the tail
        text = "…(showing log tail)\n" + text[-50_000:]
    return {"ok": True, "log": text}


@router.post("/api/v1/merge-jobs/{job_id}/accept", response_model=None)
async def accept_merge_job(job_id: str, body: MergeRequest) -> dict[str, object] | JSONResponse:
    try:
        ws = active_workspace()
    except NoActiveWorkspace as exc:
        return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})
    from app.core.merge_job import MergeJobRunner

    res = await MergeJobRunner(ws).accept(job_id, push=body.push)
    if res.get("ok"):
        return res
    return JSONResponse(status_code=409, content=res)


@router.post("/api/v1/merge-jobs/{job_id}/reject", response_model=None)
async def reject_merge_job(job_id: str) -> dict[str, object] | JSONResponse:
    try:
        ws = active_workspace()
    except NoActiveWorkspace as exc:
        return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})
    from app.core.merge_job import MergeJobRunner

    return await MergeJobRunner(ws).reject(job_id)


@router.get("/api/v1/merge-jobs/{job_id}/stream")
async def merge_job_stream(job_id: str, request: Request) -> StreamingResponse:
    from app.core.events import _summarize_event
    from app.core.merge_job import MergeJobStore
    from app.core.state import _state_dir

    jp = _state_dir() / job_id / "output.resolve.jsonl"
    terminal = {"resolved", "conflict", "failed", "accepted", "rejected"}

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
                    yield f"data: {json.dumps(_summarize_event(obj, idx=idx - 1), ensure_ascii=False)}\n\n"
                grew = True
            idle = 0.0 if grew else idle + 0.5
            job = MergeJobStore().get(job_id)
            if idle >= 2.0 and (job is None or job.status.value in terminal):
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
