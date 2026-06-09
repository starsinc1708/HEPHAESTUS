"""PARSE_RESULT phase — read agent result, build diff.patch / summary.md.

Body extracted from ``OrchestratorFSM._parse_result`` (ARCH-001). Behavior is
identical; the FSM method is now a thin delegate.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.orchestrator.fsm import OrchestratorFSM

log = logging.getLogger("hephaestus.orchestrator")


async def parse_result_phase(fsm: OrchestratorFSM, item: dict[str, Any]) -> bool:
    """Parse opencode result and update state."""
    from app.core.state import _read_state, _StateLock, _write_state

    if not fsm.iter_dir:
        return True

    result_file = fsm.iter_dir / "result.json"
    if result_file.exists():
        try:
            result = json.loads(result_file.read_text(encoding="utf-8"))
            if result.get("verify_status") == "red":
                item["selfReportedFailure"] = True
                with _StateLock():
                    s = _read_state()
                    for it in s.get("items", []):
                        if it.get("id") == item.get("id"):
                            it["selfReportedFailure"] = True
                    _write_state(s)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning(
                "failed to read result.json for self-reported failure check in %s: %s",
                fsm.iter_dir,
                exc,
            )
        except Exception:
            log.error(
                "unexpected error reading result.json in %s",
                fsm.iter_dir,
                exc_info=True,
            )

    # diff.patch + summary.md (umbrella §4.4)
    branch = item.get("branch")
    ws = getattr(fsm, "_ws", None)
    if branch and ws is not None:
        try:
            from app.core.git import GitService

            diff_text = GitService(ws).diff(branch)
            (fsm.iter_dir / "diff.patch").write_text(diff_text, encoding="utf-8")
            item["diff_ref"] = f"{fsm.iter_dir.name}/diff.patch"
        except Exception:
            log.warning(
                "failed to generate diff.patch for %s", item.get("id", "?"), exc_info=True
            )
    primary = fsm.iter_dir / "output.primary.jsonl"
    if primary.exists():
        from app.core.validators import _last_text_event

        summary = _last_text_event(primary)[:4000]
        (fsm.iter_dir / "summary.md").write_text(summary, encoding="utf-8")
        item["result_summary"] = summary

    return True
