"""Ideas API — Epic 4 (B2).

POST /api/v1/ideas/generate  — generate ideas via agent
GET  /api/v1/ideas           — list persisted ideas
POST /api/v1/ideas/import    — import selected ideas into the work queue
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.agent_jobs import start_agent_job
from app.core.pagination import MAX_LIMIT, paginate
from app.core.scan import _build_runner
from app.services.ideas import IdeaStore, generate_ideas, import_ideas

if TYPE_CHECKING:
    from app.models.workspace import RepoProfile

router = APIRouter()


class _GenerateRequest(BaseModel):
    categories: list[str] | None = None


class _ImportRequest(BaseModel):
    ids: list[str]


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


@router.post("/api/v1/ideas/generate", response_model=None)
async def generate_ideas_endpoint(body: _GenerateRequest) -> dict[str, Any] | JSONResponse:
    """Kick off a background job to generate ideas.

    Returns ``{ok, jobId, kind}`` immediately; poll GET /api/v1/agent-jobs/{id}
    or stream GET /api/v1/agent-jobs/{id}/stream for progress.
    """
    try:
        ws = active_workspace()
    except NoActiveWorkspace as exc:
        return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})

    runner = _build_runner(ws)
    categories = body.categories

    async def _work(output_path: object) -> dict[str, Any]:
        import pathlib

        ideas = await generate_ideas(
            ws, categories=categories, runner=runner,
            output_path=pathlib.Path(str(output_path)),
        )
        return {"ideas": [i.model_dump(by_alias=True) for i in ideas]}

    job = start_agent_job("ideas", _work)
    return {"ok": True, "jobId": job.id, "kind": job.kind}


@router.get("/api/v1/ideas", response_model=None)
def list_ideas(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=0, ge=0, le=MAX_LIMIT),
) -> dict[str, Any]:
    """List persisted ideas. PERF-003: opt-in offset/limit window; omit both to
    get all (already capped on disk). ``total`` reports the full count."""
    ideas = IdeaStore().list()
    window, meta = paginate(ideas, offset, limit)
    return {"ok": True, "ideas": [i.model_dump(by_alias=True) for i in window], **meta}


@router.post("/api/v1/ideas/import", response_model=None)
def import_ideas_endpoint(body: _ImportRequest) -> dict[str, Any]:
    """Import selected ideas into the work queue."""
    result = import_ideas(body.ids)
    return {"ok": True, "added": result["added"]}
