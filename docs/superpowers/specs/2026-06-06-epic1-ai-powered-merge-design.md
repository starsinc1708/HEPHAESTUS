---
title: HEPHAESTUS Epic 1 — AI-Powered Merge (conflict resolution)
status: approved
date: 2026-06-06
audience: implementing engineer
language: prose=ru, identifiers/paths/commands=en
depends_on: [2026-06-05-universal-tool-overview-design, 2026-06-05-stage3-impl-loop-validation-merge-design]
defines_for: [epic1-ai-powered-merge-plan]
---

# Epic 1 — AI-Powered Merge

Закрывает фичу #5 («AI-Powered Merge»). Сейчас при конфликте merge оркестратор/UI делают
`git merge --abort` и просят человека разрулить вручную ([backend/app/core/git.py:420-429](../../backend/app/core/git.py)).
Эпик добавляет **AI-разрешение конфликтов** поверх существующего merge-потока с изоляцией в git-worktree,
verify-гейтом и человеческим Accept/Reject. Прагматичный гибрид (НЕ полный семантический движок Aperant):
`git merge` → на конфликте агент резолвит конфликтные файлы по маркерам + intent задачи → verify → review.

Решения, зафиксированные с пользователем:
- **D-merge-1.** Стратегия = прагматичный гибрид (маркеры + intent, без языковых парсеров).
- **D-merge-2.** Исполнение = отслеживаемая **MergeJob** с live-стримом (не синхронный вызов).
- **D-merge-3.** **Изоляция в worktree**: основная база НЕ остаётся в mid-merge между резолюцией и Accept.
- **D-merge-4.** Auto-accept по умолчанию ВЫКЛ (человек смотрит diff); тумблер для автономии (Ralph, Эпик 2).

Все инварианты umbrella (§10.1) соблюдаются: workspace-scoping (`ws: RepoProfile` явно), JSONL-инвариант,
camelCase-алиасы, merge запрещён при `loop RUNNING`, persistent preflight-признаки.

---

## 1. Карта компонентов

| Слой | Артефакт | Статус |
|---|---|---|
| Модель | `MergeJob`, `MergeJobStatus`, `MergeDecision` в `backend/app/models/merge.py` | новый |
| Модель | `AgentsConfig.merge: AgentRef \| None` в `backend/app/models/workspace.py` | правка |
| Модель | `Item.merge_resolution: str \| None` (alias `mergeResolution`) в `backend/app/models/domain.py` | правка |
| Ядро | `MergeResolver` в `backend/app/core/merge_resolver.py` (агент + пост-чек маркеров) | новый |
| Ядро | `MergeJobRunner` в `backend/app/core/merge_job.py` (worktree → merge → resolve → verify → события) | новый |
| Ядро | `MergeJobStore` (персист `merge-jobs.json`) в `backend/app/core/merge_job.py` | новый |
| Ядро | helpers в `backend/app/core/git.py`: `_worktree_add/_worktree_remove`, `_ff_merge`, `_current_sha` | правка |
| Промпт | `prompts/merge-resolver.md` (intent-preservation) | новый |
| API | `backend/app/api/v1/merge.py`: merge стартует job; `merge-jobs/{id}` get/accept/reject | правка |
| SSE | новый `GET /api/v1/merge-jobs/{id}/stream` (копия `iter_stream`, завершение по статусу job) | новый |
| UI | `frontend/src/components/MergeJobPanel.vue` (live + diff + Accept/Reject) | новый |
| UI | `frontend/src/components/MergeButton.vue` → старт job, открыть panel | правка |
| UI | `frontend/src/api/client.ts`, `frontend/src/types/api.ts` (методы + типы) | правка |

**Границы юнитов.** `MergeResolver` знает только «дано repo/worktree в mid-merge с конфликтами — резолвь и
проверь, что маркеров нет»; он НЕ управляет worktree/веткой/verify. `MergeJobRunner` оркестрирует всё
остальное и НЕ содержит логики резолва. `MergeJobStore` — только персист/чтение/локинг. Это разделение
делает каждый юнит тестируемым изолированно.

---

## 2. Доменная модель

`backend/app/models/merge.py` (camelCase JSON через alias, `populate_by_name=True`):

```python
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class MergeJobStatus(StrEnum):
    RUNNING = "running"        # worktree создан, идёт git merge
    RESOLVING = "resolving"    # агент резолвит конфликты
    VERIFYING = "verifying"    # VerifyRunner на смерженном дереве
    RESOLVED = "resolved"      # успех, ждёт Accept/Reject (или авто-accept)
    CONFLICT = "conflict"      # конфликт не разрешён AI → ручной фолбэк (needs_human)
    FAILED = "failed"          # ошибка (verify red, маркеры остались, git-сбой)
    ACCEPTED = "accepted"      # влито в base (терминальный)
    REJECTED = "rejected"      # отброшено, база нетронута (терминальный)


class MergeDecision(StrEnum):
    AUTO_MERGED = "auto_merged"    # git merge без конфликтов
    AI_MERGED = "ai_merged"        # конфликты разрешены агентом
    NEEDS_HUMAN = "needs_human"    # AI не справился / лимиты → ручной режим
    FAILED = "failed"


class MergeJob(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str                                                  # "merge-NNNN" (== имя dir, == ws-room)
    branch: str                                              # auto/<task> ветка-источник
    base_branch: str = Field(..., alias="baseBranch")
    status: MergeJobStatus
    decision: MergeDecision | None = None
    conflicts: list[str] = Field(default_factory=list)       # конфликтные файлы
    resolved_files: list[str] = Field(default_factory=list, alias="resolvedFiles")
    diff: str | None = None                                  # base..worktree-HEAD (для review; усечён до N КБ)
    verify_ok: bool | None = Field(None, alias="verifyOk")
    error: str | None = None
    auto_accept: bool = Field(False, alias="autoAccept")
    push: bool = False
    # internal (не для UI, но персистится для recovery/accept):
    worktree: str | None = None
    worktree_branch: str | None = Field(None, alias="worktreeBranch")
    base_sha: str | None = Field(None, alias="baseSha")      # snapshot base на момент старта (guard для ff)
    item_id: str | None = Field(None, alias="itemId")
    created_at: str | None = Field(None, alias="createdAt")
    updated_at: str | None = Field(None, alias="updatedAt")
```

Правки:
- `AgentsConfig` (`workspace.py`): `merge: AgentRef | None = None` — роль для резолва конфликтов; при `None`
  фолбэк на `primary`. Замысел: дешёвая utility-модель (haiku-класс), как у Aperant.
- `Item` (`domain.py`): `merge_resolution: str | None = Field(None, alias="mergeResolution")` —
  `"auto" | "ai" | "manual"`, пишется при Accept. `extra="allow"` уже стоит → frontend-совместимость.
- `frontend/src/types/api.ts`: добавить тип `MergeJob` (camelCase) и `mergeResolution?` в `Item`.

---

## 3. Артефакты и персист

- **Каталог job:** `_state_dir() / "merge-NNNN"`. Номер — монотонный счётчик (макс существующих `merge-*` + 1)
  под `_StateLock` — **тот же контракт, что у `iter-NNNN`** (umbrella R12, без `time.time()`). Помести хелпер
  `_next_seq_dir(prefix: str)` в `state.py` и переиспользуй его и для iter, и для merge (рефактор-возможность,
  но scope-минимально: достаточно локальной функции в `merge_job.py`, читающей `_state_dir()`).
- Внутри `merge-NNNN/`: `output.resolve.jsonl` (JSONL агента, парсится `events.py`), `verify.log`, `merge.diff`,
  `meta.json` (дамп MergeJob).
- **Реестр job:** `_state_dir() / "merge-jobs.json"` — `{"jobs": [MergeJob...]}`; чтение/запись через
  `MergeJobStore` под `_StateLock` + atomic write (как `state.py::_atomic_write`). Хранить последние ~50.
- **Worktree:** `pathlib.Path(ws.repo_path).parent / ".hephaestus-worktrees" / "merge-NNNN"` (тот же родительский
  каталог, что у воркеров FSM). Временная ветка `hephaestus/merge/<task-id>` (префикс `hephaestus/merge/`, НЕ `auto/` —
  чтобы не попадать в `branches()`/preflight и не считаться пользовательской веткой).

---

## 4. Поток MergeJobRunner

Вход: `branch` (auto/<task>), `push: bool`, `ai_resolve: bool`, `auto_accept: bool`, `ws: RepoProfile`.
Работает в backend event loop. Каждый шаг → обновление `MergeJob.status` в сторе (его читает
`GET /api/v1/merge-jobs/{id}`). Live-вывод агента — это `merge-NNNN/output.resolve.jsonl`, который агент
пишет сам (как обычные `output.*.jsonl`); UI тейлит его через SSE-эндпоинт `/api/v1/merge-jobs/{id}/stream`
(см. §6). Отдельный WS/брокер не нужен — переиспользуется проверенный SSE-механизм tailing'а JSONL.

1. **Preflight (переиспользуем).** `GitService(ws).merge_preflight(branch)`; при `loop RUNNING` или
   `ok==False` (и не только из-за `conflicts`) → вернуть ошибку до создания job (как сейчас, см. §6).
2. **Старт job.** Создать `merge-NNNN`, записать `MergeJob(status=RUNNING, baseSha=_current_sha(base))`.
3. **Worktree.** `git worktree add -b hephaestus/merge/<id> <wt> <remote>/<base>` (best-effort `git fetch` перед;
   при отсутствии remote — от локального `base`). Стартовая точка = та же, что использует обычный merge
   (`checkout base; pull --ff-only`), но в worktree, чтобы не трогать основной checkout.
4. **git merge.** В worktree: `git merge --no-ff --no-commit <branch>`.
   - rc==0 (нет конфликтов) → `decision=AUTO_MERGED`, перейти к шагу 7 (commit) → verify.
   - rc!=0 → конфликтные файлы `git diff --name-only --diff-filter=U`. Если `ai_resolve==False` или сработал
     лимит (§7) → `git merge --abort`, снести worktree, `status=CONFLICT, decision=NEEDS_HUMAN`, вернуть
     `conflicts` (ручной фолбэк UI). Иначе → шаг 5.
5. **Resolve (MergeResolver).** Для конфликтных файлов запустить агента (§5). После — пост-чек:
   нет маркеров (`<<<<<<<`/`=======`/`>>>>>>>`), `git diff --name-only --diff-filter=U` пусто. Иначе
   `git merge --abort` + worktree remove → `status=FAILED, decision=FAILED`. Успех → `git add -A`,
   `decision=AI_MERGED`, `resolved_files=<конфликтные>`.
6. **Guard изменённых файлов.** Множество изменённых (`git diff --name-only <base>..` в worktree после add)
   должно быть подмножеством (файлы ветки ∪ конфликтные). Выход за границы → `FAILED` (агент тронул лишнее).
7. **Commit merge.** `git commit --no-edit -m "merge: <subj> (from <branch>)"` в worktree (завершает merge).
8. **Verify.** `status=VERIFYING`; `VerifyRunner(ws).run(cwd=wt, log_path=merge-NNNN/verify.log, timeout=ws.verify_timeout_sec)`.
   `verify_ok=res.ok`. Red → worktree retain? нет: `status=FAILED`, worktree remove, временная ветка удаляется.
   (Verify-команды пустые → `ok=True` no-op, как в `VerifyRunner`.)
9. **Resolved.** `diff=git diff <base>..hephaestus/merge/<id>` (усечь до ~64 КБ для UI; полный — в `merge.diff`).
   `status=RESOLVED`. Worktree и временная ветка **сохраняются** до Accept/Reject.
10. **Auto-accept.** Если `auto_accept and verify_ok and decision in {AUTO_MERGED, AI_MERGED}` → сразу `accept()`.

### accept(job)
- Guard: `_current_sha(base) == job.base_sha`? Если base сдвинулся (другой merge) → `status` остаётся RESOLVED,
  вернуть `{ok:false, error:"base moved, re-run merge"}` (worktree сохраняем для повторной попытки ff после ре-merge —
  но проще: пометить FAILED и попросить ре-run; выбираем **простой путь: ошибка + retain, оператор жмёт Reject и заново**).
- `loop RUNNING`? → запрет (R11).
- В **основном** репо: `git checkout <base>`; `git merge --ff-only hephaestus/merge/<id>`. push → `git push <remote> <base>`
  (сохранить семантику push-before-delete из `_action_merge`: при push-fail НЕ удалять ветки, вернуть ошибку).
- Cleanup: `git worktree remove --force <wt>`; `git branch -D hephaestus/merge/<id>`; `git branch -D <branch>`
  (как обычный merge). `_update_item_by_branch(branch, "merged", {merged_into, merge_sha, push, mergeResolution})`.
  `mergeResolution = "ai" if decision==AI_MERGED else "auto"`. `status=ACCEPTED`. `_append_decision`.

### reject(job)
- `git worktree remove --force <wt>` + `git branch -D hephaestus/merge/<id>`. Основная база нетронута.
  `status=REJECTED`. `_append_decision("human","merge",branch,"rejected","ai-merge discarded")`.

### Reaper (старт backend)
- При инициализации: для каждого `merge-job` в реестре со `status in {RUNNING,RESOLVING,VERIFYING}` (осиротевшие
  после рестарта) → `git worktree remove --force` + `git branch -D` (best-effort) + `git worktree prune`,
  пометить `FAILED`. Стоит вызвать из lifespan `app/main.py` (или ленивым `MergeJobStore.reap()` при первом доступе).
  Переиспользовать teardown-паттерн из `fsm.py` (`git worktree remove --force; git worktree prune`).

---

## 5. MergeResolver (агент + пост-чек)

`backend/app/core/merge_resolver.py`. **Агент инжектируется** для тестируемости (как `ai_call_fn` у Aperant).

```python
class MergeResolver:
    def __init__(self, ws: RepoProfile, *, run_agent=None) -> None:
        # run_agent: async (prompt_file, cwd, output_path) -> AgentResult.
        # default: AgentRunner(pm, engine=ws.engine, env=ws.engine_env, profiles=ws.engine_profiles).run(ref, ...)
        ...
    async def resolve(self, *, worktree_cwd: str, conflicts: list[str], item: dict,
                      job_dir: pathlib.Path, timeout_sec: int) -> "ResolveOutcome":
        ...
```

- `ref = ws.agents.merge or ws.agents.primary`; `use_models=ws.agents.use_models`.
- Промпт собирается из `prompts/merge-resolver.md` + intent задачи (`item.proposal/why/acceptance`) + список
  конфликтных файлов. Инструкция (адаптация `MERGE_PROMPT_TEMPLATE` Aperant): «в каждом файле ниже разрешён
  merge-конфликт; сохрани ОБА намерения; включи все импорты; сохрани порядок хуков (более ранняя задача —
  первой/снаружи); удали ВСЕ маркеры конфликта; **редактируй файлы на месте в рабочем каталоге**; не трогай
  другие файлы». Один прогон агента на все конфликтные файлы (батч) с `cwd=worktree`.
- После прогона `MergeJobRunner` (а не resolver) делает пост-чеки. `resolve()` возвращает
  `ResolveOutcome(ok: bool, agent_exit: int, output_path)`. Маркер-скан — отдельная чистая функция
  `has_conflict_markers(text) -> bool` (юнит-тестируется без агента).
- Стрим: агент пишет `merge-NNNN/output.resolve.jsonl` напрямую (`output_path`), как в обычном
  `AgentRunner.run`. UI читает его через SSE (§6) — никакого WS-брокера/tailer'а в `MergeResolver` нет.

---

## 6. API (расширение `backend/app/api/v1/merge.py`)

Форма ответа `{ok, ...}` / `{ok:false, error}` + статус-коды как в codebase. Активный ws — через
`active_workspace()` (R4). Гард имени ветки `_guard` сохраняется.

| Метод+путь | Тело | Ответ |
|---|---|---|
| `POST /api/v1/branches/{name}/merge` | `{push, aiResolve=true, autoAccept=false}` | `{ok, jobId, status}` (job запущен) |
| `GET /api/v1/merge-jobs/{jobId}` | — | `{ok, ...MergeJob}` (camelCase) |
| `GET /api/v1/merge-jobs/{jobId}/stream` | — | SSE: tail `merge-NNNN/output.resolve.jsonl` |
| `POST /api/v1/merge-jobs/{jobId}/accept` | `{push?}` | `{ok, branch, newHead, push}` |
| `POST /api/v1/merge-jobs/{jobId}/reject` | — | `{ok}` |
| `GET /api/v1/branches/{name}/merge-preflight` | — | без изменений |

**SSE-эндпоинт (важно).** Копирует tailing-цикл `iter_stream` ([api/v1/iters.py:85](../../backend/app/api/v1/iters.py)),
НО условие завершения другое: `iter_stream` закрывается по `pm.status("loop") != RUNNING`, а merge-job
работает в backend, когда loop НЕ running. Поэтому done-условие = `MergeJob.status` достиг терминального
(`RESOLVED/CONFLICT/FAILED/ACCEPTED/REJECTED`) И файл стабилен ≥2с. Не переиспользовать `/api/iter/.../stream`
напрямую — оно закроет поток через 2с. Парсинг событий — тот же `_summarize_event` из `app.core.events`.

- `MergeRequest` (`models/validation.py`) расширяется: `ai_resolve: bool = Field(True, alias="aiResolve")`,
  `auto_accept: bool = Field(False, alias="autoAccept")` (поле `push` уже есть).
- `POST .../merge` стартует `MergeJobRunner.start(...)` как фоновую задачу (asyncio.create_task в backend loop)
  и сразу возвращает `jobId`. **Сериализация:** допускать только один НЕ-терминальный merge-job одновременно
  (иначе 409 `merge already in progress`) — два параллельных merge в один base недопустимы.
- Сохраняется поведение текущих 409: `loop active`, task-not-found, dirty tree, preflight-fail → возвращаются
  до старта job (тот же контракт, что у `merge_to_base`).
- Legacy-совместимость: текущий `merge_to_base` остаётся для обратной совместимости/быстрого пути, ИЛИ
  переключается на job-режим. **Решение:** оставить `merge_to_base` как внутренний быстрый путь для
  `decision=AUTO_MERGED` без AI; новый job-поток — основной для UI. (Минимизируем удаление рабочего кода.)

---

## 7. Безопасность и лимиты

- **Изоляция:** вся резолюция/verify — в worktree; основной `base` checkout получает изменения только при
  Accept через `--ff-only`. Reject/FAILED → база нетронута.
- **Только конфликтные файлы:** §4.6 guard на множество изменённых файлов.
- **Пост-чек маркеров** обязателен (`has_conflict_markers`).
- **Verify-гейт** обязателен; red → FAILED (не RESOLVED).
- **Лимиты (config, дефолты):** `HEPHAESTUS_MERGE_MAX_FILES=40`, `HEPHAESTUS_MERGE_MAX_FILE_BYTES=200_000`. Превышение →
  пропустить AI, `decision=NEEDS_HUMAN` (ручной фолбэк). Добавить ключи в `ALLOWED_CONFIG_KEYS` (`config.py`).
- **loop RUNNING** → merge/accept запрещены (R11), проверяется и на старте, и в accept.
- **Один активный job** на workspace (409 при попытке второго).
- **push-before-delete** семантика сохранена (push-fail → ветки не удаляются).
- **autoAccept** по умолчанию false; true только осознанно (Ralph). При true accept выполняется лишь при
  `verify_ok and decision in {AUTO_MERGED, AI_MERGED}`.
- **Таймаут агента** = `ws.verify_timeout_sec` или отдельный `HEPHAESTUS_MERGE_TIMEOUT_SEC` (дефолт 900).

---

## 8. Frontend

- `MergeButton.vue`: `doMerge()` → `api.startMerge(branch, {push, aiResolve, autoAccept})` → получает `jobId` →
  открывает `MergeJobPanel`. Старую `conflict-modal` оставить как фолбэк, когда `decision=needs_human` (AI выкл/лимит).
- `MergeJobPanel.vue` (новый): live-вывод через `LiveConsole.vue`, расширенный опциональным пропом
  `streamUrl` (дефолт — текущий `/api/iter/{dir}/stream`; для merge передаётся `/api/v1/merge-jobs/{id}/stream`).
  Статус job (`running→resolving→verifying→resolved`) поллится через `GET /api/v1/merge-jobs/{id}`;
  по `resolved` — рендер `diff`
  (моноширинный, +/- подсветка) + кнопки **Accept** (`api.acceptMerge(jobId, {push})`) / **Reject**
  (`api.rejectMerge(jobId)`) + push-тумблер. На `accepted` → `emit('merged')`. На `failed/conflict` →
  показать `error`/`conflicts` + подсказку ручного разрешения.
- `api/client.ts`: `startMerge`, `getMergeJob`, `acceptMerge`, `rejectMerge`. `types/api.ts`: `MergeJob`,
  `MergeJobStatus`, `MergeDecision`.

---

## 9. Тестирование (TDD)

**Юнит (без агента/git):**
- `has_conflict_markers()` — позитив/негатив.
- Сборка промпта `merge-resolver.md` (intent подставлен, файлы перечислены).
- `MergeJob` переходы статусов; `MergeJobStore` read/write/atomic под `_StateLock`.
- Лимиты (max files / max bytes → NEEDS_HUMAN).

**Интеграция (tmp git repo фикстура, агент застаблен):**
- Фикстура: `base` + ветка `auto/x`, конфликтующие правки одного файла. Stub-`run_agent` пишет известную
  чистую резолюцию в файл (или редактирует) + удаляет маркеры.
- happy path: start → RESOLVED, `decision=AI_MERGED`, verify запущен, diff непустой; accept → `--ff-only` в base,
  ветки удалены, Item `merged` + `mergeResolution="ai"`; worktree снесён.
- reject: worktree снесён, временная ветка удалена, base SHA не изменился.
- AUTO_MERGED: ветка без конфликта → resolved без вызова агента.
- FAILED: stub оставляет маркеры → abort, base нетронут, `status=FAILED`.
- verify red: stub-VerifyRunner возвращает ok=False → FAILED, worktree снесён.
- loop RUNNING → merge/accept запрещены (409).
- Reaper: осиротевший RUNNING job → worktree снесён, FAILED.

**Кроссплатформа:** worktree-пути и git-команды должны проходить CI на windows-latest И ubuntu-latest
(worktree add/remove, `--ff-only`, branch -D). Агент в CI — всегда stub.

---

## 10. Что НЕ входит (явно вне scope Эпика 1)

- Полный семантический merge-движок Aperant (FileAnalysis + детерминированные стратегии import/hooks/ordering)
  — отдельный эпик при необходимости. Сейчас — только маркеры + intent.
- Авто-фикс GitHub issues, создание PR/MR, changelog — Эпик 3.
- Ralph-режим, который выставит `autoAccept=true` массово — Эпик 2 (здесь лишь подготовлен тумблер).
