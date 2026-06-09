"""GET /api/v1/echo/{message} — echo a message back."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/v1/echo/{message}", response_model=None)
def echo_message(message: str) -> dict[str, str | bool]:
    """Return the message back to the caller. Never 500."""
    return {"ok": True, "echo": message}
