# First-launch Onboarding + Tab Restructure + Remove autofix/changelog — Design

**Goal:** Make HEPHAESTUS understandable on first run: a **blocking first-launch wizard** (connect a
provider → confirm installed CLIs → pick a repo as workspace), the navigation **consolidated
from 9 tabs to 5** clear screens, and the confusing **autofix/changelog** features **removed**.
Sub-project #2 of the HEPHAESTUS v2 redesign ([[hephaestus-v2-redesign]]); builds on the finished
Providers v2 (#1).

**Status:** approved (brainstorming 2026-06-07). Decisions: **full consolidation into 5
screens**; **blocking** first-run wizard (skippable with a warning); **fully remove**
autofix/changelog (UI + backend).

**Current state (probed):** 12 routes / 9 nav items: Доска(/board), Выполняется(/running),
История(/history), Ветки(/branches), Инструменты(/tools), Настройки(/settings),
Промпты(/prompts), Логи(/logs), Insights(/insights), plus /config, /onboard, /board/task/:id.
Views: Board/Branches/Config/History/Insights/Logs/Onboard/Prompts/Running/Settings/Tools.
Workspace onboarding already exists: `OnboardView` → `ws.onboard(repoPath)`.

---

## 1. The 5 screens + fold-mapping

| New screen (route, nav) | Composes | Folded from |
|---|---|---|
| **Настройки** (`/settings`) | `ConnectionsManager` (providers, from #1) + GitHub/GitLab connect/auth (trimmed `IntegrationsPanel`, no autofix/changelog) | SettingsView (providers part) + IntegrationsPanel (trimmed) |
| **Агенты и запуск** (`/agents`) | `AgentRolesPicker` (roles) + scan/iteration/budget config (ConfigView body) + RALF/Loop controls (RunningView controls) + Prompts (PromptsView body) | SettingsView (roles) + ConfigView + RunningView + PromptsView |
| **Доска** (`/board`) | Kanban + run status on cards + a "готово/история" filter | BoardView + RunningView (status) + HistoryView |
| **Инструменты** (`/tools`) | Scanners + idea generation + Insights | ToolsView + InsightsView |
| **Worktrees** (`/worktrees`) | Basic branch/worktree list + diff/merge entry (full feature is #6 — this is the seed slot) | BranchesView |
| _Логи_ (drawer, not a tab) | Global console drawer (loop.log + iter logs), toggled from the shell header | LogsView |

**Routes:** keep `/board`, `/board/task/:id`, `/tools`, `/settings`; add `/agents`
(`AgentsRunView`), `/worktrees` (`WorktreesView`). **Redirect** old routes to their new home so
no link breaks: `/config`→`/agents`, `/running`→`/board`, `/history`→`/board`,
`/branches`→`/worktrees`, `/prompts`→`/agents`, `/insights`→`/tools`, `/logs`→`/board` (opens
the logs drawer). **Nav** becomes exactly 5 items: Настройки · Агенты и запуск · Доска ·
Инструменты · Worktrees, plus a "Логи" toggle button (opens the drawer).

**Implementation principle:** the new/repurposed views **compose existing components** — minimal
new logic. `AgentsRunView` and `WorktreesView` are new view files; `SettingsView`/`BoardView`/
`ToolsView` are repurposed. Old standalone views whose whole content moves (Running/History/
Branches/Config/Prompts/Insights/Logs) are deleted after their content lands in a new home (or
kept only as the redirect target).

## 2. First-launch blocking wizard (`OnboardWizard.vue`)

- **Trigger:** `needsOnboarding = (connections.length === 0) || (activeWorkspaceId == null)`,
  derived from the existing stores (`getConnections`, `getWorkspaces.activeId`) — **no new
  backend state**.
- **Render:** when `needsOnboarding && !skipped`, `AppShell` mounts `OnboardWizard` as a
  full-screen blocking overlay (the rest of the app is not interactable behind it).
- **Steps:**
  1. **Подключи провайдера** — mount `ConnectionsManager`; "Далее" enabled once ≥1 connection
     has `status==='connected'`.
  2. **Проверь CLI** — show the engines panel (`GET /api/v1/clis`); informational ✓/✗ per
     `claude/opencode/codex`; always allows "Далее".
  3. **Выбери репозиторий** — a repo-path input → `ws.onboard(repoPath)` (reuse OnboardView's
     flow); "Готово" enabled once a workspace is active.
- **Skip:** a "Пропустить" link sets `localStorage['hephaestus.onboarding.skipped']='1'`; the app
  opens with a dismissible top banner ("Подключите провайдера и репозиторий, чтобы запускать
  задачи") that re-opens the wizard.
- **Completion:** when both conditions are met the overlay unmounts automatically (reactive on
  `needsOnboarding`).

## 3. Remove autofix/changelog (fully)

**Backend:**
- Delete `app/services/integrations/autofix.py`, `app/services/integrations/changelog.py`,
  `prompts/changelog.md`.
- In `app/api/v1/integrations.py`: remove the `POST …/changelog`, `GET/POST …/autofix`,
  `POST …/autofix/sync` endpoints and their imports/bodies. **Keep** the GitHub/GitLab,
  `/integrations`, `/{name}/import`, `/pr`, `/{name}/sync-status/{item_id}` endpoints.
- In `app/config.py`: remove the autofix config keys from `ALLOWED_CONFIG_KEYS`/defaults.
- Remove the autofix/changelog tests (and the `changelog` agent-job kind reference if any).

**Frontend:**
- `IntegrationsPanel.vue`: remove the autofix + changelog sections; keep GitHub/GitLab connect.
- `api/client.ts` + `types/api.ts`: remove `generateChangelog`, autofix config methods/types.
- Update `IntegrationsPanel.spec.ts`.

## 4. Architecture / data flow

- **Router** (`src/router.ts`): 5 primary routes + the redirects (§1). A `beforeEach` is **not**
  used for onboarding (the wizard is an overlay, not a route) to keep deep-links working.
- **AppShell** (`src/components/AppShell.vue`): `navItems` → the 5; add a "Логи" button bound to
  a `logsDrawerOpen` ref rendering `LogsDrawer`; mount `<OnboardWizard v-if="needsOnboarding && !skipped"/>`.
- **New views** `AgentsRunView.vue` (sections: Роли / Сканы+итерации / Запуск(RALF·Loop) /
  Промпты) and `WorktreesView.vue` (branch/worktree list reusing BranchesView's logic). New
  `LogsDrawer.vue` (reuses LogsView's log fetch).
- Existing backend endpoints are unchanged except the autofix/changelog removals.

## 5. Testing

- **Router unit:** the 5 named routes resolve; each old path redirects to its new home.
- **AppShell unit:** renders exactly 5 nav items + a Логи toggle; `OnboardWizard` shows when
  `needsOnboarding` and hides when satisfied; "Пропустить" sets the flag + shows the banner.
- **OnboardWizard unit:** step 1 "Далее" disabled until a connected connection exists; step 3
  "Готово" gated on an active workspace; skip path.
- **Removal:** backend — the changelog/autofix routes 404 / are gone, github/gitlab still 200;
  frontend — IntegrationsPanel has no autofix/changelog controls, client has no changelog method.
- **Live (verify skill):** point HEPHAESTUS at a throwaway `HEPHAESTUS_LOOP_HOME` (empty store) → open the
  board → the wizard blocks; connect a provider + onboard a repo → wizard disappears, the 5-tab
  shell is shown; confirm github/gitlab settings still work and no changelog/autofix UI remains.

## 6. Out of scope (other sub-projects)

Full Worktrees tab with diffs + AI conflict resolution (#6 — here only the basic slot/list);
the per-stage conversation viewer (#5); the task dependency graph (#4); auto-driver (#3). The
agent-role resolver, FSM, runner, and Providers v2 are untouched.

## 7. Risks

- SettingsView/ConfigView/RunningView are large — fold carefully; every endpoint those views
  call must keep working (only autofix/changelog endpoints go away).
- The exact contents of the global Логи drawer (which logs, tail length) is finalized during
  implementation; the seam is `LogsView`'s existing fetch.
- Removing the `changelog` agent-job kind must not break the agent-jobs store (verify no other
  caller references it).
