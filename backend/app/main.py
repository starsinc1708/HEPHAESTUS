from __future__ import annotations

import asyncio
import hmac
import logging
import mimetypes
import os
import shutil
import subprocess
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import HOST, LOOP_HOME, PORT

log = logging.getLogger("hephaestus.backend")

# ---------------------------------------------------------------------------
# In-memory rate limiter for auth endpoints
# ---------------------------------------------------------------------------

_AUTH_RATE_LIMITS: dict[str, list[float]] = {}  # ip -> [timestamps]
_AUTH_RATE_MAX_ATTEMPTS = 5
_AUTH_RATE_WINDOW = 300  # 5 minutes


def _check_auth_rate_limit(ip: str) -> bool:
    """Return True if the IP is rate-limited (too many failed attempts)."""
    now = time.time()
    attempts = _AUTH_RATE_LIMITS.get(ip, [])
    # Prune old attempts
    attempts = [t for t in attempts if now - t < _AUTH_RATE_WINDOW]
    _AUTH_RATE_LIMITS[ip] = attempts
    return len(attempts) >= _AUTH_RATE_MAX_ATTEMPTS


def _record_auth_failure(ip: str) -> None:
    now = time.time()
    attempts = _AUTH_RATE_LIMITS.get(ip, [])
    attempts.append(now)
    _AUTH_RATE_LIMITS[ip] = attempts


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def ok_response(data: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    result = {"ok": True, **kwargs}
    if data is not None:
        result.update(data)
    return result


def error_response(error: str, status: int = 400, **kwargs: Any) -> JSONResponse:
    return JSONResponse({"ok": False, "error": error, **kwargs}, status_code=status)


# ---------------------------------------------------------------------------
# Tool availability check
# ---------------------------------------------------------------------------


def _check_tool_exists(name: str) -> bool:
    return shutil.which(name) is not None


# ---------------------------------------------------------------------------
# Lifespan — start / stop background tasks
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from app.core.broadcaster import state_broadcaster

    # --- Startup banner ---
    log.info("HEPHAESTUS Dashboard v0.1 starting on %s:%s", HOST, PORT)

    # --- Startup validation: check required tools on PATH ---
    for tool_name in ("git", "opencode"):
        if not _check_tool_exists(tool_name):
            log.warning("startup check: '%s' not found on PATH", tool_name)

    from app.config import STATE_DIR as _SD
    from app.core.migrate import migrate_legacy_state, run_migrations

    with __import__("contextlib").suppress(Exception):
        migrate_legacy_state()

    with __import__("contextlib").suppress(Exception):
        run_migrations(_SD)

    try:
        from app.core.merge_job import MergeJobRunner
        from app.core.workspaces import active_workspace
        _ws = active_workspace()
        if _ws is not None:
            MergeJobRunner(_ws).reap()
    except Exception:
        log.debug("merge reaper skipped", exc_info=True)

    # Auto-driver (#3): if a previous run left queued/in_progress items and the driver is
    # not paused, resume them. A fresh/empty store has nothing runnable → no spawn.
    # NEVER auto-spawn under pytest: tests boot the app via TestClient (→ this lifespan), and
    # when HEPHAESTUS runs a task on its OWN repo the agent/funnel runs that very suite — an
    # auto-spawn there would launch a second orchestrator that races/kills the live one. Real
    # runs (uvicorn) have no `pytest` module imported.
    import sys as _sys

    if "pytest" not in _sys.modules:
        with __import__("contextlib").suppress(Exception):
            from app.core.driver import reconcile_driver

            reconcile_driver()

        # Phase 2 (REL-001): auto-retention of old iteration dirs on startup.
        # Runs once at boot — subsequent periodic pruning is optional.
        with __import__("contextlib").suppress(Exception):
            from app.core.iters import prune_iters

            result = prune_iters()
            if result.get("pruned"):
                log.info("startup iter pruning: removed %d dirs", len(result["pruned"]))

        # Phase 2 (REL-002): reap orphaned subprocesses whose root PID is dead.
        from app.core.process import pm as _pm

        with __import__("contextlib").suppress(Exception):
            reaped = _pm.reap_orphans()
            if reaped:
                log.info("startup orphan reaping: cleaned %d entries", len(reaped))

    task = asyncio.create_task(state_broadcaster())
    log.info("state_broadcaster background task started")

    yield
    # --- Graceful shutdown with drain ---
    task.cancel()
    with __import__("contextlib").suppress(asyncio.CancelledError):
        await task
    log.info("state_broadcaster background task stopped")

    # Cancel all managed processes (cross-platform)
    from app.core.process import pm

    with __import__("contextlib").suppress(Exception):
        pm.cancel_all()

    # Close all WebSocket connections with shutdown message
    from app.services.ws_manager import manager as ws_manager

    for room_conns in list(ws_manager._rooms.values()):
        for ws in list(room_conns):
            with __import__("contextlib").suppress(Exception):
                await ws.send_json({"type": "shutdown", "reason": "server shutting down"})
            with __import__("contextlib").suppress(Exception):
                await ws.close()

    # Wait up to 5s for background tasks to complete
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        done, _ = await asyncio.wait(pending, timeout=5)
        if len(done) < len(pending):
            log.warning("shutdown: %d tasks did not complete in 5s", len(pending) - len(done))
    log.info("shutdown complete")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = FastAPI(title="HEPHAESTUS Loop API", version="0.1.0", lifespan=lifespan)

# --- Router registration ---

from app.api.v1.agent_jobs import router as agent_jobs_router  # noqa: E402
from app.api.v1.agents import router as agents_router  # noqa: E402
from app.api.v1.branches import router as branches_router  # noqa: E402
from app.api.v1.clis import router as clis_router  # noqa: E402
from app.api.v1.config_route import router as config_router  # noqa: E402
from app.api.v1.connections import router as connections_router  # noqa: E402
from app.api.v1.costs import router as costs_router  # noqa: E402
from app.api.v1.decisions import router as decisions_router  # noqa: E402
from app.api.v1.echo import router as echo_router  # noqa: E402
from app.api.v1.fs import router as fs_router  # noqa: E402
from app.api.v1.goals import router as goals_router  # noqa: E402
from app.api.v1.health import router as health_router  # noqa: E402
from app.api.v1.ideas import router as ideas_router  # noqa: E402
from app.api.v1.insights import router as insights_router  # noqa: E402
from app.api.v1.integrations import router as integrations_router  # noqa: E402
from app.api.v1.issues import router as issues_router  # noqa: E402
from app.api.v1.iters import router as iters_router  # noqa: E402
from app.api.v1.loop import router as loop_router  # noqa: E402
from app.api.v1.memory import router as memory_router  # noqa: E402
from app.api.v1.merge import router as merge_router  # noqa: E402
from app.api.v1.prompts import router as prompts_router  # noqa: E402
from app.api.v1.repos import router as repos_router  # noqa: E402
from app.api.v1.scans import router as scans_router  # noqa: E402
from app.api.v1.state import router as state_router  # noqa: E402
from app.api.v1.tasks import router as tasks_router  # noqa: E402
from app.api.v1.version import router as version_router  # noqa: E402
from app.api.v1.workspaces import router as workspaces_router  # noqa: E402
from app.api.v1.worktrees import router as worktrees_router  # noqa: E402
from app.api.ws import router as ws_router  # noqa: E402

app.include_router(state_router)
app.include_router(config_router)
app.include_router(loop_router)
app.include_router(tasks_router)
app.include_router(iters_router)
app.include_router(scans_router)
app.include_router(branches_router)
app.include_router(decisions_router)
app.include_router(echo_router)
app.include_router(fs_router)
app.include_router(agents_router)

# --- Universality routers ---
app.include_router(issues_router)
app.include_router(prompts_router)
app.include_router(repos_router)
# memory_router's type is undeterminable here due to the app.main<->memory circular
# import (memory.py imports `error_response` from app.main). Both has-type (cycle
# unresolved) and unused-ignore (cycle resolved) can surface depending on mypy's
# module-analysis order, so silence both; behavior is unaffected.
app.include_router(memory_router)  # type: ignore[has-type, unused-ignore]
app.include_router(workspaces_router)
app.include_router(merge_router)
app.include_router(goals_router)
app.include_router(ideas_router)
app.include_router(insights_router)
app.include_router(integrations_router)
app.include_router(agent_jobs_router)
app.include_router(clis_router)
app.include_router(connections_router)
app.include_router(costs_router)
app.include_router(worktrees_router)
app.include_router(health_router)
app.include_router(version_router)

# --- WebSocket router ---
app.include_router(ws_router)


# ---------------------------------------------------------------------------
# Auth middleware — optional bearer-token auth gated by HEPHAESTUS_DASHBOARD_PASSWORD
# ---------------------------------------------------------------------------

router: APIRouter = APIRouter()


@app.middleware("http")
async def auth_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Simple bearer-token auth. If HEPHAESTUS_DASHBOARD_PASSWORD is set, require it."""
    password = os.environ.get("HEPHAESTUS_DASHBOARD_PASSWORD", "")
    if password:
        # Allow healthz and readiness without auth
        if request.url.path in ("/healthz", "/health/ready"):
            return await call_next(request)
        # Check Authorization header
        auth = request.headers.get("Authorization", "")
        if hmac.compare_digest(auth, f"Bearer {password}"):
            pass  # authorized via header
        else:
            # Check cookie
            cookies = request.cookies
            if cookies.get("hephaestus_session") == password:
                pass  # authorized via cookie
            else:
                log.warning("auth failed: %s %s", request.url.path, request.headers.get("remote-addr", "unknown"))
                if request.method == "GET":
                    return JSONResponse(
                        status_code=401,
                        content={"ok": False, "error": "unauthorized"},
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                return JSONResponse(status_code=401, content={"ok": False, "error": "unauthorized"})
    return await call_next(request)


@router.post("/api/auth/login")
async def auth_login(body: dict[str, Any]) -> dict[str, Any]:
    """Login with password, set session cookie."""
    client_ip = "unknown"
    if _check_auth_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="too many attempts")
    password = os.environ.get("HEPHAESTUS_DASHBOARD_PASSWORD", "")
    if not password:
        return {"ok": True, "note": "auth disabled"}
    if hmac.compare_digest(body.get("password", ""), password):
        return {"ok": True, "token": password}
    log.warning("auth failed: /api/auth/login %s", client_ip)
    _record_auth_failure(client_ip)
    raise HTTPException(status_code=401, detail="invalid password")


app.include_router(router)


# ---------------------------------------------------------------------------
# CORS / CSRF middleware — ported from server.py Handler._allowed_origin / _check_csrf
# ---------------------------------------------------------------------------

DASHBOARD_DIR = LOOP_HOME / "frontend" / "dist"
INDEX_HTML = DASHBOARD_DIR / "index.html"

# Explicit loopback aliases that are always accepted.
_LOOPBACK_ORIGINS = {f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"}
_LOOPBACK_REFERER_PREFIXES = (f"http://localhost:{PORT}/", f"http://127.0.0.1:{PORT}/")

# Extra operator-supplied origins (comma-separated env var).
_EXTRA_ORIGINS: set[str] = {
    o.strip() for o in os.environ.get("HEPHAESTUS_DASHBOARD_ALLOWED_ORIGINS", "").split(",") if o.strip()
}


def _allowed_origin(origin: str, host: str) -> str:
    """An Origin is allowed if it matches the Host the client connected to.

    This correctly handles ssh-tunneled localhost AND direct LAN-IP access
    AND custom DNS names — all without operator config — because the browser
    always reports an Origin that matches the URL bar.
    """
    if not origin:
        return ""
    if host and (origin == f"http://{host}" or origin == f"https://{host}"):
        return origin
    if origin in _LOOPBACK_ORIGINS:
        return origin
    if origin in _EXTRA_ORIGINS:
        return origin
    return ""


def _check_csrf(request: Request) -> bool:
    """For mutating methods, require same-origin proof.

    Strategy: Origin OR Referer must match the Host header.
    Independent of how the server binds — works for SSH tunnels,
    LAN access, DNS hostnames, etc.
    """
    if request.method == "GET":
        return True
    origin = request.headers.get("origin", "")
    if origin and _allowed_origin(origin, request.headers.get("host", "")):
        return True
    # Browsers omit Origin on some same-origin POSTs; fall back to Referer.
    ref = request.headers.get("referer", "")
    if ref:
        host = request.headers.get("host", "")
        if host and (ref.startswith(f"http://{host}/") or ref.startswith(f"https://{host}/")):
            return True
        for prefix in _LOOPBACK_REFERER_PREFIXES:
            if ref.startswith(prefix):
                return True
    return False


class CsrfCorsMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces CSRF on mutating methods and adds CORS on GETs."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # CSRF check for mutating methods
        if request.method != "GET" and not _check_csrf(request):
            return JSONResponse(
                status_code=403,
                content={"ok": False, "error": f"cross-origin {request.method} refused (CSRF guard)"},
            )
        response = await call_next(request)
        # CORS: only on GETs, echo same-Host origin
        if request.method == "GET":
            origin = request.headers.get("origin", "")
            if origin:
                allowed = _allowed_origin(origin, request.headers.get("host", ""))
                if allowed:
                    response.headers["Access-Control-Allow-Origin"] = allowed
        return response


app.add_middleware(CsrfCorsMiddleware)


# ---------------------------------------------------------------------------
# Cache-Control: no-store on API responses
# ---------------------------------------------------------------------------


class NoStoreMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/api/") or request.url.path == "/healthz":
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return response


app.add_middleware(NoStoreMiddleware)


# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


app.add_middleware(SecurityHeadersMiddleware)


# ---------------------------------------------------------------------------
# Body size limit (5 MB) — defense against memory exhaustion
# ---------------------------------------------------------------------------


class BodyLimitMiddleware(BaseHTTPMiddleware):
    MAX_BODY = 5_000_000

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        cl = int(request.headers.get("content-length", "0"))
        if cl > self.MAX_BODY:
            return JSONResponse(status_code=413, content={"ok": False, "error": "body too large"})
        return await call_next(request)


app.add_middleware(BodyLimitMiddleware)


# ---------------------------------------------------------------------------
# Exception handler — return JSON errors (mirrors server.py error handling)
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.error("handler error %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": "Internal server error", "detail": str(exc)},
    )


# ---------------------------------------------------------------------------
# Healthz
# ---------------------------------------------------------------------------


@app.get("/healthz")
async def healthz() -> PlainTextResponse:
    """Simple liveness probe — always returns 'ok'."""
    return PlainTextResponse("ok")


@app.get("/health/ready")
async def health_ready() -> JSONResponse:
    """Readiness probe — checks STATE_DIR, REPO, and git availability."""
    from app.config import REPO, STATE_DIR as _STATE_DIR  # noqa: I001

    checks: dict[str, bool] = {}

    # Check STATE_DIR exists and is writable
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _STATE_DIR / ".healthz-write-test"
        tmp.write_text("ok")
        tmp.unlink()
        checks["state_dir"] = True
    except Exception:
        checks["state_dir"] = False

    # Check REPO exists and is a git repo
    try:
        repo_path = __import__("pathlib").Path(REPO)
        checks["repo"] = (repo_path / ".git").exists()
    except Exception:
        checks["repo"] = False

    # Check git --version works
    try:
        result = subprocess.run(
            ["git", "--version"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=5, check=False,
        )
        checks["git"] = result.returncode == 0
    except Exception:
        checks["git"] = False

    all_ok = all(checks.values())
    return JSONResponse(
        {"ok": all_ok, "checks": checks},
        status_code=200 if all_ok else 503,
    )


# ---------------------------------------------------------------------------
# Static file serving: / and /index.html → frontend/dist/index.html
#                       /static/{path} → frontend/dist/{path}
# ---------------------------------------------------------------------------


MAX_STATIC_SIZE = 10_000_000  # 10 MB


@app.get("/")
async def serve_index() -> Response:
    if not INDEX_HTML.exists():
        return PlainTextResponse("index.html not found", status_code=404)
    if INDEX_HTML.stat().st_size > MAX_STATIC_SIZE:
        return PlainTextResponse("file too large", status_code=413)
    return Response(content=INDEX_HTML.read_text(encoding="utf-8"), media_type="text/html; charset=utf-8")


@app.get("/index.html")
async def serve_index_html() -> Response:
    return await serve_index()


@app.get("/static/{path:path}")
async def serve_static(path: str) -> Response:
    target = (DASHBOARD_DIR / path).resolve()
    try:
        target.relative_to(DASHBOARD_DIR.resolve())
    except ValueError:
        return PlainTextResponse("not found", status_code=404)
    if not target.is_file():
        return PlainTextResponse("not found", status_code=404)
    if target.stat().st_size > MAX_STATIC_SIZE:
        return PlainTextResponse("file too large", status_code=413)
    ct = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return Response(content=target.read_bytes(), media_type=ct)


@app.get("/assets/{path:path}")
async def serve_assets(path: str) -> Response:
    """Serve Vite build assets (CSS, JS, fonts) from frontend/dist/assets/."""
    target = (DASHBOARD_DIR / "assets" / path).resolve()
    try:
        target.relative_to(DASHBOARD_DIR.resolve())
    except ValueError:
        return PlainTextResponse("not found", status_code=404)
    if not target.is_file():
        return PlainTextResponse("not found", status_code=404)
    if target.stat().st_size > MAX_STATIC_SIZE:
        return PlainTextResponse("file too large", status_code=413)
    ct = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return Response(content=target.read_bytes(), media_type=ct)


# ---------------------------------------------------------------------------
# SPA catch-all: any non-API, non-static path → index.html (client-side routing)
# ---------------------------------------------------------------------------


@app.get("/{path:path}")
async def spa_fallback(path: str) -> Response:
    """Serve index.html for client-side routes; real 404 for unknown API/health paths."""
    # Unknown /api/* (and /healthz) are NOT SPA routes — return a real 404 instead of
    # serving the HTML shell, which would otherwise mask a missing/typo'd endpoint.
    if path.startswith("api/") or path == "healthz":
        return PlainTextResponse("not found", status_code=404)
    return await serve_index()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    bind_msg = f"dashboard listening on http://{HOST}:{PORT}/"
    if HOST == "0.0.0.0":
        bind_msg += "  ⚠ EXPOSED ON ALL INTERFACES — set HEPHAESTUS_DASHBOARD_HOST=127.0.0.1 to restrict to loopback"
    elif HOST == "127.0.0.1":
        bind_msg += "  (loopback only — set HEPHAESTUS_DASHBOARD_HOST=0.0.0.0 for LAN access)"
    print(bind_msg)
    log.info(bind_msg)
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False)
