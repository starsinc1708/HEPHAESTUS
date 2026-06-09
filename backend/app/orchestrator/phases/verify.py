"""VERIFY phase — run configured verify commands + diff-test safety net.

Body extracted from ``OrchestratorFSM._verify`` (ARCH-001). Returns a
``VerifyOutcome`` so the caller can distinguish passed-with-checks, failed, and
*nothing ran* (unverified). Behavior is identical; the FSM method is now a thin
delegate.
"""

from __future__ import annotations

import logging
import pathlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.core.verify import VerifyOutcome
    from app.orchestrator.fsm import OrchestratorFSM

log = logging.getLogger("hephaestus.orchestrator")


async def verify_phase(fsm: OrchestratorFSM, item: dict[str, Any]) -> VerifyOutcome:
    """Run configured verify commands AND the diff-test safety net.

    Returns a VerifyOutcome so the caller can tell apart three states the old
    bool conflated: passed-with-checks, failed, and *nothing ran* (unverified).
    The diff-test pass (app.core.diff_tests) actually RUNS the test files this
    iteration touched — so a broken test (e.g. a committed test that asserts a
    different API than the code) flips the gate to fail instead of sailing
    through on an empty verify config.
    """
    from app.core.diff_tests import run_diff_tests
    from app.core.verify import VerifyOutcome, VerifyRunner

    if fsm._ws is None:
        return VerifyOutcome(passed=True, checks_ran=0, unverified=True, detail="no workspace")
    repo = fsm._get_repo()
    log_path = (fsm.iter_dir / "verify.log") if fsm.iter_dir else pathlib.Path("verify.log")
    vres = await VerifyRunner(fsm._ws).run(
        cwd=repo, log_path=log_path, timeout_sec=fsm._ws.verify_timeout_sec
    )
    if not vres.ok:
        log.warning("verify failed: %s", vres.failed_command)
        return VerifyOutcome(
            passed=False, checks_ran=len(vres.ran), unverified=False,
            detail=f"verify command failed: {vres.failed_command}",
        )
    # Deterministic safety net: run the test files the agent touched.
    base_ref = f"{fsm._ws.remote}/{fsm._ws.base_branch}"
    dt_log = (fsm.iter_dir / "diff-tests.log") if fsm.iter_dir else pathlib.Path("diff-tests.log")
    dres = await run_diff_tests(
        repo, base_ref, log_path=dt_log, timeout_sec=fsm._ws.verify_timeout_sec
    )
    if not dres.ok:
        log.warning("diff-tests failed: %s", dres.failed)
        return VerifyOutcome(
            passed=False, checks_ran=len(vres.ran) + len(dres.ran), unverified=False,
            detail=f"test files failed: {', '.join(dres.failed)}",
        )
    checks_ran = len(vres.ran) + len(dres.ran)
    detail = f"{len(vres.ran)} verify cmd(s), {len(dres.ran)} test file(s)"
    if dres.unrun:
        detail += f", {len(dres.unrun)} test file(s) had no runner"
    return VerifyOutcome(
        passed=True, checks_ran=checks_ran, unverified=checks_ran == 0, detail=detail
    )
