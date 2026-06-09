"""GET /api/v1/version — build info + deploy diagnostics."""
from __future__ import annotations

import subprocess
import time
from typing import Any

from fastapi import APIRouter

from app import __version__

router = APIRouter()


@router.get("/api/v1/version", response_model=None)
def get_version() -> dict[str, Any]:
    """Return version, commit SHA, and server timestamp. Never 500."""
    commit: str | None = None
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=5, check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            commit = out.stdout.strip()
    except Exception:
        commit = None

    return {
        "ok": True,
        "version": __version__,
        "commit": commit,
        "serverTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
