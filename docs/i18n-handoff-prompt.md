# Task: finish the HEPHAESTUS frontend i18n (en/ru) migration

The HEPHAESTUS frontend (`frontend/`, Vue 3 + `<script setup>` + Pinia + TypeScript) is
being migrated from Russian-only to bilingual **en/ru** using **vue-i18n**. The
infrastructure and the high-traffic screens are already done. Your job is to
migrate the **remaining screens, components, and stores** to the same pattern,
committing per-surface, with all gates green.

Default UI locale is **ru** (unchanged behaviour); English is opt-in via a RU/EN
toggle and persists in `localStorage`. So the visible default must stay identical
to today — you are only adding the ability to switch to English.

---

## 1. How the i18n system works (already built — don't rebuild it)

- Setup: `frontend/src/i18n/index.ts` — `createI18n({ legacy: false, globalInjection: true, locale: savedLocale(), fallbackLocale: 'en', messages: { ru, en }, pluralRules: { ru: russianPlural } })`. Exposes `i18n`, `setLocale()`, `savedLocale()`, `russianPlural()`.
- Catalogs: `frontend/src/i18n/locales/ru.ts` and `locales/en.ts` — plain objects, **grouped by surface namespace** (`nav`, `shell`, `wizard`, `board`, `status`, `kanban`, `taskCard`, `drawer`, `settings`, `connections`, `integrations`, …). The two files MUST have **identical key trees** — there is a parity test that fails otherwise.
- Test wiring: `frontend/src/test/setup.ts` installs i18n on every `@vue/test-utils` mount and **pins the locale to `ru` before each test**. So existing specs that assert Russian text keep passing — which means **your ru translations must reproduce the original Russian wording exactly** (e.g. a test does `expect(btn.text()).toContain('Стоп')`).

Study these reference commits to see the exact pattern (use `git show <sha>`):
- `c36a32e` — infra + nav + onboarding wizard
- `decd220` — board screen
- `aebfe53` — TaskDrawer cluster
- `4ad4c36` — settings cluster (incl. computed label arrays + store-free toasts)

## 2. The migration pattern (per file)

**In a component (`<script setup>`):**
```ts
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
```
Then replace every user-facing literal:
- Template text: `Сохранить` → `{{ t('settings.git.save') }}`
- Attributes: `placeholder="…"` → `:placeholder="t('…')"`; same for `:title`, `:aria-label`.
- Interpolation: `` `Репозиторий добавлен: ${name}` `` → `t('settings.repo.added', { name })` with message `'Репозиторий добавлен: {name}'`.
- Toasts / errors: `toast.add('error', \`Ошибка: ${msg}\`)` → `toast.add('error', t('x.error', { error: msg }))`.

**In a Pinia store** (outside component setup — `useI18n()` won't work):
```ts
import { i18n } from '@/i18n'
const t = i18n.global.t
// t('board.requeued', { id })
```

**Plurals** (Russian needs them; that's why vue-i18n was chosen):
- ru message: `'нет задач | {n} задача | {n} задачи | {n} задач'` (zero|one|few|many)
- en message: `'no tasks | {n} task | {n} tasks'`
- Call with the **count as the 2nd arg**, not a named param: `t('units.tasks', n)`. The count is available as `{n}`.

**Add every new key to BOTH `ru.ts` and `en.ts`** under a sensible namespace, identical structure.

## 3. Gotchas that have already bitten (read carefully)

1. **`t` shadowing.** Any `v-for="t in …"`, `.filter(t => …)`, `.map(t => …)`, or `const t = …` shadows the i18n `t` and breaks `t('key')` (vue-tsc error `Type 'String' has no call signatures`, or silently renders the loop item). **Rename the colliding variable** (`tpl`, `tg`, `x`, `label`, `titleText`, …). Grep each file for `\bt\b` before finishing it.
2. **Static arrays that use `t()` must become `computed`** so they re-render on locale switch — e.g. nav items, drawer TABS, `BASE_KEYS`. If you convert a `const X = [...]` to `computed(() => [...])`, update every script usage to `X.value`.
3. **Do NOT translate code comments.** Only user-facing strings: template text, placeholders, titles, aria-labels, option labels, toast/error messages. (Most of the leftover Cyrillic in already-migrated files is comments — leave it.)
4. **Toast `v-for` loop in AppShell** uses `t` as the loop variable; there we use the globally-injected `$t('…')` in the template instead. `$t` is available everywhere thanks to `globalInjection: true` — handy whenever `t` is shadowed in a template scope.
5. **Preserve exact Russian wording** in `ru.ts` for anything a test asserts (see §1). When unsure, copy the original string verbatim into `ru.ts`.

## 4. What's left to migrate (the actual work)

Counts are non-comment Cyrillic lines; group commits by surface. Suggested order = most-used first.

**A. Tools cluster** — `views/ToolsView.vue` (~95, the big one), `components/ScansPanel.vue` (10), `components/IdeasPanel.vue` (11), `components/InsightsChat.vue` (9), `components/ScopePicker.vue` (3), `components/ScopeNode.vue` (3)

**B. Agents/Run cluster** — `views/AgentsRunView.vue` (14), `components/AgentsRunControls.vue` (8), `components/AgentsScanConfig.vue` (12), `components/AgentsPromptsEditor.vue` (12), `components/AgentRolesPicker.vue` (12), `components/AgentRefEditor.vue` (4), `components/AgentListEditor.vue` (3), `components/RunTimeline.vue` (7), `components/LiveConsole.vue` (11)

**C. Worktrees** — `views/WorktreesView.vue` (~30)

**D. Conversation** — `views/ConversationView.vue` (9), `components/ConversationTree.vue` (10)

**E. Stores (toasts/errors — easy to miss, visible on every screen)** — `stores/board.ts` (13), `stores/config.ts` (4), `stores/task.ts` (2), `stores/conversation.ts` (2). Use `i18n.global.t` (see §2).

**F. Misc shared** — `components/LogsDrawer.vue` (4), `components/WorkspaceSwitcher.vue` (1), `components/HelpHint.vue` (1)

To re-scan and confirm what truly remains (filters out comment-only files), run:
```bash
cd frontend
for p in $(grep -rlE '[А-Яа-яЁё]' src --include=*.vue --include=*.ts | grep -vE '__tests__|/i18n/'); do
  grep -nE '[А-Яа-яЁё]' "$p" | grep -vE ':\s*//|:\s*\*' | grep -qE '[А-Яа-яЁё]' && echo "$p"
done
```
Then open each and translate only the user-facing strings.

## 5. Gates (run per surface before committing — ALL must pass)

```bash
cd frontend
npx vue-tsc -p tsconfig.app.json --noEmit      # MUST be clean. NOTE: bare `vue-tsc --noEmit` is a NO-OP (root tsconfig files:[])
npx vitest run                                  # currently 290 passing; ru is pinned so Russian assertions still pass
npx vite build
```
If a vitest assertion on Russian text fails, your `ru.ts` wording doesn't match the original — fix the catalog to match, don't change the test.

## 6. Commit + verify convention

- **One commit per surface** (Tools, Agents, Worktrees, Conversation, stores, misc). Keep them isolated and reviewable.
- Commit message: summary + what was migrated + "Gates: vue-tsc clean, vitest N, vite build clean." End with:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  ```
  Use `git commit -F <file>` or a quoted heredoc — commit bodies contain apostrophes/Cyrillic that break naive `-m` quoting.
- Push to `origin/master` after each (the repo is on `master`).

**Live-verify each surface in a real browser** (don't just trust tests):
```bash
# from repo root — backend serves API + the built SPA from frontend/dist
cd backend && ./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```
Open `http://localhost:8765`, navigate to the migrated screen, click the **EN** toggle (top-right), confirm the strings flip to English and back to RU. The server serves `frontend/dist` from disk per request, so after `vite build` the new bundle is live with no restart. (Playwright MCP tools work for automated checks.)

**Do NOT deploy to the 192.168.0.103 stand** — the user runs HEPHAESTUS locally only now.

## 7. Definition of done

Every user-facing string across Tools, Agents/Run, Worktrees, Conversation, the
four stores, and the misc shared components renders from the i18n catalogs;
`ru.ts`/`en.ts` key trees stay identical; toggling EN on each of those screens
shows English with no leftover Russian (comments excluded); vue-tsc/vitest/vite
build all green; each surface committed and pushed; each verified live in EN.
