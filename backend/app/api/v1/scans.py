from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.scan import (
    _scan_import,
    _scan_list,
    _scan_log,
    _scan_results,
    _scan_start,
    _scan_status,
    _scans_import_by_ids,
)
from app.models.requests import ScanImportRequest, ScanStartRequest

router = APIRouter()


class _ScansImportRequest(BaseModel):
    ids: list[str] = []
    dirname: str | None = None


@router.get("/api/scan/status")
def scan_status() -> dict[str, Any]:
    return _scan_status()


@router.get("/api/scan/log/{dirname}")
def scan_log(dirname: str) -> dict[str, Any]:
    return _scan_log(dirname)


@router.get("/api/scan/list")
def scan_list() -> dict[str, Any]:
    return {"scans": _scan_list()}


@router.get("/api/scan/results/{dirname}")
def scan_results(dirname: str) -> dict[str, Any]:
    return _scan_results(dirname)


@router.post("/api/scan/start")
def scan_start(body: ScanStartRequest) -> dict[str, Any]:
    return _scan_start(body.model_dump(by_alias=True))


@router.post("/api/scan/import/{dirname}")
def scan_import(dirname: str, body: ScanImportRequest) -> dict[str, Any]:
    return _scan_import(dirname, body.ids)


@router.post("/api/v1/scans/import", response_model=None)
def scans_import(body: _ScansImportRequest) -> dict[str, Any] | JSONResponse:
    """Import selected scan findings (by id) into the board as ``pending`` tasks.

    Body: ``{ids, dirname?}``. Empty ``ids`` → clean ``{ok, added:[], skipped:[]}``.
    A bad/missing ``dirname`` → 404. Idempotent (skips ids already on the board).
    """
    result = _scans_import_by_ids(body.ids, dirname=body.dirname)
    if not result.get("ok"):
        return JSONResponse(status_code=404, content=result)
    return result
