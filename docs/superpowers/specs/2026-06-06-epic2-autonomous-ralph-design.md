---
title: HEPHAESTUS Epic 2 — Autonomous (NL-goal + Ralph mode + per-task model/complexity)
status: approved
date: 2026-06-06
audience: implementing engineer
language: prose=ru, identifiers/paths/commands=en
depends_on: [2026-06-05-universal-tool-overview-design]
defines_for: [epic2-autonomous-ralph-plan]
---

# Epic 2 — Autonomous: NL-goal + Ralph + per-task model/complexity

Закрывает фичу #1 («Autonomous Tasks: опиши цель → агенты планируют/реализуют/валидируют») и
автономность поверх существующего loop. Три связанные части. Решения, зафиксированные с пользователем:

- **D-e2-1.** Ralph при пустой очереди = **целенаправленное авто-пополнение** под стоящую цель (re-decompose).
- **D-e2-2.** Авто-сложность = **advisory** метка (декомпозер ставит); модель выбирает человек per-task (НЕ авто-маппинг).
- **D-e2-3.** Стоп-условия Ralph = **cost budget (USD)** + **max consecutive fails (enforce)** + **wall-clock**.
  Отдельного LLM goal-met детектора НЕТ — завершение goal-directed режима через «сухость»: пополнение
  возвращает пусто `N` раз подряд → стоп (неявный goal-met).

Существующее (НЕ ломать, переиспользовать): main-loop `fsm.run()` уже непрерывный (на пустой очереди спит,
не выходит); `decompose_proposals()` строит граф из proposals; `_scan_import` — паттерн «proposals → очередь +
merge граф-полей»; `AgentRunner.run_with_fallback(ws.agents, ...)`; `_iter_cost(iter_dir)` — стоимость итерации;
`PromptManager.render_prompt(template, vars)`; эвристический `POST /api/v1/repos/decompose` остаётся как есть.

---

## 1. Карта компонентов

| Часть | Артефакт | Статус |
|---|---|---|
| A | `Item.model_override: AgentRef \| None` (alias `modelOverride`), `Item.complexity: str \| None` в `domain.py` | правка |
| A | `_run_opencode` собирает эффективный `AgentsConfig` при `model_override` в `fsm.py` | правка |
| A | декомпозер emits `complexity` per task; merge в Item (scan_import + goal-import) | правка |
| A | UI: бейдж `complexity` в `TaskCard.vue`; селектор модели в `TaskDrawer.vue` | правка |
| B | `Goal` модель + `GoalStore` (`goals.json`) в `backend/app/core/goals.py` | новый |
| B | `plan_goal()` — goal text → proposals (LLM) → очередь → `decompose_proposals` в `goals.py` | новый |
| B | `prompts/goal-planner.md` (goal → proposals JSON) | новый |
| B | API `POST /api/v1/goals`, `GET /api/v1/goals`, `GET/DELETE /api/v1/goals/{id}` в `api/v1/goals.py` | новый |
| B | UI: «опиши цель» панель на доске (`GoalComposer.vue`) | новый |
| C | run-mode + бюджеты в `fsm.run()`; `RunSummary` (`run-summary.json`); replenish-петля | правка |
| C | `prompts/goal-replenish.md` (goal + done → next proposals) | новый |
| C | `DriverStartRequest` + `runMode/costBudgetUsd/wallclockSec/maxConsecFail`; threading в `driver._start_loop` | правка |
| C | config keys `HEPHAESTUS_RUN_MODE`, `HEPHAESTUS_COST_BUDGET_USD`, `HEPHAESTUS_WALLCLOCK_SEC` (+ enforce `HEPHAESTUS_MAX_CONSEC_FAIL`) | правка |
| C | UI: переключатель режима + бюджеты в панели запуска; прогресс прогона | правка |

**Границы юнитов.** `goals.py` (модель/стор/планирование) НЕ знает про FSM. FSM `run()` дополняется
RalphController (стоп-условия + replenish), который вызывает `goals.plan_goal`/`replenish_goal`. Per-task
override — точечная правка `_run_opencode`, не трогает воронку/verify.

---

## 2. Часть A — Per-task модель + сложность

### 2.1 Доменная модель (`domain.py`)
```python
    # additions to Item
    model_override: AgentRef | None = Field(None, alias="modelOverride")  # per-task implement agent
    complexity: str | None = None        # advisory: "simple" | "medium" | "complex" (decomposer-set)
```
`AgentRef` импортируется из `app.models.workspace`. `extra="allow"` уже стоит → frontend совместим.

### 2.2 FSM использует override (`fsm.py::_run_opencode`)
Сейчас: `runner.run_with_fallback(self._ws.agents, ...)`. Меняется на: если у item есть `model_override`,
собрать эффективный `AgentsConfig` с подменённым `primary`, сохранив остальные роли/fallback:
```python
agents = self._ws.agents
mo = item.get("modelOverride") or item.get("model_override")
if mo:
    eff = self._ws.agents.model_copy(update={"primary": AgentRef.model_validate(mo)})
    agents = eff
result = await runner.run_with_fallback(agents, prompt_file=prompt_file, cwd=..., iter_dir=..., timeout_sec=...)
```
Инвариант: при отсутствии override поведение байт-в-байт прежнее. `use_models` берётся из `agents.use_models`.

### 2.3 Сложность — advisory
Декомпозер (`scan-decomposer` и новый `goal-planner`) emits `complexity` ∈ {simple,medium,complex} per task.
Merge в Item при импорте (scan_import + goal-import): `it["complexity"] = g.get("complexity")`. НЕ влияет на
выбор модели автоматически (D-e2-2). UI рендерит бейдж; пользователь сам ставит `modelOverride`.
`decompose_proposals` дополняется: проносит `complexity` из LLM-tasks в выходные task-dicts (рядом с
`conflictGroup`/`orderIndex`), default `None`.

### 2.4 UI
- `TaskCard.vue`: маленький бейдж сложности (цвет по уровню), если есть.
- `TaskDrawer.vue`: селектор `modelOverride` (provider/model из доступных ws-агентов/моделей; «по умолчанию» = none) →
  `PATCH /api/queue/{id}` (существующий patch-эндпоинт принимает произвольные поля Item; добавить `modelOverride`
  в разрешённые к патчу поля, см. tasks.py).

---

## 3. Часть B — NL-вход «опиши цель»

### 3.1 Модель (`backend/app/core/goals.py`)
```python
class Goal(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str                                   # "goal-<8hex>" (deterministic from title+ts passed in)
    title: str
    description: str = ""
    status: str = "active"                    # active | done | abandoned
    task_ids: list[str] = Field(default_factory=list, alias="taskIds")
    created_at: str | None = Field(None, alias="createdAt")
    dry_rounds: int = Field(0, alias="dryRounds")   # consecutive empty replenishments (Ralph)
```
`GoalStore` — персист `<state>/goals.json` (`{"goals":[...]}`) под `_StateLock` + atomic write (как
`MergeJobStore` в Эпике 1). Методы: `list/get/put/active() -> list[Goal]` (status==active).

### 3.2 `plan_goal(ws, goal, *, runner) -> list[str]` (goal → proposals → очередь → граф)
1. LLM: `PromptManager.render_prompt("goal-planner", {goal_title, goal_description, repo_path, memory_excerpt})`
   → агент (`ws.agents.planner or ws.agents.primary`) пишет JSON блок `PLAN_BEGIN{...}PLAN_END` со списком
   proposals в форме reducer-proposals: `[{id,title,proposal,rationale,acceptance,touches,severity,category,complexity}]`.
   Парсинг — как `_parse_decompose_block`, отдельный `_parse_plan_block`.
2. Добавить proposals в очередь как items (status=pending, `epicId=goal.id`, `source="goal:"+goal.id`,
   content-поля), переиспользуя merge-паттерн `_scan_import` (вынести общий хелпер `add_proposals_to_queue(props, *, epic_id, source)` в `queue.py`, использовать и из scan_import, и здесь — DRY).
3. `decompose_proposals(ws, props, scan_dir="goal-"+goal.id, runner=runner)` → merge граф-полей + `complexity`
   в добавленные items (как scan_import).
4. Записать `goal.task_ids`, вернуть id задач. Пусто (LLM ничего не дал) → вернуть `[]` (не падать).

### 3.3 API (`backend/app/api/v1/goals.py`)
| Метод+путь | Тело | Ответ |
|---|---|---|
| `POST /api/v1/goals` | `{title, description}` | `{ok, goal, taskIds}` (планирует синхронно) |
| `GET /api/v1/goals` | — | `{ok, goals:[...]}` |
| `GET /api/v1/goals/{id}` | — | `{ok, ...Goal}` |
| `DELETE /api/v1/goals/{id}` | — | `{ok}` (status=abandoned; задачи не трогаем) |

Активный workspace через `active_workspace()` (R4). `POST` запрещён при `loop RUNNING`? Нет — планирование
не пишет в git, только в очередь; разрешено. id цели — детерминированный hash(title) — НО передавать timestamp
снаружи (в scripts нет `time.time()`-ограничения, это backend, `time.strftime` ok).

### 3.4 UI — `GoalComposer.vue`
Поле title + textarea description + «Спланировать» → `api.createGoal` → показать сгенерированные задачи (они
появляются на доске с `epicId`). Разместить на `BoardView.vue` (рядом с queue-controls).

---

## 4. Часть C — Ralph continuous mode

### 4.1 RunSummary (`<state>/run-summary.json`)
```python
class RunSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    run_mode: str = Field("queue", alias="runMode")     # queue | ralph
    started_at_ms: int = Field(0, alias="startedAtMs")
    items_done: int = Field(0, alias="itemsDone")
    items_failed: int = Field(0, alias="itemsFailed")
    consec_fail: int = Field(0, alias="consecFail")
    cost_usd: float = Field(0.0, alias="costUsd")
    stopped_reason: str | None = Field(None, alias="stoppedReason")
```
Пишется/обновляется FSM после каждого item; читается API `GET /api/driver/status` (расширить) для UI-прогресса.

### 4.2 Модификация `fsm.run()` (sequential-петля; параллель — аналогично, в `_run_parallel`)
RalphController инкапсулирует стоп-логику. Псевдокод дополнения существующей петли:
```python
ralph = (run_mode == "ralph")
deadline = started_ms + wallclock_sec*1000 if wallclock_sec else None
while not self._stop_requested:
    if self._should_stop_budget(summary, deadline, max_consec_fail):  # cost/wallclock/consec-fail
        summary.stopped_reason = <reason>; break
    item = self._pick_next_item()
    if not item:
        if ralph and (gid := self._active_goal_id()):
            n = await self._replenish(gid)          # §4.3
            if n == 0:
                self._bump_dry(gid)                  # goal.dry_rounds += 1
                if self._dry_rounds(gid) >= 2:
                    summary.stopped_reason = "goal-complete (dry)"; break
                await asyncio.sleep(5); continue
            else:
                self._reset_dry(gid); continue
        # non-ralph or no goal: existing idle-wait
        await asyncio.sleep(30); continue
    ok = await self._process_item(item)             # existing; returns success bool
    self._update_summary(item, ok)                  # items_done/failed, consec_fail, cost += _iter_cost
    if max_iter and summary.items_done >= max_iter: break
    await asyncio.sleep(5)
```
- **consec-fail enforce:** `consec_fail` инкрементится на провале item, сбрасывается на успехе; стоп при
  `>= HEPHAESTUS_MAX_CONSEC_FAIL` (дефолт 4). Сейчас ключ есть в конфиге, но FSM его игнорирует — Эпик включает.
- **cost:** после `_process_item` прибавить `_iter_cost(self.iter_dir)["cost_usd"]` к `summary.cost_usd`; стоп
  при `>= HEPHAESTUS_COST_BUDGET_USD` (если задан, >0).
- **wall-clock:** стоп при `now_ms >= deadline` (если задан).
- Все стопы — мягкие (доводим текущий item), пишут `stopped_reason`.

### 4.3 `_replenish(goal_id) -> int` (goal + done → next proposals)
1. Собрать «сделанное»: titles/summary завершённых задач этой цели (status in done/merged).
2. LLM: `PromptManager.render_prompt("goal-replenish", {goal_title, goal_description, done_summary, repo_path})`
   → агент (`ws.agents.planner or primary`) → `PLAN_BEGIN{...}PLAN_END` с НОВЫМИ proposals (только то, чего не
   хватает для цели; «если цель достигнута — верни пустой tasks»).
3. Если proposals пусто → вернуть 0 (вызвавший считает «dry»). Иначе: `add_proposals_to_queue` +
   `decompose_proposals` (как `plan_goal`), вернуть число добавленных.
- **Анти-runaway:** один replenish добавляет ≤ `HEPHAESTUS_REPLENISH_MAX` задач (дефолт 10); replenish не чаще раза
  на «опустошение». Глобальный потолок — бюджеты §4.2.

### 4.4 API / запуск
`DriverStartRequest` += `runMode: str|None`, `costBudgetUsd: float|None`, `wallclockSec: int|None`,
`maxConsecFail: int|None`. `driver._start_loop` пробрасывает в env: `HEPHAESTUS_RUN_MODE`, `HEPHAESTUS_COST_BUDGET_USD`,
`HEPHAESTUS_WALLCLOCK_SEC`, `HEPHAESTUS_MAX_CONSEC_FAIL`. `GET /api/driver/status` дополняется полем `runSummary` (читает
`run-summary.json`). Config keys добавить в `ALLOWED_CONFIG_KEYS` + дефолты (`HEPHAESTUS_RUN_MODE=queue`,
`HEPHAESTUS_COST_BUDGET_USD=0` (0=off), `HEPHAESTUS_WALLCLOCK_SEC=0` (0=off), `HEPHAESTUS_REPLENISH_MAX=10`).

### 4.5 UI
- Панель запуска (`RunningView.vue`/where driver-start lives): переключатель `runMode` (queue/ralph),
  поля cost-budget/wall-clock, при ralph — подсказка про авто-пополнение.
- Прогресс прогона из `runSummary`: items done/failed, $ потрачено, причина остановки.

---

## 5. Безопасность / анти-runaway

- Ralph пишет в git ТОЛЬКО через существующий per-item FSM (ветки `auto/<id>`, verify, воронка) — никаких
  новых git-путей. Merge в base — по-прежнему руками/Эпик 1 (Ralph НЕ авто-мерджит, если `autoAccept` не
  включён осознанно; это пересечение с Эпиком 1 вне scope здесь).
- Жёсткие лимиты: cost budget, wall-clock, max-consec-fail, `HEPHAESTUS_REPLENISH_MAX`, dry-stop. Любой стоп — мягкий.
- replenish и plan_goal не падают на пустом/битом LLM-ответе (fallback: 0 задач).
- per-task `model_override` валидируется как `AgentRef` (provider/model обязательны); битый override → 422 на
  patch, в FSM — игнор (fallback на ws.primary), не падать.
- Все новые long-running решения логируются в `decisions.log` (replenish: «+N tasks» / «dry»; stop: reason).

---

## 6. Тестирование (TDD)

**Юнит:**
- `Item.model_override`/`complexity` camelCase round-trip; patch принимает `modelOverride`.
- `_run_opencode` собирает эффективный AgentsConfig при override (мок runner — проверить, что primary подменён);
  без override — ws.agents без изменений.
- `Goal`/`GoalStore` round-trip; `_parse_plan_block`.
- `add_proposals_to_queue` (общий хелпер) — proposals → items с epicId/source.
- RalphController стоп-предикаты: cost ≥ budget, now ≥ deadline, consec ≥ max — изолированно (без LLM/git).
- dry-логика: 2 пустых replenish подряд → stop reason "goal-complete (dry)".

**Интеграция (LLM/агент застаблен):**
- `plan_goal` со stub-runner (пишет PLAN-блок) → задачи в очереди с epicId/complexity, граф-поля проставлены.
- `_replenish` со stub: непустой → +N задач, dry сброшен; пустой → 0, dry++.
- `fsm.run()` в ralph со stub `_process_item` + stub replenish: останавливается по cost-budget; по wall-clock;
  по consec-fail; по dry(2). (Подменить `_process_item`/`_replenish`/`_iter_cost` — без реального git/LLM.)
- API: `POST /api/v1/goals` (stub plan_goal) → 200 + taskIds; `GET /api/driver/status` отдаёт runSummary.

**Контракт:** `DriverStartRequest` принимает новые поля (camelCase); `GET /api/driver/status` форма.

**Кроссплатформа:** все стоп-предикаты и сторы — чистый Python; CI windows+ubuntu.

---

## 7. Вне scope Эпика 2

- LLM goal-met детектор (решено: dry-stop вместо него).
- Авто-маппинг complexity→модель (решено: advisory + ручной).
- Авто-merge в base в Ralph (зависит от Эпика 1 `autoAccept`; не включаем массово здесь).
- GitHub/Linear/GitLab (Эпик 3), Insights/Ideas (Эпик 4).
