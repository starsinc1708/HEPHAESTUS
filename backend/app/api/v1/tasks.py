from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.iters import _task_view
from app.core.queue import (
    _patch_deps,
    _queue_add,
    _queue_delete,
    _queue_move_top,
    _queue_patch,
    _queue_requeue,
    _queue_requeue_failed,
    _reorder,
    _run_task,
    _run_tasks,
    _try_broadcast_state,
    _unqueue_task,
)
from app.core.state import _read_state, _StateLock, _write_state
from app.main import error_response
from app.models.requests import (
    DepsPatchRequest,
    QueueAddRequest,
    ReorderRequest,
    TagsPatchRequest,
    TaskRunRequest,
)

router: APIRouter = APIRouter()


@router.get("/api/task/{item_id}")
def task_view(item_id: str) -> dict[str, Any]:
    return _task_view(item_id)


@router.get("/api/v1/tasks/{item_id}/checks", response_model=None)
def task_checks(item_id: str) -> dict[str, Any] | JSONResponse:
    task = _task_view(item_id)
    if not task.get("ok"):
        return error_response(task.get("error", "not found"), status=404)
    item = task.get("item", {})
    return {
        "ok": True,
        "verifyOutcome": item.get("verify_outcome"),
        # Out-of-scope files the scope-guard flagged (Improvement 1), surfaced so the
        # drawer can warn even in advisory mode instead of hiding the violation.
        "scopeExtra": item.get("scope_extra") or [],
    }


@router.get("/api/v1/tasks/{item_id}/conversations", response_model=None)
def task_conversations(item_id: str) -> dict[str, Any] | JSONResponse:
    from app.core.conversations import _task_conversations

    res = _task_conversations(item_id)
    if not res.get("ok"):
        return error_response(res.get("error", "not found"), status=404)
    return res


@router.post("/api/queue/add", response_model=None)
def queue_add(body: QueueAddRequest) -> dict[str, Any] | JSONResponse:
    try:
        return _queue_add(body.model_dump(by_alias=True))
    except ValueError as e:
        return error_response(str(e), status=400)


@router.post("/api/queue/{qid}/move-top")
def queue_move_top(qid: str) -> dict[str, Any]:
    return _queue_move_top(qid)


@router.post("/api/queue/{qid}/requeue")
def queue_requeue(qid: str) -> dict[str, Any]:
    return _queue_requeue(qid)


@router.post("/api/v1/tasks/requeue-failed", response_model=None)
def requeue_failed() -> dict[str, Any]:
    """Bulk-requeue all failed:* items back to pending."""
    return _queue_requeue_failed()


@router.delete("/api/queue/{qid}")
def queue_delete(qid: str) -> dict[str, Any]:
    return _queue_delete(qid)


@router.patch("/api/queue/{qid}", response_model=None)
def queue_patch(qid: str, body: QueueAddRequest) -> dict[str, Any] | JSONResponse:
    try:
        return _queue_patch(qid, body.model_dump(by_alias=True))
    except ValueError as e:
        return error_response(str(e), status=400)


@router.post("/api/v1/tasks/run", response_model=None)
def run_tasks(body: TaskRunRequest) -> dict[str, Any] | JSONResponse:
    """Auto-driver: bulk send-to-run. Queue every eligible id, then reconcile the driver."""
    res = _run_tasks(body.ids)
    if res.get("queued"):
        from app.core.driver import reconcile_driver

        reconcile_driver()
    return res


@router.post("/api/v1/tasks/{item_id}/run", response_model=None)
def run_task(item_id: str) -> dict[str, Any] | JSONResponse:
    """Auto-driver: send one task to run (pending/needs_revision -> queued) + reconcile."""
    res = _run_task(item_id)
    if not res.get("ok"):
        err = res.get("error", "run failed")
        if "not found" in err:
            return error_response(err, status=404)
        return error_response(err, status=409)
    from app.core.driver import reconcile_driver

    reconcile_driver()
    return {"ok": True, "status": "queued"}


@router.post("/api/v1/tasks/{item_id}/unqueue", response_model=None)
def unqueue_task(item_id: str) -> dict[str, Any] | JSONResponse:
    """Auto-driver: un-send a task (queued -> pending). 409 once it's in_progress."""
    res = _unqueue_task(item_id)
    if not res.get("ok"):
        err = res.get("error", "unqueue failed")
        if "not found" in err:
            return error_response(err, status=404)
        return error_response(err, status=409)
    return {"ok": True, "status": "pending"}


@router.patch("/api/v1/tasks/{item_id}/deps", response_model=None)
def patch_deps(item_id: str, body: DepsPatchRequest) -> dict[str, Any] | JSONResponse:
    """Set a task's dependsOn list (validates existence/self-ref/cycle) + recompute blocks."""
    res = _patch_deps(item_id, body.dependsOn)
    if not res.get("ok"):
        err = res.get("error", "patch deps failed")
        status = 404 if "not found" in err else 400
        offending = res.get("offending")
        if offending is not None:
            return error_response(err, status=status, offending=offending)
        return error_response(err, status=status)
    return res


@router.patch("/api/v1/tasks/{item_id}/reorder", response_model=None)
def reorder_task(item_id: str, body: ReorderRequest) -> dict[str, Any] | JSONResponse:
    if item_id not in body.order:
        return error_response("item_id not in order", status=400)
    res = _reorder(body.order)
    if not res.get("ok"):
        return error_response(res.get("error", "reorder failed"), status=400)
    return res


@router.patch("/api/v1/tasks/{item_id}/tags", response_model=None)
def patch_tags(item_id: str, body: TagsPatchRequest) -> dict[str, Any] | JSONResponse:
    """Set a task's tags (normalizes: strip, remove empties, dedup)."""
    tags = [t.strip() for t in body.tags]
    tags = [t for t in tags if t]
    seen: set[str] = set()
    deduped = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    tags = deduped
    if len(tags) > 10:
        return error_response("tags must have at most 10 items", status=400)
    for t in tags:
        if len(t) > 30:
            return error_response(f"tag exceeds 30 characters: {t[:30]}", status=400)

    with _StateLock():
        s = _read_state()
        items = s.get("items", [])
        target = next((it for it in items if it.get("id") == item_id), None)
        if target is None:
            return error_response("id not found", status=404)
        target["tags"] = tags
        _write_state(s)
    _try_broadcast_state()
    return {"ok": True, "id": item_id, "tags": tags}
