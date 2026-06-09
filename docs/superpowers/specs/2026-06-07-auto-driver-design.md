# Auto-driver — Design

**Goal:** Stop making the user start/stop the loop. The driver **auto-starts** when the user
**sends a task to run**, processes the sent tasks, and **exits when the run-queue is empty** —
but tasks **never run unless the user explicitly sends them**. Sub-project #3 of the HEPHAESTUS v2
redesign ([[hephaestus-v2-redesign]]).

**Status:** approved (brainstorming 2026-06-07). Decisions: send-to-run via **both** a per-task
"Запустить" button **and** a board "К запуску" column; driver **exits on empty queue**
(auto-restarts on next send); **auto-start + a «Стоп»/«Возобновить» toggle** (no «Старт»).

**Current mechanics (probed):** new/decomposed/imported tasks get `status="pending"`; the loop
process (`app/core/driver.py::_start_loop` → `pm.start("loop", …)`) is started/stopped manually
via `/api/driver/start|stop|kill`; the FSM picks **`pending`** items
(`_pick_next_item`/`_claim_next_item` filter `status=="pending"`) and, on a dry queue, **sleeps
30s and loops forever**; crash recovery resets `in_progress`→`pending`. Statuses in use:
pending/in_progress/running/queued(literal, not loop-relevant today)/in_review/needs_revision/
done/merged/failed:*.

---

## 1. Status model — separate backlog from "sent to run"

- New/decomposed/imported tasks and ideas stay **`pending`** = **backlog, NOT run**.
- A task the user sends becomes **`queued`** = **runnable**; the loop picks **only `queued`**.
- Flow: `pending` → (send) → `queued` → `in_progress` → `in_review` → `done`/`merged`/`failed:*`.
- Crash recovery resets stale `in_progress` → **`queued`** (so a restarted driver resumes only
  the sent tasks, never the backlog).
- The `_pick_next_item`/`_claim_next_item` filters change `pending`→`queued`. **Everything that
  creates a task keeps writing `pending`** (queue_add, decompose, ideas import) — so nothing
  auto-runs. Reconcile any pre-existing `queued` literal usage during impl (it is not the
  loop-pick status today, so repurposing it is safe).

## 2. Send-to-run + un-send

- `POST /api/v1/tasks/{id}/run` → if status ∈ {`pending`,`needs_revision`}: set `queued`, then
  `reconcile_driver()`. Returns the new status. `POST /api/v1/tasks/run` (bulk: `{ids:[…]}`).
- `POST /api/v1/tasks/{id}/unqueue` → `queued`→`pending` (only while not yet `in_progress`).
- Both the per-task **«Запустить»** button (card + drawer) and the board **«К запуску»** column
  (drag → run; drag out → unqueue) call these. Dependency gating is **#4**, not here — any
  `pending` task can be sent.

## 3. Driver reconciler + pause

New `app/core/driver.py` helpers (single source of truth for "should the loop be running"):
- `driver_paused()` / `set_driver_paused(bool)` — a persisted flag (`state/driver.json` or a
  config key), default `false`.
- `_has_runnable() -> bool` — any item with status in {`queued`,`in_progress`} in work-state.
- `reconcile_driver()` — if `_has_runnable()` and not `driver_paused()` and the loop process is
  not RUNNING → `_start_loop({})`. Idempotent; safe to call often. Called after send-to-run,
  after un-pause, and on backend startup.

## 4. Loop change (`fsm.run`, queue mode only)

- Pick **`queued`** (not `pending`).
- On a **dry queue** (no `queued` and no `in_progress`): **exit the run loop** (process ends)
  instead of `sleep 30s` forever. (Ralph mode is unchanged — it intentionally replenishes toward
  a goal and keeps running until its budgets/dry-stop; auto-exit is **queue mode only**.)
- To avoid an exit↔send race: re-check the queue immediately before exiting; the
  `reconcile_driver()` on the next send re-starts the process if it had already exited.
- Crash recovery (`_recover_*`) resets `in_progress`→`queued`.

## 5. Driver controls + status

- New/extend `GET /api/driver/status` to also report `paused` + counts (`queued`, `inProgress`).
- `POST /api/driver/pause` (set paused=true + `_stop_loop_soft`) and `POST /api/driver/resume`
  (set paused=false + `reconcile_driver`). **Remove** the manual `POST /api/driver/start` from
  the UI (keep the endpoint for tests/back-compat, but the shell never calls it).

## 6. Frontend

- `AgentsRunControls.vue` (in «Агенты и запуск»): replace the «Старт» button with a **status
  indicator** — «Драйвер: работает (N в работе, M в очереди) / на паузе / простаивает» — driven
  by `/api/driver/status` polling — plus a single **«Стоп»/«Возобновить»** toggle (pause/resume).
- **Board** (`BoardView`): add a **«К запуску»** column for `queued`, positioned between backlog
  (`pending`) and «в работе» (`in_progress`/`in_review`); drag pending→queued calls `/run`,
  drag queued→pending calls `/unqueue`. Per-task **«Запустить»** button on the card and in the
  TaskDrawer for `pending`/`needs_revision`; **«Снять с очереди»** for `queued`.

## 7. Testing

- **Backend unit:** `_has_runnable`/`reconcile_driver` (starts when runnable+unpaused+stopped;
  no-op when paused or already running or nothing runnable); pause→stop, resume→reconcile; the
  FSM picks `queued` not `pending`; queue-mode `run()` exits on empty (mock the pick to return
  None → loop returns, no infinite sleep); recovery `in_progress`→`queued`.
- **Backend contract:** `/run` flips pending→queued + 409/ignored for bad status; bulk; `/unqueue`;
  `/api/driver/status` includes `paused`+counts; pause/resume.
- **Frontend unit:** «Запустить» calls `/run`; board «К запуску» column renders `queued` items
  and drag triggers `/run`/`/unqueue`; AgentsRunControls shows the right status and the
  Стоп/Возобновить toggle hits pause/resume; no «Старт» button exists.
- **Live (verify skill):** add a task (stays in backlog, driver idle) → click «Запустить» → the
  driver auto-starts, the task runs and on completion the driver process exits (no manual
  start); send another → it auto-starts again; «Стоп» mid-run halts; «Возобновить» resumes.

## 8. Out of scope

Dependency gating / graph (#4 — here any pending is sendable), conversation viewer (#5),
worktrees tab (#6). Ralph/goal mode keeps its current continuous behavior (a goal is itself an
explicit "send to run"); only its trigger is unchanged.

## 9. Risks

- **Exit↔send race** — mitigated by the pre-exit re-check + reconcile-on-send.
- **Pre-existing `queued` literal** — confirm it isn't relied on elsewhere before making it the
  loop-pick status.
- **Backend-startup auto-start** — only when leftover `queued`/`in_progress` AND not paused, so a
  fresh/empty store never spawns a loop.
- Board column add must not break the existing kanban DnD (#2 left columns intact).
