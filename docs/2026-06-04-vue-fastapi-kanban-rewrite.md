# HEPHAESTUS Vue + FastAPI Kanban rewrite — master plan

**Дата:** 2026-06-04
**Версия:** v1 (синтез 4 параллельных research-агентов)
**Целевая инфраструктура:** `c:/Users/starsinc/Desktop/hephaestus-autonomous-loop/` (он же `/home/starsinc/hephaestus-autonomous-loop/` на хосте 192.168.0.103)
**Срок:** 4 недели до Phase 5, Phase 6 опционально

---

## 0. Цель и почему сейчас

HEPHAESTUS-loop сейчас — два монолита: `dashboard/server.py` (1811 строк stdlib `ThreadingHTTPServer`, смешано всё: HTTP-routing, парсинг JSONL, git-интроспекция, tmux-контроль, ~40 эндпойнтов) и `dashboard/index.html` (2617 строк HTML + 50 KB CSS + ~2200 строк inline vanilla-JS строящего DOM через хелпер `mk()`). Оркестрация — bash (`driver.sh` 340 строк + `tier-review.sh` 432 + `lib/common.sh` 179) с явными `set +e`/`set -e` границами вокруг каждого opencode-вызова. Дашборд опрашивает `/api/state` каждые 3 секунды через `setInterval(tick, 3000)`, ре-сериализуя всё состояние независимо от активной вкладки. Авторизации нет — только `HOST=127.0.0.1` по умолчанию, в LAN-режиме `0.0.0.0` без токена.

Не переписывать — можно. Loop работает, отгружает таски в `github.com/Dmitzoc/dt` каждый день, вчера ушли C-P0-2 и C-P0-5. Но каждая новая фича сейчас дерётся с inline-DOM-хелперами и bash-control-flow, а оператор с телефона не получит ничего. Рерайт даёт: Kanban-доску с drag-n-drop, real-time через WebSocket (вместо 3-секундного опроса), per-task drawer с tabs (агенты/инструменты/diff/ревью/решения), нормальную авторизацию, mobile-layout, и Python-оркестратор с тестируемой FSM (вместо bash + `set +e`).

---

## 1. Locked architectural decisions

Эти решения **не обсуждаются** — все 3 проектных агента пришли к одинаковым выводам.

### Frontend
- **Vue 3** Composition API only, **TypeScript** обязательно
- **Pinia** для state (5 stores: board / task / loop / config / toast)
- **Vue Router 4** history mode; task-drawer как named child route поверх `/board`
- **Vite 6** сборщик; dev-server с proxy на `:8765` (`/api`) и `:8765/ws` (WebSocket upgrade)
- **Tailwind v4** + custom design-token layer (мапим существующие CSS-vars `--bg`, `--panel`, `--primary: #faff69`)
- Никаких UI-библиотек (PrimeVue/Vuetify/Element Plus отвергнуты; тёмно-терминальный aesthetic дешевле построить руками)
- HTTP: native `fetch` в типизированной обёртке `useApi()`
- **WebSocket** для real-time (НЕ SSE) — single connection multiplexed по taskId
- **Только русский язык** (preserve `STATUS_RU/VERDICT_RU/PHASE_RU/...` из `index.html:704-723`)
- Только тёмная тема

### Backend
- **FastAPI** на **Python 3.12**, **uvicorn single worker** (НЕ `--workers N` — single-process FSM, in-process WS fan-out, in-process LKG cache)
- **Pydantic v2** для всех моделей, `extra='allow'` на `Item` (чтобы не падать на полях которые bash-сторона ещё пишет)
- **Без uvloop** (узкое место — диск/subprocess, не event-loop)
- **JSON-on-disk + flock** для state (НЕ SQLite до Phase 3+; flock-контракт с bash должен сохраняться)
- **WebSocket** rooms через `ConnectionManager` с bounded queues per-subscriber
- **`asyncio.TaskGroup`** для 6+2+1 ревью fan-out
- **`asyncio.timeout()`** context manager вокруг каждого subprocess-вызова
- **`aiofiles`** для async-disk
- **`watchfiles`** (с fallback на 200ms polling) для tail-follow JSONL потоков
- **Оркестратор = отдельный процесс** под systemd (НЕ asyncio.Task внутри FastAPI), коммуникация через state-файлы + сигналы

### Контракт совместимости (load-bearing)
- `state/.work-state.lock` — POSIX `flock(LOCK_EX)`, Python `fcntl.flock`, bash `flock -x 9`. **Никаких** Python-`Lock` или `asyncio.Lock` поверх — bash их не видит
- `state/work-state.json` поля — **camelCase** (`lastIter`, `previousBranches`, `selfReportedFailure`). Pydantic пишет с `by_alias=True`
- `state/current.json` — `{updatedAt, itemId, phase, detail}`
- `state/decisions.log` — TSV `ts \t actor \t action \t branch \t result \t extra`
- Атомарная запись: tmp + fsync + `os.replace()` (никогда прямо в финальный путь)
- `ALLOWED_CONFIG_KEYS` allowlist — байт-в-байт из `server.py:57-68` (защита от shell-injection через config-override → tmux env)
- `_is_safe_auto_branch()` — байт-в-байт из `server.py:1435-1445`

---

## 2. Что сохраняем без изменений

Эти файлы переписывать **нельзя** — tuned over the past 10 days и менять их = ломать поведение агентов или контракт с bash-стороной:

- `prompts/system-prefix.md` — 64-line task brief с locked decisions + `HEPHAESTUS_RESULT_BEGIN/END` schema
- `prompts/review-tier1.md`, `review-tier2.md`, `review-final.md` — review prompts
- `prompts/scan-mapper.md`, `scan-reducer.md` — map-reduce scan
- `lib/parse-result-block.py`, `lib/extract-plan-section.py`, `lib/build-previous-attempt.py` — маленькие, корректные. Phase 4 Python-orchestrator вызывает их через subprocess
- `verify.sh` — 51 строка bash, не выигрываем переписывая
- `tier-review.sh` — оставить до Phase 6+. Параллелизм 6 background-shells проще Python-эквивалента
- `dashboard/server.py:405-471` — `_summarize_event`: defensive multi-shape JSONL parsing. Battle-tested, **порт verbatim** в `backend/app/core/events.py`
- `dashboard/server.py:235-301` — `_sum_usage` + `_iter_cost`. **Порт verbatim**

---

## 3. Целевая архитектура — backend

### Структура

```
backend/
├── app/
│   ├── main.py              # FastAPI factory, lifespan, router register, CORS/CSRF middleware
│   ├── config.py            # pydantic-settings + ALLOWED_CONFIG_KEYS allowlist
│   ├── api/v1/
│   │   ├── tasks.py         # /tasks, /tasks/{id}, POST/PATCH/DELETE, move-top, requeue
│   │   ├── iters.py         # /iters, /iters/{id}/{diff,verify,reviews,cost,raw,tools,streams,event}
│   │   ├── loop.py          # /loop GET, /loop/{start,stop,kill} POST
│   │   ├── config.py        # /config GET PUT, /config/preset POST
│   │   ├── scans.py         # /scans, /scans/{id}/results, /scans/{id}/import, /scans/start
│   │   ├── branches.py      # /branches, /branches/{name}/{merge,requeue,discard}
│   │   ├── decisions.py     # /decisions
│   │   └── state.py         # /state (backward-compat snapshot до Phase 2)
│   ├── api/ws/
│   │   ├── loop.py          # WS /ws/loop — driver-status changes
│   │   ├── iter.py          # WS /ws/iter/{id} — JSONL tail proxy
│   │   └── board.py         # WS /ws/board — item status delta
│   ├── core/
│   │   ├── state.py         # _StateLock (fcntl.flock), _atomic_write, _read_state, _write_state, _LKG_STATE
│   │   ├── events.py        # _summarize_event, _parse_events, _sum_usage, _iter_cost (порт verbatim)
│   │   ├── git.py           # _git_branches, _is_safe_auto_branch, branch actions
│   │   └── decisions.py     # _append_decision, _read_decisions
│   ├── orchestrator/
│   │   ├── fsm.py           # OrchestratorFSM (asyncio state machine)
│   │   ├── review.py        # TierReviewRunner (TaskGroup для 6+2+1)
│   │   ├── result_parser.py # порт lib/parse-result-block.py как модуль
│   │   ├── prompt_builder.py# порт prompt-build.sh
│   │   └── process.py       # run_opencode() coroutine, stream-to-disk + WS-tail
│   ├── services/
│   │   ├── scan.py          # scan-start (tmux bridge в Phase 1→2), list, results, import
│   │   ├── agent_activity.py# граф per-task (не глобальный)
│   │   └── broadcast.py     # ConnectionManager: rooms → set[WebSocket]
│   ├── models/domain.py     # Pydantic: Item, Iter, Stream, Verdict, FinalDecision, Scan, Decision, Branch, Cost
│   └── schemas/responses.py # Response envelopes
├── tests/
│   ├── unit/                # test_fsm, test_state, test_events
│   ├── contract/            # test_state_roundtrip (читает реальный state/work-state.json)
│   └── e2e/                 # test_opencode_stub
├── Dockerfile
├── pyproject.toml
└── .env.example
```

### Доменная модель (Pydantic) — критичные поля

```python
class Item(BaseModel):
    model_config = ConfigDict(extra='allow', populate_by_name=True)
    id: str
    title: str
    status: str  # НЕ Literal — failed:X варианты не enumerable
    attempts: int = 0
    proposal: str = ""
    why: str = ""
    acceptance: str = ""
    touches: list[str] = []
    branch: str | None = None
    last_iter: str | None = Field(None, alias="lastIter")
    previous_branches: list[str] = Field(default_factory=list, alias="previousBranches")
    commit: str | None = None
    plan_file: str = ""
    plan_section: str = ""
    wave: str = ""
    severity: str | None = None
    category: str | None = None
    source_scan: str | None = None
    self_reported_failure: bool = Field(False, alias="selfReportedFailure")
    requeued_at: datetime | None = None
    review: str | dict | None = None  # str OR rich dict в зависимости от пути установки
    merge_commit: str | None = Field(None, alias="mergeCommit")
    merged_at: datetime | None = Field(None, alias="mergedAt")
```

Полный список моделей (Iter, Stream, Verdict, FinalDecision, Scan, Decision, Branch, Cost) — в `backend/app/models/domain.py`, схемы согласованы с `state/iter-NNNN/` файлами.

### Orchestrator FSM

```
IDLE → PREFLIGHT → PROMPT_BUILD → OPENCODE → VERIFY → COMMIT → PARSE_RESULT
                                                                    ↓
            ┌─────── needs_revision (verify_status:red) ─────────────┤
            │                                                         │
        TIER_REVIEW (rc 0/1/2/10+) → CLEANUP → IDLE                  │
            │                                                         │
            └─── failed:refused ────────────────────────────────────→ ┘
```

Каждое состояние — `async def` метод. Транзишены пишут в `state/current.json` через тот же `set_current()`, что WS `/ws/loop` tail-читает. Никакого in-process IPC между FastAPI и orchestrator — только state-файлы.

**Сигналы:** `state/stop` (soft, оба читают) + SIGTERM на `state/orchestrator.pid` (hard). `POST /loop/stop` `touch state/stop`. `POST /loop/start` SIGUSR1 на orchestrator чтобы разбудить из idle-sleep.

### opencode subprocess

Использовать `asyncio.create_subprocess_exec`, передать prompt через stdin, stream stdout одновременно на диск (`aiofiles`) и в `tail_buffer: deque(maxlen=80)`. Каждая линия → `progress_cb(line)` для non-blocking WS fan-out. Wrap всё в `asyncio.timeout(timeout_sec)`; on TimeoutError → `proc.terminate()` + `proc.wait()` → return -1.

Среда наследуется (`os.environ`) — нужны `SSH_AUTH_SOCK`, `HOME`, `PATH`, `ALL_PROXY`. **Никогда** `env={}`.

### Tier-review parallelism

`asyncio.Semaphore(int(os.environ.get("HEPHAESTUS_TIER1_PARALLEL_CAP", "6")))` обёрнут вокруг каждого `run_reviewer`. `asyncio.TaskGroup` для fan-out 6 параллельных tier-1 reviewers. Каждый reviewer wrapped в `asyncio.timeout(REVIEW_TIMEOUT_SEC)` — на timeout task бросает `TimeoutError`, TaskGroup cancel'ит остальные. FSM ловит `ExceptionGroup` → `failed:review-error`.

**HEAD-snapshot guard** (порт `tier-review.sh:193-214`): до/после каждого reviewer запоминаем `git rev-parse HEAD` и `git status --porcelain | wc -l`. Если изменилось — `git reset --hard <before-sha> && git clean -fd`, синтетический verdict `parse_error: "reviewer-mutated-tree"`, продолжаем pipeline.

**Thresholds** (`tier-review.sh:372-405`): tier-1 short-circuit при `approve_count < 5/6`; tier-2 при `< 2/2`. Финал-reviewer вызывается только если оба tier'а прошли.

### WebSocket strategy

3 эндпойнта:
- `/ws/loop` → broadcast на phase-transition (FSM пишет `current.json` → broadcaster читает)
- `/ws/iter/{id}` → snapshot-on-connect (last 80 events через `_parse_events`) + tail JSONL через `watchfiles` или 200ms polling
- `/ws/board` → background task polls `_state_version` каждые 500ms, diff items[] vs cached snapshot

`ConnectionManager`: rooms → set[WebSocket], per-subscriber bounded `asyncio.Queue(maxsize=100)`, drop-oldest на overflow. Single tailer task для JSONL → bounded queue → fan-out.

**Heartbeat:** server `{type:"ping"}` каждые 15s, client `{type:"pong"}`. Нет pong за 30s → disconnect.

**Reconnect:** client отправляет last received `idx`; backend replay'ит с этого индекса.

### Auth

`HEPHAESTUS_DASHBOARD_PASSWORD` env var. Если unset — loopback enforcement (non-loopback IP → 401). Если set — `Authorization: Bearer <password>` ИЛИ session cookie `hephaestus_session=<argon2(password)>`. `POST /auth/login` устанавливает cookie. CSRF: Origin/Referer matching Host. Никаких JWT/OAuth.

---

## 4. Целевая архитектура — frontend

### Структура

```
frontend/
├── src/
│   ├── App.vue
│   ├── main.ts
│   ├── router.ts
│   ├── api/
│   │   ├── client.ts        # useApi() + types из openapi-typescript
│   │   └── ws.ts            # useWebSocket() с exponential backoff
│   ├── stores/
│   │   ├── board.ts
│   │   ├── task.ts
│   │   ├── loop.ts
│   │   ├── config.ts
│   │   └── toast.ts
│   ├── composables/
│   │   ├── useFormatting.ts
│   │   ├── useKeyboardShortcuts.ts
│   │   ├── useAutoscroll.ts
│   │   └── useConversationState.ts
│   ├── views/
│   │   ├── BoardView.vue
│   │   ├── ScanView.vue
│   │   ├── ConfigView.vue
│   │   ├── BranchesView.vue
│   │   ├── HistoryView.vue
│   │   └── LogsView.vue
│   ├── components/
│   │   ├── AppShell.vue
│   │   ├── KanbanBoard.vue + KanbanColumn.vue + TaskCard.vue
│   │   ├── TaskDrawer.vue + DrawerHeader.vue + DrawerTabs.vue
│   │   ├── panes/{Description,Iterations,Activity,Tools,Diff,Reviews,Agents}Pane.vue
│   │   └── shared/{ConversationRenderer,DiffViewer,ToolRow,ReviewCard,AgentGraph,IterChip,StreamChip}.vue
│   ├── i18n/ru.ts
│   ├── styles/tokens.css
│   └── types/api.ts         # openapi-typescript из FastAPI schema
├── vite.config.ts
├── tailwind.config.ts
├── tsconfig.json
└── package.json
```

### Routes

```
/board                        — Kanban board (default)
/board/task/:id               — Task drawer ПОВЕРХ /board (named child route)
/board/task/:id/iter/:dir     — deep-link на конкретную итерацию в drawer'е
/scan/:dir                    — full-page scan results (НЕ drawer)
/config | /history | /branches | /logs
```

Drawer как named-child важен: (a) пользователь видит контекст доски пока смотрит задачу, (b) URL deep-linkable, (c) `router.back()` восстанавливает scroll.

### Kanban колонки

`pending` → `in_progress` (max 1 карточка) → `needs_revision` → `done` (одобрено ревью, ждёт merge) → `merged` → `failed` (collapsed by default).

**Drag-n-drop:** **только** внутри `pending` для reorder (`POST /tasks/:id/move-top`). Перетаскивание в другую колонку **отключено** — статусы agent-driven.

Карточка: id-chip (yellow mono), title (clip 2 lines), status-border-color, severity-chip, last iter dir, agent name если `in_progress`, pulse-dot если running.

### Task drawer — 7 tabs

1. **описание** — static metadata
2. **итерации** — IterChip grid + per-iter cost summary
3. **активность** — ConversationRenderer (step-grouped events), live через WS если `in_progress`
4. **инструменты** — StreamChip selector + tool history (lazy-load, cache в task store)
5. **диф** — DiffViewer (порт `renderUnifiedDiff` + `filterDiffLines` из `index.html:1693-1751`), syntax-highlight, copy, search
6. **ревью** — verdict cards grouped by tier + final decision плашка
7. **агенты** — per-task SVG agent graph

Lazy-load: на open drawer → fetch `/api/v1/tasks/:id` (cheap aggregate). Tools/Diff/Reviews fetch при первом активации вкладки. Activity tab subscribes WS room сразу если `status==='in_progress'`.

### Real-time через WebSocket

Один WS-connection per browser, multiplexed. Client → server: subscribe/unsubscribe/ping. Server → client: snapshot/event_append/state_delta/pong/heartbeat.

**Backpressure:** activity-pane paused → composable получает messages, буферит в `pendingEvents` (cap 500). На unpause flush в `nextTick`. Cap превышен → "N событий пока на паузе — обновить".

**Reconnect:** exponential backoff 1s → 2s → 4s, cap 30s. Re-subscribe + last received `idx`.

### Pinia stores

- **useBoardStore** — items, summary, current, filter
- **useTaskStore** — views Map, caches, activeDrawerTaskId, activeDrawerIter
- **useLoopStore** — driverStatus, killswitchPresent, scanRunning
- **useConfigStore** — effective, overrides
- **useToastStore** — toasts[], auto-expire 5.5s

`useConversationState(taskId)` — factory composable backed by Map keyed by taskId.

### Accessibility

- `g+letter`: `g t / g n / g b / g h / g s / g c / g l` — preserve verbatim
- `Escape` → close drawer (`router.back()`)
- Kanban: `role="grid"` / `role="row"` / `role="gridcell"` + roving tabindex
- Focus management: drawer open → close-button; drawer close → возврат на карточку
- `prefers-reduced-motion` → disable все pulse-анимации

---

## 5. Контракт совместимости (Phase 1-3)

Bash-driver и новый Python-бэкенд читают/пишут одни и те же файлы под `state/`:

1. **Lock file** `state/.work-state.lock` — POSIX `flock(LOCK_EX)`. Python: `fcntl.flock`. Bash: `flock -x 9` на FD 9
2. **Atomic writes** — tmp-file + `f.flush()` + `os.fsync(f.fileno())` + `os.replace()`. Никогда прямо в финальный путь
3. **camelCase в work-state.json** — `lastIter`, `previousBranches`, `selfReportedFailure`, `mergeCommit`, `mergedAt`. **Pydantic пишет с `by_alias=True`** обязательно
4. **current.json format** — `{updatedAt, itemId, phase, detail}`
5. **decisions.log format** — TSV с `\t` разделителями, append-only
6. **iter-NNNN/ файлы** — оставить как есть (file-system). НЕ мигрировать в БД. Pydantic только метаданные (`Iter` модель) для rollup
7. **REFUSED short-circuit** — `summary` starts with `"REFUSED "` → skip review, `failed:refused` (`driver.sh:252-257`)
8. **verify_status:red short-circuit** — `result.json.verify_status == "red"` → skip review, `needs_revision`, `selfReportedFailure=true` (`driver.sh:259-272`)
9. **HEAD-drift detection** — после каждого opencode-вызова `ensure_on_branch(BRANCH)`
10. **Self-commit detection** — `WT_DIRTY=0 && BRANCH_AHEAD>0` → `SELF_COMMIT=1`, не делаем `git add`+`commit` (агент уже сделал коммит через Bash tool). См. `driver.sh:165-178`

---

## 6. Фазы

**Каждая фаза: ~3 дня (Phase 1 и 4 — 5 дней), exit criteria, rollback action. Loop никогда не offline >30 минут.**

### Phase 0 — Freeze + scaffolding (2-3 дня) **[DONE 2026-06-04]**

**Goal:** подготовить без disruption.
**Scope:**
- `backend/` и `frontend/` siblings к `dashboard/`
- pin Python 3.12 / FastAPI / uvicorn / Pydantic v2 / httpx / aiofiles / watchfiles в `backend/pyproject.toml`
- pin node 22 / pnpm 10.30.3 / vue@3.5 / vite@6 / pinia@2 / vue-router@4 в `frontend/package.json`
- CI: ruff + mypy --strict + pytest + vitest на каждый commit
- **Контрактный тест Phase 0:** загрузить весь существующий `state/work-state.json` в `Item.model_validate(it)` — fail CI если что-то отвергается
- Snapshot opencode-version в `state/runtime-versions.json`

**Exit:** scaffolding на main, loop continues shipping items overnight.
**Rollback:** `rm -rf backend/ frontend/` — production paths не трогали.

### Phase 1 — FastAPI proxy of legacy server (5 дней)

**Goal:** замена `dashboard/server.py` byte-for-byte на HTTP-layer; `index.html` всё ещё static.
**Scope:**
- Порт `_read_state`/`_write_state`/`_StateLock`/`_LKG_STATE`/`_atomic_write` в `backend/app/core/state.py`
- Порт `_summarize_event`/`_parse_events`/`_sum_usage`/`_iter_cost` в `backend/app/core/events.py` **verbatim**
- Порт 40 эндпойнтов из `server.py` в FastAPI routers
- Serve `dashboard/index.html` from `/` untouched
- Сохранить tmux session names (`hephaestus-loop`, `hephaestus-scan`)
- `start-dashboard.sh:12` swap: stdlib server → uvicorn

**Exit:** старый UI в браузере работает идентично; A/B smoke на adjacent ports (legacy 8765, new 8766) — diff ответов на корпусе из 50 запросов = пусто.
**Rollback:** revert `start-dashboard.sh`; старый `server.py` нетронут на диске.

### Phase 2 — Vue Kanban behind feature flag (3 дня)

**Goal:** ship новый UI без удаления старого.
**Scope:**
- `frontend/` Vue 3 + Pinia + Tailwind + TypeScript
- `pnpm run build` → `backend/static/v2/`, served at `/?ui=v2` (или cookie `hephaestus_ui=v2`)
- Default route всё ещё `dashboard/index.html`
- Kanban с 6 колонками + Task drawer с 7 sub-tabs
- Использует существующие эндпойнты

**Exit:** flipping `?ui=v2` показывает Kanban; same backend serves both.
**Rollback:** убрать cookie/query — bookmarks → старый UI.

### Phase 3 — WebSocket live updates (3 дня)

**Goal:** убить 3-секундный poll.
**Scope:**
- `WS /api/v1/ws/state` broadcast snapshots при `_write_state`
- `WS /api/v1/ws/iter/{id}` tail-follow `output.primary.jsonl` через `watchfiles` (+ 200ms polling fallback)
- `WS /api/v1/ws/board` — diff items[] vs cached snapshot
- ConnectionManager с rooms + per-subscriber bounded queues + drop-oldest
- REST `/api/v1/state` остаётся как poll fallback

**Exit:** browser refresh во время running iter показывает live step state ≤500ms p95.
**Rollback:** Vue feature-flag `live=0` → polling; backend WS endpoint оставить.

### Phase 4 — Python orchestrator (5 дней — highest risk)

**Goal:** порт `driver.sh` → `backend/app/orchestrator/fsm.py`.
**Scope:**
- `OrchestratorFSM` (asyncio FSM) — все состояния из section 3
- `process.run_opencode()` через `asyncio.create_subprocess_exec` + `asyncio.timeout`
- `TierReviewRunner` с `asyncio.TaskGroup` для 6+2+1 fan-out
- `ResultParser` (порт `lib/parse-result-block.py`)
- `PromptBuilder` (порт `prompt-build.sh`)
- HEAD-snapshot guard для reviewer mutations
- REFUSED + verify_status:red short-circuits
- Self-commit detection
- Separate process под systemd unit `hephaestus-orchestrator.service`

**Critical test before enabling в проде:**
- pytest: spawn bash `_with_state_lock sleep 5` + Python `_StateLock().__enter__()` → Python blocks ~5s. Если не блокирует — flock-контракт нарушен, **не enable Phase 4 в проде**

**Parallel-run:** **48 часов** обе версии. Bash в `hephaestus-loop` tmux, Python в `hephaestus-loop-py` tmux. После 10 последовательных iter через Python → cutover.

**Exit:** 10 iters через Python end in `done` без жалоб; lock-contract test зелёный.
**Rollback:** `start-loop.sh:27 exec bash ./driver.sh` — failsafe; `hephaestus-loop-bash-warm` keeps bash warm.

### Phase 5 — Auth + HTTPS + удаление legacy UI (3 дня)

**Goal:** production-grade access control.
**Scope:**
- Shared password gate (`HEPHAESTUS_DASHBOARD_PASSWORD`), argon2 hash, `itsdangerous` signed cookie
- `POST /api/v1/auth/login` body `{password}` → set `hephaestus_session` httponly cookie
- Caddy reverse-proxy на `:443` с Let's Encrypt (или LAN-only self-signed cert)
- Удалить `dashboard/index.html`, `dashboard/server.py` (keep в git history)

**Exit:** `https://<host>/` требует login; `:8765` закрыт.
**Rollback:** revert Caddy config; emergency `:8765` LAN listener первую неделю.

**Communicate operator one phase ahead:** новый URL + password.

### Phase 6 (опционально) — Multi-host / multi-repo (3-5 дней)

`repos` table в SQLite, per-repo `state/<repo-id>/`, repo selector в Kanban header. Skip until second target real.

---

## 7. Acceptance criteria — 10 testable checkpoints

1. **End-to-end без bash.** Item flows `pending → in_progress → done` и landing commit на `auto/<id>-<sha>` без `driver.sh`
2. **State file round-trips.** SIGTERM FastAPI mid-iter → restart → queue intact, JSON valid, next pending identifiable
3. **WebSocket p95 < 500ms.** Время от append к `output.primary.jsonl` до browser receiving event под 10 events/s
4. **3 concurrent reviewers ≤ 8GB RAM.** Orchestrator + WS fan-out under 8GB resident на 192.168.0.103
5. **Lock contract verified.** 1-min тест: bash `mark_item` и Python `_write_state` 100 раз interleaved → no lost writes, no corruption
6. **No 3-sec poll.** `grep -r "setInterval.*3000" frontend/` → 0 hits; live = WS; REST = fallback
7. **Browser refresh во время running iter** показывает live step state из broadcaster (НЕ stale snapshot)
8. **Mobile Kanban работает** на 390px viewport — drag-to-move-top touch, current-iter strip readable
9. **Auth blocks LAN.** `curl http://192.168.0.103:8765/api/v1/state` → 401; только authed browsers
10. **Schema drift logged, не crashed.** Bash инжектит never-seen field → FastAPI serves, Vue ignores, `state/schema-drift.log` пишет. No 500

---

## 8. Top-5 рисков + митигации

1. **Lock-protocol divergence в Phase 4.** Python `fcntl.flock` и bash `flock -x 9` не видят друг друга → race → corruption.
   **Mitigation:** Phase 0 pytest spawn'ит bash + Python interleaved → assert blocking. Этот тест gate'ит Phase 4.

2. **C-P0-2/C-P0-5 follow-ups теряются при миграции.** Вчерашние merge'и оставили follow-ups что ещё не в `plan-items.json`.
   **Mitigation:** перед Phase 0 — `git log --since=2026-06-03` + grep `follow_ups:` в `state/iter-NNNN/result.json` → захватить в queue.

3. **Operator muscle-memory `g+letter` shortcuts.** Если Vue не сохранит — оператор misclicks неделю.
   **Mitigation:** `useKeyboardShortcuts` composable day 1 of Phase 2; mapping `g t/n/b/h/s/c/l` byte-for-byte.

4. **Vue dev-server CPU на loop host.** `pnpm dev` на 192.168.0.103 конкурирует с loop за CPU; может вызвать `pnpm test` timeout (900s cap).
   **Mitigation:** Vue dev на developer-workstation only; ship prebuilt `dist/` на хост.

5. **Dashboard log как единственный debug trail.** Если FastAPI swallow'нет exception в WS-task — silent failure часами.
   **Mitigation:** `logging.basicConfig` рано в `state/backend.log` + `state/backend-error.log`; `loop.set_exception_handler` логирует unhandled task exceptions; structured JSON logs.

---

## 8.1 Lessons Learned — Phase 0

- **Python version:** Workstation had Python 3.11/3.13, not 3.12. Relaxed `requires-python` to `>=3.11` — no code changes needed since `from __future__ import annotations` covers union syntax.
- **Package layout:** Python package is `app` (not `backend.app`) — pytest runs from `backend/` cwd. All imports use `from app.X import Y`.
- **Pydantic datetime:** `merged_at=datetime(...)` serializes to datetime object, not string. Tests must compare types, not string literals.
- **ruff --fix:** Caught 7 issues (unused imports, import sorting, `contextlib.suppress` suggestion). Always run `--fix` before commit.
- **Lock contract tests:** Skip on Windows (no fcntl). Will gate Phase 4 on Linux CI green.
- **Commit SHA:** `52c346d` on `master` at `github.com:starsinc1708/HEPHAESTUS.git`

---

## 9. Timeline

| Phase | Календ. недели | Cumulative |
|------:|----------------|------------|
| 0 | 0.5 (3 дня) | 0.5 wk |
| 1 | 1.0 (5 дней) | 1.5 wk |
| 2 | 0.5 (3 дня) | 2.0 wk |
| 3 | 0.5 (3 дня) | 2.5 wk |
| 4 | 1.0 (5 дней, parallel-run + bake) | 3.5 wk |
| 5 | 0.5 (3 дня) | 4.0 wk |
| 6 | 1.0 (опционально) | 5.0 wk |

**4 календарные недели** до shippable rewrite (Phases 0-5), loop never offline >30 min.

---

## 10. Что НЕ переписывать (explicit no-touch)

- Все `prompts/*.md`
- `lib/parse-result-block.py`, `lib/extract-plan-section.py`, `lib/build-previous-attempt.py` (вызываем через subprocess)
- `verify.sh`
- `tier-review.sh` (до Phase 6+; Python TaskGroup-эквивалент будет в Phase 4 но bash остаётся fallback)
- HEPHAESTUS_RESULT block в `prompts/system-prefix.md:54-60` (byte-for-byte)
- `ALLOWED_CONFIG_KEYS` allowlist
- `_is_safe_auto_branch()` regex
- `oh-my-openagent` integration (известный issue с "default" — surface + log + move on)
- Тёмная palette с neon yellow `--primary: #faff69`

---

## Источники

Этот план — синтез 4 параллельных research-агентов от 2026-06-04:
- Agent 1 (code-explorer): inventory — domain model, бизнес-правила в bash, integration points, FSM, HTTP API surface, fragile spots
- Agent 2 (code-architect, Vue): Vue 3 + Pinia + Tailwind v4 design, 30-component tree, WS strategy, accessibility
- Agent 3 (code-architect, FastAPI): Python 3.12 + FastAPI design, Pydantic models, REST API, orchestrator FSM, opencode subprocess, WS rooms, deployment
- Agent 4 (general-purpose): migration phases, rollback story, risks, acceptance, timeline
