"""CLI detection endpoint: GET /api/v1/clis → installed CLIs + version + auth info."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services.cli_detect import detect_clis

router = APIRouter()


@router.get("/api/v1/clis", response_model=None)
def get_clis() -> dict[str, Any]:
    return {"ok": True, "clis": detect_clis()}
