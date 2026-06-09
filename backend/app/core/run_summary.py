"""RunSummary, should_stop, RunSummaryStore — Epic 2 Batch C (C1).

RunSummary is persisted under <state>/run-summary.json after every iteration.
should_stop is a pure predicate — no I/O, safe to call in tests.
RunSummaryStore mirrors the MergeJobStore pattern (get/put, atomic write).
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.state import _atomic_write, _state_dir, _StateLock

_REGISTRY = "run-summary.json"
_HISTORY = "run-history.json"
# Rolling cap on archived runs — bounds the history file like the other stores.
_MAX_HISTORY = 200


class RunSummary(BaseModel):
    """Summary of the current (or last) orchestrator run."""

    model_config = ConfigDict(populate_by_name=True)

    run_mode: str = Field("queue", alias="runMode")
    started_at_ms: float = Field(0.0, alias="startedAtMs")
    # FEAT-005: set when the run is archived to history; 0.0 for the live run.
    ended_at_ms: float = Field(0.0, alias="endedAtMs")
    items_done: int = Field(0, alias="itemsDone")
    items_failed: int = Field(0, alias="itemsFailed")
    consec_fail: int = Field(0, alias="consecFail")
    cost_usd: float = Field(0.0, alias="costUsd")
    stopped_reason: str = Field("", alias="stoppedReason")


def should_stop(
    summary: RunSummary,
    *,
    cost_budget: float,
    deadline_ms: float | None,
    max_consec_fail: int,
    now_ms: float,
) -> tuple[bool, str]:
    """Pure stop-predicate.  Returns (stop, reason_string).

    Rules:
    - cost_budget <= 0 means cost check is OFF.
    - deadline_ms is None means wallclock check is OFF.
    - max_consec_fail <= 0 means consecutive-failure check is OFF.
    """
    if cost_budget > 0 and summary.cost_usd >= cost_budget:
        return True, f"cost budget exceeded ({summary.cost_usd:.4f} >= {cost_budget:.4f})"
    if max_consec_fail > 0 and summary.consec_fail >= max_consec_fail:
        return True, f"consec_fail limit reached ({summary.consec_fail} >= {max_consec_fail})"
    if deadline_ms is not None and now_ms >= deadline_ms:
        return True, f"wallclock deadline reached (now={now_ms:.0f} >= deadline={deadline_ms:.0f})"
    return False, ""


class RunSummaryStore:
    """Persist RunSummary under <state>/run-summary.json."""

    def _path(self) -> pathlib.Path:
        return _state_dir() / _REGISTRY

    def get(self) -> RunSummary | None:
        p = self._path()
        if not p.exists():
            return None
        try:
            raw: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
            return RunSummary.model_validate(raw)
        except Exception:
            return None

    def put(self, summary: RunSummary) -> None:
        with _StateLock():
            payload = json.dumps(
                summary.model_dump(by_alias=True),
                indent=2,
                ensure_ascii=False,
            )
            self._path().parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(self._path(), payload)


class RunHistoryStore:
    """FEAT-005: append finished RunSummary records to <state>/run-history.json.

    Newest-last (append order); rolling-capped at ``_MAX_HISTORY``. Mirrors the
    GoalStore/IdeaStore registry pattern.
    """

    def _path(self) -> pathlib.Path:
        return _state_dir() / _HISTORY

    def list(self) -> list[RunSummary]:
        p = self._path()
        if not p.exists():
            return []
        try:
            raw: dict[str, Any] = json.loads(p.read_text(encoding="utf-8") or '{"runs": []}')
            return [RunSummary.model_validate(r) for r in raw.get("runs", [])]
        except Exception:
            return []

    def archive(self, summary: RunSummary) -> bool:
        """Append a finished run. No-op runs (processed nothing) are skipped so the
        frequent empty driver cycles don't spam history. Returns True if recorded."""
        if not (summary.items_done or summary.items_failed):
            return False
        with _StateLock():
            runs = self.list()
            runs.append(summary)
            runs = runs[-_MAX_HISTORY:]
            payload = json.dumps(
                {"runs": [r.model_dump(by_alias=True) for r in runs]},
                indent=2,
                ensure_ascii=False,
            )
            self._path().parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(self._path(), payload)
        return True
