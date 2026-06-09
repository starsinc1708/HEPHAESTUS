from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.models.requests import RenderPromptRequest, UpdatePromptRequest
from app.services.prompt_manager import PromptManager

log = logging.getLogger("hephaestus.backend")

router = APIRouter()


def _get_prompt_manager() -> PromptManager:
    return PromptManager()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("/api/v1/prompts")
def list_prompts() -> dict[str, Any]:
    mgr = _get_prompt_manager()
    try:
        prompts = mgr.list_prompts()
        return {"prompts": prompts}
    except Exception as exc:
        log.error("list_prompts failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/v1/prompts/{name}")
def get_prompt(name: str) -> dict[str, Any]:
    mgr = _get_prompt_manager()
    try:
        prompt = mgr.get_prompt(name)
    except Exception as exc:
        log.error("get_prompt(%s) failed: %s", name, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if prompt is None:
        raise HTTPException(status_code=404, detail=f"prompt '{name}' not found")
    return prompt


@router.put("/api/v1/prompts/{name}")
def update_prompt(name: str, body: UpdatePromptRequest) -> dict[str, Any]:
    mgr = _get_prompt_manager()
    try:
        result = mgr.update_prompt(name, body.content)
        # result may be None on failure; preserve existing behavior (AttributeError path).
        return {"ok": True, "name": name, "variables": result.get("variables", [])}  # type: ignore[union-attr]
    except Exception as exc:
        log.error("update_prompt(%s) failed: %s", name, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/api/v1/prompts/{name}")
def delete_prompt(name: str) -> dict[str, Any]:
    mgr = _get_prompt_manager()
    try:
        deleted = mgr.delete_prompt(name)
    except Exception as exc:
        log.error("delete_prompt(%s) failed: %s", name, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"prompt '{name}' not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


@router.post("/api/v1/prompts/{name}/render")
def render_prompt(name: str, body: RenderPromptRequest) -> dict[str, Any]:
    mgr = _get_prompt_manager()
    try:
        rendered = mgr.render_prompt(name, body.variables)
        return {"ok": True, "rendered": rendered}
    except Exception as exc:
        log.error("render_prompt(%s) failed: %s", name, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------


@router.get("/api/v1/prompts/system/task")
def build_system_task_prompt(item_id: str | None = None) -> dict[str, Any]:
    mgr = _get_prompt_manager()
    item: dict[str, Any] | None = None
    if item_id:
        from app.core.state import read_state

        state = read_state()
        for it in state.get("items", []):
            if it.get("id") == item_id:
                item = it
                break
        if item is None:
            raise HTTPException(status_code=404, detail=f"item {item_id} not found in state")

    try:
        # item may be None when no item_id given; preserve existing behavior.
        prompt = mgr.build_task_prompt(item)  # type: ignore[arg-type]
        return {"ok": True, "prompt": prompt}
    except Exception as exc:
        log.error("build_system_task_prompt failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
