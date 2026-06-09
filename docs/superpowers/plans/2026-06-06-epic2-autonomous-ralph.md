# Epic 2 — Autonomous (NL-goal + Ralph + per-task model/complexity) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add a natural-language "describe a goal → planned tasks" entry, optional per-task model override + advisory complexity, and a continuous goal-directed "Ralph" run mode with budget/wall-clock/consecutive-failure stop conditions.

**Architecture:** Three parts. (A) `Item` gains `modelOverride`/`complexity`; the FSM swaps the implement agent per-task when set. (B) `goals.py` turns a goal into LLM proposals, enqueues them (shared `add_proposals_to_queue` helper), and decomposes the graph. (C) the existing continuous `fsm.run()` loop gains a RalphController: stop on cost/wall-clock/consec-fail budgets, and when the queue empties in `ralph` mode, replenish tasks toward the active goal until two consecutive empty rounds ("dry") signal completion.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 (camelCase aliases) / pytest; Vue 3 `<script setup>` / Pinia / Vitest. Agents via existing `AgentRunner`.

**Spec:** `docs/superpowers/specs/2026-06-06-epic2-autonomous-ralph-design.md` — read it first; source of truth.

**Commands (EXACT):**
- Backend tests: `cd backend && .venv/Scripts/python.exe -m pytest tests/<path> -v`
- Backend lint/types: `cd backend && .venv/Scripts/python.exe -m ruff check .` and `.venv/Scripts/python.exe -m mypy --strict app/` (keep BOTH clean; `mypy --strict tests/` has ~231 PRE-EXISTING untyped errors — ignore, match untyped test style)
- Frontend: `cd frontend && npx vitest run` and `npx vue-tsc --noEmit` and `npm run build`

**Conventions / read first:**
- `backend/app/orchestrator/fsm.py` — `run()` main loop (sequential ~line 94-176), `_run_opencode` (~479-503), `_pick_next_item`, `_process_item`. CONFIRM exact signatures before editing.
- `backend/app/core/scan.py` `_scan_import` (~253-387) — the "proposals → queue items + merge graph fields" pattern to extract into a shared helper.
- `backend/app/core/decompose.py` `decompose_proposals` — returns graph-only fields; `_parse_decompose_block` (regex block parse).
- `backend/app/core/state.py` `_state_dir`, `_StateLock`, `_atomic_write`, `_read_state`, `_write_state`.
- `backend/app/core/merge_job.py` (Epic 1) — `MergeJobStore` is the reference pattern for `GoalStore`.
- `backend/app/services/prompt_manager.py` — `render_prompt(template, vars)` + prompts-dir resolution (LOOP_HOME). Epic 1 `merge_resolver.py` shows reuse.
- `backend/app/core/events.py` `_iter_cost(iter_dir) -> {"cost_usd": float, ...}`.
- `backend/app/core/driver.py` `_start_loop(opts)` env threading; `backend/app/models/requests.py` `DriverStartRequest`.
- `backend/app/config.py` `ALLOWED_CONFIG_KEYS` + `HEPHAESTUS_*` int/str pattern.
- Test patterns: `backend/tests/unit/test_decompose.py`, `test_fsm.py`, `test_task_fields.py`, `test_merge_job_store.py`, `backend/tests/contract/`, `frontend/src/components/__tests__/`.

Work on branch `feat/epic2-autonomous-ralph`. One commit per task.

---

## File Structure

**New backend:** `backend/app/core/goals.py` (Goal, GoalStore, plan_goal, replenish_goal), `backend/app/core/run_summary.py` (RunSummary + RalphController stop predicates), `backend/app/api/v1/goals.py`, `prompts/goal-planner.md`, `prompts/goal-replenish.md`.
**Modified backend:** `domain.py` (Item fields), `fsm.py` (`_run_opencode` override + `run()` Ralph loop), `decompose.py` (pass complexity), `queue.py` (`add_proposals_to_queue` helper), `scan.py` (use helper), `api/v1/tasks.py` (allow `modelOverride` patch), `models/requests.py` (DriverStartRequest), `core/driver.py` (env threading + status runSummary), `api/v1/loop.py` (status), `config.py` (keys), `app/main.py` (register goals router).
**New/modified frontend:** `types/api.ts`, `api/client.ts`, `components/TaskCard.vue`, `components/TaskDrawer.vue`, new `components/GoalComposer.vue`, `views/BoardView.vue`, run-start UI (`RunningView.vue` or wherever driver-start lives) + tests.

---

## BATCH A — Per-task model + complexity

### Task A1: Item fields + patch allowlist
**Files:** Modify `backend/app/models/domain.py`, `backend/app/api/v1/tasks.py`; Test `backend/tests/unit/test_task_fields.py` (extend) or new `test_item_model_override.py`.

- [ ] **Step 1 — failing test** (`backend/tests/unit/test_item_model_override.py`):
```python
from app.models.domain import Item
from app.models.workspace import AgentRef


def test_item_model_override_and_complexity_aliases():
    it = Item(id="x", title="t")
    it.model_override = AgentRef(provider="anthropic", model="claude-opus-4-8")
    it.complexity = "complex"
    d = it.model_dump(by_alias=True)
    assert d["modelOverride"]["model"] == "claude-opus-4-8"
    assert d["complexity"] == "complex"
    back = Item.model_validate(d)
    assert back.model_override.provider == "anthropic"
```
- [ ] **Step 2 — run, expect FAIL.**
- [ ] **Step 3 — add to `Item` in `domain.py`** (import `AgentRef` from `app.models.workspace`; if a circular import arises, use `from __future__ import annotations` (already present) and a `TYPE_CHECKING`-safe forward ref with a runtime import, or type as `AgentRef | None` with a top import — check what domain.py already imports):
```python
    model_override: "AgentRef | None" = Field(None, alias="modelOverride")
    complexity: str | None = None
```
Confirm import doesn't cycle (`workspace.py` does not import `domain.py`). Add `from app.models.workspace import AgentRef` at top if safe.
- [ ] **Step 4 — allow `modelOverride` in the queue PATCH.** Read `tasks.py` PATCH handler; find the allowlist of patchable Item fields and add `modelOverride` (and `complexity` if user-editable). Validate `modelOverride` parses as `AgentRef` (else 422).
- [ ] **Step 5 — run test + ruff + `mypy --strict app/`.** PASS/clean.
- [ ] **Step 6 — commit:** `feat(epic2): Item.modelOverride + complexity + patch allowlist`

### Task A2: FSM per-task override in `_run_opencode`
**Files:** Modify `backend/app/orchestrator/fsm.py`; Test `backend/tests/unit/test_fsm_model_override.py`.

- [ ] **Step 1 — read** the real `_run_opencode(self, item, prompt)` and confirm it calls `runner.run_with_fallback(self._ws.agents, ...)`.
- [ ] **Step 2 — failing test** (mock the runner; assert the agents passed has primary == override when item has modelOverride, and == ws.agents.primary otherwise). Build a minimal `OrchestratorFSM` with a stub `_ws` and a captured `run_with_fallback`. Mirror `test_fsm.py` setup.
```python
# sketch — adapt to test_fsm.py's fixtures
import asyncio
from app.models.workspace import AgentRef
def test_run_opencode_uses_item_model_override(monkeypatch, fsm_with_stub_ws):
    fsm = fsm_with_stub_ws
    captured = {}
    async def fake_rwf(agents, **kw):
        captured["primary"] = agents.primary
        class R: exit_code = 0; refused = False
        return R()
    monkeypatch.setattr("app.services.opencode_runner.AgentRunner.run_with_fallback", fake_rwf)
    item = {"id": "x", "modelOverride": {"provider": "anthropic", "model": "ovr"}}
    asyncio.run(fsm._run_opencode(item, "prompt text"))
    assert captured["primary"].model == "ovr"
```
- [ ] **Step 3 — implement** in `_run_opencode`, before the `run_with_fallback` call:
```python
        agents = self._ws.agents
        mo = item.get("modelOverride") or item.get("model_override")
        if mo:
            from app.models.workspace import AgentRef
            agents = self._ws.agents.model_copy(update={"primary": AgentRef.model_validate(mo)})
        # ... pass `agents` instead of self._ws.agents to run_with_fallback
```
- [ ] **Step 4 — run test + gates.** Confirm existing `test_fsm.py` still passes (no override → unchanged).
- [ ] **Step 5 — commit:** `feat(epic2): per-task model override in FSM _run_opencode`

### Task A3: decompose passes `complexity`
**Files:** Modify `backend/app/core/decompose.py`; Test `backend/tests/unit/test_decompose.py` (extend).
- [ ] **Step 1 — failing test:** feed a stub decompose runner whose DECOMPOSE block includes `"complexity":"complex"` for a task; assert the returned task-dict carries `complexity == "complex"`. Follow the existing `test_decompose.py` stub-runner pattern.
- [ ] **Step 2 — run, FAIL.**
- [ ] **Step 3 — implement:** in `decompose_proposals`, where `t["conflictGroup"]`/`t["orderIndex"]` are set (the graph-merge loop), also carry complexity from the matching LLM task: keep a `complexity_by_id` map from `parsed["tasks"]` and set `t["complexity"] = complexity_by_id.get(t["id"])`. `_expand_tasks` should also propagate `complexity` for subtasks from `sub.get("complexity")`. Default `None`.
- [ ] **Step 4 — gates.** Existing decompose tests pass.
- [ ] **Step 5 — commit:** `feat(epic2): decomposer carries advisory complexity`

---

## BATCH B — NL-goal entry (backend)

### Task B1: shared `add_proposals_to_queue` helper (DRY from scan_import)
**Files:** Modify `backend/app/core/queue.py` (add helper), `backend/app/core/scan.py` (use it); Test `backend/tests/unit/test_add_proposals.py`.
- [ ] **Step 1 — read** `scan.py::_scan_import` to extract the exact "append proposal dict as a pending item" shape (id/title/proposal/why/acceptance/touches/status/source...).
- [ ] **Step 2 — failing test:**
```python
import app.core.state as state
from app.core.queue import add_proposals_to_queue
def test_add_proposals_to_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    from app.core.state import _read_state
    props = [{"id": "g1-a", "title": "A", "proposal": "do A", "rationale": "why",
              "acceptance": "tests", "touches": ["x.py"]}]
    add_proposals_to_queue(props, epic_id="goal-1", source="goal:goal-1")
    items = _read_state()["items"]
    it = next(i for i in items if i["id"] == "g1-a")
    assert it["status"] == "pending" and it["epicId"] == "goal-1" and it["proposal"] == "do A"
```
- [ ] **Step 3 — implement** `add_proposals_to_queue(proposals, *, epic_id=None, source="")` in `queue.py` under `_StateLock`: for each proposal append an item with the same field mapping `_scan_import` uses (`why` from `rationale`, etc.), `status="pending"`, `epicId=epic_id`, `source=source`, `dependsOn=[]`. Skip ids already present. Then refactor `_scan_import` to call this helper (keep its behavior identical — verify scan tests still pass).
- [ ] **Step 4 — gates** (run `test_scan*`/`test_api_*` to ensure no regression).
- [ ] **Step 5 — commit:** `refactor(epic2): shared add_proposals_to_queue helper`

### Task B2: Goal model + GoalStore
**Files:** Create `backend/app/core/goals.py` (model + store only this task); Test `backend/tests/unit/test_goal_store.py`.
- [ ] **Step 1 — failing test** (mirror `test_merge_job_store.py`): put/get/list/active round-trip under `_STATE_DIR_OVERRIDE`; `active()` returns status=="active" goals.
- [ ] **Step 2 — run, FAIL.**
- [ ] **Step 3 — implement** `Goal` (per spec §3.1) + `GoalStore` (persist `<state>/goals.json`, `_StateLock` + `_atomic_write`, methods `list/get/put/active`). Copy the structure of `MergeJobStore`.
- [ ] **Step 4 — gates.**
- [ ] **Step 5 — commit:** `feat(epic2): Goal model + GoalStore`

### Task B3: `plan_goal` + goal-planner prompt
**Files:** Modify `backend/app/core/goals.py` (add `plan_goal`, `_parse_plan_block`), create `prompts/goal-planner.md`; Test `backend/tests/integration/test_plan_goal.py`.
- [ ] **Step 1 — failing test:** stub runner writes a `PLAN_BEGIN{...}PLAN_END` block with 2 proposals (incl. `complexity`); `plan_goal(ws, goal, runner=stub)` → returns task ids; queue has those items with `epicId=goal.id` and complexity merged.
```python
async def _stub_runner_run(ref, *, prompt_file, cwd, output_path, timeout_sec):
    import pathlib
    pathlib.Path(output_path).write_text(
        'PLAN_BEGIN{"tasks":[{"id":"a","title":"A","proposal":"do A","rationale":"r",'
        '"acceptance":"t","touches":["x.py"],"complexity":"simple"}]}PLAN_END')
    class R: exit_code = 0; refused = False
    return R()
```
(Inject the runner; do not call a real CLI. Reuse the `_make_ws` pattern from Epic 1 tests + `_STATE_DIR_OVERRIDE`.)
- [ ] **Step 2 — run, FAIL.**
- [ ] **Step 3 — implement** `prompts/goal-planner.md` (instructs: break the GOAL into a flat list of concrete proposals, output `PLAN_BEGIN{"tasks":[{id,title,proposal,rationale,acceptance,touches,severity,category,complexity}]}PLAN_END`). Implement `_parse_plan_block` (regex `PLAN_BEGIN\s*(\{.*?\})\s*PLAN_END`, last match, json.loads, require "tasks"). Implement `plan_goal(ws, goal, *, runner)`: render prompt via `PromptManager`, run agent (`ws.agents.planner or ws.agents.primary`) to an output file, parse, `add_proposals_to_queue(props, epic_id=goal.id, source="goal:"+goal.id)`, then `decompose_proposals(ws, props, scan_dir="goal-"+goal.id, runner=runner)` and merge graph fields + complexity into the items (reuse the scan_import merge code path / helper). Set `goal.task_ids`. Empty/bad LLM → return `[]`.
- [ ] **Step 4 — gates.**
- [ ] **Step 5 — commit:** `feat(epic2): plan_goal (goal -> proposals -> queue -> decompose)`

### Task B4: goals API
**Files:** Create `backend/app/api/v1/goals.py`; Modify `backend/app/main.py` (register router); Test `backend/tests/contract/test_goals_api.py`.
- [ ] **Step 1 — failing test:** `POST /api/v1/goals {title,description}` with `plan_goal` patched → 200, returns `goal` + `taskIds`; `GET /api/v1/goals` lists it; `DELETE` marks abandoned. Patch `active_workspace` + `plan_goal` (mirror Epic 1 `test_merge_api.py` patching).
- [ ] **Step 2 — run, FAIL.**
- [ ] **Step 3 — implement** routes per spec §3.3 (build a `Goal` with a deterministic id from title — pass any timestamp via `time.strftime`; persist via `GoalStore`; call `plan_goal` synchronously with a real `AgentRunner` built like scan does — see `scan.py::_build_runner`). Register the router in `main.py` next to other v1 routers.
- [ ] **Step 4 — gates** (full suite).
- [ ] **Step 5 — commit:** `feat(epic2): goals API (create/list/get/delete)`

---

## BATCH C — Ralph continuous mode (backend)

### Task C1: RunSummary + stop predicates (pure)
**Files:** Create `backend/app/core/run_summary.py`; Test `backend/tests/unit/test_ralph_stop.py`.
- [ ] **Step 1 — failing test** (pure predicates, no FSM):
```python
from app.core.run_summary import RunSummary, should_stop
def test_stop_on_cost_budget():
    s = RunSummary(cost_usd=5.0)
    stop, reason = should_stop(s, cost_budget=4.0, deadline_ms=None, max_consec_fail=4, now_ms=0)
    assert stop and "cost" in reason
def test_stop_on_consec_fail():
    s = RunSummary(consec_fail=4)
    stop, reason = should_stop(s, cost_budget=0, deadline_ms=None, max_consec_fail=4, now_ms=0)
    assert stop and "consec" in reason
def test_stop_on_wallclock():
    s = RunSummary()
    stop, reason = should_stop(s, cost_budget=0, deadline_ms=100, max_consec_fail=4, now_ms=200)
    assert stop and ("wall" in reason or "time" in reason)
def test_no_stop_when_under_limits():
    s = RunSummary(cost_usd=1.0, consec_fail=1)
    stop, _ = should_stop(s, cost_budget=4.0, deadline_ms=1000, max_consec_fail=4, now_ms=200)
    assert not stop
```
- [ ] **Step 2 — run, FAIL.**
- [ ] **Step 3 — implement** `RunSummary` (per spec §4.1) + `should_stop(summary, *, cost_budget, deadline_ms, max_consec_fail, now_ms) -> tuple[bool,str]`. `cost_budget<=0` / `deadline_ms is None` mean "off". Plus a `RunSummaryStore` (persist `<state>/run-summary.json`, like GoalStore) for the API to read.
- [ ] **Step 4 — gates.**
- [ ] **Step 5 — commit:** `feat(epic2): RunSummary + Ralph stop predicates`

### Task C2: replenish_goal + prompt
**Files:** Modify `backend/app/core/goals.py` (`replenish_goal`), create `prompts/goal-replenish.md`; Test `backend/tests/integration/test_replenish.py`.
- [ ] **Step 1 — failing test:** stub runner returning a non-empty PLAN block → `replenish_goal` adds N>0 tasks and resets `dry_rounds`; stub returning `{"tasks":[]}` → returns 0 and bumps `dry_rounds`. Cap at `HEPHAESTUS_REPLENISH_MAX`.
- [ ] **Step 2 — run, FAIL.**
- [ ] **Step 3 — implement** `prompts/goal-replenish.md` (inputs: goal + done-summary; instruct "return only what's still MISSING to complete the goal; if complete, return empty tasks"). `replenish_goal(ws, goal, *, runner) -> int`: gather done tasks of the goal, render prompt, run agent, parse PLAN block; if empty → bump `goal.dry_rounds`, persist, return 0; else cap to `HEPHAESTUS_REPLENISH_MAX`, `add_proposals_to_queue` + decompose, reset `dry_rounds`, persist, return count. Never raise on bad LLM (return 0).
- [ ] **Step 4 — gates.**
- [ ] **Step 5 — commit:** `feat(epic2): replenish_goal (dry-aware goal-directed replenishment)`

### Task C3: wire Ralph into `fsm.run()`
**Files:** Modify `backend/app/orchestrator/fsm.py`; Test `backend/tests/integration/test_ralph_loop.py`.
- [ ] **Step 1 — read** the real `run()` loop. Determine how item success is known (status after `_process_item`, or a return value). Define a local `_succeeded(item_id)` if needed (read state, status in done/merged/in_review).
- [ ] **Step 2 — failing tests** (stub `_process_item`, `_replenish`/`replenish_goal`, and cost so NO real git/LLM):
```python
# stops on cost budget
def test_ralph_stops_on_cost(monkeypatch, ralph_fsm_factory): ...
# stops after 2 dry replenishments (goal complete)
def test_ralph_stops_when_dry(monkeypatch, ralph_fsm_factory): ...
# stops on consecutive failures
def test_ralph_stops_on_consec_fail(monkeypatch, ralph_fsm_factory): ...
```
Build a factory that constructs an `OrchestratorFSM` in ralph mode with: a queue seeded via `_STATE_DIR_OVERRIDE`, `_process_item` monkeypatched to mark items done/failed without git, `_iter_cost` monkeypatched to a fixed cost, and `replenish_goal` monkeypatched (returns 0 to force dry, or N). Assert the loop exits with the expected `RunSummary.stopped_reason`. Keep iterations bounded so the test is fast.
- [ ] **Step 3 — implement** the loop changes per spec §4.2: read `run_mode`/budgets from env (`HEPHAESTUS_RUN_MODE`, `HEPHAESTUS_COST_BUDGET_USD`, `HEPHAESTUS_WALLCLOCK_SEC`, `HEPHAESTUS_MAX_CONSEC_FAIL`, `HEPHAESTUS_REPLENISH_MAX`); maintain a `RunSummary` (persist via store each iteration); call `should_stop` at the top; on empty queue in ralph mode with an active goal, call `replenish_goal` and apply dry-stop (2 consecutive dry → stop `"goal-complete (dry)"`); update `consec_fail`/`items_done`/`items_failed`/`cost_usd` after each item. All stops soft. Non-ralph path unchanged (existing idle-wait).
- [ ] **Step 4 — run new tests + existing `test_fsm.py`/`test_loop_start_stop.py`.** All pass.
- [ ] **Step 5 — commit:** `feat(epic2): Ralph run-mode loop (budgets + goal-directed replenish + dry-stop)`

### Task C4: DriverStartRequest + driver threading + config + status
**Files:** Modify `backend/app/models/requests.py`, `backend/app/core/driver.py`, `backend/app/api/v1/loop.py` (status), `backend/app/config.py`; Test `backend/tests/contract/test_driver_ralph.py`.
- [ ] **Step 1 — failing test:** `POST /api/driver/start {runMode:"ralph", costBudgetUsd:2.5, wallclockSec:3600}` (patch `pm`/`_start_loop` so no real process) → env contains `HEPHAESTUS_RUN_MODE=ralph`, `HEPHAESTUS_COST_BUDGET_USD=2.5`, `HEPHAESTUS_WALLCLOCK_SEC=3600`; `GET /api/driver/status` returns `runSummary` when `run-summary.json` exists.
- [ ] **Step 2 — run, FAIL.**
- [ ] **Step 3 — implement:** add fields to `DriverStartRequest` (`runMode: str|None`, `costBudgetUsd: float|None`, `wallclockSec: int|None`, `maxConsecFail: int|None`); thread them into env in `_start_loop` (mirror the existing `maxIter`/`tierReview` handling); add config keys to `ALLOWED_CONFIG_KEYS` + defaults (`HEPHAESTUS_RUN_MODE=queue`, `HEPHAESTUS_COST_BUDGET_USD=0`, `HEPHAESTUS_WALLCLOCK_SEC=0`, `HEPHAESTUS_REPLENISH_MAX=10`); extend the driver-status payload with `runSummary` read from `RunSummaryStore`.
- [ ] **Step 4 — gates** (full suite).
- [ ] **Step 5 — commit:** `feat(epic2): driver run-mode + budgets + runSummary status`

---

## BATCH D — Frontend

### Task D1: types + client
**Files:** Modify `frontend/src/types/api.ts`, `frontend/src/api/client.ts`.
- [ ] Add `modelOverride?: { provider: string; model: string; agent?: string } | null` and `complexity?: 'simple'|'medium'|'complex'|null` to `Item`. Add `Goal` interface + `RunSummary` interface (camelCase per spec). Add client methods: `createGoal(title, description)`, `listGoals()`, `deleteGoal(id)`, and ensure driver-start payload accepts `runMode`/`costBudgetUsd`/`wallclockSec`. Match existing `get/post` helper names.
- [ ] `npx vue-tsc --noEmit` clean. Commit: `feat(epic2): frontend types + goal/ralph client methods`

### Task D2: complexity badge + model selector
**Files:** Modify `frontend/src/components/TaskCard.vue`, `frontend/src/components/TaskDrawer.vue`; Test extend their specs.
- [ ] TaskCard: render a small complexity badge when `item.complexity` set (color by level; `data-test="complexity-badge"`). TaskDrawer: a model-override selector (options from workspace agents/models; "default" = clears override) that PATCHes `modelOverride` via `api` and a read-only complexity line. Add/extend vitest specs asserting badge renders and selecting a model calls the patch. Keep existing specs green.
- [ ] `npx vitest run` + `vue-tsc` clean. Commit: `feat(epic2): complexity badge + per-task model selector UI`

### Task D3: GoalComposer + run-mode controls
**Files:** Create `frontend/src/components/GoalComposer.vue`; Modify `frontend/src/views/BoardView.vue` and the driver-start UI (find where `api.driverStart`/start button lives — likely `RunningView.vue` or a control bar); Test `frontend/src/components/__tests__/GoalComposer.spec.ts`.
- [ ] **GoalComposer.vue:** title input + description textarea + "Спланировать" button → `api.createGoal` → emits/refreshes board; shows the returned task count. Mount in BoardView. Test (mock `@/api/client.createGoal` → returns `{ok, goal, taskIds:['a','b']}`): asserts clicking plans and shows "2".
- [ ] **Run-mode controls:** in the driver-start UI add a `runMode` toggle (queue/ralph), cost-budget + wall-clock inputs (shown when ralph), passed into the start call; show `runSummary` progress (items done/failed, $ spent, stopped reason) when present. Keep it minimal; test the toggle wiring if the start UI already has a spec.
- [ ] `npx vitest run` + `vue-tsc` + `npm run build` clean. Commit: `feat(epic2): GoalComposer + Ralph run-mode controls + progress`

---

## BATCH E — Integration verification
- [ ] Full backend suite green (`pytest tests/ -q`), ruff clean, `mypy --strict app/` clean.
- [ ] Full frontend (`vitest run`, `vue-tsc`, `build`) green.
- [ ] Final code review of the whole epic diff (`git diff master..HEAD`) by a reviewer subagent: focus on the `fsm.run()` Ralph loop (no infinite loops, all stops soft + persisted, replenish capped, dry-stop correct), `plan_goal`/`replenish_goal` (never raise on bad LLM), per-task override (no behavior change when unset), and queue-helper refactor (scan behavior unchanged). Apply fixes.

---

## Self-Review (applied during authoring)
- **Spec coverage:** §2→A1-A3; §3→B1-B4; §4→C1-C4; §5 safety→C1/C2/C3 (caps, soft stops, no-raise); §6 testing→every task TDD; UI §2.4/§3.4/§4.5→D1-D3.
- **Carried unknowns for implementers:** (1) exact `_run_opencode` signature + how `run_with_fallback` is called — A2 step 1 says read it; (2) how `_process_item` signals success — C3 step 1 says determine it (derive from item status); (3) where the driver-start button lives in the frontend — D3 says find it.
- **Type consistency:** `Goal`/`RunSummary`/`add_proposals_to_queue`/`plan_goal`/`replenish_goal`/`should_stop` names identical across backend tasks and frontend types; `modelOverride`/`complexity` consistent A1↔A2↔D1↔D2.
