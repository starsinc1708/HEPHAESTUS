"""Revision loop: needs_revision → re-run → pass; exhaustion → failed:max-revisions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.core.verify import VerifyOutcome
from app.models.validation import ValidationResult
from app.orchestrator.fsm import OrchestratorFSM


def _ws():
    return SimpleNamespace(review=SimpleNamespace(max_revisions=2),
                           repo_path="/tmp/x", base_branch="main", remote="origin",
                           branch_prefix="auto")


def setattr_status(item, status):
    item["status"] = status


async def _drive(fsm, item, ws, validate_results):
    """Patch FSM I/O boundaries; feed scripted ValidationResults."""
    seq = iter(validate_results)
    fsm._validate = AsyncMock(side_effect=lambda *a, **k: next(seq))  # type: ignore[method-assign]
    fsm._run_opencode = AsyncMock(return_value=0)  # type: ignore[method-assign]
    fsm._verify = AsyncMock(  # type: ignore[method-assign]
        return_value=VerifyOutcome(passed=True, checks_ran=1, unverified=False))
    fsm._commit = AsyncMock(return_value=True)  # type: ignore[method-assign]
    fsm._parse_result = AsyncMock(return_value=True)  # type: ignore[method-assign]
    fsm._cleanup = AsyncMock(return_value=None)  # type: ignore[method-assign]
    fsm._preflight = AsyncMock(return_value=True)  # type: ignore[method-assign]
    fsm._build_prompt = AsyncMock(return_value="prompt")  # type: ignore[method-assign]
    fsm._mark_done = lambda it: setattr_status(it, "done")  # type: ignore[method-assign]
    fsm._mark_failed = lambda it, s: setattr_status(it, s)  # type: ignore[method-assign]
    fsm._set_phase = lambda ph, iid="": None  # type: ignore[method-assign]
    fsm._set_status = lambda it, s: setattr_status(it, s)  # type: ignore[method-assign]
    await fsm._process_item(item, ws)


async def test_needs_revision_then_pass(tmp_path):
    fsm = OrchestratorFSM()
    fsm.iter_dir = tmp_path
    item = {"id": "x", "attempts": 0, "branch": "auto/x-1", "proposal": "p", "acceptance": "a"}
    results = [
        ValidationResult(gate="needs_revision", blocking=["fix it"], revision=0),
        ValidationResult(gate="pass", revision=1),
    ]
    await _drive(fsm, item, _ws(), results)
    assert item["status"] == "done"
    assert item["attempts"] == 1


async def test_max_revisions_exhausted(tmp_path):
    fsm = OrchestratorFSM()
    fsm.iter_dir = tmp_path
    item = {"id": "x", "attempts": 0, "branch": "auto/x-1", "proposal": "p", "acceptance": "a"}
    results = [ValidationResult(gate="needs_revision", blocking=["nope"], revision=i) for i in range(5)]
    await _drive(fsm, item, _ws(), results)
    assert item["status"] == "failed:max-revisions"
    assert item["attempts"] == 3
