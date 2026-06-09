from __future__ import annotations

import logging
import traceback as tb
from typing import Any

from fastapi import APIRouter, HTTPException

from app.models.requests import AddCommentRequest, CreateIssueRequest, UpdateIssueRequest
from app.services.github_issues import GitHubIssuesService

log = logging.getLogger("hephaestus.backend")

router: APIRouter = APIRouter()


def _get_issues_service() -> GitHubIssuesService:
    return GitHubIssuesService()


# ---------------------------------------------------------------------------
# List / get / create / update
# ---------------------------------------------------------------------------


@router.get("/api/v1/issues")
def list_issues(
    labels: str | None = None,
    state: str | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    try:
        svc = _get_issues_service()
        issues = svc.list_issues(labels=labels, state=state, limit=limit)
        return {"issues": issues}
    except Exception as exc:
        log.error("list_issues failed: %s\n%s", exc, tb.format_exc())
        return {"issues": [], "error": str(exc)}


@router.get("/api/v1/issues/{number}")
def get_issue(number: int) -> dict[str, Any]:
    svc = _get_issues_service()
    try:
        issue = svc.get_issue(number)
    except Exception as exc:
        log.error("get_issue(%s) failed: %s", number, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if issue is None:
        raise HTTPException(status_code=404, detail=f"issue {number} not found")
    return issue


@router.post("/api/v1/issues")
def create_issue(body: CreateIssueRequest) -> dict[str, Any]:
    svc = _get_issues_service()
    try:
        result = svc.create_issue(body.title, body.body, body.labels or [])
        # result is dict | None; preserve existing runtime behavior (no None guard).
        return {"ok": True, "number": result.get("number"), "url": result.get("url")}  # type: ignore[union-attr]
    except Exception as exc:
        log.error("create_issue failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/api/v1/issues/{number}")
def update_issue(number: int, body: UpdateIssueRequest) -> dict[str, Any]:
    svc = _get_issues_service()
    try:
        svc.update_issue(number, **body.model_dump(exclude_none=True))
        return {"ok": True}
    except Exception as exc:
        log.error("update_issue(%s) failed: %s", number, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


@router.post("/api/v1/issues/{number}/comment")
def add_comment(number: int, body: AddCommentRequest) -> dict[str, Any]:
    comment_body = body.body
    if not comment_body:
        raise HTTPException(status_code=400, detail="body is required")
    svc = _get_issues_service()
    try:
        svc.add_comment(number, comment_body)
        return {"ok": True}
    except Exception as exc:
        log.error("add_comment(%s) failed: %s", number, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/v1/issues/{number}/memory")
def get_issue_memory(number: int) -> dict[str, Any]:
    svc = _get_issues_service()
    try:
        comments = svc.get_memory(number)
        return {"comments": comments}
    except Exception as exc:
        log.error("get_memory(%s) failed: %s", number, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Sync helpers
# ---------------------------------------------------------------------------


@router.post("/api/v1/issues/sync")
def sync_to_queue() -> dict[str, Any]:
    svc = _get_issues_service()
    try:
        result = svc.sync_to_queue()
        return {
            "ok": True,
            "added": result.get("added", []),
            "skipped": result.get("skipped", []),
            "errors": result.get("errors", []),
        }
    except Exception as exc:
        log.error("sync_to_queue failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/v1/issues/from-task/{item_id}")
def create_from_task(item_id: str) -> dict[str, Any]:
    from app.core.state import read_state

    state = read_state()
    items = state.get("items", [])
    item = None
    for it in items:
        if it.get("id") == item_id:
            item = it
            break
    if item is None:
        raise HTTPException(status_code=404, detail=f"item {item_id} not found in state")

    svc = _get_issues_service()
    try:
        result = svc.create_from_task(item)
        # result is dict | None; preserve existing runtime behavior (no None guard).
        return {"ok": True, "number": result.get("number"), "url": result.get("url")}  # type: ignore[union-attr]
    except Exception as exc:
        log.error("create_from_task(%s) failed: %s", item_id, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
