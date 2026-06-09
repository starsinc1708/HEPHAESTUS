"""Goal model + GoalStore — Epic 2 (B2).

Persists goals under <state>/goals.json analogous to MergeJobStore.
"""

from __future__ import annotations

import builtins
import json
import pathlib
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.events import extract_assistant_text
from app.core.state import _atomic_write, _state_dir, _StateLock

_REGISTRY = "goals.json"
_MAX_KEEP = 200

_PLAN_RE = re.compile(r"PLAN_BEGIN\s*(\{.*?\})\s*PLAN_END", re.DOTALL)


def _parse_plan_block(text: str) -> dict[str, Any] | None:
    """Find the LAST PLAN_BEGIN..END block, parse JSON, require 'tasks' key."""
    matches = list(_PLAN_RE.finditer(text))
    if not matches:
        return None
    raw = matches[-1].group(1)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "tasks" not in data:
        return None
    return data


class Goal(BaseModel):
    """A high-level natural-language goal that will be decomposed into queue tasks."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    description: str = ""
    status: str = "active"
    task_ids: list[str] = Field(default_factory=list, alias="taskIds")
    created_at: str | None = Field(None, alias="createdAt")
    dry_rounds: int = Field(0, alias="dryRounds")


class GoalStore:
    """Persist Goal records as a rolling JSON registry in the state dir."""

    def _path(self) -> pathlib.Path:
        return _state_dir() / _REGISTRY

    def list(self) -> list[Goal]:
        p = self._path()
        if not p.exists():
            return []
        raw = json.loads(p.read_text(encoding="utf-8") or '{"goals": []}')
        return [Goal.model_validate(g) for g in raw.get("goals", [])]

    def get(self, goal_id: str) -> Goal | None:
        return next((g for g in self.list() if g.id == goal_id), None)

    def put(self, goal: Goal) -> None:
        with _StateLock():
            goals = [g for g in self.list() if g.id != goal.id]
            goals.append(goal)
            goals = goals[-_MAX_KEEP:]
            payload = json.dumps(
                {"goals": [g.model_dump(by_alias=True) for g in goals]},
                indent=2,
                ensure_ascii=False,
            )
            self._path().parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(self._path(), payload)

    def active(self) -> builtins.list[Goal]:
        """Return all goals with status == 'active'."""
        return [g for g in self.list() if g.status == "active"]


# ---------------------------------------------------------------------------
# plan_goal (B3) — imported here lazily to avoid circular imports at module load.
# ---------------------------------------------------------------------------


async def plan_goal(
    ws: Any,
    goal: Goal,
    *,
    runner: Any,
    max_tasks: int | None = None,
) -> list[str]:
    """Decompose a Goal into queue tasks via the goal-planner agent.

    Steps:
    1. Render goal-planner prompt → run agent → parse PLAN block.
    1b. Optionally cap the parsed proposals to ``max_tasks`` (wrapper-level cap;
        does not alter the decompose agent's prompt/logic).
    2. add_proposals_to_queue → enqueue items.
    3. decompose_proposals → merge graph fields into items.
    4. Update goal.task_ids; return ids.
    """
    import logging

    from app.core.decompose import decompose_proposals
    from app.core.queue import add_proposals_to_queue
    from app.core.state import _read_state, _state_dir, _write_state
    from app.services import project_memory
    from app.services.prompt_manager import PromptManager

    log = logging.getLogger("hephaestus.backend.goals")

    # 1. Render prompt and run the planner agent
    pm = PromptManager()
    memory_excerpt = (project_memory.read_doc(ws, "architecture") or "")[:2000]
    prompt = pm.render_prompt(
        "goal-planner",
        {
            "goal_title": goal.title,
            "goal_description": goal.description,
            "repo_path": ws.repo_path,
            "memory_excerpt": memory_excerpt,
        },
    ) or ""

    sd = _state_dir()
    goal_dir = sd / f"goal-{goal.id}"
    goal_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = goal_dir / "plan.prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    output_path = goal_dir / "plan.output.md"

    ref = getattr(ws.agents, "planner", None) or ws.agents.primary
    try:
        await runner.run(
            ref,
            prompt_file=prompt_file,
            cwd=ws.repo_path,
            output_path=output_path,
            timeout_sec=600,
        )
        final_text = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    except Exception as exc:
        log.warning("plan_goal: runner failed (%s) — returning empty", exc)
        return []

    parsed = _parse_plan_block(extract_assistant_text(final_text))
    if parsed is None:
        log.warning("plan_goal: no/invalid PLAN block — returning empty")
        return []

    props: list[dict[str, Any]] = parsed.get("tasks", [])
    if not props:
        return []

    if max_tasks is not None and max_tasks > 0:
        props = props[:max_tasks]

    # 2. Enqueue proposals
    add_proposals_to_queue(props, epic_id=goal.id, source=f"goal:{goal.id}")

    # 3. Decompose proposals into task graph
    scan_dir_name = f"goal-{goal.id}"
    try:
        tasks = await decompose_proposals(
            ws, props, scan_dir=scan_dir_name, runner=runner
        )
    except Exception as exc:
        log.warning("plan_goal: decompose failed (%s) — 1:1 fallback", exc)
        tasks = [
            {"id": p["id"], "dependsOn": [], "epicId": goal.id, "parent": None,
             "orderIndex": i, "conflictGroup": None}
            for i, p in enumerate(props)
        ]

    # Merge graph fields into enqueued items (same pattern as _scan_import)
    graph_by_id = {t["id"]: t for t in tasks}
    with _StateLock():
        s = _read_state()
        for it in s.get("items", []):
            g = graph_by_id.get(it.get("id"))
            if g:
                it["dependsOn"] = g.get("dependsOn", [])
                it["orderIndex"] = g.get("orderIndex", 0)
                it["conflictGroup"] = g.get("conflictGroup")
                it["epicId"] = g.get("epicId") or goal.id
                it["parent"] = g.get("parent")
                if g.get("complexity"):
                    it["complexity"] = g["complexity"]
        _write_state(s)

    # 4. Update goal.task_ids
    goal.task_ids = [p["id"] for p in props if p.get("id")]
    return goal.task_ids


# ---------------------------------------------------------------------------
# replenish_goal (C2) — goal-directed queue replenishment in Ralph mode.
# ---------------------------------------------------------------------------


async def replenish_goal(
    ws: Any,
    goal: Goal,
    *,
    runner: Any,
) -> int:
    """Fill the queue with tasks still needed to finish *goal*.

    Steps:
    1. Gather items for this goal that are already done/merged/in_review.
    2. Render goal-replenish prompt → run agent → parse PLAN block.
    3. Empty/bad block → bump goal.dry_rounds, persist, return 0.
    4. Non-empty → cap to HEPHAESTUS_REPLENISH_MAX, add_proposals_to_queue,
       decompose_proposals, reset goal.dry_rounds=0, persist, return count.

    NEVER raises — all agent errors are logged and treated as "dry".
    """
    import logging
    import os

    from app.core.decompose import decompose_proposals
    from app.core.queue import add_proposals_to_queue
    from app.core.state import _read_state, _state_dir
    from app.services.prompt_manager import PromptManager

    log = logging.getLogger("hephaestus.backend.goals")

    _SUCCESS_STATUSES = {"done", "merged", "in_review"}

    try:
        max_replenish = int(os.environ.get("HEPHAESTUS_REPLENISH_MAX", "10") or "10")
    except ValueError:
        max_replenish = 10

    # 1. Gather done tasks for this goal
    state = _read_state()
    done_items = [
        it
        for it in state.get("items", [])
        if it.get("epicId") == goal.id and it.get("status") in _SUCCESS_STATUSES
    ]
    if done_items:
        lines = []
        for it in done_items:
            summary = it.get("result_summary") or ""
            lines.append(f"- [{it.get('status')}] {it.get('title', '?')}: {summary[:200]}")
        done_summary = "\n".join(lines)
    else:
        done_summary = "(none yet)"

    # 2. Render prompt and run agent
    pm = PromptManager()
    prompt = pm.render_prompt(
        "goal-replenish",
        {
            "goal_title": goal.title,
            "goal_description": goal.description,
            "done_summary": done_summary,
            "repo_path": ws.repo_path,
        },
    ) or ""

    sd = _state_dir()
    replenish_dir = sd / f"goal-{goal.id}-replenish"
    replenish_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = replenish_dir / "replenish.prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    output_path = replenish_dir / "replenish.output.md"

    ref = getattr(ws.agents, "planner", None) or ws.agents.primary
    try:
        await runner.run(
            ref,
            prompt_file=prompt_file,
            cwd=ws.repo_path,
            output_path=output_path,
            timeout_sec=600,
        )
        final_text = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    except Exception as exc:
        log.warning("replenish_goal: runner failed (%s) — treating as dry", exc)
        final_text = ""

    parsed = _parse_plan_block(extract_assistant_text(final_text))

    # 3. Empty / bad → dry round
    if parsed is None or not parsed.get("tasks"):
        goal.dry_rounds += 1
        GoalStore().put(goal)
        log.info(
            "replenish_goal: goal=%s dry_rounds=%d (empty/bad PLAN block)",
            goal.id,
            goal.dry_rounds,
        )
        return 0

    # 4. Cap, enqueue, decompose
    props: list[dict[str, Any]] = parsed["tasks"][:max_replenish]

    add_proposals_to_queue(props, epic_id=goal.id, source=f"replenish:{goal.id}")

    scan_dir_name = f"goal-{goal.id}-replenish"
    try:
        tasks = await decompose_proposals(ws, props, scan_dir=scan_dir_name, runner=runner)
    except Exception as exc:
        log.warning("replenish_goal: decompose failed (%s) — 1:1 fallback", exc)
        tasks = [
            {
                "id": p["id"],
                "dependsOn": [],
                "epicId": goal.id,
                "parent": None,
                "orderIndex": i,
                "conflictGroup": None,
            }
            for i, p in enumerate(props)
        ]

    # Merge graph fields
    from app.core.state import _read_state as _rs2
    from app.core.state import _StateLock, _write_state

    graph_by_id = {t["id"]: t for t in tasks}
    with _StateLock():
        s = _rs2()
        for it in s.get("items", []):
            g = graph_by_id.get(it.get("id"))
            if g:
                it["dependsOn"] = g.get("dependsOn", [])
                it["orderIndex"] = g.get("orderIndex", 0)
                it["conflictGroup"] = g.get("conflictGroup")
                it["epicId"] = g.get("epicId") or goal.id
                it["parent"] = g.get("parent")
                if g.get("complexity"):
                    it["complexity"] = g["complexity"]
        _write_state(s)

    goal.dry_rounds = 0
    GoalStore().put(goal)
    log.info("replenish_goal: goal=%s enqueued %d tasks", goal.id, len(props))
    return len(props)
