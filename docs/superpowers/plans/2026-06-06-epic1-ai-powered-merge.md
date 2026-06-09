# Epic 1 — AI-Powered Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add AI conflict resolution to the merge flow — on a `git merge` conflict, an agent resolves the conflicted files (markers + task intent), the result is verified, and a human Accepts/Rejects via a live panel — all isolated in a git worktree.

**Architecture:** A tracked `MergeJob` (persisted in `merge-jobs.json`, artifacts in `merge-NNNN/`) is run by `MergeJobRunner` in the backend event loop: create worktree → `git merge` → on conflict call `MergeResolver` (injectable agent) → post-check markers gone → `VerifyRunner` → `RESOLVED`. Accept fast-forwards the worktree branch into base; Reject discards it (base untouched). Live agent output streams over a dedicated SSE endpoint that terminates on job status (not loop status).

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 (camelCase aliases) / pytest; Vue 3 `<script setup>` / Pinia / Vitest. Agents via existing `AgentRunner` (opencode/claude CLI). Git worktrees.

**Spec:** `docs/superpowers/specs/2026-06-06-epic1-ai-powered-merge-design.md` — read it before starting; it is the source of truth for contracts.

**Conventions to follow (read these first):**
- Models: `backend/app/models/validation.py`, `backend/app/models/workspace.py` (camelCase via `Field(alias=...)`, `populate_by_name=True`).
- Git/merge: `backend/app/core/git.py` (`GitService`, `_action_merge`, `merge_to_base`, `_run`, `_is_safe_auto_branch`).
- State/locking/atomic write: `backend/app/core/state.py` (`_state_dir`, `_StateLock`, `_atomic_write`).
- Agent: `backend/app/services/opencode_runner.py` (`AgentRunner`, `AgentResult`).
- Verify: `backend/app/core/verify.py` (`VerifyRunner.run`).
- SSE tailing: `backend/app/api/v1/iters.py:85` (`iter_stream`), event parse `backend/app/core/events.py` (`_summarize_event`).
- Test patterns: `backend/tests/integration/test_merge_to_base.py`, `backend/tests/unit/test_git_service.py`, `backend/tests/contract/test_merge_api.py`, `backend/tests/unit/test_task_fields.py`, `frontend/src/components/__tests__/MergeButton.spec.ts`.

**Frequent commits:** one commit per task (after its tests pass). Work on branch `feat/epic1-ai-powered-merge`.

---

## File Structure

**New backend files**
- `backend/app/models/merge.py` — `MergeJobStatus`, `MergeDecision`, `MergeJob`.
- `backend/app/core/merge_resolver.py` — `has_conflict_markers()`, `build_resolver_prompt()`, `MergeResolver`, `ResolveOutcome`.
- `backend/app/core/merge_job.py` — `MergeJobStore`, `MergeJobRunner`, `_next_merge_seq()`.
- `prompts/merge-resolver.md` — intent-preservation prompt template.

**Modified backend files**
- `backend/app/models/workspace.py` — `AgentsConfig.merge: AgentRef | None`.
- `backend/app/models/domain.py` — `Item.merge_resolution` (alias `mergeResolution`).
- `backend/app/models/validation.py` — `MergeRequest` gains `ai_resolve`, `auto_accept`.
- `backend/app/core/git.py` — add `_current_sha`, `_worktree_add`, `_worktree_remove`, `_ff_merge` helpers (module-level, used by runner).
- `backend/app/api/v1/merge.py` — merge starts a job; add `merge-jobs/{id}` get/stream/accept/reject.
- `backend/app/config.py` — `ALLOWED_CONFIG_KEYS` += merge limit/timeout keys.
- `backend/app/main.py` — call `MergeJobStore().reap()` in lifespan startup.

**New/modified frontend files**
- `frontend/src/types/api.ts` — `MergeJob`, `MergeJobStatus`, `MergeDecision`, `Item.mergeResolution?`.
- `frontend/src/api/client.ts` — `startMerge`, `getMergeJob`, `acceptMerge`, `rejectMerge`.
- `frontend/src/components/LiveConsole.vue` — optional `streamUrl` prop.
- `frontend/src/components/MergeJobPanel.vue` — new: live + diff + Accept/Reject.
- `frontend/src/components/MergeButton.vue` — start job, open panel.

**Tests**
- `backend/tests/unit/test_merge_models.py`, `test_merge_resolver.py`, `test_merge_job_store.py`
- `backend/tests/integration/test_merge_job_flow.py`
- `backend/tests/contract/test_merge_api.py` (extend existing)
- `frontend/src/components/__tests__/MergeJobPanel.spec.ts`, extend `MergeButton.spec.ts`

---

## Task 1: Domain models (MergeJob, AgentsConfig.merge, Item.mergeResolution)

**Files:**
- Create: `backend/app/models/merge.py`
- Modify: `backend/app/models/workspace.py` (AgentsConfig), `backend/app/models/domain.py` (Item)
- Test: `backend/tests/unit/test_merge_models.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_merge_models.py
from app.models.merge import MergeJob, MergeJobStatus, MergeDecision
from app.models.workspace import AgentsConfig, AgentRef


def test_mergejob_camelcase_roundtrip():
    job = MergeJob(
        id="merge-0001", branch="auto/x", base_branch="main",
        status=MergeJobStatus.RESOLVED, decision=MergeDecision.AI_MERGED,
        resolved_files=["a.py"], verify_ok=True, worktree_branch="hephaestus/merge/x",
        base_sha="abc123", item_id="x",
    )
    d = job.model_dump(by_alias=True)
    assert d["baseBranch"] == "main"
    assert d["resolvedFiles"] == ["a.py"]
    assert d["verifyOk"] is True
    assert d["workerBranch" if False else "worktreeBranch"] == "hephaestus/merge/x"
    assert d["baseSha"] == "abc123"
    # round-trips back from camelCase
    assert MergeJob.model_validate(d).status is MergeJobStatus.RESOLVED


def test_agentsconfig_merge_role_optional():
    cfg = AgentsConfig(primary=AgentRef(provider="anthropic", model="m"),
                       fallback=AgentRef(provider="anthropic", model="m"))
    assert cfg.merge is None
    cfg2 = AgentsConfig.model_validate({
        "primary": {"provider": "a", "model": "m"},
        "fallback": {"provider": "a", "model": "m"},
        "merge": {"provider": "a", "model": "haiku"},
    })
    assert cfg2.merge.model == "haiku"


def test_item_merge_resolution_alias():
    from app.models.domain import Item
    it = Item(id="x", title="t")
    it.merge_resolution = "ai"
    assert it.model_dump(by_alias=True)["mergeResolution"] == "ai"
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError: app.models.merge`)

Run: `cd backend && python -m pytest tests/unit/test_merge_models.py -v`

- [ ] **Step 3: Implement `backend/app/models/merge.py`**

Copy the full `MergeJobStatus`, `MergeDecision`, `MergeJob` definitions verbatim from spec §2 (all fields with their camelCase aliases). Use `from enum import StrEnum` and `model_config = ConfigDict(populate_by_name=True)`.

- [ ] **Step 4: Add `merge` role to `AgentsConfig`** in `workspace.py` after `final`:

```python
    final: AgentRef | None = None
    # Conflict-resolution role (Epic 1). None -> falls back to `primary`.
    merge: AgentRef | None = None
```

- [ ] **Step 5: Add `merge_resolution` to `Item`** in `domain.py` (place beside the other merge fields like `merge_sha`):

```python
    merge_resolution: str | None = Field(None, alias="mergeResolution")  # "auto"|"ai"|"manual"
```
If `Item` uses `model_config = ConfigDict(extra="allow", populate_by_name=True)` already (it does), no other change is needed.

- [ ] **Step 6: Run — expect PASS**

Run: `cd backend && python -m pytest tests/unit/test_merge_models.py -v`

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/merge.py backend/app/models/workspace.py backend/app/models/domain.py backend/tests/unit/test_merge_models.py
git commit -m "feat(epic1): MergeJob model + merge agent role + Item.mergeResolution"
```

---

## Task 2: Conflict-marker detection + resolver prompt (pure functions)

**Files:**
- Create: `backend/app/core/merge_resolver.py` (partial — pure helpers only), `prompts/merge-resolver.md`
- Test: `backend/tests/unit/test_merge_resolver.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/test_merge_resolver.py
from app.core.merge_resolver import has_conflict_markers, build_resolver_prompt


def test_has_conflict_markers_positive():
    text = "a\n<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> auto/x\nb\n"
    assert has_conflict_markers(text) is True


def test_has_conflict_markers_negative():
    assert has_conflict_markers("clean code\nno markers\n") is False
    # a line that merely contains '====' but is not a 7-char conflict marker
    assert has_conflict_markers("x = '======='  # decoration\n") is False


def test_build_resolver_prompt_includes_intent_and_files():
    item = {"proposal": "add retry", "why": "flaky net", "acceptance": "tests green"}
    prompt = build_resolver_prompt(item=item, conflicts=["src/a.py", "src/b.py"])
    assert "add retry" in prompt
    assert "src/a.py" in prompt and "src/b.py" in prompt
    assert "conflict" in prompt.lower()
```

- [ ] **Step 2: Run — expect FAIL** (import error)

Run: `cd backend && python -m pytest tests/unit/test_merge_resolver.py -v`

- [ ] **Step 3: Create `prompts/merge-resolver.md`** (intent-preservation template; `{intent}` / `{files}` placeholders):

```markdown
You are resolving git merge conflicts. The working directory contains files with
conflict markers (<<<<<<<, =======, >>>>>>>).

Task intent (preserve this behavior):
{intent}

Files with conflicts:
{files}

Rules:
- Resolve each conflicted file so BOTH sides' intent is preserved.
- Include all imports from both sides. Preserve hook/initialization ordering
  (earlier side first / outer). Combine edits to the same function logically.
- Remove EVERY conflict marker (<<<<<<<, =======, >>>>>>>).
- Edit the files IN PLACE in the working directory. Do NOT touch any other files.
- Do not add features or refactor beyond resolving the conflict.

When done, output a one-line summary of how you resolved them.
```

- [ ] **Step 4: Implement pure helpers in `backend/app/core/merge_resolver.py`**

```python
from __future__ import annotations
import pathlib

_PROMPT_PATH = pathlib.Path(__file__).resolve().parents[2] / "prompts" / "merge-resolver.md"
# parents[2] == repo root (backend/app/core -> backend/app -> backend -> root). Verify at runtime.


def has_conflict_markers(text: str) -> bool:
    for line in text.splitlines():
        if line.startswith("<<<<<<<") or line.startswith(">>>>>>>") or line == "=======":
            return True
    return False


def build_resolver_prompt(*, item: dict, conflicts: list[str]) -> str:
    intent = "\n".join(
        f"- {k}: {item.get(k)}" for k in ("proposal", "why", "acceptance") if item.get(k)
    ) or "- (no intent recorded)"
    files = "\n".join(f"- {f}" for f in conflicts)
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    return template.replace("{intent}", intent).replace("{files}", files)
```

Note: confirm `parents[2]` resolves to repo root containing `prompts/`. If the runtime root differs, resolve relative to `prompts/` the way `prompt_manager.py` does (read `backend/app/services/prompt_manager.py` for the established prompts-dir resolution and reuse it).

- [ ] **Step 5: Run — expect PASS**

Run: `cd backend && python -m pytest tests/unit/test_merge_resolver.py -v`

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/merge_resolver.py prompts/merge-resolver.md backend/tests/unit/test_merge_resolver.py
git commit -m "feat(epic1): conflict-marker detection + resolver prompt builder"
```

---

## Task 3: MergeJobStore + merge-NNNN sequencing (persistence)

**Files:**
- Modify: `backend/app/core/merge_job.py` (new file; store + seq only this task)
- Test: `backend/tests/unit/test_merge_job_store.py`

- [ ] **Step 1: Write failing tests** (use the `_STATE_DIR_OVERRIDE` test hook like `test_state.py`)

```python
# backend/tests/unit/test_merge_job_store.py
import pathlib
import app.core.state as state
from app.core.merge_job import MergeJobStore, _next_merge_seq
from app.models.merge import MergeJob, MergeJobStatus


def _use_tmp(tmp_path: pathlib.Path):
    state._STATE_DIR_OVERRIDE = tmp_path
    return tmp_path


def test_next_merge_seq_monotonic(tmp_path, monkeypatch):
    _use_tmp(tmp_path)
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    (tmp_path / "merge-0001").mkdir()
    (tmp_path / "merge-0007").mkdir()
    assert _next_merge_seq() == 8


def test_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    store = MergeJobStore()
    job = MergeJob(id="merge-0001", branch="auto/x", base_branch="main",
                   status=MergeJobStatus.RUNNING)
    store.put(job)
    got = store.get("merge-0001")
    assert got is not None and got.branch == "auto/x"
    job.status = MergeJobStatus.RESOLVED
    store.put(job)
    assert store.get("merge-0001").status is MergeJobStatus.RESOLVED
    assert any(j.id == "merge-0001" for j in store.list())
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd backend && python -m pytest tests/unit/test_merge_job_store.py -v`

- [ ] **Step 3: Implement store + seq in `backend/app/core/merge_job.py`**

```python
from __future__ import annotations
import json
from app.core.state import _state_dir, _StateLock, _atomic_write
from app.models.merge import MergeJob

_REGISTRY = "merge-jobs.json"
_MAX_KEEP = 50


def _next_merge_seq() -> int:
    sd = _state_dir()
    nums = [int(p.name.split("-")[1]) for p in sd.glob("merge-*")
            if p.is_dir() and p.name.split("-")[1].isdigit()]
    return (max(nums) + 1) if nums else 1


class MergeJobStore:
    def _path(self):
        return _state_dir() / _REGISTRY

    def list(self) -> list[MergeJob]:
        p = self._path()
        if not p.exists():
            return []
        raw = json.loads(p.read_text(encoding="utf-8") or '{"jobs": []}')
        return [MergeJob.model_validate(j) for j in raw.get("jobs", [])]

    def get(self, job_id: str) -> MergeJob | None:
        return next((j for j in self.list() if j.id == job_id), None)

    def put(self, job: MergeJob) -> None:
        with _StateLock():
            jobs = self.list()
            jobs = [j for j in jobs if j.id != job.id]
            jobs.append(job)
            jobs = jobs[-_MAX_KEEP:]
            payload = json.dumps({"jobs": [j.model_dump(by_alias=True) for j in jobs]},
                                 indent=2, ensure_ascii=False)
            self._path().parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(self._path(), payload)

    def active(self) -> MergeJob | None:
        """The single non-terminal job, if any (serialization guard)."""
        terminal = {"accepted", "rejected", "failed", "conflict"}
        return next((j for j in self.list() if j.status.value not in terminal), None)
```

- [ ] **Step 4: Run — expect PASS**

Run: `cd backend && python -m pytest tests/unit/test_merge_job_store.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/merge_job.py backend/tests/unit/test_merge_job_store.py
git commit -m "feat(epic1): MergeJobStore + merge-NNNN sequencing"
```

---

## Task 4: Git worktree/ff helpers

**Files:**
- Modify: `backend/app/core/git.py` (add module-level helpers)
- Test: `backend/tests/unit/test_merge_git_helpers.py`

- [ ] **Step 1: Write failing test** (build a tmp git repo; follow `test_merge_to_base.py` fixture style)

```python
# backend/tests/unit/test_merge_git_helpers.py
import subprocess, pathlib
from app.core.git import _current_sha, _worktree_add, _worktree_remove, _ff_merge


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _make_repo(tmp_path) -> pathlib.Path:
    r = tmp_path / "repo"; r.mkdir()
    _git(r, "init", "-b", "main"); _git(r, "config", "user.email", "a@b.c")
    _git(r, "config", "user.name", "t")
    (r / "f.txt").write_text("base\n"); _git(r, "add", "-A"); _git(r, "commit", "-m", "init")
    return r


def test_worktree_add_remove_and_ff(tmp_path):
    repo = _make_repo(tmp_path)
    base_sha = _current_sha(str(repo), "main")
    assert base_sha and len(base_sha) >= 7
    # branch with a non-conflicting change
    _git(repo, "checkout", "-b", "auto/x")
    (repo / "g.txt").write_text("new\n"); _git(repo, "add", "-A"); _git(repo, "commit", "-m", "add g")
    _git(repo, "checkout", "main")
    wt = tmp_path / "wt"
    assert _worktree_add(str(repo), str(wt), "hephaestus/merge/x", "main") is True
    _git(wt, "merge", "--no-ff", "--no-edit", "auto/x")
    # ff main to the worktree branch
    assert _ff_merge(str(repo), "hephaestus/merge/x", "main") is True
    assert (repo / "g.txt").exists()
    _worktree_remove(str(repo), str(wt), "hephaestus/merge/x")
    assert not wt.exists()
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd backend && python -m pytest tests/unit/test_merge_git_helpers.py -v`

- [ ] **Step 3: Implement helpers in `git.py`** (reuse existing `_run` + `subprocess` patterns; place after `GitService` or near other helpers)

```python
def _current_sha(repo: str, ref: str) -> str:
    return _run(["git", "rev-parse", ref], cwd=repo, default="")


def _worktree_add(repo: str, wt: str, branch: str, start_ref: str) -> bool:
    # best-effort cleanup of a stale worktree at this path, then create
    subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=repo,
                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    r = subprocess.run(["git", "worktree", "add", "-b", branch, wt, start_ref], cwd=repo,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    return r.returncode == 0


def _worktree_remove(repo: str, wt: str, branch: str | None = None) -> None:
    subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=repo,
                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    subprocess.run(["git", "worktree", "prune"], cwd=repo,
                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if branch:
        subprocess.run(["git", "branch", "-D", branch], cwd=repo,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)


def _ff_merge(repo: str, branch: str, base: str) -> bool:
    co = subprocess.run(["git", "checkout", base], cwd=repo, capture_output=True,
                        text=True, encoding="utf-8", errors="replace", timeout=60)
    if co.returncode != 0:
        return False
    m = subprocess.run(["git", "merge", "--ff-only", branch], cwd=repo, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=60)
    return m.returncode == 0
```

- [ ] **Step 4: Run — expect PASS** (on this machine, Windows — confirms cross-platform worktree ops)

Run: `cd backend && python -m pytest tests/unit/test_merge_git_helpers.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/git.py backend/tests/unit/test_merge_git_helpers.py
git commit -m "feat(epic1): git worktree add/remove + ff-merge helpers"
```

---

## Task 5: MergeResolver.resolve (agent injection + outcome)

**Files:**
- Modify: `backend/app/core/merge_resolver.py` (add `ResolveOutcome`, `MergeResolver`)
- Test: `backend/tests/unit/test_merge_resolver.py` (extend)

- [ ] **Step 1: Write failing test** (stub agent that edits a file to strip markers; no real CLI)

```python
# append to backend/tests/unit/test_merge_resolver.py
import pathlib, asyncio
from app.core.merge_resolver import MergeResolver, ResolveOutcome


def test_resolver_runs_injected_agent(tmp_path):
    wt = tmp_path / "wt"; wt.mkdir()
    conflicted = wt / "a.py"
    conflicted.write_text("<<<<<<< HEAD\nx=1\n=======\nx=2\n>>>>>>> auto/x\n")

    async def fake_agent(prompt_file, cwd, output_path):
        # simulate the agent resolving the conflict in place + writing JSONL
        conflicted.write_text("x = 1\nx = 2\n")
        pathlib.Path(output_path).write_text('{"type":"finish"}\n')
        from app.services.opencode_runner import AgentResult
        return AgentResult(exit_code=0, refused=False, output_path=pathlib.Path(output_path),
                           agent_label="stub")

    ws = _make_ws()  # helper returning a minimal RepoProfile (see test_git_service.py)
    res = asyncio.run(MergeResolver(ws, run_agent=fake_agent).resolve(
        worktree_cwd=str(wt), conflicts=["a.py"], item={"proposal": "p"},
        job_dir=tmp_path, timeout_sec=60))
    assert isinstance(res, ResolveOutcome) and res.ok is True
    assert "<<<<<<<" not in conflicted.read_text()
```

Add a `_make_ws()` helper at the top of the test module that builds a minimal `RepoProfile` (copy the pattern from `backend/tests/unit/test_git_service.py`).

- [ ] **Step 2: Run — expect FAIL**

Run: `cd backend && python -m pytest tests/unit/test_merge_resolver.py::test_resolver_runs_injected_agent -v`

- [ ] **Step 3: Implement `ResolveOutcome` + `MergeResolver`**

```python
# add to backend/app/core/merge_resolver.py
from pydantic import BaseModel


class ResolveOutcome(BaseModel):
    ok: bool
    agent_exit: int
    output_path: pathlib.Path


class MergeResolver:
    def __init__(self, ws, *, run_agent=None) -> None:
        self.ws = ws
        self._run_agent = run_agent  # async (prompt_file, cwd, output_path) -> AgentResult

    async def resolve(self, *, worktree_cwd, conflicts, item, job_dir, timeout_sec) -> ResolveOutcome:
        prompt = build_resolver_prompt(item=item, conflicts=conflicts)
        job_dir = pathlib.Path(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = job_dir / "resolve.prompt.md"
        prompt_file.write_text(prompt, encoding="utf-8")
        output_path = job_dir / "output.resolve.jsonl"
        if self._run_agent is not None:
            result = await self._run_agent(prompt_file, worktree_cwd, output_path)
        else:
            from app.core.process import pm
            from app.services.opencode_runner import AgentRunner
            ref = self.ws.agents.merge or self.ws.agents.primary
            runner = AgentRunner(pm, engine=self.ws.engine, env=self.ws.engine_env,
                                 profiles=self.ws.engine_profiles)
            result = await runner.run(ref, prompt_file=prompt_file, cwd=worktree_cwd,
                                      output_path=output_path, timeout_sec=timeout_sec,
                                      use_models=self.ws.agents.use_models)
        return ResolveOutcome(ok=(result.exit_code == 0 and not result.refused),
                              agent_exit=result.exit_code, output_path=output_path)
```

Marker post-checking is the **runner's** job (Task 6), not the resolver's — keep this unit focused on "run the agent."

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/merge_resolver.py backend/tests/unit/test_merge_resolver.py
git commit -m "feat(epic1): MergeResolver with injectable agent"
```

---

## Task 6: MergeJobRunner — start flow (worktree → merge → resolve → verify → resolved)

**Files:**
- Modify: `backend/app/core/merge_job.py` (add `MergeJobRunner`)
- Test: `backend/tests/integration/test_merge_job_flow.py`

- [ ] **Step 1: Write failing tests** (tmp repo with a real conflict; stub resolver agent + stub verify)

```python
# backend/tests/integration/test_merge_job_flow.py
import subprocess, pathlib, asyncio
import app.core.state as state
from app.core.merge_job import MergeJobRunner, MergeJobStore
from app.models.merge import MergeJobStatus, MergeDecision


def _git(cwd, *a): subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True)


def _conflict_repo(tmp_path):
    r = tmp_path / "repo"; r.mkdir()
    _git(r, "init", "-b", "main"); _git(r, "config", "user.email", "a@b.c"); _git(r, "config", "user.name", "t")
    (r / "f.txt").write_text("base\n"); _git(r, "add", "-A"); _git(r, "commit", "-m", "init")
    _git(r, "checkout", "-b", "auto/x")
    (r / "f.txt").write_text("branch-change\n"); _git(r, "add", "-A"); _git(r, "commit", "-m", "x")
    _git(r, "checkout", "main")
    (r / "f.txt").write_text("base-change\n"); _git(r, "add", "-A"); _git(r, "commit", "-m", "base")
    return r


def _ws_for(repo, monkeypatch, tmp_path):
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path / "hephaestusstate")
    (tmp_path / "hephaestusstate").mkdir()
    # seed a Task referencing the branch so preflight/item lookup works
    from app.core.state import _write_state
    _write_state({"items": [{"id": "x", "branch": "auto/x", "verify_green": True,
                             "validation": {"gate": "pass"}, "status": "done", "proposal": "p"}]})
    return _make_ws(str(repo))  # minimal RepoProfile with repo_path=repo, base_branch=main


async def _resolve_ok(prompt_file, cwd, output_path):
    # resolve the conflict in the worktree, strip markers
    (pathlib.Path(cwd) / "f.txt").write_text("base-change\nbranch-change\n")
    pathlib.Path(output_path).write_text('{"type":"finish"}\n')
    from app.services.opencode_runner import AgentResult
    return AgentResult(exit_code=0, refused=False, output_path=pathlib.Path(output_path), agent_label="stub")


def test_ai_merge_resolved(tmp_path, monkeypatch):
    repo = _conflict_repo(tmp_path); ws = _ws_for(repo, monkeypatch, tmp_path)
    runner = MergeJobRunner(ws, run_agent=_resolve_ok, verify=_FakeVerify(ok=True))
    job = asyncio.run(runner.start(branch="auto/x", push=False, ai_resolve=True, auto_accept=False))
    assert job.status is MergeJobStatus.RESOLVED
    assert job.decision is MergeDecision.AI_MERGED
    assert job.verify_ok is True
    assert "f.txt" in job.resolved_files
    # base is NOT yet changed (still isolated in worktree)
    assert (repo / "f.txt").read_text() == "base-change\n"


def test_ai_merge_failed_when_markers_remain(tmp_path, monkeypatch):
    repo = _conflict_repo(tmp_path); ws = _ws_for(repo, monkeypatch, tmp_path)
    async def _bad(pf, cwd, op):
        pathlib.Path(op).write_text("{}\n")
        from app.services.opencode_runner import AgentResult
        return AgentResult(exit_code=0, refused=False, output_path=pathlib.Path(op), agent_label="stub")
    runner = MergeJobRunner(ws, run_agent=_bad, verify=_FakeVerify(ok=True))
    job = asyncio.run(runner.start(branch="auto/x", push=False, ai_resolve=True, auto_accept=False))
    assert job.status is MergeJobStatus.FAILED
    # worktree cleaned, base untouched
    assert (repo / "f.txt").read_text() == "base-change\n"


def test_verify_red_fails(tmp_path, monkeypatch):
    repo = _conflict_repo(tmp_path); ws = _ws_for(repo, monkeypatch, tmp_path)
    runner = MergeJobRunner(ws, run_agent=_resolve_ok, verify=_FakeVerify(ok=False))
    job = asyncio.run(runner.start(branch="auto/x", push=False, ai_resolve=True, auto_accept=False))
    assert job.status is MergeJobStatus.FAILED
```

Add a `_FakeVerify` class (a stand-in with `async def run(self, *, cwd, log_path, timeout_sec)` returning an object with `.ok`) and reuse the `_make_ws` helper. Mirror the fixture style of `test_merge_to_base.py`.

- [ ] **Step 2: Run — expect FAIL**

Run: `cd backend && python -m pytest tests/integration/test_merge_job_flow.py -v`

- [ ] **Step 3: Implement `MergeJobRunner.start`** following spec §4 exactly. Key structure:

```python
# add to backend/app/core/merge_job.py
import pathlib, time
from app.core.git import (_current_sha, _worktree_add, _worktree_remove, _ff_merge,
                          _run, _is_safe_auto_branch, _update_item_by_branch)
from app.core.decisions import _append_decision
from app.core.merge_resolver import MergeResolver, has_conflict_markers
from app.core.verify import VerifyRunner
from app.models.merge import MergeJob, MergeJobStatus, MergeDecision


class MergeJobRunner:
    def __init__(self, ws, *, run_agent=None, verify=None) -> None:
        self.ws = ws
        self._run_agent = run_agent          # inject for tests
        self._verify = verify or VerifyRunner(ws)
        self.store = MergeJobStore()

    def _now(self): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    async def start(self, *, branch, push, ai_resolve, auto_accept) -> MergeJob:
        from app.core.state import _state_dir, _read_state
        repo, base, remote = self.ws.repo_path, self.ws.base_branch, self.ws.remote
        seq = _next_merge_seq()
        job_id = f"merge-{seq:04d}"
        job_dir = _state_dir() / job_id
        item = next((it for it in _read_state().get("items", []) if it.get("branch") == branch), None)
        wt = str(pathlib.Path(repo).parent / ".hephaestus-worktrees" / job_id)
        wt_branch = f"hephaestus/merge/{branch.split('/', 1)[-1]}"
        job = MergeJob(id=job_id, branch=branch, base_branch=base, status=MergeJobStatus.RUNNING,
                       worktree=wt, worktree_branch=wt_branch, base_sha=_current_sha(repo, base),
                       item_id=(item or {}).get("id"), push=push, auto_accept=auto_accept,
                       created_at=self._now(), updated_at=self._now())
        self.store.put(job)

        def _fail(msg, status=MergeJobStatus.FAILED, decision=MergeDecision.FAILED):
            _worktree_remove(repo, wt, wt_branch)
            job.status, job.decision, job.error, job.updated_at = status, decision, msg, self._now()
            self.store.put(job); return job

        # fetch base (best-effort) then create worktree from base
        _run(["git", "fetch", remote, base], cwd=repo)  # best effort; ignore failure
        if not _worktree_add(repo, wt, wt_branch, base):
            return _fail("worktree add failed")
        # merge the source branch INTO the worktree (no commit yet)
        import subprocess
        m = subprocess.run(["git", "merge", "--no-ff", "--no-commit", branch], cwd=wt,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        conflicts = _run(["git", "diff", "--name-only", "--diff-filter=U"], cwd=wt).splitlines()
        if m.returncode == 0 and not conflicts:
            job.decision = MergeDecision.AUTO_MERGED
        else:
            if not ai_resolve or self._over_limits(wt, conflicts):
                subprocess.run(["git", "merge", "--abort"], cwd=wt, capture_output=True, text=True)
                _worktree_remove(repo, wt, wt_branch)
                job.status, job.decision, job.conflicts = MergeJobStatus.CONFLICT, MergeDecision.NEEDS_HUMAN, conflicts
                job.updated_at = self._now(); self.store.put(job); return job
            job.status, job.conflicts = MergeJobStatus.RESOLVING, conflicts; self.store.put(job)
            outcome = await MergeResolver(self.ws, run_agent=self._run_agent).resolve(
                worktree_cwd=wt, conflicts=conflicts, item=item or {}, job_dir=job_dir,
                timeout_sec=self._timeout())
            # post-checks: agent exit ok, no markers left, no unmerged paths
            if not outcome.ok:
                subprocess.run(["git", "merge", "--abort"], cwd=wt, capture_output=True, text=True)
                return _fail("resolver agent failed")
            still = _run(["git", "diff", "--name-only", "--diff-filter=U"], cwd=wt).splitlines()
            markers_left = any(
                has_conflict_markers((pathlib.Path(wt) / f).read_text(encoding="utf-8", errors="replace"))
                for f in conflicts if (pathlib.Path(wt) / f).exists())
            if still or markers_left:
                subprocess.run(["git", "merge", "--abort"], cwd=wt, capture_output=True, text=True)
                return _fail("conflict markers remain after resolution")
            _run(["git", "add", "-A"], cwd=wt)
            job.decision, job.resolved_files = MergeDecision.AI_MERGED, conflicts

        # commit the merge in the worktree
        subj = _run(["git", "log", "-1", "--pretty=%s", branch], cwd=repo) or f"merge {branch}"
        if job.decision is MergeDecision.AUTO_MERGED:
            _run(["git", "add", "-A"], cwd=wt)
        subprocess.run(["git", "commit", "--no-edit", "-m", f"merge: {subj} (from {branch})"],
                       cwd=wt, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        # verify on the merged tree
        job.status = MergeJobStatus.VERIFYING; self.store.put(job)
        vres = await self._verify.run(cwd=wt, log_path=job_dir / "verify.log", timeout_sec=self._timeout())
        job.verify_ok = vres.ok
        if not vres.ok:
            return _fail("verify failed on merged tree")
        # resolved: capture diff, retain worktree for accept/reject
        diff = _run(["git", "diff", f"{base}..{wt_branch}"], cwd=repo, default="")
        (job_dir).mkdir(parents=True, exist_ok=True)
        (job_dir / "merge.diff").write_text(diff, encoding="utf-8")
        job.diff = diff[:65536]
        job.status, job.updated_at = MergeJobStatus.RESOLVED, self._now()
        self.store.put(job)
        if auto_accept and job.verify_ok and job.decision in (MergeDecision.AUTO_MERGED, MergeDecision.AI_MERGED):
            return await self.accept(job_id, push=push)
        return job
```

Add helper methods `_over_limits(wt, conflicts)` (count > `HEPHAESTUS_MERGE_MAX_FILES` or any file > `HEPHAESTUS_MERGE_MAX_FILE_BYTES` → True) and `_timeout()` (reads `HEPHAESTUS_MERGE_TIMEOUT_SEC` or `ws.verify_timeout_sec`). Read these from `app.config` (added in Task 8).

- [ ] **Step 4: Run — expect PASS** for the three start-flow tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/merge_job.py backend/tests/integration/test_merge_job_flow.py
git commit -m "feat(epic1): MergeJobRunner start flow (worktree/merge/resolve/verify)"
```

---

## Task 7: MergeJobRunner — accept / reject / reaper

**Files:**
- Modify: `backend/app/core/merge_job.py`
- Test: `backend/tests/integration/test_merge_job_flow.py` (extend)

- [ ] **Step 1: Write failing tests**

```python
# append to test_merge_job_flow.py
def test_accept_ff_into_base_and_cleanup(tmp_path, monkeypatch):
    repo = _conflict_repo(tmp_path); ws = _ws_for(repo, monkeypatch, tmp_path)
    runner = MergeJobRunner(ws, run_agent=_resolve_ok, verify=_FakeVerify(ok=True))
    job = asyncio.run(runner.start(branch="auto/x", push=False, ai_resolve=True, auto_accept=False))
    res = asyncio.run(runner.accept(job.id, push=False))
    assert res["ok"] is True
    assert (repo / "f.txt").read_text() == "base-change\nbranch-change\n"   # merged into base now
    # source + temp branches deleted; item marked merged with mergeResolution
    from app.core.state import _read_state
    it = next(i for i in _read_state()["items"] if i["id"] == "x")
    assert it["status"] == "merged" and it.get("mergeResolution") == "ai"
    assert MergeJobStore().get(job.id).status.value == "accepted"


def test_reject_discards_worktree_base_untouched(tmp_path, monkeypatch):
    repo = _conflict_repo(tmp_path); ws = _ws_for(repo, monkeypatch, tmp_path)
    runner = MergeJobRunner(ws, run_agent=_resolve_ok, verify=_FakeVerify(ok=True))
    job = asyncio.run(runner.start(branch="auto/x", push=False, ai_resolve=True, auto_accept=False))
    res = asyncio.run(runner.reject(job.id))
    assert res["ok"] is True
    assert (repo / "f.txt").read_text() == "base-change\n"
    assert not pathlib.Path(job.worktree).exists()
    assert MergeJobStore().get(job.id).status.value == "rejected"
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement `accept`, `reject`, `reap`**

```python
    async def accept(self, job_id, *, push) -> dict:
        job = self.store.get(job_id)
        if job is None or job.status is not MergeJobStatus.RESOLVED:
            return {"ok": False, "error": "job not in resolved state"}
        repo, base, remote = self.ws.repo_path, base_branch_of(self.ws), self.ws.remote
        from app.core.git import GitService
        if GitService(self.ws)._loop_active():
            return {"ok": False, "error": "loop active, stop it before merge"}
        if _current_sha(repo, base) != job.base_sha:
            return {"ok": False, "error": "base moved, reject and re-run merge"}
        if not _ff_merge(repo, job.worktree_branch, base):
            return {"ok": False, "error": "fast-forward into base failed"}
        push_note = "not-pushed"
        if push:
            import subprocess
            p = subprocess.run(["git", "push", remote, base], cwd=repo, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=60)
            if p.returncode != 0:
                # keep branches/worktree so operator can retry; do NOT delete
                return {"ok": False, "error": f"merged locally but push failed: {p.stderr.strip()[:300]}"}
            push_note = "pushed"
        new_sha = _current_sha(repo, base)
        _worktree_remove(repo, job.worktree, job.worktree_branch)
        _run(["git", "branch", "-D", job.branch], cwd=repo)
        resolution = "ai" if job.decision is MergeDecision.AI_MERGED else "auto"
        _update_item_by_branch(job.branch, "merged", {"merged_into": base, "merge_sha": new_sha,
                               "push": push_note, "mergeResolution": resolution})
        _append_decision("human", "merge", job.branch, "ok", f"{new_sha[:10]} {push_note} ({resolution})")
        job.status, job.updated_at = MergeJobStatus.ACCEPTED, self._now(); self.store.put(job)
        return {"ok": True, "branch": job.branch, "newHead": new_sha[:10], "push": push_note}

    async def reject(self, job_id) -> dict:
        job = self.store.get(job_id)
        if job is None:
            return {"ok": False, "error": "job not found"}
        _worktree_remove(self.ws.repo_path, job.worktree, job.worktree_branch)
        job.status, job.updated_at = MergeJobStatus.REJECTED, self._now(); self.store.put(job)
        _append_decision("human", "merge", job.branch, "rejected", "ai-merge discarded")
        return {"ok": True}

    def reap(self) -> None:
        """Clean orphaned non-terminal jobs left by a backend restart."""
        for job in self.store.list():
            if job.status in (MergeJobStatus.RUNNING, MergeJobStatus.RESOLVING, MergeJobStatus.VERIFYING):
                if job.worktree:
                    _worktree_remove(self.ws.repo_path, job.worktree, job.worktree_branch)
                job.status, job.error = MergeJobStatus.FAILED, "orphaned by restart"
                self.store.put(job)
```

Add a tiny `base_branch_of(ws)` inline or just use `self.ws.base_branch` directly (prefer the latter; the helper line above is illustrative — replace with `self.ws.base_branch`).

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/merge_job.py backend/tests/integration/test_merge_job_flow.py
git commit -m "feat(epic1): merge job accept/reject/reaper"
```

---

## Task 8: Config keys + MergeRequest fields

**Files:**
- Modify: `backend/app/config.py` (ALLOWED_CONFIG_KEYS + getters), `backend/app/models/validation.py`
- Test: `backend/tests/unit/test_merge_config.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/unit/test_merge_config.py
from app.models.validation import MergeRequest


def test_merge_request_defaults_and_aliases():
    r = MergeRequest.model_validate({"push": True, "aiResolve": False, "autoAccept": True})
    assert r.push is True and r.ai_resolve is False and r.auto_accept is True
    assert MergeRequest().ai_resolve is True  # default ON
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Extend `MergeRequest`** in `validation.py`:

```python
class MergeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    push: bool = False
    ai_resolve: bool = Field(True, alias="aiResolve")
    auto_accept: bool = Field(False, alias="autoAccept")
```

- [ ] **Step 4: Add config keys** in `config.py` — append to `ALLOWED_CONFIG_KEYS` and add getters (follow the existing pattern for `HEPHAESTUS_*` ints):
`HEPHAESTUS_MERGE_MAX_FILES` (default 40), `HEPHAESTUS_MERGE_MAX_FILE_BYTES` (default 200000), `HEPHAESTUS_MERGE_TIMEOUT_SEC` (default 900). Implement `_over_limits`/`_timeout` in `merge_job.py` to read these.

- [ ] **Step 5: Run — expect PASS**

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/app/models/validation.py backend/tests/unit/test_merge_config.py
git commit -m "feat(epic1): merge config limits + MergeRequest ai/auto fields"
```

---

## Task 9: API endpoints (start job, get, stream, accept, reject)

**Files:**
- Modify: `backend/app/api/v1/merge.py`
- Test: `backend/tests/contract/test_merge_api.py` (extend)

- [ ] **Step 1: Write failing tests** (FastAPI TestClient; patch the runner so no real git/agent runs). Follow `test_merge_api.py` existing style.

```python
# extend backend/tests/contract/test_merge_api.py
def test_start_merge_returns_jobid(client, monkeypatch, active_ws):
    async def fake_start(self, **kw):
        from app.models.merge import MergeJob, MergeJobStatus
        return MergeJob(id="merge-0001", branch=kw["branch"], base_branch="main",
                        status=MergeJobStatus.RESOLVED)
    monkeypatch.setattr("app.core.merge_job.MergeJobRunner.start", fake_start)
    r = client.post("/api/v1/branches/auto%2Fx/merge", json={"push": False})
    assert r.status_code == 200 and r.json()["jobId"] == "merge-0001"


def test_get_merge_job(client, monkeypatch):
    from app.models.merge import MergeJob, MergeJobStatus
    monkeypatch.setattr("app.core.merge_job.MergeJobStore.get",
                        lambda self, jid: MergeJob(id=jid, branch="auto/x",
                                                   base_branch="main", status=MergeJobStatus.RESOLVED))
    r = client.get("/api/v1/merge-jobs/merge-0001")
    assert r.status_code == 200 and r.json()["status"] == "resolved"


def test_second_active_job_conflicts(client, monkeypatch, active_ws):
    from app.models.merge import MergeJob, MergeJobStatus
    monkeypatch.setattr("app.core.merge_job.MergeJobStore.active",
                        lambda self: MergeJob(id="merge-0001", branch="auto/y",
                                              base_branch="main", status=MergeJobStatus.RESOLVING))
    r = client.post("/api/v1/branches/auto%2Fx/merge", json={})
    assert r.status_code == 409
```

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement endpoints** in `merge.py`. Keep `merge_preflight`; change `merge_branch` to start a job, add the four new routes:

```python
@router.post("/api/v1/branches/{name:path}/merge", response_model=None)
async def merge_branch(name: str, body: MergeRequest):
    decoded = _guard(name)
    if decoded is None:
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid branch name"})
    try:
        ws = active_workspace()
    except NoActiveWorkspace as exc:
        return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})
    from app.core.merge_job import MergeJobRunner, MergeJobStore
    from app.core.git import GitService
    if MergeJobStore().active() is not None:
        return JSONResponse(status_code=409, content={"ok": False, "error": "merge already in progress"})
    # reuse existing preflight error contract (loop active / task-not-found / dirty / not-ok)
    pf = GitService(ws).merge_preflight(decoded)
    if GitService(ws)._loop_active():
        return JSONResponse(status_code=409, content={"ok": False, "error": "loop active, stop it before merge"})
    if not pf.ok and not pf.conflicts:
        return JSONResponse(status_code=409, content={"ok": False, "error": "preflight failed",
                            "preflight": pf.model_dump(by_alias=True)})
    runner = MergeJobRunner(ws)
    job = await runner.start(branch=decoded, push=body.push, ai_resolve=body.ai_resolve,
                             auto_accept=body.auto_accept)
    return {"ok": True, "jobId": job.id, "status": job.status.value}


@router.get("/api/v1/merge-jobs/{job_id}", response_model=None)
def get_merge_job(job_id: str):
    from app.core.merge_job import MergeJobStore
    job = MergeJobStore().get(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "job not found"})
    return {"ok": True, **job.model_dump(by_alias=True)}


@router.post("/api/v1/merge-jobs/{job_id}/accept", response_model=None)
async def accept_merge_job(job_id: str, body: MergeRequest):
    try:
        ws = active_workspace()
    except NoActiveWorkspace as exc:
        return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})
    from app.core.merge_job import MergeJobRunner
    res = await MergeJobRunner(ws).accept(job_id, push=body.push)
    return res if res.get("ok") else JSONResponse(status_code=409, content=res)


@router.post("/api/v1/merge-jobs/{job_id}/reject", response_model=None)
async def reject_merge_job(job_id: str):
    try:
        ws = active_workspace()
    except NoActiveWorkspace as exc:
        return JSONResponse(status_code=409, content={"ok": False, "error": str(exc)})
    from app.core.merge_job import MergeJobRunner
    return await MergeJobRunner(ws).reject(job_id)
```

`start()` runs synchronously-awaited here for simplicity (the route is async; resolution may take minutes — acceptable for a deliberate human action and keeps state consistent). If a non-blocking start is later desired, wrap in `asyncio.create_task` and return immediately — out of scope now.

- [ ] **Step 4: Implement the SSE stream route** (copy `iter_stream` from `api/v1/iters.py:85`, change the done-condition to job status):

```python
@router.get("/api/v1/merge-jobs/{job_id}/stream")
async def merge_job_stream(job_id: str, request: Request):
    from app.core.state import _state_dir
    from app.core.events import _summarize_event
    from app.core.merge_job import MergeJobStore
    jp = _state_dir() / job_id / "output.resolve.jsonl"
    terminal = {"resolved", "conflict", "failed", "accepted", "rejected"}

    async def gen():
        idx = 0; offset = 0; buf = b""; idle = 0.0; started = time.monotonic()
        yield ": connected\n\n"
        while True:
            if await request.is_disconnected() or (time.monotonic() - started) > 1800:
                break
            grew = False
            if jp.exists() and jp.stat().st_size > offset:
                with jp.open("rb") as f:
                    f.seek(offset); chunk = f.read()
                offset += len(chunk); buf += chunk
                parts = buf.split(b"\n"); buf = parts.pop()
                for raw in parts:
                    line = raw.strip(); idx += 1
                    if not line: continue
                    try: obj = json.loads(line.decode("utf-8", "replace"))
                    except ValueError: continue
                    yield f"data: {json.dumps(_summarize_event(obj, idx=idx-1), ensure_ascii=False)}\n\n"
                grew = True
            idle = 0.0 if grew else idle + 0.5
            job = MergeJobStore().get(job_id)
            if idle >= 2.0 and (job is None or job.status.value in terminal):
                yield "event: done\ndata: {}\n\n"; break
            if not grew: yield ": keepalive\n\n"
            await asyncio.sleep(0.5)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

Add imports at top of `merge.py`: `import asyncio, json, time`, `from fastapi import Request`, `from fastapi.responses import StreamingResponse`.

- [ ] **Step 5: Run — expect PASS**

Run: `cd backend && python -m pytest tests/contract/test_merge_api.py -v`

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/merge.py backend/tests/contract/test_merge_api.py
git commit -m "feat(epic1): merge-job API (start/get/stream/accept/reject)"
```

---

## Task 10: Reaper wired into startup

**Files:**
- Modify: `backend/app/main.py` (lifespan startup)
- Test: `backend/tests/integration/test_merge_job_flow.py` (reaper test)

- [ ] **Step 1: Write failing test**

```python
def test_reaper_fails_orphaned_job(tmp_path, monkeypatch):
    repo = _conflict_repo(tmp_path); ws = _ws_for(repo, monkeypatch, tmp_path)
    from app.models.merge import MergeJob, MergeJobStatus
    store = MergeJobStore()
    store.put(MergeJob(id="merge-0009", branch="auto/x", base_branch="main",
                       status=MergeJobStatus.RESOLVING, worktree=str(tmp_path / "gone")))
    MergeJobRunner(ws).reap()
    assert store.get("merge-0009").status is MergeJobStatus.FAILED
```

- [ ] **Step 2: Run — expect FAIL** (reaper exists from Task 7; this verifies it; if it already passes, still wire startup below)

- [ ] **Step 3: Call reaper in `main.py` lifespan startup** — after the registry/workspace is available, best-effort:

```python
    try:
        from app.core.workspaces import active_workspace
        from app.core.merge_job import MergeJobRunner
        ws = active_workspace()
        if ws is not None:
            MergeJobRunner(ws).reap()
    except Exception:
        log.debug("merge reaper skipped", exc_info=True)
```

Place it near the existing startup tasks (where `state_broadcaster` is created). Do not block startup on failure.

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/integration/test_merge_job_flow.py
git commit -m "feat(epic1): reap orphaned merge jobs on startup"
```

---

## Task 11: Frontend types + API client

**Files:**
- Modify: `frontend/src/types/api.ts`, `frontend/src/api/client.ts`
- Test: none new (covered via component tests in Task 13)

- [ ] **Step 1: Add types** to `api.ts`:

```ts
export type MergeJobStatus = 'running' | 'resolving' | 'verifying' | 'resolved'
  | 'conflict' | 'failed' | 'accepted' | 'rejected'
export type MergeDecision = 'auto_merged' | 'ai_merged' | 'needs_human' | 'failed'
export interface MergeJob {
  id: string; branch: string; baseBranch: string; status: MergeJobStatus
  decision?: MergeDecision | null; conflicts: string[]; resolvedFiles: string[]
  diff?: string | null; verifyOk?: boolean | null; error?: string | null
  worktreeBranch?: string | null; itemId?: string | null
}
```
Add `mergeResolution?: 'auto' | 'ai' | 'manual'` to the `Item` interface.

- [ ] **Step 2: Add client methods** to `client.ts` (follow existing `merge`/`mergePreflight` patterns):

```ts
startMerge: (branch: string, opts: { push?: boolean; aiResolve?: boolean; autoAccept?: boolean }) =>
  post<{ ok: boolean; jobId: string; status: MergeJobStatus }>(
    `/api/v1/branches/${encodeURIComponent(branch)}/merge`, opts),
getMergeJob: (jobId: string) => get<MergeJob & { ok: boolean }>(`/api/v1/merge-jobs/${jobId}`),
acceptMerge: (jobId: string, push: boolean) =>
  post<{ ok: boolean; error?: string }>(`/api/v1/merge-jobs/${jobId}/accept`, { push }),
rejectMerge: (jobId: string) => post<{ ok: boolean }>(`/api/v1/merge-jobs/${jobId}/reject`, {}),
```
Match the actual helper names used in `client.ts` (`get`/`post` wrappers) — read the file first and mirror them.

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run build` (or `vue-tsc --noEmit`)
Expected: no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/api/client.ts
git commit -m "feat(epic1): frontend MergeJob types + api client methods"
```

---

## Task 12: LiveConsole streamUrl prop

**Files:**
- Modify: `frontend/src/components/LiveConsole.vue`
- Test: existing tests must still pass

- [ ] **Step 1: Add optional `streamUrl` prop** and use it when present:

```ts
const props = defineProps<{
  iterDir: string | null
  stream?: string
  active: boolean
  streamUrl?: string   // override; when set, used instead of the iter URL
}>()
```
In `connect()` replace the URL line:
```ts
const url = props.streamUrl
  ?? `/api/iter/${encodeURIComponent(props.iterDir)}/stream?stream=${props.stream ?? 'primary'}`
```
When `streamUrl` is set, gate on `props.active` only (not `iterDir`): adjust the `watch` and the early-return in `connect()` so a non-null `streamUrl` is sufficient to connect.

- [ ] **Step 2: Run existing LiveConsole/RunningView tests**

Run: `cd frontend && npx vitest run src/components/__tests__`
Expected: PASS (no regressions).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/LiveConsole.vue
git commit -m "feat(epic1): LiveConsole optional streamUrl prop"
```

---

## Task 13: MergeJobPanel + MergeButton wiring

**Files:**
- Create: `frontend/src/components/MergeJobPanel.vue`
- Modify: `frontend/src/components/MergeButton.vue`
- Test: `frontend/src/components/__tests__/MergeJobPanel.spec.ts`, extend `MergeButton.spec.ts`

- [ ] **Step 1: Write failing component test** (mount panel with a mocked `getMergeJob` returning RESOLVED + diff; assert Accept/Reject render and call client). Mirror `MergeButton.spec.ts` mocking of `@/api/client`.

```ts
// frontend/src/components/__tests__/MergeJobPanel.spec.ts
import { mount, flushPromises } from '@vue/test-utils'
import { vi, describe, it, expect } from 'vitest'
import MergeJobPanel from '../MergeJobPanel.vue'

vi.mock('@/api/client', () => ({ api: {
  getMergeJob: vi.fn().mockResolvedValue({ ok: true, id: 'merge-0001', branch: 'auto/x',
    baseBranch: 'main', status: 'resolved', decision: 'ai_merged', conflicts: ['f.txt'],
    resolvedFiles: ['f.txt'], diff: 'diff --git a/f b/f', verifyOk: true }),
  acceptMerge: vi.fn().mockResolvedValue({ ok: true }),
  rejectMerge: vi.fn().mockResolvedValue({ ok: true }),
}}))

describe('MergeJobPanel', () => {
  it('shows resolved diff and Accept/Reject', async () => {
    const w = mount(MergeJobPanel, { props: { jobId: 'merge-0001' } })
    await flushPromises()
    expect(w.text()).toContain('diff --git')
    expect(w.find('[data-test="accept-merge"]').exists()).toBe(true)
    expect(w.find('[data-test="reject-merge"]').exists()).toBe(true)
  })
  it('calls acceptMerge on Accept click', async () => {
    const { api } = await import('@/api/client')
    const w = mount(MergeJobPanel, { props: { jobId: 'merge-0001' } })
    await flushPromises()
    await w.find('[data-test="accept-merge"]').trigger('click')
    expect(api.acceptMerge).toHaveBeenCalledWith('merge-0001', false)
  })
})
```

- [ ] **Step 2: Run — expect FAIL** (component missing)

Run: `cd frontend && npx vitest run src/components/__tests__/MergeJobPanel.spec.ts`

- [ ] **Step 3: Implement `MergeJobPanel.vue`**

Behavior: poll `api.getMergeJob(jobId)` every ~1s until terminal; render the status pill + `<LiveConsole :active="true" :stream-url="'/api/v1/merge-jobs/'+jobId+'/stream'" :iter-dir="null" />`; when `status==='resolved'` show `<pre>` of `job.diff` + push toggle + `Accept` (`data-test="accept-merge"`, calls `api.acceptMerge(jobId, push)`) and `Reject` (`data-test="reject-merge"`, calls `api.rejectMerge(jobId)`); on `accepted` `emit('merged')`; on `failed`/`conflict` show `error`/`conflicts` + manual-resolve hint. Props: `{ jobId: string }`, emits `{ merged: [] }`.

- [ ] **Step 4: Wire `MergeButton.vue`** — `doMerge()` now calls `api.startMerge(branch, { push, aiResolve: true, autoAccept: false })`, stores the returned `jobId`, and renders `<MergeJobPanel :job-id="jobId" @merged="emit('merged')" />`. Keep the old `conflict-modal` only as the fallback shown when a job returns `status === 'conflict'` (decision needs_human). Update `MergeButton.spec.ts` expectations accordingly (startMerge instead of merge).

- [ ] **Step 5: Run — expect PASS**

Run: `cd frontend && npx vitest run src/components/__tests__`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/MergeJobPanel.vue frontend/src/components/MergeButton.vue frontend/src/components/__tests__/
git commit -m "feat(epic1): MergeJobPanel live+diff+accept/reject, wire MergeButton"
```

---

## Task 14: Full suite + cross-platform sanity

**Files:** none (verification)

- [ ] **Step 1: Backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all green (new + existing). Fix any regression before proceeding.

- [ ] **Step 2: Frontend suite + build**

Run: `cd frontend && npx vitest run && npm run build`
Expected: tests pass, build succeeds.

- [ ] **Step 3: Lint/type (match project verify)**

Run the workspace verify commands (`.hephaestus/memory/verify.md` or `ruff`/`mypy`/`vue-tsc` as configured). Expected: clean.

- [ ] **Step 4: Commit any fixups**

```bash
git add -A && git commit -m "test(epic1): full suite green for AI-powered merge"
```

---

## Self-Review checklist (already applied during authoring)

- **Spec coverage:** §2 models→T1/T8; §3 persist/seq→T3; §4 runner flow→T6/T7; §5 resolver→T2/T5; §6 API+SSE→T9; §7 safety (worktree isolation, marker post-check, verify gate, limits, single-active-job, loop guard, push-before-delete)→T6/T7/T8/T9; §8 frontend→T11/T12/T13; §9 testing→every task TDD.
- **Open item carried forward:** the agent's JSONL is streamed by tailing `output.resolve.jsonl` over the dedicated SSE route (T9 step 4), NOT the unused `iter:` WS room — confirmed against `iters.py`/`LiveConsole.vue`.
- **Type consistency:** `MergeJob`/`MergeJobStatus`/`MergeDecision` names identical across backend (T1) and frontend (T11); `startMerge/getMergeJob/acceptMerge/rejectMerge` consistent T11↔T13; `run_agent`/`verify` injection points consistent T5↔T6.
