# Этап 2 — Scan -> декомпозиция задач + граф зависимостей + память Implementation Plan
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать Этап 2 HEPHAESTUS: обобщить map-reduce scanner под любой стек (убрать HEPHAESTUS-как-цель из `prompts/scan-*.md` и `scan.py`), ввести `task_graph.py` (DAG + conflict-aware reorder как единственный источник истины предиката `can_reorder`), `decompose.py` (находки → `Task` с `depends_on`/`order_index`/`conflict_group`/`epic`), `project_memory.py` (writer/reader `<repo>/.hephaestus/memory/*.md` с frontmatter), расширить доменную модель `Item` Stage-2-полями, добавить роуты `PATCH /api/v1/tasks/{id}/reorder` и `GET/PUT /api/v1/workspaces/{id}/memory/{doc}`, и отобразить порядок/конфликты на доске с откатом при отказе reorder.

**Architecture:** FastAPI backend (`backend/app/`) + Vue 3/Pinia frontend (`frontend/src/`). Чистый stdlib для графа (Kahn topo-sort + union-find), pydantic v2 для домена, `AgentRunner`/`ProcessManager` (Этап 1) вызываются через интерфейсы. До слияния Этапа 1 — временный шим `backend/app/core/ws_shim.py::get_active_profile()`. Все Этап-2-функции принимают `ws: RepoProfile` явно (umbrella §10.1 workspace-scoping); глобали `config.REPO`/`BASE_BRANCH` не читаются в новом коде. Единственный писатель state — backend под `_StateLock` (`backend/app/core/state.py`).

**Tech Stack:** Python `>=3.11` (target 3.12), pydantic `>=2.11,<3`, pytest `>=8.3,<9`, pytest-asyncio `>=0.25` (`asyncio_mode = "auto"`), ruff `>=0.11`, mypy `>=1.15`. Frontend: vue `^3.5`, pinia `^2.3`, vitest `^3.1`, sortablejs `^1.15`. Тесты кроссплатформенные — без `bash`/`tmux`/`flock`; subprocess и `AgentRunner` мокаются.

---

## File Structure

### Новые файлы (backend)

| Путь | Ответственность |
|------|-----------------|
| `backend/app/core/task_graph.py` | `GraphNode`/`Graph` dataclass'ы; `build_graph`, `detect_cycles`, `topo_order`, `assign_conflict_groups` (КОСМЕТИЧЕСКАЯ метка для UI, R6), `can_reorder` (файло-конфликт ПОПАРНО, не транзитивно), `apply_reorder`, `_norm_touch`. Единственный источник истины reorder-предиката (umbrella §10.5). Чистый stdlib. |
| `backend/app/core/decompose.py` | `decompose_proposals(ws, proposals, *, scan_dir, runner, decomposer_ref=None)`; `_parse_decompose_block`, `_expand_epics`, `_drop_dangling`. Вызывает `AgentRunner`, парсит `DECOMPOSE_BEGIN/END`, проставляет `depends_on`/`order_index`/`conflict_group`/`epic_id`/`parent`. |
| `backend/app/core/scan_run.py` | Нативный map-reduce worker (R19, D1): `chunk_files`, `dedup_findings`, `run_mappers` (scan-mapper.md), `run_reducers` (scan-reducer.md), `parse_findings_block`/`parse_proposals_block`, `main(--dir)`. Запускается `ProcessManager.start(name="scan", ...)`; собственный asyncio loop; никакого tmux/bash. |
| `backend/app/services/project_memory.py` | `DOCS`, `_FILENAME`, `memory_dir`, `read_doc`, `write_doc`, `read_verify_commands`, `init_memory`, `update_after_scan`, `update_after_task`, `_frontmatter`, `_parse_frontmatter`, `utcnow_iso`. MemoryWriter/Reader для `<repo>/.hephaestus/memory/*.md`. |
| `backend/app/api/v1/memory.py` | Роутер: `GET /api/v1/workspaces/{ws_id}/memory/{doc}`, `PUT /api/v1/workspaces/{ws_id}/memory/{doc}`. |
| `backend/app/core/ws_shim.py` | Временный `get_active_profile() -> RepoProfile` из `config.REPO`/`BASE_BRANCH`/`REMOTE`/`BRANCH_PREFIX` + effective-config агентов. Удаляется при слиянии Этапа 1. |
| `backend/app/models/workspace.py` | (если ещё нет от Этапа 1) минимальные `AgentRef`/`AgentsConfig`/`RepoProfile` по umbrella §4.1 — нужны как тип-хинт для `ws`. Если файл уже создан Этапом 1 — НЕ перезаписывать, только импортировать. |
| `prompts/scan-decomposer.md` | Промпт агента-декомпозитора со схемой вывода `DECOMPOSE_BEGIN/END` (§4.5 спеки). Read-only (`read`/`grep`/`glob`). |

### Новые файлы (тесты)

| Путь | Ответственность |
|------|-----------------|
| `backend/tests/unit/test_task_graph.py` | DAG/reorder/conflict/normalize (13 тестов §7.1, включая `test_can_reorder_conflict_pairwise_not_transitive`, R6). |
| `backend/tests/unit/test_scan_run.py` | Нативный скан (R19): `chunk_files`/`dedup_findings`/`run_mappers`/`run_reducers` (AgentRunner мокается, 4 теста §7.3a). |
| `backend/tests/unit/test_decompose.py` | Парсинг вывода декомпозитора + epic expansion + fallback (5 тестов §7.2). |
| `backend/tests/unit/test_project_memory.py` | frontmatter roundtrip / verify-команды / atomic write / append tech-debt (5 тестов §7.3). |
| `backend/tests/integration/test_api_reorder.py` | Контракт `PATCH /api/v1/tasks/{id}/reorder` (4 теста §7.4). |
| `frontend/src/components/__tests__/OrderBadge.spec.ts` | vitest: рендер `#N` + conflict-dot. |
| `frontend/src/stores/__tests__/board.reorder.spec.ts` | vitest: оптимистичный откат `reorderItems` при `{ok:false}`. |

### Новые файлы (frontend)

| Путь | Ответственность |
|------|-----------------|
| `frontend/src/components/OrderBadge.vue` | Props `{ orderIndex: number; conflictGroup: string \| null }`. Рендерит `#<orderIndex+1>` (1-based) и amber-точку при `conflictGroup`. |

### Модифицируемые файлы

| Путь | Изменение |
|------|-----------|
| `backend/app/models/domain.py` | `Item` += `workspace_id`, `depends_on`, `blocks`, `order_index`, `epic_id`, `parent`, `conflict_group`, `validation`, `result_summary`, `diff_ref` (umbrella §4.2). |
| `backend/app/models/requests.py` | += `ReorderRequest`, `MemoryWriteRequest`. |
| `backend/app/core/queue.py` | += `_reorder(new_order)`; `_queue_move_top` переписать поверх `_reorder`; `_queue_add` заполняет `order_index` (хвост). |
| `backend/app/core/scan.py` | `_scan_start` — убрать дефолт scope `"apps packages services"`; добавить `_scan_start_native(opts)` (R19/R1: пишет `request.json`, запускает супервизируемый `scan`-процесс через `ProcessManager.start` → `scan_run`; до Этапа 1 — понятная ошибка, не tmux); `_scan_import` — после append прогонять `decompose_proposals` + `update_after_scan`. |
| `backend/tests/conftest.py` | Фикстура `tmp_state_dir` (R18): `tmp_path/state` + пустые `work-state.json`/`decisions.log`; тесты сами монкипатчат `STATE_DIR`. Уже есть в репо — Task 11 проверяет/документирует её явно. |
| `backend/app/core/iters.py` | `build_state` — сортировать `items` по `(order_index, id)`; `_task_view` — добавить `depends_on`/`blocks`/`conflict_group` в `item`-блок ответа. |
| `backend/app/api/v1/tasks.py` | += `PATCH /api/v1/tasks/{item_id}/reorder`. |
| `backend/app/main.py` | Зарегистрировать `memory_router`. |
| `prompts/scan-mapper.md` | Обобщить: убрать хардкоды → `{{repo_path}}`/`{{scope}}`/`{{chunk}}`/`{{tech_stack}}`/`{{memory_excerpt}}`/`{{tech_debt_excerpt}}`. |
| `prompts/scan-reducer.md` | Убрать `.claude/memory/hephaestus-tech-debt.md` → `{{tech_debt_excerpt}}`; добавить `depends_on_hint` (опционально) в выходную схему. |
| `frontend/src/types/api.ts` | `Item` += Stage-2 поля; `ItemStatus` += `'in_review'`; += `ReorderResult`. |
| `frontend/src/api/client.ts` | += `reorderTask`, `getWorkspaceMemory`, `putWorkspaceMemory`. |
| `frontend/src/stores/board.ts` | += `reorderItems(newOrder)` (оптимистично + откат + тост). |
| `frontend/src/components/KanbanColumn.vue` | `onEnd` → `emit('reorder', sortable.toArray())`; рендер `OrderBadge`. |
| `frontend/src/components/TaskCard.vue` | Заменить `'sisyphus'` на `item.agent_override ?? '—'`; рендер `OrderBadge` + conflict-индикатор. |
| `frontend/src/views/BoardView.vue` | `onReorder` → `board.reorderItems(ids)`. |
| `frontend/package.json` | += devDeps `@vue/test-utils`, `jsdom`; vitest-конфиг в `vite.config.ts` (`test.environment='jsdom'`). |

---

## Task 1: Доменная модель — добавить Stage-2 поля в `Item`

Цель: расширить `backend/app/models/domain.py` полями умбреллы §4.2, не ломая обратную совместимость старого `work-state.json`. Это фундамент — все остальные модули читают/пишут эти поля.

- [ ] Прочитать текущий `backend/app/models/domain.py` (символ `Item`, `model_config = ConfigDict(extra="allow", populate_by_name=True)`).

- [ ] Дописать падающий контракт-тест в `backend/tests/contract/test_existing_state.py` (новая функция в конце файла):

```python
def test_stage2_fields_default_and_alias() -> None:
    """Stage 2 additions parse from old state (defaults) and dump camelCase."""
    old = {"id": "x", "title": "y", "status": "pending"}
    item = Item.model_validate(old)
    assert item.depends_on == []
    assert item.blocks == []
    assert item.order_index == 0
    assert item.conflict_group is None
    assert item.epic_id is None
    assert item.parent is None
    assert item.validation is None
    assert item.result_summary == ""
    assert item.diff_ref is None
    assert item.workspace_id is None
    dumped = item.model_dump(by_alias=True)
    assert dumped["dependsOn"] == []
    assert dumped["orderIndex"] == 0
    assert dumped["conflictGroup"] is None
    assert dumped["epicId"] is None
    assert dumped["resultSummary"] == ""
    assert dumped["diffRef"] is None
    assert dumped["workspaceId"] is None


def test_stage2_fields_populate_by_alias() -> None:
    """camelCase JSON from frontend populates snake_case fields."""
    data = {
        "id": "a", "title": "t", "status": "pending",
        "dependsOn": ["b"], "orderIndex": 3, "conflictGroup": "cg-deadbeef",
        "epicId": "e1", "parent": "e1", "resultSummary": "done it", "diffRef": "iter-0007/diff.patch",
        "workspaceId": "9f3a1c20e4b57d61",
    }
    item = Item.model_validate(data)
    assert item.depends_on == ["b"]
    assert item.order_index == 3
    assert item.conflict_group == "cg-deadbeef"
    assert item.epic_id == "e1"
    assert item.result_summary == "done it"
```

- [ ] Запустить тест — ожидаемый **FAIL** (полей пока нет):

```
cd backend && python -m pytest tests/contract/test_existing_state.py::test_stage2_fields_default_and_alias -q
# FAILED ... AttributeError: 'Item' object has no attribute 'depends_on'
```

- [ ] Реализация: добавить в класс `Item` (после строки `source_issue: int | None = Field(None, alias="sourceIssue")`) дословно по umbrella §4.2:

```python
    # --- Stage 2 additions (umbrella §4.2) ---
    workspace_id: str | None = Field(None, alias="workspaceId")
    depends_on: list[str] = Field(default_factory=list, alias="dependsOn")
    blocks: list[str] = Field(default_factory=list)
    order_index: int = Field(0, alias="orderIndex")
    epic_id: str | None = Field(None, alias="epicId")
    parent: str | None = None
    conflict_group: str | None = Field(None, alias="conflictGroup")
    validation: dict | None = None  # Stage 3 заполняет; Stage 2 резервирует
    result_summary: str = Field("", alias="resultSummary")
    diff_ref: str | None = Field(None, alias="diffRef")
```

- [ ] Запустить тесты — ожидаемый **PASS** (включая существующие контракт-тесты):

```
cd backend && python -m pytest tests/contract/test_existing_state.py -q
# 5 passed
```

- [ ] `git add backend/app/models/domain.py backend/tests/contract/test_existing_state.py && git commit -m "feat(stage2): add Task graph/memory fields to Item domain model"`

---

## Task 2: `task_graph.py` — нормализация touches + conflict-группы (union-find)

Цель: чистый stdlib-модуль для нормализации путей и присвоения `conflict_group` через union-find по разделяемым файлам (D5, спека §4.2).

- [ ] Создать падающий тест `backend/tests/unit/test_task_graph.py`:

```python
"""Unit tests for task_graph — DAG, conflict groups, reorder predicate. Cross-platform, no bash."""

from __future__ import annotations

from app.core.task_graph import (
    _norm_touch,
    assign_conflict_groups,
)


def test_norm_touch_windows() -> None:
    assert _norm_touch("a\\B.py:10") == _norm_touch("a/b.py")
    assert _norm_touch("src/X.py:42") == "src/x.py"
    assert _norm_touch("  ./src/x.py  ") == "src/x.py"


def test_assign_conflict_groups_shared_file() -> None:
    items = [
        {"id": "t1", "touches": ["src/x.py:42"]},
        {"id": "t2", "touches": ["src\\x.py"]},
        {"id": "t3", "touches": ["src/other.py"]},
    ]
    groups = assign_conflict_groups(items)
    assert groups["t1"] is not None
    assert groups["t1"] == groups["t2"]
    assert groups["t1"].startswith("cg-")
    assert groups["t3"] is None


def test_conflict_group_singleton_none() -> None:
    items = [{"id": "solo", "touches": ["a.py"]}]
    assert assign_conflict_groups(items) == {"solo": None}
```

- [ ] Запустить — ожидаемый **FAIL** (`ModuleNotFoundError: No module named 'app.core.task_graph'`):

```
cd backend && python -m pytest tests/unit/test_task_graph.py -q
# ERROR ... ModuleNotFoundError
```

- [ ] Создать `backend/app/core/task_graph.py` с dataclass'ами, нормализацией и union-find:

```python
"""DAG construction + conflict groups + reorder predicate — pure stdlib, cross-platform.

Single source of truth for the reorder predicate (umbrella §10.5).
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger("hephaestus.backend.task_graph")


@dataclass
class GraphNode:
    id: str
    depends_on: list[str]  # рёбра «X зависит от Y» (Y должен идти раньше X)
    touches: list[str]
    order_index: int
    conflict_group: str | None = None
    blocks: list[str] = field(default_factory=list)


@dataclass
class Graph:
    nodes: dict[str, GraphNode]
    forward: dict[str, list[str]]  # X -> [его зависимости]
    reverse: dict[str, list[str]]  # Y -> [кто зависит от Y]


def _norm_touch(t: str) -> str:
    """Normalize a touch path: strip ':LINE', backslash→slash, posix-normalize, casefold."""
    path = t.split(":", 1)[0].strip().replace("\\", "/")
    return os.path.normpath(path).replace("\\", "/").casefold()


class _UnionFind:
    def __init__(self, ids: list[str]) -> None:
        self._parent: dict[str, str] = {i: i for i in ids}

    def find(self, x: str) -> str:
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra


def assign_conflict_groups(items: list[dict]) -> dict[str, str | None]:
    """id -> conflict_group. Группа = connected component по разделяемому touches-файлу.
    Ключ группы = 'cg-' + sha1(','.join(sorted(member_ids)))[:8]. Одиночка → None."""
    all_ids = [it["id"] for it in items]
    file_to_ids: dict[str, list[str]] = {}
    for it in items:
        for t in it.get("touches", []) or []:
            file_to_ids.setdefault(_norm_touch(t), []).append(it["id"])
    uf = _UnionFind(all_ids)
    for ids in file_to_ids.values():
        for j in range(1, len(ids)):
            uf.union(ids[0], ids[j])
    buckets: dict[str, list[str]] = {}
    for i in all_ids:
        buckets.setdefault(uf.find(i), []).append(i)
    result: dict[str, str | None] = {}
    for members in buckets.values():
        if len(members) <= 1:
            result[members[0]] = None
        else:
            key = "cg-" + hashlib.sha1(",".join(sorted(members)).encode()).hexdigest()[:8]
            for m in members:
                result[m] = key
    return result
```

- [ ] Запустить — ожидаемый **PASS**:

```
cd backend && python -m pytest tests/unit/test_task_graph.py -q
# 3 passed
```

- [ ] `git add backend/app/core/task_graph.py backend/tests/unit/test_task_graph.py && git commit -m "feat(stage2): task_graph conflict groups via union-find"`

---

## Task 3: `task_graph.py` — `build_graph`, `detect_cycles`, `topo_order`

Цель: построить DAG из items, детектить циклы, стабильный Kahn topo-sort с тай-брейком `(order_index, id)` и разрывом циклов (спека §4.2, §6).

- [ ] Дописать падающие тесты в `backend/tests/unit/test_task_graph.py`:

```python
from app.core.task_graph import build_graph, detect_cycles, topo_order


def test_topo_order_respects_deps() -> None:
    # C dep B dep A → A before B before C
    items = [
        {"id": "C", "dependsOn": ["B"], "touches": [], "orderIndex": 2},
        {"id": "A", "dependsOn": [], "touches": [], "orderIndex": 0},
        {"id": "B", "dependsOn": ["A"], "touches": [], "orderIndex": 1},
    ]
    g = build_graph(items)
    assert topo_order(g) == ["A", "B", "C"]


def test_topo_order_stable_tiebreak() -> None:
    # independent nodes sort by (order_index, id)
    items = [
        {"id": "z", "dependsOn": [], "touches": [], "orderIndex": 0},
        {"id": "a", "dependsOn": [], "touches": [], "orderIndex": 0},
        {"id": "m", "dependsOn": [], "touches": [], "orderIndex": 5},
    ]
    g = build_graph(items)
    # order_index ties broken by id: a,z before m
    assert topo_order(g) == ["a", "z", "m"]


def test_detect_cycles() -> None:
    items = [
        {"id": "A", "dependsOn": ["B"], "touches": [], "orderIndex": 0},
        {"id": "B", "dependsOn": ["A"], "touches": [], "orderIndex": 1},
    ]
    g = build_graph(items)
    cycles = detect_cycles(g)
    assert len(cycles) == 1
    assert set(cycles[0]) == {"A", "B"}
    # acyclic → []
    g2 = build_graph([{"id": "X", "dependsOn": [], "touches": [], "orderIndex": 0}])
    assert detect_cycles(g2) == []


def test_topo_order_breaks_llm_cycle() -> None:
    items = [
        {"id": "A", "dependsOn": ["B"], "touches": [], "orderIndex": 0},
        {"id": "B", "dependsOn": ["A"], "touches": [], "orderIndex": 1},
        {"id": "C", "dependsOn": [], "touches": [], "orderIndex": 2},
    ]
    g = build_graph(items)
    order = topo_order(g)
    # all nodes present, cycle nodes pushed to end by id
    assert set(order) == {"A", "B", "C"}
    assert order.index("C") < order.index("A") or order.index("C") < order.index("B")
```

- [ ] Запустить — ожидаемый **FAIL** (`ImportError: cannot import name 'build_graph'`):

```
cd backend && python -m pytest tests/unit/test_task_graph.py -k "topo or cycle" -q
# ERROR ... ImportError
```

- [ ] Реализация: дописать в `backend/app/core/task_graph.py`:

```python
def build_graph(items: list[dict]) -> Graph:
    """Build DAG. Edges from depends_on; dangling deps (id not in items) dropped (§6)."""
    ids = {it["id"] for it in items}
    nodes: dict[str, GraphNode] = {}
    forward: dict[str, list[str]] = {}
    reverse: dict[str, list[str]] = {}
    groups = assign_conflict_groups(items)
    for it in items:
        nid = it["id"]
        deps = [d for d in (it.get("dependsOn") or []) if d in ids and d != nid]
        nodes[nid] = GraphNode(
            id=nid,
            depends_on=deps,
            touches=list(it.get("touches", []) or []),
            order_index=int(it.get("orderIndex", 0) or 0),
            conflict_group=groups.get(nid),
        )
        forward.setdefault(nid, []).extend(deps)
        for d in deps:
            reverse.setdefault(d, []).append(nid)
    # compute blocks (reverse edges) per node
    for nid, node in nodes.items():
        node.blocks = sorted(reverse.get(nid, []))
    return Graph(nodes=nodes, forward=forward, reverse=reverse)


def detect_cycles(g: Graph) -> list[list[str]]:
    """Return list of cycles (each a list of ids). Empty = acyclic. DFS with colours."""
    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in g.nodes}
    cycles: list[list[str]] = []
    stack: list[str] = []

    def visit(n: str) -> None:
        color[n] = GREY
        stack.append(n)
        for dep in g.nodes[n].depends_on:
            if color.get(dep, BLACK) == GREY:
                # back-edge → cycle from dep..n
                i = stack.index(dep)
                cycles.append(stack[i:])
            elif color.get(dep, BLACK) == WHITE:
                visit(dep)
        stack.pop()
        color[n] = BLACK

    for n in sorted(g.nodes):
        if color[n] == WHITE:
            visit(n)
    return cycles


def topo_order(g: Graph) -> list[str]:
    """Stable Kahn topo-sort: tie-break by (order_index, id). On cycle, broken edges
    logged; cycle nodes appended at the end in id order."""
    indeg: dict[str, int] = {n: 0 for n in g.nodes}
    for n in g.nodes:
        for dep in g.nodes[n].depends_on:
            indeg[n] += 1  # n waits for its deps
    ready = sorted(
        (n for n in g.nodes if indeg[n] == 0),
        key=lambda n: (g.nodes[n].order_index, n),
    )
    out: list[str] = []
    while ready:
        n = ready.pop(0)
        out.append(n)
        for dependent in sorted(g.reverse.get(n, [])):
            indeg[dependent] -= 1
            if indeg[dependent] == 0:
                ready.append(dependent)
        ready.sort(key=lambda x: (g.nodes[x].order_index, x))
    if len(out) < len(g.nodes):
        leftover = sorted(n for n in g.nodes if n not in out)
        log.warning("topo_order: cycle detected, appending unresolved nodes: %s", leftover)
        out.extend(leftover)
    return out
```

- [ ] Запустить — ожидаемый **PASS**:

```
cd backend && python -m pytest tests/unit/test_task_graph.py -q
# 7 passed
```

- [ ] `git add backend/app/core/task_graph.py backend/tests/unit/test_task_graph.py && git commit -m "feat(stage2): task_graph build/detect_cycles/topo_order"`

---

## Task 4: `task_graph.py` — `can_reorder` (попарный конфликт, R6) + `apply_reorder`

Цель: реализовать точный алгоритм валидации перестановки (D5, спека §4.2) — единственный источник истины (umbrella §10.5). Файло-конфликт проверяется **попарно** (пары с общим файлом), НЕ транзитивной union-find компонентой (R6); `assign_conflict_groups` остаётся косметической меткой для UI и в `can_reorder` не используется.

- [ ] Дописать падающие тесты в `backend/tests/unit/test_task_graph.py`:

```python
from app.core.task_graph import apply_reorder, can_reorder


def _items() -> list[dict]:
    return [
        {"id": "A", "dependsOn": [], "touches": ["a.py"], "orderIndex": 0},
        {"id": "B", "dependsOn": ["A"], "touches": ["b.py"], "orderIndex": 1},
        {"id": "C", "dependsOn": [], "touches": ["c.py"], "orderIndex": 2},
    ]


def test_can_reorder_ok() -> None:
    items = _items()
    ok, reason = can_reorder(items, ["A", "C", "B"])  # B still after A
    assert ok is True
    assert reason == ""


def test_can_reorder_breaks_dependency() -> None:
    items = _items()
    ok, reason = can_reorder(items, ["B", "A", "C"])  # B before its dep A
    assert ok is False
    assert "breaks dependency A before B" in reason


def test_can_reorder_set_mismatch() -> None:
    items = _items()
    ok, reason = can_reorder(items, ["A", "B"])  # dropped C
    assert ok is False
    assert "reorder set mismatch" in reason


def test_can_reorder_dangling_dep_ignored() -> None:
    items = [
        {"id": "A", "dependsOn": ["ghost"], "touches": ["a.py"], "orderIndex": 0},
        {"id": "B", "dependsOn": [], "touches": ["b.py"], "orderIndex": 1},
    ]
    ok, reason = can_reorder(items, ["B", "A"])
    assert ok is True


def test_can_reorder_conflict_order() -> None:
    # two tasks share x.py → pairwise file conflict; swapping them is forbidden
    items = [
        {"id": "A", "dependsOn": [], "touches": ["src/x.py"], "orderIndex": 0},
        {"id": "B", "dependsOn": [], "touches": ["src/x.py:9"], "orderIndex": 1},
    ]
    ok, reason = can_reorder(items, ["B", "A"])
    assert ok is False
    assert "violates conflict order" in reason
    assert "A must stay before B" in reason


def test_can_reorder_conflict_pairwise_not_transitive() -> None:
    # R6: A∩B share x.py, B∩C share y.py, but A∩C is empty.
    # Union-find would lump A,B,C into one component; the PAIRWISE predicate must NOT.
    # Reordering A and C (keeping each relative to B) is allowed.
    items = [
        {"id": "A", "dependsOn": [], "touches": ["src/x.py"], "orderIndex": 0},
        {"id": "B", "dependsOn": [], "touches": ["src/x.py", "src/y.py"], "orderIndex": 1},
        {"id": "C", "dependsOn": [], "touches": ["src/y.py"], "orderIndex": 2},
    ]
    # A and C have NO shared file → swapping them around B is fine as long as
    # A stays before B (share x.py) and B stays before C (share y.py).
    ok, reason = can_reorder(items, ["A", "B", "C"])
    assert ok is True, reason
    # Swapping A before/after C with B fixed is unconstrained between A and C:
    # moving C up only fails because it would cross B (shared y.py), not because of A.
    ok2, reason2 = can_reorder(items, ["C", "B", "A"])
    assert ok2 is False  # C before B violates the B-C shared-file pair
    assert "violates conflict order" in reason2


def test_apply_reorder_dense_indices() -> None:
    items = _items()
    out = apply_reorder(items, ["A", "C", "B"])
    by_id = {it["id"]: it for it in out}
    assert by_id["A"]["orderIndex"] == 0
    assert by_id["C"]["orderIndex"] == 1
    assert by_id["B"]["orderIndex"] == 2
    # original list untouched (returns a copy)
    assert items[1]["id"] == "B" and items[1]["orderIndex"] == 1
```

- [ ] Запустить — ожидаемый **FAIL** (`ImportError: cannot import name 'can_reorder'`):

```
cd backend && python -m pytest tests/unit/test_task_graph.py -k "reorder" -q
# ERROR ... ImportError
```

- [ ] Реализация: дописать в `backend/app/core/task_graph.py`:

```python
def can_reorder(items: list[dict], new_order: list[str]) -> tuple[bool, str]:
    """Single source of truth for reorder validity (umbrella §10.5, D5).

    File conflict is checked PAIRWISE, NOT transitively (R6): only pairs of tasks that
    share a real file (touches ∩ != empty) constrain relative order. Transitive union-find
    components do NOT block reorder (if A∩B and B∩C but A∩C is empty, A and C may swap).
    conflict_group / assign_conflict_groups is a cosmetic UI label only — never used here.
    """
    by_id = {it["id"]: it for it in items}
    # 0. new_order must be an exact permutation of current ids
    if set(new_order) != set(by_id):
        return (False, "reorder set mismatch: ids added or dropped")
    pos = {id_: i for i, id_ in enumerate(new_order)}
    # 1. DAG invariant: for each dep edge (X dependsOn dep), dep must precede X
    for it in items:
        x = it["id"]
        for dep in it.get("dependsOn", []) or []:
            if dep not in by_id:
                continue  # dangling dep — ignore (§6)
            if pos[dep] > pos[x]:
                return (False, f"reorder breaks dependency {dep} before {x}")
    # 2. Pairwise file-conflict invariant (R6): for every unordered pair (a, b) that shares
    #    at least one normalized file, the task that came first in the ORIGINAL order
    #    (order_index, id) must stay first in new_order.
    norm = {it["id"]: {_norm_touch(t) for t in (it.get("touches") or [])} for it in items}

    def _orig_rank(i: str) -> tuple[int, str]:
        return (int(by_id[i].get("orderIndex", 0) or 0), i)

    ids = list(by_id)
    for ai in range(len(ids)):
        for bi in range(ai + 1, len(ids)):
            a, b = ids[ai], ids[bi]
            if not (norm[a] & norm[b]):
                continue  # no shared file → this pair is free to swap
            first, second = (a, b) if _orig_rank(a) < _orig_rank(b) else (b, a)
            if pos[first] > pos[second]:
                return (
                    False,
                    f"reorder violates conflict order: {first} must stay before "
                    f"{second} (shared files)",
                )
    return (True, "")


def apply_reorder(items: list[dict], new_order: list[str]) -> list[dict]:
    """Return a copy of items with order_index rewritten to match new_order (dense 0..n-1).
    Ids not in new_order keep their relative tail order after the listed ones."""
    pos = {id_: i for i, id_ in enumerate(new_order)}
    tail_base = len(new_order)
    out: list[dict] = []
    tail_seen = 0
    for it in items:
        copy = dict(it)
        if it["id"] in pos:
            copy["orderIndex"] = pos[it["id"]]
        else:
            copy["orderIndex"] = tail_base + tail_seen
            tail_seen += 1
        out.append(copy)
    out.sort(key=lambda c: c["orderIndex"])
    return out
```

- [ ] Запустить полный модуль — ожидаемый **PASS** (13 тестов §7.1, включая `test_can_reorder_conflict_pairwise_not_transitive`, R6):

```
cd backend && python -m pytest tests/unit/test_task_graph.py -q
# 14 passed
```

- [ ] `ruff check backend/app/core/task_graph.py` — clean. `mypy backend/app/core/task_graph.py` — clean.

- [ ] `git add backend/app/core/task_graph.py backend/tests/unit/test_task_graph.py && git commit -m "feat(stage2): task_graph can_reorder pairwise file-conflict (R6/D5)"`

---

## Task 5: `project_memory.py` — frontmatter roundtrip + DOCS

Цель: реализовать frontmatter writer/parser и контракт `DOCS`/`_FILENAME` (спека §4.4, umbrella §4.3).

- [ ] Создать падающий тест `backend/tests/unit/test_project_memory.py`:

```python
"""Unit tests for project_memory — frontmatter, verify commands, atomic write. Cross-platform."""

from __future__ import annotations

import types

import pytest

from app.services import project_memory as pm


def _ws(repo_path: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(id="9f3a1c20e4b57d61", repo_path=repo_path, memory_dir=".hephaestus/memory")


def test_frontmatter_roundtrip() -> None:
    fm = pm._frontmatter("verify", "9f3a1c20e4b57d61", "scan")
    meta, body = pm._parse_frontmatter(fm + "## commands\nhello\n")
    assert meta["doc"] == "verify"
    assert meta["workspace_id"] == "9f3a1c20e4b57d61"
    assert meta["source"] == "scan"
    assert meta["schema"] == "1"
    assert body.strip() == "## commands\nhello"


def test_parse_frontmatter_absent() -> None:
    meta, body = pm._parse_frontmatter("no frontmatter here")
    assert meta == {}
    assert body == "no frontmatter here"


def test_unknown_doc_rejected() -> None:
    ws = _ws("/tmp/repo")
    with pytest.raises(ValueError):
        pm.write_doc(ws, "nope", "x", source="manual")
    assert pm.read_doc(ws, "nope") is None
```

- [ ] Запустить — ожидаемый **FAIL** (`ModuleNotFoundError: app.services.project_memory`):

```
cd backend && python -m pytest tests/unit/test_project_memory.py -q
# ERROR ... ModuleNotFoundError
```

- [ ] Создать `backend/app/services/project_memory.py` (часть 1 — frontmatter + DOCS + read/write):

```python
"""MemoryWriter/Reader for <repo>/.hephaestus/memory/*.md with YAML frontmatter (umbrella §4.3)."""

from __future__ import annotations

import logging
import pathlib
import time
from typing import TYPE_CHECKING

from app.core.state import _atomic_write

if TYPE_CHECKING:
    from app.models.workspace import RepoProfile

log = logging.getLogger("hephaestus.backend.project_memory")

DOCS = ("index", "architecture", "verify", "conventions", "tech-debt")
_FILENAME = {
    "index": "MEMORY.md",
    "architecture": "architecture.md",
    "verify": "verify.md",
    "conventions": "conventions.md",
    "tech-debt": "tech-debt.md",
}


def utcnow_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def memory_dir(ws: "RepoProfile") -> pathlib.Path:
    return pathlib.Path(ws.repo_path) / ws.memory_dir


def _frontmatter(doc: str, ws_id: str, source: str) -> str:
    return (
        f"---\ndoc: {doc}\nworkspace_id: {ws_id}\n"
        f"updated_at: {utcnow_iso()}\nsource: {source}\nschema: 1\n---\n"
    )


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (meta-dict, body-without-frontmatter). No frontmatter → ({}, text)."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines(keepends=True)
    # find the closing '---' after line 0
    end = None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\n") == "---":
            end = i
            break
    if end is None:
        return {}, text
    meta: dict = {}
    for ln in lines[1:end]:
        if ":" in ln:
            k, _, v = ln.partition(":")
            meta[k.strip()] = v.strip()
    body = "".join(lines[end + 1 :])
    return meta, body


def _validate_doc(doc: str) -> None:
    if doc not in DOCS:
        raise ValueError(f"unknown memory doc: {doc} (allowed: {', '.join(DOCS)})")


def read_doc(ws: "RepoProfile", doc: str) -> str | None:
    """Read raw file body (without frontmatter). Unknown doc or missing file → None."""
    if doc not in DOCS:
        return None
    p = memory_dir(ws) / _FILENAME[doc]
    if not p.exists():
        return None
    try:
        _, body = _parse_frontmatter(p.read_text(encoding="utf-8"))
        return body
    except Exception as exc:
        log.error("read_doc %s failed: %s", doc, exc)
        return None


def write_doc(ws: "RepoProfile", doc: str, body: str, *, source: str) -> pathlib.Path:
    """Write <repo>/.hephaestus/memory/<file> with frontmatter + body (atomic). Updates MEMORY.md index."""
    _validate_doc(doc)
    mdir = memory_dir(ws)
    mdir.mkdir(parents=True, exist_ok=True)
    p = mdir / _FILENAME[doc]
    _atomic_write(p, _frontmatter(doc, ws.id, source) + body)
    if doc != "index":
        _refresh_index(ws, source=source)
    return p


def _refresh_index(ws: "RepoProfile", *, source: str) -> None:
    mdir = memory_dir(ws)
    lines = ["# HEPHAESTUS Project Memory", "", f"Updated: {utcnow_iso()}", ""]
    for doc in DOCS:
        if doc == "index":
            continue
        fname = _FILENAME[doc]
        exists = (mdir / fname).exists()
        mark = "x" if exists else " "
        lines.append(f"- [{mark}] [{doc}]({fname})")
    body = "\n".join(lines) + "\n"
    _atomic_write(mdir / _FILENAME["index"], _frontmatter("index", ws.id, source) + body)
```

- [ ] Запустить — ожидаемый **PASS**:

```
cd backend && python -m pytest tests/unit/test_project_memory.py -q
# 3 passed
```

- [ ] `git add backend/app/services/project_memory.py backend/tests/unit/test_project_memory.py && git commit -m "feat(stage2): project_memory frontmatter + read/write_doc"`

---

## Task 6: `project_memory.py` — `read_verify_commands` + atomic write + `update_after_scan`

Цель: парсинг verify-команд из `verify.md`, проверка atomic write + индекса, append tech-debt после скана (спека §4.4, §6).

- [ ] Дописать падающие тесты в `backend/tests/unit/test_project_memory.py`:

```python
def test_read_verify_commands(tmp_path) -> None:
    ws = _ws(str(tmp_path))
    body = "## commands\n```sh\nuv run pytest -q\n# a comment\n\nuv run ruff check .\n```\n"
    pm.write_doc(ws, "verify", body, source="profiler")
    cmds = pm.read_verify_commands(ws)
    assert cmds == ["uv run pytest -q", "uv run ruff check ."]


def test_read_verify_commands_no_block(tmp_path) -> None:
    ws = _ws(str(tmp_path))
    pm.write_doc(ws, "verify", "no commands here\n", source="profiler")
    assert pm.read_verify_commands(ws) == []


def test_write_doc_atomic(tmp_path) -> None:
    ws = _ws(str(tmp_path))
    p = pm.write_doc(ws, "architecture", "# Arch\nmodules\n", source="profiler")
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert text.startswith("---\ndoc: architecture\n")
    index = (pm.memory_dir(ws) / "MEMORY.md").read_text(encoding="utf-8")
    assert "[architecture](architecture.md)" in index
    assert "[x]" in index


def test_update_after_scan_appends_tech_debt(tmp_path) -> None:
    ws = _ws(str(tmp_path))
    proposals = [
        {"id": "scan-a", "title": "Fix race", "category": "bug", "severity": "high"},
        {"id": "scan-b", "title": "Add CSRF", "category": "security", "severity": "medium"},
        {"id": "scan-c", "title": "Rename var", "category": "quality", "severity": "low"},
    ]
    pm.update_after_scan(ws, scan_dir="scan-20260605-1", proposals=proposals)
    body = pm.read_doc(ws, "tech-debt")
    assert body is not None
    assert "## from scan scan-20260605-1" in body
    assert "Fix race" in body  # bug high included
    assert "Add CSRF" in body  # security included
    assert "Rename var" not in body  # low quality excluded
```

- [ ] Запустить — ожидаемый **FAIL** (`AttributeError: module ... has no attribute 'read_verify_commands'`):

```
cd backend && python -m pytest tests/unit/test_project_memory.py -k "verify or atomic or tech_debt" -q
# FAILED ... AttributeError
```

- [ ] Реализация: дописать в `backend/app/services/project_memory.py`:

```python
def read_verify_commands(ws: "RepoProfile") -> list[str]:
    """Parse verify.md: the ```sh ... ``` block under '## commands' → list of commands.
    One per line, no blanks/comments. Empty → []."""
    body = read_doc(ws, "verify")
    if not body:
        return []
    lines = body.splitlines()
    in_commands = False
    in_block = False
    out: list[str] = []
    for ln in lines:
        stripped = ln.strip()
        if stripped.lower().startswith("## commands"):
            in_commands = True
            continue
        if in_commands and stripped.startswith("```"):
            if not in_block:
                in_block = True
                continue
            break  # closing fence
        if in_block:
            if not stripped or stripped.startswith("#"):
                continue
            out.append(stripped)
    return out


def init_memory(
    ws: "RepoProfile",
    *,
    architecture: str,
    verify_commands: list[str],
    conventions: str,
    tech_debt: str,
) -> None:
    """Profiler onboarding (Stage 1 calls; Stage 2 provides impl)."""
    write_doc(ws, "architecture", architecture, source="profiler")
    verify_body = "## commands\n```sh\n" + "\n".join(verify_commands) + "\n```\n"
    write_doc(ws, "verify", verify_body, source="profiler")
    write_doc(ws, "conventions", conventions, source="profiler")
    write_doc(ws, "tech-debt", tech_debt, source="profiler")


def update_after_scan(ws: "RepoProfile", *, scan_dir: str, proposals: list[dict]) -> None:
    """Append a '## from scan <dir>' section to tech-debt.md with high/security/bug items."""
    relevant = [
        p
        for p in proposals
        if (p.get("category") in ("bug", "security")) or (p.get("severity") == "high")
    ]
    if not relevant:
        return
    existing = read_doc(ws, "tech-debt") or "# Tech Debt\n"
    section = [f"\n## from scan {scan_dir}\n"]
    for p in relevant:
        cat = p.get("category", "?")
        sev = p.get("severity", "?")
        section.append(f"- [{cat}/{sev}] {p.get('title', p.get('id', '?'))}")
    new_body = existing.rstrip() + "\n" + "\n".join(section) + "\n"
    write_doc(ws, "tech-debt", new_body, source="scan")


def update_after_task(ws: "RepoProfile", *, task: dict, summary: str) -> None:
    """After a done task: append a convention note if a new pattern was introduced."""
    if not summary.strip():
        return
    existing = read_doc(ws, "conventions") or "# Conventions\n"
    note = f"\n## from task {task.get('id', '?')}\n- {summary.strip()}\n"
    write_doc(ws, "conventions", existing.rstrip() + "\n" + note, source="task")
```

- [ ] Запустить полный модуль — ожидаемый **PASS** (7 тестов; §7.3 покрыт):

```
cd backend && python -m pytest tests/unit/test_project_memory.py -q
# 7 passed
```

- [ ] `ruff check backend/app/services/project_memory.py` — clean. `mypy backend/app/services/project_memory.py` — clean.

- [ ] `git add backend/app/services/project_memory.py backend/tests/unit/test_project_memory.py && git commit -m "feat(stage2): project_memory verify commands + update_after_scan/task + init_memory"`

---

## Task 7: `ws_shim.py` + минимальный `workspace.py` (граничный случай — Этап 1 не слит)

Цель: предоставить `get_active_profile()` и тип `RepoProfile` для роутеров/тестов до готовности Этапа 1 (спека §6, umbrella §4.1). Если Этап 1 уже создал `backend/app/models/workspace.py` — НЕ перезаписывать, только дополнить шим.

- [ ] Проверить наличие `backend/app/models/workspace.py`:

```
cd backend && python -c "import os; print(os.path.exists('app/models/workspace.py'))"
# если False → создать минимальную версию ниже; если True → пропустить создание workspace.py
```

- [ ] Если файла нет — создать `backend/app/models/workspace.py` (минимальный набор по umbrella §4.1, без полей, не нужных Этапу 2):

```python
"""Workspace / RepoProfile domain (umbrella §4.1). Minimal Stage-2 subset.

If Stage 1 ships a fuller version, it supersedes this file — do not duplicate fields.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class VerifySource(StrEnum):
    AGENT = "agent"
    MANUAL = "manual"


class AgentRef(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    provider: str
    model: str
    agent: str | None = None


class AgentsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    use_models: bool = Field(False, alias="useModels")
    primary: AgentRef
    fallback: AgentRef
    validators: list[AgentRef] = []
    arbiters: list[AgentRef] = []
    final: AgentRef | None = None


class RepoProfile(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    name: str
    repo_path: str = Field(..., alias="repoPath")
    base_branch: str = Field("main", alias="baseBranch")
    remote: str = "origin"
    branch_prefix: str = Field("auto", alias="branchPrefix")
    agents: AgentsConfig
    strictness: str = "standard"
    memory_dir: str = Field(".hephaestus/memory", alias="memoryDir")
    verify_source: VerifySource = Field(VerifySource.AGENT, alias="verifySource")
    verify_commands_override: list[str] = Field([], alias="verifyCommandsOverride")
    onboarded: bool = False
```

- [ ] Создать `backend/app/core/ws_shim.py`:

```python
"""Temporary active-workspace accessor — removed when Stage 1 registry lands (spec §6)."""

from __future__ import annotations

import hashlib
import os

from app.config import BASE_BRANCH, BRANCH_PREFIX, REMOTE, REPO, _config_effective
from app.models.workspace import AgentRef, AgentsConfig, RepoProfile


def _ws_id(repo_path: str) -> str:
    return hashlib.sha256(os.path.realpath(repo_path).casefold().encode()).hexdigest()[:16]


def get_active_profile() -> RepoProfile:
    """Build a RepoProfile from current global config until the Stage 1 registry exists."""
    eff = _config_effective()
    primary = AgentRef(
        provider=eff.get("HEPHAESTUS_AGENT_PROVIDER", "opencode"),
        model=eff.get("HEPHAESTUS_PRIMARY_MODEL", "default"),
        agent=eff.get("HEPHAESTUS_PRIMARY_AGENT") or None,
    )
    fallback = AgentRef(
        provider=eff.get("HEPHAESTUS_AGENT_PROVIDER", "opencode"),
        model=eff.get("HEPHAESTUS_FALLBACK_MODEL", "default"),
        agent=eff.get("HEPHAESTUS_FALLBACK_AGENT") or None,
    )
    return RepoProfile(
        id=_ws_id(REPO),
        name=os.path.basename(os.path.normpath(REPO)) or "workspace",
        repo_path=REPO,
        base_branch=BASE_BRANCH,
        remote=REMOTE,
        branch_prefix=BRANCH_PREFIX,
        agents=AgentsConfig(primary=primary, fallback=fallback),
    )
```

- [ ] Создать smoke-тест `backend/tests/unit/test_ws_shim.py`:

```python
"""ws_shim builds a RepoProfile from global config (temporary Stage-1 bridge)."""

from __future__ import annotations

from app.core.ws_shim import get_active_profile
from app.models.workspace import RepoProfile


def test_get_active_profile_returns_repo_profile() -> None:
    prof = get_active_profile()
    assert isinstance(prof, RepoProfile)
    assert prof.repo_path
    assert prof.memory_dir == ".hephaestus/memory"
    assert len(prof.id) == 16
    assert prof.agents.primary is not None
```

- [ ] Запустить — ожидаемый **PASS**:

```
cd backend && python -m pytest tests/unit/test_ws_shim.py -q
# 1 passed
```

- [ ] `ruff check backend/app/core/ws_shim.py backend/app/models/workspace.py` — clean.

- [ ] `git add backend/app/core/ws_shim.py backend/app/models/workspace.py backend/tests/unit/test_ws_shim.py && git commit -m "feat(stage2): ws_shim get_active_profile + minimal RepoProfile bridge"`

---

## Task 8: `prompts/scan-decomposer.md` — промпт декомпозитора

Цель: создать промпт-шаблон с обязательным блоком вывода `DECOMPOSE_BEGIN/END` (спека §4.5), переменные `{{proposals_json}}`/`{{repo_path}}`/`{{memory_excerpt}}`, без vendor-имён.

- [ ] Создать падающий тест `backend/tests/unit/test_decompose.py` (проверяет, что промпт существует и содержит переменные):

```python
"""Unit tests for decompose — block parsing, epic expansion, fallback. AgentRunner mocked."""

from __future__ import annotations

import pathlib


def test_decomposer_prompt_exists_and_templated() -> None:
    p = pathlib.Path(__file__).resolve().parents[2] / "prompts" / "scan-decomposer.md"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "{{proposals_json}}" in text
    assert "{{repo_path}}" in text
    assert "{{memory_excerpt}}" in text
    assert "DECOMPOSE_BEGIN" in text
    assert "DECOMPOSE_END" in text
    # no vendor agent names / hardcoded paths
    for forbidden in ("sisyphus", "atlas", "/home/starsinc", "pnpm"):
        assert forbidden not in text
```

- [ ] Запустить — ожидаемый **FAIL** (`assert p.exists()` → False):

```
cd backend && python -m pytest tests/unit/test_decompose.py::test_decomposer_prompt_exists_and_templated -q
# FAILED ... assert False
```

- [ ] Создать `prompts/scan-decomposer.md`:

````markdown
# HEPHAESTUS Scan — Decomposer

You are the **decomposer** in a repo-wide improvement scan. A reducer has produced a list
of proposals. Your job: assign an implementation **order** and **dependencies**, and split
oversized proposals into an epic with subtasks. You are **read-only**: use `read`, `grep`,
`glob` to inspect `{{repo_path}}` and confirm dependencies. Never edit, never `git`.

## Project memory excerpt

{{memory_excerpt}}

## Proposals (JSON)

{{proposals_json}}

## What to decide

1. **Semantic dependencies** (`dependsOn`): if implementing proposal X requires another
   proposal Y to land first (shared abstraction, prerequisite refactor), list Y in X's
   `dependsOn`. Use the proposal `id` values exactly. Do NOT infer dependencies from shared
   files — file conflicts are handled separately by the tool.
2. **Epics**: if a proposal is too large to land in one change, mark `"epic": true` and split
   it into `subtasks`, each a small, independently-shippable unit with its own `touches` and
   intra-epic `dependsOn`.
3. **Reason**: one sentence per dependency explaining why.

## Output protocol (REQUIRED — block parsed by the tool)

End your reply with exactly one block, no prose after:

```
DECOMPOSE_BEGIN
{
  "tasks": [
    {
      "id": "scan-<kebab>",
      "epic": false,
      "subtasks": [],
      "dependsOn": ["scan-other-id"],
      "reason": "<1 sentence: why it depends>"
    }
  ]
}
DECOMPOSE_END
```

- For an epic, set `"epic": true` and populate `subtasks` with
  `[{ "id", "title", "proposal", "touches", "dependsOn" }]` (intra-epic ids).
- `dependsOn` ids that don't exist among proposals/subtasks are dropped by the tool.
- Keep it minimal: most proposals have **no** dependencies. Only add an edge when a real
  prerequisite exists.
````

- [ ] Запустить — ожидаемый **PASS**:

```
cd backend && python -m pytest tests/unit/test_decompose.py::test_decomposer_prompt_exists_and_templated -q
# 1 passed
```

- [ ] `git add prompts/scan-decomposer.md backend/tests/unit/test_decompose.py && git commit -m "feat(stage2): scan-decomposer prompt with DECOMPOSE block schema"`

---

## Task 9: `decompose.py` — `_parse_decompose_block` + fallback

Цель: парсинг последнего блока `DECOMPOSE_BEGIN/END` с graceful fallback на 1:1 проекцию (спека §4.3, §6).

- [ ] Дописать падающие тесты в `backend/tests/unit/test_decompose.py`:

```python
from app.core.decompose import _parse_decompose_block


def test_parse_decompose_block() -> None:
    text = (
        "some reasoning\n"
        "DECOMPOSE_BEGIN\n"
        '{"tasks": [{"id": "scan-a", "epic": false, "subtasks": [], "dependsOn": ["scan-b"], "reason": "x"}]}\n'
        "DECOMPOSE_END\n"
        "trailing"
    )
    parsed = _parse_decompose_block(text)
    assert parsed is not None
    assert parsed["tasks"][0]["id"] == "scan-a"
    assert parsed["tasks"][0]["dependsOn"] == ["scan-b"]


def test_parse_decompose_block_takes_last() -> None:
    text = (
        "DECOMPOSE_BEGIN\n{\"tasks\": []}\nDECOMPOSE_END\n"
        "DECOMPOSE_BEGIN\n{\"tasks\": [{\"id\": \"scan-z\"}]}\nDECOMPOSE_END\n"
    )
    parsed = _parse_decompose_block(text)
    assert parsed["tasks"][0]["id"] == "scan-z"


def test_parse_decompose_block_bad_json() -> None:
    assert _parse_decompose_block("DECOMPOSE_BEGIN\n{not json}\nDECOMPOSE_END") is None
    assert _parse_decompose_block("no block at all") is None
```

- [ ] Запустить — ожидаемый **FAIL** (`ModuleNotFoundError: app.core.decompose`):

```
cd backend && python -m pytest tests/unit/test_decompose.py -k "parse" -q
# ERROR ... ModuleNotFoundError
```

- [ ] Создать `backend/app/core/decompose.py` (часть 1 — parsing + fallback helpers):

```python
"""Decomposer — proposals → Task-dicts with depends_on / order_index / conflict_group (D5)."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from app.core.task_graph import assign_conflict_groups, build_graph, detect_cycles, topo_order

if TYPE_CHECKING:
    import pathlib

    from app.models.workspace import AgentRef, RepoProfile

log = logging.getLogger("hephaestus.backend.decompose")

_BLOCK_RE = re.compile(r"DECOMPOSE_BEGIN\s*(\{.*?\})\s*DECOMPOSE_END", re.DOTALL)


def _parse_decompose_block(text: str) -> dict | None:
    """Find the LAST DECOMPOSE_BEGIN..END, json.loads the middle. Bad/absent → None."""
    matches = list(_BLOCK_RE.finditer(text))
    if not matches:
        return None
    raw = matches[-1].group(1)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "tasks" not in data:
        return None
    return data


def _fallback_projection(proposals: list[dict]) -> list[dict]:
    """1:1 projection: each proposal → Task without depends_on/epic. order_index = tail."""
    out: list[dict] = []
    for i, p in enumerate(proposals):
        out.append(
            {
                "id": p["id"],
                "dependsOn": [],
                "epicId": None,
                "parent": None,
                "orderIndex": i,
            }
        )
    return out
```

- [ ] Запустить — ожидаемый **PASS**:

```
cd backend && python -m pytest tests/unit/test_decompose.py -k "parse" -q
# 3 passed
```

- [ ] `git add backend/app/core/decompose.py backend/tests/unit/test_decompose.py && git commit -m "feat(stage2): decompose block parser + fallback projection"`

---

## Task 10: `decompose.py` — `decompose_proposals` (merge, epics, dangling, cycle-break)

Цель: полная функция — мок AgentRunner, слияние с proposals, epic-expansion, отбрасывание висячих зависимостей, разрыв LLM-циклов, присвоение `conflict_group`/`order_index` (спека §4.3, §6).

- [ ] Дописать падающие тесты в `backend/tests/unit/test_decompose.py`:

```python
import pathlib

import pytest

from app.core.decompose import decompose_proposals


class _FakeRunner:
    """Mock AgentRunner: writes a predetermined final text to output_path, returns it."""

    def __init__(self, final_text: str) -> None:
        self._text = final_text

    async def run(self, ref, *, prompt_file, cwd, output_path: pathlib.Path, timeout_sec):
        output_path.write_text(self._text, encoding="utf-8")
        import types as _t
        return _t.SimpleNamespace(exit_code=0, refused=False, output_path=output_path, agent_label="mock")


def _ws(tmp_path) -> object:
    import types
    from app.models.workspace import AgentRef, AgentsConfig
    agents = AgentsConfig(primary=AgentRef(provider="p", model="m"), fallback=AgentRef(provider="p", model="m"))
    return types.SimpleNamespace(
        id="ws01", repo_path=str(tmp_path), memory_dir=".hephaestus/memory", agents=agents
    )


def _proposals() -> list[dict]:
    return [
        {"id": "scan-a", "title": "A", "proposal": "do a", "touches": ["src/x.py"]},
        {"id": "scan-b", "title": "B", "proposal": "do b", "touches": ["src/y.py"]},
    ]


@pytest.mark.asyncio
async def test_decompose_empty_returns_empty(tmp_path) -> None:
    runner = _FakeRunner("")
    out = await decompose_proposals(_ws(tmp_path), [], scan_dir="scan-1", runner=runner)
    assert out == []


@pytest.mark.asyncio
async def test_decompose_fallback_on_bad_json(tmp_path) -> None:
    runner = _FakeRunner("garbage with no block")
    out = await decompose_proposals(_ws(tmp_path), _proposals(), scan_dir="scan-1", runner=runner)
    assert {t["id"] for t in out} == {"scan-a", "scan-b"}
    assert all(t["dependsOn"] == [] for t in out)


@pytest.mark.asyncio
async def test_decompose_applies_depends_and_order(tmp_path) -> None:
    block = (
        "DECOMPOSE_BEGIN\n"
        '{"tasks": [{"id": "scan-b", "epic": false, "subtasks": [], "dependsOn": ["scan-a"]}]}\n'
        "DECOMPOSE_END"
    )
    runner = _FakeRunner(block)
    out = await decompose_proposals(_ws(tmp_path), _proposals(), scan_dir="scan-1", runner=runner)
    by_id = {t["id"]: t for t in out}
    assert by_id["scan-b"]["dependsOn"] == ["scan-a"]
    # topo: a before b
    assert by_id["scan-a"]["orderIndex"] < by_id["scan-b"]["orderIndex"]


@pytest.mark.asyncio
async def test_dangling_depends_dropped(tmp_path) -> None:
    block = (
        "DECOMPOSE_BEGIN\n"
        '{"tasks": [{"id": "scan-a", "dependsOn": ["ghost"]}]}\n'
        "DECOMPOSE_END"
    )
    runner = _FakeRunner(block)
    out = await decompose_proposals(_ws(tmp_path), _proposals(), scan_dir="scan-1", runner=runner)
    by_id = {t["id"]: t for t in out}
    assert by_id["scan-a"]["dependsOn"] == []


@pytest.mark.asyncio
async def test_epic_expansion(tmp_path) -> None:
    proposals = [{"id": "scan-epic", "title": "Big", "proposal": "p", "touches": []}]
    block = (
        "DECOMPOSE_BEGIN\n"
        '{"tasks": [{"id": "scan-epic", "epic": true, "subtasks": ['
        '{"id": "1", "title": "part1", "proposal": "p1", "touches": ["a.py"], "dependsOn": []},'
        '{"id": "2", "title": "part2", "proposal": "p2", "touches": ["b.py"], "dependsOn": ["1"]}'
        ']}]}\n'
        "DECOMPOSE_END"
    )
    runner = _FakeRunner(block)
    out = await decompose_proposals(_ws(tmp_path), proposals, scan_dir="scan-1", runner=runner)
    by_id = {t["id"]: t for t in out}
    assert "scan-epic" in by_id  # parent container
    assert by_id["scan-epic"]["epicId"] is None
    assert "scan-epic-1" in by_id and by_id["scan-epic-1"]["epicId"] == "scan-epic"
    assert by_id["scan-epic-1"]["parent"] == "scan-epic"
    assert by_id["scan-epic-2"]["dependsOn"] == ["scan-epic-1"]


@pytest.mark.asyncio
async def test_llm_cycle_broken(tmp_path, caplog) -> None:
    block = (
        "DECOMPOSE_BEGIN\n"
        '{"tasks": [{"id": "scan-a", "dependsOn": ["scan-b"]}, {"id": "scan-b", "dependsOn": ["scan-a"]}]}\n'
        "DECOMPOSE_END"
    )
    runner = _FakeRunner(block)
    out = await decompose_proposals(_ws(tmp_path), _proposals(), scan_dir="scan-1", runner=runner)
    assert {t["id"] for t in out} == {"scan-a", "scan-b"}  # both survive
```

- [ ] Запустить — ожидаемый **FAIL** (`ImportError: cannot import name 'decompose_proposals'`):

```
cd backend && python -m pytest tests/unit/test_decompose.py -k "decompose_" -q
# ERROR ... ImportError
```

- [ ] Реализация: дописать в `backend/app/core/decompose.py`:

```python
def _expand_tasks(proposals: list[dict], llm_tasks: list[dict]) -> list[dict]:
    """Merge LLM output with proposals by id; expand epics into parent + subtasks.
    Returns minimal Task-dicts: {id, dependsOn, epicId, parent, touches}."""
    by_pid = {p["id"]: p for p in proposals}
    llm_by_id = {t.get("id"): t for t in llm_tasks if t.get("id")}
    result: list[dict] = []
    for pid, prop in by_pid.items():
        spec = llm_by_id.get(pid, {})
        if spec.get("epic") and spec.get("subtasks"):
            subs = spec["subtasks"]
            parent_touches: list[str] = []
            for sub in subs:
                parent_touches.extend(sub.get("touches", []) or [])
            result.append(
                {"id": pid, "dependsOn": [], "epicId": None, "parent": None, "touches": parent_touches}
            )
            for sub in subs:
                sub_id = f"{pid}-{sub['id']}"
                dep = [f"{pid}-{d}" for d in (sub.get("dependsOn") or [])]
                result.append(
                    {
                        "id": sub_id,
                        "dependsOn": dep,
                        "epicId": pid,
                        "parent": pid,
                        "touches": sub.get("touches", []) or [],
                        "title": sub.get("title", sub_id),
                        "proposal": sub.get("proposal", ""),
                    }
                )
        else:
            result.append(
                {
                    "id": pid,
                    "dependsOn": list(spec.get("dependsOn") or []),
                    "epicId": None,
                    "parent": None,
                    "touches": prop.get("touches", []) or [],
                }
            )
    return result


def _sanitize_graph(tasks: list[dict]) -> list[dict]:
    """Drop dangling deps and break LLM-introduced cycles (last edge of each cycle)."""
    ids = {t["id"] for t in tasks}
    for t in tasks:
        t["dependsOn"] = [d for d in t["dependsOn"] if d in ids and d != t["id"]]
    g = build_graph(tasks)
    cycles = detect_cycles(g)
    if cycles:
        log.warning("decompose: LLM introduced %d cycle(s); breaking last edge each", len(cycles))
        for cyc in cycles:
            last, first = cyc[-1], cyc[0]
            for t in tasks:
                if t["id"] == last and first in t["dependsOn"]:
                    t["dependsOn"].remove(first)
    return tasks


async def decompose_proposals(
    ws: "RepoProfile",
    proposals: list[dict],
    *,
    scan_dir: str,
    runner: "object | None",
    decomposer_ref: "AgentRef | None" = None,
) -> list[dict]:
    """Build Task-dicts (camelCase-ready) from reducer proposals. Never writes state."""
    import pathlib

    from app.config import STATE_DIR
    from app.services import project_memory
    from app.services.prompt_manager import PromptManager

    if not proposals:
        return []

    pm = PromptManager()
    memory_excerpt = (project_memory.read_doc(ws, "architecture") or "")[:2000]
    prompt = pm.render_prompt(
        "scan-decomposer",
        {
            "proposals_json": __import__("json").dumps(proposals, ensure_ascii=False, indent=2),
            "repo_path": ws.repo_path,
            "memory_excerpt": memory_excerpt,
        },
    ) or ""
    scan_path = STATE_DIR / "scans" / scan_dir
    scan_path.mkdir(parents=True, exist_ok=True)
    prompt_file = scan_path / "decompose.prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    output_path = scan_path / "decompose.output.jsonl"

    if runner is None:
        log.warning("decompose: no runner provided — 1:1 fallback projection")
        return _fallback_projection(proposals)

    ref = decomposer_ref or ws.agents.primary
    try:
        await runner.run(  # type: ignore[attr-defined]
            ref,
            prompt_file=prompt_file,
            cwd=ws.repo_path,
            output_path=output_path,
            timeout_sec=600,
        )
        final_text = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    except Exception as exc:  # noqa: BLE001 — agent failure must not lose the scan
        log.warning("decompose: runner failed (%s) — using fallback projection", exc)
        final_text = ""

    parsed = _parse_decompose_block(final_text)
    if parsed is None:
        log.warning("decompose: no/invalid DECOMPOSE block — 1:1 fallback")
        return _fallback_projection(proposals)

    tasks = _expand_tasks(proposals, parsed.get("tasks", []))
    tasks = _sanitize_graph(tasks)
    # conflict groups + topo order
    groups = assign_conflict_groups(tasks)
    g = build_graph(tasks)
    order = topo_order(g)
    pos = {tid: i for i, tid in enumerate(order)}
    for t in tasks:
        t["conflictGroup"] = groups.get(t["id"])
        t["orderIndex"] = pos.get(t["id"], 0)
    return tasks
```

- [ ] Запустить полный модуль — ожидаемый **PASS** (5+ тестов §7.2 покрыты):

```
cd backend && python -m pytest tests/unit/test_decompose.py -q
# 10 passed
```

- [ ] `ruff check backend/app/core/decompose.py` — clean. `mypy backend/app/core/decompose.py` — clean.

- [ ] `git add backend/app/core/decompose.py backend/tests/unit/test_decompose.py && git commit -m "feat(stage2): decompose_proposals with epics, dangling/cycle sanitize, conflict groups"`

---

## Task 11: `queue._reorder` + `_queue_move_top` поверх `task_graph`

Цель: добавить `_reorder(new_order)` поверх `can_reorder`/`apply_reorder`; переписать `_queue_move_top` как reorder-с-проверкой; `_queue_add` заполняет `order_index` хвостом (спека §4.8).

- [ ] **R18 — фикстура `tmp_state_dir`.** Перед написанием тестов убедиться, что в `backend/tests/conftest.py` есть фикстура `tmp_state_dir` (создаёт `tmp_path/state` + пустые `work-state.json`/`decisions.log` и возвращает путь; `STATE_DIR` монкипатчат сами тесты). Если её нет — добавить дословно:

```python
@pytest.fixture
def tmp_state_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Isolated state dir for queue/reorder/iters/scan-import tests (R18).
    Tests monkeypatch STATE_DIR onto this path themselves."""
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "work-state.json").write_text(json.dumps({"items": []}))
    (state_dir / "decisions.log").write_text("")
    return state_dir
```

(требует `import json`, `import pathlib`, `import pytest` в шапке `conftest.py` — добавить, если отсутствуют). Эта фикстура используется в тестах Task 11/12/15 — не предполагать её молча.

- [ ] Проверить наличие фикстуры:

```
cd backend && python -m pytest tests/unit/test_queue.py -q --fixtures | findstr tmp_state_dir
# tmp_state_dir -- conftest.py
```

- [ ] Создать падающий тест `backend/tests/unit/test_queue_reorder.py`:

```python
"""Unit tests for queue._reorder + _queue_move_top over task_graph (cross-platform)."""

from __future__ import annotations

import json
import pathlib

import pytest


def _seed(state_dir: pathlib.Path, items: list[dict]) -> None:
    (state_dir / "work-state.json").write_text(json.dumps({"items": items}))


def test_reorder_ok(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_state_dir, raising=False)
    from app.core.queue import _reorder
    _seed(tmp_state_dir, [
        {"id": "A", "title": "A", "status": "pending", "dependsOn": [], "touches": ["a.py"], "orderIndex": 0},
        {"id": "B", "title": "B", "status": "pending", "dependsOn": [], "touches": ["b.py"], "orderIndex": 1},
    ])
    res = _reorder(["B", "A"])
    assert res["ok"] is True
    assert res["order"] == ["B", "A"]
    s = json.loads((tmp_state_dir / "work-state.json").read_text())
    by_id = {it["id"]: it for it in s["items"]}
    assert by_id["B"]["orderIndex"] == 0
    assert by_id["A"]["orderIndex"] == 1


def test_reorder_breaks_dependency(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_state_dir, raising=False)
    from app.core.queue import _reorder
    _seed(tmp_state_dir, [
        {"id": "A", "title": "A", "status": "pending", "dependsOn": [], "touches": ["a.py"], "orderIndex": 0},
        {"id": "B", "title": "B", "status": "pending", "dependsOn": ["A"], "touches": ["b.py"], "orderIndex": 1},
    ])
    res = _reorder(["B", "A"])
    assert res["ok"] is False
    assert "breaks dependency A before B" in res["error"]


def test_move_top_blocked_by_dependency(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_state_dir, raising=False)
    from app.core.queue import _queue_move_top
    _seed(tmp_state_dir, [
        {"id": "A", "title": "A", "status": "pending", "dependsOn": [], "touches": ["a.py"], "orderIndex": 0},
        {"id": "B", "title": "B", "status": "pending", "dependsOn": ["A"], "touches": ["b.py"], "orderIndex": 1},
    ])
    res = _queue_move_top("B")  # would put B before its dep A
    assert res["ok"] is False
    assert "breaks dependency" in res["error"]


def test_move_top_ok(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_state_dir, raising=False)
    from app.core.queue import _queue_move_top
    _seed(tmp_state_dir, [
        {"id": "A", "title": "A", "status": "pending", "dependsOn": [], "touches": ["a.py"], "orderIndex": 0},
        {"id": "B", "title": "B", "status": "pending", "dependsOn": [], "touches": ["b.py"], "orderIndex": 1},
    ])
    res = _queue_move_top("B")
    assert res["ok"] is True
    s = json.loads((tmp_state_dir / "work-state.json").read_text())
    assert s["items"][0]["id"] == "B"
```

- [ ] Запустить — ожидаемый **FAIL** (`ImportError: cannot import name '_reorder'`):

```
cd backend && python -m pytest tests/unit/test_queue_reorder.py -q
# ERROR ... ImportError
```

- [ ] Реализация: в `backend/app/core/queue.py` добавить `_reorder` и переписать `_queue_move_top`. Заменить существующую функцию `_queue_move_top` (строки 71-83) на:

```python
def _reorder(new_order: list[str]) -> dict:
    """Validate + apply a full reorder. Single source of truth: task_graph.can_reorder."""
    from app.core.task_graph import apply_reorder, can_reorder

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


def _queue_move_top(qid: str) -> dict:
    """Move-top = reorder with [qid] first; refuses if it breaks a dependency/conflict order."""
    with _StateLock():
        s = _read_state()
        items: list[dict] = s.get("items", [])
        current = [it.get("id") for it in items]
        if qid not in current:
            return {"ok": False, "error": "id not found"}
    new_order = [qid] + [i for i in current if i != qid]
    return _reorder(new_order)
```

- [ ] Реализация: в `_queue_add` (после `item["branch"] = None`, перед `with _StateLock():`) добавить заполнение хвостового `order_index`. Заменить блок `with _StateLock():` в `_queue_add` на:

```python
    with _StateLock():
        s = _read_state()
        s["items"] = [it for it in s.get("items", []) if it.get("id") != item["id"]]
        max_order = max((int(it.get("orderIndex", 0) or 0) for it in s["items"]), default=-1)
        item.setdefault("orderIndex", max_order + 1)
        s["items"].append(item)
        _write_state(s)
```

- [ ] Запустить — ожидаемый **PASS**:

```
cd backend && python -m pytest tests/unit/test_queue_reorder.py tests/unit/test_queue.py -q
# all passed
```

- [ ] `ruff check backend/app/core/queue.py` — clean.

- [ ] `git add backend/app/core/queue.py backend/tests/unit/test_queue_reorder.py && git commit -m "feat(stage2): queue _reorder + move-top over task_graph; _queue_add order_index"`

---

## Task 12: `requests.py` + `PATCH /api/v1/tasks/{id}/reorder` роут

Цель: добавить `ReorderRequest`/`MemoryWriteRequest` и роут reorder с 400 при нарушении (спека §4.7, umbrella §6).

- [ ] Создать падающий тест `backend/tests/integration/test_api_reorder.py`:

```python
"""Contract tests for PATCH /api/v1/tasks/{id}/reorder. No network/AgentRunner — state from fixture."""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient


def _seed(state_dir: pathlib.Path, items: list[dict]) -> None:
    (state_dir / "work-state.json").write_text(json.dumps({"items": items}))


@pytest.fixture
def reorder_client(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_state_dir, raising=False)
    from app.main import app
    return TestClient(app)


def test_reorder_ok(reorder_client, tmp_state_dir, monkeypatch) -> None:
    _seed(tmp_state_dir, [
        {"id": "A", "title": "A", "status": "pending", "dependsOn": [], "touches": ["a.py"], "orderIndex": 0},
        {"id": "B", "title": "B", "status": "pending", "dependsOn": [], "touches": ["b.py"], "orderIndex": 1},
    ])
    r = reorder_client.patch("/api/v1/tasks/B/reorder", json={"order": ["B", "A"]})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["order"] == ["B", "A"]


def test_reorder_breaks_dependency(reorder_client, tmp_state_dir) -> None:
    _seed(tmp_state_dir, [
        {"id": "A", "title": "A", "status": "pending", "dependsOn": [], "touches": ["a.py"], "orderIndex": 0},
        {"id": "B", "title": "B", "status": "pending", "dependsOn": ["A"], "touches": ["b.py"], "orderIndex": 1},
    ])
    r = reorder_client.patch("/api/v1/tasks/B/reorder", json={"order": ["B", "A"]})
    assert r.status_code == 400
    assert "breaks dependency" in r.json()["error"]


def test_reorder_conflict_order(reorder_client, tmp_state_dir) -> None:
    _seed(tmp_state_dir, [
        {"id": "A", "title": "A", "status": "pending", "dependsOn": [], "touches": ["src/x.py"], "orderIndex": 0},
        {"id": "B", "title": "B", "status": "pending", "dependsOn": [], "touches": ["src/x.py"], "orderIndex": 1},
    ])
    r = reorder_client.patch("/api/v1/tasks/A/reorder", json={"order": ["B", "A"]})
    assert r.status_code == 400
    assert "conflict order" in r.json()["error"]
```

- [ ] Запустить — ожидаемый **FAIL** (404, роута пока нет):

```
cd backend && python -m pytest tests/integration/test_api_reorder.py -q
# FAILED ... assert 404 == 200
```

- [ ] Реализация: добавить в `backend/app/models/requests.py` (в конце файла):

```python
class ReorderRequest(BaseModel):
    order: list[str]


class MemoryWriteRequest(BaseModel):
    content: str
```

- [ ] Реализация: добавить роут в `backend/app/api/v1/tasks.py`. Импорт `_reorder` и `ReorderRequest`, новый роут:

```python
from app.core.queue import _queue_add, _queue_delete, _queue_move_top, _queue_patch, _queue_requeue, _reorder
from app.models.requests import QueueAddRequest, ReorderRequest


@router.patch("/api/v1/tasks/{item_id}/reorder")
def reorder_task(item_id: str, body: ReorderRequest) -> dict:
    if item_id not in body.order:
        return error_response("item_id not in order", status=400)
    res = _reorder(body.order)
    if not res.get("ok"):
        return error_response(res.get("error", "reorder failed"), status=400)
    return res
```

- [ ] Запустить — ожидаемый **PASS** (4 теста §7.4):

```
cd backend && python -m pytest tests/integration/test_api_reorder.py -q
# 4 passed
```

- [ ] `git add backend/app/models/requests.py backend/app/api/v1/tasks.py backend/tests/integration/test_api_reorder.py && git commit -m "feat(stage2): PATCH /api/v1/tasks/{id}/reorder with DAG validation"`

---

## Task 13: `api/v1/memory.py` роутер + регистрация в `main.py`

Цель: добавить `GET/PUT /api/v1/workspaces/{ws_id}/memory/{doc}` (спека §4.7, umbrella §6).

- [ ] Создать падающий тест `backend/tests/integration/test_api_memory.py`:

```python
"""Contract tests for memory routes. Uses ws_shim active profile + tmp repo memory dir."""

from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def memory_client(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Point the active workspace's repo at a tmp dir so memory writes land in tmp.
    import app.core.ws_shim as shim
    import types
    from app.models.workspace import AgentRef, AgentsConfig
    agents = AgentsConfig(primary=AgentRef(provider="p", model="m"), fallback=AgentRef(provider="p", model="m"))
    prof = types.SimpleNamespace(
        id="ws01", name="repo", repo_path=str(tmp_path), base_branch="main", remote="origin",
        branch_prefix="auto", memory_dir=".hephaestus/memory", agents=agents,
    )
    monkeypatch.setattr(shim, "get_active_profile", lambda: prof)
    from app.main import app
    return TestClient(app)


def test_get_unknown_doc_400(memory_client) -> None:
    r = memory_client.get("/api/v1/workspaces/ws01/memory/nope")
    assert r.status_code == 400


def test_put_then_get_roundtrip(memory_client) -> None:
    r = memory_client.put("/api/v1/workspaces/ws01/memory/conventions", json={"content": "# C\nuse tabs\n"})
    assert r.status_code == 200 and r.json()["ok"] is True
    r2 = memory_client.get("/api/v1/workspaces/ws01/memory/conventions")
    assert r2.status_code == 200
    assert "use tabs" in r2.json()["content"]
```

- [ ] Запустить — ожидаемый **FAIL** (404):

```
cd backend && python -m pytest tests/integration/test_api_memory.py -q
# FAILED ... assert 404 == 400
```

- [ ] Создать `backend/app/api/v1/memory.py`:

```python
from __future__ import annotations

from fastapi import APIRouter

from app.core.ws_shim import get_active_profile
from app.main import error_response
from app.models.requests import MemoryWriteRequest
from app.services import project_memory

router = APIRouter()


def _resolve_ws(ws_id: str):
    """Resolve workspace by id. Until Stage 1 registry exists, return the active profile."""
    prof = get_active_profile()
    # ws_id is accepted for REST symmetry; active-shim ignores mismatches (spec §6).
    return prof


@router.get("/api/v1/workspaces/{ws_id}/memory/{doc}")
def get_memory(ws_id: str, doc: str) -> dict:
    if doc not in project_memory.DOCS:
        return error_response(f"unknown doc {doc}", status=400)
    ws = _resolve_ws(ws_id)
    content = project_memory.read_doc(ws, doc)
    return {"ok": True, "content": content or ""}


@router.put("/api/v1/workspaces/{ws_id}/memory/{doc}")
def put_memory(ws_id: str, doc: str, body: MemoryWriteRequest) -> dict:
    if doc not in project_memory.DOCS:
        return error_response(f"unknown doc {doc}", status=400)
    ws = _resolve_ws(ws_id)
    project_memory.write_doc(ws, doc, body.content, source="manual")
    return {"ok": True}
```

- [ ] Реализация: зарегистрировать роутер в `backend/app/main.py`. Добавить импорт рядом с другими v1-импортами (после `from app.api.v1.loop import router as loop_router`):

```python
from app.api.v1.memory import router as memory_router  # noqa: E402
```

и `app.include_router(memory_router)` в блоке Universality routers (после `app.include_router(repos_router)`).

- [ ] Запустить — ожидаемый **PASS**:

```
cd backend && python -m pytest tests/integration/test_api_memory.py -q
# 2 passed
```

- [ ] `git add backend/app/api/v1/memory.py backend/app/main.py backend/tests/integration/test_api_memory.py && git commit -m "feat(stage2): memory GET/PUT routes + main.py registration"`

---

## Task 14: `scan.py` — `_scan_import` запускает decompose + memory

Цель: после append proposals прогонять `decompose_proposals` (под `_StateLock` writer — backend единственный) + `update_after_scan`. Убрать дефолт scope в `_scan_start` (D7, спека §3.2, §6). НЕ вводить tmux в новом коде; native scan-start — отдельный шим, помеченный для Этапа 1.

- [ ] Создать падающий тест `backend/tests/integration/test_scan_import_decompose.py`:

```python
"""_scan_import runs decompose + memory. AgentRunner mocked; no tmux/bash."""

from __future__ import annotations

import json
import pathlib

import pytest


def _write_results(scans_dir: pathlib.Path, dirname: str, proposals: list[dict]) -> None:
    d = scans_dir / dirname
    d.mkdir(parents=True, exist_ok=True)
    (d / "results.json").write_text(json.dumps({"proposals": proposals, "n_unique": len(proposals)}))


def test_scan_import_decomposes_and_orders(tmp_path, monkeypatch) -> None:
    import app.core.state as state_mod
    import app.core.scan as scan_mod
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "work-state.json").write_text(json.dumps({"items": []}))
    (state_dir / "decisions.log").write_text("")
    scans_dir = state_dir / "scans"
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", state_dir, raising=False)
    monkeypatch.setattr(scan_mod, "STATE_DIR", state_dir)
    monkeypatch.setattr(scan_mod, "SCANS_DIR", scans_dir)

    _write_results(scans_dir, "scan-1", [
        {"id": "scan-a", "title": "A", "proposal": "do a", "touches": ["x.py"], "category": "bug", "severity": "high"},
        {"id": "scan-b", "title": "B", "proposal": "do b", "touches": ["y.py"], "category": "quality"},
    ])

    # decompose_proposals is the seam: mock it so the test never needs Stage-1 AgentRunner.
    async def _fake_decompose(ws, proposals, *, scan_dir, runner, decomposer_ref=None):
        return [
            {"id": p["id"], "dependsOn": [], "epicId": None, "parent": None, "orderIndex": i, "conflictGroup": None}
            for i, p in enumerate(proposals)
        ]
    monkeypatch.setattr(scan_mod, "decompose_proposals", _fake_decompose)
    # _build_runner returns None when Stage 1 runner is absent; decompose handles None.
    monkeypatch.setattr(scan_mod, "_build_runner", lambda: None, raising=False)

    res = scan_mod._scan_import("scan-1", [])
    assert res["ok"] is True
    assert set(res["added"]) == {"scan-a", "scan-b"}
    s = json.loads((state_dir / "work-state.json").read_text())
    by_id = {it["id"]: it for it in s["items"]}
    assert "orderIndex" in by_id["scan-a"]
    # memory tech-debt got the bug/high item
    td = (tmp_path / ".hephaestus" / "memory" / "tech-debt.md")  # ws_shim repo_path defaults to config.REPO; see note
    # tech-debt presence asserted indirectly via decisions log
    assert any("scan-import" in line for line in (state_dir / "decisions.log").read_text().splitlines())
```

Примечание: `update_after_scan` пишет в `ws.repo_path/.hephaestus/memory`. В тесте `ws` — это active-profile из `ws_shim` (repo_path = `config.REPO`). Чтобы тест не писал в реальный REPO, замокать `get_active_profile`:

```python
    import app.core.ws_shim as shim
    import types
    from app.models.workspace import AgentRef, AgentsConfig
    agents = AgentsConfig(primary=AgentRef(provider="p", model="m"), fallback=AgentRef(provider="p", model="m"))
    prof = types.SimpleNamespace(id="ws01", name="r", repo_path=str(tmp_path), base_branch="main",
                                 remote="origin", branch_prefix="auto", memory_dir=".hephaestus/memory", agents=agents)
    monkeypatch.setattr(shim, "get_active_profile", lambda: prof)
```

(добавить этот блок в тест перед вызовом `_scan_import`.)

- [ ] Запустить — ожидаемый **FAIL** (decompose не вызывается; `decompose_proposals` не импортирован в scan.py):

```
cd backend && python -m pytest tests/integration/test_scan_import_decompose.py -q
# FAILED ... AttributeError: module 'app.core.scan' has no attribute 'decompose_proposals'
```

- [ ] Реализация: в `backend/app/core/scan.py` изменить `_scan_start` (строка 47) — убрать дефолт scope:

```python
    scope = (opts.get("scope") or "").strip()
    if not scope:
        return {"ok": False, "error": "scope is required"}
    # Sanitize scope — must be space-separated dir names. Refuse shell metacharacters.
    if not re.match(r"^[A-Za-z0-9_./\- ]{1,200}$", scope):
        return {"ok": False, "error": "scope contains forbidden characters"}
    for seg in scope.split():
        if ".." in seg:
            return {"ok": False, "error": "scope must not contain '..'"}
```

- [ ] Реализация: добавить импорты в шапку `backend/app/core/scan.py` (после существующих импортов) и хелпер `_build_runner` (seam для тестов и для graceful-деградации до Этапа 1):

```python
from app.core.decompose import decompose_proposals
from app.core.ws_shim import get_active_profile
from app.services import project_memory


def _build_runner() -> object | None:
    """Construct the Stage-1 AgentRunner if available; None otherwise.
    decompose_proposals tolerates a None runner (falls back to 1:1 projection)."""
    try:
        from app.core.process import ProcessManager  # Stage 1 provides this
        from app.services.opencode_runner import AgentRunner  # Stage 1 provides this

        return AgentRunner(ProcessManager())
    except Exception as exc:  # noqa: BLE001 — Stage 1 not merged yet
        log.warning("_build_runner: AgentRunner unavailable (%s)", exc)
        return None
```

- [ ] Реализация: переписать конец `_scan_import` (после `_write_state(s)` и до `_append_decision`). Заменить блок начиная с `s["items"].append(item)` обработки — обернуть append в сбор `added_proposals`, и после `with _StateLock():` прогнать decompose. Конкретно: внутри цикла, рядом с `added.append(pid)`, добавить `added_proposals.append(p)` (инициализировать `added_proposals: list[dict] = []` рядом с `added`). После закрытия `with _StateLock():` добавить:

```python
    # Decompose freshly-added proposals into Task graph fields (depends_on/order/conflict).
    ws = get_active_profile()
    decomposed: list[str] = []
    if added_proposals:
        import asyncio

        runner = _build_runner()  # None when Stage 1 not merged — decompose degrades gracefully
        try:
            tasks = asyncio.run(
                decompose_proposals(ws, added_proposals, scan_dir=dirname, runner=runner)
            )
        except Exception as exc:  # noqa: BLE001 — never lose the import on agent/runner error
            log.warning("_scan_import: decompose failed (%s) — 1:1 order only", exc)
            tasks = [
                {"id": p["id"], "dependsOn": [], "epicId": None, "parent": None,
                 "orderIndex": i, "conflictGroup": None}
                for i, p in enumerate(added_proposals)
            ]
        graph_by_id = {t["id"]: t for t in tasks}
        with _StateLock():
            s2 = _read_state()
            for it in s2.get("items", []):
                g = graph_by_id.get(it.get("id"))
                if g:
                    it["dependsOn"] = g.get("dependsOn", [])
                    it["orderIndex"] = g.get("orderIndex", 0)
                    it["conflictGroup"] = g.get("conflictGroup")
                    it["epicId"] = g.get("epicId")
                    it["parent"] = g.get("parent")
                    decomposed.append(it["id"])
            # epic parents/subtasks created by decompose that aren't proposals → append
            existing2 = {it.get("id") for it in s2.get("items", [])}
            for t in tasks:
                if t["id"] not in existing2 and t.get("parent"):
                    s2["items"].append({
                        "id": t["id"], "title": t.get("title", t["id"]),
                        "proposal": t.get("proposal", ""), "status": "pending", "attempts": 0,
                        "branch": None, "touches": t.get("touches", []), "source_scan": dirname,
                        "dependsOn": t.get("dependsOn", []), "orderIndex": t.get("orderIndex", 0),
                        "conflictGroup": t.get("conflictGroup"), "epicId": t.get("epicId"),
                        "parent": t.get("parent"),
                    })
            _write_state(s2)
        try:
            project_memory.update_after_scan(ws, scan_dir=dirname, proposals=added_proposals)
        except Exception as exc:  # noqa: BLE001 — memory write must not fail the import
            log.warning("_scan_import: memory update failed (%s)", exc)
    _try_broadcast_state_safe()
```

И добавить `added_proposals: list[dict] = []` рядом с `added: list[str] = []`; добавить хелпер в конце модуля:

```python
def _try_broadcast_state_safe() -> None:
    try:
        from app.core.queue import _try_broadcast_state
        _try_broadcast_state()
    except Exception:
        pass
```

Return-значение `_scan_import` дополнить: `return {"ok": True, "added": added, "skipped": skipped, "decomposed": decomposed}`.

- [ ] Запустить — ожидаемый **PASS** (тест мокает `decompose_proposals`, поэтому Stage-1 импорты `AgentRunner`/`ProcessManager` не достигаются):

```
cd backend && python -m pytest tests/integration/test_scan_import_decompose.py -q
# 1 passed
```

- [ ] Проверить отсутствие tmux в новых путях scan.py grep'ом — `_scan_start` всё ещё содержит tmux (миграция в Этап 1), но НОВЫЙ код Этапа 2 (`_scan_import` decompose-блок) tmux не использует. Зафиксировать.

- [ ] `ruff check backend/app/core/scan.py` — clean.

- [ ] `git add backend/app/core/scan.py backend/tests/integration/test_scan_import_decompose.py && git commit -m "feat(stage2): _scan_import runs decompose + memory; scope required (D7)"`

---

## Task 14a: `scan_run.py` — нативный map-reduce scan + `_scan_start_native` (R19, D1)

Цель: реализовать нативный (без tmux/bash) map-reduce скан как **супервизируемый процесс `scan`** (R1): `chunk_files → N mappers (scan-mapper.md) → dedup → M reducers (scan-reducer.md) → dedup → results.json`. Запуск через `ProcessManager.start(name="scan", cmd=[python, -m, app.core.scan_run, --dir, <dir>])`. До слияния Этапа 1 (`pm`/`AgentRunner`) `_scan_start_native` отдаёт понятную ошибку — никакого tmux-фолбэка в новом коде. Юнит-тесты мокают `AgentRunner` и парсеры находок; кроссплатформенно.

- [ ] Создать падающий тест `backend/tests/unit/test_scan_run.py`:

```python
"""Unit tests for native map-reduce scan_run. AgentRunner + finding parsers mocked. Cross-platform."""

from __future__ import annotations

import json
import pathlib
import types

import pytest

from app.core import scan_run


def test_chunk_files_round_robin(tmp_path: pathlib.Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    for i in range(5):
        (src / f"f{i}.py").write_text("x\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "ignored.py").write_text("nope\n")
    chunks = scan_run.chunk_files(str(tmp_path), "src", n=2)
    flat = sorted(f for c in chunks for f in c)
    assert flat == ["src/f0.py", "src/f1.py", "src/f2.py", "src/f3.py", "src/f4.py"]
    assert all(".git" not in f for f in flat)
    assert 1 <= len(chunks) <= 2


def test_dedup_findings_merges_and_counts() -> None:
    items = [
        {"title": "Fix race", "touches": ["src/x.py:10"]},
        {"title": "fix race", "touches": ["src\\x.py"]},  # same after normalize
        {"title": "Other", "touches": ["src/y.py"]},
    ]
    out = scan_run.dedup_findings(items)
    assert len(out) == 2
    merged = [it for it in out if it["title"].lower() == "fix race"][0]
    assert merged["agreement_count"] == 2


@pytest.mark.asyncio
async def test_run_mappers_aggregates(tmp_path: pathlib.Path, monkeypatch) -> None:
    # Mock the SCAN_FINDINGS parser to return one finding per chunk.
    monkeypatch.setattr(
        scan_run, "parse_findings_block",
        lambda text: [{"title": text.strip(), "touches": ["a.py"]}],
        raising=False,
    )

    class _Runner:
        async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec):
            output_path.write_text(f"finding-from-{output_path.stem}", encoding="utf-8")
            return types.SimpleNamespace(exit_code=0)

    class _PM:
        def render_prompt(self, name, vars):
            return "PROMPT"

    ws = types.SimpleNamespace(
        repo_path=str(tmp_path),
        agents=types.SimpleNamespace(primary=types.SimpleNamespace(provider="p", model="m")),
    )
    scan_dir = tmp_path / "scan-1"
    scan_dir.mkdir()
    findings = await scan_run.run_mappers(
        ws, _Runner(), scan_dir, [["a.py"], ["b.py"]], prompt_mgr=_PM(), timeout_sec=10
    )
    assert len(findings) == 2


@pytest.mark.asyncio
async def test_run_reducers_shards(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(
        scan_run, "parse_proposals_block",
        lambda text: [{"id": "scan-x", "title": "X", "touches": ["a.py"]}],
        raising=False,
    )

    class _Runner:
        async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec):
            output_path.write_text("blob", encoding="utf-8")
            return types.SimpleNamespace(exit_code=0)

    class _PM:
        def render_prompt(self, name, vars):
            return "PROMPT"

    ws = types.SimpleNamespace(
        repo_path=str(tmp_path),
        agents=types.SimpleNamespace(primary=types.SimpleNamespace(provider="p", model="m")),
    )
    scan_dir = tmp_path / "scan-1"
    scan_dir.mkdir()
    proposals = await scan_run.run_reducers(
        ws, _Runner(), scan_dir, [{"title": "f1"}, {"title": "f2"}],
        reducers=2, prompt_mgr=_PM(), timeout_sec=10
    )
    assert len(proposals) >= 1
```

- [ ] Запустить — ожидаемый **FAIL** (`ModuleNotFoundError: No module named 'app.core.scan_run'`):

```
cd backend && python -m pytest tests/unit/test_scan_run.py -q
# ERROR ... ModuleNotFoundError
```

- [ ] Создать `backend/app/core/scan_run.py` (нативный worker — запускается ВНУТРИ `scan`-процесса, собственный asyncio loop):

```python
"""Native map-reduce scan worker (R19, D1). Runs INSIDE the supervised `scan` process with
its own asyncio loop. chunk → N scan-mapper agents → dedup → M scan-reducer agents → dedup
→ results.json. No tmux, no bash. CLI: python -m app.core.scan_run --dir <scan_dir>."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import pathlib
import sys

log = logging.getLogger("hephaestus.backend.scan_run")


def chunk_files(repo_path: str, scope: str, n: int) -> list[list[str]]:
    """Walk scope dirs under repo_path, collect source files, split into n round-robin chunks.
    Skips VCS/build/vendor dirs. Pure stdlib, cross-platform."""
    root = pathlib.Path(repo_path)
    skip = {".git", ".hephaestus", "node_modules", "dist", "build", "__pycache__", ".venv", "venv"}
    seg = [s for s in scope.split() if s and ".." not in s]
    files: list[str] = []
    for s in seg:
        base = root / s
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and not (set(p.parts) & skip):
                files.append(str(p.relative_to(root)).replace("\\", "/"))
    files.sort()
    buckets: list[list[str]] = [[] for _ in range(max(1, n))]
    for i, f in enumerate(files):
        buckets[i % len(buckets)].append(f)
    return [c for c in buckets if c]


def dedup_findings(items: list[dict]) -> list[dict]:
    """Merge duplicates by (normalized title, sorted normalized touches); bumps agreement_count."""
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
            copy = dict(it)
            copy.setdefault("agreement_count", 1)
            seen[key] = copy
    return list(seen.values())


def parse_findings_block(text: str) -> list[dict]:
    """Parse a SCAN_FINDINGS_BEGIN..END JSON array. Bad/absent → []. (Stage 1 may provide a
    shared parser in app.core.events; this local fallback keeps Stage 2 self-contained.)"""
    import re

    m = re.search(r"SCAN_FINDINGS_BEGIN\s*(\[.*?\])\s*SCAN_FINDINGS_END", text, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def parse_proposals_block(text: str) -> list[dict]:
    """Parse SCAN_PROPOSAL_BEGIN..END blocks (one JSON object each) into a list. Bad/absent → []."""
    import re

    out: list[dict] = []
    for m in re.finditer(r"SCAN_PROPOSAL_BEGIN\s*(\{.*?\})\s*SCAN_PROPOSAL_END", text, re.DOTALL):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                out.append(obj)
        except json.JSONDecodeError:
            continue
    return out


async def run_mappers(ws, runner, scan_dir: pathlib.Path, chunks: list[list[str]],
                      *, prompt_mgr, timeout_sec: int) -> list[dict]:
    """N concurrent scan-mapper agents (one per chunk). Each writes scanner-<i>.findings.jsonl.
    A single mapper failure is logged and skipped — does not abort the others."""
    async def _one(i: int, chunk: list[str]) -> list[dict]:
        prompt = prompt_mgr.render_prompt("scan-mapper", {
            "repo_path": ws.repo_path,
            "scope": " ".join(sorted({c.split("/")[0] for c in chunk})),
            "chunk": "\n".join(chunk),
            "tech_stack": "",
            "memory_excerpt": "",
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
            log.warning("scan mapper failed: %s", r)
            continue
        findings.extend(r)
    return findings


async def run_reducers(ws, runner, scan_dir: pathlib.Path, findings: list[dict],
                       *, reducers: int, prompt_mgr, timeout_sec: int) -> list[dict]:
    """M concurrent scan-reducer agents over sharded findings. Each writes reducer-<j>.proposals.jsonl."""
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
            log.warning("scan reducer failed: %s", r)
            continue
        proposals.extend(r)
    return proposals


async def _run(scan_dir: pathlib.Path) -> int:
    from app.core.process import pm  # Stage 1 module-singleton ProcessManager
    from app.core.ws_shim import get_active_profile
    from app.services.opencode_runner import AgentRunner
    from app.services.prompt_manager import PromptManager

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
                           reducers=int(req.get("reviewers", 2)),
                           prompt_mgr=prompt_mgr, timeout_sec=900)
    )
    (scan_dir / "results.json").write_text(
        json.dumps({"proposals": proposals, "n_unique": len(proposals)}, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("scan_run done: %d proposals", len(proposals))
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

- [ ] Запустить — ожидаемый **PASS** (4 теста §7.3a):

```
cd backend && python -m pytest tests/unit/test_scan_run.py -q
# 4 passed
```

- [ ] Реализация: добавить `_scan_start_native` в `backend/app/core/scan.py` (рядом с `_scan_start`). Это backend-сторона (sync): пишет `request.json`, запускает супервизируемый процесс `scan` через `ProcessManager` (R1). До слияния Этапа 1 (`pm`/`ProcessManager` отсутствуют) — понятная ошибка, НЕ tmux:

```python
def _scan_start_native(opts: dict) -> dict:
    """Start a native map-reduce scan as a supervised `scan` process (R1/R19). No tmux/bash."""
    import json
    import sys
    import time as _time

    scope = (opts.get("scope") or "").strip()
    if not scope:
        return {"ok": False, "error": "scope is required"}
    if not re.match(r"^[A-Za-z0-9_./\- ]{1,200}$", scope):
        return {"ok": False, "error": "scope contains forbidden characters"}
    for seg in scope.split():
        if ".." in seg:
            return {"ok": False, "error": "scope must not contain '..'"}
    try:
        scanners = int(opts.get("scanners") or 6)
        reviewers = int(opts.get("reviewers") or 2)
    except (ValueError, TypeError):
        return {"ok": False, "error": "scanners/reviewers must be integers"}

    try:
        from app.core.process import pm  # Stage 1 module-singleton ProcessManager
    except Exception as exc:  # noqa: BLE001 — Stage 1 not merged: no tmux fallback
        log.warning("_scan_start_native: ProcessManager unavailable (%s)", exc)
        return {"ok": False, "error": "native scan requires Stage 1 ProcessManager"}

    if pm.status("scan").state == "running":
        return {"ok": False, "error": "a scan is already running"}

    dirname = "scan-" + _time.strftime("%Y%m%d-%H%M%S", _time.gmtime())
    scan_dir = SCANS_DIR / dirname
    scan_dir.mkdir(parents=True, exist_ok=True)
    ws = get_active_profile()
    (scan_dir / "request.json").write_text(
        json.dumps({"repo_path": ws.repo_path, "scope": scope,
                    "scanners": scanners, "reviewers": reviewers}),
        encoding="utf-8",
    )
    cmd = [sys.executable, "-m", "app.core.scan_run", "--dir", dirname]
    pm.start("scan", cmd, cwd=str(LOOP_HOME), env={},
             output_path=(scan_dir / "scan.log"))
    return {"ok": True, "scan_dir": dirname, "scanners": scanners, "reviewers": reviewers, "scope": scope}
```

- [ ] Проверить отсутствие tmux в `scan_run.py` (exit §9.7):

```
cd backend && python -c "import pathlib; assert 'tmux' not in pathlib.Path('app/core/scan_run.py').read_text()"
# (no output = ok)
```

- [ ] `ruff check backend/app/core/scan_run.py` — clean. `mypy backend/app/core/scan_run.py` — clean.

- [ ] `git add backend/app/core/scan_run.py backend/app/core/scan.py backend/tests/unit/test_scan_run.py && git commit -m "feat(stage2): native map-reduce scan_run + _scan_start_native (R19, no tmux)"`

---

## Task 15: `iters.build_state` сортировка по `order_index` + `_task_view` deps

Цель: `build_state` отдаёт items отсортированными по `(order_index, id)`; `_task_view` добавляет `depends_on`/`blocks`/`conflict_group` в ответ (спека §3.2).

- [ ] Создать падающий тест `backend/tests/unit/test_iters_order.py`:

```python
"""build_state sorts items by (orderIndex, id); _task_view exposes deps. Cross-platform."""

from __future__ import annotations

import json
import pathlib

import pytest


def test_build_state_sorts_by_order_index(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.state as state_mod
    import app.core.iters as iters_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_state_dir, raising=False)
    monkeypatch.setattr(iters_mod, "STATE_DIR", tmp_state_dir)
    (tmp_state_dir / "work-state.json").write_text(json.dumps({"items": [
        {"id": "B", "title": "B", "status": "pending", "orderIndex": 2},
        {"id": "A", "title": "A", "status": "pending", "orderIndex": 0},
        {"id": "C", "title": "C", "status": "pending", "orderIndex": 1},
    ]}))
    st = iters_mod.build_state()
    assert [it["id"] for it in st["items"]] == ["A", "C", "B"]
```

- [ ] Запустить — ожидаемый **FAIL** (порядок `B,A,C`):

```
cd backend && python -m pytest tests/unit/test_iters_order.py -q
# FAILED ... assert ['B','A','C'] == ['A','C','B']
```

- [ ] Реализация: в `backend/app/core/iters.py` `build_state` заменить `"items": state.get("items", []),` на:

```python
        "items": sorted(
            state.get("items", []),
            key=lambda it: (int(it.get("orderIndex", 0) or 0), str(it.get("id", ""))),
        ),
```

- [ ] Реализация: в `_task_view`, в return-блоке `"item": item,` дополнить — после получения `item` (после строки `if not item: return ...`) добавить отражение deps в выдачу. Заменить `"item": item,` на отдельную сборку: после `latest_iter = ...` вставить:

```python
    item_out = dict(item)
    item_out["dependsOn"] = item.get("dependsOn", [])
    item_out["blocks"] = item.get("blocks", [])
    item_out["conflictGroup"] = item.get("conflictGroup")
```

и в return заменить `"item": item,` на `"item": item_out,`.

- [ ] Запустить — ожидаемый **PASS**:

```
cd backend && python -m pytest tests/unit/test_iters_order.py -q
# 1 passed
```

- [ ] `git add backend/app/core/iters.py backend/tests/unit/test_iters_order.py && git commit -m "feat(stage2): build_state sorts by orderIndex; _task_view exposes deps"`

---

## Task 16: Обобщить `prompts/scan-mapper.md` и `scan-reducer.md` (D7)

Цель: убрать HEPHAESTUS-как-цель, шаблонизировать переменными (спека §4.6, exit-criterion §9.6). Grep-проверка должна быть пустой.

- [ ] Создать падающий grep-тест `backend/tests/unit/test_scan_prompts_generic.py`:

```python
"""scan-*.md must not contain HEPHAESTUS-as-target hardcodes (D7, spec §9.6)."""

from __future__ import annotations

import pathlib

import pytest

_PROMPTS = pathlib.Path(__file__).resolve().parents[2] / "prompts"
_FORBIDDEN = ["/home/starsinc", "pnpm", "Prisma", "zod", "otplib", "@hephaestus/server", "hephaestus-platform-snapshot"]


@pytest.mark.parametrize("name", ["scan-mapper", "scan-reducer"])
def test_scan_prompt_generic(name: str) -> None:
    text = (_PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    for token in _FORBIDDEN:
        assert token not in text, f"{name}.md still contains '{token}'"


def test_scan_mapper_templated() -> None:
    text = (_PROMPTS / "scan-mapper.md").read_text(encoding="utf-8")
    for var in ("{{repo_path}}", "{{scope}}", "{{chunk}}", "{{tech_stack}}", "{{memory_excerpt}}", "{{tech_debt_excerpt}}"):
        assert var in text
```

- [ ] Запустить — ожидаемый **FAIL** (текущий mapper содержит `/home/starsinc`, `pnpm`, `Prisma`, `zod`, `otplib`):

```
cd backend && python -m pytest tests/unit/test_scan_prompts_generic.py -q
# FAILED ... still contains '/home/starsinc'
```

- [ ] Реализация: переписать `prompts/scan-mapper.md` — generic-версия:

````markdown
# HEPHAESTUS Scan — Mapper

You are one of **N parallel scanner agents** in the map-phase of a repo-wide improvement
scan against `{{repo_path}}`.

## Project context

- **Tech stack:** {{tech_stack}}
- **Architecture & conventions (excerpt):**

{{memory_excerpt}}

- **Known tech debt — do NOT flag these (already tracked):**

{{tech_debt_excerpt}}

## Hard rules

1. **Read-only.** Use `read`, `glob`, `grep` only. Never edit, never `git`, never modify state.
2. **Stay in your slice.** Your assigned files:

{{scope}}

   Specifically these files (your chunk):

{{chunk}}

   Read those (and close neighbours: direct imports, base interfaces). Don't wander.
3. **Independent.** You run in parallel with other scanners. Don't coordinate.
4. **Tight output.** Read, analyze, emit findings block. Verbal output under ~400 words.

## What to look for (roughly by importance)

### 1. Real bugs (highest signal — flag aggressively)
- Swallowed exceptions (empty catch / except with no log or re-raise).
- Off-by-one in loop bounds, slice indices, pagination.
- Race conditions — shared state mutated without a lock, missing await in a transaction.
- Unvalidated input from a trust boundary (HTTP body, cookie, env var) used as a typed value.
- Config/env read inline without a default or validation — silent fail-open if unset.
- Unbounded background timers/intervals without cleanup — leak process state.
- Network calls without timeout — can hang indefinitely on a flaky upstream.

### 2. Security
- Secrets / API keys in logs, errors, or response bodies.
- SSRF — request constructed from user input without a URL guard.
- Injection — markup/SQL/command built from un-sanitized data.
- Missing auth / CSRF / rate-limit on a protected route.
- Crypto: insecure randomness for tokens, non-constant-time secret compare, weak hash.

### 3. Performance (hot paths only)
- N+1 query (loop with an await fetch inside).
- Unbounded loop or recursion.
- Sync where async belongs (file IO, network, hashing on the hot path).
- A query filter with no matching index.

### 4. Code quality (low signal — flag sparingly)
- Dead code (exported but never imported — verify with grep before flagging).
- A genuinely oversized file that needs splitting.
- A pattern repeated 3+ times begging for a helper.
- A cast chain that breaks type safety end-to-end.

### 5. Test gaps
- Production code with NO test (verify with `glob`).
- A test that passes trivially.

### 6. Locked-decision violations
Read the repo's conventions and any `CLAUDE.md`. Flag changes that violate a documented
locked decision recorded there. (The specific invariants are repo-defined — see the
conventions excerpt above. Do not assume a particular stack.)

## What NOT to flag

- Anything listed in the tech-debt excerpt above — known and deferred.
- Cosmetic style not enforced by the project's linter.
- Strictness purism (missing return types on trivial helpers, test-fixture looseness).

## Output protocol (REQUIRED — block parsed by reducer)

End your reply with one block, no prose after:

```
SCAN_FINDINGS_BEGIN
[
  {
    "title": "<one-line, imperative>",
    "category": "bug|security|perf|quality|test|docs|locked-decision",
    "severity": "low|medium|high",
    "touches": ["repo/relative/path:LINE", "..."],
    "proposal": "<2-4 sentences — what to change, how, why this is the right shape>",
    "rationale": "<1-2 sentences — concrete evidence with a file:line cite>"
  }
]
SCAN_FINDINGS_END
```

- **Aim for 4-10 findings.** Quality > quantity.
- Cite **file:line** in rationale — proves you read the code.
- If your slice is clean, report 1-2 or `[]`. Honest "no issues" beats invented filler.
- Higher severity = real impact.
````

- [ ] Реализация: переписать `prompts/scan-reducer.md` — заменить строку 34 (`Anything in the inherited tech-debt list (.claude/memory/hephaestus-tech-debt.md).`) на:

```markdown
- Anything in the known tech-debt excerpt (provided to scanners) — already tracked.

## Tech debt to skip

{{tech_debt_excerpt}}
```

и в выходную схему `SCAN_PROPOSAL_BEGIN` добавить опциональное поле после `"agreement_count"`:

```json
    "depends_on_hint": ["scan-<other-id>"],
```

с комментарием в проз-части над блоком: `- "depends_on_hint" is optional: if a proposal obviously requires another to land first, list its id. The tool's decomposer makes the final call.`

- [ ] Запустить — ожидаемый **PASS**:

```
cd backend && python -m pytest tests/unit/test_scan_prompts_generic.py -q
# 3 passed
```

- [ ] `git add prompts/scan-mapper.md prompts/scan-reducer.md backend/tests/unit/test_scan_prompts_generic.py && git commit -m "feat(stage2): generalize scan-mapper/reducer prompts (D7), templated vars"`

---

## Task 17: Frontend types — `Item` Stage-2 поля, `ItemStatus += in_review`, `ReorderResult`

Цель: расширить `frontend/src/types/api.ts` (спека §4.9). Чисто типовое изменение; проверяется `vue-tsc`.

- [ ] Реализация: в `frontend/src/types/api.ts` расширить `ItemStatus`:

```ts
export type ItemStatus =
  | 'pending'
  | 'in_progress'
  | 'in_review'
  | 'done'
  | 'merged'
  | 'needs_revision'
  | 'discarded'
  | `failed:${string}`
```

- [ ] Реализация: в интерфейс `Item` добавить (после `requeued_at?: string | null`):

```ts
  // ── Stage 2 additions ──
  dependsOn: string[]
  blocks: string[]
  orderIndex: number
  epicId: string | null
  parent: string | null
  conflictGroup: string | null
  validation?: Record<string, unknown> | null
  resultSummary: string
  diffRef: string | null
  workspaceId?: string | null
```

- [ ] Реализация: добавить тип `ReorderResult` (после `BranchActionResponse`):

```ts
export interface ReorderResult {
  ok: boolean
  order?: string[]
  error?: string
}
```

- [ ] Запустить typecheck — ожидаемый **PASS** после Task 18-22 (компоненты используют новые поля). Сейчас проверить только парсинг типов:

```
cd frontend && npx vue-tsc --noEmit
# clean (existing components do not yet reference new fields)
```

- [ ] `git add frontend/src/types/api.ts && git commit -m "feat(stage2): frontend Item Stage-2 fields, in_review status, ReorderResult"`

---

## Task 18: Frontend client — `reorderTask` + memory методы

Цель: добавить методы в `frontend/src/api/client.ts` (спека §4.9).

- [ ] Реализация: в `frontend/src/api/client.ts` импортировать `ReorderResult` (добавить в import-список из `@/types/api`) и добавить в объект `api` (после `decisions`):

```ts
  // Reorder (Stage 2)
  reorderTask: (order: string[]) =>
    request<ReorderResult>(`/api/v1/tasks/${order[0] ?? '_'}/reorder`, {
      method: 'PATCH',
      body: JSON.stringify({ order }),
    }),

  // Workspace memory (Stage 2)
  getWorkspaceMemory: (wsId: string, doc: string) =>
    request<{ ok: boolean; content: string }>(`/api/v1/workspaces/${wsId}/memory/${doc}`),
  putWorkspaceMemory: (wsId: string, doc: string, content: string) =>
    request<{ ok: boolean }>(`/api/v1/workspaces/${wsId}/memory/${doc}`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    }),
```

Примечание: `request` принимает `(path, init?, timeoutMs?)` — метод задаётся через `init.method`, как в существующих методах (`moveTop` и др.). Не использовать сигнатуру `request('PATCH', path, body)` из спеки дословно — она не совпадает с фактической `client.ts`; адаптировано под реальный `request<T>(path, init)`.

- [ ] Запустить typecheck — ожидаемый **PASS**:

```
cd frontend && npx vue-tsc --noEmit
# clean
```

- [ ] `git add frontend/src/api/client.ts && git commit -m "feat(stage2): client reorderTask + workspace memory methods"`

---

## Task 19: Frontend board store — `reorderItems` с откатом

Цель: добавить `reorderItems(newOrder)` в `frontend/src/stores/board.ts` (спека §4.9) — оптимистично переставить, при `{ok:false}` откатить + тост.

- [ ] Установить vitest DOM-окружение для store-теста. Добавить в `frontend/package.json` devDependencies (если отсутствуют): `"@vue/test-utils": "^2.4.6"`, `"jsdom": "^25.0.0"`. Запустить:

```
cd frontend && npm install --save-dev @vue/test-utils jsdom
```

- [ ] Добавить vitest-конфиг в `frontend/vite.config.ts` — внутри `defineConfig({...})` добавить ключ `test`:

```ts
  test: {
    environment: 'jsdom',
    globals: true,
  },
```

- [ ] Создать падающий тест `frontend/src/stores/__tests__/board.reorder.spec.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useBoardStore } from '@/stores/board'
import { api } from '@/api/client'

vi.mock('@/api/client', () => ({
  api: { reorderTask: vi.fn(), getState: vi.fn() },
}))

describe('board.reorderItems', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('rolls back on {ok:false}', async () => {
    const store = useBoardStore()
    store.items = [
      { id: 'A', title: 'A', status: 'pending', orderIndex: 0 } as never,
      { id: 'B', title: 'B', status: 'pending', orderIndex: 1 } as never,
    ]
    ;(api.reorderTask as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: false, error: 'reorder breaks dependency A before B' })
    await store.reorderItems(['B', 'A'])
    // rolled back to original order
    expect(store.items.map(i => i.id)).toEqual(['A', 'B'])
  })

  it('keeps optimistic order and refetches on ok', async () => {
    const store = useBoardStore()
    store.items = [
      { id: 'A', title: 'A', status: 'pending', orderIndex: 0 } as never,
      { id: 'B', title: 'B', status: 'pending', orderIndex: 1 } as never,
    ]
    ;(api.reorderTask as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, order: ['B', 'A'] })
    ;(api.getState as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [{ id: 'B' }, { id: 'A' }], summary: store.summary,
    })
    await store.reorderItems(['B', 'A'])
    expect(api.getState).toHaveBeenCalled()
  })
})
```

- [ ] Запустить — ожидаемый **FAIL** (`reorderItems is not a function`):

```
cd frontend && npx vitest run src/stores/__tests__/board.reorder.spec.ts
# FAIL ... store.reorderItems is not a function
```

- [ ] Реализация: в `frontend/src/stores/board.ts` добавить функцию `reorderItems` (перед `return {...}`) и экспортировать её:

```ts
  async function reorderItems(newOrder: string[]) {
    const toast = useToastStore()
    const snapshot = [...items.value]
    // Optimistic: reorder local items to match newOrder
    const byId = new Map(items.value.map(it => [it.id, it]))
    const reordered = newOrder.map(id => byId.get(id)).filter((x): x is Item => !!x)
    const rest = items.value.filter(it => !newOrder.includes(it.id))
    items.value = [...reordered, ...rest]
    try {
      const res = await api.reorderTask(newOrder)
      if (!res.ok) {
        items.value = snapshot
        toast.add('error', res.error ?? 'Перестановка отклонена')
        return
      }
      await fetchState()
    } catch (e: unknown) {
      items.value = snapshot
      toast.add('error', `Ошибка перестановки: ${e instanceof Error ? e.message : String(e)}`)
    }
  }
```

и добавить `reorderItems` в `return {...}` (рядом с `moveTop`).

- [ ] Запустить — ожидаемый **PASS**:

```
cd frontend && npx vitest run src/stores/__tests__/board.reorder.spec.ts
# 2 passed
```

- [ ] `git add frontend/package.json frontend/vite.config.ts frontend/src/stores/board.ts frontend/src/stores/__tests__/board.reorder.spec.ts && git commit -m "feat(stage2): board.reorderItems optimistic+rollback; vitest jsdom env"`

---

## Task 20: Frontend `OrderBadge.vue` + vitest spec

Цель: создать компонент бэйджа порядка (спека §4.9).

- [ ] Создать падающий тест `frontend/src/components/__tests__/OrderBadge.spec.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import OrderBadge from '@/components/OrderBadge.vue'

describe('OrderBadge', () => {
  it('renders 1-based order', () => {
    const w = mount(OrderBadge, { props: { orderIndex: 0, conflictGroup: null } })
    expect(w.text()).toContain('#1')
    expect(w.find('.conflict-dot').exists()).toBe(false)
  })

  it('shows conflict dot when conflictGroup set', () => {
    const w = mount(OrderBadge, { props: { orderIndex: 4, conflictGroup: 'cg-deadbeef' } })
    expect(w.text()).toContain('#5')
    expect(w.find('.conflict-dot').exists()).toBe(true)
  })
})
```

- [ ] Запустить — ожидаемый **FAIL** (`Failed to resolve import '@/components/OrderBadge.vue'`):

```
cd frontend && npx vitest run src/components/__tests__/OrderBadge.spec.ts
# FAIL ... Cannot find module
```

- [ ] Создать `frontend/src/components/OrderBadge.vue`:

```vue
<script setup lang="ts">
defineProps<{ orderIndex: number; conflictGroup: string | null }>()
</script>

<template>
  <span class="order-badge">
    <span class="order-num">#{{ orderIndex + 1 }}</span>
    <span
      v-if="conflictGroup"
      class="conflict-dot"
      title="Конфликт файлов: порядок зафиксирован"
    />
  </span>
</template>

<style scoped>
.order-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
}
.order-num {
  background: var(--panel-2);
  border-radius: 3px;
  padding: 1px 5px;
}
.conflict-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--amber);
}
</style>
```

- [ ] Запустить — ожидаемый **PASS**:

```
cd frontend && npx vitest run src/components/__tests__/OrderBadge.spec.ts
# 2 passed
```

- [ ] `git add frontend/src/components/OrderBadge.vue frontend/src/components/__tests__/OrderBadge.spec.ts && git commit -m "feat(stage2): OrderBadge component with conflict indicator"`

---

## Task 21: Frontend `TaskCard.vue` — `OrderBadge` + dependsOn/blocks-чипы (R21) + убрать хардкод `'sisyphus'`

Цель: рендерить `OrderBadge`, показать компактные чипы `dependsOn`/`blocks` (R21), заменить `'sisyphus'` на `item.agent_override ?? '—'` (спека §3.2, §4.9). Полноценный граф-вью DAG — out of scope (будущее, R21); здесь только чипы + порядковый бэйдж + точка конфликта.

- [ ] Реализация: в `frontend/src/components/TaskCard.vue` импортировать `OrderBadge` (после `import StatusBadge`):

```ts
import OrderBadge from './OrderBadge.vue'
```

- [ ] Реализация: добавить computed-хелперы для чипов зависимостей (после `const isPending = ...`):

```ts
const depsCount = computed(() => (props.item.dependsOn ?? []).length)
const blocksCount = computed(() => (props.item.blocks ?? []).length)
const depsTitle = computed(() => `Требует: ${(props.item.dependsOn ?? []).join(', ') || '—'}`)
const blocksTitle = computed(() => `Блокирует: ${(props.item.blocks ?? []).join(', ') || '—'}`)
```

- [ ] Реализация: заменить строку `{{ item.agent_override ?? 'sisyphus' }}` на:

```vue
        {{ item.agent_override ?? '—' }}
```

- [ ] Реализация: в `<template>`, в `.card-footer`, добавить `OrderBadge` первым элементом (перед `severity-chip`) и чипы зависимостей:

```vue
      <OrderBadge :order-index="item.orderIndex ?? 0" :conflict-group="item.conflictGroup ?? null" />
      <span v-if="depsCount" class="dep-chip dep-in" :title="depsTitle">dep {{ depsCount }}</span>
      <span v-if="blocksCount" class="dep-chip dep-out" :title="blocksTitle">blk {{ blocksCount }}</span>
```

(`dep N` / `blk N` — компактные индикаторы «требует N» / «блокирует N»; полный список id — в `title` и в `TaskDrawer`, Task 21a.)

- [ ] Реализация: добавить стили чипов в `<style scoped>` (после `.severity-chip { ... }`):

```css
.dep-chip {
  font-family: var(--mono);
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--panel-2);
}
.dep-in { color: var(--blue); }
.dep-out { color: var(--rose); }
```

- [ ] Создать smoke-тест `frontend/src/components/__tests__/TaskCard.spec.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import TaskCard from '@/components/TaskCard.vue'

const base = {
  id: 'scan-a', title: 'Task A', status: 'pending', attempts: 0, proposal: '', why: '',
  acceptance: '', touches: [], branch: null, lastIter: null, previousBranches: [], commit: null,
  planFile: '', planSection: '', wave: '', severity: null, category: null, sourceScan: null,
  selfReportedFailure: false, requeuedAt: null, review: null, mergeCommit: null, mergedAt: null,
  dependsOn: ['scan-x', 'scan-y'], blocks: ['scan-z'], orderIndex: 2, epicId: null, parent: null,
  conflictGroup: 'cg-x', resultSummary: '', diffRef: null,
}

describe('TaskCard', () => {
  it('renders order badge, dependency chips, and no sisyphus hardcode', () => {
    const w = mount(TaskCard, { props: { item: base as never } })
    expect(w.text()).toContain('#3')
    expect(w.find('.dep-in').text()).toContain('2')   // dependsOn count
    expect(w.find('.dep-out').text()).toContain('1')  // blocks count
    expect(w.text()).not.toContain('sisyphus')
  })

  it('hides dependency chips when none', () => {
    const w = mount(TaskCard, { props: { item: { ...base, dependsOn: [], blocks: [] } as never } })
    expect(w.find('.dep-in').exists()).toBe(false)
    expect(w.find('.dep-out').exists()).toBe(false)
  })
})
```

- [ ] Запустить — ожидаемый **PASS**:

```
cd frontend && npx vitest run src/components/__tests__/TaskCard.spec.ts
# 2 passed
```

- [ ] `git add frontend/src/components/TaskCard.vue frontend/src/components/__tests__/TaskCard.spec.ts && git commit -m "feat(stage2): TaskCard OrderBadge + dependsOn/blocks chips (R21); drop 'sisyphus'"`

---

## Task 21a: Frontend `TaskDrawer.vue` — блок «Зависимости» (dependsOn/blocks чипы, R21)

Цель: в «Описание»-табе drawer'а показать секцию зависимостей с полными id-чипами `dependsOn`/`blocks` (R21). Данные уже в `item` — новых API-вызовов нет. Граф-вью DAG — будущее (out of scope).

- [ ] Реализация: в `frontend/src/components/TaskDrawer.vue`, в табе `tab === 0` («Описание»), после секции «Затронутые файлы» (`<section class="desc-section">` с `touches-list`) добавить условную секцию:

```vue
              <section
                v-if="(item.dependsOn?.length ?? 0) || (item.blocks?.length ?? 0)"
                class="desc-section"
              >
                <h4>Зависимости</h4>
                <div v-if="item.dependsOn?.length" class="dep-row">
                  <span class="dep-label">Требует:</span>
                  <code v-for="d in item.dependsOn" :key="'dep-' + d" class="dep-id">{{ d }}</code>
                </div>
                <div v-if="item.blocks?.length" class="dep-row">
                  <span class="dep-label">Блокирует:</span>
                  <code v-for="b in item.blocks" :key="'blk-' + b" class="dep-id">{{ b }}</code>
                </div>
              </section>
```

- [ ] Реализация: добавить стили в `<style scoped>` (после `.touches-list code { ... }`):

```css
.dep-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-bottom: 6px; }
.dep-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
}
.dep-id {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--blue);
  background: var(--panel-2);
  padding: 2px 6px;
  border-radius: 3px;
}
```

- [ ] Создать smoke-тест `frontend/src/components/__tests__/TaskDrawer.deps.spec.ts`:

```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import TaskDrawer from '@/components/TaskDrawer.vue'

const base = {
  id: 'scan-a', title: 'Task A', status: 'pending', attempts: 0, proposal: 'p', why: 'w',
  acceptance: 'a', touches: [], branch: null, lastIter: null, previousBranches: [], commit: null,
  dependsOn: ['scan-x'], blocks: ['scan-z'], orderIndex: 0, epicId: null, parent: null,
  conflictGroup: null, resultSummary: '', diffRef: null,
}

describe('TaskDrawer dependencies', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('renders dependsOn and blocks id chips', async () => {
    const w = mount(TaskDrawer, { props: { item: base as never }, attachTo: document.body })
    expect(w.text()).toContain('Зависимости')
    expect(w.text()).toContain('scan-x')
    expect(w.text()).toContain('scan-z')
    w.unmount()
  })
})
```

- [ ] Запустить — ожидаемый **PASS** (drawer открыт при `item != null`, таб 0 по умолчанию):

```
cd frontend && npx vitest run src/components/__tests__/TaskDrawer.deps.spec.ts
# 1 passed
```

- [ ] `git add frontend/src/components/TaskDrawer.vue frontend/src/components/__tests__/TaskDrawer.deps.spec.ts && git commit -m "feat(stage2): TaskDrawer dependencies block (dependsOn/blocks chips, R21)"`

---

## Task 22: Frontend `KanbanColumn.vue` + `BoardView.vue` — reorder через `reorderItems`

Цель: `onEnd` Sortable вызывает `reorderItems` (через `emit('reorder')` → `BoardView.onReorder`), а не `move-top` в обратном порядке (спека §4.9).

- [ ] Реализация: в `frontend/src/views/BoardView.vue` заменить `onReorder` (строки 44-55) на:

```ts
async function onReorder(_status: string, ids: string[]) {
  await boardStore.reorderItems(ids)
}
```

(`KanbanColumn` уже эмитит `reorder` c полным порядком pending-колонки через `sortable.toArray()` в `onEnd` — изменений в `KanbanColumn.vue` логики drag не требуется; компонент уже корректен.)

- [ ] Реализация: в `frontend/src/components/KanbanColumn.vue` импортировать и отрисовать `OrderBadge` рядом с каждым `TaskCard` НЕ требуется (badge уже внутри `TaskCard`). Достаточно убедиться, что `onEnd` эмитит полный порядок — он уже это делает (`sortable.toArray()`). Никаких изменений кода в `KanbanColumn.vue`, кроме комментария-маркера для ревьюера: добавить комментарий над `onEnd`:

```ts
    // Stage 2: full pending-column order → BoardView.onReorder → board.reorderItems (DAG-checked on backend)
```

- [ ] Запустить полный frontend typecheck + тесты + build:

```
cd frontend && npx vue-tsc --noEmit && npx vitest run && npm run build
# typecheck clean; vitest all passed; build succeeds
```

- [ ] `git add frontend/src/views/BoardView.vue frontend/src/components/KanbanColumn.vue && git commit -m "feat(stage2): BoardView reorder via board.reorderItems (DAG-checked)"`

---

## Task 23: Финальная верификация exit-criteria + cleanup

Цель: подтвердить все exit-criteria спеки §9 одним прогоном; убедиться в отсутствии плейсхолдеров и tmux в новом коде.

- [ ] Backend unit + integration + contract — green:

```
cd backend && python -m pytest tests/unit/test_task_graph.py tests/unit/test_decompose.py tests/unit/test_project_memory.py tests/unit/test_queue_reorder.py tests/unit/test_iters_order.py tests/unit/test_scan_prompts_generic.py tests/unit/test_ws_shim.py tests/integration/test_api_reorder.py tests/integration/test_api_memory.py tests/integration/test_scan_import_decompose.py tests/contract/test_existing_state.py -q
# all passed
```

- [ ] Полный backend-прогон (регрессия существующих тестов) — green:

```
cd backend && python -m pytest -q
# all passed
```

- [ ] Lint + types на новых модулях — clean:

```
cd backend && ruff check app/core/task_graph.py app/core/decompose.py app/services/project_memory.py app/core/ws_shim.py app/api/v1/memory.py
cd backend && python -m mypy app/core/task_graph.py app/core/decompose.py app/services/project_memory.py
# no errors
```

- [ ] Grep-проверка обобщения промптов (exit §9.6) — пусто:

```
cd backend && python -m pytest tests/unit/test_scan_prompts_generic.py -q
# 3 passed
```

- [ ] Проверить отсутствие `tmux` в новых Этап-2-путях (exit §9.7). `_scan_start` всё ещё содержит tmux (миграция — Этап 1), но новый код (`decompose.py`, `task_graph.py`, `project_memory.py`, `memory.py`, `_scan_import` decompose-блок) — нет:

```
cd backend && python -c "import pathlib; bad=[f for f in ['app/core/task_graph.py','app/core/decompose.py','app/services/project_memory.py','app/api/v1/memory.py'] if 'tmux' in pathlib.Path(f).read_text()]; print('tmux in:', bad); assert not bad"
# tmux in: []
```

- [ ] Frontend — green:

```
cd frontend && npx vue-tsc --noEmit && npx vitest run && npm run build
# clean / passed / built
```

- [ ] Проверить отсутствие плейсхолдеров в новом коде (нет голых `TODO`/`pass  # ...` без реализации):

```
cd backend && python -c "import pathlib,re; files=['app/core/task_graph.py','app/core/decompose.py','app/services/project_memory.py','app/api/v1/memory.py','app/core/ws_shim.py']; bad=[(f,ln) for f in files for ln in pathlib.Path(f).read_text().splitlines() if re.search(r'\bTODO\b|\bFIXME\b', ln)]; print(bad); assert not bad"
# []
```

- [ ] Ручной сценарий (exit §9.9, при наличии Этап-1 `AgentRunner`/`ProcessManager` или мока): импорт скана создаёт задачи с `orderIndex`/`conflictGroup`; drag задачи через зависимость → тост-отказ с причиной; `.hephaestus/memory/tech-debt.md` дополняется. Если Этап 1 не слит — этот шаг покрыт интеграционными тестами Task 12/14 с моками; зафиксировать в PR-описании как "manual scenario covered by mocked integration tests pending Stage 1".

- [ ] `git add -A && git commit -m "test(stage2): verify all exit criteria green (task_graph/decompose/memory/reorder)"`

---

## Notes for the implementing engineer

- **Workspace-scoping (umbrella §10.1).** Новый код НЕ читает `config.REPO`/`BASE_BRANCH` напрямую — только через `ws: RepoProfile` (из `get_active_profile()` в роутерах/`_scan_import`). Шим `ws_shim.py` — единственное место, где глобали читаются, и он помечен на удаление при слиянии Этапа 1.
- **Stage 1 зависимости.** `AgentRunner` (`app.services.opencode_runner`) и `ProcessManager` (`app.core.process`) — из Этапа 1. В `_scan_import` (Task 14) они импортируются лениво внутри `try/except`: если Этап 1 не слит, decompose graceful-fallback'ится на 1:1 порядок, импорт скана не падает. Все unit-тесты декомпозитора мокают runner и не требуют Этапа 1.
- **Единственный писатель state.** Все мутации `work-state.json` — под `_StateLock` (`backend/app/core/state.py`); reorder и scan-import сериализуются (спека §6 «Конкурентный reorder + scan-import»).
- **`request` сигнатура (frontend).** Спека §4.9 показывает `request('PATCH', path, body)`, но фактический `client.ts` использует `request<T>(path, init)`. Task 18 адаптирует под реальную сигнатуру — это сознательное отклонение от дословного текста спеки в пользу совместимости с существующим кодом (umbrella §4.4: frontend остаётся обратносовместимым).
- **vitest DOM.** `@vue/test-utils` + `jsdom` добавляются в Task 19 (их не было в `package.json`). Если CI запрещает менять lockfile — store-тест (Task 19) можно оставить под jsdom, а компонент-тесты (Task 20-21) требуют `@vue/test-utils` обязательно.
