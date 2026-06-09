"""Cross-platform, sync PID-based process supervisor (replaces tmux/pgrep/pkill).

Key invariants:
  - SYNC only — subprocess.Popen, threading.Lock (no asyncio anywhere)
  - PID-based — stores PID, uses os.kill(pid, 0) for liveness
  - Cross-platform — Windows uses CREATE_NEW_PROCESS_GROUP + taskkill /F /T;
    POSIX uses start_new_session + os.killpg
  - Module singleton ``pm = ProcessManager()``
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time
from enum import StrEnum
from typing import IO, Any

from pydantic import BaseModel, Field

log = logging.getLogger("hephaestus.backend.process")


# ---------- constants ----------

_PROCESS_JSON = "process.json"

# Windows process creation flag: the new process does not inherit the console
# of the parent and gets its own process group (needed for CTRL_BREAK_EVENT).
_CREATE_NEW_PROCESS_GROUP = 0x00000200  # CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP equivalent

# On Windows we use taskkill /F /T to kill the entire tree.
# On POSIX we use os.killpg with SIGKILL.
_IS_WINDOWS = os.name == "nt"


# ---------- state enum ----------


class ProcState(StrEnum):
    """Observable state of a managed process."""

    IDLE = "idle"  # not started / unknown
    RUNNING = "running"  # alive according to os.kill(pid, 0)
    STOPPING = "stopping"  # graceful stop in progress
    EXITED = "exited"  # process has terminated


# ---------- handle model ----------


class ProcessHandle(BaseModel):
    """Snapshot of a managed process at a point in time."""

    name: str
    pid: int | None = None
    state: ProcState = ProcState.IDLE
    started_at_ms: int | None = None
    exit_code: int | None = None
    children: list[int] = Field(default_factory=list)


# ---------- helpers ----------


def _pid_alive(pid: int) -> bool:
    """Return True if *pid* refers to a live process.

    Uses ``os.kill(pid, 0)`` which is the standard POSIX liveness check and
    works on Windows for local processes as well.
    """
    if pid < 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we don't have permission to signal it — still alive.
        return True
    except OSError:
        return False
    except SystemError:
        # CPython on Windows can surface "<class 'OSError'> returned a result with an
        # exception set" for recycled pids — treat as not alive rather than crashing.
        return False


def _kill_tree(pid: int) -> None:
    """Force-kill the process tree rooted at *pid*.

    Windows: ``taskkill /F /T /PID <pid>``
    POSIX:   ``os.killpg`` with SIGKILL (the process must be a session leader).
    """
    if not _pid_alive(pid):
        return
    if _IS_WINDOWS:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            log.warning("taskkill failed for PID %d", pid, exc_info=True)
    else:
        try:
            # Kill the entire process group (negative PID = PGID when the
            # process was started with start_new_session=True).
            # POSIX-only attrs; unreachable on Windows where mypy runs.
            os.killpg(pid, signal.SIGKILL)  # type: ignore[attr-defined]
        except ProcessLookupError:
            pass  # already dead
        except Exception:
            log.warning("os.killpg failed for PID %d", pid, exc_info=True)


def _now_ms() -> int:
    return int(time.monotonic_ns() // 1_000_000)


# ---------- ProcessManager ----------

# Module-level alias because ProcessManager.list() shadows builtin list.
_StrList = list[str]


class ProcessManager:
    """Synchronous, PID-based process supervisor.

    Usage::

        from app.core.process import pm

        handle = pm.start("my-scan", ["python", "scan.py"], cwd="/tmp", env={})
        print(pm.status("my-scan"))
        pm.cancel("my-scan")
    """

    def __init__(self, state_dir: str | os.PathLike[str] | None = None) -> None:
        # Reentrant: status()/cancel() hold the lock and call _finalize(), which
        # re-acquires it. A plain Lock self-deadlocks once a process actually exits.
        self._lock = threading.RLock()
        # name -> subprocess.Popen
        self._procs: dict[str, subprocess.Popen[bytes]] = {}
        # name -> ProcessHandle
        self._handles: dict[str, ProcessHandle] = {}
        self._state_dir: pathlib.Path | None = pathlib.Path(state_dir) if state_dir is not None else None

    # ---- internal helpers ----

    def _process_json(self) -> pathlib.Path:
        """Resolve the path to the process.json file for this manager."""
        if self._state_dir is not None:
            return self._state_dir / _PROCESS_JSON
        # Fall back to the global state dir from app.core.state.
        from app.core.state import STATE_DIR  # type: ignore[attr-defined]

        return STATE_DIR / _PROCESS_JSON

    def _persist(self, name: str, pid: int | None, children: list[int]) -> None:
        """Write process state to process.json."""
        p = self._process_json()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            existing: dict[str, Any] = {}
            if p.exists():
                try:
                    existing = json.loads(p.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    log.debug("_persist: failed to parse existing process.json", exc_info=True)
                    existing = {}
            if pid is None:
                existing.pop(name, None)
            else:
                existing[name] = {"pid": pid, "children": children}
            p.write_text(json.dumps(existing, indent=2))
        except Exception:
            log.warning("failed to persist process state for %s", name, exc_info=True)

    def _recover(self, name: str) -> ProcessHandle | None:
        """Try to recover a previously persisted process by reading process.json.

        Returns a ``ProcessHandle`` if the PID is still alive, else ``None``.
        """
        p = self._process_json()
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.debug("_recover: failed to parse process.json", exc_info=True)
            return None
        entry = data.get(name)
        if entry is None:
            return None
        pid = entry.get("pid")
        if pid is None or not _pid_alive(pid):
            return None
        return ProcessHandle(
            name=name,
            pid=pid,
            state=ProcState.RUNNING,
            children=entry.get("children", []),
        )

    def _finalize(self, name: str, proc: subprocess.Popen[bytes] | None = None) -> ProcessHandle:
        """Clean up after a process has exited and return the final handle."""
        with self._lock:
            self._procs.pop(name, None)
            h = self._handles.pop(name, ProcessHandle(name=name))
            if proc is not None:
                h.exit_code = proc.poll()
            h.state = ProcState.EXITED
            self._persist(name, None, [])
        return h

    # ---- public API ----

    def start(
        self,
        name: str,
        cmd: list[str],
        *,
        cwd: str | os.PathLike[str],
        env: dict[str, str],
        output_path: str | os.PathLike[str] | None = None,
        timeout_sec: float | None = None,
    ) -> ProcessHandle:
        """Start a new managed process.

        Raises ``ValueError`` if a process with the same *name* is already
        running (either in-memory or recovered from process.json).
        """
        with self._lock:
            # Check in-memory first.
            existing = self._procs.get(name)
            if existing is not None and existing.poll() is None:
                raise ValueError(f"'{name}' is already running (PID {existing.pid})")

            # Check recovered from process.json.
            recovered = self._recover(name)
            if recovered is not None and recovered.state is ProcState.RUNNING:
                raise ValueError(f"'{name}' is already running (PID {recovered.pid})")

            # Prepare stdout/stderr.
            stdout: int | IO[bytes] = subprocess.DEVNULL
            if output_path is not None:
                stdout = open(output_path, "ab")  # noqa: SIM115 — binary append

            startupinfo: Any = None
            creationflags = 0
            if _IS_WINDOWS:
                creationflags = _CREATE_NEW_PROCESS_GROUP
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            else:
                # POSIX: start a new session so we can kill the process group.
                pass

            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(cwd),
                    env={**os.environ, **env} if env else None,
                    stdout=stdout,
                    stderr=subprocess.STDOUT if output_path is not None else subprocess.DEVNULL,
                    startupinfo=startupinfo,
                    creationflags=creationflags,
                    start_new_session=not _IS_WINDOWS,
                )
            except Exception:
                # subprocess.PIPE is an int sentinel, not a class; the isinstance call
                # is preserved verbatim for runtime parity (type-only suppression).
                if output_path is not None and isinstance(stdout, subprocess.PIPE):  # type: ignore[arg-type]
                    stdout.close()
                raise

            pid = proc.pid
            if pid is None:
                raise RuntimeError(f"subprocess started but PID is None for '{name}'")

            handle = ProcessHandle(
                name=name,
                pid=pid,
                state=ProcState.RUNNING,
                started_at_ms=_now_ms(),
            )
            self._procs[name] = proc
            self._handles[name] = handle
            self._persist(name, pid, [])

        return handle

    def stop(self, name: str, *, grace_sec: float = 10.0) -> ProcessHandle:
        """Gracefully stop a managed process.

        Sends SIGTERM (POSIX) or CTRL_BREAK_EVENT (Windows), waits up to
        *grace_sec* seconds, then force-kills via ``cancel()``.
        """
        with self._lock:
            proc = self._procs.get(name)
            handle = self._handles.get(name)

            if proc is None or proc.poll() is not None:
                # Not in memory — try recovery.
                recovered = self._recover(name)
                if recovered is not None:
                    return self.cancel(name)
                return self._finalize(name)

            pid = proc.pid
            if pid is None:
                return self._finalize(name)

            handle.state = ProcState.STOPPING  # type: ignore[union-attr]
            self._handles[name] = handle  # type: ignore[assignment]

        # Send graceful signal outside the lock.
        try:
            if _IS_WINDOWS:
                # CTRL_BREAK_EVENT is the only reliable console signal on Windows.
                os.kill(pid, signal.CTRL_BREAK_EVENT)
            else:
                os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass  # already dead
        except Exception:
            log.warning("stop signal failed for %s (PID %d)", name, pid, exc_info=True)

        # Wait for graceful exit.
        deadline = time.monotonic() + grace_sec
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return self._finalize(name, proc)
            time.sleep(0.05)

        # Grace period expired — force kill.
        return self.cancel(name)

    def cancel(self, name: str) -> ProcessHandle:
        """Force-kill a managed process and its entire process tree."""
        with self._lock:
            proc = self._procs.get(name)
            handle = self._handles.get(name)

            pid: int | None = None
            if proc is not None:
                pid = proc.pid
            elif handle is not None:
                pid = handle.pid
            else:
                # Try recovery from process.json.
                recovered = self._recover(name)
                if recovered is not None:
                    pid = recovered.pid
                    handle = recovered

            if pid is None or not _pid_alive(pid):
                return self._finalize(name, proc)

        # Kill outside the lock.
        _kill_tree(pid)

        # Wait for the process to actually die.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not _pid_alive(pid):
                break
            time.sleep(0.05)

        return self._finalize(name, proc)

    def status(self, name: str) -> ProcessHandle:
        """Return the current status of a managed process.

        Performs a live liveness check via ``os.kill(pid, 0)``.
        """
        with self._lock:
            proc = self._procs.get(name)
            handle = self._handles.get(name)

            if proc is not None:
                # We hold the Popen handle, so poll() is the authoritative liveness check —
                # os.kill(pid, 0) is unreliable on Windows (a dead/recycled pid can read as
                # alive, leaving a finished scan stuck "running").
                if proc.poll() is None:
                    return ProcessHandle(
                        name=name,
                        pid=proc.pid,
                        state=ProcState.RUNNING,
                        started_at_ms=handle.started_at_ms if handle else None,
                    )
                # Process has exited — finalize.
                return self._finalize(name, proc)

            if handle is not None:
                if handle.pid is not None and _pid_alive(handle.pid):
                    return handle
                # Stale handle — return as IDLE.
                return ProcessHandle(name=name)

            # Not in memory — try recovery.
            recovered = self._recover(name)
            if recovered is not None:
                return recovered

            return ProcessHandle(name=name)

    def list(self) -> list[ProcessHandle]:
        """Return a list of all known process handles (in-memory + recovered)."""
        with self._lock:
            result: list[ProcessHandle] = []
            seen: set[str] = set()

            for name, proc in self._procs.items():
                seen.add(name)
                if proc.poll() is None:  # authoritative for our own child (see status())
                    handle = self._handles.get(name)
                    result.append(
                        ProcessHandle(
                            name=name,
                            pid=proc.pid,
                            state=ProcState.RUNNING,
                            started_at_ms=handle.started_at_ms if handle else None,
                        )
                    )
                else:
                    result.append(ProcessHandle(name=name))

            # Also check process.json for recovered processes not in memory.
            p = self._process_json()
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    for name, entry in data.items():
                        if name in seen:
                            continue
                        pid = entry.get("pid")
                        if pid is not None and _pid_alive(pid):
                            result.append(
                                ProcessHandle(
                                    name=name,
                                    pid=pid,
                                    state=ProcState.RUNNING,
                                    children=entry.get("children", []),
                                )
                            )
                except (json.JSONDecodeError, OSError):
                    log.debug("list: failed to parse process.json for recovered procs", exc_info=True)
                    pass

            return result

    def reap_orphans(self) -> _StrList:
        """Kill orphaned child processes whose root PID is dead.

        Scans ``process.json`` for entries where the root PID is no longer alive
        but child PIDs may still be running.  Kills surviving children and cleans
        up tracking.  Returns the list of entry names that were cleaned up.

        Safety: **no-op** when running under pytest (``"pytest" in sys.modules``).
        """
        if "pytest" in sys.modules:
            return []

        reaped: list[str] = []
        with self._lock:
            p = self._process_json()
            if not p.exists():
                return []
            try:
                data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                log.debug("reap_orphans: failed to parse process.json", exc_info=True)
                return []

            for name, entry in list(data.items()):
                pid = entry.get("pid")
                children: list[int] = entry.get("children", [])
                if pid is None:
                    continue
                # If root is alive this is NOT an orphan — skip.
                if _pid_alive(pid):
                    continue
                # Root is dead — kill any surviving children.
                for child_pid in children:
                    if _pid_alive(child_pid):
                        log.warning(
                            "reap_orphans: killing orphan child PID %d of dead root %d (name=%s)",
                            child_pid,
                            pid,
                            name,
                        )
                        _kill_tree(child_pid)
                # Clean up tracking.
                self._persist(name, None, [])
                reaped.append(name)
                log.info("reap_orphans: cleaned up dead entry '%s' (PID %d)", name, pid)

        return reaped

    def cancel_all(self) -> None:
        """Force-kill all managed processes."""
        names = list(self._procs.keys())
        for name in names:
            try:
                self.cancel(name)
            except Exception:
                log.warning("cancel_all: failed to cancel '%s'", name, exc_info=True)


# Module singleton — importers use ``from app.core.process import pm``.
pm = ProcessManager()
