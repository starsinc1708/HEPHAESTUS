from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core.iters import _state_cleanup, build_state
from app.models.requests import StateCleanupRequest

router = APIRouter()


@router.get("/api/state")
def get_state() -> dict[str, Any]:
    return build_state()


@router.post("/api/state/cleanup")
def state_cleanup(body: StateCleanupRequest) -> dict[str, Any]:
    return _state_cleanup(body.model_dump(by_alias=True))
