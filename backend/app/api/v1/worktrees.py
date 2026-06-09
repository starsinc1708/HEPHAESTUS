"""Sub-project #6 — worktrees enumeration + per-branch unified-diff endpoint.

Follows the codebase convention (see merge.py): return JSONResponse / PlainTextResponse
directly on error, a plain dict on success; response_model=None on each route. Reuses
merge.py's workspace resolver (single source of truth).
"""

from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse

from app.api.v1.merge import NoActiveWorkspace, active_workspace
from app.core.git import GitService, _is_safe_auto_branch
from app.core.worktrees import list_worktrees

router = APIRouter()

_DIFF_CAP = 200_000


@router.get("/api/v1/worktrees", response_model=None)
def get_worktrees() -> dict[str, object] | JSONResponse:
    try:
        ws = active_workspace()
    except NoActiveWorkspace as exc:
        return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})
    return {"ok": True, "worktrees": [w.model_dump(by_alias=True) for w in list_worktrees(ws)]}


@router.get("/api/v1/branches/{name:path}/diff", response_model=None)
def branch_diff(name: str) -> PlainTextResponse | JSONResponse:
    decoded = unquote(name)
    if len(decoded) > 250 or not _is_safe_auto_branch(decoded):
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid branch name"})
    try:
        ws = active_workspace()
    except NoActiveWorkspace as exc:
        return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})
    return PlainTextResponse(GitService(ws).diff(decoded)[:_DIFF_CAP])
