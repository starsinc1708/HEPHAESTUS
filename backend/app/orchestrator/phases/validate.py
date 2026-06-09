"""VALIDATE phase — map-reduce ValidationFunnel pass.

Body extracted from ``OrchestratorFSM._validate`` (ARCH-001). The runtime cast
to ``RepoProfile`` is preserved so duck-typed workspaces in tests still pass
through to ``GitService`` and ``ValidationFunnel``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from app.core.validators import _AgentRunnerProto
    from app.models.validation import ValidationResult
    from app.models.workspace import RepoProfile
    from app.orchestrator.fsm import OrchestratorFSM

log = logging.getLogger("hephaestus.orchestrator")


async def validate_phase(
    fsm: OrchestratorFSM, item: dict[str, Any], ws: object, revision: int
) -> ValidationResult:
    """Run the map-reduce validation funnel (replaces the legacy tier-review no-op).

    R15: uses the module-singleton ProcessManager via fsm._pm and AgentRunner(fsm._pm).
    """
    from app.core.validators import ValidationFunnel
    from app.models.validation import ValidationResult
    from app.services.opencode_runner import AgentRunner

    if not fsm.iter_dir:
        return ValidationResult(gate="pass", revision=revision)
    # ws is `object` for duck-typing (tests pass a SimpleNamespace); cast to the
    # concrete profile expected by GitService/ValidationFunnel — runtime no-op.
    ws_profile = cast("RepoProfile", ws)
    diff_text = ""
    try:
        from app.core.git import GitService

        branch = item.get("branch", "")
        if branch:
            diff_text = GitService(ws_profile).diff(branch)
    except Exception:
        log.warning(
            "failed to generate diff for validation funnel for %s",
            item.get("id", "?"),
            exc_info=True,
        )
    runner = AgentRunner(
        fsm._pm,
        engine=getattr(ws_profile, "engine", "opencode"),
        env=getattr(ws_profile, "engine_env", {}),
        profiles=getattr(ws_profile, "engine_profiles", []),
    )
    # AgentRunner satisfies the funnel's _AgentRunnerProto at runtime; the
    # static cast bridges AgentRunner.run's narrower `ref` param vs the Protocol.
    funnel = ValidationFunnel(ws_profile, cast("_AgentRunnerProto", runner))
    return await funnel.run_funnel(
        item, iter_dir=fsm.iter_dir, diff_text=diff_text, revision=revision
    )
