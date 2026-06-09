# ARCH-001 — FSM Phase Decomposition (BEHAVIOR-PRESERVING)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Extract 7 phase bodies (`_preflight`, `_run_opencode`/`_run_opencode_with_retry`, `_verify`, `_commit`, `_parse_result`, `_validate`, `_cleanup`) from `backend/app/orchestrator/fsm.py` (1190 lines) into a new `app/orchestrator/phases/` package — STRICTLY preserving behavior bit-for-bit. fsm.py keeps all control flow (`run`/`_run_parallel`/`_process_item`/`_set_phase`/`_recover_checkpoint`/`_TRANSITIONS`/state mutators) and becomes a thin driver delegating to phase functions.

**Architecture:** Each phase becomes a module-level `async def <name>_phase(fsm: OrchestratorFSM, ...)` function in `app/orchestrator/phases/<name>.py`. The FSM method on the class becomes a one-line delegate: `return await <name>_phase(self, item)`. This is zero-semantic-risk because (a) the FSM `self` is passed verbatim, (b) all attribute access and mutation lives in the same instance, (c) no module-level state changes, (d) signatures are unchanged. Lazy imports (TYPE_CHECKING for the FSM type to avoid circular imports) match the project's existing style.

**Tech Stack:** Python 3.12, mypy --strict, ruff, pytest. Backend venv at `backend/.venv` (uv-managed).

**Constraints (HARD):**
- ZERO existing test changes. If a test needs editing, you changed behavior — STOP.
- Public surface unchanged: `OrchestratorFSM`, `Phase`, `_TRANSITIONS`, `_snapshot_revision`, `build_task_prompt`, `get_working_dir`, `drop_worktree`, `restore_base_branch`, `replenish_goal` all importable from `app.orchestrator.fsm` exactly as before.
- One phase per commit; full gates (pytest + mypy --strict + ruff) green after every commit.
- Self-referential repo: this work is being done by a human (me) on the repo; no HEPHAESTUS task should be triggered during it. Commit before any push.

---

## File Structure

**Create:**
- `backend/app/orchestrator/phases/__init__.py` — package marker (empty or just docstring)
- `backend/app/orchestrator/phases/cleanup.py` — `cleanup_phase(fsm, item)`
- `backend/app/orchestrator/phases/parse_result.py` — `parse_result_phase(fsm, item)`
- `backend/app/orchestrator/phases/commit.py` — `commit_phase(fsm, item)`
- `backend/app/orchestrator/phases/verify.py` — `verify_phase(fsm, item)`
- `backend/app/orchestrator/phases/opencode.py` — `run_opencode(fsm, item, prompt)` + `run_opencode_with_retry(fsm, item, prompt)`
- `backend/app/orchestrator/phases/preflight.py` — `preflight_phase(fsm, item)`
- `backend/app/orchestrator/phases/validate.py` — `validate_phase(fsm, item, ws, revision)`

**Modify:**
- `backend/app/orchestrator/fsm.py` — phase methods become 1-2 line delegates; everything else (control flow, transitions, checkpoint/recovery, state mutators, helpers) unchanged.

**Untouched:**
- Existing extracted helpers (`git_ops.py`, `prompt_builder.py`, `revision_snapshot.py`) — already done in earlier work.
- All tests (no test file edited).
- Frontend.

---

## Task 1: Create phases package

**Files:**
- Create: `backend/app/orchestrator/phases/__init__.py`

- [ ] **Step 1: Create __init__.py**

```python
"""FSM phase handlers — bodies of the per-item pipeline phases extracted from fsm.py.

Each phase is a module-level function that takes the FSM instance as its first
argument. This keeps the FSM's `self` as the single source of state (worktree,
iter_dir, intermediate_results, current_item, workspace) so behavior is
identical to having the body inline on the class. The FSM methods on
``OrchestratorFSM`` are kept as thin delegates so their signatures remain stable
for existing tests.
"""

from __future__ import annotations
```

- [ ] **Step 2: Gate check**

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/unit/test_fsm.py tests/unit/test_fsm_recovery.py -q
.venv/Scripts/python.exe -m ruff check app tests
.venv/Scripts/python.exe -m mypy --strict app/
```

Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add backend/app/orchestrator/phases/__init__.py
git commit -m "ARCH-001(1/8): create app/orchestrator/phases/ package"
```

---

## Task 2: Extract _cleanup → phases/cleanup.py

The simplest phase — 15 lines. No early returns. Mutates `fsm._worktree`, `fsm.current_item`, `fsm.iter_dir`, deletes checkpoint file.

**Files:**
- Create: `backend/app/orchestrator/phases/cleanup.py`
- Modify: `backend/app/orchestrator/fsm.py` (1132-1147)

- [ ] **Step 1: Create cleanup.py**

```python
"""CLEANUP phase — final per-item teardown after successful validation."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.orchestrator.fsm import OrchestratorFSM


async def cleanup_phase(fsm: OrchestratorFSM, item: dict[str, Any]) -> None:
    """Clean up after iteration."""
    from app.core.helpers import _run
    from app.core.workspaces import registry

    branch = item.get("branch")
    if branch and fsm._ws is not None and fsm._ws.autopush:
        _run(["git", "push", fsm._ws.remote, branch], cwd=fsm._get_repo())
    # Drop the isolated worktree (the branch stays for review/merge).
    fsm._drop_worktree()
    if fsm._ws is not None:
        cp_path = registry.state_dir(fsm._ws) / "fsm-checkpoint.json"
        with contextlib.suppress(Exception):
            cp_path.unlink(missing_ok=True)
    fsm.current_item = None
    fsm.iter_dir = None
```

- [ ] **Step 2: Replace _cleanup in fsm.py with delegate**

```python
async def _cleanup(self, item: dict[str, Any]) -> None:
    """Clean up after iteration."""
    from app.orchestrator.phases.cleanup import cleanup_phase
    await cleanup_phase(self, item)
```

- [ ] **Step 3: Gate**

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check app tests
.venv/Scripts/python.exe -m mypy --strict app/
```

Expected: full suite green, mypy clean, ruff clean.

- [ ] **Step 4: Commit**

```bash
git add backend/app/orchestrator/phases/cleanup.py backend/app/orchestrator/fsm.py
git commit -m "ARCH-001(2/8): extract _cleanup -> phases/cleanup.py"
```

---

## Task 3: Extract _parse_result → phases/parse_result.py

**Files:**
- Create: `backend/app/orchestrator/phases/parse_result.py`
- Modify: `backend/app/orchestrator/fsm.py` (915-969)

Body has nested try/except + diff.patch + summary.md. Direct copy of body, replace `self.` with `fsm.`.

- [ ] **Step 1: Create parse_result.py** (full body — see implementation)
- [ ] **Step 2: Replace in fsm.py with delegate**
- [ ] **Step 3: Gate (full pytest + mypy + ruff)**
- [ ] **Step 4: Commit `ARCH-001(3/8): extract _parse_result -> phases/parse_result.py`**

---

## Task 4: Extract _commit → phases/commit.py

**Files:**
- Create: `backend/app/orchestrator/phases/commit.py`
- Modify: `backend/app/orchestrator/fsm.py` (876-913)

Includes `fsm._intermediate_results["commit"] = head_sha` (REL-003 critical).

- [ ] **Step 1: Create commit.py**
- [ ] **Step 2: Delegate**
- [ ] **Step 3: Gate**
- [ ] **Step 4: Commit `ARCH-001(4/8): extract _commit -> phases/commit.py`**

---

## Task 5: Extract _verify → phases/verify.py

**Files:**
- Create: `backend/app/orchestrator/phases/verify.py`
- Modify: `backend/app/orchestrator/fsm.py` (831-874)

Returns `VerifyOutcome`. Critical: identical detail strings and unverified semantics.

- [ ] **Step 1: Create verify.py**
- [ ] **Step 2: Delegate**
- [ ] **Step 3: Gate**
- [ ] **Step 4: Commit `ARCH-001(5/8): extract _verify -> phases/verify.py`**

---

## Task 6: Extract _run_opencode + _run_opencode_with_retry → phases/opencode.py

**Files:**
- Create: `backend/app/orchestrator/phases/opencode.py`
- Modify: `backend/app/orchestrator/fsm.py` (754-829)

Both go in one module since the retry wraps the single-shot. Preserves the `modelOverride` AgentRef path and the transient retry classifier + backoff.

- [ ] **Step 1: Create opencode.py** with both functions
- [ ] **Step 2: Delegates for _run_opencode and _run_opencode_with_retry**
- [ ] **Step 3: Gate**
- [ ] **Step 4: Commit `ARCH-001(6/8): extract _run_opencode(+retry) -> phases/opencode.py`**

---

## Task 7: Extract _preflight → phases/preflight.py

**Files:**
- Create: `backend/app/orchestrator/phases/preflight.py`
- Modify: `backend/app/orchestrator/fsm.py` (689-748)

Branches on `fsm._parallel` (worktree path) vs sequential (`git checkout -b`). Atomic iter-dir claim loop. Sets `fsm._worktree` and `fsm.iter_dir`.

- [ ] **Step 1: Create preflight.py**
- [ ] **Step 2: Delegate**
- [ ] **Step 3: Gate**
- [ ] **Step 4: Commit `ARCH-001(7/8): extract _preflight -> phases/preflight.py`**

---

## Task 8: Extract _validate → phases/validate.py

**Files:**
- Create: `backend/app/orchestrator/phases/validate.py`
- Modify: `backend/app/orchestrator/fsm.py` (971-1005)

Delegates to ValidationFunnel. Uses `cast` to satisfy the Protocol.

- [ ] **Step 1: Create validate.py**
- [ ] **Step 2: Delegate**
- [ ] **Step 3: Gate**
- [ ] **Step 4: Commit `ARCH-001(8/8): extract _validate -> phases/validate.py`**

---

## Task 9: Final gates + audit update + merge

- [ ] **Step 1: Full pytest run**

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q
```

Expected: all green, no skips/xfails that weren't there before.

- [ ] **Step 2: mypy strict + ruff**

```bash
.venv/Scripts/python.exe -m mypy --strict app/
.venv/Scripts/python.exe -m ruff check app tests
```

Expected: clean.

- [ ] **Step 3: Verify no test files were modified**

```bash
git diff master -- backend/tests/
```

Expected: empty.

- [ ] **Step 4: Record new fsm.py line count**

```bash
wc -l backend/app/orchestrator/fsm.py backend/app/orchestrator/phases/*.py
```

- [ ] **Step 5: Update audit doc**

Edit `docs/reviews/2026-06-08-improvement-audit.md`: under Phase 3/4 progress lines for ARCH-001, mark as fully decomposed with new line counts.

- [ ] **Step 6: Merge + push**

```bash
git checkout master
git merge --no-ff arch-001-fsm-phase-decomposition -m "merge: ARCH-001 — FSM phase decomposition (behavior-preserving)"
git push origin master
```

---

## Self-Review

**Spec coverage:** all 7 phase bodies have an extraction task; control flow + transitions + checkpoint logic + state mutators stay in fsm.py; all tests stay unchanged.

**Risk controls:** one phase per commit, full gates between each; rollback = `git reset HEAD~1`. No test edits anywhere — the hardest gate.

**Deferred (not in scope):** generic enter/exit/recover driver via registry; combining with other audit findings; the wider Phase 6 stage cleanup.
