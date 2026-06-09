---
title: HEPHAESTUS Stage 2 — Scan → Decompose (deps + DAG) + Project Memory: Design Spec
status: design
date: 2026-06-05
audience: tool author (user) + implementing engineer
language: prose=ru, identifiers/paths/commands=en
depends_on: [2026-06-05-universal-tool-overview-design.md]
defines_for: [stage-2-scan-decompose-memory]
covers_vision: [4, 5, 6]
---

# HEPHAESTUS Stage 2 — Scan → Decompose + Memory: Design Spec

> Этот документ — **детальная спека Этапа 2**. Все общие контракты (доменные типы `Task`/`RepoProfile`/`AgentRef`, движковые интерфейсы `ProcessManager`/`AgentRunner`/`VerifyRunner`/`GitService`, API-конвенции `{ok|error}`, JSONL-инвариант, memory-путь, reorder-инвариант) определены в umbrella-спеке `docs/superpowers/specs/2026-06-05-universal-tool-overview-design.md` и **здесь не переопределяются** — только используются/реализуются. При расхождении приоритет у umbrella (§10 «Контракты»).

---

## 1. Goal

Обобщить map-reduce Scanner под любой стек (убрать HEPHAESTUS-как-цель из `prompts/scan-*.md` и `scan.py`), ввести **Decomposer** (находки → `Task` с `depends_on`/`order_index`/`conflict_group`, эпик→подзадачи) и **MemoryWriter** (генерация/обновление `<repo>/.hephaestus/memory/*.md`), реализовать на доске отображение порядка реализации и **conflict-aware reorder** с точным алгоритмом валидации перестановки, API-проверкой и причиной отказа в UI. Покрывает пункты видения 4 (скан), 5 (декомпозиция + память), 6 (порядок + safe-reorder).

---

## 2. Confirmed decisions (релевантные этому этапу)

| ID | Что обязывает Этап 2 |
|----|----------------------|
| D1 | Скан-orchestration — нативный Python через `ProcessManager.start(name="scan", ...)`; никакого `tmux`/`pgrep`/`bash repo-scan.sh`. |
| D2 | Scanner/Reducer/Decomposer/Profiler-агенты исполняются через `AgentRunner` (opencode CLI, провайдер/модель/агент из `RepoProfile.agents`); поток `output.*.jsonl` сохраняется. |
| D5 | Зависимости/конфликты — **гибрид**: LLM даёт `depends_on` (семантика), **попарное** пересечение `touches` даёт файло-конфликт (R6). Reorder валиден ⇔ не нарушает рёбра DAG `depends_on` **и** сохраняет относительный исходный порядок для **каждой пары** задач с реально общим файлом (`touches ∩ != пусто`). Конфликт — попарный, НЕ транзитивный: `conflict_group` остаётся косметической меткой компонента для UI, но предикатом допустимости порядка не является. |
| D6 | Память — md-файлы внутри целевого репо `<repo>/.hephaestus/memory/*.md` под git; пишутся через `project_memory.py`, с обязательным frontmatter. |
| D7 | Убрать из `prompts/scan-*.md` хардкод `/home/starsinc/hephaestus-repo`, pnpm/Prisma/zod-домен, security-домен по умолчанию, vendor-агентов. Бренд `HEPHAESTUS_*` и `scan-<kebab>` ID остаются. |
| D8 | Эволюционно in-place: расширяем `scan.py`, `queue.py`, `domain.py`, api-роутеры; переиспользуем `_StateLock`/`_read_state`/`_write_state`. |
| D9 | Скан/декомпозиция/память — ws-scoped: принимают `ws: RepoProfile` явно, читают `ws.repo_path`/`ws.agents`/`ws.memory_dir`, не глобали `config.REPO`. |
| D10 | (граница) `Task.validation` НЕ заполняется здесь — это Этап 3. Этап 2 только резервирует поля. |

Этап 2 **зависит** от Этапа 1: `ProcessManager`, `AgentRunner`, `RepoProfile`/реестр воркспейсов, `active_workspace()`-аксессор, миграция state. Если Этап 1 ещё не готов в момент реализации, Этап 2 использует временный шим `get_active_profile()` (см. §6 «Граничные случаи»).

---

## 3. Затрагиваемые / новые файлы

### 3.1 Новые файлы

| Путь | Назначение |
|------|-----------|
| `backend/app/core/task_graph.py` | DAG-построение и валидация: `build_graph`, `topo_order`, `assign_conflict_groups`, `can_reorder`, `apply_reorder`, `detect_cycles`. Единственный источник истины reorder-предиката (umbrella §10.5). |
| `backend/app/core/scan_run.py` | Нативный map-reduce worker внутри `scan`-процесса (R19): `chunk_files`, `run_mappers`, `run_reducers`, `dedup_findings`, `main(--dir)`. Запускается `ProcessManager.start(name="scan", ...)`; собственный asyncio loop; агенты — `AgentRunner` (промпты `scan-mapper.md`/`scan-reducer.md`). |
| `backend/app/core/decompose.py` | Decomposer: `decompose_proposals(ws, proposals, scan_dir) -> list[Task-dict]`; вызывает `AgentRunner` агентом-декомпозитором, парсит блок `DECOMPOSE_BEGIN/END`, проставляет `depends_on`/`order_index`/`conflict_group`/`epic_id`. |
| `prompts/scan-mapper.md` / `scan-reducer.md` | (модифицируются — §4.6) промпты map/reduce-фаз нативного скана; используются `scan_run.run_mappers`/`run_reducers`. |
| `backend/app/services/project_memory.py` | MemoryWriter/Reader: `read_doc`, `write_doc`, `read_verify_commands`, `update_after_scan`, `update_after_task`, `init_memory`, `_frontmatter`, `_parse_frontmatter`. |
| `backend/app/api/v1/memory.py` | Роуты `GET/PUT /api/v1/workspaces/{id}/memory/{doc}`. |
| `prompts/scan-decomposer.md` | Промпт агента-декомпозитора (схема вывода в §4.5). |
| `backend/tests/conftest.py` (новый/дополняемый) | Фикстура `tmp_state_dir` (R18): `tmp_path` + `monkeypatch` `STATE_DIR` в `app.core.state`/потребителях; используется reorder/queue/iters/scan-import тестами. Явный шаг плана, не предполагается молча. |
| `backend/tests/unit/test_task_graph.py` | Юнит-тесты DAG/reorder/conflict, включая `test_can_reorder_conflict_pairwise_not_transitive` (R6) (кроссплатформенные, без bash). |
| `backend/tests/unit/test_scan_run.py` | Юнит-тесты нативного скана (R19): `chunk_files`/`dedup_findings`/`run_mappers`/`run_reducers` (AgentRunner мокается). |
| `backend/tests/unit/test_decompose.py` | Юнит-тесты парсинга вывода декомпозитора + assignment. |
| `backend/tests/unit/test_project_memory.py` | Юнит-тесты frontmatter/read/write/verify-команд. |
| `backend/tests/integration/test_api_reorder.py` | Контрактный тест `PATCH /api/v1/tasks/{id}/reorder`. |
| `frontend/src/components/OrderBadge.vue` | Бэйдж порядка (`#order_index`) + индикатор `conflict_group` на `TaskCard`. |

### 3.2 Модифицируемые файлы (с указанием существующих символов)

| Путь | Изменение |
|------|-----------|
| `backend/app/models/domain.py` | Класс `Item` → расширить полями `workspace_id`, `depends_on`, `blocks`, `order_index`, `epic_id`, `parent`, `conflict_group`, `validation`, `result_summary`, `diff_ref` (umbrella §4.2). Сохранить `extra="allow"`, `populate_by_name=True`. |
| `backend/app/core/scan.py` | `_scan_start` — заменить `_tmux_has`/`tmux new-session` на `ProcessManager.start(name="scan", cmd=[python, -m, app.core.scan_run, --dir, <dir>], ...)`; убрать дефолт scope `"apps packages services"`. Добавить `_scan_start_native(ws, opts) -> dict` (резолвит активный `ws`, пишет `request.json`, запускает супервизируемый процесс `scan` по R1). `_scan_import` — после append прогонять `decompose_proposals` + `project_memory.update_after_scan`. |
| `backend/app/core/scan_run.py` (новый) | Нативный map-reduce **внутри** супервизируемого `scan`-процесса (R19): собственный asyncio loop; `chunk_files` → N `AgentRunner.run(scan-mapper)` → `scanner-*.findings.json`; сбор+dedup → M `AgentRunner.run(scan-reducer)` → `reducer-*.proposals.json`; финальный merge+dedup → `results.json`. CLI-вход `python -m app.core.scan_run --dir <scan_dir>`. Никакого tmux/bash. |
| `backend/app/core/queue.py` | `_queue_add`/`_scan_import`-вставка — заполнять `order_index` (хвост). Новая функция `_reorder(new_order: list[str]) -> dict` поверх `task_graph.can_reorder`/`apply_reorder`. `_queue_move_top` — переписать поверх `_reorder` (move-top = reorder с проверкой). |
| `backend/app/core/iters.py` | `build_state` — сортировать `items` по `order_index` перед отдачей; `_task_view` — добавить `depends_on`/`blocks`/`conflict_group` в ответ. |
| `backend/app/api/v1/tasks.py` | Новый роут `PATCH /api/v1/tasks/{id}/reorder` (body `ReorderRequest`); `queue_move_top` остаётся (вызывает `_queue_move_top`). |
| `backend/app/api/v1/scans.py` | `scan_start` принимает ws-context; `scan_import` после импорта возвращает `decomposed`/`order`. |
| `backend/app/models/requests.py` | Добавить `ReorderRequest`, `MemoryWriteRequest`. |
| `backend/app/main.py` | Зарегистрировать роутеры `memory.router`; убрать из shutdown `pkill opencode/verify.sh` (миграция D1 — формально Этап 1, но Этап 2 не должен полагаться на pkill). |
| `prompts/scan-mapper.md` | Обобщить: убрать `/home/starsinc/hephaestus-repo`, pnpm/Prisma/zod/otplib, секцию «Locked-decision violations» с HEPHAESTUS-снапшотом → шаблонизировать `{{repo_path}}`, `{{scope}}`, `{{tech_stack}}`, `{{memory_excerpt}}`. |
| `prompts/scan-reducer.md` | Убрать ссылку на `.claude/memory/hephaestus-tech-debt.md` → `{{tech_debt_excerpt}}`; вывод дополняется полем `depends_on_hint` (опционально). |
| `frontend/src/types/api.ts` | `Item` → добавить `dependsOn`, `blocks`, `orderIndex`, `epicId`, `parent`, `conflictGroup`, `validation?`, `resultSummary`, `diffRef`. `ItemStatus` → добавить `'in_review'`. Новый тип `ReorderResult`. |
| `frontend/src/api/client.ts` | Метод `reorderTask(id, newOrder)`; `getWorkspaceMemory`/`putWorkspaceMemory`. |
| `frontend/src/stores/board.ts` | `reorderItems(newOrder)` — оптимистично применяет порядок, при `{ok:false}` откатывает + тост с `error`. |
| `frontend/src/components/KanbanColumn.vue` | `onEnd` Sortable → вызывать `reorderItems` (а не `move-top` в обратном порядке); показывать причину отказа. Рендерить `OrderBadge`. |
| `frontend/src/components/TaskCard.vue` | Заменить хардкод `'sisyphus'` на `item.agent_override ?? '—'`; рендерить `OrderBadge` + индикатор конфликта. |
| `frontend/src/views/BoardView.vue` | `onReorder` → `board.reorderItems(ids)` вместо `api.moveTop` в обратном порядке. |

---

## 4. Ключевые контракты

### 4.1 Доменные дополнения `Task` (`backend/app/models/domain.py`)

Дословно по umbrella §4.2 (поля добавляются в существующий класс `Item`; не создаём отдельный класс — frontend-контракт `Item` сохраняется):

```python
    # --- Stage 2 additions ---
    workspace_id: str | None = Field(None, alias="workspaceId")
    depends_on: list[str] = Field(default_factory=list, alias="dependsOn")
    blocks: list[str] = Field(default_factory=list)
    order_index: int = Field(0, alias="orderIndex")
    epic_id: str | None = Field(None, alias="epicId")
    parent: str | None = None
    conflict_group: str | None = Field(None, alias="conflictGroup")
    validation: dict | None = None          # Stage 3 заполняет; Stage 2 резервирует
    result_summary: str = Field("", alias="resultSummary")
    diff_ref: str | None = Field(None, alias="diffRef")
```

Сериализация: `model_dump(by_alias=True)` (camelCase). `blocks` и `order_index` — **производные** (вычисляются Decomposer'ом/`task_graph`), но персистятся в `work-state.json` для O(1) рендера и независимости от порядка массива `items`.

### 4.2 `task_graph.py` — DAG и reorder

```python
# backend/app/core/task_graph.py
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class GraphNode:
    id: str
    depends_on: list[str]          # рёбра «X зависит от Y» (Y должен идти раньше X)
    touches: list[str]
    order_index: int
    conflict_group: str | None = None
    blocks: list[str] = field(default_factory=list)

@dataclass
class Graph:
    nodes: dict[str, GraphNode]
    # adjacency: dep -> [dependents]; обратные рёбра для топосорта
    forward: dict[str, list[str]]  # X -> [его зависимости]
    reverse: dict[str, list[str]]  # Y -> [кто зависит от Y]

def build_graph(items: list[dict]) -> Graph: ...
def detect_cycles(g: Graph) -> list[list[str]]:
    """Возвращает список циклов (каждый — список id). Пусто = ацикличен."""
def topo_order(g: Graph) -> list[str]:
    """Стабильный Kahn: тай-брейк по (order_index, id). При цикле —
    битые рёбра логируются, узлы цикла идут в конец в порядке id."""
def assign_conflict_groups(items: list[dict]) -> dict[str, str | None]:
    """id -> conflict_group — КОСМЕТИЧЕСКАЯ метка компонента для UI (R6), НЕ предикат
    reorder. Группа = connected component (union-find) по разделяемому touches-файлу
    (нормализованному). Ключ группы = 'cg-' + sha1(sorted(member_ids))[:8]. Одиночка → None."""
def can_reorder(items: list[dict], new_order: list[str]) -> tuple[bool, str]:
    """Единственный источник истины (umbrella §10.5). Файло-конфликт ПОПАРНО, НЕ
    транзитивно (R6): проверяет пары с общим файлом + рёбра depends_on DAG. См. псевдокод ниже."""
def apply_reorder(items: list[dict], new_order: list[str]) -> list[dict]:
    """Возвращает копию items с переписанными order_index согласно new_order
    (для id вне new_order сохраняет относительный хвост)."""
```

**Нормализация touches.** Файло-конфликт сравнивает только путь, без `:LINE`-суффикса и с приведением к posix-форме нижним регистром на Windows:

```python
def _norm_touch(t: str) -> str:
    path = t.split(":", 1)[0].strip().replace("\\", "/")
    return os.path.normpath(path).replace("\\", "/").casefold()
```

**Псевдокод `assign_conflict_groups` (union-find по файлам — КОСМЕТИЧЕСКАЯ метка для UI, R6; reorder её НЕ использует):**

```
file_to_ids: dict[str, list[str]] = {}
for it in items:
    for t in it["touches"]:
        file_to_ids.setdefault(_norm_touch(t), []).append(it["id"])
uf = UnionFind(all_ids)
for ids in file_to_ids.values():
    for j in range(1, len(ids)):
        uf.union(ids[0], ids[j])
groups: dict[root, list[id]] = bucket ids by uf.find(id)
result = {}
for root, members in groups.items():
    if len(members) <= 1:           # одиночка — не в конфликт-группе
        result[members[0]] = None
    else:
        key = "cg-" + sha1(",".join(sorted(members)).encode()).hexdigest()[:8]
        for m in members: result[m] = key
return result
```

**Псевдокод `can_reorder` (точный алгоритм валидации перестановки — D5, ПОПАРНО по R6):**

```
def can_reorder(items, new_order):
    by_id = {it["id"]: it for it in items}
    # 0. new_order должен быть перестановкой текущих id ровно (без добавления/потери)
    if set(new_order) != set(by_id):
        return (False, "reorder set mismatch: ids added or dropped")

    pos = {id_: i for i, id_ in enumerate(new_order)}   # целевая позиция

    # 1. DAG-инвариант: для каждого ребра depends_on (X зависит от dep),
    #    dep ОБЯЗАН стоять раньше X.
    for it in items:
        x = it["id"]
        for dep in it.get("dependsOn", []):
            if dep not in by_id:        # висячая зависимость — игнор (см. §6)
                continue
            if pos[dep] > pos[x]:
                return (False,
                  f"reorder breaks dependency {dep} before {x}")

    # 2. Файло-конфликт ПОПАРНО, НЕ транзитивно (R6, D5):
    #    проверяем относительный исходный порядок ТОЛЬКО для пар задач с реально
    #    общим файлом (touches ∩ != пусто). Если A∩B != пусто и B∩C != пусто, но
    #    A∩C == пусто — A и C переставлять МОЖНО (транзитивную компоненту union-find
    #    как запрет НЕ используем). Для каждой конфликтной пары (a,b), где в ИСХОДНОМ
    #    порядке a раньше b, в new_order a тоже обязан быть раньше b.
    #    (Их diff'ы конкурируют за одни файлы — порядок определяет, кто базируется
    #     на чьём результате.)
    norm = {it["id"]: {_norm_touch(t) for t in (it.get("touches") or [])} for it in items}
    def _orig_rank(i):                  # исходный порядок: (order_index, id)
        return (by_id[i].get("orderIndex", 0), i)
    ids = list(by_id)
    for a in ids:
        for b in ids:
            if a >= b:                  # каждую неупорядоченную пару — один раз
                continue
            if not (norm[a] & norm[b]):  # нет общего файла — пара свободна
                continue
            # эталон: кто раньше в исходном порядке, тот должен остаться раньше
            first, second = (a, b) if _orig_rank(a) < _orig_rank(b) else (b, a)
            if pos[first] > pos[second]:
                return (False,
                  f"reorder violates conflict order: {first} must stay before "
                  f"{second} (shared files)")

    return (True, "")
```

`_norm_touch` (см. ниже) нормализует путь (срез `:LINE`, posix lower-case) — пересечение множеств `norm[a] & norm[b]` даёт «есть ли общий файл». Предикат проверяет каждую конфликтную ПАРУ независимо; `assign_conflict_groups`/`conflict_group` здесь НЕ участвуют (они только косметическая метка для UI, R6).

`apply_reorder` после успешной валидации перезаписывает `order_index = pos[id]` каждому item; `topo_order` НЕ вызывается на reorder (пользовательский порядок — авторитетен, если прошёл `can_reorder`). `topo_order` вызывается только при импорте/декомпозиции для **первичной** раскладки.

### 4.3 `decompose.py` — Decomposer

```python
# backend/app/core/decompose.py
async def decompose_proposals(
    ws: "RepoProfile",
    proposals: list[dict],
    *,
    scan_dir: str,
    runner: "AgentRunner",
    decomposer_ref: "AgentRef | None" = None,
) -> list[dict]:
    """Из reducer-proposals строит список Task-dict'ов (готовых к вставке в queue).
    Шаги:
      1. Если proposals пуст → [].
      2. Построить prompt из prompts/scan-decomposer.md (см. §4.5), inject:
         {{proposals_json}}, {{repo_path}}, {{memory_excerpt}}.
      3. runner.run(decomposer_ref or ws.agents.primary, ...) → output.jsonl.
      4. Распарсить блок DECOMPOSE_BEGIN/END (JSON). При parse-fail →
         FALLBACK: 1:1 проекция каждого proposal в Task без depends_on/epic
         (graceful degradation — скан не теряется).
      5. Слить LLM-вывод с исходными proposals по id; для эпиков создать
         родительский Task (status=pending, epic_id=None) + подзадачи
         (epic_id=<epic>, parent=<epic>).
      6. assign_conflict_groups → conflict_group каждому.
      7. build_graph + topo_order → order_index (стабильный).
      8. Вернуть список Task-dict (camelCase-ready: dependsOn/orderIndex/...).
    Никаких глобалей: всё из ws."""
```

Decomposer **не пишет state сам** — возвращает список, `_scan_import` вставляет под `_StateLock` (единственный писатель). `decomposer_ref` по умолчанию `ws.agents.primary` (отдельного vendor-агента не хардкодим).

**Слияние эпик→подзадачи.** Если LLM пометил proposal как `"epic": true` со списком `subtasks`, Decomposer создаёт:
- родителя `id = proposal.id` (`epic_id=None`, `parent=None`, `touches = union(subtask.touches)`),
- подзадачи `id = f"{proposal.id}-{n}"` (`epic_id=proposal.id`, `parent=proposal.id`).
Родитель получает `depends_on = []`; подзадачи — `depends_on` из LLM-вывода (внутри эпика) плюс неявно ничего к родителю (родитель — контейнер, не блокер).

### 4.4 `project_memory.py` — MemoryWriter/Reader

```python
# backend/app/services/project_memory.py
DOCS = ("index", "architecture", "verify", "conventions", "tech-debt")
_FILENAME = {"index": "MEMORY.md", "architecture": "architecture.md",
             "verify": "verify.md", "conventions": "conventions.md",
             "tech-debt": "tech-debt.md"}

def memory_dir(ws: "RepoProfile") -> pathlib.Path:
    return pathlib.Path(ws.repo_path) / ws.memory_dir   # <repo>/.hephaestus/memory

def read_doc(ws, doc: str) -> str | None: ...
def write_doc(ws, doc: str, body: str, *, source: str) -> pathlib.Path:
    """Пишет <repo>/.hephaestus/memory/<file> с frontmatter (doc/workspace_id/
    updated_at/source/schema=1) + body; atomic write; обновляет MEMORY.md индекс."""
def read_verify_commands(ws) -> list[str]:
    """Парсит verify.md: блок ```sh ... ``` под '## commands' → список команд
    (по одной на строку, без пустых/комментов). Пусто → []."""
def init_memory(ws, *, architecture: str, verify_commands: list[str],
                conventions: str, tech_debt: str) -> None:
    """Профайлер-онбординг (Этап 1 вызывает; Этап 2 предоставляет реализацию)."""
def update_after_scan(ws, *, scan_dir: str, proposals: list[dict]) -> None:
    """Дописывает tech-debt.md разделом '## from scan <scan_dir>' с найденными
    high/security/bug-пунктами; обновляет updated_at в architecture.md если
    скан затронул новые модули. source='scan'."""
def update_after_task(ws, *, task: dict, summary: str) -> None:
    """После done-задачи: дописывает conventions.md если введён новый паттерн,
    снимает закрытый пункт из tech-debt.md. source='task'."""
```

**Frontmatter (запись/чтение):**

```python
def _frontmatter(doc: str, ws_id: str, source: str) -> str:
    return (f"---\ndoc: {doc}\nworkspace_id: {ws_id}\n"
            f"updated_at: {utcnow_iso()}\nsource: {source}\nschema: 1\n---\n")

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Возвращает (meta-dict, body-без-frontmatter). Нет frontmatter → ({}, text)."""
```

`write_doc` **идемпотентно перезаписывает** документ целиком (не append-в-середину), кроме секций-append, формируемых вызывающим (`update_after_scan` сам собирает новый body из старого + новой секции, затем `write_doc`). **Память держится КОРОТКОЙ** (research, ETH Zurich по AGENTS.md, 2026): целевой потолок каждого md ≤ ~150 строк; `update_after_scan`/`update_after_task` дедуплицируют и усекают добавляемые секции (хранят последние N / самые severe), а не накапливают бесконечно — длинная/очевидная память снижает success rate агентов.

### 4.5 Промпт-схема Decomposer (`prompts/scan-decomposer.md`)

Переменные `{{proposals_json}}`, `{{repo_path}}`, `{{memory_excerpt}}` (инжектятся `_VAR_RE` из `prompt_manager.py`). Тело инструктирует агента (read-only: `read`/`grep`/`glob`) разметить порядок и зависимости. **Обязательный блок вывода:**

```
DECOMPOSE_BEGIN
{
  "tasks": [
    {
      "id": "scan-<kebab>",            // совпадает с proposal.id или новый для эпика-подзадачи
      "epic": false,                    // true → есть subtasks
      "subtasks": [],                   // при epic=true: [{ "id","title","proposal","touches","dependsOn" }]
      "dependsOn": ["scan-other-id"],   // СЕМАНТИЧЕСКИЕ зависимости (D5): этот task требует тех
      "reason": "<1 предложение: почему зависит>"
    }
  ]
}
DECOMPOSE_END
```

**Контракт парсинга (`decompose.py`):** ищем последний `DECOMPOSE_BEGIN ... DECOMPOSE_END`, `json.loads` середины. `dependsOn`-id, которых нет среди proposals/подзадач, отбрасываются (висячие). Циклы, привнесённые LLM, разрываются `detect_cycles` + удалением последнего ребра цикла (лог `WARNING`). Никаких vendor-имён в промпте; стек берётся из `{{memory_excerpt}}` (architecture.md).

### 4.6 Обобщение `prompts/scan-mapper.md` / `scan-reducer.md`

Удаляются: `/home/starsinc/hephaestus-repo`, `pnpm`, `Prisma`, `zod`, `otplib`, `@hephaestus/server`, секция «Locked-decision violations» с конкретным HEPHAESTUS-снапшотом, список «inherited noise» из `hephaestus-tech-debt.md`. Заменяются переменными:
- mapper: `{{repo_path}}`, `{{scope}}`, `{{chunk}}` (список файлов слайса), `{{tech_stack}}`, `{{memory_excerpt}}` (architecture+conventions выдержка), `{{tech_debt_excerpt}}` (что НЕ флагать).
- reducer: `{{all_findings}}`, `{{tech_debt_excerpt}}`. Категория `locked-decision` остаётся в enum (универсально применима: репо может иметь свои locked-decisions в conventions.md), но привязка к HEPHAESTUS-снапшоту убрана. Выходной блок `SCAN_FINDINGS_*`/`SCAN_PROPOSAL_*` и ID-схема `scan-<kebab>` сохраняются (D7 — бренд-неймспейс).

### 4.6a `scan_run.py` — нативный map-reduce внутри `scan`-процесса (R19, D1)

`_scan_start_native(ws, opts)` (backend, sync) пишет `state/scans/scan-<ts>/request.json` и запускает супервизируемый процесс `scan` через `ProcessManager.start(name="scan", cmd=[sys.executable, "-m", "app.core.scan_run", "--dir", "scan-<ts>"], cwd, env)` (R1 — никакого `tmux`/`bash repo-scan.sh`). **Внутри** процесса `scan_run.main` поднимает собственный единый asyncio loop и гоняет map→reduce через `AgentRunner` (R1/R2: каждый агент пишет в уникальный `output_path`, общего `session_name` нет).

```python
# backend/app/core/scan_run.py
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import pathlib
import sys

log = logging.getLogger("hephaestus.backend.scan_run")


def chunk_files(repo_path: str, scope: str, n: int) -> list[list[str]]:
    """Walk scope dirs under repo_path, collect candidate source files, split into n chunks
    (round-robin for size balance). Skips VCS/build/vendor dirs. Pure stdlib, cross-platform."""
    root = pathlib.Path(repo_path)
    skip = {".git", ".hephaestus", "node_modules", "dist", "build", "__pycache__", ".venv", "venv"}
    seg = [s for s in scope.split() if s and ".." not in s]
    files: list[str] = []
    for s in seg:
        base = (root / s)
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and not (set(p.parts) & skip):
                files.append(str(p.relative_to(root)).replace("\\", "/"))
    files.sort()
    chunks: list[list[str]] = [[] for _ in range(max(1, n))]
    for i, f in enumerate(files):
        chunks[i % len(chunks)].append(f)
    return [c for c in chunks if c]


def dedup_findings(items: list[dict]) -> list[dict]:
    """Merge duplicates by (normalized title, sorted normalized touches). Bumps agreement_count."""
    from app.core.task_graph import _norm_touch

    seen: dict[tuple, dict] = {}
    for it in items:
        key = (
            (it.get("title", "") or "").strip().casefold(),
            tuple(sorted(_norm_touch(t) for t in (it.get("touches") or []))),
        )
        if key in seen:
            seen[key]["agreement_count"] = int(seen[key].get("agreement_count", 1) or 1) + 1
        else:
            it = dict(it)
            it.setdefault("agreement_count", 1)
            seen[key] = it
    return list(seen.values())


async def run_mappers(ws, runner, scan_dir: pathlib.Path, chunks: list[list[str]],
                      *, prompt_mgr, timeout_sec: int) -> list[dict]:
    """N concurrent scan-mapper agents, one per chunk. Each writes scanner-<i>.findings.jsonl."""
    # parse_findings_block — локальный парсер блока SCAN_FINDINGS_*, определён в этом же
    # модуле scan_run.py (НЕ в app.core.events — там его нет). См. план Stage 2.

    async def _one(i: int, chunk: list[str]) -> list[dict]:
        prompt = prompt_mgr.render_prompt("scan-mapper", {
            "repo_path": ws.repo_path, "scope": " ".join(sorted({c.split('/')[0] for c in chunk})),
            "chunk": "\n".join(chunk), "tech_stack": "", "memory_excerpt": "",
            "tech_debt_excerpt": "",
        }) or ""
        pf = scan_dir / f"scanner-{i}.prompt.md"
        pf.write_text(prompt, encoding="utf-8")
        out = scan_dir / f"scanner-{i}.findings.jsonl"
        await runner.run(ws.agents.primary, prompt_file=pf, cwd=ws.repo_path,
                         output_path=out, timeout_sec=timeout_sec)
        return parse_findings_block(out.read_text(encoding="utf-8")) if out.exists() else []

    results = await asyncio.gather(*[_one(i, c) for i, c in enumerate(chunks)],
                                   return_exceptions=True)
    findings: list[dict] = []
    for r in results:
        if isinstance(r, Exception):
            log.warning("mapper failed: %s", r)
            continue
        findings.extend(r)
    return findings


async def run_reducers(ws, runner, scan_dir: pathlib.Path, findings: list[dict],
                       *, reducers: int, prompt_mgr, timeout_sec: int) -> list[dict]:
    """M concurrent scan-reducer agents over sharded findings. Each writes reducer-<j>.proposals.jsonl."""
    # parse_proposals_block — локальный парсер блока SCAN_PROPOSAL_* в scan_run.py (НЕ в app.core.events).

    shards: list[list[dict]] = [[] for _ in range(max(1, reducers))]
    for i, f in enumerate(findings):
        shards[i % len(shards)].append(f)

    async def _one(j: int, shard: list[dict]) -> list[dict]:
        prompt = prompt_mgr.render_prompt("scan-reducer", {
            "all_findings": json.dumps(shard, ensure_ascii=False, indent=2),
            "tech_debt_excerpt": "",
        }) or ""
        pf = scan_dir / f"reducer-{j}.prompt.md"
        pf.write_text(prompt, encoding="utf-8")
        out = scan_dir / f"reducer-{j}.proposals.jsonl"
        await runner.run(ws.agents.primary, prompt_file=pf, cwd=ws.repo_path,
                         output_path=out, timeout_sec=timeout_sec)
        return parse_proposals_block(out.read_text(encoding="utf-8")) if out.exists() else []

    results = await asyncio.gather(*[_one(j, s) for j, s in enumerate(shards) if s],
                                   return_exceptions=True)
    proposals: list[dict] = []
    for r in results:
        if isinstance(r, Exception):
            log.warning("reducer failed: %s", r)
            continue
        proposals.extend(r)
    return proposals


async def _run(scan_dir: pathlib.Path) -> int:
    from app.core.process import pm
    from app.services.opencode_runner import AgentRunner
    from app.services.prompt_manager import PromptManager
    from app.core.ws_shim import get_active_profile

    req = json.loads((scan_dir / "request.json").read_text(encoding="utf-8"))
    ws = get_active_profile()
    runner = AgentRunner(pm)
    prompt_mgr = PromptManager()
    chunks = chunk_files(ws.repo_path, req["scope"], int(req.get("scanners", 6)))
    findings = dedup_findings(
        await run_mappers(ws, runner, scan_dir, chunks, prompt_mgr=prompt_mgr, timeout_sec=900)
    )
    proposals = dedup_findings(
        await run_reducers(ws, runner, scan_dir, findings,
                           reducers=int(req.get("reviewers", 2)), prompt_mgr=prompt_mgr, timeout_sec=900)
    )
    (scan_dir / "results.json").write_text(
        json.dumps({"proposals": proposals, "n_unique": len(proposals)}, ensure_ascii=False),
        encoding="utf-8",
    )
    return 0


def main() -> int:
    from app.config import STATE_DIR

    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    args = ap.parse_args()
    scan_dir = STATE_DIR / "scans" / args.dir
    return asyncio.run(_run(scan_dir))


if __name__ == "__main__":
    sys.exit(main())
```

`parse_findings_block`/`parse_proposals_block` — переиспользуемые парсеры `SCAN_FINDINGS_*`/`SCAN_PROPOSAL_*` (живут рядом с `backend/app/core/events.py`; если их там нет — добавляются в Этапе 1 вместе с `AgentRunner`-стримом, Этап 2 опирается на их сигнатуру). До слияния Этапа 1 (`pm`/`AgentRunner` отсутствуют) `_scan_start_native` graceful-fallback'ится: если импорт `ProcessManager`/`AgentRunner` падает — возвращает `{"ok": False, "error": "native scan requires Stage 1 runner"}` (никакого `tmux`).

### 4.7 API-контракты

```python
# backend/app/models/requests.py
class ReorderRequest(BaseModel):
    order: list[str]                 # полный новый порядок id (перестановка)

class MemoryWriteRequest(BaseModel):
    content: str
```

```python
# backend/app/api/v1/tasks.py — новый роут
@router.patch("/api/v1/tasks/{item_id}/reorder")
def reorder_task(item_id: str, body: ReorderRequest) -> dict:
    return _reorder(body.order)      # _queue._reorder; см. §4.8
```

Ответ при успехе: `{"ok": true, "order": [<id...>]}`. При нарушении (umbrella §6):
`{"ok": false, "error": "reorder breaks dependency <X> before <Y>"}` (или `... violates conflict order ...`), статус 400 через `error_response`.

```python
# backend/app/api/v1/memory.py
@router.get("/api/v1/workspaces/{ws_id}/memory/{doc}")
def get_memory(ws_id: str, doc: str) -> dict:
    # doc ∈ project_memory.DOCS, иначе 400
    # ws = registry.get(ws_id) или active-shim; read_doc → {"ok":True,"content":..}

@router.put("/api/v1/workspaces/{ws_id}/memory/{doc}")
def put_memory(ws_id: str, doc: str, body: MemoryWriteRequest) -> dict:
    # write_doc(ws, doc, body.content, source="manual")
```

`{item_id}` в `reorder_task` сохранён в пути для REST-симметрии/будущего «вставить этот id в позицию», но валидируется как принадлежащий `body.order`.

### 4.8 `queue._reorder` (поверх `task_graph`)

```python
# backend/app/core/queue.py
def _reorder(new_order: list[str]) -> dict:
    from app.core.task_graph import can_reorder, apply_reorder
    with _StateLock():
        s = _read_state()
        items = s.get("items", [])
        ok, reason = can_reorder(items, new_order)
        if not ok:
            return {"ok": False, "error": reason}
        s["items"] = apply_reorder(items, new_order)
        _write_state(s)
    _try_broadcast_state()
    return {"ok": True, "order": new_order}
```

`_queue_move_top(qid)` переписывается: построить `new_order` = `[qid] + [i for i in current_order if i != qid]`, вызвать `_reorder`. Если `can_reorder` отказывает (move-top нарушит зависимость/конфликт) — вернуть отказ с причиной (а не молча переставить).

### 4.9 Frontend-контракты

`frontend/src/types/api.ts`: `ItemStatus` += `'in_review'`; `Item` += `dependsOn: string[]`, `blocks: string[]`, `orderIndex: number`, `epicId: string | null`, `parent: string | null`, `conflictGroup: string | null`, `validation?: Record<string, unknown> | null`, `resultSummary: string`, `diffRef: string | null`.

```ts
export interface ReorderResult { ok: boolean; order?: string[]; error?: string }
```

`client.ts` (R8 — фактическая сигнатура `request<T>(path, init?)`; метод/тело через `init`, НЕ позиционная форма `request('PATCH', path, body)`):
```ts
reorderTask: (order: string[]) =>
  request<ReorderResult>(`/api/v1/tasks/${order[0] ?? '_'}/reorder`, {
    method: 'PATCH',
    body: JSON.stringify({ order }),
  }),
getWorkspaceMemory: (wsId: string, doc: string) =>
  request<{ ok: boolean; content: string }>(`/api/v1/workspaces/${wsId}/memory/${doc}`),
putWorkspaceMemory: (wsId: string, doc: string, content: string) =>
  request<{ ok: boolean }>(`/api/v1/workspaces/${wsId}/memory/${doc}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  }),
```

`board.ts` `reorderItems(newOrder: string[])`: snapshot текущих `items`, оптимистично переставить по `newOrder`, `await api.reorderTask(newOrder)`; при `res.ok === false` — откат к snapshot + `toast.add('error', res.error)`; при успехе — `await fetchState()`.

`OrderBadge.vue`: props `{ orderIndex: number; conflictGroup: string | null }`. Рендерит `#<orderIndex+1>` (1-based для людей) и, если `conflictGroup`, цветную точку `var(--amber)` с `title="Конфликт файлов: порядок зафиксирован"`.

`KanbanColumn.vue` `onEnd`: `emit('reorder', sortable.toArray())` (полный порядок pending-колонки) → `BoardView.onReorder` → `board.reorderItems`. Перетаскивание задач из `conflict_group` визуально допустимо, но бэк вернёт отказ → откат + тост (UI не дублирует логику — umbrella §10.5).

**Визуализация зависимостей (R21).** На `TaskCard.vue` и в `TaskDrawer.vue` зависимости показываются **чипами**: `dependsOn` (входящие, «требует») и `blocks` (исходящие, «блокирует») как компактные id-чипы, плюс `OrderBadge` с точкой `conflict_group` (амбер, при наличии). Чип-зависимости — чисто информационные (клик опционально подсвечивает связанную карту по id; навигации-графа нет). **Полноценный граф-вью DAG (force-directed/визуальное дерево зависимостей) — out of scope текущего этапа, помечен как будущее** (§10): сейчас достаточно чипов + порядкового бэйджа; отдельный граф-компонент не вводится. `TaskDrawer.vue` дополняется блоком «Dependencies» только если `item.dependsOn.length || item.blocks.length` — без новых API-вызовов (данные уже в `item`).

---

## 5. Поток данных (Этап 2)

```
[UI ToolsView] POST /api/scan/start {scope}            # legacy-путь, R10
   │
   ▼
scan._scan_start_native(ws, opts)                      # backend, sync
   │  пишет state/scans/scan-<ts>/request.json {repo_path, scope, scanners, reviewers}
   │  ProcessManager.start(name="scan",
   │      cmd=[sys.executable, "-m", "app.core.scan_run", "--dir", "scan-<ts>"],
   │      cwd=<backend>, env=...)                       # супервизируемый процесс (R1)
   ▼
scan_run.main(--dir)  →  один asyncio loop ВНУТРИ scan-процесса (R1):   # R19
   files   = chunk_files(ws.repo_path, scope, n=SCANNERS)   # списки путей-слайсов
   mappers = await asyncio.gather(*[
                AgentRunner(pm).run(ws.agents.primary,
                    prompt_file=scan-mapper(chunk_i), cwd=ws.repo_path,
                    output_path=scan-<ts>/scanner-<i>.findings.jsonl, timeout_sec=...)
             ])                                            # N конкурентных мапперов
   findings = dedup_findings(collect(scanner-*.findings.jsonl))   # по (title, touches)
   reducers = await asyncio.gather(*[
                AgentRunner(pm).run(ws.agents.primary,
                    prompt_file=scan-reducer(findings_shard_j), cwd=ws.repo_path,
                    output_path=scan-<ts>/reducer-<j>.proposals.jsonl, timeout_sec=...)
             ])                                            # M конкурентных редьюсеров
   proposals = dedup_findings(collect(reducer-*.proposals.jsonl))
   write results.json {proposals, n_unique}              # вход для _scan_import
   │   (каждый агент — уникальный output_path; общего session_name нет, R1/R2)
   ▼
[UI] POST /api/scan/import/{dirname} {ids}
   │
   ▼
scan._scan_import(dir, ids):
   under _StateLock:
     proposals = results.json.filter(ids)
     tasks = await decompose.decompose_proposals(ws, proposals, scan_dir=dir, runner)
              → depends_on (LLM) + conflict_group (touches) + order_index (topo)
     s["items"] += tasks ;  _write_state(s)
   project_memory.update_after_scan(ws, scan_dir=dir, proposals=proposals)   # tech-debt.md
   broadcast_state()
   │
   ▼
[UI Board] GET /api/state → items отсортированы по orderIndex
   TaskCard: OrderBadge(#order) + conflict-dot
   drag in pending → board.reorderItems(newOrder)
        → PATCH /api/v1/tasks/{id}/reorder
        → can_reorder() ? apply_reorder()+write : {ok:false, error:<reason>}
        → UI: success → refetch ; fail → откат + тост(reason)
```

Память при онбординге (Этап 1 триггерит, Этап 2 реализует writer): `init_memory(ws, ...)` создаёт `architecture.md`/`verify.md`/`conventions.md`/`tech-debt.md`/`MEMORY.md`. После каждого `done`-таска FSM (Этап 1/3) зовёт `update_after_task`.

---

## 6. Обработка ошибок и граничные случаи

| Случай | Поведение |
|--------|-----------|
| Decomposer parse-fail (нет `DECOMPOSE_*` блока / битый JSON) | FALLBACK 1:1: каждый proposal → Task без `depends_on`/`epic`; `order_index` = хвостовая раскладка по исходному порядку proposals. Лог `WARNING`, скан не теряется. |
| LLM привнёс цикл в `depends_on` | `detect_cycles` находит цикл; `topo_order` разрывает последнее ребро цикла, кладёт узлы цикла в конец по `id`; лог `WARNING` с перечислением узлов. |
| Висячая зависимость (`dependsOn` ссылается на id, которого нет в очереди) | Игнорируется в `can_reorder` (continue) и в `build_graph` (ребро не добавляется). Не блокирует reorder. |
| `new_order` ≠ перестановка текущих id | `can_reorder → (False, "reorder set mismatch: ids added or dropped")`, 400. Защита от рассинхрона UI/бэк. |
| Пустой scope в `_scan_start` | Ошибка `{"ok": False, "error": "scope is required"}` — убран дефолт `"apps packages services"` (D7). Frontend ToolsView делает scope обязательным. |
| scope с shell-метасимволами | Существующая проверка `re.match(r"^[A-Za-z0-9_./\- ]{1,200}$", scope)` сохраняется (но теперь scope не идёт в shell — передаётся как Python-список путей; проверка остаётся как защита от path-traversal `..`). Дополнительно: каждый сегмент проверяется `".." not in seg`. |
| `touches` с `:LINE` и backslash (Windows) | `_norm_touch` срезает `:LINE`, приводит к posix lower-case → конфликт-группы стабильны кросс-платформенно. |
| `_scan_import` дважды по тем же id | Существующая дедуп-логика (`pid in existing_ids → skipped`) сохраняется; Decomposer запускается только на новых. |
| `memory_dir` не существует | `write_doc`/`init_memory` создают `<repo>/.hephaestus/memory/` (`mkdir(parents=True, exist_ok=True)`). Файлы под git целевого репо — коммитятся пользователем/FSM, не бэкендом. |
| `read_verify_commands` без `## commands` блока | Возвращает `[]` → VerifyRunner трактует как no-op (umbrella §5.3), не падает. |
| `ws_id` в memory-роуте не в реестре | 400 `{"ok": False, "error": "unknown workspace"}`. До готовности Этапа 1 — шим `get_active_profile()` возвращает профиль из `config.REPO`/дефолтов (см. ниже). |
| Этап 1 ещё не слит (нет реестра/`active_workspace`) | Временный `backend/app/core/ws_shim.py::get_active_profile() -> RepoProfile`, собирающий профиль из текущих `config.REPO`/`BASE_BRANCH`/`REMOTE`/`BRANCH_PREFIX` + дефолтных `AgentsConfig` из effective-config. **Когда Этап 1 слит (R4):** `get_active_profile` сначала пытается делегировать в единый источник — `from app.core.workspaces import active_workspace` и вернуть `active_workspace()`, если он не `None`; иначе — старый локальный билд из глобалей. Импорт `app.core.workspace_registry` ЗАПРЕЩЁН (umbrella §10.1). Шим удаляется целиком, когда роутеры переведены на `active_workspace()`/`registry.active()` напрямую. Все Этап-2-функции принимают `ws` явно — шим только в роутерах. |
| Конкурентный reorder + scan-import | Оба под `_StateLock` (единственный писатель — backend); сериализуются. |
| `order_index` коллизии после ручных правок | `apply_reorder` всегда перезаписывает индексы плотно `0..n-1`; `build_state` сортирует по `(orderIndex, id)` — детерминированно. |

---

## 7. Тестирование (кроссплатформенно, без bash)

Все тесты — `pytest`, запускаются на Windows/macOS/Linux. Никаких `flock`/`tmux`/`bash`-зависимостей; subprocess/AgentRunner мокаются.

### 7.1 `backend/tests/unit/test_task_graph.py`

- `test_topo_order_respects_deps` — A→B→C (C dep B dep A): порядок `[A,B,C]`.
- `test_topo_order_stable_tiebreak` — независимые узлы сортируются по `(order_index, id)`.
- `test_detect_cycles` — A↔B возвращает один цикл; ацикличный граф → `[]`.
- `test_assign_conflict_groups_shared_file` — два таска c общим `src/x.py` → одна `cg-*`; нормализация `src/x.py:42` ≡ `src\x.py`.
- `test_conflict_group_singleton_none` — таск без пересечений → `conflict_group is None`.
- `test_can_reorder_ok` — допустимая перестановка независимых задач → `(True, "")`.
- `test_can_reorder_breaks_dependency` — поставить `dep` после зависимого → `(False, "reorder breaks dependency ...")`.
- `test_can_reorder_conflict_order` — поменять местами два таска с реально общим файлом → `(False, "... violates conflict order ...")`.
- `test_can_reorder_conflict_pairwise_not_transitive` (R6) — A∩B по `x.py`, B∩C по `y.py`, но A∩C пусто: перестановка A и C (с сохранением порядка относительно B) → `(True, "")`. Транзитивная компонента union-find НЕ запрещает reorder.
- `test_can_reorder_set_mismatch` — `new_order` с лишним/потерянным id → `(False, "reorder set mismatch ...")`.
- `test_can_reorder_dangling_dep_ignored` — `dependsOn` на отсутствующий id не блокирует.
- `test_apply_reorder_dense_indices` — после reorder `order_index` = `0..n-1` без дыр.
- `test_norm_touch_windows` — `"a\\B.py:10"` и `"a/b.py"` нормализуются одинаково (запуск на любой ОС, без реального FS).

### 7.2 `backend/tests/unit/test_decompose.py`

- `test_parse_decompose_block` — извлечение последнего `DECOMPOSE_BEGIN/END`, корректный JSON.
- `test_decompose_fallback_on_bad_json` — битый блок → 1:1 проекция, без исключения.
- `test_epic_expansion` — `epic:true` + 2 subtasks → родитель + 2 подзадачи с `epic_id`/`parent`.
- `test_dangling_depends_dropped` — `dependsOn` на несуществующий id отбрасывается.
- `test_llm_cycle_broken` — привнесённый цикл разрывается, лог WARNING, выход ацикличен.
- AgentRunner мокается (фиктивный `output.jsonl` с заранее заданным финальным текстом).

### 7.3 `backend/tests/unit/test_project_memory.py`

- `test_frontmatter_roundtrip` — `_frontmatter` → `_parse_frontmatter` возвращает исходные meta + чистый body.
- `test_read_verify_commands` — `verify.md` с блоком ```sh → список команд; без блока → `[]`.
- `test_write_doc_atomic` — пишет файл во временный `repo/.hephaestus/memory/`, frontmatter присутствует, `MEMORY.md` обновлён (использует `tmp_path` — кроссплатформенно).
- `test_update_after_scan_appends_tech_debt` — high/security/bug-пункты появляются в `tech-debt.md` секцией `## from scan ...`.
- `test_unknown_doc_rejected` — `read_doc(ws, "nope")` → `None`/raises ValueError (контракт `DOCS`).

### 7.4 `backend/tests/integration/test_api_reorder.py`

- `test_reorder_ok` — TestClient + фикстура state c независимыми задачами → `PATCH .../reorder` 200, `order` совпал, `order_index` переписаны.
- `test_reorder_breaks_dependency` — 400 + `error` содержит `"breaks dependency"`.
- `test_reorder_conflict_order` — 400 + `error` содержит `"conflict order"`.
- `test_move_top_blocked_by_dependency` — `move-top` на таск с зависимостью, нарушающей порядок → отказ с причиной.
- Использует фикстуру `tmp_state_dir` (R18) из `backend/tests/conftest.py` (`tmp_path` + `monkeypatch` `STATE_DIR`); без сети — Decomposer/AgentRunner не задействованы (state наполняется фикстурой).

### 7.3a `backend/tests/unit/test_scan_run.py` (R19)

- `test_chunk_files_round_robin` — `chunk_files(repo, scope, n=3)` на `tmp_path`-репо c файлами раскидывает их по 3 чанкам, пропускает `.git`/`node_modules` (кроссплатформенно, реальный FS под `tmp_path`).
- `test_dedup_findings_merges_and_counts` — две находки с тем же `(title, touches)` → одна, `agreement_count == 2`; нормализация путей через `_norm_touch`.
- `test_run_mappers_aggregates` — `AgentRunner` замокан (пишет фиктивный `SCAN_FINDINGS_*` блок в `output_path`); `run_mappers` собирает находки из всех чанков; падение одного маппера логируется и не валит остальные.
- `test_run_reducers_shards` — `run_reducers` шардит находки по M, собирает proposals; мок-runner.

### 7.5 Контракт-тест домена

- Расширить `backend/tests/contract/test_existing_state.py`: после добавления полей `Item.model_validate` на старом `work-state.json` (без новых полей) **не падает** (дефолты применяются) — гарантия обратной совместимости миграции.

### 7.6 Frontend

- `frontend/src/components/__tests__/OrderBadge.spec.ts` (vitest): рендер `#N`, conflict-dot при `conflictGroup`.
- `board.reorderItems` — тест оптимистичного отката при `{ok:false}` (мок `api.reorderTask`).

---

## 8. Зависимости / пины

Новых сторонних зависимостей **не добавляется**. `task_graph` (Kahn/union-find) — чистый stdlib (`collections`, `hashlib`, `os.path`). `project_memory` использует stdlib + существующий `state._atomic_write`. `scan_run` (R19) — чистый stdlib (`argparse`, `asyncio`, `pathlib`) + `AgentRunner`/`ProcessManager`/`PromptManager` (Этап 1) + парсеры `SCAN_FINDINGS_*`/`SCAN_PROPOSAL_*`. Decomposer использует существующий `AgentRunner` (Этап 1) и `prompt_manager._VAR_RE`. Frontend: `sortablejs` уже в `package.json` (Phase 0/3), новых пакетов нет.

Пины наследуются из `backend/pyproject.toml` (Python `>=3.12,<3.13`, pydantic `^2.11`, pytest `^8.3`, pytest-asyncio `^0.25`) и `frontend/package.json` (vue `^3.5`, vitest `^3`).

---

## 9. Exit criteria (проверяемые)

1. `pytest backend/tests/unit/test_task_graph.py backend/tests/unit/test_decompose.py backend/tests/unit/test_project_memory.py -q` — green на Windows и Linux.
2. `pytest backend/tests/integration/test_api_reorder.py -q` — green; reorder-отказы возвращают человекочитаемую `error`.
3. `pytest backend/tests/contract/test_existing_state.py -q` — старый `work-state.json` валидируется новой `Item`-моделью без ошибок.
4. `ruff check backend/app/core/task_graph.py backend/app/core/decompose.py backend/app/services/project_memory.py` — clean.
5. `mypy --strict` по новым модулям — clean.
6. `prompts/scan-mapper.md`/`scan-reducer.md` не содержат `/home/starsinc`, `pnpm`, `Prisma`, `zod`, `otplib`, `@hephaestus/server`, `hephaestus-platform-snapshot` (grep-проверка пуста).
7. `_scan_start` не вызывает `tmux`/`_tmux_has`; скан стартует через `ProcessManager.start(name="scan", ...)` → `scan_run` (R19); проверяется отсутствием `tmux` в `scan.py`/`scan_run.py` (grep).
8. `pytest backend/tests/unit/test_scan_run.py -q` — green (R19): `chunk_files`/`dedup_findings`/`run_mappers`/`run_reducers` с мок-runner'ом, кроссплатформенно.
9. `pnpm build` (frontend) проходит; `vitest run` green (OrderBadge + reorder-store + TaskCard/TaskDrawer dependsOn/blocks-чипы тесты).
10. Ручной сценарий: импорт скана создаёт задачи с `order_index`/`conflict_group`; перетаскивание задачи через зависимость в pending даёт тост-отказ с причиной; `.hephaestus/memory/tech-debt.md` дополняется после импорта; на `TaskCard`/`TaskDrawer` видны чипы `dependsOn`/`blocks` (R21).

---

## 10. Out of scope + Rollback

**Out of scope (другие этапы / будущее):**
- `ProcessManager`/`AgentRunner`/`VerifyRunner`/`GitService`-реализация, реестр воркспейсов, миграция state, Profiler-онбординг, удаление bash/tmux из `driver.py`/`fsm.py` — **Этап 1**. `scan_run.py` (R19) опирается на `ProcessManager.start` и `AgentRunner` из Этапа 1; до их слияния `_scan_start_native` отдаёт понятную ошибку (никакого tmux-фолбэка).
- Воронка валидации (`validators.py`, заполнение `Task.validation`/`ValidationResult`, статус-петля `in_review→needs_revision`), merge-preflight/merge-API/conflict-UI, визуализация валидации в `TaskDrawer` — **Этап 3**. Этап 2 только резервирует поля `validation`/`result_summary`/`diff_ref` и значение `in_review` в `ItemStatus`.
- **Полноценный граф-вью DAG зависимостей** (force-directed/визуальное дерево) — **будущее (R21)**. Этап 2 ограничивается чипами `dependsOn`/`blocks` + точкой `conflict_group` на `TaskCard`/`TaskDrawer`; отдельный граф-компонент не вводится.
- Реальный запуск opencode-агентов в CI (Decomposer- и scan_run-тесты мокают AgentRunner).

**Rollback.**
- Новые файлы (`task_graph.py`, `decompose.py`, `scan_run.py`, `project_memory.py`, `api/v1/memory.py`, `prompts/scan-decomposer.md`, новые тесты, `OrderBadge.vue`) удаляются без следов — не трогают существующий поток. `_scan_start` (legacy tmux-вариант) сохраняется до Этапа 1, поэтому скан работает и при откате `scan_run`.
- Модификации обратимы: добавленные поля `Item` имеют дефолты (`extra="allow"` гарантирует чтение старого state); `_reorder`/`_queue_move_top` можно вернуть к прежнему `_queue_move_top` (git revert одного коммита). `prompts/scan-*.md` — git revert восстанавливает HEPHAESTUS-специфику.
- Frontend: `ItemStatus`/`Item`-дополнения опциональны для рендера; revert `KanbanColumn.onEnd` к старому `move-top`-в-обратном-порядке.
- Память живёт в целевом репо (не в инструменте) — откат инструмента не трогает уже записанные `.hephaestus/memory/*.md`; пользователь удаляет их `git`-средствами при желании.
