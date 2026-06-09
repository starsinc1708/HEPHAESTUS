"""Integrations API router — Epic 3 + v2 #8 (UI connect).

Endpoints:
  GET  /api/v1/integrations                    — list providers + connection state
  POST /api/v1/integrations/{name}/connect     — store PAT + verify (no env)
  POST /api/v1/integrations/{name}/verify       — re-verify the stored PAT
  POST /api/v1/integrations/{name}/disconnect   — erase the stored PAT
  POST /api/v1/integrations/{name}/import      — import issues into queue
  POST /api/v1/integrations/{name}/sync-status/{item_id} — push status back
  POST /api/v1/integrations/pr                 — create a pull request

All responses: {ok, ...} / {ok:false, error}; unavailable → 409, never 500.
Tokens are masked in every response and never logged.
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services.integrations.base import ProviderCapabilities
from app.services.integrations.creds import (
    KNOWN_PROVIDERS,
    clear_cred,
    get_cred,
    list_masked,
    mask_token,
    set_cred,
    set_status,
)
from app.services.integrations.registry import default_provider, get_provider
from app.services.integrations.verify import normalize_gitlab_host, verify_credential

if TYPE_CHECKING:
    from app.models.workspace import RepoProfile

log = logging.getLogger("hephaestus.backend.integrations")

router = APIRouter()

# Capabilities are static per provider — both support issues + pull/merge requests.
_CAPABILITIES: dict[str, ProviderCapabilities] = {
    "github": ProviderCapabilities(issues=True, pull_requests=True),
    "gitlab": ProviderCapabilities(issues=True, pull_requests=True),
}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _persist_status(name: str, status: str, error: str | None) -> None:
    """Best-effort status write — a disk error must never 500 the endpoint."""
    try:
        set_status(name, status, error=error, tested_at=_now())
    except Exception:  # noqa: BLE001
        log.warning("set_status %s failed (disk error?)", name, exc_info=True)

# ---------------------------------------------------------------------------
# Branch safety: for PR creation we accept any safe branch name (not just
# auto/*), but still reject injections, flags, traversal, etc.
# ---------------------------------------------------------------------------

_SAFE_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")


def _is_safe_pr_branch(name: str) -> bool:
    """Accept any branch name that is safe for git operations.

    Applies a broader allowlist than _is_safe_auto_branch (which requires
    the auto/ prefix). Delegates to _is_safe_auto_branch for auto/* names
    so the prefix validation is consistent.
    """
    if not name or not isinstance(name, str):
        return False
    if ".." in name or "//" in name:
        return False
    if name.startswith("-"):
        return False
    if any(c in name for c in "\n\r\t \x00\\"):
        return False
    # Delegate auto/* branches to the canonical check.
    try:
        from app.core.git import _is_safe_auto_branch

        if name.startswith("auto/"):
            return _is_safe_auto_branch(name)
    except Exception:  # noqa: BLE001
        log.debug("_is_safe_pr_branch: auto branch check failed for %s", name, exc_info=True)
        pass
    return bool(_SAFE_BRANCH_RE.match(name))


# ---------------------------------------------------------------------------
# Workspace helper — mirrors merge.py / goals.py
# ---------------------------------------------------------------------------


class NoActiveWorkspace(RuntimeError):
    """Raised when no workspace is active."""

    def __init__(self, message: str = "no active workspace") -> None:
        super().__init__(message)


def active_workspace() -> RepoProfile:
    """Resolve the active workspace or raise NoActiveWorkspace."""
    try:
        from app.core.workspaces import active_workspace as _aw
    except ImportError as exc:
        raise NoActiveWorkspace("workspace registry unavailable") from exc
    ws = _aw()
    if ws is None:
        raise NoActiveWorkspace("no active workspace")
    return ws


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class _ConnectBody(BaseModel):
    token: str
    host: str | None = None


class _ImportBody(BaseModel):
    label: str


class _PRBody(BaseModel):
    branch: str
    provider: str | None = None
    title: str | None = None
    body: str = ""
    base: str | None = None


# ---------------------------------------------------------------------------
# GET /api/v1/integrations
# ---------------------------------------------------------------------------


@router.get("/api/v1/integrations", response_model=None)
def list_integrations() -> dict[str, Any]:
    """List every known provider with capabilities + connection state (token masked).

    Always returns github + gitlab (even when nothing is connected) so the UI can
    render a connect card; ``connected``/``token``/``host`` reflect the store.
    """
    providers: list[dict[str, Any]] = []
    for row in list_masked():
        caps = _CAPABILITIES.get(row["name"], ProviderCapabilities())
        providers.append({**row, "capabilities": caps.model_dump(by_alias=True)})
    dflt = default_provider()
    return {
        "ok": True,
        "providers": providers,
        "default": dflt.name if dflt is not None else None,
    }


# ---------------------------------------------------------------------------
# Connect / verify / disconnect (v2 #8) — store a PAT in the UI, no env files
# ---------------------------------------------------------------------------


def _state_response(name: str, status: str, error: str | None, token: str, host: str | None) -> dict[str, Any]:
    return {
        "ok": True,
        "name": name,
        "status": status,
        "connected": status == "connected",
        "error": error,
        "token": mask_token(token),
        "host": host,
    }


@router.post("/api/v1/integrations/{name}/connect", response_model=None)
def connect(name: str, body: _ConnectBody) -> dict[str, Any] | JSONResponse:
    """Store *name*'s PAT (+ host for GitLab) and verify it. Never 500."""
    if name not in KNOWN_PROVIDERS:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"unknown provider '{name}'"})
    token = (body.token or "").strip()
    if not token:
        return JSONResponse(status_code=400, content={"ok": False, "error": "token required"})

    host: str | None = None
    if name == "gitlab":
        host = normalize_gitlab_host(body.host)
        if host is None:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": "invalid GitLab URL (https required)"},
            )

    try:
        set_cred(name, token, host=host)
        status, error = verify_credential(name, token=token, host=host)
    except Exception:  # noqa: BLE001 — never crash the endpoint
        log.warning("connect %s failed unexpectedly", name, exc_info=True)
        status, error = "failed", "internal error"
    _persist_status(name, status, error)
    return _state_response(name, status, error, token, host)


@router.post("/api/v1/integrations/{name}/verify", response_model=None)
def verify(name: str) -> dict[str, Any] | JSONResponse:
    """Re-verify the stored PAT for *name* (the «Проверить» action). Never 500."""
    if name not in KNOWN_PROVIDERS:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"unknown provider '{name}'"})
    cred = get_cred(name)
    if not cred or not cred.get("token"):
        return JSONResponse(status_code=409, content={"ok": False, "error": "not connected"})
    token = str(cred["token"])
    host = cred.get("host") if name == "gitlab" else None
    try:
        status, error = verify_credential(name, token=token, host=host)
    except Exception:  # noqa: BLE001 — never crash the endpoint
        log.warning("verify %s failed unexpectedly", name, exc_info=True)
        status, error = "failed", "internal error"
    _persist_status(name, status, error)
    return _state_response(name, status, error, token, host)


@router.post("/api/v1/integrations/{name}/disconnect", response_model=None)
def disconnect(name: str) -> dict[str, Any] | JSONResponse:
    """Erase the stored PAT for *name* (the «Отключить» action)."""
    if name not in KNOWN_PROVIDERS:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"unknown provider '{name}'"})
    clear_cred(name)
    return {"ok": True, "name": name}


# ---------------------------------------------------------------------------
# POST /api/v1/integrations/{name}/import
# ---------------------------------------------------------------------------


@router.post("/api/v1/integrations/{name}/import", response_model=None)
def import_issues(name: str, body: _ImportBody) -> dict[str, Any] | JSONResponse:
    """Import issues labelled *label* from *name* provider into the work queue."""
    p = get_provider(name)
    if p is None or not p.available():
        return JSONResponse(
            status_code=409,
            content={"ok": False, "error": f"provider '{name}' unavailable"},
        )
    result = p.import_to_queue(label=body.label)
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# POST /api/v1/integrations/{name}/sync-status/{item_id}
# ---------------------------------------------------------------------------


@router.post("/api/v1/integrations/{name}/sync-status/{item_id}", response_model=None)
def sync_status(name: str, item_id: str) -> dict[str, Any] | JSONResponse:
    """Push current task status for *item_id* back to the provider."""
    p = get_provider(name)
    if p is None or not p.available():
        return JSONResponse(
            status_code=409,
            content={"ok": False, "error": f"provider '{name}' unavailable"},
        )
    from app.core.state import read_state

    state = read_state()
    items: list[dict[str, Any]] = state.get("items", [])
    item: dict[str, Any] | None = next(
        (it for it in items if it.get("id") == item_id), None
    )
    if item is None:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "error": f"item '{item_id}' not found"},
        )
    p.sync_status(item)
    return {"ok": True}


# ---------------------------------------------------------------------------
# POST /api/v1/integrations/pr
# ---------------------------------------------------------------------------


@router.post("/api/v1/integrations/pr", response_model=None)
def create_pr(body: _PRBody) -> dict[str, Any] | JSONResponse:
    """Create a pull request via the specified (or default) provider."""
    # Validate branch name.
    if not _is_safe_pr_branch(body.branch):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "invalid branch name"},
        )

    # Resolve provider.
    p = get_provider(body.provider) if body.provider else default_provider()

    if p is None or not p.available():
        return JSONResponse(
            status_code=409,
            content={"ok": False, "error": "PR creation failed (provider unavailable or error)"},
        )

    caps = p.capabilities()
    if not caps.pull_requests:
        return JSONResponse(
            status_code=409,
            content={"ok": False, "error": "PR creation failed (provider unavailable or error)"},
        )

    # Resolve base branch from active workspace when not supplied.
    base = body.base
    if base is None:
        try:
            ws = active_workspace()
            base = ws.base_branch
        except NoActiveWorkspace:
            base = "main"

    title = body.title if body.title is not None else f"HEPHAESTUS: {body.branch}"

    result = p.create_pr(body.branch, title=title, body=body.body, base=base)
    if result is None:
        return JSONResponse(
            status_code=409,
            content={"ok": False, "error": "PR creation failed (provider unavailable or error)"},
        )
    return {"ok": True, **result}
