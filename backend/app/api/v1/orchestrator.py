"""Orchestrator control endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core.helpers import _load_json
from app.core.state import _state_dir
from app.orchestrator.fsm import OrchestratorFSM

router = APIRouter()

_fsm: OrchestratorFSM | None = None


@router.post("/api/v1/orchestrator/start")
async def start_orchestrator() -> dict[str, Any]:
    """Start the orchestrator (placeholder — real start is via systemd)."""
    return {"ok": True, "note": "Orchestrator runs as separate process (systemd)"}


@router.get("/api/v1/orchestrator/status")
async def orchestrator_status() -> dict[str, Any]:
    """Get orchestrator status."""
    # current.json is always a JSON object; `or {}` only handles the None case.
    # `.get` on a (never-occurring) list would raise — preserve that exactly.
    current: dict[str, Any] | list[Any] = _load_json(_state_dir() / "current.json") or {}
    return {
        "phase": current.get("phase", "idle"),  # type: ignore[union-attr]
        "itemId": current.get("itemId"),  # type: ignore[union-attr]
        "detail": current.get("detail", ""),  # type: ignore[union-attr]
        "updatedAt": current.get("updatedAt"),  # type: ignore[union-attr]
    }
