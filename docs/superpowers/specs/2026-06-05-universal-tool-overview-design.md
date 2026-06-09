---
title: HEPHAESTUS Universal Tool — Umbrella Overview & Shared Contracts
status: anchor
date: 2026-06-05
audience: tool author (user) + implementing engineer
language: prose=ru, identifiers/paths/commands=en
depends_on: []
defines_for: [stage-1-onboarding-engine, stage-2-scan-decompose-memory, stage-3-validation-funnel-merge]
---

# HEPHAESTUS Universal Tool — Umbrella Overview & Shared Contracts

Это якорный документ. Он фиксирует продуктовую рамку, доменную модель и интерфейсы движка **один раз**, чтобы три детальные спеки этапов могли ссылаться на него, не переопределяя контракты. Любое расхождение со спекой этапа разрешается в пользу этого документа. Идентификаторы, пути, имена типов/функций/тестов даны на английском, как в коде.

---

## 1. Цель и продуктовая рамка

HEPHAESTUS перестаёт быть «вспомогательным loop'ом над одним хардкод-репозиторием» (`HEPHAESTUS_REPO=/home/starsinc/hephaestus-repo`) и становится **универсальным локальным инструментом**: пользователь онбордит произвольный локальный git-репозиторий, выбирает модели/строгость/ревью, запускает скан улучшений, получает декомпозированную доску задач с порядком и зависимостями, прогоняет loop реализации с воронкой валидации map-reduce и вливает готовые ветки в базовую.

Ключевой сдвиг модели — введение понятия **Workspace** (D9): один онбординнутый репозиторий = один Workspace со своим `RepoProfile` (настройки, агенты, strictness), памятью (`<repo>/.hephaestus/memory/*.md`), доской (`work-state.json`) и историей прогонов (`iter-*`). Инструмент держит **реестр воркспейсов** и понятие *активного* воркспейса; все существующие глобальные синглтоны (`config.REPO`, `STATE_DIR`, `BASE_BRANCH`, `REMOTE`, `BRANCH_PREFIX`) становятся производными от активного `Workspace`, а не от env-дефолтов.

**Брендинг (D7).** Имя «HEPHAESTUS» остаётся брендом самого инструмента; префикс `HEPHAESTUS_*` остаётся неймспейсом конфигов и WS/REST-контракта (`work-state.json`, `output.primary.jsonl`, `auto/<task>`-ветки, `decisions.log`). Убирается только «HEPHAESTUS-как-цель»: хардкод путей, pnpm-привязка верификации, домен security-сканирования по умолчанию и vendor-агенты `sisyphus`/`atlas`/`oracle`/… как дефолты. Старый `dashboard/` (http.server + статический index) выводится из эксплуатации (legacy); единственный сервер — `backend/app/main.py` (FastAPI) + `frontend/dist`.

**Эволюционность (D8).** Реструктуризация in-place: расширяем `backend/app/orchestrator/fsm.py`, переиспользуем `state.py`, `scan.py`, `queue.py`, `git.py`, api-роутеры. Новое ядро с нуля не пишем.

---

## 2. Таблица решений (D1–D11)

| ID | Решение | Якорный артефакт в этом документе |
|----|---------|-----------------------------------|
| D1 | Кроссплатформенный нативный Python-движок; убрать bash-скрипты и tmux; ввести **синхронный PID-based** `ProcessManager` (супервизит только верхнеуровневые долгоживущие дочерние процессы: `loop`/`scan`/`profiler`) | §5 ProcessManager, §9 удаления |
| D2 | Агенты через CLI `opencode` (мульти-провайдер); «выбор модели» = провайдер/модель/агент opencode; поток JSONL сохранить | §5 AgentRunner, §4 RepoProfile.agents |
| D3 | Работа в 3 этапа: umbrella + 3 детальные спеки + 3 плана | §8 границы этапов |
| D4 | Verify-команды определяет Profiler при онбординге → `.hephaestus/memory/verify.md`; ручной override в настройках | §4 Memory, §5 VerifyRunner |
| D5 | Зависимости/конфликты — гибрид: LLM `depends_on` (семантика) + **попарное** пересечение `touches` (файло-конфликт); reorder допустим, если соблюдён DAG `depends_on` И относительный исходный порядок для **каждой пары** с общим файлом (НЕ транзитивно) | §4 Task, §8 поток |
| D6 | Память — md внутри целевого репо под git: `<repo>/.hephaestus/memory/*.md` | §4 Memory |
| D7 | «HEPHAESTUS» остаётся брендом и неймспейсом; убрать HEPHAESTUS-как-цель | §1 Брендинг |
| D8 | Реструктуризация эволюционно, in-place | §1 Эволюционность |
| D9 | Понятие Workspace; несколько воркспейсов, активный выбирается пользователем | §1, §4 Workspace |
| D10 | Воронка валидации map-reduce «от многих к меньшим»; размеры/пороги от strictness (`TIER_PRESETS`) | §7 Воронка |
| D11 | Merge из UI = локальный `git merge auto/<task>` в base с **персистентными** проверками (`item.validation.gate=='pass'` + `item.verify_green`), запрет при `loop RUNNING`; опциональный push; обработка конфликтов | §5 GitService, §6 API |

---

## 3. Карта компонентов (слои)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ FRONTEND  (Vue 3 / Pinia / Vue Router)  frontend/src                      │
│   Workspaces picker · KanbanBoard (order+deps) · TaskDrawer · Config       │
│   ConfigView(strictness) · ToolsView(scan) · BranchesView(merge) · WS live │
└───────────────┬──────────────────────────────────────────────────────────┘
                │ REST {ok|error}  +  WS /ws/board /ws/loop /ws/iter
┌───────────────▼──────────────────────────────────────────────────────────┐
│ FASTAPI API  backend/app/main.py  +  backend/app/api/v1/*                  │
│   /api/v1/workspaces · /api/v1/tasks · /api/scan/* · /api/driver/*(loop)    │
│   /api/v1/branches(merge) · /api/v1/prompts · /api/v1/memory · /api/v1/issues│
└───────────────┬──────────────────────────────────────────────────────────┘
                │  (active Workspace context threaded into every call)
┌───────────────▼──────────────────────────────────────────────────────────┐
│ CROSS-PLATFORM PYTHON ENGINE   backend/app/core + backend/app/orchestrator │
│  ┌────────────────┐ ┌──────────────┐ ┌──────────────┐ ┌─────────────────┐ │
│  │ ProcessManager │ │ AgentRunner  │ │ VerifyRunner │ │ GitService      │ │
│  │ (sync, PID-    │ │ (opencode    │ │ (verify.md   │ │ (branch/commit/ │ │
│  │  based; super- │ │  run, model  │ │  commands,   │ │  diff/merge→    │ │
│  │  visit loop/   │ │  selection,  │ │  no bash,    │ │  base; conflict │ │
│  │  scan/profiler)│ │  JSONL out)  │ │  xplatform)  │ │  handling)      │ │
│  └────────────────┘ └──────────────┘ └──────────────┘ └─────────────────┘ │
│           OrchestratorFSM (fsm.py): IDLE→PREFLIGHT→…→VALIDATE→MERGEABLE     │
└───────────────┬──────────────────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────────────────┐
│ STAGE CAPABILITIES                                                         │
│  Stage1 Onboarding+Engine │ Stage2 Scan+Decompose+Memory │ Stage3 Funnel  │
│  (ProcessManager, runners,│ (map-reduce scan, task_graph │ +Merge          │
│   profiler, RepoProfile)  │  DAG, project memory writers) │ (validators)   │
└───────────────┬──────────────────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────────────────┐
│ DOMAIN & STATE                                                            │
│  Workspace registry  ·  Task (ex-Item)  ·  Memory(.hephaestus/memory/*.md)     │
│  work-state.json (per workspace)  ·  iter-NNNN/ artifacts  ·  decisions.log│
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Доменная модель

Сериализация — camelCase через Pydantic-алиасы, по образцу `backend/app/models/domain.py` (`model_config = ConfigDict(extra="allow", populate_by_name=True)`, `by_alias=True` при `model_dump`). Поля с `snake_case` именами в Python, у которых JSON-контракт camelCase, получают `Field(..., alias="camelCase")`.

### 4.1 `Workspace` / `RepoProfile`

Новый файл `backend/app/models/workspace.py`. Один `Workspace` = один онбординнутый репозиторий. `id` — детерминированный hash абсолютного нормализованного пути репозитория (`sha256(os.path.realpath(repo_path).casefold().encode())[:16]`), чтобы один и тот же репо не онбордился дважды и не зависел от регистра пути на Windows.

```python
# backend/app/models/workspace.py
from __future__ import annotations
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class VerifySource(StrEnum):
    AGENT = "agent"      # команды определены Profiler'ом → .hephaestus/memory/verify.md
    MANUAL = "manual"    # пользователь задал override в настройках


class AgentRef(BaseModel):
    """opencode provider/model/agent triple. 'agent' опционален: либо именованный
    opencode-агент, либо чистая model-строка при use_models=True (D2)."""
    model_config = ConfigDict(populate_by_name=True)
    provider: str                     # 'anthropic' | 'openai' | 'deepseek' | ...
    model: str                        # 'claude-opus-4-8' | 'gpt-4.1' | ...
    agent: str | None = None          # имя opencode-агента, если используется


class AgentsConfig(BaseModel):
    """Дефолтные пулы заполняет WorkspaceRegistry при онбординге (R3):
    provider/model берутся из env HEPHAESTUS_AGENT_PROVIDER / HEPHAESTUS_AGENT_MODEL,
    иначе нейтральный плейсхолдер; пользователь переопределяет в SettingsView."""
    model_config = ConfigDict(populate_by_name=True)
    use_models: bool = Field(False, alias="useModels")     # HEPHAESTUS_USE_MODELS
    primary: AgentRef
    fallback: AgentRef
    # пул валидаторов воронки (§7): >=5 AgentRef, по одной на линзу
    # correctness/tests/security/conventions/scope
    validators: list[AgentRef] = []
    arbiters: list[AgentRef] = []      # арбитры слоя 2 (>=2)
    final: AgentRef | None = None      # финальный гейт слоя 3 (1)


class ReviewConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    enabled: bool = True                                   # HEPHAESTUS_TIER_REVIEW
    tier1_threshold: int = Field(5, alias="tier1Threshold")  # HEPHAESTUS_TIER1_APPROVE_THRESHOLD
    tier2_threshold: int = Field(2, alias="tier2Threshold")  # HEPHAESTUS_TIER2_APPROVE_THRESHOLD
    max_revisions: int = Field(2, alias="maxRevisions")    # лимит needs_revision-петель (D10);
    # env-ключ HEPHAESTUS_REVISION_MAX → JSON-alias maxRevisions (маппинг при сборке RepoProfile, R17)


class RepoProfile(BaseModel):
    """Workspace == RepoProfile + runtime paths. Persisted at
    <hephaestus_home>/workspaces/<id>/profile.json (registry side) and mirrored as the
    workspace's effective config layer."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str                                                # sha256(realpath)[:16]
    name: str                                              # human label (repo basename by default)
    repo_path: str = Field(..., alias="repoPath")          # абсолютный путь (replaces config.REPO)
    base_branch: str = Field("main", alias="baseBranch")   # HEPHAESTUS_BASE_BRANCH
    remote: str = "origin"                                 # HEPHAESTUS_REMOTE
    branch_prefix: str = Field("auto", alias="branchPrefix")  # HEPHAESTUS_BRANCH_PREFIX

    agents: AgentsConfig
    strictness: str = "standard"                           # strict|standard|permissive (preset key)
    review: ReviewConfig = ReviewConfig()

    verify_source: VerifySource = Field(VerifySource.AGENT, alias="verifySource")  # D4
    verify_commands_override: list[str] = Field([], alias="verifyCommandsOverride")
    verify_timeout_sec: int = Field(900, alias="verifyTimeoutSec")

    memory_dir: str = Field(".hephaestus/memory", alias="memoryDir")  # relative to repo_path (D6)
    autopush: bool = False                                 # HEPHAESTUS_AUTOPUSH
    autopush_remote: str = Field("origin", alias="autopushRemote")

    created_at: str | None = Field(None, alias="createdAt")
    onboarded: bool = False                                # True после прогона Profiler'а
```

**Дефолты пулов агентов и выбор моделей (R3, D10).** `WorkspaceRegistry` при создании воркспейса заполняет `agents` производными от выбранного провайдера/модели: `primary`, `fallback`, `validators` (>=5 `AgentRef`, по одной на линзу `correctness`/`tests`/`security`/`conventions`/`scope`), `arbiters` (>=2), `final` (1). Плейсхолдеры провайдера/модели берутся из env `HEPHAESTUS_AGENT_PROVIDER` / `HEPHAESTUS_AGENT_MODEL`, иначе — нейтральный плейсхолдер. `SettingsView` (Этап 1) редактирует `provider`/`model`/`agent` для `primary` и `fallback` (+ toggle `use_models`), а также размеры и модели пулов `validators`/`arbiters`/`final`, отправляя их через `WorkspaceUpdateRequest.agents`. Воронка (Этап 3) НИКОГДА не вырождается молча в `gate=pass`: если `ws.agents.validators` пуст — используется `[ws.agents.primary] * N`; если `final is None` — используется `primary` (см. §7).

**Маппинг env→alias (R17).** При сборке `RepoProfile` env-ключ `HEPHAESTUS_REVISION_MAX` явно отображается в `ReviewConfig.max_revisions` (JSON-alias `maxRevisions`). FSM-петля ревизий читает `ws.review.max_revisions`; параллельного источника истины для этого лимита нет.

### 4.2 `Task` — эволюция `Item`

`Task` расширяет существующий `Item` (`backend/app/models/domain.py`). **Все текущие поля сохраняются** (контракт frontend `Item` в `frontend/src/types/api.ts` остаётся валидным): `id, title, status, attempts, proposal, why, acceptance, touches, branch, last_iter(alias lastIter), previous_branches(previousBranches), commit, plan_file, plan_section, wave, severity, category, source_scan, self_reported_failure(selfReportedFailure), requeued_at(requeuedAt), review, merge_commit(mergeCommit), merged_at(mergedAt), recovered_at(recoveredAt), merged_into(mergedInto), merge_sha(mergeSha), push, agreement_count(agreementCount), source_issue(sourceIssue)`.

Добавляются поля (camelCase в JSON):

```python
# дополнения к Item → Task в backend/app/models/domain.py
    workspace_id: str | None = Field(None, alias="workspaceId")   # привязка к Workspace
    depends_on: list[str] = Field(default_factory=list, alias="dependsOn")  # D5 семантика
    blocks: list[str] = Field(default_factory=list)               # обратные рёбра (derived)
    order_index: int = Field(0, alias="orderIndex")               # позиция в доске/исполнении
    epic_id: str | None = Field(None, alias="epicId")             # parent-эпик при декомпозиции
    parent: str | None = None                                     # прямой родитель (sub-task)
    conflict_group: str | None = Field(None, alias="conflictGroup")  # косметическая метка компонента
    # touches-конфликта; ПРЕДИКАТ reorder — попарный, НЕ по этому полю (R6, см. §4 ниже и D5)
    validation: dict | None = None                               # результат воронки (см. §7 ValidationResult)
    result_summary: str = Field("", alias="resultSummary")       # «что сделано» (D-видение п.8)
    diff_ref: str | None = Field(None, alias="diffRef")          # iter-dir/diff или branch для diff
```

**Статусы (строки, не `Literal` — `failed:*` варианты неперечислимы):**
`pending → in_progress → in_review → needs_revision → done → merged | failed:*`.
`in_review` — новый промежуточный статус между завершённой реализацией и прохождением воронки (§7); `needs_revision` — воронка вернула фидбэк, item возвращается в loop с инкрементом `attempts` (лимит `ReviewConfig.max_revisions`). Frontend-тип `ItemStatus` в `frontend/src/types/api.ts` расширяется значением `'in_review'`.

**Файло-конфликт — попарно, не транзитивно (R6, D5).** Конфликт хранится как **рёбра между парами** задач с реально общим файлом (`touches ∩ != пусто`). Предикат `task_graph.can_reorder` проверяет относительный исходный порядок ТОЛЬКО для пар с общим файлом и рёбер `depends_on` DAG. Транзитивные компоненты (union-find) НЕ используются как запрет reorder: если `A∩B != пусто` и `B∩C != пусто`, но `A∩C == пусто`, то `A` и `C` переставлять **можно**. Поле `conflict_group` остаётся косметической меткой компонента для UI, но не является предикатом допустимости порядка.

### 4.3 Memory — раскладка `<repo>/.hephaestus/memory/`

Память живёт **внутри целевого репозитория, под git** (D6), создаётся Profiler'ом при онбординге, дописывается после каждого скана/задачи. Файлы:

```
<repo>/.hephaestus/
  memory/
    MEMORY.md         # индекс: ссылки на остальные + дата последнего обновления
    architecture.md   # модули, слои, точки входа, потоки данных
    verify.md         # verify-команды проекта (источник для VerifyRunner при verify_source=agent)
    conventions.md    # код-стиль, паттерны, naming, тест-конвенции
    tech-debt.md      # известный долг, риск-зоны, «не трогать»
```

Каждый md-файл начинается YAML-frontmatter (парсится `backend/app/services/project_memory.py`):

```markdown
---
doc: verify            # один из: index|architecture|verify|conventions|tech-debt
workspace_id: 9f3a1c20e4b57d61
updated_at: 2026-06-05T10:00:00Z
source: profiler       # profiler|scan|task|manual
schema: 1
---
```

`verify.md` тело содержит исполнимый блок команд, который VerifyRunner читает дословно (по одной команде на строку, в порядке исполнения), напр.:

```markdown
## commands
```sh
uv run pytest -q
uv run ruff check .
```
```

### 4.4 Run / Iteration артефакты

Расширяем существующий layout `state/iter-NNNN/` (теперь — `<workspace_state>/iter-NNNN/`). **Имена директорий — монотонный последовательный счётчик** `iter-NNNN` (R12): читается максимум существующих `iter-*` и `+1` под `_StateLock`, как в исходном layout. НЕ использовать `int(time.time())` с `:04d` — это даёт коллизии и немонотонность. Существующие артефакты сохраняются: `prompt.md`, `output.primary.jsonl`, `output.fallback.jsonl`, `verify.log`, `commit-msg.txt`, `run-tag`, `result.json`, `reviews/`. Добавляются:

```
iter-NNNN/
  validation/                       # §7 воронка
    layer1/<lens>.jsonl             # вердикт каждого валидатора-линзы (correctness/...)
    layer2/arbiter-<i>.json         # сведённые находки арбитра i (1..M)
    layer3/final.json               # {gate: pass|needs_revision, ...}
  diff.patch                        # git diff base..branch (для diff_ref и result_summary)
  summary.md                        # human-readable «что сделано» (result_summary source)
```

**Уникальность конкурентных артефактов (R2).** Каждый конкурентный вызов агента имеет **уникальный артефакт-путь и идентичность**, без общего `session_name` и без коллизии на имени `'loop'`: валидаторы Layer1 → `iter-NNNN/validation/layer1/<lens>.jsonl`; арбитры Layer2 → `iter-NNNN/validation/layer2/arbiter-<i>.json`; финал Layer3 → `iter-NNNN/validation/layer3/final.json`; профайлер — онбординг-таск с идентичностью `profiler-<ws.id>`. Валидаторы воронки — **внутренние конкурентные asyncio-подпроцессы оркестратора**, а НЕ `ProcessManager`-сессии backend (см. §5.1, §7).

---

## 5. Интерфейсы движка

Все четыре — кроссплатформенные (Windows/macOS/Linux, без WSL, без bash, без tmux). Async там, где есть I/O subprocess. Контекст активного `Workspace` передаётся явно (`ws: RepoProfile`), а не читается из глобалей — это обязательный контракт для Этапов 2 и 3.

### 5.1 `ProcessManager` — `backend/app/core/process.py` (D1, заменяет tmux + pgrep + pkill)

`ProcessManager` супервизит **только верхнеуровневые долгоживущие ДОЧЕРНИЕ процессы по PID, синхронно и кроссплатформенно** (R1). Долгоживущие сущности — каждая отдельный супервизируемый процесс под логическим именем-сессией:
- `loop` — оркестратор как отдельный процесс: `python -m app.orchestrator.main --workspace <id>`;
- `scan` — нативный map-reduce как отдельный процесс (детализация map→reduce — в Stage 2, R19);
- `profiler` — онбординг.

Менеджер — **обычный sync-объект** (один на backend; сериализация через `threading.Lock`, БЕЗ `asyncio.Lock`). Он НЕ хранит `asyncio.subprocess.Process`; вместо этого хранит PID и PID-дерево в `<state>/process.json`. Запуск — через `subprocess.Popen` (НЕ `asyncio.create_subprocess_*`), с `start_new_session=True` (POSIX) / `creationflags=CREATE_NEW_PROCESS_GROUP` (Windows). Методы `status()`/`stop()`/`cancel()` **синхронны**: liveness через `os.kill(pid, 0)`; kill дерева — `taskkill /T /F` (Windows) и `os.killpg(SIGTERM→SIGKILL)` (POSIX).

**ЗАПРЕЩЕНО** вызывать `asyncio.run(pm.*)` из sync FastAPI-роутов: `pm` синхронен и вызывается напрямую. **ВНУТРИ** дочернего процесса (оркестратор/скан) живёт собственный единый asyncio event loop; там `AgentRunner` запускает `opencode` через `asyncio.subprocess` НА ТЕКУЩЕМ loop. Это устраняет смешивание loop'ов между backend и движком.

```python
from enum import StrEnum
import pathlib

class ProcState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    EXITED = "exited"

class ProcessHandle(BaseModel):
    name: str                 # logical session: 'loop' | 'scan' | 'profiler'
    pid: int | None           # PID супервизируемого дочернего процесса (R9: единое имя)
    state: ProcState
    started_at_ms: int | None
    exit_code: int | None
    children: list[int] = []  # PID-дерево (best-effort), персистится в state/process.json

class ProcessManager:
    # sync, PID-based; threading.Lock (НЕ asyncio.Lock); хранит PID, не Popen-объект
    def start(self, name: str, cmd: list[str], *, cwd: str,
              env: dict[str, str], output_path: pathlib.Path | None = None,
              timeout_sec: int | None = None) -> ProcessHandle:
        """subprocess.Popen(start_new_session=True | creationflags=CREATE_NEW_PROCESS_GROUP).
        Сохраняет pid + PID-дерево в state/process.json."""
    def stop(self, name: str, *, grace_sec: float = 10.0) -> ProcessHandle:
        """Graceful: SIGTERM/CTRL_BREAK; после grace — kill дерева
        (taskkill /T /F | os.killpg SIGKILL)."""
    def status(self, name: str) -> ProcessHandle:
        """Liveness через os.kill(pid, 0); восстановление из state/process.json."""
    def list(self) -> list[ProcessHandle]: ...
    def cancel(self, name: str) -> None:
        """Hard cancel: kill PID-дерева немедленно (taskkill /T /F | os.killpg).
        Заменяет _kill_loop_hard."""
```

Замены: `backend/app/core/driver.py::_start_loop/_stop_loop_soft/_kill_loop_hard/_loop_status` и `backend/app/core/scan.py::_scan_start/_scan_running` переписываются поверх `ProcessManager` (вместо `tmux new-session` / `tmux has-session` / `pgrep` / `pkill`). PID-файлы заменяются на in-memory реестр `ProcessManager` + `<state>/process.json` (PID-дерево) для восстановления после рестарта backend.

**Граница ответственности (R1).** `AgentRunner` НЕ обращается к приватным полям `ProcessManager` (`_procs`/`_finalize`). `AgentRunner` управляет СВОИМ `asyncio.subprocess`-хэндлом и `await`'ит именно его. Конкурентные агенты воронки не делят общий `session_name` (см. §7, R2): они — внутренние подпроцессы оркестратора, не backend-сессии `ProcessManager`.

### 5.2 `AgentRunner` — `backend/app/services/opencode_runner.py` (D2)

Обёртка над `opencode run`, выбирающая провайдер/модель/агент из `Workspace.agents`. Сохраняет поток JSONL (`output.primary.jsonl` / `output.fallback.jsonl`), парсимый `backend/app/core/events.py`.

```python
class AgentResult(BaseModel):
    exit_code: int            # 0 ok; <0 timeout/launch-error
    refused: bool             # детект 'REFUSED' в первых байтах output (см. fsm._run_opencode)
    output_path: pathlib.Path
    agent_label: str          # provider/model[/agent] для логов и UI

class AgentRunner:
    def __init__(self, pm: ProcessManager) -> None: ...
    async def run(self, ref: "AgentRef", *, prompt_file: pathlib.Path, cwd: str,
                  output_path: pathlib.Path, timeout_sec: int) -> AgentResult:
        """opencode 1.16.0 (подтверждено `opencode run --help`): cmd =
        `opencode run --format json [--agent <a> | --model <provider/model>] <message>`.
        Промпт — ПОЗИЦИОННЫЙ message (нет --prompt); вывод JSON-событий в STDOUT
        (нет --output) → захватываем в output_path; не использовать --command (баг #2923).
        Запускает СВОЙ asyncio.subprocess на текущем event loop и await'ит именно его —
        НЕ обращается к приватным полям pm (_procs/_finalize). Каждый конкурентный вызов
        имеет уникальный output_path; общего session_name нет (R1/R2)."""
    async def run_with_fallback(self, agents: "AgentsConfig", *, prompt_file, cwd,
                                iter_dir: pathlib.Path, timeout_sec: int) -> AgentResult:
        """primary→fallback. Пишет output.primary.jsonl / output.fallback.jsonl.
        Заменяет fsm._run_opencode + _run_opencode_subprocess; убирает хардкод
        'sisyphus'/'glm' suffix-эвристики."""
```

### 5.3 `VerifyRunner` — `backend/app/core/verify.py` (D4, заменяет `verify.sh` + bash)

Без bash, без pnpm-хардкода. Источник команд: при `verify_source=agent` — парсинг `<repo>/.hephaestus/memory/verify.md`; при `verify_source=manual` — `RepoProfile.verify_commands_override`. Конвенция exit-кодов: `0 = green`, иначе fail.

**Контракт verify-команд (R5, ради Windows).** Каждая команда — **одна программа + аргументы на строку, без shell-операторов** (`&&`, `|`, `>`, `$VAR`). Этот контракт зафиксирован также в `prompts/profiler.md` и в формате `.hephaestus/memory/verify.md`. `VerifyRunner` резолвит исполняемый файл через `shutil.which` ПЕРЕД exec (на Windows подхватывает `.cmd`/`.bat`/`.exe`-шимы вроде `npm.cmd`/`pnpm.cmd`). Опциональный manual-override может пометить команду `shell: true` → тогда запуск через `['cmd', '/c', cmd]` (Windows) / `['sh', '-c', cmd]` (POSIX); по умолчанию `shell: false`. НЕ использовать `shlex.split(..., posix=True)` на Windows для путей — на Windows разбор без `posix` (или собственный). CI-тест на `windows-latest` с `.cmd`-шимом и составной командой обязателен.

```python
class VerifyResult(BaseModel):
    ok: bool
    ran: list[str]            # команды, которые исполнились
    failed_command: str | None
    log_path: pathlib.Path    # iter-dir/verify.log

class VerifyRunner:
    def __init__(self, ws: "RepoProfile") -> None: ...
    def resolve_commands(self) -> list[str]:
        """verify_source=agent → project_memory.read_verify_commands(ws);
        verify_source=manual → ws.verify_commands_override. Пусто → ok=True (no-op)."""
    async def run(self, *, cwd: str, log_path: pathlib.Path,
                  timeout_sec: int) -> VerifyResult: ...
```

`fsm._verify` перестаёт звать `bash verify.sh`; вместо этого инстанцирует `VerifyRunner(ws)`.

### 5.4 `GitService` — расширение `backend/app/core/git.py` (D11)

Существующие функции (`_git_branches`, `_git_recent_commits`, `_action_merge`, `_action_requeue`, `_action_discard`, `_is_safe_auto_branch`, `BRANCH_ACTIONS`) сохраняются и оборачиваются в класс, принимающий `RepoProfile` (вместо глобальных `REPO`/`BASE_BRANCH`/`REMOTE`/`BRANCH_PREFIX`). Добавляются методы для merge-в-base из UI с предпроверками.

```python
class MergePreflight(BaseModel):
    clean_tree: bool
    verify_green: bool        # ПЕРСИСТЕНТНЫЙ признак item.verify_green (пишется FSM
                              # после зелёного verify), НЕ эвристика по статусу (R11)
    validation_passed: bool   # ПЕРСИСТЕНТНЫЙ item.validation.gate == 'pass' (§7, R11)
    loop_active: bool         # pm.status('loop') == RUNNING → merge запрещён (R11)
    base_branch: str
    conflicts: list[str] = [] # файлы-конфликты, заполняется при попытке merge
    ok: bool                  # все предпроверки прошли (и loop НЕ активен)

class GitService:
    def __init__(self, ws: "RepoProfile") -> None: ...
    def branches(self) -> list[dict]: ...                 # ex-_git_branches, scoped to ws
    def create_branch(self, name: str) -> bool: ...       # из ensure_clean_base логики fsm._preflight
    def commit(self, msg: str) -> str | None: ...         # ex-fsm._commit, возвращает short sha
    def diff(self, branch: str) -> str: ...               # git diff base..branch → diff.patch
    def merge_preflight(self, branch: str) -> MergePreflight:
        """Резолвит Task по ветке. Task не найден → понятная 409 (НЕ молчаливый False).
        Читает ПЕРСИСТЕНТНЫЕ item.validation.gate=='pass' и item.verify_green;
        loop_active = (pm.status('loop')==RUNNING)."""
    async def merge_to_base(self, branch: str, *, push: bool) -> dict:
        """Локальный git merge auto/<branch> → base. Запрещён, пока loop RUNNING
        (409 'loop active, stop it before merge'). Конфликт → git merge --abort,
        вернуть {ok:False, conflicts:[...]}. Сохраняет существующую push-before-delete
        семантику _action_merge. (Альтернатива worktree — будущее.)"""
```

**Merge-сериализация и признаки (R11, D11).** `merge_preflight` опирается на **персистентные признаки в самом `Task`**, а НЕ на эвристику по префиксу статуса: `item.validation.gate == 'pass'` и `item.verify_green` (bool, который FSM пишет после зелёного verify). Если `Task` по ветке не найден — возвращается понятная **409**, а не молчаливый `False`. Пока `loop` в состоянии RUNNING (`pm.status('loop') == RUNNING`), merge запрещён → **409** `'loop active, stop it before merge'` (одновременная запись в base из loop и из merge-UI исключается; worktree-альтернатива помечена как будущее).

---

## 6. API-конвенции

**Форма ответа** — как в `backend/app/main.py`: успех `{"ok": true, ...data}` (`ok_response`), ошибка `{"ok": false, "error": "<msg>", ...}` со статусом 400/4xx (`error_response`). Глобальный 500 → `{"ok": false, "error": "Internal server error", "detail": "..."}`. Middleware (CSRF, no-store, security headers, body-limit) и auth (`HEPHAESTUS_DASHBOARD_PASSWORD`) сохраняются как есть.

**Версионирование путей.** Существующие роутеры в `backend/app/api/v1/*` исторически отдают пути `/api/...` (без `/v1`). Новые ресурсы добавляются под `/api/v1/...`; legacy-пути остаются для обратной совместимости текущего frontend. **scan и loop сохраняют ФАКТИЧЕСКИЕ legacy-пути (R10):** loop — `/api/driver/start|stop|kill` (+ статус), scan — `/api/scan/*`, как в существующем коде. Префикс `/api/v1/*` используется только для `tasks`/`workspaces`/`memory`/`issues`/`prompts`/`repos`/`merge`.

**Новые/расширяемые маршруты:**

| Метод+путь | Назначение | Этап |
|---|---|---|
| `GET /api/v1/workspaces` | список воркспейсов из реестра | 1 |
| `POST /api/v1/workspaces` | онбординг: `{repoPath}` → создать `RepoProfile`, запустить Profiler | 1 |
| `GET /api/v1/workspaces/{id}` | профиль воркспейса | 1 |
| `PUT /api/v1/workspaces/{id}` | правка настроек (агенты, strictness, verify override) | 1 |
| `POST /api/v1/workspaces/{id}/activate` | сделать активным | 1 |
| `GET /api/v1/workspaces/{id}/memory/{doc}` | чтение `.hephaestus/memory/<doc>.md` | 2 |
| `PUT /api/v1/workspaces/{id}/memory/{doc}` | ручная правка памяти | 2 |
| `POST /api/scan/start` · `GET /api/scan/status` · `POST /api/scan/import/{dirname}` | скан (ws-scoped, ProcessManager), legacy-путь | 2 |
| `GET /api/v1/tasks` · `PATCH /api/v1/tasks/{id}/reorder` | доска + reorder с DAG-проверкой | 2 |
| `POST /api/driver/start` · `/stop` · `/kill` · `GET /api/driver/status` | loop через ProcessManager, legacy-путь | 1/3 |
| `GET /api/v1/branches/{name}/merge-preflight` | предпроверки merge | 3 |
| `POST /api/v1/branches/{name}/merge` | `{push: bool}` → локальный merge-в-base | 3 |

`PATCH /api/v1/tasks/{id}/reorder` обязан вернуть `{"ok": false, "error": "reorder breaks dependency <X> before <Y>"}` при нарушении DAG/файло-порядка (D5).

**WS-каналы** (без изменений по форме, `backend/app/api/ws.py`): `/ws/board` (полный `StateSnapshot`), `/ws/loop` (фазовые переходы FSM), `/ws/iter/{dirname}` (live JSONL). `LoopStatus.tmux` в `frontend/src/types/api.ts` заменяется на `process: { state, pid, children }` (отражение `ProcessHandle`); поле `tmux` помечается deprecated и временно дублируется как `state === 'running'`.

**Имя PID-поля — единое сквозь стек (R9).** `ProcessHandle.pid` → JSON `process.pid` → TS `ProcessManagerStatus.pid`. Поле `driverPid` не используется (в крайнем случае оставляется как deprecated-зеркало, но основным считается `pid`). Frontend читает `pid` напрямую, без скрытого нормализатора.

---

## 7. Воронка валидации (D10)

Map-reduce «от многих к меньшим», заменяет no-op `fsm._tier_review` и `tier-review.sh`. Три слоя:

- **Layer 1 — линзы (много).** `N` параллельных валидаторов, каждый смотрит свою линзу: `correctness`, `tests`, `security`, `conventions`, `scope`. Голосуют `approve | needs_revision | reject` + `confidence` + `reasoning`. Реализация — `AgentRunner` как **внутренние конкурентные asyncio-подпроцессы оркестратора** (НЕ `ProcessManager`-сессии backend, R2); каждый имеет уникальный артефакт-путь `iter-NNNN/validation/layer1/<lens>.jsonl`, без общего `session_name`.
- **Layer 2 — арбитры (меньше).** `M` арбитров сводят находки слоя 1 (dedupe, severity, агрегированный вердикт) → `iter-NNNN/validation/layer2/arbiter-<i>.json` (i = 1..M).
- **Layer 3 — финальный гейт (один).** Сводит слои 1–2 → `iter-NNNN/validation/layer3/final.json`: `{gate: "pass" | "needs_revision", blocking: [...], notes: "..."}`.

`needs_revision` → фидбэк возвращается агенту, item переходит `in_review → needs_revision → in_progress`, `attempts += 1`; при `attempts > ReviewConfig.max_revisions` → `failed:max-revisions`.

**Воронка не вырождается молча в `gate=pass` (R3).** Если `ws.agents.validators` пуст — используется `[ws.agents.primary] * N`; если `ws.agents.final is None` — используется `primary`. Пустой пул при `strictness != disabled` НЕ означает автоматический `pass`.

**Маппинг strictness → размеры/пороги** переиспользует `TIER_PRESETS` из `backend/app/config.py` (не вводим новый источник истины):

| strictness | layer1 N (линзы) | layer2 M | tier1_threshold | tier2_threshold | gate |
|---|---|---|---|---|---|
| `strict` | 5 (все линзы) | 2 | 6→clamp к N | 2 | pass требует обе ступени |
| `standard` | 5 | 2 | 5 | 2 | дефолт |
| `permissive` | 3 (correctness, tests, scope) | 1 | 3 | 1 | мягкий gate |
| `disabled` | 0 | 0 | — | — | gate=pass без проверок |

Пороги читаются из `TIER_PRESETS` через `_config_preset(name)` (который уже проставляет `HEPHAESTUS_TIER1_APPROVE_THRESHOLD` / `HEPHAESTUS_TIER2_APPROVE_THRESHOLD`); добавление этих ключей в `_config_effective` — лишь страховка standard-пресета, НЕ параллельный источник истины (R16). Метод вычисления размеров слоёв `_layer_sizes_for` живёт как метод класса `ValidationFunnel` в `backend/app/core/validators.py` (НЕ в `config.py`). В `config.py` добавляется ТОЛЬКО `HEPHAESTUS_REVISION_MAX`. Результат сериализуется в `Task.validation` (`ValidationResult`-форма с camelCase-алиасами, R7):

```python
class LensVerdict(BaseModel):
    lens: str                 # correctness|tests|security|conventions|scope
    verdict: str              # approve|needs_revision|reject
    confidence: float
    reasoning: str

class ValidationResult(BaseModel):
    # camelCase-алиасы, чтобы буквальный код совпал со Stage 3 и frontend-типом (R7)
    model_config = ConfigDict(populate_by_name=True)
    layer1: list[LensVerdict]
    layer2_summary: list[dict] = Field(default_factory=list, alias="layer2Summary")
    gate: str                 # pass|needs_revision
    blocking: list[str] = []
    revision: int             # какая попытка
```

**Диагностика воронки (R20, D10).** В финальном `ValidationResult.blocking` при провале Layer2 добавляется явная причина вида `'arbiters: X of t2 approvals'`. Если ВСЕ арбитры недоступны (errored — не по существу, а из-за сбоя запуска), Layer2 НЕ штрафуется: гейт опирается на L1+L3 (как при `m == 0`). Это отличает «арбитры отклонили» от «арбитры не отработали».

---

## 8. Сквозной поток (end-to-end) и границы трёх этапов

**End-to-end (по 9 пунктам видения):**

1. Пользователь выбирает локальный репо → `POST /api/v1/workspaces {repoPath}`.
2. Profiler (опенкод-агент) онбордит: детектит стек/verify-команды, пишет `.hephaestus/memory/*.md`, ставит `RepoProfile.onboarded=true`. Пользователь правит модели/strictness/ревью/verify-override через `PUT /api/v1/workspaces/{id}`.
3. Скан: `POST /api/scan/start` → `ProcessManager` запускает нативный map-reduce scan как супервизируемый процесс `scan` (нативный Python orchestration в `scan.py`; детализация в Stage 2, R19), агенты — `AgentRunner`. Находки декомпозируются в `Task` с `depends_on`/`touches`; память дописывается (`source: scan`).
4. Импорт в доску: `POST /api/scan/import/{dir}` → `Task`-ы с `order_index`/`conflict_group`. Frontend показывает порядок; reorder проходит через `task_graph` DAG-валидацию (D5).
5. Loop: `POST /api/driver/start` → `OrchestratorFSM` как супервизируемый процесс `loop` (`python -m app.orchestrator.main --workspace <id>`), внутри — собственный asyncio loop. Для каждого item: PREFLIGHT(ветка `auto/<id>`) → PROMPT_BUILD (`_build_prompt(item)`) → OPENCODE (`_run_opencode(item, prompt)` поверх `AgentRunner`) → VERIFY(`VerifyRunner`) → COMMIT(`GitService`) → PARSE_RESULT → **VALIDATE(воронка §7)** → CLEANUP. `needs_revision` петляет.
6. Итог: ветка `auto/<task>`, `diff.patch`, `summary.md` → `Task.result_summary`/`diff_ref`. Статус `done`; FSM пишет персистентный `item.verify_green` после зелёного verify.
7. Merge: `GET /api/v1/branches/{name}/merge-preflight` → `POST /api/v1/branches/{name}/merge {push}` → `GitService.merge_to_base` в `base_branch` (запрещён при `loop` RUNNING, R11). Конфликт → `{ok:false, conflicts:[...]}`.

**Границы этапов (D3):**

- **Этап 1 — Onboarding & Engine.** `Workspace`/`RepoProfile`, реестр воркспейсов, `ProcessManager`, `AgentRunner`, `VerifyRunner`, расширение `GitService`, Profiler-онбординг, миграция глобалей→workspace, удаление tmux/bash из `driver.py`/`scan.py`/`fsm.py` путей запуска. **Не включает** новую воронку и merge-UI.
- **Этап 2 — Scan, Decompose, Memory.** Нативный map-reduce scan, декомпозиция в `Task` с `depends_on`/`order_index`/`conflict_group`, `task_graph.py` (DAG + reorder-валидация), `project_memory.py` (writers `.hephaestus/memory/*.md`), reorder-API.
- **Этап 3 — Validation Funnel & Merge.** Воронка §7 (`validators`), `ValidationResult`, статусы `in_review`/`needs_revision`-петля, merge-preflight + merge-API + conflict handling, frontend merge-UI и визуализация валидации.

**FSM-контракты `_build_prompt` и `_run_opencode` (R14, R15).** Фаза PROMPT_BUILD оформлена как извлечённый метод `OrchestratorFSM._build_prompt(item) -> str` (используется и Этапом 1 в loop'е, и Этапом 3 в петле ревизий). Запуск агента — единая сигнатура во всех документах: `async def _run_opencode(self, item, prompt)` (`ws` берётся через `self._ws`, третьего аргумента нет). В `_validate` (Этап 3) используется module-singleton `from app.core.process import pm` и `AgentRunner(pm)` (или `self._pm = pm` в `__init__`); ветки `AgentRunner(None)` нет.

---

## 9. Что удаляется и миграция state

**Удаляется (D1, D7):**

- bash-скрипты: `driver.sh`, `start-loop.sh`, `verify.sh`, `tier-review.sh`, `repo-scan.sh`, `prompt-build.sh`, `lib/common.sh`.
- tmux: все `tmux new-session/has-session/kill-session/list-panes` и `pgrep`/`pkill` в `backend/app/core/driver.py`, `scan.py`, `iters.py`, `main.py` (shutdown-`pkill`). Замена — `ProcessManager`.
- pnpm-привязка верификации (`verify.sh` → `VerifyRunner` + `verify.md`).
- vendor-дефолты агентов (`sisyphus`/`atlas`/`oracle`/…) из `config.py:116-125`, `fsm.py:248,280`, `repo-scan.sh`, `tier-review.sh` → `RepoProfile.agents`.
- хардкод путей: `config.py:22 REPO=/home/starsinc/hephaestus-repo`, `config.env` Linux-пути → `RepoProfile.repo_path`.
- legacy `dashboard/` (http.server + `server.py` + статический index) — выводится из эксплуатации.
- `config.env` как central source — заменяется per-workspace `profile.json` + `state/config.json` overlay.

**Кроссплатформенный лок.** `state.py::_StateLock` сейчас no-op на Windows (`HAVE_FCNTL=False`). Поскольку bash-сторона удаляется, единственный писатель — backend; межпроцессный flock не нужен, остаётся `_thread_lock` + atomic write. Файловый лок сохраняем опционально через `msvcrt.locking` на Windows / `fcntl` на POSIX для защиты от второго инстанса backend. На Windows перед `msvcrt.locking` обязателен `self._fd.seek(0)` с блокировкой фиксированного байта offset 0 (и `seek(0)` при разблокировке) — иначе взаимного исключения нет (R13).

**Миграция `state/work-state.json` → Workspace.** Одноразовый мигратор `backend/app/core/migrate.py::migrate_legacy_state()`:
1. Если есть `state/work-state.json` и нет реестра воркспейсов — создать `Workspace` из текущих `config.REPO`/`BASE_BRANCH`/`REMOTE`/`BRANCH_PREFIX`, `id = sha256(realpath(REPO))`.
2. Переместить `state/work-state.json`, `state/iter-*`, `state/scans/*`, `state/decisions.log` под `<hephaestus_home>/workspaces/<id>/state/`.
3. Проставить `workspace_id` каждому `Task` (in-place, `extra="allow"` гарантирует совместимость).
4. Записать `profile.json` с `onboarded=false` (Profiler дозаполнит при первом запуске).
Мигратор идемпотентен; уже мигрированное состояние пропускается.

---

## 10. Глоссарий и точки стыковки этапов

**Глоссарий.**
- **Workspace** — онбординнутый локальный репозиторий + его `RepoProfile`, память, доска, история.
- **RepoProfile** — персистентные настройки воркспейса (`profile.json`).
- **Task** — единица работы (эволюция `Item`) с зависимостями/порядком/валидацией.
- **Lens** — одна перспектива валидации слоя 1 (`correctness`/`tests`/`security`/`conventions`/`scope`).
- **Funnel / воронка** — map-reduce валидация D10.
- **AgentRef** — тройка provider/model/agent для opencode.
- **conflict_group** — косметическая метка компонента задач с пересекающимися `touches` (для UI); предикат reorder — попарный, не по этой метке (R6).

### 10.1 Контракт `active_workspace()` (R4)

Единый источник активного воркспейса — `backend/app/core/workspaces.py`: класс `WorkspaceRegistry`, singleton `registry`, метод `registry.active() -> RepoProfile | None` И модульная функция-обёртка:

```python
# backend/app/core/workspaces.py
def active_workspace() -> RepoProfile | None:
    return registry.active()
```

Этап 3 импортирует `from app.core.workspaces import active_workspace, registry`. **Запрещено** использовать несуществующий модуль `app.core.workspace_registry`. Имя модуля и функции зафиксированы здесь как контракт.

**Контракты, которые Этапы 2 и 3 ОБЯЗАНЫ соблюдать (нарушение = расхождение с якорем):**

1. **Workspace-scoping.** Любой движковый вызов принимает `ws: RepoProfile` явно; запрещено читать `config.REPO`/`BASE_BRANCH`/`REMOTE`/`BRANCH_PREFIX` напрямую (они становятся свойствами активного `Workspace`).
2. **`ProcessManager`-эксклюзив.** Никакого `tmux`/`pgrep`/`pkill`/`bash`. Долгоживущие верхнеуровневые процессы (`loop`, `scan`, `profiler`) запускаются через **синхронный** `ProcessManager.start(name=...)` (PID-based, §5.1, R1). Конкурентные валидатор-агенты воронки — НЕ `ProcessManager`-сессии, а внутренние asyncio-подпроцессы оркестратора (`AgentRunner`, §7, R2).
3. **JSONL-инвариант.** Выводы агентов всегда `output.primary.jsonl`/`output.fallback.jsonl` (и `validation/layer1/<lens>.jsonl` + `validation/layer2/arbiter-<i>.json` + `validation/layer3/final.json` для воронки), парсимые `backend/app/core/events.py`. Формат не меняется.
4. **Доменные алиасы.** Новые поля `Task`/`Workspace` сериализуются camelCase через Pydantic-alias; `extra="allow"` сохраняется. Frontend `Item`/`StateSnapshot` остаются обратносовместимыми.
5. **Reorder-инвариант (D5, R6).** Этап 2 предоставляет `task_graph.can_reorder(tasks, new_order) -> (bool, reason)`; Этап 3 и UI используют тот же предикат — единственный источник истины для допустимости порядка. Предикат **попарный**: проверяет относительный исходный порядок только для пар с общим файлом (`touches ∩ != пусто`) и рёбер `depends_on` DAG; транзитивный `conflict_group` запретом reorder НЕ является.
6. **Strictness-источник истины.** Размеры слоёв/пороги воронки выводятся из `TIER_PRESETS` + effective-config; Этап 3 не вводит параллельный конфиг порогов.
7. **Memory-путь.** `.hephaestus/memory/*.md` с обязательным frontmatter (`doc`, `workspace_id`, `updated_at`, `source`, `schema`); и Profiler (Этап 1), и scan/task-writers (Этап 2) пишут через `project_memory.py`, а не напрямую.
8. **Merge-предпроверки (D11, R11).** Merge возможен только при `MergePreflight.ok` (clean tree + **персистентный** `item.verify_green` + **персистентный** `item.validation.gate == 'pass'`) И при `pm.status('loop') != RUNNING`; Этап 3 не ослабляет эти условия и не подменяет их эвристикой по префиксу статуса.
9. **Активный воркспейс (R4).** Единственный источник — `active_workspace()` / `registry.active()` из `app.core.workspaces` (§10.1). Импорт `app.core.workspace_registry` запрещён.
