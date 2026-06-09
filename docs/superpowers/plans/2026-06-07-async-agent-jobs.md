# Async Agent Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert three long-running synchronous agent endpoints (rebuild-map, ideas/generate, changelog) to an async background-job pattern that returns a `jobId` immediately and lets clients stream progress via SSE.

**Architecture:** A new `AgentJobStore` (persisted JSON in `<state>/agent-jobs.json`) tracks jobs with `running/done/failed` status. `start_agent_job(kind, work)` creates an `ajob-NNNN/output.jsonl` file, fires an `asyncio.create_task`, and returns the job immediately. A new `/api/v1/agent-jobs/{id}` router handles GET-job and SSE-stream, copying the proven `merge_job_stream` pattern.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, asyncio, pytest (pytest-asyncio), ruff, mypy --strict.

---

## Environment / Commands

All commands run from `backend/`:

```
cd backend
# Tests:      .venv/Scripts/python.exe -m pytest tests/<path> -v
# Lint:       .venv/Scripts/python.exe -m ruff check .
# Types:      .venv/Scripts/python.exe -m mypy --strict app/
```

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `backend/app/core/agent_jobs.py` | `AgentJob` model, `AgentJobStore`, `_next_seq`, `start_agent_job` |
| Create | `backend/tests/unit/test_agent_jobs.py` | Unit tests for core (store, seq, happy-path, failure) |
| Modify | `backend/app/services/codebase_map.py` | Add `output_path: Path | None = None` to `build_map` |
| Modify | `backend/app/services/ideas.py` | Add `output_path: Path | None = None` to `generate_ideas` |
| Modify | `backend/app/services/integrations/changelog.py` | Add `output_path: Path | None = None` to `generate_changelog` |
| Create | `backend/app/api/v1/agent_jobs.py` | GET /agent-jobs/{id}, GET /agent-jobs/{id}/stream |
| Modify | `backend/app/api/v1/insights.py` | `rebuild_map` → async, returns `{ok, jobId, kind}` |
| Modify | `backend/app/api/v1/ideas.py` | `generate_ideas_endpoint` → async, returns `{ok, jobId, kind}` |
| Modify | `backend/app/api/v1/integrations.py` | `generate_changelog_endpoint` → async, returns `{ok, jobId, kind}` |
| Modify | `backend/app/main.py` | Register `agent_jobs_router` |
| Create | `backend/tests/contract/test_agent_jobs_api.py` | Contract tests for new router |
| Modify | `backend/tests/contract/test_insights_api.py` | Update `test_rebuild_map_returns_count` to new `{jobId, kind}` shape |
| Modify | `backend/tests/contract/test_ideas_api.py` | Update generate tests to new `{jobId, kind}` shape |
| Modify | `backend/tests/contract/test_integrations_api.py` | Update changelog test (if any) to new `{jobId, kind}` shape |

---

## Task 1: `agent_jobs` core — model, store, background runner

**Files:**
- Create: `backend/app/core/agent_jobs.py`
- Create: `backend/tests/unit/test_agent_jobs.py`

### Step 1.1 — Write the failing unit tests first

- [ ] Create `backend/tests/unit/test_agent_jobs.py` with the following content:

```python
"""Unit tests for AgentJobStore + _next_seq + start_agent_job."""
from __future__ import annotations

import asyncio
import pathlib

import pytest

import app.core.state as state_mod


# ---------------------------------------------------------------------------
# Store round-trip
# ---------------------------------------------------------------------------


def test_store_roundtrip(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    from app.core.agent_jobs import AgentJob, AgentJobStore

    store = AgentJobStore()
    job = AgentJob(id="ajob-0001", kind="map")
    store.put(job)

    fetched = store.get("ajob-0001")
    assert fetched is not None
    assert fetched.kind == "map"
    assert fetched.status == "running"

    job.status = "done"
    job.result = {"count": 5}
    store.put(job)

    updated = store.get("ajob-0001")
    assert updated is not None
    assert updated.status == "done"
    assert updated.result == {"count": 5}
    assert any(j.id == "ajob-0001" for j in store.list())


def test_store_missing_returns_none(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    from app.core.agent_jobs import AgentJobStore

    assert AgentJobStore().get("ajob-9999") is None


def test_store_list_empty(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    from app.core.agent_jobs import AgentJobStore

    assert AgentJobStore().list() == []


# ---------------------------------------------------------------------------
# _next_seq monotonic
# ---------------------------------------------------------------------------


def test_next_seq_monotonic(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    (tmp_path / "ajob-0001").mkdir()
    (tmp_path / "ajob-0007").mkdir()

    from app.core.agent_jobs import _next_seq

    assert _next_seq() == 8


def test_next_seq_empty(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    from app.core.agent_jobs import _next_seq

    assert _next_seq() == 1


# ---------------------------------------------------------------------------
# start_agent_job — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_agent_job_happy(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    from app.core.agent_jobs import AgentJobStore, start_agent_job

    async def work(output_path: pathlib.Path) -> dict:
        output_path.write_text('{"type":"text","text":"hi"}\n', encoding="utf-8")
        return {"x": 1}

    job = start_agent_job("map", work)
    assert job.status == "running"
    assert job.id.startswith("ajob-")

    # Drain all background tasks so _run() completes
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    store = AgentJobStore()
    done = store.get(job.id)
    assert done is not None
    assert done.status == "done"
    assert done.result == {"x": 1}

    # output.jsonl must exist (created by start_agent_job before the task runs)
    output_jsonl = tmp_path / job.output_dir / "output.jsonl"
    assert output_jsonl.exists()


# ---------------------------------------------------------------------------
# start_agent_job — failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_agent_job_failure(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    from app.core.agent_jobs import AgentJobStore, start_agent_job

    async def bad_work(output_path: pathlib.Path) -> dict:
        raise ValueError("agent exploded")

    job = start_agent_job("ideas", bad_work)
    assert job.status == "running"

    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    store = AgentJobStore()
    failed = store.get(job.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error is not None
    assert "agent exploded" in failed.error
    # Must NOT re-raise — no exception from gather above
```

- [ ] **Run the failing tests** to verify they fail with `ModuleNotFoundError`:

```
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_agent_jobs.py -v 2>&1 | head -30
```

Expected: `ERROR collecting ... ModuleNotFoundError: No module named 'app.core.agent_jobs'`

### Step 1.2 — Implement `backend/app/core/agent_jobs.py`

- [ ] Create `backend/app/core/agent_jobs.py` with the following content:

```python
"""AgentJobStore + start_agent_job — async background runner for agent tasks.

Pattern mirrors MergeJobStore / _next_merge_seq in app.core.merge_job.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.state import _atomic_write, _state_dir, _StateLock

_REGISTRY = "agent-jobs.json"
_MAX_KEEP = 50


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class AgentJob(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    kind: str
    status: str = "running"
    result: dict[str, Any] | None = None
    error: str | None = None
    output_dir: str = Field("", alias="outputDir")
    created_at: str | None = Field(None, alias="createdAt")
    updated_at: str | None = Field(None, alias="updatedAt")


# ---------------------------------------------------------------------------
# Sequencing
# ---------------------------------------------------------------------------


def _next_seq() -> int:
    """Return the next monotonically-increasing agent-job sequence number."""
    sd = _state_dir()
    nums: list[int] = []
    for p in sd.glob("ajob-*"):
        part = p.name.split("-", 1)[1] if "-" in p.name else ""
        if p.is_dir() and part.isdigit():
            nums.append(int(part))
    return (max(nums) + 1) if nums else 1


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class AgentJobStore:
    """Persist AgentJob records as a rolling JSON registry in the state dir."""

    def _path(self) -> pathlib.Path:
        return _state_dir() / _REGISTRY

    def list(self) -> list[AgentJob]:
        p = self._path()
        if not p.exists():
            return []
        raw = json.loads(p.read_text(encoding="utf-8") or '{"jobs": []}')
        return [AgentJob.model_validate(j) for j in raw.get("jobs", [])]

    def get(self, job_id: str) -> AgentJob | None:
        return next((j for j in self.list() if j.id == job_id), None)

    def put(self, job: AgentJob) -> None:
        with _StateLock():
            jobs = [j for j in self.list() if j.id != job.id]
            jobs.append(job)
            jobs = jobs[-_MAX_KEEP:]
            payload = json.dumps(
                {"jobs": [j.model_dump(by_alias=True) for j in jobs]},
                indent=2,
                ensure_ascii=False,
            )
            self._path().parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(self._path(), payload)


# ---------------------------------------------------------------------------
# Background runner
# ---------------------------------------------------------------------------


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def start_agent_job(
    kind: str,
    work: Callable[[pathlib.Path], Awaitable[dict[str, Any]]],
) -> AgentJob:
    """Create a background agent job, fire-and-forget the coroutine, return immediately.

    ``work`` receives the path to ``output.jsonl`` (already created, empty) and must
    return a result dict on success or raise on failure.
    """
    sd = _state_dir()
    seq = _next_seq()
    output_dir = f"ajob-{seq:04d}"
    job_dir = sd / output_dir
    job_dir.mkdir(parents=True, exist_ok=True)
    output_path = job_dir / "output.jsonl"
    output_path.write_text("", encoding="utf-8")

    store = AgentJobStore()
    job = AgentJob(
        id=f"ajob-{seq:04d}",
        kind=kind,
        status="running",
        output_dir=output_dir,
        created_at=_now(),
        updated_at=_now(),
    )
    store.put(job)

    async def _run() -> None:
        try:
            res = await work(output_path)
            job.status = "done"
            job.result = res
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error = str(exc)
        finally:
            job.updated_at = _now()
            AgentJobStore().put(job)

    asyncio.create_task(_run())
    return job
```

### Step 1.3 — Run tests and verify they pass

- [ ] **Run the unit tests**:

```
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_agent_jobs.py -v
```

Expected: All 7 tests PASS.

### Step 1.4 — Lint and type-check

- [ ] **Run ruff** (must be zero errors):

```
cd backend && .venv/Scripts/python.exe -m ruff check .
```

- [ ] **Run mypy** on `app/` only:

```
cd backend && .venv/Scripts/python.exe -m mypy --strict app/
```

Both must pass with 0 errors before committing.

### Step 1.5 — Commit

- [ ] **Commit**:

```bash
git add backend/app/core/agent_jobs.py backend/tests/unit/test_agent_jobs.py
git commit -m "feat: agent_jobs core (background runner + store + SSE-able output)"
```

---

## Task 2: Add `output_path` to the 3 agent service functions

**Files:**
- Modify: `backend/app/services/codebase_map.py` — `build_map`
- Modify: `backend/app/services/ideas.py` — `generate_ideas`
- Modify: `backend/app/services/integrations/changelog.py` — `generate_changelog` / `_generate`

### Step 2.1 — Write failing tests for each modified service

**Why tests first:** The existing tests pass `runner=None` or a fake runner and don't pass `output_path`. New tests must assert that when `output_path` is supplied, it receives the agent output. The existing tests must stay green (no `output_path` → same behavior as before).

- [ ] Add to `backend/tests/integration/test_codebase_map.py` (or a new file `backend/tests/unit/test_output_path.py` — prefer a new isolated file to avoid touching integration test state):

Create `backend/tests/unit/test_output_path.py`:

```python
"""Tests: optional output_path parameter for build_map, generate_ideas, generate_changelog."""
from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

import pytest

import app.core.state as state_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_runner(output_text: str = ""):
    """Returns a SimpleNamespace with an async run() that writes output_text to output_path."""

    class _Runner:
        async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec, use_models=True):
            pathlib.Path(output_path).write_text(output_text, encoding="utf-8")
            return SimpleNamespace(exit_code=0, refused=False,
                                   output_path=output_path, agent_label="fake")

    return _Runner()


def _make_ws(tmp_path: pathlib.Path):
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / ".hephaestus" / "state").mkdir(parents=True, exist_ok=True)
    (repo / ".hephaestus" / "memory").mkdir(parents=True, exist_ok=True)
    (repo / ".git").mkdir(exist_ok=True)
    agents = SimpleNamespace(
        primary=SimpleNamespace(provider="p", model="m", agent="primary"),
        planner=None,
    )
    return SimpleNamespace(
        id="ws-test",
        repo_path=str(repo),
        agents=agents,
        engine="opencode",
        engine_env={},
        engine_profiles=[],
    )


# ---------------------------------------------------------------------------
# build_map output_path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_map_with_output_path(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    map_block = 'MAP_BEGIN{"map":{"a.py":"entry"}}MAP_END'
    map_json = json.dumps({"type": "text", "text": map_block})
    runner = _fake_runner(map_json + "\n")

    custom_output = tmp_path / "custom_map.jsonl"

    from app.services.codebase_map import build_map

    ws = _make_ws(tmp_path)
    result = await build_map(ws, runner=runner, output_path=custom_output)

    assert isinstance(result, dict)
    # The custom output path must exist (runner wrote to it)
    assert custom_output.exists()


@pytest.mark.asyncio
async def test_build_map_without_output_path_still_works(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backward-compat: no output_path → uses the default internal path."""
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    runner = _fake_runner("")
    from app.services.codebase_map import build_map

    ws = _make_ws(tmp_path)
    result = await build_map(ws, runner=runner)
    # Returns {} on empty output — that's fine; just must not raise
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# generate_ideas output_path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_ideas_with_output_path(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    idea_block = 'IDEAS_BEGIN{"ideas":[{"title":"T","proposal":"p","rationale":"r","category":"quality","severity":"low","touches":[]}]}IDEAS_END'
    idea_json = json.dumps({"type": "text", "text": idea_block})
    runner = _fake_runner(idea_json + "\n")

    custom_output = tmp_path / "custom_ideas.jsonl"

    from app.services.ideas import generate_ideas

    ws = _make_ws(tmp_path)
    # Stub project_memory and codebase_map to avoid FS side-effects
    monkeypatch.setattr("app.services.ideas.project_memory.read_doc", lambda ws, k: "")
    monkeypatch.setattr("app.services.ideas.codebase_map.read_map", lambda ws: {})
    monkeypatch.setattr(
        "app.services.ideas.PromptManager.render_prompt",
        lambda self, name, ctx: "prompt text",
    )

    result = await generate_ideas(ws, categories=None, runner=runner, output_path=custom_output)

    assert isinstance(result, list)
    assert custom_output.exists()


@pytest.mark.asyncio
async def test_generate_ideas_without_output_path_still_works(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    runner = _fake_runner("")
    monkeypatch.setattr("app.services.ideas.project_memory.read_doc", lambda ws, k: "")
    monkeypatch.setattr("app.services.ideas.codebase_map.read_map", lambda ws: {})
    monkeypatch.setattr(
        "app.services.ideas.PromptManager.render_prompt",
        lambda self, name, ctx: "prompt text",
    )

    from app.services.ideas import generate_ideas

    ws = _make_ws(tmp_path)
    result = await generate_ideas(ws, categories=None, runner=runner)
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# generate_changelog output_path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_changelog_with_output_path(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    cl_block = 'CHANGELOG_BEGIN{"markdown":"## v1","versionSuggestion":"minor"}CHANGELOG_END'
    cl_json = json.dumps({"type": "text", "text": cl_block})
    runner = _fake_runner(cl_json + "\n")

    custom_output = tmp_path / "custom_cl.jsonl"

    from app.services.integrations.changelog import generate_changelog

    ws = SimpleNamespace(
        repo_path=str(tmp_path / "repo"),
        agents=SimpleNamespace(
            primary=SimpleNamespace(provider="p", model="m", agent="primary"),
            planner=None,
        ),
    )
    (tmp_path / "repo").mkdir(exist_ok=True)

    # Stub git log + prompt
    monkeypatch.setattr("app.services.integrations.changelog._run",
                        lambda cmd, cwd, default="": "abc123 fix (dev)")
    monkeypatch.setattr(
        "app.services.integrations.changelog.PromptManager.render_prompt",
        lambda self, name, ctx: "prompt text",
    )

    result = await generate_changelog(ws, since=None, runner=runner, output_path=custom_output)

    assert isinstance(result, dict)
    assert "markdown" in result
    assert custom_output.exists()


@pytest.mark.asyncio
async def test_generate_changelog_without_output_path_still_works(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    runner = _fake_runner("")
    (tmp_path / "repo").mkdir(exist_ok=True)

    monkeypatch.setattr("app.services.integrations.changelog._run",
                        lambda cmd, cwd, default="": "abc123 fix (dev)")
    monkeypatch.setattr(
        "app.services.integrations.changelog.PromptManager.render_prompt",
        lambda self, name, ctx: "prompt text",
    )

    from app.services.integrations.changelog import generate_changelog

    ws = SimpleNamespace(
        repo_path=str(tmp_path / "repo"),
        agents=SimpleNamespace(
            primary=SimpleNamespace(provider="p", model="m", agent="primary"),
            planner=None,
        ),
    )

    result = await generate_changelog(ws, since=None, runner=runner)
    assert isinstance(result, dict)
    assert "markdown" in result
```

- [ ] **Run the failing tests** to confirm they fail before the implementation:

```
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_output_path.py -v 2>&1 | head -40
```

Expected: Tests fail with `TypeError: build_map() got an unexpected keyword argument 'output_path'` (or similar).

### Step 2.2 — Modify `build_map` in `backend/app/services/codebase_map.py`

- [ ] Edit `codebase_map.py` — change the signature and the `runner.run()` call:

Find this block:

```python
async def build_map(
    ws: RepoProfile,
    *,
    runner: Any,
    max_files: int = 400,
) -> dict[str, str]:
```

Replace with:

```python
async def build_map(
    ws: RepoProfile,
    *,
    runner: Any,
    max_files: int = 400,
    output_path: pathlib.Path | None = None,
) -> dict[str, str]:
```

Then find inside `build_map`:

```python
        output_path = state_dir / "codebase-map.output.jsonl"

        ref = ws.agents.primary
        result = await runner.run(
            ref,
            prompt_file=prompt_file,
            cwd=str(repo),
            output_path=output_path,
            timeout_sec=300,
            use_models=False,
        )
        if result.refused:
            log.warning("build_map: agent refused")
            return {}

        from app.core.events import extract_assistant_text

        final_text = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
```

Replace with:

```python
        _default_output = state_dir / "codebase-map.output.jsonl"
        effective_output = output_path if output_path is not None else _default_output

        ref = ws.agents.primary
        result = await runner.run(
            ref,
            prompt_file=prompt_file,
            cwd=str(repo),
            output_path=effective_output,
            timeout_sec=300,
            use_models=False,
        )
        if result.refused:
            log.warning("build_map: agent refused")
            return {}

        from app.core.events import extract_assistant_text

        final_text = effective_output.read_text(encoding="utf-8") if effective_output.exists() else ""
```

Also add `import pathlib` at the top if not already present (it is already imported via `import pathlib` inside the function — move it to the top-level):

Find:
```python
    try:
        repo = pathlib.Path(ws.repo_path)
```

The function already does `import pathlib` locally inside. Since we need `pathlib.Path` in the signature, ensure `import pathlib` is at the module top-level. Check: the existing file uses `import pathlib` inside the `try` block. Move it to the module level imports section:

Add `import pathlib` to the existing imports at the top (after `import time`). Then remove the local `import pathlib` inside the function body.

### Step 2.3 — Modify `generate_ideas` in `backend/app/services/ideas.py`

- [ ] Edit `ideas.py` — change the signature and the `runner.run()` call:

Find:
```python
async def generate_ideas(
    ws: RepoProfile,
    *,
    categories: list[str] | None,
    runner: Any,
) -> list[Idea]:
```

Replace with:
```python
async def generate_ideas(
    ws: RepoProfile,
    *,
    categories: list[str] | None,
    runner: Any,
    output_path: pathlib.Path | None = None,
) -> list[Idea]:
```

Inside `generate_ideas`, find:
```python
        output_path = ideas_dir / "ideas.output.jsonl"

        ref = ws.agents.primary
        result = await runner.run(
            ref,
            prompt_file=prompt_file,
            cwd=str(repo),
            output_path=output_path,
            timeout_sec=300,
            use_models=False,
        )
        if result.refused:
            log.warning("generate_ideas: agent refused")
            return []

        from app.core.events import extract_assistant_text

        final_text = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
```

Replace with:
```python
        _default_output = ideas_dir / "ideas.output.jsonl"
        effective_output = output_path if output_path is not None else _default_output

        ref = ws.agents.primary
        result = await runner.run(
            ref,
            prompt_file=prompt_file,
            cwd=str(repo),
            output_path=effective_output,
            timeout_sec=300,
            use_models=False,
        )
        if result.refused:
            log.warning("generate_ideas: agent refused")
            return []

        from app.core.events import extract_assistant_text

        final_text = effective_output.read_text(encoding="utf-8") if effective_output.exists() else ""
```

### Step 2.4 — Modify `generate_changelog` in `backend/app/services/integrations/changelog.py`

- [ ] Edit `changelog.py` — the public function delegates to `_generate`. Add the parameter to both.

Find:
```python
async def generate_changelog(
    ws: RepoProfile,
    *,
    since: str | None,
    runner: Any,
) -> dict[str, Any]:
```

Replace with:
```python
async def generate_changelog(
    ws: RepoProfile,
    *,
    since: str | None,
    runner: Any,
    output_path: pathlib.Path | None = None,
) -> dict[str, Any]:
```

Find:
```python
    try:
        return await _generate(ws, since=since, runner=runner)
```

Replace with:
```python
    try:
        return await _generate(ws, since=since, runner=runner, output_path=output_path)
```

Find:
```python
async def _generate(
    ws: RepoProfile,
    *,
    since: str | None,
    runner: Any,
) -> dict[str, Any]:
```

Replace with:
```python
async def _generate(
    ws: RepoProfile,
    *,
    since: str | None,
    runner: Any,
    output_path: pathlib.Path | None = None,
) -> dict[str, Any]:
```

Inside `_generate`, find:
```python
    # Build paths under <repo>/.hephaestus/state/
    repo_path = pathlib.Path(ws.repo_path)
    hephaestus_state = repo_path / ".hephaestus" / "state"
    hephaestus_state.mkdir(parents=True, exist_ok=True)
    output_path = hephaestus_state / "changelog.output.jsonl"
```

Replace with:
```python
    # Build paths under <repo>/.hephaestus/state/
    repo_path = pathlib.Path(ws.repo_path)
    hephaestus_state = repo_path / ".hephaestus" / "state"
    hephaestus_state.mkdir(parents=True, exist_ok=True)
    _default_output = hephaestus_state / "changelog.output.jsonl"
    effective_output = output_path if output_path is not None else _default_output
```

Then find every subsequent use of `output_path` inside `_generate` (there are 2: the `runner.run()` call and the `output_path.read_text()` call) and replace them with `effective_output`:

```python
        result = await runner.run(
            ref,
            prompt_file=prompt_file,
            cwd=ws.repo_path,
            output_path=effective_output,   # was: output_path
            timeout_sec=120,
        )
```

And:
```python
        text = effective_output.read_text(encoding="utf-8", errors="replace")  # was: output_path
```

### Step 2.5 — Run all tests to confirm existing tests still green and new tests pass

- [ ] **Run the new output_path tests**:

```
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_output_path.py -v
```

Expected: All 6 tests PASS.

- [ ] **Run the full unit + existing contract suite** to confirm nothing regressed:

```
cd backend && .venv/Scripts/python.exe -m pytest tests/unit/ tests/contract/ -v 2>&1 | tail -30
```

Expected: All previously-passing tests still PASS (including existing `test_ideas_api.py`, `test_insights_api.py`, `test_integrations_api.py`).

### Step 2.6 — Lint and type-check

- [ ] **Run ruff**:

```
cd backend && .venv/Scripts/python.exe -m ruff check .
```

- [ ] **Run mypy**:

```
cd backend && .venv/Scripts/python.exe -m mypy --strict app/
```

Both must be clean.

### Step 2.7 — Commit

- [ ] **Commit**:

```bash
git add backend/app/services/codebase_map.py \
        backend/app/services/ideas.py \
        backend/app/services/integrations/changelog.py \
        backend/tests/unit/test_output_path.py
git commit -m "feat: optional output_path on build_map/generate_ideas/generate_changelog"
```

---

## Task 3: Agent-jobs API + convert the 3 endpoints

**Files:**
- Create: `backend/app/api/v1/agent_jobs.py`
- Modify: `backend/app/api/v1/insights.py`
- Modify: `backend/app/api/v1/ideas.py`
- Modify: `backend/app/api/v1/integrations.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/contract/test_agent_jobs_api.py`
- Modify: `backend/tests/contract/test_insights_api.py` (update `test_rebuild_map_*` tests)
- Modify: `backend/tests/contract/test_ideas_api.py` (update `test_generate_ideas_*` tests)
- Modify: `backend/tests/contract/test_integrations_api.py` (update changelog test)

### Step 3.1 — Write contract tests FIRST (they will fail)

- [ ] Create `backend/tests/contract/test_agent_jobs_api.py`:

```python
"""Contract tests for the agent-jobs router (/api/v1/agent-jobs/*)."""
from __future__ import annotations

import pathlib

import app.core.state as state_mod

_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


# ---------------------------------------------------------------------------
# GET /api/v1/agent-jobs/{id}
# ---------------------------------------------------------------------------


def test_get_agent_job_returns_job(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    from app.core.agent_jobs import AgentJob, AgentJobStore

    store = AgentJobStore()
    job = AgentJob(
        id="ajob-0001",
        kind="map",
        status="done",
        result={"count": 3},
        output_dir="ajob-0001",
    )
    store.put(job)

    r = client.get("/api/v1/agent-jobs/ajob-0001")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["id"] == "ajob-0001"
    assert data["kind"] == "map"
    assert data["status"] == "done"


def test_get_agent_job_not_found(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    r = client.get("/api/v1/agent-jobs/ajob-9999")
    assert r.status_code == 404
    assert r.json()["ok"] is False


def test_get_agent_job_invalid_id(client, tmp_path, monkeypatch):
    """job_id that doesn't match ^ajob-\\d+$ → 400."""
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    r = client.get("/api/v1/agent-jobs/../../etc")
    assert r.status_code in (400, 404)


# ---------------------------------------------------------------------------
# POST /api/v1/insights/rebuild-map → now returns jobId
# ---------------------------------------------------------------------------


def _make_fake_ws(tmp_path: pathlib.Path):
    import types

    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    agents = types.SimpleNamespace(
        primary=types.SimpleNamespace(provider="p", model="m", agent="primary"),
        planner=None,
    )
    return types.SimpleNamespace(
        id="ws-test",
        name="test",
        repo_path=str(repo),
        base_branch="main",
        remote="origin",
        branch_prefix="auto",
        agents=agents,
        engine="opencode",
        engine_env={},
        engine_profiles=[],
        memory_dir=".hephaestus/memory",
        verify_timeout_sec=120,
    )


def test_rebuild_map_returns_job_id(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    import app.api.v1.insights as ins_api
    from app.core.agent_jobs import AgentJob

    fake_ws = _make_fake_ws(tmp_path)
    monkeypatch.setattr(ins_api, "active_workspace", lambda: fake_ws)

    fake_job = AgentJob(id="ajob-0001", kind="map", output_dir="ajob-0001")

    def _fake_start_agent_job(kind, work):
        return fake_job

    monkeypatch.setattr(ins_api, "start_agent_job", _fake_start_agent_job)

    r = client.post("/api/v1/insights/rebuild-map", json={}, headers=_CSRF)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["jobId"] == "ajob-0001"
    assert data["kind"] == "map"
    # Must NOT have old "count" key
    assert "count" not in data


def test_rebuild_map_no_workspace_409(client, monkeypatch):
    import app.api.v1.insights as ins_api

    def _boom():
        raise ins_api.NoActiveWorkspace()

    monkeypatch.setattr(ins_api, "active_workspace", _boom)
    r = client.post("/api/v1/insights/rebuild-map", json={}, headers=_CSRF)
    assert r.status_code == 409
    assert r.json()["ok"] is False


# ---------------------------------------------------------------------------
# POST /api/v1/ideas/generate → now returns jobId
# ---------------------------------------------------------------------------


def test_generate_ideas_returns_job_id(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    import app.api.v1.ideas as ideas_api
    from app.core.agent_jobs import AgentJob

    fake_ws = _make_fake_ws(tmp_path)
    monkeypatch.setattr(ideas_api, "active_workspace", lambda: fake_ws)

    fake_job = AgentJob(id="ajob-0002", kind="ideas", output_dir="ajob-0002")

    def _fake_start_agent_job(kind, work):
        return fake_job

    monkeypatch.setattr(ideas_api, "start_agent_job", _fake_start_agent_job)

    r = client.post(
        "/api/v1/ideas/generate",
        json={"categories": ["quality"]},
        headers=_CSRF,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["jobId"] == "ajob-0002"
    assert data["kind"] == "ideas"
    # Must NOT have old "ideas" key
    assert "ideas" not in data


def test_generate_ideas_no_workspace_409(client, monkeypatch):
    import app.api.v1.ideas as ideas_api

    def _boom():
        raise ideas_api.NoActiveWorkspace()

    monkeypatch.setattr(ideas_api, "active_workspace", _boom)
    r = client.post("/api/v1/ideas/generate", json={}, headers=_CSRF)
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# POST /api/v1/integrations/changelog → now returns jobId
# ---------------------------------------------------------------------------


def test_generate_changelog_returns_job_id(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    import app.api.v1.integrations as int_api
    from app.core.agent_jobs import AgentJob

    fake_ws = _make_fake_ws(tmp_path)
    monkeypatch.setattr(int_api, "active_workspace", lambda: fake_ws)

    fake_job = AgentJob(id="ajob-0003", kind="changelog", output_dir="ajob-0003")

    def _fake_start_agent_job(kind, work):
        return fake_job

    monkeypatch.setattr(int_api, "start_agent_job", _fake_start_agent_job)

    r = client.post(
        "/api/v1/integrations/changelog",
        json={"since": "v1.0"},
        headers=_CSRF,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["jobId"] == "ajob-0003"
    assert data["kind"] == "changelog"
    # Must NOT have old "markdown" key
    assert "markdown" not in data


def test_generate_changelog_no_workspace_409(client, monkeypatch):
    import app.api.v1.integrations as int_api

    def _boom():
        raise int_api.NoActiveWorkspace()

    monkeypatch.setattr(int_api, "active_workspace", _boom)
    r = client.post(
        "/api/v1/integrations/changelog", json={}, headers=_CSRF
    )
    assert r.status_code == 409
```

- [ ] **Run the failing contract tests** to verify they fail:

```
cd backend && .venv/Scripts/python.exe -m pytest tests/contract/test_agent_jobs_api.py -v 2>&1 | head -50
```

Expected: Most tests fail with `404` (router not registered) or import errors.

### Step 3.2 — Update the OLD contract tests to the NEW shape

The existing tests `test_rebuild_map_returns_count`, `test_generate_ideas_returns_ok_and_ideas`, and `test_generate_ideas_no_categories` now assert the OLD sync shape. They must be updated to the new `{jobId, kind}` shape. The changelog endpoint had no existing test for the generate call in `test_integrations_api.py` that asserts the sync shape — confirm before editing.

- [ ] **Update `test_insights_api.py`** — find `test_rebuild_map_returns_count` and replace it:

```python
def test_rebuild_map_returns_job_id(client, tmp_path, monkeypatch):
    """rebuild-map now returns {ok, jobId, kind} instead of {ok, count}."""
    import app.api.v1.insights as ins_api
    import app.core.state as state_mod
    from app.core.agent_jobs import AgentJob

    sd = tmp_path / "st7"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    fake_ws = _make_fake_ws(tmp_path)
    monkeypatch.setattr(ins_api, "active_workspace", lambda: fake_ws)

    fake_job = AgentJob(id="ajob-0001", kind="map", output_dir="ajob-0001")

    def _fake_start(kind, work):
        return fake_job

    monkeypatch.setattr(ins_api, "start_agent_job", _fake_start)

    r = client.post("/api/v1/insights/rebuild-map", json={}, headers=_CSRF)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["jobId"] == "ajob-0001"
    assert data["kind"] == "map"
    assert "count" not in data
```

Also update `test_rebuild_map_no_workspace_returns_409` — no shape change needed there, just keep it as-is (it already tests a 409).

- [ ] **Update `test_ideas_api.py`** — replace `test_generate_ideas_returns_ok_and_ideas` and `test_generate_ideas_no_categories`:

```python
def test_generate_ideas_returns_job_id(client, tmp_path, monkeypatch):
    """generate now returns {ok, jobId, kind} instead of {ok, ideas:[...]}."""
    import app.api.v1.ideas as ideas_api
    import app.core.state as state_mod
    from app.core.agent_jobs import AgentJob

    sd = tmp_path / "st"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    fake_ws = _make_fake_ws(tmp_path)
    monkeypatch.setattr(ideas_api, "active_workspace", lambda: fake_ws)

    fake_job = AgentJob(id="ajob-0001", kind="ideas", output_dir="ajob-0001")

    def _fake_start(kind, work):
        return fake_job

    monkeypatch.setattr(ideas_api, "start_agent_job", _fake_start)

    r = client.post(
        "/api/v1/ideas/generate",
        json={"categories": ["performance"]},
        headers=_CSRF,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["jobId"] == "ajob-0001"
    assert data["kind"] == "ideas"
    assert "ideas" not in data


def test_generate_ideas_no_categories_returns_job_id(client, tmp_path, monkeypatch):
    import app.api.v1.ideas as ideas_api
    import app.core.state as state_mod
    from app.core.agent_jobs import AgentJob

    sd = tmp_path / "st2"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    fake_ws = _make_fake_ws(tmp_path)
    monkeypatch.setattr(ideas_api, "active_workspace", lambda: fake_ws)

    fake_job = AgentJob(id="ajob-0002", kind="ideas", output_dir="ajob-0002")

    def _fake_start(kind, work):
        return fake_job

    monkeypatch.setattr(ideas_api, "start_agent_job", _fake_start)

    r = client.post("/api/v1/ideas/generate", json={}, headers=_CSRF)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["jobId"] == "ajob-0002"
```

### Step 3.3 — Create `backend/app/api/v1/agent_jobs.py`

- [ ] Create `backend/app/api/v1/agent_jobs.py`:

```python
"""Agent-jobs router — async progress polling + SSE for map/ideas/changelog jobs.

GET /api/v1/agent-jobs/{job_id}         — fetch AgentJob by id
GET /api/v1/agent-jobs/{job_id}/stream  — SSE tail of output.jsonl (mirrors merge_job_stream)
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.agent_jobs import AgentJobStore
from app.core.state import _state_dir

router = APIRouter()

_JOB_ID_RE = re.compile(r"^ajob-\d+$")
_TERMINAL = {"done", "failed"}


@router.get("/api/v1/agent-jobs/{job_id}", response_model=None)
def get_agent_job(job_id: str) -> dict[str, object] | JSONResponse:
    if not _JOB_ID_RE.match(job_id):
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid job_id"})
    job = AgentJobStore().get(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "job not found"})
    return {"ok": True, **job.model_dump(by_alias=True)}


@router.get("/api/v1/agent-jobs/{job_id}/stream")
async def agent_job_stream(job_id: str, request: Request) -> StreamingResponse:
    if not _JOB_ID_RE.match(job_id):
        return StreamingResponse(
            _error_stream("invalid job_id — must match ajob-NNNN"),
            media_type="text/event-stream",
            status_code=400,
        )

    from app.core.events import _summarize_event

    job_record = AgentJobStore().get(job_id)
    if job_record is None:
        return StreamingResponse(
            _error_stream("job not found"),
            media_type="text/event-stream",
            status_code=404,
        )

    jp = _state_dir() / job_record.output_dir / "output.jsonl"

    async def gen() -> AsyncIterator[str]:
        idx = 0
        offset = 0
        buf = b""
        idle = 0.0
        started = time.monotonic()
        yield ": connected\n\n"
        while True:
            if await request.is_disconnected() or (time.monotonic() - started) > 1800:
                break
            grew = False
            if jp.exists() and jp.stat().st_size > offset:
                with jp.open("rb") as f:
                    f.seek(offset)
                    chunk = f.read()
                offset += len(chunk)
                buf += chunk
                parts = buf.split(b"\n")
                buf = parts.pop()
                for raw in parts:
                    line = raw.strip()
                    idx += 1
                    if not line:
                        continue
                    try:
                        obj = json.loads(line.decode("utf-8", "replace"))
                    except ValueError:
                        continue
                    yield f"data: {json.dumps(_summarize_event(obj, idx=idx - 1), ensure_ascii=False)}\n\n"
                grew = True
            idle = 0.0 if grew else idle + 0.5
            current_job = AgentJobStore().get(job_id)
            if idle >= 2.0 and (current_job is None or current_job.status in _TERMINAL):
                yield "event: done\ndata: {}\n\n"
                break
            if not grew:
                yield ": keepalive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _error_stream(msg: str) -> AsyncIterator[str]:
    yield f"data: {json.dumps({'error': msg})}\n\n"
```

### Step 3.4 — Convert `insights.py` `rebuild_map` to async

- [ ] **Edit `backend/app/api/v1/insights.py`** — add new imports and convert the endpoint:

Add to the imports section:
```python
from app.core.agent_jobs import start_agent_job
```

Replace the `rebuild_map` handler entirely:

```python
@router.post("/api/v1/insights/rebuild-map", response_model=None)
async def rebuild_map() -> dict[str, Any] | JSONResponse:
    """Start a background map-rebuild job and return jobId immediately."""
    try:
        ws = active_workspace()
    except NoActiveWorkspace as exc:
        return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})

    runner = _build_runner(ws)

    async def _map_work(output_path: Any) -> dict[str, Any]:
        import pathlib as _pathlib
        m = await build_map(ws, runner=runner, output_path=_pathlib.Path(output_path))
        return {"count": len(m)}

    job = start_agent_job("map", _map_work)
    return {"ok": True, "jobId": job.id, "kind": "map"}
```

Also remove the old `import asyncio` usage inside `rebuild_map` if needed (the `asyncio` import at the top is still needed for other things in the file — `insights_ask` uses it — so keep it).

### Step 3.5 — Convert `ideas.py` `generate_ideas_endpoint` to async

- [ ] **Edit `backend/app/api/v1/ideas.py`** — add new imports and convert the endpoint:

Add to the imports section:
```python
from app.core.agent_jobs import start_agent_job
```

Replace the `generate_ideas_endpoint` handler entirely:

```python
@router.post("/api/v1/ideas/generate", response_model=None)
async def generate_ideas_endpoint(body: _GenerateRequest) -> dict[str, Any] | JSONResponse:
    """Start a background ideas-generation job and return jobId immediately."""
    try:
        ws = active_workspace()
    except NoActiveWorkspace as exc:
        return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})

    runner = _build_runner(ws)

    async def _ideas_work(output_path: Any) -> dict[str, Any]:
        import pathlib as _pathlib
        ideas = await generate_ideas(
            ws, categories=body.categories, runner=runner,
            output_path=_pathlib.Path(output_path),
        )
        return {"ideas": [i.model_dump(by_alias=True) for i in ideas]}

    job = start_agent_job("ideas", _ideas_work)
    return {"ok": True, "jobId": job.id, "kind": "ideas"}
```

### Step 3.6 — Convert `integrations.py` `generate_changelog_endpoint` to async

- [ ] **Edit `backend/app/api/v1/integrations.py`** — add new imports and convert the endpoint.

Add to the imports section (alongside existing imports):
```python
from app.core.agent_jobs import start_agent_job
```

Replace the `generate_changelog_endpoint` handler entirely:

```python
@router.post("/api/v1/integrations/changelog", response_model=None)
async def generate_changelog_endpoint(body: _ChangelogBody) -> dict[str, Any] | JSONResponse:
    """Start a background changelog-generation job and return jobId immediately."""
    try:
        ws = active_workspace()
    except NoActiveWorkspace as exc:
        return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})

    from app.core.scan import _build_runner
    from app.services.integrations.changelog import generate_changelog

    runner = _build_runner(ws)

    async def _changelog_work(output_path: Any) -> dict[str, Any]:
        import pathlib as _pathlib
        return await generate_changelog(
            ws, since=body.since, runner=runner,
            output_path=_pathlib.Path(output_path),
        )

    job = start_agent_job("changelog", _changelog_work)
    return {"ok": True, "jobId": job.id, "kind": "changelog"}
```

### Step 3.7 — Register the router in `main.py`

- [ ] **Edit `backend/app/main.py`** — add the new router import and include call:

After the existing router imports block (near line 196), add:
```python
from app.api.v1.agent_jobs import router as agent_jobs_router  # noqa: E402
```

After `app.include_router(merge_router)` (around line 215), add:
```python
app.include_router(agent_jobs_router)
```

### Step 3.8 — Run ALL contract tests to verify the new + updated tests pass

- [ ] **Run the new agent-jobs API tests**:

```
cd backend && .venv/Scripts/python.exe -m pytest tests/contract/test_agent_jobs_api.py -v
```

Expected: All tests PASS.

- [ ] **Run the updated existing contract tests** (insights + ideas + integrations):

```
cd backend && .venv/Scripts/python.exe -m pytest tests/contract/test_insights_api.py tests/contract/test_ideas_api.py tests/contract/test_integrations_api.py -v
```

Expected: All tests PASS (including the updated shape tests, and the old tests that were not about the generate endpoint).

### Step 3.9 — Run the full test suite

- [ ] **Run all tests**:

```
cd backend && .venv/Scripts/python.exe -m pytest tests/ -v 2>&1 | tail -40
```

Expected: All tests PASS. Note and fix any regressions.

### Step 3.10 — Full lint + type-check

- [ ] **Run ruff** (zero errors):

```
cd backend && .venv/Scripts/python.exe -m ruff check .
```

- [ ] **Run mypy** (zero errors in `app/`):

```
cd backend && .venv/Scripts/python.exe -m mypy --strict app/
```

Fix any issues before committing. Common mypy issues to watch for:
- `start_agent_job`'s `work` parameter type: `Callable[[pathlib.Path], Awaitable[dict[str, Any]]]` — the lambdas in the endpoint handlers capture `output_path: Any` which may need casting.
- The `output_path: Any` param in the lambda closures — using `pathlib.Path(output_path)` converts it correctly.

### Step 3.11 — Commit

- [ ] **Commit**:

```bash
git add backend/app/api/v1/agent_jobs.py \
        backend/app/api/v1/insights.py \
        backend/app/api/v1/ideas.py \
        backend/app/api/v1/integrations.py \
        backend/app/main.py \
        backend/tests/contract/test_agent_jobs_api.py \
        backend/tests/contract/test_insights_api.py \
        backend/tests/contract/test_ideas_api.py \
        backend/tests/contract/test_integrations_api.py
git commit -m "feat: agent-jobs API + convert rebuild-map/ideas/changelog to job mode"
```

---

## Post-implementation verification checklist

Run these after all 3 tasks are committed:

- [ ] `cd backend && .venv/Scripts/python.exe -m pytest tests/ -v` — ALL green
- [ ] `cd backend && .venv/Scripts/python.exe -m ruff check .` — zero errors
- [ ] `cd backend && .venv/Scripts/python.exe -m mypy --strict app/` — zero errors
- [ ] `git log --oneline -4` — shows 3 logical commits for this feature

---

## Notes & potential gotchas

1. **asyncio.create_task requires a running loop.** `start_agent_job` must ONLY be called from `async def` handlers (Task 3). The 3 converted endpoints are all `async def`, so this is satisfied.

2. **_StateLock is a threading lock + file lock.** It works fine from both sync and async contexts because the async handlers run in the event loop thread (FastAPI/uvicorn). The lock is non-blocking with a 30s timeout.

3. **pytest-asyncio mode.** The unit tests use `@pytest.mark.asyncio`. Check `pyproject.toml` or `pytest.ini` for `asyncio_mode`. If it's `auto`, the marker is optional. If `strict`, add the marker. The existing `test_plan_goal.py` uses `asyncio.run()` inside sync tests — our tests use the `@pytest.mark.asyncio` decorator + `await` pattern which is cleaner.

4. **ruff unused imports.** `from __future__ import annotations` and unused `import asyncio` in the converted endpoints (since `asyncio.run()` is removed). Remove any no-longer-needed imports. Check especially `integrations.py` which had `import asyncio` for the `asyncio.run()` call — if no other function uses it, remove it or keep only if needed by `autofix_sync`.

5. **ideas.py `asyncio` import.** After converting `generate_ideas_endpoint`, `asyncio` is no longer needed in `ideas.py`. Remove it from the module-level imports to keep ruff clean.

6. **insights.py `asyncio` import.** `asyncio` is still needed for `insights_ask` which uses `asyncio.run(ask(...))`. Keep it.

7. **mypy and the `work` lambda.** The lambda `_map_work(output_path: Any) -> dict[str, Any]` satisfies `Callable[[pathlib.Path], Awaitable[dict[str, Any]]]` at runtime. Mypy may complain about `Any` covariance. If so, type the parameter as `pathlib.Path` directly:
   ```python
   async def _map_work(op: pathlib.Path) -> dict[str, Any]:
       m = await build_map(ws, runner=runner, output_path=op)
       return {"count": len(m)}
   job = start_agent_job("map", _map_work)
   ```
   This is cleaner and mypy-friendly.
