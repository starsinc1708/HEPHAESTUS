---
title: HEPHAESTUS Epic 4 — Insights (agentic project chat) + Ideas (low-hanging fruit)
status: approved
date: 2026-06-06
audience: implementing engineer
language: prose=ru, identifiers/paths/commands=en
depends_on: [2026-06-05-universal-tool-overview-design, 2026-06-06-epic1-ai-powered-merge-design, 2026-06-06-epic2-autonomous-ralph-design]
defines_for: [epic4-insights-ideas-plan]
---

# Epic 4 — Insights + Ideas

Финальный эпик. Закрывает Aperant-фишки «Insights» (чат по проекту) и «Ideas» (быстрые улучшения).
Решения с пользователем:

- **D-e4-1.** Insights = **агентный поиск + лёгкий file→purpose индекс** (codebase_map). БЕЗ embeddings/vector-БД
  (вердикт исследования: для FastAPI-инструмента агентный поиск даёт ~80% пользы без тяжёлого Graphiti-стека).
- **D-e4-2.** Ideas = **отдельный модуль** (независимый генератор quick-wins), не через scan.

Переиспользуем: `AgentRunner.run(...)` (read-only прогон), `PromptManager.render_prompt`, `add_proposals_to_queue`
(Epic 2, `queue.py`), SSE-tail-паттерн `/api/v1/merge-jobs/{id}/stream` (Epic 1, `iters.py` tailing-цикл),
store-паттерн `MergeJobStore`/`GoalStore`, `project_memory.read_doc`.

---

## 1. Карта компонентов

| Часть | Артефакт | Статус |
|---|---|---|
| 4A | `codebase_map.py`: `build_map(ws, runner)` + `read_map(ws)` → `<repo>/.hephaestus/memory/codebase_map.json` | новый |
| 4A | `prompts/codebase-map.md` (file-tree → {path: purpose} JSON) | новый |
| 4B | `insights.py`: `InsightsSession`/`InsightsStore` + `ask(ws, question, *, session_id, runner)` | новый |
| 4B | `prompts/insights.md` (read-only investigator) | новый |
| 4B | API `api/v1/insights.py`: ask / sessions / stream(SSE) | новый |
| 4B | UI `InsightsChat.vue` (чат + live-стрим ответа) + view/route | новый |
| 4C | `ideas.py`: `generate_ideas(ws, *, categories, runner)` + `IdeaStore` + `import_ideas(ids)` | новый |
| 4C | `prompts/ideas.md` (quick-wins: security/perf/cleanup) | новый |
| 4C | API `api/v1/ideas.py`: generate / list / import | новый |
| 4C | UI `IdeasPanel.vue` (список идей + one-click импорт) | новый |
| — | register routers in `main.py` | правка |

**Границы.** `codebase_map` — только индекс (build/read). `insights` — сессии+агентный прогон, использует map+memory
как контекст. `ideas` — генерация+store+импорт, не зависит от insights. Каждый — самостоятельный модуль.

---

## 2. Часть 4A — codebase_map (file→purpose индекс)

`backend/app/services/codebase_map.py`:
```python
async def build_map(ws, *, runner, max_files: int = 400) -> dict[str, str]:
    """List tracked files (git ls-files, capped), ask the agent to label each with a
    one-line purpose -> {path: purpose}. Persist to <repo>/.hephaestus/memory/codebase_map.json.
    Never raises (partial/empty map on failure)."""

def read_map(ws) -> dict[str, str]:
    """Read codebase_map.json (or {} if absent)."""
```
- File list: `git ls-files` via `_run` (cap `max_files`; skip vendored dirs node_modules/.venv/dist via simple filters).
- Prompt `codebase-map.md`: input = file list; output = `MAP_BEGIN{"map":{"path":"purpose"}}MAP_END`. Parse leniently (regex, last match); failure → `{}`.
- Persisted JSON has the same frontmatter-free shape `{ "map": {...}, "updatedAt": "..." }`. `read_map` returns the inner map.
- Used by Insights as a navigation hint; rebuilt on demand (button) — NOT auto on every chat.

---

## 3. Часть 4B — Insights (agentic project chat)

### 3.1 Model + store (`backend/app/services/insights.py`)
```python
class InsightsTurn(BaseModel):
    role: str                 # "user" | "assistant"
    content: str
    iter_dir: str | None = Field(None, alias="iterDir")   # for streaming the assistant turn

class InsightsSession(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str                   # "ins-<8hex>"
    title: str = ""
    turns: list[InsightsTurn] = Field(default_factory=list)
    created_at: str | None = Field(None, alias="createdAt")
    updated_at: str | None = Field(None, alias="updatedAt")
```
`InsightsStore` persists `<state>/insights.json` (`{"sessions":[...]}`), `_StateLock`+atomic, methods list/get/put.

### 3.2 `ask(ws, question, *, session_id, runner) -> dict`
1. Load/create session; append a `user` turn.
2. Allocate an artifact dir `<state>/insights-NNNN` (monotonic, like merge-NNNN). Build the prompt from
   `prompts/insights.md` with: read-only-investigator instruction, prior turns (capped), `read_map(ws)` (file→purpose),
   memory excerpt (`project_memory.read_doc(ws,"architecture")[:2000]`), recent `git log` (`-n 20`), and the question.
3. Run the agent **read-only** in `cwd=ws.repo_path` (`AgentRunner.run(ref=ws.agents.primary, prompt_file, cwd, output_path=<dir>/output.insights.jsonl, timeout)`).
   The prompt MUST instruct: "You are READ-ONLY. Investigate with your search/read tools. DO NOT modify, create, or
   delete any files. Answer the question with file:line references." The loop never commits Insights runs.
4. Parse the final assistant text from the JSONL (reuse events parsing — extract text/finish parts), append an
   `assistant` turn with `iter_dir=insights-NNNN`, persist. Return `{sessionId, iterDir, answer}`.
- **Read-only caveat (R-e4):** isolation is by instruction + no-commit (lightweight, per D-e4-1). Before/after the run,
  capture `git status --porcelain`; if the set grew, log a warning and include `modifiedFiles` in the response — do
  NOT auto-clean (never touch the user's working tree). Worktree-isolation is a future hardening (out of scope).
- Forbidden while `loop RUNNING`? No — read-only, no git writes; allowed concurrently. But uses its own iter dir.

### 3.3 API (`backend/app/api/v1/insights.py`)
| Метод+путь | Назначение |
|---|---|
| `POST /api/v1/insights/ask` `{question, sessionId?}` | run a turn (sync, asyncio.run like goals); returns `{sessionId, iterDir, answer}` |
| `GET /api/v1/insights/sessions` · `GET /api/v1/insights/sessions/{id}` | list / get history |
| `GET /api/v1/insights/{iterDir}/stream` | SSE tail of `insights-NNNN/output.insights.jsonl` (copy merge-job stream; terminate when file stable ≥2s, 1800s cap) |
| `POST /api/v1/insights/rebuild-map` | `build_map(ws, runner)` → `{ok, count}` |

### 3.4 UI `InsightsChat.vue`
Chat transcript (user/assistant turns) + input. On send → `POST /ask` returns `iterDir` → open `LiveConsole`
(`streamUrl=/api/v1/insights/{iterDir}/stream`, reuse Epic 1 prop) to stream the assistant's investigation live;
on completion show the final answer. A "Rebuild project map" button → `rebuild-map`. New route/tab "Insights".

---

## 4. Часть 4C — Ideas (low-hanging fruit)

### 4.1 Model + store + generate (`backend/app/services/ideas.py`)
```python
class Idea(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str                   # "idea-<8hex>"
    title: str
    proposal: str = ""
    rationale: str = ""
    category: str = ""        # security | performance | cleanup | tests | docs
    severity: str = ""        # low | medium | high
    touches: list[str] = Field(default_factory=list)
    imported: bool = False

async def generate_ideas(ws, *, categories: list[str] | None, runner) -> list[Idea]:
    """Agent scans for quick wins -> Idea list. Persist to <state>/ideas.json. Never raises (empty on fail)."""
def import_ideas(ids: list[str]) -> dict:
    """Move selected ideas into the work queue via add_proposals_to_queue; mark imported. Returns {added:[...]}."""
```
- `IdeaStore` persists `<state>/ideas.json`; `generate_ideas` runs the agent with `prompts/ideas.md` (input: categories,
  memory excerpt, codebase_map; output `IDEAS_BEGIN{"ideas":[{title,proposal,rationale,category,severity,touches}]}IDEAS_END`).
- `import_ideas` maps selected `Idea`→proposal dict and calls `add_proposals_to_queue(props, source="ideas")`,
  sets `imported=True`.

### 4.2 API (`backend/app/api/v1/ideas.py`)
| Метод+путь | Назначение |
|---|---|
| `POST /api/v1/ideas/generate` `{categories?}` | generate + persist; returns `{ok, ideas:[...]}` |
| `GET /api/v1/ideas` | list persisted ideas |
| `POST /api/v1/ideas/import` `{ids}` | import selected → queue |

### 4.3 UI `IdeasPanel.vue`
"Generate ideas" (+ category filter) → list of idea cards (title, category/severity badges, proposal) with
checkboxes + "Import selected" → queue. Mount in ToolsView (or a new tab).

---

## 5. Безопасность

- Insights/ideas агент-прогоны: read-only по инструкции; loop НИКОГДА не коммитит их; стрэй-правки только
  детектируются (git status diff) и сообщаются, НЕ авточистятся (не трогаем рабочее дерево пользователя).
- Все generate/ask/build never-raise на битом LLM (пустой результат).
- codebase_map/ideas/insights — артефакты в state/`.hephaestus`; никаких внешних сервисов (агентный, без embeddings).
- SSE Insights завершается по стабильности файла (≥2с) + 1800с-cap + client disconnect (как merge-stream).
- `import_ideas` идемпотентен (add_proposals_to_queue пропускает существующие id).

---

## 6. Тестирование (TDD)

**Юнит (агент застаблен):**
- `codebase_map`: build с stub-runner (MAP-блок) + застабленный `git ls-files` → JSON; `read_map` пусто → {}.
- `_parse` блоки (MAP/IDEAS) — позитив/негатив.
- `InsightsStore`/`IdeaStore` round-trip.
- `ideas.generate_ideas` stub → Idea-список persisted; `import_ideas` → add_proposals_to_queue вызван, imported=True.

**Интеграция (stub runner + `_STATE_DIR_OVERRIDE`):**
- `insights.ask` stub → сессия с user+assistant turn, iter_dir выставлен, answer непустой; read-only (git status
  не изменился при stub, который ничего не пишет).
- `import_ideas` end-to-end → задачи в очереди с source="ideas".

**Контракт (FastAPI TestClient, ask/generate замоканы):**
- `/api/v1/insights/ask` → {sessionId, iterDir, answer}; sessions list/get; rebuild-map.
- `/api/v1/ideas/generate` → ideas; `/import` → added.

**Frontend (vitest):** InsightsChat renders transcript + streams; IdeasPanel lists + imports selected.

**Кроссплатформа:** subprocess (git ls-files) + stores — CI windows+ubuntu; агент застаблен.

---

## 7. Вне scope Эпика 4

- Embeddings/vector-store/semantic RAG (решено: агентный + file-map).
- Worktree-изоляция Insights-прогона (read-only по инструкции; hardening — будущее).
- Graph-память Aperant/Graphiti.
- Авто-rebuild codebase_map по расписанию (только по кнопке).
