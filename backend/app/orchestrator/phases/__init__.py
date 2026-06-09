"""FSM phase handlers — bodies of the per-item pipeline phases extracted from fsm.py.

Each phase is a module-level function that takes the ``OrchestratorFSM`` instance
as its first argument. The FSM ``self`` remains the single source of state
(``_worktree``, ``iter_dir``, ``_intermediate_results``, ``current_item``,
``_ws``), so behavior is identical to having the body inline on the class. The
methods on ``OrchestratorFSM`` are kept as thin delegates so their signatures
remain stable for existing tests.

ARCH-001 (2026-06-09): begin decomposition of the 1190-line FSM monolith into
focused per-phase modules WITHOUT changing the driver / control flow.
"""

from __future__ import annotations
