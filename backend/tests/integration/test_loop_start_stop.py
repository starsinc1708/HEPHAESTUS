"""Integration: driver start/stop via SYNC ProcessManager, no tmux, no asyncio.run(pm.*)."""
from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace


def test_start_then_status_running(monkeypatch, tmp_path: pathlib.Path) -> None:
    import app.core.driver as drv
    from app.core.process import ProcState

    monkeypatch.setattr(
        drv, "_loop_cmd", lambda: [sys.executable, "-c", "import time; time.sleep(30)"], raising=False
    )
    monkeypatch.setattr(drv, "_loop_cwd", lambda: str(tmp_path), raising=False)

    res = drv._start_loop({})
    assert res["ok"] is True
    st = drv._loop_status()
    assert st["process"]["state"] == ProcState.RUNNING.value
    assert "pid" in st["process"]  # R9
    res2 = drv._kill_loop_hard()
    assert res2["ok"] is True


def test_loop_status_idle_has_process_field() -> None:
    import app.core.driver as drv

    st = drv._loop_status()
    assert "process" in st
    assert "tmux" in st  # deprecated mirror retained


def test_scan_start_uses_process_manager(tmp_git_repo: pathlib.Path, monkeypatch) -> None:
    import app.core.scan as scan_mod
    import app.core.workspaces as wsmod
    from app.core.process import pm

    # Scan now runs against the registry's active workspace and spawns the real worker.
    ws = wsmod.registry.create(str(tmp_git_repo))
    wsmod.registry.activate(ws.id)

    # Don't actually fork the worker subprocess; record the launch instead.
    monkeypatch.setattr(pm, "status",
                        lambda name: SimpleNamespace(state=SimpleNamespace(value="stopped")))
    launched: dict[str, object] = {}

    def _fake_start(name, cmd, *, cwd, env, output_path=None, timeout_sec=None):  # noqa: ANN001
        launched.update(name=name, cmd=cmd, cwd=cwd, output_path=output_path)
        return SimpleNamespace(pid=4321)
    monkeypatch.setattr(pm, "start", _fake_start)

    res = scan_mod._scan_start({"scanners": 2, "reviewers": 1, "scope": "src"})
    assert res["ok"] is True
    assert res["session"] == "scan"
    assert launched["name"] == "scan"
    assert "app.core.scan_run" in launched["cmd"]
    # Worker launches from the backend dir (where `app` is importable), not the repo.
    assert launched["cwd"] == str(scan_mod._BACKEND_DIR)
    # request.json + initial status.json were written under the workspace scans dir.
    sd = pathlib.Path(ws.repo_path) / ".hephaestus" / "state" / "scans" / res["dir"]
    assert (sd / "request.json").exists()
    assert (sd / "status.json").exists()


def test_start_loop_tolerates_none_maxiter(tmp_git_repo: pathlib.Path, monkeypatch) -> None:
    """The route dumps maxIter=None for a {} body; _start_loop must not 400 on int(None)."""
    import app.core.driver as drv
    import app.core.workspaces as wsmod
    from app.models.requests import DriverStartRequest

    ws = wsmod.registry.create(str(tmp_git_repo))
    wsmod.registry.activate(ws.id)
    monkeypatch.setattr(drv.pm, "status",
                        lambda name: SimpleNamespace(state=SimpleNamespace(value="stopped")))
    monkeypatch.setattr(drv.pm, "start",
                        lambda *a, **k: SimpleNamespace(pid=4321, children=[]))

    # Exactly what driver_start() passes for a no-arg "Запуск" click.
    opts = DriverStartRequest().model_dump(by_alias=True)
    assert opts["maxIter"] is None
    res = drv._start_loop(opts)
    assert res["ok"] is True, res
