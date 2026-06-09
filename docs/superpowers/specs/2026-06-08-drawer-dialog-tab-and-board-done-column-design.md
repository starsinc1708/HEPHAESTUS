# Task drawer «Диалог» tab + board «Готово» column — Design

**Goal:** Make the agent's run readable and stop losing finished work. Three UI fixes in the
task drawer and the board:
1. The agent conversation renders as a readable story (markdown), not raw JSON.
2. The four redundant tabs that all show the same agent event stream
   (Активность, Инструменты, Таймлайн, ▶ Live) collapse into ONE live «Диалог» tab.
3. A finished task (`done`/`merged`) stays visible on the board — it is currently hidden by
   default, and `merged` lands in a separate «Слито» column instead of «Готово».

**Status:** approved (brainstorming 2026-06-08). Decisions: one «Диалог» tab with the existing
markdown renderer; board shows done/merged by default and merges «Готово»+«Слито» into one
«Готово» column.

Frontend-only. The data already exists (the SSE stream `/api/iter/{dir}/stream` + the #5 full
parse `/api/iter/{dir}/conversation`); no backend change.

---

## 1. One «Диалог» tab — `TaskDrawer.vue`

The drawer tabs `Активность` (loadTab case 2), `Инструменты` (case 3) and `Таймлайн` (case 6) all
call `fetchEvents(dir, 'primary')` — the same data, rendered three ways — and `▶ Live` streams the
same thing as compact rows whose system/hook bodies are raw JSON.

- **Remove** the `Активность`, `Инструменты`, `Таймлайн` and `▶ Live` tabs and the `LiveConsole`
  import/usage from the drawer.
- **Add** one tab **«Диалог»** that renders the current iteration's implementer conversation with
  the existing [`ConversationPane.vue`](../../frontend/src/components/ConversationPane.vue) (#5):
  markdown text, collapsible thinking (`data-test="msg-thinking"`), expandable tool input/output
  (`data-test="msg-tool"`), tokens — no raw JSON. System/hook events are already dropped by the #5
  full parse, so only the real story shows (assistant text, thinking, tool_use + tool_result).
- **Live update:** while the task is `in_progress`, hold the existing SSE stream
  (`/api/iter/{dir}/stream`, primary→`output.primary` / fallback) purely as a "changed" signal and
  do a ~700 ms-debounced refetch of the full conversation — the exact pattern `ConversationView`
  already uses. When the task is not running, the pane is static.
- Data source: reuse the conversation store / `api.conversation(dir, stream)` that #5 introduced
  (the same call `ConversationPane`/`ConversationView` consume). The drawer shows the **implementer**
  stream of the current iteration (`item.lastIter`, stream `output.primary`, fallback
  `output.fallback`); validators/arbiters/final stay in the existing `Ревью` tab.
- Open-to-tab logic: a running task still opens to «Диалог» (replaces the old `LIVE_TAB`); the
  `Ревью` auto-open on review/revision is unchanged.
- Unchanged tabs: `Описание`, `Итерации`, `Дифф`, `Ревью`, `Проверки`. The full-screen «Переписки»
  button (route `/board/task/:id/conversation`) stays.

## 2. Board «Готово» column shows done + merged — `KanbanBoard.vue`

- Merge the `done` («Готово») and `merged` («Слито») columns into ONE «Готово» column. The column
  keeps `status: 'done'`, and `getItems('done')` returns items whose status is `done` OR `merged`.
  8 columns → 7.
- A merged card shows a small «слито» chip (so the distinction is still visible). Done from the
  funnel-but-not-merged stays a plain card.
- The `failed` column already aggregates `failed:*` via `startsWith` — mirror that idea for the
  done/merged grouping in `getItems`.

## 3. Board shows finished tasks by default — `BoardView.vue`

- `displayedItems` currently drops `done`/`merged` unless `showHistory` or an explicit
  Готово/Сл`и`то stat filter is active ([BoardView.vue:95-99](../../frontend/src/views/BoardView.vue)).
  Invert the default: **show** done/merged. Keep the `Готово`/`Слито` summary stats (they can both
  point at the merged column or be combined) and keep the history toggle, now meaning "hide
  finished" rather than "show finished" (or drop it if it no longer earns its place — decide during
  implementation, preferring the smaller surface).

## 4. Testing

- **TaskDrawer unit:** the drawer renders a «Диалог» tab; switching to it mounts `ConversationPane`
  (assert a `data-test` from the pane, e.g. `conv-msg`/`msg-thinking`); the removed tabs
  (Активность/Инструменты/Таймлайн/Live) are gone. Update/remove any existing test that asserted
  those tabs or `LiveConsole`.
- **KanbanBoard unit:** the «Готово» column contains both a `done` and a `merged` item; there is no
  separate «Слито» column; a `merged` card shows the «слито» chip.
- **BoardView unit:** a `done`/`merged` item is in `displayedItems` by default (no history toggle
  needed).
- Frontend gates green: `npx vitest run`, `npx vue-tsc -p tsconfig.app.json --noEmit` (the real
  type-check — bare `vue-tsc` is a no-op), `npx vite build`.

## 5. Out of scope

Backend changes; the full-screen «Переписки» viewer (unchanged); validator/review rendering (stays
in `Ревью`); restyling `ConversationPane` itself (reused as-is).

## 6. Risks

- `ConversationPane` was built for the full-screen viewer; verify it renders well in the narrower
  drawer column (it already has a render cap + collapsibles; adjust only width/overflow CSS if
  needed).
- Live refetch churn: debounce the SSE-triggered refetch (~700 ms) and only while `in_progress`, so
  a fast stream doesn't hammer `/conversation`.
- Removing tabs shifts the `loadTab` case indices — keep the index→tab mapping consistent with the
  `TABS` array, or switch to keyed tabs to avoid off-by-one bugs.
