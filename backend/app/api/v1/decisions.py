from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core.decisions import _read_decisions

router = APIRouter()


@router.get("/api/decisions")
def get_decisions() -> dict[str, Any]:
    return {"decisions": _read_decisions(limit=80)}
