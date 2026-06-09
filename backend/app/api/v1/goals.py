"""Goals API — Epic 2 (B4).

POST /api/v1/goals         — create goal + decompose into tasks
GET  /api/v1/goals         — list all goals
GET  /api/v1/goals/{id}    — fetch one goal
DELETE /api/v1/goals/{id}  — abandon a goal
"""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.agent_jobs import start_agent_job
from app.core.goals import Goal, GoalStore, plan_goal
from app.core.pagination import MAX_LIMIT, paginate
from app.core.scan import _build_runner

if TYPE_CHECKING:
    from app.models.workspace import RepoProfile

router = APIRouter()


class _GoalRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(max_length=200)
    description: str = Field("", max_length=10000)
    # 0 (or omitted) means "no cap"; a positive value caps the decomposed task count.
    max_tasks: int = Field(0, alias="maxTasks", ge=0, le=100)


class NoActiveWorkspace(RuntimeError):
    """Raised when no workspace is active or the registry is unavailable."""

    def __init__(self, message: str = "no active workspace") -> None:
        super().__init__(message)


def active_workspace() -> RepoProfile:
    """Resolve the active workspace (R4)."""
    try:
        from app.core.workspaces import active_workspace as _aw
    except ImportError as exc:
        raise NoActiveWorkspace("workspace registry unavailable") from exc
    ws = _aw()
    if ws is None:
        raise NoActiveWorkspace("no active workspace")
    return ws


def _make_goal_id(title: str) -> str:
    seed = f"{title}|{time.time()}"
    return "goal-" + hashlib.sha1(seed.encode()).hexdigest()[:8]


@router.post("/api/v1/goals", response_model=None)
async def create_goal(body: _GoalRequest) -> dict[str, Any] | JSONResponse:
    """Create a goal and decompose it into tasks ASYNCHRONOUSLY as an agent job.

    Returns ``{ok, jobId, kind}`` immediately; poll GET /api/v1/agent-jobs/{id}
    or stream GET /api/v1/agent-jobs/{id}/stream for progress.

    One-shot: the job runs the decompose agent and lands the resulting task tree
    (with ``dependsOn``) as ``pending`` backlog items via ``add_proposals_to_queue``.
    It does NOT start Ralph/continuous replenishment — it only produces the tree.
    """
    try:
        ws = active_workspace()
    except NoActiveWorkspace as exc:
        return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})

    goal_id = _make_goal_id(body.title)
    goal = Goal(
        id=goal_id,
        title=body.title,
        description=body.description,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    GoalStore().put(goal)

    runner = _build_runner(ws)
    max_tasks = body.max_tasks

    async def _work(output_path: object) -> dict[str, Any]:
        # One-shot: plan_goal enqueues the decomposed tree as `pending` (with dependsOn)
        # via add_proposals_to_queue. It does NOT start Ralph/continuous mode.
        task_ids = await plan_goal(ws, goal, runner=runner, max_tasks=max_tasks)
        goal.task_ids = task_ids
        GoalStore().put(goal)
        return {"goalId": goal.id, "taskIds": task_ids}

    job = start_agent_job("decompose", _work)
    return {"ok": True, "jobId": job.id, "kind": job.kind}


@router.get("/api/v1/goals", response_model=None)
def list_goals(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=0, ge=0, le=MAX_LIMIT),
) -> dict[str, Any]:
    """List goals. PERF-003: opt-in offset/limit window; omit both to get all
    (already capped on disk). ``total`` reports the full count for paging."""
    goals = GoalStore().list()
    window, meta = paginate(goals, offset, limit)
    return {"ok": True, "goals": [g.model_dump(by_alias=True) for g in window], **meta}


# FEAT-003: built-in goal presets to seed common tasks (title + description fill the modal).
_GOAL_TEMPLATES: list[dict[str, str]] = [
    {
        "id": "api-endpoint",
        "title": "Add a read-only API endpoint",
        "description": (
            "A new GET endpoint in backend/app/api/v1/ returning JSON; register it in "
            "backend/app/main.py next to the other v1 routers; add a contract test in "
            "backend/tests/contract/. Minimal, never-500, camelCase."
        ),
    },
    {
        "id": "frontend-util",
        "title": "Add a frontend utility + test",
        "description": (
            "A pure TS function in frontend/src/utils/ with types and a vitest test in "
            "frontend/src/utils/__tests__/. No dependencies, no changes to other files."
        ),
    },
    {
        "id": "input-validation",
        "title": "Add input validation to an endpoint",
        "description": (
            "Add pydantic Field constraints (max_length / ge / le) to the request model of "
            "the given endpoint + a contract test that rejects invalid input."
        ),
    },
    {
        "id": "task-field",
        "title": "Add a task field + PATCH endpoint",
        "description": (
            "Add a field to the work-state item (camelCase) + PATCH /api/v1/tasks/{id}/<field> "
            "with validation and never-crash + a contract test. Pattern: like PATCH /api/v1/tasks/{id}/tags."
        ),
    },
    {
        "id": "fix-tests",
        "title": "Fix failing tests",
        "description": (
            "Find and fix failing tests in the given module without weakening the checks "
            "(no deleting / .skip without reason). All gates green."
        ),
    },
]


@router.get("/api/v1/goals/templates", response_model=None)
def goal_templates() -> dict[str, Any]:
    """Built-in goal presets (FEAT-003). Registered before /goals/{goal_id} so the literal path
    isn't swallowed by the path-param route."""
    return {"ok": True, "templates": _GOAL_TEMPLATES}


@router.get("/api/v1/goals/{goal_id}", response_model=None)
def get_goal(goal_id: str) -> dict[str, Any] | JSONResponse:
    goal = GoalStore().get(goal_id)
    if goal is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "goal not found"})
    return {"ok": True, "goal": goal.model_dump(by_alias=True)}


@router.delete("/api/v1/goals/{goal_id}", response_model=None)
def delete_goal(goal_id: str) -> dict[str, Any] | JSONResponse:
    store = GoalStore()
    goal = store.get(goal_id)
    if goal is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "goal not found"})
    goal.status = "abandoned"
    store.put(goal)
    return {"ok": True}
