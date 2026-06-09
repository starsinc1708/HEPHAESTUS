"""Driver control via SYNC ProcessManager (D1, R1) — replaces tmux/pgrep/pkill loop mgmt.

All pm.* calls are synchronous; NEVER asyncio.run(pm.*). The loop is launched as a separate
supervised process: `python -m app.orchestrator.main --workspace <id>`.
"""
from __future__ import annotations

import logging
import pathlib
import sys
from typing import Any

from app.core.process import ProcState, pm

log = logging.getLogger("hephaestus.backend.driver")

# Dir containing the importable `app` package (…/backend). The loop is launched as
# `python -m app.orchestrator.main`; the package isn't necessarily pip-installed in the
# venv, so we put this on PYTHONPATH or it dies with ModuleNotFoundError. core/driver.py
# -> parents[2] == backend.
_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]


# ---------- backward-compat shim for callers that still import _tmux_has (scan.py) ----------


def _tmux_has(session: str) -> bool:
    """Deprecated — returns True when the named process is RUNNING via pm."""
    return pm.status(session).state == ProcState.RUNNING


# ---------- workspace helpers ----------


def _active_ws_id() -> str | None:
    try:
        from app.core.workspaces import registry
        ws = registry.active()
        return ws.id if ws is not None else None
    except Exception:
        log.warning("failed to resolve active workspace id", exc_info=True)
        return None


def _loop_cmd() -> list[str]:
    cmd = [sys.executable, "-m", "app.orchestrator.main"]
    ws_id = _active_ws_id()
    if ws_id:
        cmd += ["--workspace", ws_id]
    return cmd


def _loop_cwd() -> str:
    try:
        from app.core.workspaces import registry
        ws = registry.active()
        if ws is not None:
            return ws.repo_path
    except Exception:
        log.warning("failed to resolve workspace cwd — falling back to LOOP_HOME", exc_info=True)
    from app.config import LOOP_HOME
    return str(LOOP_HOME)


# ---------- public API (used by router) ----------


def _loop_status() -> dict[str, Any]:
    handle = pm.status("loop")  # sync (R1)
    return {
        "process": handle.model_dump(),  # contains 'pid' (R9)
        "tmux": handle.state == ProcState.RUNNING,  # deprecated mirror
        "driver_pid": handle.pid,  # deprecated; read process.pid
        "opencode_pids": handle.children,
    }


def _start_loop(opts: dict[str, Any]) -> dict[str, Any]:
    from app.config import _config_effective, filter_env_bits

    if pm.status("loop").state == ProcState.RUNNING:
        return {"ok": False, "error": "loop already running"}

    env_bits: dict[str, str] = dict(_config_effective())
    # The request model dumps every field (maxIter=None for a {} body), so guard on the
    # VALUE, not key presence — otherwise a plain start hits int(None) and 400s. None/""
    # = "not provided" → keep the config default (HEPHAESTUS_MAX_ITER from Базовые параметры).
    if opts.get("maxIter") not in (None, ""):
        try:
            env_bits["HEPHAESTUS_MAX_ITER"] = str(int(opts["maxIter"]))
        except (ValueError, TypeError):
            return {"ok": False, "error": "maxIter must be an integer"}
    if opts.get("tierReview") is not None:
        env_bits["HEPHAESTUS_TIER_REVIEW"] = "on" if opts["tierReview"] else "off"
    # C4: Ralph run-mode parameters
    if opts.get("runMode") not in (None, ""):
        env_bits["HEPHAESTUS_RUN_MODE"] = str(opts["runMode"])
    if opts.get("costBudgetUsd") not in (None, ""):
        try:
            env_bits["HEPHAESTUS_COST_BUDGET_USD"] = str(float(opts["costBudgetUsd"]))
        except (ValueError, TypeError):
            return {"ok": False, "error": "costBudgetUsd must be a number"}
    if opts.get("wallclockSec") not in (None, ""):
        try:
            env_bits["HEPHAESTUS_WALLCLOCK_SEC"] = str(int(opts["wallclockSec"]))
        except (ValueError, TypeError):
            return {"ok": False, "error": "wallclockSec must be an integer"}
    if opts.get("maxConsecFail") not in (None, ""):
        try:
            env_bits["HEPHAESTUS_MAX_CONSEC_FAIL"] = str(int(opts["maxConsecFail"]))
        except (ValueError, TypeError):
            return {"ok": False, "error": "maxConsecFail must be an integer"}
    ws_id = _active_ws_id()
    if ws_id:
        env_bits["HEPHAESTUS_WORKSPACE_ID"] = ws_id
    env_bits = {k: str(v) for k, v in filter_env_bits(env_bits).items() if v not in (None, "")}
    # PYTHONPATH isn't a config key (filtered out above) — set it after filtering so the
    # spawned `python -m app.orchestrator.main` can import `app` regardless of cwd.
    env_bits["PYTHONPATH"] = str(_BACKEND_DIR)

    import contextlib

    from app.core.state import _state_dir

    log_path = _state_dir() / "loop.log"
    with contextlib.suppress(OSError):
        log_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        handle = pm.start("loop", _loop_cmd(), cwd=_loop_cwd(), env=env_bits,
                          output_path=str(log_path))
    except FileNotFoundError:
        return {"ok": False, "error": "python executable not found"}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "session": "loop", "env": env_bits, "pid": handle.pid}


def _stop_loop_soft() -> dict[str, Any]:
    pm.stop("loop")
    return {"ok": True, "note": "loop stop requested"}


def _kill_loop_hard() -> dict[str, Any]:
    if pm.status("loop").state != ProcState.RUNNING:
        return {"ok": True, "note": "loop was not running"}
    handle = pm.cancel("loop")
    return {"ok": True, "exit_code": handle.exit_code}


# ---------- auto-driver: pause flag + reconciler (the single source of truth for
# "should the loop be running") ----------

_DRIVER_FILE = "driver.json"


def driver_paused() -> bool:
    """Read the persisted paused flag from <state_dir>/driver.json. Defaults to False;
    a missing or corrupt file is treated as not-paused (never crashes)."""
    import json

    from app.core.state import _state_dir

    try:
        path = _state_dir() / _DRIVER_FILE
        if not path.exists():
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        return bool(data.get("paused", False))
    except Exception:
        log.debug("driver_paused: failed to read driver.json — defaulting to False", exc_info=True)
        return False


def set_driver_paused(value: bool) -> bool:
    """Persist the paused flag atomically to <state_dir>/driver.json.

    Returns True on success, False if the write failed (permission/disk). A failed persist
    is surfaced (not silently swallowed) so the caller can report it — otherwise /pause would
    claim ok:true while the flag was never written, and the loop would auto-start after a
    restart, contradicting the user's pause.
    """
    import json

    from app.core.state import _atomic_write, _state_dir

    try:
        sd = _state_dir()
        sd.mkdir(parents=True, exist_ok=True)
        _atomic_write(sd / _DRIVER_FILE, json.dumps({"paused": bool(value)}))
        return True
    except Exception:
        log.warning("set_driver_paused: failed to persist paused=%s", value, exc_info=True)
        return False


def _has_runnable() -> bool:
    """True if anything is runnable RIGHT NOW: any item in_progress OR any ready (queued +
    deps satisfied). Shares app.core.deps.has_runnable with the loop's exit check so the
    reconciler and the loop agree — a dead-end (queued items whose deps are not done) is
    NOT runnable. Never crashes."""
    from app.core import deps
    from app.core.state import _read_state

    try:
        return deps.has_runnable(_read_state().get("items", []))
    except Exception:
        log.debug("_has_runnable: read failed — assuming nothing runnable", exc_info=True)
        return False


def _driver_counts() -> dict[str, int]:
    """{"queued": N, "inProgress": M} from work-state (camelCase for the status payload)."""
    from app.core.state import _read_state

    queued = in_progress = 0
    try:
        for it in _read_state().get("items", []):
            st = it.get("status")
            if st == "queued":
                queued += 1
            elif st == "in_progress":
                in_progress += 1
    except Exception:
        log.debug("_driver_counts: read failed", exc_info=True)
    return {"queued": queued, "inProgress": in_progress}


def reconcile_driver() -> dict[str, Any]:
    """Single source of truth for "should the loop be running". Start the loop iff there is
    something runnable AND the driver is not paused AND the loop process is not already
    RUNNING. Idempotent, safe to call often, never crashes."""
    try:
        if not _has_runnable():
            return {"ok": True, "note": "no-op (nothing runnable)"}
        if driver_paused():
            return {"ok": True, "note": "no-op (paused)"}
        if pm.status("loop").state == ProcState.RUNNING:
            return {"ok": True, "note": "no-op (running)"}
        result = _start_loop({})
        # Race: another caller may have started the loop between our RUNNING check above and
        # _start_loop's own check. "loop already running" IS the desired state — treat it as a
        # success no-op so /resume doesn't surface ok:false at HTTP 200.
        if not result.get("ok") and "already running" in str(result.get("error", "")):
            return {"ok": True, "note": "no-op (already running)"}
        return result
    except Exception as e:  # noqa: BLE001 — reconcile must never raise to a request handler
        log.warning("reconcile_driver failed: %s", e)
        return {"ok": False, "error": str(e)}
