# Goal→Decompose + Import Ideas/Scans → Board — Design

**Goal:** From the Board, propose a goal and have agents decompose it (asynchronously, with
progress) into a dependency-aware task tree that lands as backlog tasks; and from Tools, select
generated ideas / scan findings and import them as backlog tasks. The user then runs them via #3
(send-to-run) honouring #4 (dependencies). Sub-project #7 of the HEPHAESTUS v2 redesign
([[hephaestus-v2-redesign]]).

**Status:** approved (brainstorming 2026-06-07). Decisions: goal decompose is **async with a
progress job** (like idea generation); the board goal is a **pure one-shot** (decompose → tasks
on the board; Ralph stays the separate autonomous mode in «Агенты и запуск»); ideas/scans import
via **checkbox-select + «Импортировать на доску»**.

**Current state (probed):** much exists — `POST /api/v1/goals` ("create goal + decompose into
tasks", currently **sync** in a threadpool); `POST /api/v1/ideas/import {ids}` (import selected
ideas into the queue); `add_proposals_to_queue(proposals, epic_id)` (append proposals as
`pending` tasks, skipping existing ids, `dependsOn=[]`); `decompose.py` produces task dicts
**with `dependsOn`** (a tree); the agent-job pattern (`start_agent_job`, `useAgentJob`,
`/api/v1/agent-jobs/{id}`) drives idea/changelog-style async jobs. #2 folded scanners + ideas +
Insights into the **Tools** tab; #3 gave `pending` backlog; #4 honours `dependsOn`.

---

## 1. Board goal → async one-shot decompose

- A **«Новая цель»** control on the Board (`BoardView`) opens a small input (goal text +
  optional max-tasks) → calls a goal-decompose endpoint that runs **as an agent job**.
- **Backend:** rework `POST /api/v1/goals` (or add `POST /api/v1/goals/decompose`) to wrap the
  decomposition in `start_agent_job("decompose", work)` and return `{ok, jobId, kind}`. The job's
  `work` runs the existing decompose agent and `add_proposals_to_queue(tasks)` so the tree
  (with `dependsOn`) lands as `pending`. **One-shot:** it does **not** start Ralph/continuous
  replenishment — it just produces the task tree. (A goal record may still be created for
  provenance, but no loop is auto-started.)
- **Frontend:** the «Новая цель» modal kicks off the job and shows progress via the existing
  `useAgentJob` composable; on completion it refreshes the board (the new `pending` tasks appear,
  and the #4 graph mode shows their dependency tree). The user then «Запустить» the root → #3+#4
  run the chain in dependency order.

## 2. Tools — import selected ideas / scan findings → board

- In the **Tools** tab, the idea-generation results and scan results render as **checkbox-select**
  lists with a **«Импортировать на доску»** button. Imported items become `pending` backlog tasks.
- **Ideas:** `POST /api/v1/ideas/import {ids}` already exists — wire the selection UI to it.
- **Scans:** add `POST /api/v1/scans/import {ids}` (if not present) that maps the selected scan
  findings → proposals → `add_proposals_to_queue` (idempotent: skip ids already on the board).
- After import, the board refreshes; imported tasks carry any `dependsOn` the source produced
  (scan findings typically none; that's fine — they're independent backlog items).

## 3. Backend changes

- `app/api/v1/goals.py`: make the decompose path async via `start_agent_job("decompose", work)`;
  `work` = run decompose agent → `add_proposals_to_queue(tasks)`; return `{ok, jobId, kind}`.
  Keep the existing `GET /goals`, `DELETE /goals/{id}` for back-compat.
- `app/api/v1/scans.py`: `POST /api/v1/scans/import {ids}` → resolve the scan's stored proposals
  by id → `add_proposals_to_queue` (reuse the ideas-import shape). 404/empty handled cleanly.
- No change to the decompose agent logic or `add_proposals_to_queue` (it already sets `pending`,
  `dependsOn`, skips existing).

## 4. Frontend changes

- `BoardView`: a «Новая цель» button → a `GoalModal.vue` (text + optional max) → start the
  goal-decompose job, show progress (`useAgentJob`), refresh on done.
- Tools (the panels folded in #2): idea list + scan list get a selection model
  (`data-test="import-select-<id>"`) + an «Импортировать на доску» button
  (`data-test="ideas-import"` / `data-test="scans-import"`) calling the import endpoints.
- API client + types: `decomposeGoal(text, maxTasks?) → {jobId,kind}`, `importScans(ids)`; ideas
  import already wired.

## 5. Testing

- **Backend:** goal-decompose returns a `jobId` and the job populates work-state with `pending`
  tasks carrying `dependsOn` (mock the decompose runner to emit a 3-task tree); `scans/import`
  adds selected findings as `pending` and skips already-present ids; `ideas/import` still works.
- **Frontend unit:** «Новая цель» starts the job + shows progress + refreshes the board on
  completion (mock `useAgentJob`); the Tools idea/scan lists select items and the import button
  calls the right endpoint with the selected ids.
- **Live (verify skill):** on the Board, enter a goal → the decompose job runs (progress) → a
  task tree appears as `pending`; switch the board to Граф (#4) → the dependency tree shows;
  «Запустить» the root → #3+#4 queue the chain in order. In Tools, generate ideas → select 2 →
  «Импортировать» → 2 `pending` tasks appear on the board; run a scan → import a finding → it
  appears. Capture evidence.

## 6. Out of scope

The decompose agent's prompt/logic (only async-wrapped); Ralph/continuous mode (the board goal is
one-shot — Ralph stays in «Агенты и запуск»); the dependency graph/gating themselves (#4 done);
worktrees (#6); GitHub/GitLab (#8).

## 7. Risks

- **Job writes to work-state** — the decompose job runs in the agent-job worker and must persist
  the tasks via the same `add_proposals_to_queue` path (state-lock honoured); verify no double-add
  on job retry (idempotent skip-existing).
- **One-shot vs existing goal/Ralph infra** — ensure creating a board goal does **not** auto-start
  the continuous loop; it only enqueues the decomposed `pending` tasks.
- **Import idempotency** — both imports skip ids already on the board so re-import is safe.
- **Board refresh timing** — refresh after the job completes (poll/terminal), not mid-run.
