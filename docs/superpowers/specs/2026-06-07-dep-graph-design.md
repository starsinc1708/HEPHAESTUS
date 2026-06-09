# Task Dependency Graph + Gating — Design

**Goal:** Enforce task dependencies, let the user see them as a graph, and edit them. A task with
unfinished prerequisites can't run; sending a task to run queues its whole unfinished
prerequisite chain and the loop runs them in dependency order. Sub-project #4 of the HEPHAESTUS v2
redesign ([[hephaestus-v2-redesign]]); builds on #3 auto-driver.

**Status:** approved (brainstorming 2026-06-07). Decisions: **queue-the-chain + topo order**
(«Запустить» queues the task + its unfinished prerequisites; the loop runs ready-first); the
graph is a **mode toggle on the Board** (kanban ↔ graph); dependencies are edited in the
**TaskDrawer** (drag-to-connect on the graph is out of scope).

**Current state (probed):** items carry `dependsOn: string[]` (+ inverse `blocks`); `decompose`
populates `dependsOn` (LLM, with id-validation + self/2-cycle breaking); the board card +
TaskDrawer **display** deps/blocks (badges «Требует/Блокирует») but nothing **gates, edits, or
graphs** them. #3 gave: `pending`=backlog, `queued`=sent (loop picks `queued`), `/api/v1/tasks/{id}/run`,
`reconcile_driver`, queue-mode exit-on-empty, `_has_runnable`.

---

## 1. Dependency helpers (`app/core/deps.py`)

Pure functions over the work-state items (`by_id = {it["id"]: it}`):
- `is_done(item)` — `status in {"done","merged"}`.
- `deps_satisfied(item, by_id)` — every `dependsOn` id is present **and** `is_done` (a missing
  dep id is treated as satisfied so a deleted prereq never deadlocks).
- `ready(item, by_id)` — `status == "queued"` and `deps_satisfied`.
- `has_runnable(items)` — any `in_progress` **or** any `ready` (replaces #3's "any queued/in_progress").
- `unfinished_ancestors(task_id, by_id)` — the transitive set of `dependsOn` ancestors that are
  **not** `is_done` (the prerequisite chain to queue).
- `would_create_cycle(task_id, new_dep_id, by_id)` — DFS over `dependsOn` to detect a cycle.
- `recompute_blocks(items)` — rebuild every item's `blocks` as the inverse of all `dependsOn`.

## 2. Queue-the-chain (extend `POST /api/v1/tasks/{id}/run`)

`/run` (and bulk `/run`) now: collect `{task} ∪ unfinished_ancestors(task)`, set each that is
`pending`/`needs_revision` to `queued` (already-`queued`/`in_progress` left as is), then
`reconcile_driver()`. Returns the count queued. `/unqueue` only un-queues the single task
(`queued`→`pending`) when not yet `in_progress`. Dependency **gating is enforced at execution**
(§3), so `/run` never refuses on unfinished deps — it queues the chain.

## 3. Loop gating (FSM, on top of #3)

- `_pick_next_item`/`_claim_next_item` pick a `queued` item that is **`ready`** (deps satisfied),
  not just any `queued`. Topo order emerges naturally: only leaves (no unfinished deps) are ready
  first; as each finishes, its dependents become ready.
- The queue-mode dry-check uses `has_runnable(items)` (§1): exit when no `in_progress` and no
  `ready` queued. **Dead-end:** if a prerequisite ends `failed:*`, its dependents stay
  `queued`-but-not-`ready` → `has_runnable` is false → the driver exits cleanly; the blocked
  tasks remain queued and the UI shows «заблокирована (зависимость X провалена)». The user
  requeues/fixes X. Ralph mode keeps picking `{queued,pending}` but **also** honours `ready`
  (a ralph task with unfinished deps waits).

## 4. Editing dependencies (drawer + backend)

- `PATCH /api/v1/tasks/{id}/deps` body `{dependsOn: string[]}` → validate: each id exists, no
  self-ref, and `not would_create_cycle` for each new edge; on success persist the item's
  `dependsOn` and `recompute_blocks(items)`. 400 with the offending id on a cycle/self/unknown.
- **TaskDrawer:** a «Зависимости» editor — current `dependsOn` as removable chips (✕) + «Добавить
  зависимость» (a `<select>`/typeahead of other tasks by id+title). Add/remove calls the PATCH;
  a cycle attempt shows the 400 error inline. The existing read-only deps/blocks display is
  replaced by this editor.

## 5. Graph mode on the Board

- `BoardView` gets a view toggle `data-test="board-view-mode"` → «Колонки» (existing kanban) /
  «Граф». Graph mode mounts `DepGraph.vue`.
- `DepGraph.vue`: a **lightweight layered SVG DAG**, no heavy library. Compute longest-path
  layering (each node's level = 1 + max level of its `dependsOn`), place nodes in level columns,
  draw `dependsOn` edges as SVG lines with arrowheads. Nodes are small cards (id/short title)
  coloured by status (backlog/queued/in_progress/in_review/done/failed) with a «ready»/«ждёт»
  ring; click a node → open the TaskDrawer (router `/board/task/:id`). Read-only.
- Performance: cap the rendered set sensibly (e.g. current workspace's items); horizontal scroll
  for wide graphs.

## 6. UI gating affordances

- Card/drawer «Запустить» (for `pending`/`needs_revision`) calls `/run` (queues the chain) with a
  tooltip when it will also queue prerequisites («+N предпосылок»). A `queued` task with
  unfinished deps shows a «ждёт: X, Y» sub-badge (from `deps_satisfied`).

## 7. Testing

- **Backend unit (`deps.py`):** `deps_satisfied`/`ready`/`has_runnable`; `unfinished_ancestors`
  (transitive, skips done); `would_create_cycle` (direct + transitive); `recompute_blocks`.
- **Backend (FSM + api):** `/run` queues the chain (task + unfinished ancestors); the loop picks
  only `ready` (a blocked queued task is skipped; topo order on a 3-chain); dead-end (failed dep
  → driver exits, dependents stay queued); `PATCH …/deps` rejects a cycle/self/unknown id and
  recomputes `blocks`.
- **Frontend unit:** `DepGraph` renders N nodes + the right edges from a fixture and a node click
  opens the drawer; the board mode toggle switches kanban↔graph; the drawer dep-editor adds/removes
  a dep (calls PATCH) and shows the cycle error; a `queued`-with-unfinished-deps card shows «ждёт».
- **Live (verify skill):** create A→B→C (C depends on B, B on A); «Запустить» C → queue holds
  {A,B,C}; the driver runs A→B→C in order (verify via status/logs); attempt a cycle edit (C→A) →
  rejected; the Board graph mode shows the three-node chain coloured by status; clicking a node
  opens its drawer.

## 8. Out of scope

Drag-to-connect editing on the graph (graph is read-only here); auto-layout libraries; the
conversation viewer (#5); the worktrees tab (#6); goal→auto-decompose (#7). Existing
decompose-produced dependencies are honoured as-is.

## 9. Risks

- **Layered-DAG layout** is the main UI effort — keep it a simple longest-path layering; if it
  gets gnarly, a tiny layered placement is still preferable to pulling in a graph library.
- **`ready` pick must stay consistent with #3** `_has_runnable`/exit so the driver neither spins
  on a dead-end nor exits while work remains — both use the same `has_runnable`.
- **Large graphs** (many tasks) — render the active workspace's items only; horizontal scroll.
- **`recompute_blocks`** must run on every `dependsOn` change (edit, and ideally decompose) so the
  inverse stays correct.
