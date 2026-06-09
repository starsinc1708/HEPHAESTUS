from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.git import BRANCH_ACTIONS, _is_safe_auto_branch

router: APIRouter = APIRouter()

_VALID_ACTIONS = {"merge", "requeue", "discard"}


@router.post("/api/branch/{name}/{action}", response_model=None)
def branch_action(name: str, action: str) -> dict[str, Any] | JSONResponse | PlainTextResponse:
    if action not in _VALID_ACTIONS:
        return PlainTextResponse(f"invalid action: {action}", status_code=404)
    decoded_name = unquote(name)
    if len(decoded_name) > 250:
        return JSONResponse(status_code=400, content={"ok": False, "error": "branch name too long"})
    if not _is_safe_auto_branch(decoded_name):
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid branch name"})
    fn = BRANCH_ACTIONS.get(action)
    if not fn:
        return PlainTextResponse(f"unknown action: {action}", status_code=404)
    res: dict[str, Any] = fn(decoded_name)
    if not res.get("ok"):
        return JSONResponse(content=res, status_code=409)
    return res
