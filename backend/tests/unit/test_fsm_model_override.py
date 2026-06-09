"""FSM per-task model override in _run_opencode (Epic 2, Batch A, Task A2)."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from app.models.workspace import AgentRef, AgentsConfig
from app.orchestrator.fsm import OrchestratorFSM


def _make_agents() -> AgentsConfig:
    return AgentsConfig(
        primary=AgentRef(provider="anthropic", model="claude-sonnet"),
        fallback=AgentRef(provider="anthropic", model="claude-haiku"),
    )


def _make_fsm_with_ws() -> OrchestratorFSM:
    fsm = OrchestratorFSM()
    mock_ws = MagicMock()
    mock_ws.agents = _make_agents()
    mock_ws.verify_timeout_sec = 30
    mock_ws.engine = "opencode"
    mock_ws.engine_env = {}
    mock_ws.engine_profiles = []
    fsm._ws = mock_ws
    fsm.iter_dir = MagicMock()
    fsm.iter_dir.__truediv__ = lambda self, other: MagicMock(
        write_text=MagicMock(), __str__=lambda s: f"iter/{other}"
    )
    return fsm


def test_run_opencode_with_model_override():
    """When item has modelOverride, run_with_fallback receives agents with that primary."""
    fsm = _make_fsm_with_ws()

    captured: list[AgentsConfig] = []

    mock_result = MagicMock()
    mock_result.refused = False
    mock_result.exit_code = 0

    async def fake_run_with_fallback(agents, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(agents)
        return mock_result

    mock_runner = MagicMock()
    mock_runner.run_with_fallback = fake_run_with_fallback

    item = {
        "id": "test-task",
        "modelOverride": {"provider": "anthropic", "model": "ovr"},
    }

    async def _run() -> int | None:
        with patch("app.services.opencode_runner.AgentRunner", return_value=mock_runner):
            return await fsm._run_opencode(item, "test prompt")

    rc = asyncio.run(_run())
    assert rc == 0
    assert len(captured) == 1
    assert captured[0].primary.model == "ovr"
    assert captured[0].primary.provider == "anthropic"


def test_run_opencode_without_override_uses_ws_agents():
    """When item has no modelOverride, run_with_fallback receives the workspace agents unchanged."""
    fsm = _make_fsm_with_ws()
    original_agents = fsm._ws.agents

    captured: list[AgentsConfig] = []

    mock_result = MagicMock()
    mock_result.refused = False
    mock_result.exit_code = 0

    async def fake_run_with_fallback(agents, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(agents)
        return mock_result

    mock_runner = MagicMock()
    mock_runner.run_with_fallback = fake_run_with_fallback

    item = {"id": "test-task-no-override"}

    async def _run() -> int | None:
        with patch("app.services.opencode_runner.AgentRunner", return_value=mock_runner):
            return await fsm._run_opencode(item, "test prompt")

    rc = asyncio.run(_run())
    assert rc == 0
    assert len(captured) == 1
    # Should be the same primary agent — no copy was made for no-override path
    assert captured[0].primary.model == original_agents.primary.model
    assert captured[0].primary.provider == original_agents.primary.provider


def test_run_opencode_override_does_not_mutate_ws_agents():
    """The override must not mutate the workspace's agents object."""
    fsm = _make_fsm_with_ws()
    original_model = fsm._ws.agents.primary.model

    mock_result = MagicMock()
    mock_result.refused = False
    mock_result.exit_code = 0

    async def fake_run_with_fallback(agents, **kwargs):  # type: ignore[no-untyped-def]
        return mock_result

    mock_runner = MagicMock()
    mock_runner.run_with_fallback = fake_run_with_fallback

    item = {
        "id": "test-immutability",
        "modelOverride": {"provider": "openai", "model": "gpt-4o"},
    }

    async def _run() -> int | None:
        with patch("app.services.opencode_runner.AgentRunner", return_value=mock_runner):
            return await fsm._run_opencode(item, "test prompt")

    asyncio.run(_run())
    # workspace agents must not be mutated
    assert fsm._ws.agents.primary.model == original_model


# ---------------------------------------------------------------------------
# FIX C1 Part 2: invalid modelOverride in FSM must NOT raise — falls back to ws default
# ---------------------------------------------------------------------------

def test_run_opencode_invalid_override_falls_back_to_ws_agents():
    """item with modelOverride='garbage' must NOT raise; agents used = workspace primary."""
    fsm = _make_fsm_with_ws()
    ws_primary_model = fsm._ws.agents.primary.model
    ws_primary_provider = fsm._ws.agents.primary.provider

    captured: list[AgentsConfig] = []

    mock_result = MagicMock()
    mock_result.refused = False
    mock_result.exit_code = 0

    async def fake_run_with_fallback(agents, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(agents)
        return mock_result

    mock_runner = MagicMock()
    mock_runner.run_with_fallback = fake_run_with_fallback

    item = {
        "id": "test-bad-override",
        "modelOverride": "garbage",
    }

    async def _run() -> int | None:
        with patch("app.services.opencode_runner.AgentRunner", return_value=mock_runner):
            return await fsm._run_opencode(item, "test prompt")

    # Must NOT raise
    rc = asyncio.run(_run())
    assert rc == 0
    assert len(captured) == 1
    # Must fall back to the workspace primary, not crash
    assert captured[0].primary.model == ws_primary_model
    assert captured[0].primary.provider == ws_primary_provider
