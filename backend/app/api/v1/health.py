"""GET /api/v1/health — minimal liveness probe."""
from __future__ import annotations

import json
import logging
import os
import shutil
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import STATE_DIR

log = logging.getLogger("hephaestus.backend.health")

router = APIRouter()


@router.get("/api/v1/health", response_model=None)
def health() -> dict[str, bool | str]:
    return {"ok": True, "status": "ok"}


@router.get("/api/v1/system/health", response_model=None)
def system_health() -> JSONResponse:
    """Enhanced health check: disk space, CLI availability, state validity."""
    ok = True
    disk_free_gb: float = 0.0
    disk_warn: bool = False
    state_ok: bool = False

    # --- Disk space ---
    try:
        usage = shutil.disk_usage(str(STATE_DIR))
        disk_free_gb = usage.free / (1024**3)
        warn_threshold = float(os.environ.get("HEPHAESTUS_DISK_WARN_GB", "1"))
        disk_warn = disk_free_gb < warn_threshold
        if disk_warn:
            ok = False
    except Exception:
        log.exception("disk_usage check failed")
        ok = False

    # --- CLI availability ---
    cli_names = ("git", "opencode", "claude", "codex")
    clis: dict[str, bool] = {}
    for name in cli_names:
        try:
            clis[name] = shutil.which(name) is not None
        except Exception:
            clis[name] = False

    # --- State validity ---
    try:
        state_file = STATE_DIR / "work-state.json"
        if state_file.exists():
            json.loads(state_file.read_text(encoding="utf-8"))
            state_ok = True
        else:
            state_ok = False
            ok = False
    except Exception:
        state_ok = False
        ok = False

    payload: dict[str, Any] = {
        "ok": ok,
        "diskFreeGb": round(disk_free_gb, 2),
        "diskWarn": disk_warn,
        "clis": clis,
        "stateOk": state_ok,
    }
    return JSONResponse(content=payload)
