"""Workspace registry endpoints (Stage 1).

Onboarding runs the Profiler as a SUPERVISED CHILD PROCESS via the sync ProcessManager
(pm.start("profiler", ...)), NOT in-process. Inside that process orchestrator/main.py
(--profile <id>) owns its own asyncio loop and calls Profiler.onboard() (R1/R2).
Status is read synchronously (pm.status), never via asyncio.run(pm.*).
"""
from __future__ import annotations

import logging
import pathlib
import sys
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.process import ProcState, pm
from app.core.workspaces import registry
from app.models.connections import mask_env
from app.models.requests import OnboardRequest, UpdatePromptRequest, WorkspaceUpdateRequest
from app.models.workspace import RepoProfile
from app.services.prompt_manager import PromptManager

router = APIRouter()
log = logging.getLogger("hephaestus.backend.workspaces")


def _masked_ws_dump(ws: RepoProfile) -> dict[str, Any]:
    """Dump a (possibly resolver-injected) workspace profile with all secret-bearing env
    values masked. The role-connection resolver injects key-bearing engineProfiles into the
    in-memory profile; never expose those raw keys (or top-level engineEnv) via the API."""
    d = ws.model_dump(by_alias=True)
    d["engineEnv"] = mask_env(d.get("engineEnv") or {})
    for ep in d.get("engineProfiles") or []:
        if isinstance(ep, dict):
            ep["env"] = mask_env(ep.get("env") or {})
    return d


def _ws_prompt_mgr(repo_path: str) -> PromptManager:
    """PromptManager whose override layer is <repo>/.hephaestus/prompts."""
    return PromptManager(override_dir=pathlib.Path(repo_path) / ".hephaestus" / "prompts")


def _profiler_cmd(ws_id: str) -> list[str]:
    return [sys.executable, "-m", "app.orchestrator.main", "--profile", ws_id]


def _start_profiler(ws_id: str, repo_path: str) -> None:
    """Spawn the profiler as a supervised process (sync, R1). Best-effort."""
    if pm.status("profiler").state == ProcState.RUNNING:
        return
    try:
        pm.start("profiler", _profiler_cmd(ws_id), cwd=repo_path, env={"HEPHAESTUS_WORKSPACE_ID": ws_id})
    except Exception:  # noqa: BLE001 — onboarding launch must not crash the request
        log.exception("profiler launch failed for %s", ws_id)


@router.get("/api/v1/workspaces")
def list_workspaces() -> dict[str, Any]:
    active = registry.active()
    return {
        "ok": True,
        "workspaces": [_masked_ws_dump(w) for w in registry.list()],
        "activeId": active.id if active else None,
    }


@router.post("/api/v1/workspaces")
def create_workspace(body: OnboardRequest) -> dict[str, Any]:
    try:
        ws = registry.create(body.repoPath, name=body.name)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    _start_profiler(ws.id, ws.repo_path)
    return {"ok": True, "workspace": _masked_ws_dump(ws)}


@router.get("/api/v1/workspaces/{ws_id}")
def get_workspace(ws_id: str) -> dict[str, Any]:
    ws = registry.get(ws_id)
    if ws is None:
        return {"ok": False, "error": "workspace not found"}
    onboarding = pm.status("profiler")  # sync (R1)
    return {"ok": True, "workspace": _masked_ws_dump(ws), "onboarding": onboarding.model_dump()}


_SINGLE_ROLES = ("primary", "fallback", "planner", "final", "merge")
_LIST_ROLES = ("validators", "arbiters")


def _role_connection_ids(role_connections: dict[str, Any]) -> list[str]:
    """Flatten every connection id referenced by a roleConnections patch (singles + lists)."""
    ids: list[str] = []
    for role in _SINGLE_ROLES:
        cid = role_connections.get(role)
        if isinstance(cid, str) and cid:
            ids.append(cid)
    for role in _LIST_ROLES:
        for cid in role_connections.get(role) or []:
            if isinstance(cid, str) and cid:
                ids.append(cid)
    return ids


@router.api_route("/api/v1/workspaces/{ws_id}", methods=["PUT", "PATCH"], response_model=None)
def update_workspace(ws_id: str, body: WorkspaceUpdateRequest) -> dict[str, Any] | JSONResponse:
    if registry.get(ws_id) is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "workspace not found"})
    patch = dict(body.model_dump(exclude_none=True))
    role_connections = patch.get("roleConnections")
    if role_connections is not None:
        from app.services import connections as conn_store

        for cid in _role_connection_ids(role_connections):
            if conn_store.get_connection(cid) is None:
                return JSONResponse(
                    status_code=400,
                    content={"ok": False, "error": f"unknown connection id: {cid}"},
                )
    try:
        ws = registry.update(ws_id, patch)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "workspace": _masked_ws_dump(ws)}


@router.get("/api/v1/workspaces/{ws_id}/dirs")
def list_workspace_dirs(ws_id: str, under: str = "") -> dict[str, Any]:
    """Immediate subdirectories of <repo>/<under> for the scan-scope picker (checkbox tree).
    `under` is a repo-relative path ("" = root); the UI lazy-loads deeper levels on expand."""
    from app.core.scan_run import list_subdirs

    ws = registry.get(ws_id)
    if ws is None:
        return {"ok": False, "error": "workspace not found"}
    return {"ok": True, "under": under, "dirs": list_subdirs(ws.repo_path, under)}


@router.post("/api/v1/workspaces/{ws_id}/activate")
def activate_workspace(ws_id: str) -> dict[str, Any]:
    if registry.get(ws_id) is None:
        return {"ok": False, "error": "workspace not found"}
    registry.activate(ws_id)
    return {"ok": True, "activeId": ws_id}


# ---------------------------------------------------------------------------
# Per-workspace prompt overrides (<repo>/.hephaestus/prompts) — global templates that
# can be overridden per repository. Global templates: /api/v1/prompts/*.
# ---------------------------------------------------------------------------


@router.get("/api/v1/workspaces/{ws_id}/prompts")
def list_ws_prompts(ws_id: str) -> dict[str, Any]:
    ws = registry.get(ws_id)
    if ws is None:
        return {"ok": False, "error": "workspace not found"}
    mgr = _ws_prompt_mgr(ws.repo_path)
    out: list[dict[str, Any]] = []
    for p in mgr.list_prompts():
        name = str(p["name"])
        out.append({"name": name, "variables": p.get("variables", []),
                    "overridden": mgr.is_overridden(name)})
    return {"ok": True, "prompts": out}


@router.get("/api/v1/workspaces/{ws_id}/prompts/{name}", response_model=None)
def get_ws_prompt(ws_id: str, name: str) -> dict[str, Any] | JSONResponse:
    ws = registry.get(ws_id)
    if ws is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "workspace not found"})
    detail = _ws_prompt_mgr(ws.repo_path).get_prompt_detail(name)
    if detail is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"prompt '{name}' not found"})
    return {"ok": True, **detail}


@router.put("/api/v1/workspaces/{ws_id}/prompts/{name}", response_model=None)
def put_ws_prompt(ws_id: str, name: str, body: UpdatePromptRequest) -> dict[str, Any] | JSONResponse:
    ws = registry.get(ws_id)
    if ws is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "workspace not found"})
    detail = _ws_prompt_mgr(ws.repo_path).set_override(name, body.content)
    if detail is None:
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid prompt name or content"})
    return {"ok": True, **detail}


@router.delete("/api/v1/workspaces/{ws_id}/prompts/{name}", response_model=None)
def delete_ws_prompt(ws_id: str, name: str) -> dict[str, Any] | JSONResponse:
    ws = registry.get(ws_id)
    if ws is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "workspace not found"})
    detail = _ws_prompt_mgr(ws.repo_path).clear_override(name)
    if detail is None:
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid prompt name"})
    return {"ok": True, **detail}
