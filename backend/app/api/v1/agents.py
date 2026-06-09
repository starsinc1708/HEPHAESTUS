from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.services.agent_activity import _agent_activity

router = APIRouter()


@router.get("/api/agents/activity")
def agents_activity() -> dict[str, Any]:
    return _agent_activity()
