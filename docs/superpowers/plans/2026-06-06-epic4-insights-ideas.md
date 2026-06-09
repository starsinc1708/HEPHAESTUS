# Epic 4 — Insights + Ideas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** An agentic project-chat ("Insights") backed by a lightweight file→purpose map (no embeddings), and an "Ideas" quick-wins generator with one-click import to the queue.

**Architecture:** `codebase_map` builds/reads a `{path: purpose}` JSON the agent uses for navigation. `insights` runs a READ-ONLY agent over the repo + map + memory + git log, streams via SSE, and persists chat sessions. `ideas` runs an agent to surface quick wins, persists them, and imports selected ones via the Epic 2 `add_proposals_to_queue` helper.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 / pytest; Vue 3 / Vitest. Agents via existing `AgentRunner`. No vector DB.

**Spec:** `docs/superpowers/specs/2026-06-06-epic4-insights-ideas-design.md` — source of truth; read first.

**Commands (EXACT):**
- Backend tests: `cd backend && .venv/Scripts/python.exe -m pytest tests/<path> -v`
- Lint/types: `cd backend && .venv/Scripts/python.exe -m ruff check .` (FULL — no unused imports in tests) and `.venv/Scripts/python.exe -m mypy --strict app/` (keep both clean)
- Frontend: `cd frontend && npx vitest run` / `npx vue-tsc --noEmit` / `npm run build`

**Conventions / read first:**
- `backend/app/core/merge_job.py` (Epic 1) — `MergeJobStore` (store pattern) + the monotonic `merge-NNNN` seq helper to mirror for `insights-NNNN`.
- `backend/app/core/goals.py` (Epic 2) — `_parse_plan_block` regex pattern (mirror for MAP/IDEAS blocks), store, agent-run-then-parse flow.
- `backend/app/core/queue.py` (Epic 2) — `add_proposals_to_queue(props, *, epic_id, source)`.
- `backend/app/services/opencode_runner.py` — `AgentRunner(pm, engine=, env=, profiles=).run(ref, prompt_file=, cwd=, output_path=, timeout_sec=, use_models=)`.
- `backend/app/services/prompt_manager.py` — `render_prompt`; `backend/app/services/merge_resolver.py`/Epic 1 — prompts-dir read pattern (LOOP_HOME). prompts/ at repo root.
- `backend/app/api/v1/merge.py` (Epic 1) — the SSE `merge_job_stream` (copy for insights stream) + `active_workspace()` + sync-handler+asyncio.run pattern (also goals.py / integrations.py).
- `backend/app/core/state.py` — `_state_dir`, `_StateLock`, `_atomic_write`, `_read_state`.
- `backend/app/services/project_memory.py` — `read_doc(ws, "architecture")`.
- `backend/app/core/scan.py` `_build_runner(ws)` — build an AgentRunner for one-off runs.
- `backend/app/core/events.py` — JSONL event parsing (extract final assistant text).
- `backend/app/main.py` — v1 router registration.
- Test patterns: `backend/tests/contract/test_merge_api.py`, `test_goals_api.py`, `backend/tests/integration/test_plan_goal.py` (stub runner + `_make_ws` + `_STATE_DIR_OVERRIDE`).

Branch `feat/epic4-insights-ideas`. One commit per task.

---

## BATCH A — codebase_map

### Task A1: build_map + read_map + prompt
**Files:** Create `backend/app/services/codebase_map.py`, `prompts/codebase-map.md`; Test `backend/tests/integration/test_codebase_map.py`.
- [ ] **Test** (stub runner writing a MAP block; stub `_run` for `git ls-files`):
```python
import asyncio, json, pathlib
import app.core.state as state
from app.services import codebase_map as cm
def test_build_and_read_map(tmp_path, monkeypatch):
    repo = tmp_path / "repo"; (repo / ".hephaestus" / "memory").mkdir(parents=True)
    monkeypatch.setattr("app.services.codebase_map._run", lambda cmd, **kw: "a.py\nb.py")
    ws = _make_ws(str(repo))
    class Stub:
        async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec, use_models=False):
            pathlib.Path(output_path).write_text('MAP_BEGIN{"map":{"a.py":"entry","b.py":"util"}}MAP_END')
            class R: exit_code = 0; refused = False
            return R()
    m = asyncio.run(cm.build_map(ws, runner=Stub()))
    assert m["a.py"] == "entry"
    assert cm.read_map(ws)["b.py"] == "util"
def test_read_map_absent(tmp_path):
    ws = _make_ws(str(tmp_path / "norepo"))
    assert cm.read_map(ws) == {}
```
(Add `_make_ws` helper — copy from an Epic 1/2 test.)
- [ ] Implement `prompts/codebase-map.md` (input `{files}`; output `MAP_BEGIN{"map":{"<path>":"<one-line purpose>"}}MAP_END`). Implement `build_map(ws, *, runner, max_files=400)`: `git ls-files` via `_run` (filter out node_modules/.venv/dist/.git; cap), render prompt, run agent (`ws.agents.primary`) → output file under `<repo>/.hephaestus/state/codebase-map.output.jsonl`, parse `MAP_BEGIN{...}MAP_END` (regex last match, json.loads), write `<repo>/.hephaestus/memory/codebase_map.json` = `{"map": <map>, "updatedAt": <ts>}`. Never raise → `{}` on any failure. `read_map(ws)` reads that file's `map` (or `{}`).
- [ ] `ruff check .` + mypy app/ clean. Commit: `feat(epic4): codebase_map build/read (file->purpose index)`

---

## BATCH B — Ideas backend

### Task B1: Idea model + store + generate + import + prompt
**Files:** Create `backend/app/services/ideas.py`, `prompts/ideas.md`; Test `backend/tests/integration/test_ideas.py`.
- [ ] **Test** (stub runner + `_STATE_DIR_OVERRIDE`):
```python
import asyncio, pathlib
import app.core.state as state
from app.services import ideas as ideas_mod
def test_generate_and_import(tmp_path, monkeypatch):
    sd = tmp_path / "st"; sd.mkdir(); monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)
    ws = _make_ws(str(tmp_path / "repo"))
    class Stub:
        async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec, use_models=False):
            pathlib.Path(output_path).write_text(
              'IDEAS_BEGIN{"ideas":[{"title":"Add index","proposal":"p","rationale":"r",'
              '"category":"performance","severity":"medium","touches":["db.py"]}]}IDEAS_END')
            class R: exit_code = 0; refused = False
            return R()
    out = asyncio.run(ideas_mod.generate_ideas(ws, categories=None, runner=Stub()))
    assert out[0].title == "Add index"
    iid = out[0].id
    res = ideas_mod.import_ideas([iid])
    assert res["added"]
    from app.core.state import _read_state
    assert any(i.get("source") == "ideas" for i in _read_state()["items"])
```
- [ ] Implement `prompts/ideas.md` (input `categories`, `memory_excerpt`, `map_excerpt`; output `IDEAS_BEGIN{"ideas":[{title,proposal,rationale,category,severity,touches}]}IDEAS_END`). Implement `Idea` (pydantic, id `"idea-"+sha1(title+ts)[:8]`), `IdeaStore` (`<state>/ideas.json`, list/get/put), `generate_ideas(ws, *, categories, runner)` (render prompt with `read_map(ws)` excerpt + memory, run agent, parse `IDEAS_BEGIN` block, build Idea list, persist; never raise → `[]`), `import_ideas(ids)` (map selected Idea→proposal dict `{id,title,proposal,rationale:why,acceptance:"",touches,category,severity}` → `add_proposals_to_queue(props, source="ideas")`; set `imported=True`; return `{added:[...]}`).
- [ ] `ruff check .` + mypy app/ clean. Commit: `feat(epic4): Ideas generator + store + import`

### Task B2: Ideas API
**Files:** Create `backend/app/api/v1/ideas.py`; Modify `backend/app/main.py`; Test `backend/tests/contract/test_ideas_api.py`.
- [ ] **Test** (patch `active_workspace` + `generate_ideas`/`import_ideas`): `POST /api/v1/ideas/generate` → `{ok, ideas}`; `GET /api/v1/ideas` → list; `POST /api/v1/ideas/import {ids}` → `{ok, added}`.
- [ ] Implement the router (sync handlers + `asyncio.run` for generate, like goals API; comment sync requirement). `generate` builds a runner via `_build_runner(ws)`. Register in `main.py`.
- [ ] Full suite + `ruff check .` + mypy app/ clean. Commit: `feat(epic4): Ideas API`

---

## BATCH C — Insights backend

### Task C1: session store + ask + prompt
**Files:** Create `backend/app/services/insights.py`, `prompts/insights.md`; Test `backend/tests/integration/test_insights.py`.
- [ ] **Test** (stub runner writing an assistant answer JSONL; `_STATE_DIR_OVERRIDE`):
```python
import asyncio, pathlib, json
import app.core.state as state
from app.services import insights as ins
def test_ask_appends_turns(tmp_path, monkeypatch):
    sd = tmp_path / "st"; sd.mkdir(); monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)
    repo = tmp_path / "repo"; (repo / ".hephaestus" / "memory").mkdir(parents=True)
    monkeypatch.setattr("app.services.insights._run", lambda cmd, **kw: "")  # git log/status stubs
    ws = _make_ws(str(repo))
    class Stub:
        async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec, use_models=False):
            pathlib.Path(output_path).write_text(
                json.dumps({"type":"text","text":"It uses FastAPI in app/main.py"}) + "\n" +
                json.dumps({"type":"finish"}) + "\n")
            class R: exit_code = 0; refused = False
            return R()
    res = asyncio.run(ins.ask(ws, "What web framework?", session_id=None, runner=Stub()))
    assert "FastAPI" in res["answer"]
    sess = ins.InsightsStore().get(res["sessionId"])
    assert len(sess.turns) == 2 and sess.turns[0].role == "user"
```
- [ ] Implement `prompts/insights.md` (READ-ONLY investigator instruction per spec §3.2; vars: `question`, `history`, `codebase_map`, `memory_excerpt`, `git_log`). Implement `InsightsTurn`/`InsightsSession`/`InsightsStore` (`<state>/insights.json`), a `_next_insights_seq()` (mirror merge-NNNN), and `ask(ws, question, *, session_id, runner)`:
  - load/create session, append user turn;
  - dir `<state>/insights-NNNN`; render prompt with prior turns (cap ~10), `read_map(ws)`, memory excerpt, `git log -n 20` (via `_run`), question;
  - capture `git status --porcelain` before; run agent (`ws.agents.primary`, cwd=repo, output `insights-NNNN/output.insights.jsonl`); capture after — if grew, set `modifiedFiles` + log warning (no auto-clean);
  - parse final assistant text from the JSONL (concatenate `text` parts / last text before finish — reuse `events` helpers if available, else a small local parser);
  - append assistant turn (`iter_dir=insights-NNNN`), persist; return `{sessionId, iterDir, answer, modifiedFiles}`. Never raise (on agent failure → answer="(no response)").
- [ ] `ruff check .` + mypy app/ clean. Commit: `feat(epic4): Insights session store + read-only ask`

### Task C2: Insights API + SSE
**Files:** Create `backend/app/api/v1/insights.py`; Modify `backend/app/main.py`; Test `backend/tests/contract/test_insights_api.py`.
- [ ] **Test** (patch `ask`/`build_map`/`active_workspace`): `POST /api/v1/insights/ask {question}` → `{sessionId, iterDir, answer}`; `GET /api/v1/insights/sessions` + `/{id}`; `POST /api/v1/insights/rebuild-map` → `{ok, count}`. (SSE endpoint: a light test that it returns 200 text/event-stream for a known dir, or skip streaming assertion.)
- [ ] Implement the router: `ask` (sync + asyncio.run, `_build_runner`), `sessions` list/get, `rebuild-map` (asyncio.run `build_map`), and `GET /api/v1/insights/{iter_dir}/stream` — COPY `merge_job_stream` from `merge.py` but tail `<state>/{iter_dir}/output.insights.jsonl` and terminate when the file is stable ≥2s (no loop-status dependency) + 1800s cap + client disconnect. Register in `main.py`.
- [ ] Full suite + `ruff check .` + mypy app/ clean. Commit: `feat(epic4): Insights API + SSE stream`

---

## BATCH D — Frontend
### Task D1: types + client
- [ ] `types/api.ts`: `Idea` (`{id,title,proposal,rationale,category,severity,touches,imported}`), `InsightsTurn` (`{role,content,iterDir?}`), `InsightsSession` (`{id,title,turns,createdAt?,updatedAt?}`). `api/client.ts`: `generateIdeas(categories?)`, `listIdeas()`, `importIdeas(ids)`, `askInsights(question, sessionId?)`, `listInsightsSessions()`, `getInsightsSession(id)`, `rebuildMap()`. `vue-tsc` clean. Commit: `feat(epic4): frontend Insights/Ideas types + client`

### Task D2: IdeasPanel + InsightsChat
**Files:** Create `frontend/src/components/IdeasPanel.vue`, `frontend/src/components/InsightsChat.vue`; mount in views (ToolsView for Ideas; a new "Insights" tab/route for chat); Test their specs.
- [ ] **IdeasPanel.vue:** "Generate ideas" (+ optional category filter) → `generateIdeas` → list of idea cards (title + category/severity badges + proposal) with checkboxes + "Import selected" (`data-test="import-ideas"`) → `importIdeas(selectedIds)` → toast. Spec: mock client, assert generate renders cards + import calls `importIdeas`.
- [ ] **InsightsChat.vue:** transcript (user/assistant bubbles) + input + send. On send → `askInsights(q, sessionId)` returns `iterDir` → render `<LiveConsole :stream-url="'/api/v1/insights/'+iterDir+'/stream'" :iter-dir="null" :active="true" />` to stream the investigation, then show `answer`. "Rebuild project map" button → `rebuildMap`. Spec: mock client, assert sending a question calls `askInsights` and shows the answer.
- [ ] Add an "Insights" route/nav entry (mirror an existing view registration). `vitest` + `vue-tsc` + `build` clean. Commit: `feat(epic4): IdeasPanel + InsightsChat UI`

---

## BATCH E — Verify + final review + finish
- [ ] Full backend suite + `ruff check .` + mypy app/ clean; frontend vitest + vue-tsc + build clean.
- [ ] Final reviewer subagent over `git diff master..HEAD`: focus — agent runs never raise on bad LLM; Insights read-only (no commit; stray-edit detection not auto-clean); SSE terminates correctly (file-stable, not loop-status); stores idempotent; import_ideas idempotent; no secrets; sync-handler+asyncio.run safe. Apply fixes.

---

## Self-Review (applied)
- **Spec coverage:** §2→A1; §3→C1/C2; §4→B1/B2; §5 safety→never-raise + read-only + SSE-terminate in each task; §6 testing→every task TDD; UI→D1/D2.
- **Carried unknowns:** exact final-text extraction from JSONL (C1) — reuse `events` parsing if a helper exists, else a small local parser over `text` parts; the Insights SSE done-condition is file-stability (NOT `pm.status('loop')`), per Epic 1 merge-stream lesson.
- **Type consistency:** `build_map`/`read_map`/`generate_ideas`/`import_ideas`/`ask`/`InsightsStore`/`IdeaStore` names consistent across tasks; frontend `iterDir`/`category`/`severity` match backend aliases.
