"""Connections REST API: provider catalog + global connections CRUD + real-CLI test.

Follows the codebase convention (see merge.py): return JSONResponse directly on error
and a plain dict on success — `response_model=None` so the union return type type-checks.
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.models.connections import PROVIDER_CATALOG, mask_env
from app.services.connection_test import test_connection
from app.services.connections import (
    add_connection,
    delete_connection,
    get_connection,
    list_connections_masked,
    set_status,
)

router = APIRouter()


class CreateConnectionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    provider: str
    engine: str
    model: str
    key: str = ""
    auth_method: str = Field("api_key", alias="authMethod")
    label: str | None = None


@router.get("/api/v1/connection-presets", response_model=None)
def get_presets() -> dict[str, Any]:
    return {"ok": True, "catalog": [e.model_dump(by_alias=True) for e in PROVIDER_CATALOG]}


@router.get("/api/v1/connections", response_model=None)
def get_connections() -> dict[str, Any]:
    return {"ok": True, "connections": list_connections_masked()}


@router.post("/api/v1/connections", response_model=None)
def create_connection(body: CreateConnectionRequest) -> dict[str, Any] | JSONResponse:
    try:
        conn = add_connection(provider=body.provider, engine=body.engine,
                              auth_method=body.auth_method, model=body.model,
                              key=body.key, label=body.label)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})
    d = conn.model_dump(by_alias=True)
    d["env"] = mask_env(conn.env)  # never return the raw key in the create response
    return {"ok": True, "connection": d}


@router.delete("/api/v1/connections/{conn_id}", response_model=None)
def remove_connection(conn_id: str) -> dict[str, Any] | JSONResponse:
    if not delete_connection(conn_id):
        return JSONResponse(status_code=404, content={"ok": False, "error": "connection not found"})
    return {"ok": True}


@router.post("/api/v1/connections/{conn_id}/test", response_model=None)
async def run_connection_test(conn_id: str) -> dict[str, Any] | JSONResponse:
    conn = get_connection(conn_id)
    if conn is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "connection not found"})
    status, error = await test_connection(conn)
    tested_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    set_status(conn_id, status, error=error, tested_at=tested_at)
    return {"ok": True, "status": status, "error": error}
