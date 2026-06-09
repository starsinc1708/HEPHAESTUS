from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse

from app.core.events import _iter_cost, _read_event_at_idx, _summarize_event, parse_full_conversation
from app.core.helpers import _all_iter_dirs
from app.core.iters import (
    _iter_details,
    _iter_diff,
    _iter_raw_events,
    _iter_streams,
    _iter_summary_row,
    _iter_tool_history,
    _iter_verify,
    _resolve_conversation_stream,
    _safe_iter_dir,
)

router = APIRouter()

_STREAM_RE = re.compile(r"^[a-zA-Z0-9_-]{1,60}$")


@router.get("/api/history")
def get_history(page: int = Query(default=1, ge=1), per_page: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    all_iters = [_iter_summary_row(d) for d in reversed(_all_iter_dirs())]
    total = len(all_iters)
    start = (page - 1) * per_page
    end = start + per_page
    return {"iters": all_iters[start:end], "total": total, "page": page, "per_page": per_page}


@router.get("/api/iter/{dirname}/details")
def iter_details(dirname: str) -> dict[str, Any]:
    return _iter_details(dirname)


@router.get("/api/iter/{dirname}/diff")
def iter_diff(dirname: str) -> Response:
    diff = _iter_diff(dirname)
    if diff is None:
        return PlainTextResponse("no diff available", status_code=404)
    return PlainTextResponse(diff)


@router.get("/api/iter/{dirname}/verify")
def iter_verify(dirname: str) -> Response:
    v = _iter_verify(dirname)
    if v is None:
        return PlainTextResponse("no verify log", status_code=404)
    return PlainTextResponse(v)


@router.get("/api/iter/{dirname}/reviews")
def iter_reviews(dirname: str) -> dict[str, Any]:
    det = _iter_details(dirname)
    return {k: det.get(k) for k in ("verdicts", "tier1_summary", "tier2_summary", "final_decision", "has_reviews")}


@router.get("/api/iter/{dirname}/cost")
def iter_cost(dirname: str) -> dict[str, Any]:
    d = _safe_iter_dir(dirname)
    if d is None:
        return {"total_usd": 0.0, "by_stream": {}}
    return _iter_cost(d)


@router.get("/api/iter/{dirname}/raw")
def iter_raw(dirname: str, stream: str = Query(default="primary")) -> Response:
    if not _STREAM_RE.match(stream):
        return JSONResponse({"error": "invalid stream name"}, status_code=400)
    events = _iter_raw_events(dirname, stream=stream, limit=400)
    if events is None:
        return JSONResponse({"events": [], "stream": stream}, status_code=404)
    return JSONResponse({"events": events or [], "stream": stream})


@router.get("/api/iter/{dirname}/stream")
async def iter_stream(dirname: str, request: Request, stream: str = Query(default="primary")) -> Response:
    """Server-Sent Events: tail the agent's JSONL output and emit each new parsed event
    live (terminal-style streaming in the browser). Replays existing events first, then
    follows the file while the loop runs; ends when the run stops and the file is stable."""
    if not _STREAM_RE.match(stream):
        return JSONResponse({"error": "invalid stream name"}, status_code=400)
    d = _safe_iter_dir(dirname)
    if d is None:
        return JSONResponse({"error": "iter not found"}, status_code=404)
    jp = (d / f"output.{stream}.jsonl" if stream in ("primary", "fallback")
          else d / "reviews" / f"{stream}.out.jsonl")

    async def gen() -> AsyncIterator[str]:
        from app.core.process import ProcState, pm

        idx = 0
        offset = 0
        buf = b""
        idle = 0.0
        started = time.monotonic()
        yield ": connected\n\n"  # prime the stream so the client opens immediately
        while True:
            if await request.is_disconnected() or (time.monotonic() - started) > 1800:
                break
            grew = False
            if jp.exists():
                size = jp.stat().st_size
                if size > offset:
                    with jp.open("rb") as f:
                        f.seek(offset)
                        chunk = f.read()
                    offset += len(chunk)
                    buf += chunk
                    parts = buf.split(b"\n")
                    buf = parts.pop()  # keep trailing partial line
                    for raw in parts:
                        line = raw.strip()
                        idx += 1
                        if not line:
                            continue
                        try:
                            obj = json.loads(line.decode("utf-8", "replace"))
                        except ValueError:
                            continue
                        ev = _summarize_event(obj, idx=idx - 1)
                        yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                    grew = True
            idle = 0.0 if grew else idle + 0.5
            # Stable file + run finished -> we've shown everything; close cleanly.
            if idle >= 2.0 and pm.status("loop").state != ProcState.RUNNING:
                yield "event: done\ndata: {}\n\n"
                break
            if not grew:
                yield ": keepalive\n\n"  # comment frame keeps the connection alive
            await asyncio.sleep(0.5)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/api/iter/{dirname}/tools")
def iter_tools(dirname: str, stream: str = Query(default="primary")) -> Response:
    if not _STREAM_RE.match(stream):
        return JSONResponse({"error": "invalid stream name"}, status_code=400)
    tools = _iter_tool_history(dirname, stream=stream)
    if tools is None:
        return JSONResponse({"tools": [], "stream": stream}, status_code=404)
    return JSONResponse({"tools": tools or [], "stream": stream})


@router.get("/api/iter/{dirname}/streams")
def iter_streams_list(dirname: str) -> dict[str, Any]:
    return {"streams": _iter_streams(dirname)}


@router.get("/api/iter/{dirname}/conversation", response_model=None)
def iter_conversation(dirname: str, stream: str = Query(default="output.primary")) -> dict[str, Any] | Response:
    d = _safe_iter_dir(dirname)
    if d is None:
        return JSONResponse({"error": "iter not found"}, status_code=404)
    fp = _resolve_conversation_stream(d, stream)
    if fp is None:
        return JSONResponse({"error": "invalid stream"}, status_code=400)
    if not fp.exists():
        return JSONResponse({"messages": [], "stream": stream}, status_code=404)
    messages = parse_full_conversation(fp)
    return {"ok": True, "stream": stream, "messages": messages}


@router.get("/api/iter/{dirname}/event/{idx}", response_model=None)
def iter_event(dirname: str, idx: int, stream: str = Query(default="primary")) -> dict[str, Any] | Response:
    if not _STREAM_RE.match(stream):
        return JSONResponse({"error": "invalid stream name"}, status_code=400)
    d = _safe_iter_dir(dirname)
    if d is None:
        return JSONResponse({"error": "iter not found"}, status_code=404)
    jp = d / f"output.{stream}.jsonl" if stream in ("primary", "fallback") else d / "reviews" / f"{stream}.out.jsonl"
    ev = _read_event_at_idx(jp, idx)
    if ev is None:
        return JSONResponse({"error": "event not found"}, status_code=404)
    return ev
