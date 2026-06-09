from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.core.driver import (
    _driver_counts,
    _kill_loop_hard,
    _loop_status,
    _start_loop,
    _stop_loop_soft,
    driver_paused,
    reconcile_driver,
    set_driver_paused,
)
from app.core.pagination import MAX_LIMIT
from app.models.requests import DriverStartRequest

router = APIRouter()


@router.post("/api/driver/start")
def driver_start(body: DriverStartRequest) -> dict[str, Any]:
    return _start_loop(body.model_dump(by_alias=True))


@router.post("/api/driver/stop")
def driver_stop() -> dict[str, Any]:
    return _stop_loop_soft()


@router.post("/api/driver/pause")
def driver_pause() -> dict[str, Any]:
    """Auto-driver: persist paused=True and soft-stop the loop. The reconciler will not
    restart it while paused. Never crashes; if the flag can't be persisted, the response
    says so (ok:false) but the soft-stop is still attempted best-effort."""
    try:
        persisted = set_driver_paused(True)
        result = {**_stop_loop_soft(), "paused": True}
        if not persisted:
            result["ok"] = False
            result["error"] = "could not persist paused flag"
        return result
    except Exception as e:  # noqa: BLE001 — handler must never 500
        return {"ok": False, "error": str(e), "paused": True}


@router.post("/api/driver/resume")
def driver_resume() -> dict[str, Any]:
    """Auto-driver: clear paused, then reconcile (auto-starts if anything is runnable).
    Never crashes; if the flag can't be persisted, the response says so (ok:false) but the
    reconcile is still attempted best-effort."""
    try:
        persisted = set_driver_paused(False)
        result = {**reconcile_driver(), "paused": False}
        if not persisted:
            result["ok"] = False
            result["error"] = "could not persist paused flag"
        return result
    except Exception as e:  # noqa: BLE001 — handler must never 500
        return {"ok": False, "error": str(e), "paused": False}


@router.post("/api/driver/kill")
def driver_kill() -> dict[str, Any]:
    return _kill_loop_hard()


@router.get("/api/driver/status")
def driver_status() -> dict[str, Any]:
    """Return driver process status + RunSummary + auto-driver paused flag and counts."""
    from app.core.run_summary import RunSummaryStore

    status = _loop_status()
    summary = RunSummaryStore().get()
    status["runSummary"] = summary.model_dump(by_alias=True) if summary is not None else None
    status["paused"] = driver_paused()
    status.update(_driver_counts())  # adds "queued" + "inProgress" (camelCase)
    return status


@router.get("/api/driver/runs")
def driver_runs(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=0, ge=0, le=MAX_LIMIT),
) -> dict[str, Any]:
    """FEAT-005: finished-run history, newest first. PERF-003-style offset/limit
    window; ``total`` reports the full archived count."""
    from app.core.pagination import paginate
    from app.core.run_summary import RunHistoryStore

    runs = list(reversed(RunHistoryStore().list()))  # newest first
    window, meta = paginate(runs, offset, limit)
    return {"ok": True, "runs": [r.model_dump(by_alias=True) for r in window], **meta}
