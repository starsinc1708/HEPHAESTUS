# Onboarding Wizard + Tab Restructure + Remove autofix/changelog — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A blocking first-launch wizard, navigation consolidated 9→5 screens, and autofix/changelog fully removed.

**Architecture:** Mostly a **frontend restructure that composes existing components** + a clean backend removal. New views `AgentsRunView`/`WorktreesView`, new `OnboardWizard`/`LogsDrawer`; repurposed `SettingsView`/`BoardView`/`ToolsView`; router gets 5 primary routes + redirects; old standalone views are deleted after their content moves. No new backend state — `needsOnboarding` is derived from existing stores.

**Tech Stack:** Vue 3 + Pinia + TS (vitest, vue-tsc), FastAPI + Pydantic (pytest/ruff/mypy --strict). Russian UI. Cross-platform.

**Gates (after every task that touches them):** frontend `npx vitest run` + `npx vue-tsc -p tsconfig.app.json --noEmit` (NOTE: bare `npx vue-tsc --noEmit` is a no-op here — root tsconfig has `files:[]`; ConfigView.vue/ToolsView.vue have *pre-existing* unrelated errors, confirm your changed files add 0) + `npm run build`; backend `backend/.venv/Scripts/python.exe -m pytest -q` + `ruff check app tests` + `mypy --strict app/`.

**Current structure (probed):** views Board/Branches/Config/History/Insights/Logs/Onboard/Prompts/Running/Settings/Tools; nav (9) Доска/Выполняется/История/Ветки/Инструменты/Настройки/Промпты/Логи/Insights; routes incl. `/board /board/task/:id /config /history /branches /running /tools /logs /onboard /settings /prompts /insights`. autofix/changelog live in `backend/app/services/integrations/{autofix,changelog}.py`, endpoints in `backend/app/api/v1/integrations.py`, keys in `backend/app/config.py`, `prompts/changelog.md`, and frontend `IntegrationsPanel.vue` + `api/client.ts` + `types/api.ts`. Workspace onboarding: `OnboardView` → `ws.onboard(repoPath)`.

---

### Task 1: Backend — remove autofix/changelog

**Files:** Delete `backend/app/services/integrations/autofix.py`, `backend/app/services/integrations/changelog.py`, `prompts/changelog.md`; Modify `backend/app/api/v1/integrations.py`, `backend/app/config.py`; Delete/trim the autofix/changelog tests.

- [ ] **Step 1: find the blast radius** — `grep -rn "autofix\|changelog" backend/app backend/tests prompts`. Note every endpoint/import/test/config key.
- [ ] **Step 2: remove endpoints** — in `integrations.py` delete the route fns `generate_changelog_endpoint` (`POST …/changelog`), `get_autofix_config`/`patch_autofix_config` (`GET/POST …/autofix`), and `…/autofix/sync`, plus their request-body models and the `from app.services.integrations.autofix import _autofix_tick` import. **Keep** `/integrations`, `/{name}/import`, `/pr`, `/{name}/sync-status/{item_id}`, and all GitHub/GitLab code.
- [ ] **Step 3: delete service files + prompt** — `git rm backend/app/services/integrations/autofix.py backend/app/services/integrations/changelog.py prompts/changelog.md`.
- [ ] **Step 4: config keys** — in `config.py` remove any `HEPHAESTUS_AUTOFIX*` (or similar) entries from `ALLOWED_CONFIG_KEYS` and defaults.
- [ ] **Step 5: tests** — delete autofix/changelog-specific tests; if `agent_jobs` had a `"changelog"` kind test, remove that path; grep confirms no remaining `changelog`/`autofix` references in `app/`.
- [ ] **Step 6: gates green** (pytest/ruff/mypy) — fix any now-dangling import. **Commit** `refactor(integrations): remove autofix + changelog (backend)`.

---

### Task 2: Frontend — remove autofix/changelog

**Files:** Modify `frontend/src/components/IntegrationsPanel.vue`, `frontend/src/api/client.ts`, `frontend/src/types/api.ts`, `frontend/src/components/__tests__/IntegrationsPanel.spec.ts`.

- [ ] **Step 1: failing/updated test** — edit `IntegrationsPanel.spec.ts` to assert there is **no** element `[data-test="autofix-section"]` / `[data-test="changelog-section"]` and that GitHub/GitLab connect controls still render.
- [ ] **Step 2: implement** — remove the autofix + changelog `<section>`s and their handlers/state from `IntegrationsPanel.vue` (keep GitHub/GitLab). Remove `generateChangelog` + any `getAutofixConfig`/`setAutofixConfig` from `client.ts` and their types from `types/api.ts`. Grep the frontend for remaining `changelog`/`autofix` refs and clean them.
- [ ] **Step 3: gates** (vitest + `vue-tsc -p tsconfig.app.json` + build). **Commit** `refactor(integrations): remove autofix + changelog (frontend)`.

---

### Task 3: Router + AppShell nav (5 + redirects) + LogsDrawer

**Files:** Modify `frontend/src/router.ts`, `frontend/src/components/AppShell.vue`; Create `frontend/src/components/LogsDrawer.vue`; Test `frontend/src/__tests__/router.spec.ts` (create), `frontend/src/components/__tests__/AppShell.spec.ts` (create/extend).

- [ ] **Step 1: failing tests**
```ts
// router.spec.ts
import { routes } from '@/router'  // export `routes` from router.ts if not already
const byName = (n: string) => routes.find(r => r.name === n)
test('five primary screens exist', () => {
  for (const n of ['settings', 'agents', 'board', 'tools', 'worktrees']) expect(byName(n)).toBeTruthy()
})
test('old paths redirect to their new home', () => {
  const red = (p: string) => routes.find(r => r.path === p)?.redirect
  expect(red('/config')).toBe('/agents'); expect(red('/running')).toBe('/board')
  expect(red('/history')).toBe('/board'); expect(red('/branches')).toBe('/worktrees')
  expect(red('/prompts')).toBe('/agents'); expect(red('/insights')).toBe('/tools')
})
```
```ts
// AppShell.spec.ts — exactly five nav items + a logs toggle
const w = mount(AppShell, { global: { plugins: [router, pinia], stubs: { 'router-view': true } } })
expect(w.findAll('[data-test="nav-link"]')).toHaveLength(5)
await w.find('[data-test="logs-toggle"]').trigger('click')
expect(w.find('[data-test="logs-drawer"]').exists()).toBe(true)
```

- [ ] **Step 2: FAIL. Step 3: implement**
  - **First create stub views** `frontend/src/views/AgentsRunView.vue` and `WorktreesView.vue` (each just `<template><div/></template>` for now — filled in Tasks 4–5) so the router's lazy imports resolve and `npm run build` passes this task.
  - `router.ts`: export `routes`; primary routes `{path:'/settings',name:'settings',…}`, `/agents`→`AgentsRunView`, `/board`(+`/board/task/:id`), `/tools`, `/worktrees`→`WorktreesView`; redirects `{path:'/config',redirect:'/agents'}` etc. for config/running/history/branches/prompts/insights/logs/onboard (logs+onboard→`/board`). Keep `/` → redirect `/board`.
  - `AppShell.vue`: `navItems` = the 5 (`data-test="nav-link"` on each `router-link`); add a "Логи" button (`data-test="logs-toggle"`) bound to `const logsDrawerOpen = ref(false)`; render `<LogsDrawer v-if="logsDrawerOpen" data-test="logs-drawer" @close="logsDrawerOpen=false"/>`.
  - `LogsDrawer.vue`: a right-side overlay that reuses `LogsView`'s log fetch (move/extract the fetch); shows the tail with a close ✕.
- [ ] **Step 4: PASS; gates; Commit** `feat(nav): 5-screen router + nav + logs drawer + redirects`.

---

### Task 4: AgentsRunView (roles + config + run + prompts)

**Files:** Create `frontend/src/views/AgentsRunView.vue`; Test `frontend/src/views/__tests__/AgentsRunView.spec.ts`.

- [ ] Compose four sections (each `data-test="agents-<key>"`): **roles** (`<AgentRolesPicker>` + the connections load it needs — reuse SettingsView's current wiring), **scans** (scan params), **iterations** (ConfigView's body: max-iter/tier thresholds/budgets — move its component/logic here), **run** (RALF/Loop controls from RunningView: start/stop, run-mode), **prompts** (PromptsView's editor body).
- [ ] **Spec:** mount with mocked api; assert the four `data-test="agents-roles|scans|run|prompts"` sections render and the roles picker shows connected connections. **Step 2 FAIL → 3 implement (lift the bodies of ConfigView/RunningView/PromptsView into sections; keep their api calls) → 4 PASS → gates; Commit** `feat(agents): AgentsRunView composes roles+config+run+prompts`.

---

### Task 5: SettingsView repurpose + WorktreesView + Board/Tools folds + delete dead views

**Files:** Modify `frontend/src/views/SettingsView.vue`, `frontend/src/views/BoardView.vue`, `frontend/src/views/ToolsView.vue`; Create `frontend/src/views/WorktreesView.vue`; Delete `ConfigView.vue RunningView.vue HistoryView.vue BranchesView.vue PromptsView.vue InsightsView.vue LogsView.vue OnboardView.vue` (after their content moved in Tasks 3–4 and here); Tests as noted.

- [ ] **SettingsView** → only **Подключения** (`<ConnectionsManager>`) + **GitHub/GitLab** (`<IntegrationsPanel>`, already trimmed in Task 2). Remove the roles block (now in AgentsRunView). Spec: renders `ConnectionsManager` + `IntegrationsPanel`, no roles picker.
- [ ] **WorktreesView** → reuse BranchesView's branch/worktree list + per-branch diff/merge entry (`<MergeButton>` already exists). `data-test="worktrees-list"`. Spec: renders the branch rows from the mocked branches api.
- [ ] **BoardView** → add a "готово/история" filter control (`data-test="board-history-filter"`) folding HistoryView, and surface run status on cards (RunningView's status already flows via the task store). Spec: filter toggles done items.
- [ ] **ToolsView** → mount the Insights panel (`<InsightsChat>`/InsightsView body) alongside scanners + ideas. Spec: renders an `data-test="tools-insights"` section.
- [ ] **Delete dead views** + remove any lingering imports; `grep -r "ConfigView\|RunningView\|HistoryView\|BranchesView\|PromptsView\|InsightsView\|LogsView\|OnboardView" frontend/src` returns nothing except the redirects (which reference paths, not the view files). Delete their `__tests__` specs too.
- [ ] **Gates; Commit** `feat(nav): repurpose Settings/Board/Tools + WorktreesView, remove folded views`.

---

### Task 6: OnboardWizard (blocking first-launch) + AppShell mount

**Files:** Create `frontend/src/components/OnboardWizard.vue`; Modify `frontend/src/components/AppShell.vue`; Test `frontend/src/components/__tests__/OnboardWizard.spec.ts`, extend `AppShell.spec.ts`.

- [ ] **`needsOnboarding`** (computed, in AppShell or a small composable): `connections.length === 0 || activeWorkspaceId == null`, from the existing connections + workspaces stores. `skipped` = `localStorage.getItem('hephaestus.onboarding.skipped') === '1'`.
- [ ] **AppShell:** `<OnboardWizard v-if="needsOnboarding && !skipped" data-test="onboard-wizard" />` as a full-screen overlay; when `needsOnboarding && skipped`, show a dismissible banner (`data-test="onboard-banner"`) with a "Настроить" button that clears the skip flag.
- [ ] **OnboardWizard:** 3 steps (`data-test="wiz-step-1|2|3"`):
  1. `<ConnectionsManager>`; "Далее" (`data-test="wiz-next-1"`) disabled until ≥1 connection `status==='connected'`.
  2. engines panel (`getClis()`), informational; "Далее" always enabled.
  3. repo-path input → `ws.onboard(repoPath)` (reuse OnboardView's flow); "Готово" (`data-test="wiz-done"`) disabled until a workspace is active. On done the overlay unmounts reactively.
- [ ] **Specs:** wizard shows when `needsOnboarding`; `wiz-next-1` disabled with 0 connected, enabled with 1 connected; `wiz-done` disabled with no active workspace; clicking "Пропустить" (`data-test="wiz-skip"`) sets the flag and renders the banner. **Step 2 FAIL → 3 implement → 4 PASS → gates; Commit** `feat(onboarding): blocking first-launch wizard + skip banner`.

---

### Final: end-to-end verification

- [ ] Full gates green (backend + frontend; remember `vue-tsc -p tsconfig.app.json`).
- [ ] **Live (verify skill):** start the backend with a throwaway `HEPHAESTUS_LOOP_HOME` (empty store) → open `/board` → the wizard blocks; connect a provider (use an existing key) → step through to onboard a repo → wizard disappears and the **5-tab** shell shows; confirm GitHub/GitLab settings still load and there is **no** autofix/changelog UI anywhere; confirm an old URL (`/config`) redirects to `/agents`. Capture evidence.
- [ ] Finish branch per superpowers:finishing-a-development-branch (merge `feat/onboarding-tabs` → master).
- [ ] Migration note: existing users (with connections + a workspace) skip the wizard automatically (`needsOnboarding=false`); deep-links to old routes redirect.
```
