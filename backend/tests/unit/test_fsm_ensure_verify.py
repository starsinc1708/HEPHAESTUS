"""_ensure_verify_configured wiring (Improvement 2): the loop auto-populates verify.md
from the detector when it's empty, and never lets that crash the loop."""
from __future__ import annotations


def test_ensure_verify_calls_init_for_active_ws(monkeypatch) -> None:
    import app.core.workspaces as ws_mod
    import app.services.project_memory as pm_mod
    from app.orchestrator.fsm import OrchestratorFSM

    called: dict[str, object] = {}
    sentinel_ws = object()
    monkeypatch.setattr(ws_mod, "active_workspace", lambda: sentinel_ws)

    def _fake_init(ws: object) -> bool:
        called["ws"] = ws
        return True

    monkeypatch.setattr(pm_mod, "init_verify_if_empty", _fake_init)

    OrchestratorFSM()._ensure_verify_configured()
    assert called["ws"] is sentinel_ws


def test_ensure_verify_never_raises(monkeypatch) -> None:
    import app.core.workspaces as ws_mod
    from app.orchestrator.fsm import OrchestratorFSM

    # Construct cleanly (the ctor resolves the workspace too), THEN make the helper's
    # own active_workspace() call blow up — the helper must swallow it.
    monkeypatch.setattr(ws_mod, "active_workspace", lambda: None)
    fsm = OrchestratorFSM()

    def _boom() -> object:
        raise RuntimeError("registry down")

    monkeypatch.setattr(ws_mod, "active_workspace", _boom)
    fsm._ensure_verify_configured()  # must not raise — a memory hiccup can't take down the loop


def test_ensure_verify_noop_when_no_workspace(monkeypatch) -> None:
    import app.core.workspaces as ws_mod
    import app.services.project_memory as pm_mod
    from app.orchestrator.fsm import OrchestratorFSM

    monkeypatch.setattr(ws_mod, "active_workspace", lambda: None)

    def _must_not_run(ws: object) -> bool:
        raise AssertionError("init_verify_if_empty called with no active workspace")

    monkeypatch.setattr(pm_mod, "init_verify_if_empty", _must_not_run)
    OrchestratorFSM()._ensure_verify_configured()  # no ws → no init call, no raise
