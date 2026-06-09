from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter

from app.config import ALLOWED_CONFIG_KEYS, CONFIG_OVERRIDE, _config_effective, _config_overrides, _config_preset
from app.core.state import _atomic_write, _StateLock
from app.models.requests import ConfigPresetRequest

router = APIRouter()


@router.get("/api/config")
def get_config() -> dict[str, Any]:
    return {"effective": _config_effective(), "overrides": _config_overrides()}


@router.put("/api/config")
def put_config(body: dict[str, Any]) -> dict[str, Any]:
    with _StateLock():
        cur = _config_overrides()
        cur.update({k: str(v) for k, v in body.items() if k in ALLOWED_CONFIG_KEYS})
        _atomic_write(CONFIG_OVERRIDE, json.dumps(cur, indent=2, ensure_ascii=False))
    return {"ok": True, "overrides": cur}


@router.post("/api/config/preset")
def config_preset(body: ConfigPresetRequest) -> dict[str, Any]:
    return _config_preset(body.name)
