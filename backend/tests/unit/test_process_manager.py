"""Unit: ProcessManager — sync PID-based start/status/stop/cancel (no tmux, no asyncio)."""
from __future__ import annotations

import sys

import pytest


def test_start_status_running(tmp_path) -> None:
    from app.core.process import ProcessManager, ProcState

    pm = ProcessManager(state_dir=tmp_path)
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    h = pm.start("loop", cmd, cwd=str(tmp_path), env={})
    assert h.state is ProcState.RUNNING
    assert h.pid is not None
    st = pm.status("loop")
    assert st.state is ProcState.RUNNING
    pm.cancel("loop")


def test_double_start_raises(tmp_path) -> None:
    from app.core.process import ProcessManager

    pm = ProcessManager(state_dir=tmp_path)
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    pm.start("loop", cmd, cwd=str(tmp_path), env={})
    with pytest.raises(ValueError, match="already running"):
        pm.start("loop", cmd, cwd=str(tmp_path), env={})
    pm.cancel("loop")


def test_cancel_terminates_under_10s(tmp_path) -> None:
    import time as _t

    from app.core.process import ProcessManager, ProcState

    pm = ProcessManager(state_dir=tmp_path)
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    pm.start("loop", cmd, cwd=str(tmp_path), env={})
    t0 = _t.monotonic()
    h = pm.cancel("loop")
    assert _t.monotonic() - t0 < 10.0
    assert h.state is ProcState.EXITED


def test_cancel_all_clears(tmp_path) -> None:
    from app.core.process import ProcessManager, ProcState

    pm = ProcessManager(state_dir=tmp_path)
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    pm.start("loop", cmd, cwd=str(tmp_path), env={})
    pm.start("scan", cmd, cwd=str(tmp_path), env={})
    pm.cancel_all()
    assert pm.status("loop").state in (ProcState.EXITED, ProcState.IDLE)
    assert pm.status("scan").state in (ProcState.EXITED, ProcState.IDLE)


def test_status_idle_for_unknown(tmp_path) -> None:
    from app.core.process import ProcessManager, ProcState

    pm = ProcessManager(state_dir=tmp_path)
    st = pm.status("never-started")
    assert st.state is ProcState.IDLE
    assert st.pid is None


def test_status_recovers_from_process_json(tmp_path) -> None:
    """A fresh manager reads state/process.json to detect a live PID (R1)."""
    import subprocess

    from app.core.process import ProcessManager, ProcState

    pm = ProcessManager(state_dir=tmp_path)
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )
    try:
        pm._persist("loop", proc.pid, [])  # type: ignore[attr-defined]
        pm2 = ProcessManager(state_dir=tmp_path)
        assert pm2.status("loop").state is ProcState.RUNNING
    finally:
        proc.kill()
        proc.wait(timeout=10)
