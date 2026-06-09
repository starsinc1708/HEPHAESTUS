"""REL-003: FSM crash recovery with intermediate result persistence.

Tests verify that intermediate_results are persisted in the checkpoint
after VERIFY and COMMIT phases, and that recovery handles them gracefully
(persisted for logging; safe clear+requeue is the current recovery action).

Happy-path FSM tests are unchanged.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

from app.orchestrator.fsm import OrchestratorFSM, Phase


def _mock_fsm() -> OrchestratorFSM:
    """Create an FSM with minimal mocks for checkpoint testing."""
    with patch("app.config.STATE_DIR", MagicMock()), \
         patch("app.core.state._atomic_write"), \
         patch("app.orchestrator.fsm.OrchestratorFSM._resolve_ws", return_value=None):
        fsm = OrchestratorFSM()
    # Ensure _intermediate_results starts empty
    assert fsm._intermediate_results == {}
    return fsm


# ---------------------------------------------------------------------------
# 1. Intermediate results start empty
# ---------------------------------------------------------------------------


def test_intermediate_results_starts_empty():
    """FSM starts with empty intermediate_results dict."""
    fsm = _mock_fsm()
    assert fsm._intermediate_results == {}


# ---------------------------------------------------------------------------
# 2. _set_phase writes checkpoint with intermediate_results
# ---------------------------------------------------------------------------


def test_set_phase_includes_intermediate_results():
    """_set_phase should include intermediate_results in checkpoint JSON."""
    written: list[str] = []
    state_dir = MagicMock()
    state_dir.__truediv__.return_value = state_dir

    def fake_atomic_write(path, data):
        written.append(data)

    with patch("app.core.state._atomic_write", side_effect=fake_atomic_write):
        fsm = _mock_fsm()
        fsm._intermediate_results["verify_green"] = True
        fsm._intermediate_results["commit"] = "abc1234"
        with patch.object(fsm, "_ws", None), \
             patch("app.config.STATE_DIR", state_dir):
            fsm._set_phase(Phase.COMMIT, "test-item")

    assert len(written) >= 1
    # Check the checkpoint (second write; first is current.json)
    cp_json = json.loads(written[1])
    assert "intermediate_results" in cp_json
    assert cp_json["intermediate_results"]["verify_green"] is True
    assert cp_json["intermediate_results"]["commit"] == "abc1234"
    assert cp_json["phase"] == "commit"
    assert cp_json["item_id"] == "test-item"


# ---------------------------------------------------------------------------
# 3. IDLE phase does NOT write checkpoint
# ---------------------------------------------------------------------------


def test_idle_phase_skips_checkpoint():
    """IDLE phase should not write the checkpoint (only current.json)."""
    written: list[str] = []
    state_dir = MagicMock()
    state_dir.__truediv__.return_value = state_dir

    def fake_atomic_write(path, data):
        written.append(data)

    with patch("app.core.state._atomic_write", side_effect=fake_atomic_write):
        fsm = _mock_fsm()
        fsm._intermediate_results["verify_green"] = True
        with patch.object(fsm, "_ws", None), \
             patch("app.config.STATE_DIR", state_dir):
            fsm._set_phase(Phase.IDLE, "test-item")

    # Only current.json should be written, NOT the checkpoint
    assert len(written) == 1  # only current.json


# ---------------------------------------------------------------------------
# 4. Recovery logs intermediate_results when present
# ---------------------------------------------------------------------------


def test_recovery_logs_intermediate_results(caplog):
    """_recover_checkpoint should log intermediate_results when present."""
    state_dir = MagicMock()
    state_dir.__truediv__.return_value = state_dir
    state_dir.exists.return_value = True

    checkpoint = json.dumps({
        "phase": "commit",
        "item_id": "task-1",
        "branch": "auto/task-1-12345",
        "iter_dir": "/tmp/iter-001",
        "timestamp": 1000.0,
        "intermediate_results": {"verify_green": True, "commit": "abc1234"},
    })
    state_dir.read_text.return_value = checkpoint

    with patch("app.config.STATE_DIR", "/fake/state"), \
         patch("app.core.state._atomic_write"), \
         patch("app.orchestrator.fsm.OrchestratorFSM._resolve_ws", return_value=None), \
         patch("app.orchestrator.fsm.OrchestratorFSM._requeue_stale_in_progress"), \
         caplog.at_level(logging.INFO):
        fsm = _mock_fsm()
        # Replace _get_state_dir to return our mocked state_dir
        with patch.object(fsm, "_ws", None), \
             patch("app.config.STATE_DIR", state_dir):
            fsm._recover_checkpoint()

    assert any("intermediate results available" in r.message for r in caplog.records)
    assert any("verify_green=True" in r.message for r in caplog.records)
    assert any("commit=abc1234" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 5. Recovery without intermediate_results doesn't log them
# ---------------------------------------------------------------------------


def test_recovery_no_intermediate(caplog):
    """_recover_checkpoint should not log intermediate_results block when absent."""
    state_dir = MagicMock()
    state_dir.__truediv__.return_value = state_dir
    state_dir.exists.return_value = True

    checkpoint = json.dumps({
        "phase": "verify",
        "item_id": "task-1",
        "branch": "auto/task-1-12345",
        "iter_dir": "/tmp/iter-001",
        "timestamp": 1000.0,
    })
    state_dir.read_text.return_value = checkpoint

    with patch("app.config.STATE_DIR", "/fake/state"), \
         patch("app.core.state._atomic_write"), \
         patch("app.orchestrator.fsm.OrchestratorFSM._resolve_ws", return_value=None), \
         patch("app.orchestrator.fsm.OrchestratorFSM._requeue_stale_in_progress"), \
         caplog.at_level(logging.INFO):
        fsm = _mock_fsm()
        with patch.object(fsm, "_ws", None), \
             patch("app.config.STATE_DIR", state_dir):
            fsm._recover_checkpoint()

    # Should NOT have "intermediate results available" message
    assert not any("intermediate results available" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 6. No checkpoint file → no-op
# ---------------------------------------------------------------------------


def test_recovery_no_checkpoint():
    """No checkpoint file should be a no-op."""
    state_dir = MagicMock()
    state_dir.__truediv__.return_value = state_dir
    state_dir.exists.return_value = False

    with patch("app.config.STATE_DIR", "/fake/state"), \
         patch("app.core.state._atomic_write"), \
         patch("app.orchestrator.fsm.OrchestratorFSM._resolve_ws", return_value=None), \
         patch("app.orchestrator.fsm.OrchestratorFSM._requeue_stale_in_progress") as requeue:
        fsm = _mock_fsm()
        with patch.object(fsm, "_ws", None), \
             patch("app.config.STATE_DIR", state_dir):
            fsm._recover_checkpoint()

    requeue.assert_not_called()


# ---------------------------------------------------------------------------
# 7. Corrupt checkpoint → renamed to .corrupt + requeue
# ---------------------------------------------------------------------------


def test_recovery_corrupt_checkpoint():
    """Corrupt checkpoint should be renamed to .json.corrupt."""
    state_dir = MagicMock()
    state_dir.__truediv__.return_value = state_dir
    state_dir.exists.return_value = True
    state_dir.read_text.side_effect = json.JSONDecodeError("corrupt", "", 0)

    with patch("app.config.STATE_DIR", "/fake/state"), \
         patch("app.core.state._atomic_write"), \
         patch("app.orchestrator.fsm.OrchestratorFSM._resolve_ws", return_value=None), \
         patch("app.orchestrator.fsm.OrchestratorFSM._requeue_stale_in_progress") as requeue:
        fsm = _mock_fsm()
        with patch.object(fsm, "_ws", None), \
             patch("app.config.STATE_DIR", state_dir):
            fsm._recover_checkpoint()

    requeue.assert_called_once()


# ---------------------------------------------------------------------------
# 8. current.json is always written (non-IDLE phases)
# ---------------------------------------------------------------------------


def test_current_json_always_written():
    """non-IDLE _set_phase always writes current.json."""
    written = []
    state_dir = MagicMock()
    state_dir.__truediv__.return_value = state_dir

    def fake_atomic_write(path, data):
        written.append(data)

    with patch("app.core.state._atomic_write", side_effect=fake_atomic_write):
        fsm = _mock_fsm()
        with patch.object(fsm, "_ws", None), \
             patch("app.config.STATE_DIR", state_dir):
            fsm._set_phase(Phase.VERIFY, "task-1")

    assert len(written) >= 1
    parsed = json.loads(written[0])
    assert parsed["phase"] == "verify"
    assert parsed["itemId"] == "task-1"


# ---------------------------------------------------------------------------
# REL-003 resume: a durably-committed item recovers straight to in_review
# ---------------------------------------------------------------------------


def test_resume_committed_item_to_in_review():
    """Crashed-after-commit item with a SHA git confirms → recovered to in_review (skip re-run),
    other in_progress items left for the normal requeue."""
    fsm = _mock_fsm()
    fsm._ws = MagicMock()
    fsm._ws.repo_path = "/repo"
    cp = {"item_id": "task-1", "intermediate_results": {
        "verify_green": True, "commit": "abc1234", "verify_outcome": {"passed": True}}}
    state = {"items": [
        {"id": "task-1", "status": "in_progress"},
        {"id": "other", "status": "in_progress"},
    ]}

    with patch("app.core.helpers._run", return_value="abc1234\n"), \
         patch("app.core.state._read_state", return_value=state), \
         patch("app.core.state._write_state"), \
         patch("app.core.state._StateLock"):
        resumed = fsm._try_resume_committed(cp)

    assert resumed == "task-1"
    t1 = next(i for i in state["items"] if i["id"] == "task-1")
    assert t1["status"] == "in_review"
    assert t1["verify_green"] is True
    assert t1["commit"] == "abc1234"
    # The unrelated in_progress item is NOT resumed (it goes through the normal requeue).
    assert next(i for i in state["items"] if i["id"] == "other")["status"] == "in_progress"


def test_no_resume_when_commit_missing_in_git():
    """If git can't confirm the commit (rev-parse empty), do NOT resume — safe requeue path."""
    fsm = _mock_fsm()
    fsm._ws = MagicMock()
    fsm._ws.repo_path = "/repo"
    cp = {"item_id": "task-1", "intermediate_results": {"verify_green": True, "commit": "deadbeef"}}
    state = {"items": [{"id": "task-1", "status": "in_progress"}]}

    with patch("app.core.helpers._run", return_value=""), \
         patch("app.core.state._read_state", return_value=state), \
         patch("app.core.state._write_state") as wr, \
         patch("app.core.state._StateLock"):
        resumed = fsm._try_resume_committed(cp)

    assert resumed is None
    assert state["items"][0]["status"] == "in_progress"  # untouched
    wr.assert_not_called()


def test_no_resume_without_verify_green():
    """A persisted commit without verify_green is not resumable (verify hadn't passed)."""
    fsm = _mock_fsm()
    fsm._ws = MagicMock()
    fsm._ws.repo_path = "/repo"
    cp = {"item_id": "task-1", "intermediate_results": {"verify_green": False, "commit": "abc1234"}}
    # No git call should be needed; resume bails before touching state.
    with patch("app.core.helpers._run") as run:
        resumed = fsm._try_resume_committed(cp)
    assert resumed is None
    run.assert_not_called()
