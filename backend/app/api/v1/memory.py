from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.ws_shim import get_active_profile
from app.main import error_response
from app.models.requests import MemoryWriteRequest
from app.services import project_memory

if TYPE_CHECKING:
    from app.models.workspace import RepoProfile

router = APIRouter()


def _resolve_ws(ws_id: str) -> RepoProfile:
    """Resolve the workspace by id from the registry (so memory reads/writes hit the right
    <repo>/.hephaestus/memory). Falls back to the active/legacy profile if the id is unknown."""
    try:
        from app.core.workspaces import registry

        ws = registry.get(ws_id)
        if ws is not None:
            return ws
    except Exception:  # noqa: BLE001 — registry optional
        pass
    return get_active_profile()


@router.get("/api/v1/workspaces/{ws_id}/memory/{doc}", response_model=None)
def get_memory(ws_id: str, doc: str) -> dict[str, Any] | JSONResponse:
    if doc not in project_memory.DOCS:
        return error_response(f"unknown doc {doc}", status=400)
    ws = _resolve_ws(ws_id)
    content = project_memory.read_doc(ws, doc)
    return {"ok": True, "content": content or ""}


@router.put("/api/v1/workspaces/{ws_id}/memory/{doc}", response_model=None)
def put_memory(ws_id: str, doc: str, body: MemoryWriteRequest) -> dict[str, Any] | JSONResponse:
    if doc not in project_memory.DOCS:
        return error_response(f"unknown doc {doc}", status=400)
    ws = _resolve_ws(ws_id)
    project_memory.write_doc(ws, doc, body.content, source="manual")
    return {"ok": True}
