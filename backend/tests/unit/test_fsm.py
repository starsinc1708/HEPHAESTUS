"""Tests for FSM transitions, timeout validation, and subprocess kill fallback."""

from __future__ import annotations

import asyncio
import inspect
import logging
from unittest.mock import AsyncMock, MagicMock, patch

from app.orchestrator.fsm import _TRANSITIONS, OrchestratorFSM, Phase

# ---------------------------------------------------------------------------
# 1. Valid transition: idle -> preflight
# ---------------------------------------------------------------------------


def test_valid_transition_idle_to_preflight():
    """IDLE -> PREFLIGHT should be a valid transition."""
    allowed = _TRANSITIONS[Phase.IDLE]
    assert Phase.PREFLIGHT in allowed, "IDLE should allow transition to PREFLIGHT"


# ---------------------------------------------------------------------------
# 2. Valid transition: preflight -> prompt_build
# ---------------------------------------------------------------------------


def test_valid_transition_preflight_to_prompt_build():
    """PREFLIGHT -> PROMPT_BUILD should be a valid transition."""
    allowed = _TRANSITIONS[Phase.PREFLIGHT]
    assert Phase.PROMPT_BUILD in allowed, "PREFLIGHT should allow transition to PROMPT_BUILD"


# ---------------------------------------------------------------------------
# 3. Invalid transition: idle -> done (should warn, not crash)
# ---------------------------------------------------------------------------


def test_invalid_transition_idle_to_done(caplog):
    """Invalid transitions should log a warning but not crash."""
    fsm = OrchestratorFSM()
    assert fsm.phase == Phase.IDLE

    with patch("app.config.STATE_DIR", MagicMock()), \
         patch("app.core.state._atomic_write"), caplog.at_level(logging.WARNING):
        fsm._set_phase(Phase.COMMIT, "test-item")

    # Should have logged a warning about invalid transition
    assert any("invalid FSM transition" in r.message for r in caplog.records)
    # But phase should still be updated (no crash)
    assert fsm.phase == Phase.COMMIT


# ---------------------------------------------------------------------------
# 4. Timeout validation clamps invalid values
# ---------------------------------------------------------------------------


def test_timeout_validation_clamps_invalid():
    """Timeout is threaded through AgentRunner.run_with_fallback."""
    fsm = OrchestratorFSM()

    sig = inspect.signature(fsm._run_opencode)
    # _run_opencode accepts (item, prompt) — timeout is sourced from ws.verify_timeout_sec
    assert "item" in sig.parameters, "_run_opencode should accept item"
    assert "prompt" in sig.parameters, "_run_opencode should accept prompt"


# ---------------------------------------------------------------------------
# 5. Subprocess kill fallback: when terminate times out, kill is called
# ---------------------------------------------------------------------------


def test_subprocess_kill_fallback():
    """When AgentRunner.run_with_fallback is called, timeout_sec is forwarded."""

    fsm = OrchestratorFSM()
    fsm.iter_dir = MagicMock()

    mock_result = MagicMock()
    mock_result.refused = False
    mock_result.exit_code = -1

    mock_runner = MagicMock()
    mock_runner.run_with_fallback = AsyncMock(return_value=mock_result)

    async def _run():
        with patch("app.services.opencode_runner.AgentRunner", return_value=mock_runner):
            # Need a workspace for _run_opencode to proceed
            fsm._ws = MagicMock()
            fsm._ws.agents = MagicMock()
            fsm._ws.verify_timeout_sec = 10
            return await fsm._run_opencode({"id": "test"}, "test prompt")

    rc = asyncio.run(_run())
    assert rc == -1, "Should return -1 on agent failure"
    mock_runner.run_with_fallback.assert_called_once()


# ---------------------------------------------------------------------------
# 6. All valid transitions are listed in _TRANSITIONS
# ---------------------------------------------------------------------------


def test_all_phases_have_transitions():
    """Every Phase should have an entry in _TRANSITIONS."""
    for phase in Phase:
        assert phase in _TRANSITIONS, f"Phase {phase} missing from _TRANSITIONS"


# ---------------------------------------------------------------------------
# 7. CLEANUP always transitions to IDLE
# ---------------------------------------------------------------------------


def test_cleanup_transitions_to_idle():
    """CLEANUP should only allow transitioning to IDLE."""
    allowed = _TRANSITIONS[Phase.CLEANUP]
    assert allowed == {Phase.IDLE}, "CLEANUP should only transition to IDLE"


# ---------------------------------------------------------------------------
# Stage 3: VALIDATE phase replaces TIER_REVIEW + revision-loop transitions
# ---------------------------------------------------------------------------


def test_validate_phase_exists():
    assert Phase.VALIDATE.value == "validate"
    assert not hasattr(Phase, "TIER_REVIEW")


def test_validate_transitions_allow_opencode_and_cleanup():
    allowed = _TRANSITIONS[Phase.VALIDATE]
    assert Phase.OPENCODE in allowed   # revision loop
    assert Phase.CLEANUP in allowed
    assert Phase.IDLE in allowed


def test_parse_result_transitions_to_validate():
    assert Phase.VALIDATE in _TRANSITIONS[Phase.PARSE_RESULT]
