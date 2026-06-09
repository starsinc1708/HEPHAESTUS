"""State management for HEPHAESTUS loop — ported from dashboard/server.py:101-183.

Cross-process file lock via fcntl.flock matches bash side's `flock -x 9`.
Atomic writes via tmp + fsync + os.replace.
Last-known-good cache prevents empty-file clobber.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import pathlib
import shutil
import threading
import time
from typing import IO, Any

from app.config import STATE_DIR

try:
    import fcntl  # POSIX only — required for cross-process file lock

    HAVE_FCNTL = True
except ImportError:
    HAVE_FCNTL = False

try:
    import msvcrt  # Windows only — required for cross-process file lock

    HAVE_MSVCRT = True
except ImportError:
    HAVE_MSVCRT = False

log = logging.getLogger("hephaestus.backend.state")

# Test/override hook — if set, takes precedence over the active workspace.
_STATE_DIR_OVERRIDE: pathlib.Path | None = None


def _state_dir() -> pathlib.Path:
    """Resolve the active workspace state dir, falling back to the legacy global."""
    if _STATE_DIR_OVERRIDE is not None:
        return _STATE_DIR_OVERRIDE
    try:
        from app.core.workspaces import registry

        ws = registry.active()
        if ws is not None:
            return registry.state_dir(ws)
    except Exception:
        log.debug("_state_dir: workspace registry unavailable, using legacy STATE_DIR", exc_info=True)
        pass
    return STATE_DIR  # legacy fallback


# ---------- atomic write ----------


def _atomic_write(path: pathlib.Path, data_str: str) -> None:
    """Atomic write with fsync. Raises on failure; never leaves a partial file at `path`."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(data_str)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
    except Exception:
        with contextlib.suppress(Exception):
            tmp.unlink(missing_ok=True)
        raise


# ---------- LKG cache ----------

LKG_MAX_AGE = 300  # 5 minutes — discard stale cache

_LKG_STATE: dict[str, Any] = {"value": None, "ts": 0.0}

# Cross-process file lock — matches the bash side's `flock -x 9` on the same path.
# Threading lock is layered ON TOP to serialize within-process callers.
_thread_lock = threading.Lock()


class _StateLock:
    def __enter__(self) -> _StateLock:
        _thread_lock.acquire()
        try:
            lock_dir = _state_dir()
            lock_path = lock_dir / ".work-state.lock"
            lock_dir.mkdir(parents=True, exist_ok=True)
            self._fd: IO[str] | None = open(lock_path, "a+")
            deadline = time.monotonic() + 30
            if HAVE_FCNTL:
                # Non-blocking lock with retry loop (max 30s)
                while True:
                    try:
                        fcntl.flock(self._fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            self._fd.close()
                            self._fd = None
                            _thread_lock.release()
                            raise TimeoutError("could not acquire file lock within 30s") from None
                        time.sleep(0.1)
            elif HAVE_MSVCRT:
                while True:
                    try:
                        self._fd.seek(0)
                        msvcrt.locking(self._fd.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            self._fd.close()
                            self._fd = None
                            _thread_lock.release()
                            raise TimeoutError("could not acquire file lock within 30s") from None
                        time.sleep(0.1)
            else:
                self._fd = None
        except BaseException:
            # If thread_lock was acquired but something failed, release it.
            # Only release if we still hold it (TimeoutError case releases above).
            try:
                if self._fd is not None:
                    self._fd.close()
                    self._fd = None
            except Exception:
                log.debug("_StateLock.__enter__: failed to close fd during cleanup", exc_info=True)
                pass
            with __import__("contextlib").suppress(RuntimeError):
                _thread_lock.release()
            raise
        return self

    def __exit__(self, *exc: object) -> None:
        try:
            if self._fd is not None:
                if HAVE_FCNTL:
                    fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
                elif HAVE_MSVCRT:
                    with contextlib.suppress(OSError):
                        self._fd.seek(0)
                        msvcrt.locking(self._fd.fileno(), msvcrt.LK_UNLCK, 1)
                self._fd.close()
        finally:
            _thread_lock.release()


# Kept as an alias for existing callsites that import _state_lock.
_state_lock = _StateLock()


def _read_state() -> dict[str, Any]:
    p = _state_dir() / "work-state.json"
    if not p.exists():
        return {"items": []}
    try:
        raw = p.read_text(encoding="utf-8")
        if not raw.strip():
            # empty file — refuse to interpret as empty queue
            if _LKG_STATE["value"] is not None:
                if time.time() - _LKG_STATE["ts"] > LKG_MAX_AGE:
                    log.warning("discarding stale LKG cache (age=%.0fs)", time.time() - _LKG_STATE["ts"])
                    _LKG_STATE["value"] = None
                    _LKG_STATE["ts"] = 0.0
                    return {"items": []}
                cached: dict[str, Any] = _LKG_STATE["value"]
                return cached
            return {"items": []}
        parsed: dict[str, Any] = json.loads(raw)
        _LKG_STATE["value"] = parsed
        _LKG_STATE["ts"] = time.time()
        return parsed
    except Exception as e:
        # parse error on a non-empty file — return cache and log loudly
        log.error("work-state.json parse failed: %s — falling back to last-known-good", e)
        if _LKG_STATE["value"] is not None:
            if time.time() - _LKG_STATE["ts"] > LKG_MAX_AGE:
                log.warning("discarding stale LKG cache (age=%.0fs)", time.time() - _LKG_STATE["ts"])
                _LKG_STATE["value"] = None
                _LKG_STATE["ts"] = 0.0
                return {"items": []}
            cached_err: dict[str, Any] = _LKG_STATE["value"]
            return cached_err
        return {"items": []}


def _write_state(state: dict[str, Any]) -> None:
    state["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    payload = json.dumps(state, indent=2, ensure_ascii=False)
    # Validate before write — same paranoia as bash side.
    try:
        json.loads(payload)
    except Exception as exc:
        log.error("_write_state refused: produced invalid JSON: %s", exc)
        raise RuntimeError(f"_write_state produced invalid JSON: {exc}") from exc
    # Rotate backups before overwriting: .bak.{N} → .bak.{N+1}, .bak.1 ← current
    sd = _state_dir()
    state_path = sd / "work-state.json"
    try:
        if state_path.exists() and state_path.stat().st_size > 0:
            keep = int(os.environ.get("HEPHAESTUS_BACKUP_KEEP", "5"))
            # Delete oldest backup if it exists
            oldest = sd / f"work-state.json.bak.{keep}"
            if oldest.exists():
                oldest.unlink(missing_ok=True)
            # Shift: .bak.{N-1} → .bak.{N} for N from keep down to 2
            for i in range(keep, 1, -1):
                src = sd / f"work-state.json.bak.{i - 1}"
                dst = sd / f"work-state.json.bak.{i}"
                if src.exists():
                    src.replace(dst)
            # Create .bak.1 from current state file
            shutil.copy2(state_path, sd / "work-state.json.bak.1")
    except Exception:
        log.debug("state backup rotation failed (non-critical): %s", __import__("traceback").format_exc())
    _atomic_write(state_path, payload)
    _LKG_STATE["value"] = state
    _LKG_STATE["ts"] = time.time()


read_state = _read_state
