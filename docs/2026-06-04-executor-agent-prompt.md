# Executor agent prompt — HEPHAESTUS Vue + FastAPI Kanban rewrite

> Скопируйте всё ниже в новый Claude Code session и отправьте как первый user-message агенту-исполнителю. Промпт самодостаточный: содержит контекст, ссылки на план, чёткие первые шаги, дисциплину subagent-делегирования и skill-usage.

---

# Задача: реализовать универсальную Vue + FastAPI Kanban-платформу для итеративного улучшения произвольных репозиториев

Ты — Claude Code, агент-исполнитель проекта. Тебя пригласили реализовать **универсальный инструмент** для агент-driven улучшения N репозиториев на любом стеке. Текущая инфраструктура HEPHAESTUS — частный случай (один TypeScript-репо, opencode-runner). Сегодня **2026-06-04**.

---

## PIVOT (2026-06-04): универсальная платформа, не single-repo рерайт

Master plan был написан под рерайт текущей инфры с привязкой к sec_audit_app. С 2026-06-04 цель сместилась — это **универсальная Kanban-платформа** для итеративного улучшения кода/инфры/функционала **N произвольных репозиториев** (любой язык, любая verify-команда, любой агент-runner). Master plan — отправная точка; адаптируй по дельтам ниже:

### Phase 0 (изменения)
- **`Repo` как first-class сущность** в Pydantic-моделях: `id`, `name`, `git_remote`, `base_branch`, `ssh_key_ref` (path или env-var), `runner` (enum: `opencode|claude_code|aider|generic_cli`), `verify_command` (string), `agent_overrides` (dict), `tier_thresholds` (`{tier1: 5, tier2: 2}`), `locked_decisions` (markdown text)
- `state/repos/<repo-id>/{work-state.json, iter-NNNN/, scans/, decisions.log, .work-state.lock}` — single-repo текущей инфры мигрирует в `state/repos/default/`. **flock per-repo** (separate lock file)
- `Item.repo_id` FK обязательно. Pydantic-модель `Item` подхватывает alias через `populate_by_name=True`
- Phase 0 contract test: загрузить существующий single-repo `state/work-state.json` под `default` repo — fail если не валидируется

### Phase 1 (изменения)
- REST scoped under repo: `/api/v1/repos`, `/api/v1/repos/{id}/tasks`, `/api/v1/repos/{id}/iters/{iter_id}/{diff,reviews,tools,...}`, `/api/v1/repos/{id}/branches`, `/api/v1/repos/{id}/config`. Top-level `/api/v1/loop`, `/api/v1/agents` остаются global
- В Phase 1 для backward-compat: legacy `/api/v1/tasks` → alias на `/api/v1/repos/default/tasks` (deprecated после Phase 2)
- `_StateLock(repo_id)` — каждый репо свой lock-файл; cross-repo операции (если есть) держат несколько локов в caller order

### Phase 2 (Vue Kanban) изменения
- **Top-level repo-selector** в `AppShell.vue` (chip-list или dropdown). Active repo persisted в `localStorage`
- Routes: `/repos/<id>/board`, `/repos/<id>/board/task/<task-id>`, `/repos/<id>/config`. Глобальные: `/repos` (репо-список + добавить), `/scan`, `/logs`
- Кanban-card показывает repo-chip если view = "all repos"; скрыт если view filtered to one repo
- Per-repo settings screen: git remote, runner type, verify command, agent overrides, tier thresholds, locked decisions

### Phase 4 (orchestrator) изменения
- FSM single-process по-прежнему. `pick_next_item()` итерирует через все repos (priority queue или round-robin; начни с round-robin)
- `IterContext.repo: Repo` пробрасывается в каждый subprocess-вызов (cwd = repo.local_path)
- **Runner adapter pattern:** `backend/app/orchestrator/runners/{opencode,claude_code,aider,generic_cli}.py` с общим интерфейсом:
  ```python
  class AgentRunner(Protocol):
      async def run(self, agent: str, prompt_path: Path, output_path: Path,
                    repo: Repo, timeout_sec: int, progress_cb) -> int: ...
      def parse_result_block(self, output_path: Path) -> ResultBlock: ...
      def parse_events(self, output_path: Path, limit: int) -> list[Event]: ...
  ```
  Выбор runner'а из `repo.runner` поля
- `verify_command` — строка из `Repo.config`, не захардкоженный pnpm. Phase 4 запускает её через subprocess с тем же timeout

### Что НЕ меняется
- Single-tenant LAN-only auth (Phase 5: shared password). Multi-user/JWT/SaaS — НЕ сейчас
- `prompts/system-prefix.md` — становится Jinja2 шаблоном с `{{repo.name}}`, `{{repo.locked_decisions}}`, `{{verify_command}}` плейсхолдерами. Контентом не меняется, только параметризуется
- Прочие no-touch файлы из master plan секции 10 — сохраняются (`lib/*.py`, `prompts/review-*.md`, `prompts/scan-*.md`)
- 6+2+1 tier-review pipeline неизменна (но agent-list и thresholds per-repo configurable)
- HEPHAESTUS_RESULT block schema — байт-в-байт (runner adapter мапит specific-CLI output в общий формат)

### Phase 6 переопределён
- Был: ~~Multi-host / multi-repo (optional)~~ — это теперь Phase 0-1, обязательно
- Стал: **hosted/SaaS** (если потребуется): multi-user auth (OAuth/SAML), per-user permissions per repo, audit log per user, invitation flow, billing hooks. Skip если single-operator остаётся достаточным

### Vendor-agnostic agent abstraction (новый раздел в master plan'е, когда дойдёшь до Phase 4)
- opencode и claude-code эмитят разный JSONL — runner adapter нормализует в общий `Event` shape, который `_summarize_event` (порт из server.py:405-471) уже обрабатывает defensively
- aider — другой stdin-format и markdown-output; runner adapter транслирует
- generic_cli — последняя надёжда: запускает любую CLI с prompt в stdin, парсит stdout как plaintext, конвертит в синтетический tool-call событие

---

## Что есть

- **Master plan:** `c:/Users/starsinc/Desktop/hephaestus-autonomous-loop/docs/2026-06-04-vue-fastapi-kanban-rewrite.md` — обязательно прочитай целиком прежде чем начнёшь работать. Там 10 секций: цель, locked decisions, что не трогать, целевая архитектура backend, целевая архитектура frontend, контракт совместимости, 6 фаз, acceptance criteria, риски, no-touch list.
- **Текущая инфраструктура:** `c:/Users/starsinc/Desktop/hephaestus-autonomous-loop/` (мирор `/home/starsinc/hephaestus-autonomous-loop/` на хосте 192.168.0.103).
- **Целевой HEPHAESTUS-репо:** `/home/starsinc/hephaestus-repo` на хосте (это то, в чём loop отгружает работу; рерайт ничего в нём не меняет).
- **GitHub remote:** `github.com:Dmitzoc/dt.git`, branch `main`.
- **Память проекта:** `c:/1_Projects/sec_audit_app/.claude/memory/` (зеркало `~/.claude/projects/C--1-Projects-sec-audit-app/memory/`). Прочитай `MEMORY.md` для контекста.

## Жёсткие правила

1. **Локальные правки на Windows, синк на Linux-хост через scp/ssh.** Не правь файлы напрямую на хосте через ssh — потеряешь diff в git.
2. **Никаких git push без явного разрешения пользователя.** Локальные коммиты OK, мерджи в main OK после подтверждения, push — спрашивай.
3. **Loop работает в проде.** Не убивай tmux-сессии `hephaestus-loop` без warning'а пользователю. На хосте есть запущенные процессы и очередь из 14 pending items.
4. **Контракт совместимости с bash — load-bearing.** `state/.work-state.lock` через POSIX flock, camelCase JSON-поля, atomic-writes — не нарушать. См. секцию 5 master plan'а.
5. **Не переписывай файлы из секции 10 master plan'а.** prompts/, lib/*.py, verify.sh, tier-review.sh (до Phase 6+) — touch and you'll break tuned behavior.
6. **Тёмная yellow-neon палитра** в Vue — сохрани design tokens из `index.html:8-16`. Не вставляй UI-библиотеку с собственной темой.

## Дисциплина инструментов

### Skills
Перед каждой фазой **обязательно** вызывай:
- `superpowers:brainstorming` — прежде чем формировать ExitPlanMode для фазы. Узнай у пользователя что важно, что некритично.
- `superpowers:test-driven-development` — для backend FSM, для Pydantic-контрактов, для DiffViewer. TDD дисциплина: написать failing test → minimum code → refactor.
- `superpowers:debugging` — когда что-то отказывает (lock contract, WS-fan-out, JSONL parsing edge cases). Скилл предписывает root-cause-first, не симптом-симптом.
- `superpowers:frontend-design` — Phase 2 для Vue Kanban. Перед написанием компонентов.
- `superpowers:writing-plans` — между фазами обновляй master plan если открылись новые знания.

Не пропускай ни одной skill-invocation если она применима. Каждый раз, когда сомневаешься "нужен ли skill" — нужен.

### Subagents

Используй `Agent` tool с правильным `subagent_type`. Запускай параллельно если задачи независимы.

| Когда | Subagent | Зачем |
|---|---|---|
| Глубокий разбор существующего кода перед изменением | `feature-dev:code-explorer` | Не догадывайся — пусть explorer прочитает и доложит |
| Дизайн новой подсистемы (роутер, model, компонент) | `feature-dev:code-architect` | Получишь blueprint с file-paths и data-flows |
| Code-review перед мерджем фазы в main | `feature-dev:code-reviewer` | Catches bugs, security issues, project-convention violations |
| Поиск файла/символа когда не уверен где | `Explore` | Дешевле чем сам грепать |
| Большой план перед началом фазы | `Plan` | Architect для последовательности шагов |
| Любая независимая исследовательская задача | `general-purpose` | Параллелизм для скорости |

**Параллелизация:** Phase 1 порт endpoints — раздели endpoints на 4 кластера (`tasks/iters/loop/state` vs `config/scans/branches/decisions` vs `core/state.py + core/events.py` vs `tests`) и запусти 4 `feature-dev:code-architect` или `general-purpose` параллельно. Phase 2 frontend — `views/` и `components/shared/` независимы.

### Tasks

Каждая фаза → отдельный `TaskCreate`. Внутри фазы — sub-tasks per major component. Mark `in_progress` ровно один таск за раз; `completed` сразу как закончил (не батчь).

## Порядок действий

### Шаг 1 — Загрузить контекст (не пиши код)

1. Read master plan: `c:/Users/starsinc/Desktop/hephaestus-autonomous-loop/docs/2026-06-04-vue-fastapi-kanban-rewrite.md`
2. Read memory: `c:/1_Projects/sec_audit_app/.claude/memory/MEMORY.md` + linked entries про hephaestus-autonomous-loop
3. Skim текущий код: `dashboard/server.py`, `dashboard/index.html` (последние 500 строк где новый task-drilldown), `driver.sh`, `tier-review.sh`, `lib/common.sh`
4. Прочитай `state/work-state.json` для понимания текущей очереди (14 pending items)
5. Прочитай `prompts/system-prefix.md` — это контракт с агентами, его трогать нельзя

### Шаг 2 — Запусти brainstorming skill

Вызови `superpowers:brainstorming`. Тема: "Phase 0 scaffolding + Phase 1 FastAPI proxy — приоритеты". Узнай у пользователя:

- Хочет ли он Vue dev-server на хосте или только prebuilt-`dist/`? (по master plan'у — только prebuilt, но подтверди)
- Готов ли он к 30-минутному downtime'у дашборда на cutover Phase 1 или нужно adjacent-port A/B?
- Какая авторизация по умолчанию (none/password/IP-allowlist) для Phase 1 пока Phase 5 не наступит?
- Какой порт для FastAPI: тот же 8765 (требует stop старого server.py) или новый 8766 на параллельный run?

### Шаг 3 — ExitPlanMode для Phase 0

Сформируй детальный план Phase 0 (scaffolding) с конкретными файлами:

- `backend/pyproject.toml` (укажи каждую пинованную версию)
- `backend/app/main.py` (минимальный FastAPI с healthz)
- `backend/app/core/state.py` (порт `_StateLock`, `_atomic_write`, `_read_state`, `_write_state`, `_LKG_STATE` — verbatim, с unit-test'ами)
- `backend/app/models/domain.py` (Pydantic `Item` модель с `extra='allow'` + alias'ами)
- `backend/tests/contract/test_existing_state.py` — критичный тест: загрузить весь существующий `state/work-state.json` в `Item.model_validate(it)`, fail на отвержении
- `backend/tests/contract/test_lock_contract.py` — критичный тест: bash `_with_state_lock sleep 5` + Python `_StateLock` interleaved, assert Python blocks ~5s
- `frontend/package.json` (укажи каждую пинованную версию)
- `frontend/vite.config.ts` (proxy на 8765)
- `frontend/tailwind.config.ts` (импорт CSS-tokens из existing dashboard/index.html)
- CI workflow `.github/workflows/hephaestus-loop-ci.yml` (ruff + mypy --strict + pytest + vitest)
- Snapshot `state/runtime-versions.json` с `opencode --version` + `pnpm --version` + `python --version`

Phase 0 НЕ трогает production. Loop продолжает работать. `dashboard/server.py` и `index.html` нетронуты.

### Шаг 4 — Implement Phase 0

Через TDD-дисциплину (`superpowers:test-driven-development`). Параллелизуй где можно через 2-3 `feature-dev:code-architect` подагента (один — backend scaffolding, один — frontend scaffolding, один — CI). Запускай в одном message.

После Phase 0:
- Локальный коммит на feature branch `feature/vue-fastapi-rewrite-phase-0`
- `feature-dev:code-reviewer` подагент ревьюит diff
- Применяй замечания через TDD
- Спроси у пользователя перед merge в main и push

### Шаг 5 — Phase 1 (FastAPI proxy)

См. master plan секцию 6 Phase 1. Опять brainstorming → ExitPlanMode → parallel implementation → review → ship.

**Критичный момент Phase 1:** контрактный тест "ответы старого и нового сервера побайтово равны на 50 запросов". Перед swap'ом `start-dashboard.sh:12` запусти оба сервера на 8765/8766, прогони `curl` корпус, diff'ни.

### Шаг 6+ — Phase 2..5

Каждая фаза:
1. Read master plan секцию для этой фазы
2. `superpowers:brainstorming` с пользователем
3. `Plan` подагент для детальной последовательности
4. Parallel implementation через subagents
5. `feature-dev:code-reviewer` review
6. Acceptance criteria check (см. master plan секция 7)
7. Спросить разрешение на merge → user-confirm → merge → ask before push

## Что делать в конце

После каждой фазы:
- Обнови `c:/Users/starsinc/Desktop/hephaestus-autonomous-loop/docs/2026-06-04-vue-fastapi-kanban-rewrite.md`: пометь фазу `[DONE 2026-MM-DD]`, добавь lessons-learned секцию если нашёл что-то неожиданное
- Обнови `c:/1_Projects/sec_audit_app/.claude/memory/hephaestus-autonomous-loop.md`: dual-write в home mirror; запиши SHA merge-коммита фазы
- Спроси нужно ли запустить HEPHAESTUS-loop как smoke-test, или у пользователя есть ручной чек-лист

## Что НЕ делать

- Не запускай Phase 4 (Python orchestrator) пока Phase 0 lock-contract test не зелёный
- Не удаляй `dashboard/server.py` и `index.html` пока Phase 5 не закончится с успешным rollback-чеклистом
- Не add'ай зависимости которые нужны только в одной фазе — задержи до этой фазы
- Не "улучшай" `_StateLock` через `asyncio.Lock` или сторонний `filelock` — bash не увидит
- Не пиши Markdown/планы которые пользователь не просил
- Не push'ай в main без явного разрешения

## Первая реплика

Начни с:
1. Кратко (3-4 предложения) подтверди что прочитал master plan + memory
2. Вызови `superpowers:brainstorming` skill для Phase 0
3. После брэйнсторма — `ExitPlanMode` с детальным Phase 0 планом

Не пиши код в первой реплике. Не пиши markdown-документацию. Сначала alignment с пользователем через brainstorming.

---

# Конец промпта.
