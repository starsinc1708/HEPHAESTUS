---
title: HEPHAESTUS — Async agent jobs (rebuild-map / ideas / changelog) with progress stream
status: approved
date: 2026-06-07
audience: implementing engineer
language: prose=ru, identifiers/paths/commands=en
depends_on: [2026-06-06-epic1-ai-powered-merge-design, 2026-06-06-epic4-insights-ideas-design]
---

# Async agent jobs

Долгие синхронные агент-эндпоинты (`rebuild-map`, `ideas/generate`, `changelog`) держат HTTP-соединение
минутами → фронт-клиент рвёт запрос по таймауту (баг «API 0 Timeout 30000ms»), хотя backend доводит работу.
Перевести их в **job-режим**: эндпоинт стартует фоновую задачу и сразу возвращает `jobId`; статус опрашивается,
прогресс (JSONL агента) стримится по SSE. Паттерн — как merge-job (Epic 1) + iter-SSE.

## Контракт (generic)
`backend/app/core/agent_jobs.py`:
- `AgentJob` (pydantic, camelCase): `id ("ajob-NNNN"), kind, status (running|done|failed), result: dict|None, error, outputDir, createdAt, updatedAt`.
- `AgentJobStore`: персист `<state>/agent-jobs.json` (`{"jobs":[...]}`, `_StateLock`+`_atomic_write`, list/get/put, keep 50). Как `MergeJobStore`/`GoalStore`.
- `start_agent_job(kind: str, work) -> AgentJob`: создаёт `<state>/ajob-NNNN/` + пустой `output.jsonl`, пишет job(status=running), `asyncio.create_task(_run)`, возвращает job сразу. `_run` делает `res = await work(output_path)`, на успехе `status=done, result=res`, на исключении `status=failed, error=str(exc)` (НЕ падает наружу); persists. `_next_seq()` монотонный по `ajob-*` (как merge-NNNN).
- `work: Callable[[pathlib.Path], Awaitable[dict]]` — получает путь к `output.jsonl`, куда агент должен писать (для SSE), и возвращает result-dict.

## Рефактор агент-функций (добавить параметр output_path)
- `codebase_map.build_map(ws, *, runner, max_files=400, output_path: Path|None=None)` — агент пишет в `output_path` если задан, иначе текущий дефолт (обратная совместимость stub-тестов).
- `ideas.generate_ideas(ws, *, categories, runner, output_path=None)` — то же.
- `changelog.generate_changelog(ws, *, since, runner, output_path=None)` — писать вывод агента в `output_path` (вместо tempfile) если задан.
Инвариант: без `output_path` поведение и сигнатуры-совместимость прежние (существующие тесты зелёные).

## API
- `POST /api/v1/insights/rebuild-map` → **async def**: build runner, `start_agent_job("map", work)`, вернуть `{ok, jobId, kind:"map"}`. work: `build_map(ws, runner=, output_path=op)` → `{"count": len(map)}`.
- `POST /api/v1/ideas/generate {categories?}` → `start_agent_job("ideas", ...)` → `{ok, jobId, kind:"ideas"}`. work → `{"ideas":[idea.model_dump(by_alias) ...]}`.
- `POST /api/v1/integrations/changelog {since?}` → `start_agent_job("changelog", ...)` → `{ok, jobId, kind:"changelog"}`. work → `{"markdown":..., "versionSuggestion":...}`.
- Новые generic-роуты (новый router `api/v1/agent_jobs.py`): `GET /api/v1/agent-jobs/{id}` → `{ok, ...AgentJob}`; `GET /api/v1/agent-jobs/{id}/stream` → SSE tail `<state>/{outputDir}/output.jsonl` (копия merge-job SSE: парс `_summarize_event`, завершение когда `job.status` терминальный И файл стабилен ≥2с, cap 1800с, client-disconnect). Зарегистрировать router в `main.py`.
- Endpoints async; `start_agent_job` вызывает `asyncio.create_task` (нужен running loop → только из async-хендлера). Runner строится через `app.core.scan._build_runner(ws)`. CSRF/`active_workspace` как в существующих роутах.

## Frontend
- `api/client.ts`: `rebuildMap()/generateIdeas()/generateChangelog()` теперь возвращают `{ok, jobId, kind}`; новый `getAgentJob(id)` → AgentJob. Эти стартовые вызовы быстрые → обычный таймаут (можно вернуть к дефолту, но оставить AGENT_TIMEOUT безвредно).
- `composables/useAgentJob.ts` (новый): `run(startFn) → { jobId, status, result, error }` — стартует, опрашивает `getAgentJob` каждую ~1.5с до терминального, отдаёт result; экспонирует `iterDir` (=outputDir) для `<LiveConsole :stream-url="/api/v1/agent-jobs/{id}/stream">`.
- `IdeasPanel.vue`: generate → useAgentJob → пока running показывать LiveConsole-стрим + спиннер → по done рендер `result.ideas`.
- `InsightsChat.vue`: «Rebuild map» → useAgentJob → стрим + по done тост `result.count`.
- `IntegrationsPanel.vue`: changelog → useAgentJob → стрим + по done рендер `result.markdown`.
- Типы `AgentJob` в `types/api.ts`.

## Тесты
- backend unit: `AgentJobStore` round-trip; `_next_seq`; `start_agent_job` happy (work returns dict → status=done, result) + failure (work raises → status=failed, error), используя asyncio + `_STATE_DIR_OVERRIDE` (await the created task).
- backend: рефактор-функции с `output_path` (stub runner пишет в переданный путь) → результат как раньше; без output_path — прежние тесты зелёные.
- backend contract: `POST rebuild-map/ideas/changelog` (work замокан) → `{jobId}`; `GET agent-jobs/{id}` форма.
- frontend: useAgentJob (мок getAgentJob: running→done) ; панели рендерят result после done.
- Гейты: `ruff check .` + `mypy --strict app/` + `pytest` + `vue-tsc` + `vitest` + `build`.

## Вне scope
- goals `plan_goal` и insights `ask` (ask уже стримит iterDir; конвертация — тем же паттерном позже).
- Отмена job / очередь параллельных job (пока просто фоновые задачи).
