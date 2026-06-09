# Этап 1 — Универсализация + кроссплатформенный движок (фундамент) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Превратить bash/tmux-центричный HEPHAESTUS-loop над одним хардкод-репозиторием в кроссплатформенный нативный Python: ввести `Workspace`/`RepoProfile` + реестр воркспейсов, заменить tmux/`pgrep`/`pkill` на `ProcessManager`, `verify.sh` на `VerifyRunner`, обернуть `opencode run` в `AgentRunner`, де-HEPHAESTUS-ифицировать `config.py`, добавить Profiler-онбординг с памятью `<repo>/.hephaestus/memory/*.md`, мигрировать `state/` в Workspace-структуру и удалить bash/tmux/legacy-dashboard. Покрывает D1, D2, D4, D6, D7, D8, D9; готовит точки расширения под D5/D10/D11 (Этапы 2/3).

**Architecture:** FastAPI backend (`backend/app/`) с кроссплатформенным движком из четырёх интерфейсов — `ProcessManager` (`core/process.py`), `AgentRunner` (`services/opencode_runner.py`), `VerifyRunner` (`core/verify.py`), `GitService` (`core/git.py`). Доменная модель — `RepoProfile`/`AgentsConfig`/`AgentRef`/`ReviewConfig`/`VerifySource` (`models/workspace.py`), эволюция `Item` → `Task` (`models/domain.py`). Реестр воркспейсов (`core/workspaces.py`) под `hephaestus_home()` (`services/hephaestus_home.py`); память внутри репо через `ProjectMemory` (`services/project_memory.py`); онбординг через `Profiler` (`services/profiler.py`). Все движковые вызовы принимают `ws: RepoProfile` явно (umbrella §10.1). Серилизация — camelCase через Pydantic-алиасы; ответы `{ok|error}`. Frontend — Vue 3 / Pinia: новый `useWorkspaceStore`, `OnboardView`, `SettingsView`, `WorkspaceSwitcher`; `LoopStatus.tmux` → `process: ProcessManagerStatus`.

**Tech Stack:** Python 3.11+ (stdlib only для движка: asyncio, subprocess, signal, os, shlex, pathlib, msvcrt/fcntl, hashlib, re), FastAPI ^0.115, Pydantic ^2.11, pydantic-settings ^2.9, pytest ^8.3 + pytest-asyncio ^0.25, ruff, mypy --strict. Frontend: Vue 3, Pinia, Vue Router, TypeScript (vue-tsc), Vitest. CI matrix: ubuntu-latest + windows-latest. Внешнее (не пины): `opencode` CLI + ключи провайдеров, `git` на PATH. Новых runtime-зависимостей нет; YAML-frontmatter парсится regex без pyyaml.

---

## File Structure

### Новые файлы (backend)

| Путь | Ответственность |
|---|---|
| `backend/app/services/hephaestus_home.py` | `hephaestus_home()` — путь реестра (`~/.hephaestus` или `HEPHAESTUS_HOME`). Единая точка для путей вне репо. |
| `backend/app/models/workspace.py` | `VerifySource`, `AgentRef`, `AgentsConfig`, `ReviewConfig`, `RepoProfile` (umbrella §4.1). |
| `backend/app/core/process.py` | `ProcState`, `ProcessHandle`, `ProcessManager` + singleton `pm` (D1). Кроссплатформенный пуск/стоп/статус/cancel именованных сессий. |
| `backend/app/services/opencode_runner.py` | `AgentResult`, `AgentRunner` (D2). Обёртка `opencode run` через `ProcessManager`. |
| `backend/app/core/verify.py` | `VerifyResult`, `VerifyRunner` (D4). Verify-команды из памяти/override, кроссплатформенно. |
| `backend/app/services/project_memory.py` | `ProjectMemory` (D6). Чтение/запись `<repo>/.hephaestus/memory/*.md` с frontmatter. |
| `backend/app/services/profiler.py` | `ProfilerOutput`, `Profiler` (D4+D6). Онбординг-агент. |
| `backend/app/core/workspaces.py` | `WorkspaceRegistry` + singleton `registry` (D9). CRUD реестра, активный воркспейс, разрешение путей. |
| `backend/app/core/migrate.py` | `migrate_legacy_state()` — идемпотентная миграция `state/` -> `workspaces/<id>/state/`. |
| `backend/app/api/v1/workspaces.py` | Роутер list/create(onboard)/get/update/activate. |
| `prompts/profiler.md` | Промпт Profiler-агента (контракт вывода — §4.6 спеки). |

### Модифицируемые файлы (backend)

| Путь | Изменение |
|---|---|
| `backend/app/config.py` | Убрать хардкод `REPO=/home/starsinc/hephaestus-repo`; убрать vendor-дефолты в `_config_effective`; добавить ключи в `ALLOWED_CONFIG_KEYS`. |
| `backend/app/core/state.py` | `STATE_DIR` ws-scoped (`_state_dir()`); `_StateLock` кроссплатформенный (msvcrt/fcntl); сигнатуры `_read_state`/`_write_state`/`_atomic_write` неизменны. |
| `backend/app/core/driver.py` | Переписать `_loop_status`/`_start_loop`/`_stop_loop_soft`/`_kill_loop_hard` поверх `ProcessManager`; удалить tmux/pgrep/pkill. |
| `backend/app/core/scan.py` | `_scan_start`/`_scan_running` через `pm.start(name="scan", ...)` (стаб-orchestrator); `_scan_*` ws-scoped. |
| `backend/app/core/git.py` | Добавить `GitService(ws)` + `MergePreflight`; существующие функции и `BRANCH_ACTIONS` сохраняются для legacy-роутера. |
| `backend/app/core/iters.py` | `_loop_status()`/cleanup — убрать `_tmux_has`, читать `pm.status("loop")`. |
| `backend/app/orchestrator/fsm.py` | `_run_opencode` -> `AgentRunner.run_with_fallback`; `_verify` -> `VerifyRunner`; `_preflight`/`_commit`/`_cleanup`/`_get_repo` читают `ws`. |
| `backend/app/orchestrator/main.py` | signal-handling уже Windows-safe; `OrchestratorFSM` сам разрешает `HEPHAESTUS_WORKSPACE_ID` (Task 14). |
| `backend/app/services/doc_reader.py` | Использовать ws-scoped `repo_path` (конструктор уже принимает). |
| `backend/app/main.py` | Startup-check убрать `tmux`; shutdown `pm.cancel_all()`; зарегистрировать `workspaces_router`; вызвать `migrate_legacy_state()` в lifespan. |
| `backend/app/api/v1/loop.py` | Без изменений сигнатур; `_start_loop`/`_stop_loop_soft`/`_kill_loop_hard` теперь ProcessManager-обёртки (Task 12). |
| `backend/app/models/requests.py` | Добавить `OnboardRequest`, `WorkspaceUpdateRequest`. |
| `backend/app/models/domain.py` | Добавить поля `Task` (`workspace_id`, `depends_on`, `order_index`, …). |

### Новые/модифицируемые файлы (frontend)

| Путь | Изменение |
|---|---|
| `frontend/src/types/api.ts` | Добавить `ProcessManagerStatus`, `AgentRef`, `RepoProfile`; `LoopStatus.tmux` -> `process`. |
| `frontend/src/stores/workspace.ts` (новый) | `useWorkspaceStore`. |
| `frontend/src/stores/loop.ts` | `status` дефолт `{process:{...}}`; `pollLoop` читает `state.loopStatus.process`. |
| `frontend/src/views/OnboardView.vue` (новый) | Wizard онбординга. |
| `frontend/src/views/SettingsView.vue` (новый) | Настройки воркспейса. |
| `frontend/src/components/WorkspaceSwitcher.vue` (новый) | Переключатель активного воркспейса. |
| `frontend/src/router.ts` | Роуты `/onboard`, `/settings`. |
| `frontend/src/components/AppShell.vue` | `WorkspaceSwitcher`; `loopRunning = status.process.state === 'running'`. |
| `frontend/src/api/client.ts` | Методы `listWorkspaces`/`onboard`/`getWorkspace`/`updateWorkspace`/`activateWorkspace`. |

### Удаляемые файлы (последний коммит этапа, D1/D7)

`driver.sh`, `start-loop.sh`, `verify.sh`, `tier-review.sh`, `repo-scan.sh`, `prompt-build.sh`, `lib/common.sh`, `config.env`, `dashboard/`. Bash-зависимый `backend/tests/contract/test_lock_contract.py` переписывается под чистый Python.

### Раскладка тестов

`backend/tests/unit/{test_process_manager,test_verify_runner,test_workspace_registry,test_project_memory,test_agent_runner_cmd,test_profiler_parse,test_config_dehephaestus,test_hephaestus_home,test_git_service}.py`; `backend/tests/contract/{test_workspace_schema,test_loopstatus_shape,test_migrate_idempotent,test_lock_contract}.py`; `backend/tests/integration/{test_onboard_flow,test_loop_start_stop,test_verify_from_memory}.py`.

---

## Соответствие имён umbrella/спеке

Перед стартом сверь — все идентификаторы дословно из спеки/umbrella: `ProcState{IDLE,RUNNING,STOPPING,EXITED}`, `ProcessHandle{name,pid,state,started_at_ms,exit_code,children}`, `ProcessManager.{start,stop,status,list,cancel,cancel_all}`, `AgentResult{exit_code,refused,output_path,agent_label}`, `AgentRunner.{_build_cmd,run,run_with_fallback}`, `VerifyResult{ok,ran,failed_command,log_path}`, `VerifyRunner.{resolve_commands,run}`, `RepoProfile`-поля (`repo_path/repoPath`, `base_branch/baseBranch`, `verify_source/verifySource`, `verify_commands_override/verifyCommandsOverride`, `memory_dir/memoryDir`), `WorkspaceRegistry.{list,get,create,update,activate,active,state_dir,memory_dir,ws_id_for}`, `ProjectMemory.{ensure_dir,write_doc,read_doc,read_verify_commands,bootstrap_index}`, `Profiler.onboard`, `ProfilerOutput`, `migrate_legacy_state`, `MergePreflight`, `GitService`.

---

## Task 1: hephaestus_home() — единая точка путей реестра

- [ ] Создать падающий тест `backend/tests/unit/test_hephaestus_home.py`:

```python
"""Unit: hephaestus_home() resolves registry root cross-platform."""
from __future__ import annotations

import pathlib

import pytest


def test_hephaestus_home_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEPHAESTUS_HOME", raising=False)
    from app.services.hephaestus_home import hephaestus_home

    h = hephaestus_home()
    assert isinstance(h, pathlib.Path)
    assert h.name == ".hephaestus"
    assert h == pathlib.Path.home() / ".hephaestus"


def test_hephaestus_home_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    monkeypatch.setenv("HEPHAESTUS_HOME", str(tmp_path / "reg"))
    from app.services.hephaestus_home import hephaestus_home

    assert hephaestus_home() == (tmp_path / "reg")
```

- [ ] Запустить — ожидается FAIL (модуля нет):

```
cd backend && python -m pytest tests/unit/test_hephaestus_home.py -x
```
Ожидаемый вывод: `ModuleNotFoundError: No module named 'app.services.hephaestus_home'`.

- [ ] Создать `backend/app/services/hephaestus_home.py`:

```python
"""Registry root resolution — single source for paths OUTSIDE any repo."""
from __future__ import annotations

import os
import pathlib


def hephaestus_home() -> pathlib.Path:
    """Return the HEPHAESTUS registry root: $HEPHAESTUS_HOME or ~/.hephaestus."""
    env = os.environ.get("HEPHAESTUS_HOME")
    if env:
        return pathlib.Path(env)
    return pathlib.Path.home() / ".hephaestus"
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/unit/test_hephaestus_home.py -x
```
Ожидаемый вывод: `2 passed`.

- [ ] Commit:

```
git add backend/app/services/hephaestus_home.py backend/tests/unit/test_hephaestus_home.py && git commit -m "feat(stage1): add hephaestus_home() registry-root resolver"
```

---

## Task 2: RepoProfile + Agents/Review/VerifySource доменные типы

- [ ] Создать падающий тест `backend/tests/contract/test_workspace_schema.py`:

```python
"""Contract: RepoProfile round-trips camelCase aliases."""
from __future__ import annotations


def test_repoprofile_round_trip() -> None:
    from app.models.workspace import AgentRef, RepoProfile, VerifySource

    payload = {
        "id": "9f3a1c20e4b57d61",
        "name": "demo",
        "repoPath": "/tmp/demo",
        "baseBranch": "main",
        "branchPrefix": "auto",
        "agents": {
            "useModels": True,
            "primary": {"provider": "anthropic", "model": "claude-opus-4-8"},
            "fallback": {"provider": "openai", "model": "gpt-4.1"},
        },
        "verifySource": "agent",
        "verifyCommandsOverride": [],
    }
    ws = RepoProfile.model_validate(payload)
    assert ws.repo_path == "/tmp/demo"
    assert ws.base_branch == "main"
    assert ws.verify_source is VerifySource.AGENT
    assert ws.agents.use_models is True
    assert isinstance(ws.agents.primary, AgentRef)

    dumped = ws.model_dump(by_alias=True)
    assert dumped["repoPath"] == "/tmp/demo"
    assert dumped["verifySource"] == "agent"
    assert dumped["memoryDir"] == ".hephaestus/memory"


def test_agentsconfig_defaults() -> None:
    from app.models.workspace import AgentsConfig, AgentRef

    cfg = AgentsConfig(
        primary=AgentRef(provider="anthropic", model="claude-opus-4-8"),
        fallback=AgentRef(provider="openai", model="gpt-4.1"),
    )
    assert cfg.use_models is False
    assert cfg.validators == []
    assert cfg.final is None
```

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/contract/test_workspace_schema.py -x
```
Ожидаемый вывод: `ModuleNotFoundError: No module named 'app.models.workspace'`.

- [ ] Создать `backend/app/models/workspace.py` (дословно по umbrella §4.1):

```python
"""Workspace domain model — RepoProfile + agent/review config (umbrella §4.1)."""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class VerifySource(StrEnum):
    AGENT = "agent"      # команды определены Profiler'ом -> .hephaestus/memory/verify.md
    MANUAL = "manual"    # пользователь задал override в настройках


class AgentRef(BaseModel):
    """opencode provider/model/agent triple. 'agent' опционален."""
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


class ReviewConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    enabled: bool = True
    tier1_threshold: int = Field(5, alias="tier1Threshold")
    tier2_threshold: int = Field(2, alias="tier2Threshold")
    max_revisions: int = Field(2, alias="maxRevisions")


class RepoProfile(BaseModel):
    """Workspace == RepoProfile + runtime paths."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    name: str
    repo_path: str = Field(..., alias="repoPath")
    base_branch: str = Field("main", alias="baseBranch")
    remote: str = "origin"
    branch_prefix: str = Field("auto", alias="branchPrefix")

    agents: AgentsConfig
    strictness: str = "standard"
    review: ReviewConfig = ReviewConfig()

    verify_source: VerifySource = Field(VerifySource.AGENT, alias="verifySource")
    verify_commands_override: list[str] = Field([], alias="verifyCommandsOverride")
    verify_timeout_sec: int = Field(900, alias="verifyTimeoutSec")

    memory_dir: str = Field(".hephaestus/memory", alias="memoryDir")
    autopush: bool = False
    autopush_remote: str = Field("origin", alias="autopushRemote")

    created_at: str | None = Field(None, alias="createdAt")
    onboarded: bool = False
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/contract/test_workspace_schema.py -x
```
Ожидаемый вывод: `2 passed`.

- [ ] Commit:

```
git add backend/app/models/workspace.py backend/tests/contract/test_workspace_schema.py && git commit -m "feat(stage1): add RepoProfile / AgentsConfig / VerifySource domain model"
```

---

## Task 3: ProcessManager — кроссплатформенный пуск/стоп/cancel (без tmux)

- [ ] Создать падающий тест `backend/tests/unit/test_process_manager.py` (синхронный — `pm` sync PID-based, R1):

```python
"""Unit: ProcessManager — sync PID-based start/status/stop/cancel (no tmux, no asyncio)."""
from __future__ import annotations

import sys

import pytest


def test_start_status_running(tmp_path) -> None:
    from app.core.process import ProcessManager, ProcState

    pm = ProcessManager(state_dir=tmp_path)
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    h = pm.start("loop", cmd, cwd=str(tmp_path), env={})
    assert h.state is ProcState.RUNNING
    assert h.pid is not None
    st = pm.status("loop")
    assert st.state is ProcState.RUNNING
    pm.cancel("loop")


def test_double_start_raises(tmp_path) -> None:
    from app.core.process import ProcessManager

    pm = ProcessManager(state_dir=tmp_path)
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    pm.start("loop", cmd, cwd=str(tmp_path), env={})
    with pytest.raises(ValueError, match="already running"):
        pm.start("loop", cmd, cwd=str(tmp_path), env={})
    pm.cancel("loop")


def test_cancel_terminates_under_5s(tmp_path) -> None:
    import time as _t

    from app.core.process import ProcessManager, ProcState

    pm = ProcessManager(state_dir=tmp_path)
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    pm.start("loop", cmd, cwd=str(tmp_path), env={})
    t0 = _t.monotonic()
    h = pm.cancel("loop")
    assert _t.monotonic() - t0 < 5.0
    assert h.state is ProcState.EXITED


def test_cancel_all_clears(tmp_path) -> None:
    from app.core.process import ProcessManager, ProcState

    pm = ProcessManager(state_dir=tmp_path)
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    pm.start("loop", cmd, cwd=str(tmp_path), env={})
    pm.start("scan", cmd, cwd=str(tmp_path), env={})
    pm.cancel_all()
    assert pm.status("loop").state in (ProcState.EXITED, ProcState.IDLE)
    assert pm.status("scan").state in (ProcState.EXITED, ProcState.IDLE)


def test_status_idle_for_unknown(tmp_path) -> None:
    from app.core.process import ProcessManager, ProcState

    pm = ProcessManager(state_dir=tmp_path)
    st = pm.status("never-started")
    assert st.state is ProcState.IDLE
    assert st.pid is None


def test_status_recovers_from_process_json(tmp_path) -> None:
    """A fresh manager reads state/process.json to detect a live PID (R1)."""
    import subprocess

    from app.core.process import ProcessManager, ProcState

    pm = ProcessManager(state_dir=tmp_path)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        pm._persist("loop", proc.pid, [])  # type: ignore[attr-defined]
        pm2 = ProcessManager(state_dir=tmp_path)
        assert pm2.status("loop").state is ProcState.RUNNING
    finally:
        proc.kill()
        proc.wait()
```

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/unit/test_process_manager.py -x
```
Ожидаемый вывод: `ModuleNotFoundError: No module named 'app.core.process'`.

- [ ] Создать `backend/app/core/process.py` (**синхронный PID-based** менеджер: `subprocess.Popen`, `threading.Lock`, sync `start/stop/status/cancel`, liveness через `os.kill(pid,0)`, PID-дерево в `state/process.json` — R1, R9):

```python
"""ProcessManager — sync PID-based supervisor of long-lived child processes (D1, R1).

Supervises ONLY top-level long-lived children ('loop', 'scan', 'profiler') by PID,
synchronously and cross-platform. Uses subprocess.Popen (NOT asyncio.create_subprocess_*)
and threading.Lock (NOT asyncio.Lock). status()/stop()/cancel() are SYNC and are called
directly from sync FastAPI routes — NEVER via asyncio.run(pm.*). The PID tree is persisted
to <state>/process.json so a restarted backend can recover/cancel orphans.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time
from enum import StrEnum

from pydantic import BaseModel

log = logging.getLogger("hephaestus.backend.process")

_IS_WIN = sys.platform.startswith("win")


class ProcState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    EXITED = "exited"


class ProcessHandle(BaseModel):
    name: str
    pid: int | None = None
    state: ProcState = ProcState.IDLE
    started_at_ms: int | None = None
    exit_code: int | None = None
    children: list[int] = []


def _pid_alive(pid: int) -> bool:
    """Cross-platform liveness via os.kill(pid, 0)."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but not ours to signal
    except OSError:
        return False
    return True


class ProcessManager:
    def __init__(self, state_dir: pathlib.Path | None = None) -> None:
        self._lock = threading.Lock()
        self._procs: dict[str, subprocess.Popen] = {}
        self._handles: dict[str, ProcessHandle] = {}
        self._logs: dict[str, object] = {}
        self._state_dir = state_dir

    # ----- process.json (PID-tree persistence for restart recovery) -----

    def _process_json(self) -> pathlib.Path | None:
        base = self._state_dir
        if base is None:
            try:
                from app.core.state import _state_dir

                base = _state_dir()
            except Exception:
                return None
        return pathlib.Path(base) / "process.json"

    def _persist(self, name: str, pid: int | None, children: list[int]) -> None:
        path = self._process_json()
        if path is None:
            return
        try:
            data = {}
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
            if pid is None:
                data.pop(name, None)
            else:
                data[name] = {"pid": pid, "children": children}
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            log.warning("could not persist process.json for %s", name)

    def _recover(self, name: str) -> ProcessHandle | None:
        path = self._process_json()
        if path is None or not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        entry = data.get(name)
        if not entry:
            return None
        pid = entry.get("pid")
        if pid and _pid_alive(int(pid)):
            return ProcessHandle(
                name=name, pid=int(pid), state=ProcState.RUNNING,
                children=list(entry.get("children", [])),
            )
        return None

    # ----- lifecycle (all SYNC) -----

    def start(
        self,
        name: str,
        cmd: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        output_path: pathlib.Path | None = None,
        timeout_sec: int | None = None,
    ) -> ProcessHandle:
        with self._lock:
            if self.status(name).state == ProcState.RUNNING:
                raise ValueError(f"session '{name}' already running")
            stdout: object = subprocess.DEVNULL
            logf = None
            if output_path is not None:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                logf = output_path.open("ab")
                stdout = logf
            kwargs: dict = {"cwd": cwd, "env": {**os.environ, **env}}
            if _IS_WIN:
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kwargs["start_new_session"] = True
            try:
                proc = subprocess.Popen(
                    cmd, stdout=stdout, stderr=subprocess.STDOUT, **kwargs
                )
            except BaseException:
                if logf is not None:
                    logf.close()
                raise
            self._procs[name] = proc
            if logf is not None:
                self._logs[name] = logf
            handle = ProcessHandle(
                name=name,
                pid=proc.pid,
                state=ProcState.RUNNING,
                started_at_ms=int(time.time() * 1000),
            )
            self._handles[name] = handle
            self._persist(name, proc.pid, [])
            return handle.model_copy()

    def stop(self, name: str, *, grace_sec: float = 10.0) -> ProcessHandle:
        proc = self._procs.get(name)
        if proc is None or proc.poll() is not None:
            return self.status(name)
        if name in self._handles:
            self._handles[name].state = ProcState.STOPPING
        try:
            if _IS_WIN:
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        try:
            proc.wait(timeout=grace_sec)
        except subprocess.TimeoutExpired:
            return self.cancel(name)
        return self._finalize(name, proc)

    def cancel(self, name: str) -> ProcessHandle:
        proc = self._procs.get(name)
        if proc is None:
            recovered = self._recover(name)
            if recovered is not None and recovered.pid is not None:
                self._kill_tree(recovered.pid)
                self._persist(name, None, [])
                return ProcessHandle(name=name, state=ProcState.EXITED)
            return self.status(name)
        if proc.poll() is None:
            self._kill_tree(proc.pid)
            with contextlib.suppress(Exception):
                proc.wait(timeout=15)
        return self._finalize(name, proc)

    def _kill_tree(self, pid: int) -> None:
        if _IS_WIN:
            with contextlib.suppress(Exception):
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    timeout=15,
                )
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass

    def _finalize(self, name: str, proc: subprocess.Popen) -> ProcessHandle:
        handle = self._handles.get(name) or ProcessHandle(name=name)
        handle.state = ProcState.EXITED
        handle.exit_code = proc.returncode
        logf = self._logs.pop(name, None)
        if logf is not None:
            with contextlib.suppress(Exception):
                logf.close()  # type: ignore[attr-defined]
        self._persist(name, None, [])
        return handle.model_copy()

    def status(self, name: str) -> ProcessHandle:
        proc = self._procs.get(name)
        handle = self._handles.get(name)
        if proc is None or handle is None:
            recovered = self._recover(name)
            if recovered is not None:
                return recovered
            return ProcessHandle(name=name, state=ProcState.IDLE)
        rc = proc.poll()
        if rc is not None and handle.state != ProcState.EXITED:
            handle.state = ProcState.EXITED
            handle.exit_code = rc
            self._persist(name, None, [])
        return handle.model_copy()

    def list(self) -> list[ProcessHandle]:
        return [h.model_copy() for h in self._handles.values()]

    def cancel_all(self) -> None:
        for name in list(self._procs.keys()):
            self.cancel(name)


pm = ProcessManager()
```

- [ ] Запустить — ожидается PASS на текущей платформе:

```
cd backend && python -m pytest tests/unit/test_process_manager.py -x
```
Ожидаемый вывод: `6 passed`.

- [ ] Commit:

```
git add backend/app/core/process.py backend/tests/unit/test_process_manager.py && git commit -m "feat(stage1): add cross-platform ProcessManager (replaces tmux)"
```

---

## Task 4: ProjectMemory — md-память с frontmatter и read_verify_commands

- [ ] Создать падающий тест `backend/tests/unit/test_project_memory.py`:

```python
"""Unit: ProjectMemory write/read round-trip + verify-command extraction."""
from __future__ import annotations

import pathlib


def _ws(tmp_path: pathlib.Path):
    from app.models.workspace import AgentRef, AgentsConfig, RepoProfile

    return RepoProfile(
        id="abc123",
        name="demo",
        repo_path=str(tmp_path),
        agents=AgentsConfig(
            primary=AgentRef(provider="anthropic", model="claude-opus-4-8"),
            fallback=AgentRef(provider="openai", model="gpt-4.1"),
        ),
    )


def test_write_doc_frontmatter(tmp_path: pathlib.Path) -> None:
    from app.services.project_memory import ProjectMemory

    pmem = ProjectMemory(_ws(tmp_path))
    p = pmem.write_doc("architecture", "## Modules\nfoo", source="profiler")
    assert p.exists()
    fm, body = pmem.read_doc("architecture")
    assert fm["doc"] == "architecture"
    assert fm["workspace_id"] == "abc123"
    assert fm["source"] == "profiler"
    assert fm["schema"] == 1
    assert body.strip() == "## Modules\nfoo"


def test_read_verify_commands(tmp_path: pathlib.Path) -> None:
    from app.services.project_memory import ProjectMemory

    pmem = ProjectMemory(_ws(tmp_path))
    body = "## commands\n```sh\nuv run pytest -q\n# a comment\n\nuv run ruff check .\n```\n"
    pmem.write_doc("verify", body, source="profiler")
    cmds = pmem.read_verify_commands()
    assert cmds == ["uv run pytest -q", "uv run ruff check ."]


def test_read_verify_commands_empty(tmp_path: pathlib.Path) -> None:
    from app.services.project_memory import ProjectMemory

    pmem = ProjectMemory(_ws(tmp_path))
    pmem.write_doc("verify", "no commands fence here", source="manual")
    assert pmem.read_verify_commands() == []


def test_read_doc_missing(tmp_path: pathlib.Path) -> None:
    from app.services.project_memory import ProjectMemory

    pmem = ProjectMemory(_ws(tmp_path))
    fm, body = pmem.read_doc("verify")
    assert fm == {}
    assert body == ""


def test_bootstrap_index(tmp_path: pathlib.Path) -> None:
    from app.services.project_memory import ProjectMemory

    pmem = ProjectMemory(_ws(tmp_path))
    pmem.write_doc("architecture", "x", source="profiler")
    pmem.bootstrap_index()
    fm, body = pmem.read_doc("index")
    assert fm["doc"] == "index"
    assert "architecture.md" in body
```

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/unit/test_project_memory.py -x
```
Ожидаемый вывод: `ModuleNotFoundError: No module named 'app.services.project_memory'`.

- [ ] Создать `backend/app/services/project_memory.py`:

```python
"""ProjectMemory — read/write <repo>/.hephaestus/memory/*.md with YAML frontmatter (D6)."""
from __future__ import annotations

import logging
import pathlib
import re
import time

from app.models.workspace import RepoProfile

log = logging.getLogger("hephaestus.backend.memory")

_DOC_TYPES = ("index", "architecture", "verify", "conventions", "tech-debt")
_FILE_FOR = {
    "index": "MEMORY.md",
    "architecture": "architecture.md",
    "verify": "verify.md",
    "conventions": "conventions.md",
    "tech-debt": "tech-debt.md",
}

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.S)
_COMMANDS_RE = re.compile(r"##\s*commands\s*\n```(?:sh|bash)?\s*\n(.*?)\n```", re.S)


class ProjectMemory:
    def __init__(self, ws: RepoProfile) -> None:
        self.ws = ws
        self._dir = pathlib.Path(ws.repo_path) / ws.memory_dir

    def ensure_dir(self) -> pathlib.Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        return self._dir

    def _path(self, doc: str) -> pathlib.Path:
        return self._dir / _FILE_FOR[doc]

    def write_doc(self, doc: str, body: str, *, source: str) -> pathlib.Path:
        if doc not in _FILE_FOR:
            raise ValueError(f"unknown doc type {doc!r}")
        self.ensure_dir()
        updated = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        fm = (
            f"---\ndoc: {doc}\nworkspace_id: {self.ws.id}\n"
            f"updated_at: {updated}\nsource: {source}\nschema: 1\n---\n"
        )
        path = self._path(doc)
        from app.core.state import _atomic_write

        _atomic_write(path, fm + body)
        return path

    def read_doc(self, doc: str) -> tuple[dict, str]:
        path = self._path(doc)
        if not path.exists():
            return {}, ""
        raw = path.read_text(encoding="utf-8", errors="replace")
        m = _FRONTMATTER_RE.match(raw)
        if not m:
            return {}, raw
        fm_block, body = m.group(1), m.group(2)
        fm: dict = {}
        for line in fm_block.splitlines():
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            val = v.strip()
            if val.isdigit():
                fm[k.strip()] = int(val)
            else:
                fm[k.strip()] = val
        return fm, body

    def read_verify_commands(self) -> list[str]:
        _fm, body = self.read_doc("verify")
        m = _COMMANDS_RE.search(body)
        if not m:
            return []
        return [
            ln.strip()
            for ln in m.group(1).splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]

    def bootstrap_index(self) -> None:
        present = [
            _FILE_FOR[d]
            for d in _DOC_TYPES
            if d != "index" and self._path(d).exists()
        ]
        lines = ["# Project memory index", ""]
        lines += [f"- [{f}]({f})" for f in present]
        self.write_doc("index", "\n".join(lines) + "\n", source="profiler")
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/unit/test_project_memory.py -x
```
Ожидаемый вывод: `5 passed`.

- [ ] Commit:

```
git add backend/app/services/project_memory.py backend/tests/unit/test_project_memory.py && git commit -m "feat(stage1): add ProjectMemory md store with verify-command extraction"
```

---

## Task 5: VerifyRunner — кроссплатформенный verify без bash/pnpm

- [ ] Создать падающий тест `backend/tests/unit/test_verify_runner.py`:

```python
"""Unit: VerifyRunner resolves commands and runs them cross-platform (no bash)."""
from __future__ import annotations

import os
import pathlib
import sys

import pytest


def _ws(tmp_path: pathlib.Path, **over):
    from app.models.workspace import AgentRef, AgentsConfig, RepoProfile

    base = dict(
        id="abc123",
        name="demo",
        repo_path=str(tmp_path),
        agents=AgentsConfig(
            primary=AgentRef(provider="anthropic", model="claude-opus-4-8"),
            fallback=AgentRef(provider="openai", model="gpt-4.1"),
        ),
    )
    base.update(over)
    return RepoProfile(**base)


def test_resolve_manual(tmp_path: pathlib.Path) -> None:
    from app.core.verify import VerifyRunner
    from app.models.workspace import VerifySource

    ws = _ws(tmp_path, verify_source=VerifySource.MANUAL, verify_commands_override=["echo hi"])
    assert VerifyRunner(ws).resolve_commands() == ["echo hi"]


def test_resolve_agent_from_memory(tmp_path: pathlib.Path) -> None:
    from app.core.verify import VerifyRunner
    from app.services.project_memory import ProjectMemory

    ws = _ws(tmp_path)
    ProjectMemory(ws).write_doc("verify", "## commands\n```sh\necho ok\n```\n", source="profiler")
    assert VerifyRunner(ws).resolve_commands() == ["echo ok"]


@pytest.mark.asyncio
async def test_run_green(tmp_path: pathlib.Path) -> None:
    from app.core.verify import VerifyRunner
    from app.models.workspace import VerifySource

    py = sys.executable.replace("\\", "/")
    ws = _ws(
        tmp_path,
        verify_source=VerifySource.MANUAL,
        verify_commands_override=[f'"{py}" -c "import sys; sys.exit(0)"'],
    )
    res = await VerifyRunner(ws).run(cwd=str(tmp_path), log_path=tmp_path / "verify.log", timeout_sec=30)
    assert res.ok is True
    assert res.failed_command is None
    assert len(res.ran) == 1


@pytest.mark.asyncio
async def test_run_fail(tmp_path: pathlib.Path) -> None:
    from app.core.verify import VerifyRunner
    from app.models.workspace import VerifySource

    py = sys.executable.replace("\\", "/")
    fail = f'"{py}" -c "import sys; sys.exit(1)"'
    ws = _ws(
        tmp_path,
        verify_source=VerifySource.MANUAL,
        verify_commands_override=[fail, f'"{py}" -c "import sys; sys.exit(0)"'],
    )
    res = await VerifyRunner(ws).run(cwd=str(tmp_path), log_path=tmp_path / "verify.log", timeout_sec=30)
    assert res.ok is False
    assert res.failed_command == fail


@pytest.mark.asyncio
async def test_run_empty_is_noop(tmp_path: pathlib.Path) -> None:
    from app.core.verify import VerifyRunner
    from app.models.workspace import VerifySource

    ws = _ws(tmp_path, verify_source=VerifySource.MANUAL, verify_commands_override=[])
    res = await VerifyRunner(ws).run(cwd=str(tmp_path), log_path=tmp_path / "verify.log", timeout_sec=30)
    assert res.ok is True
    assert res.ran == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows .cmd shim resolution (R5)")
@pytest.mark.asyncio
async def test_run_resolves_cmd_shim_on_windows(tmp_path: pathlib.Path, monkeypatch) -> None:
    """A bare 'mytool' must resolve to mytool.cmd via shutil.which (R5)."""
    from app.core.verify import VerifyRunner
    from app.models.workspace import VerifySource

    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    (shim_dir / "mytool.cmd").write_text("@echo verify-ok\r\n@exit /b 0\r\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(shim_dir) + os.pathsep + os.environ["PATH"])

    ws = _ws(tmp_path, verify_source=VerifySource.MANUAL, verify_commands_override=["mytool"])
    res = await VerifyRunner(ws).run(cwd=str(tmp_path), log_path=tmp_path / "verify.log", timeout_sec=30)
    assert res.ok is True
    assert "verify-ok" in (tmp_path / "verify.log").read_text(errors="replace")


def test_argv_for_shell_override(tmp_path: pathlib.Path) -> None:
    """shell:-prefixed commands route through cmd /c (Windows) / sh -c (POSIX) (R5)."""
    from app.core.verify import VerifyRunner
    from app.models.workspace import VerifySource

    ws = _ws(tmp_path, verify_source=VerifySource.MANUAL)
    argv = VerifyRunner(ws)._argv_for("shell:echo a && echo b")
    if sys.platform == "win32":
        assert argv[:2] == ["cmd", "/c"]
    else:
        assert argv[:2] == ["sh", "-c"]
```

Тест-файл импортирует `import os` и `import sys` (добавить в шапку, если ещё нет).

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/unit/test_verify_runner.py -x
```
Ожидаемый вывод: `ModuleNotFoundError: No module named 'app.core.verify'`.

- [ ] Создать `backend/app/core/verify.py`:

```python
"""VerifyRunner — cross-platform verify commands from memory/override (D4, R5).

Each command is "one program + args per line, no shell operators" (&&, |, >, $VAR).
The executable is resolved via shutil.which BEFORE exec so Windows picks up .cmd/.bat/.exe
shims (npm.cmd / pnpm.cmd). shlex.split uses posix=True (NOT posix=False) on every platform:
it strips quotes correctly and we always pass an argv list to create_subprocess_exec, never a
shell. An optional manual-override may mark a command shell:true -> ['cmd','/c',cmd] (Windows)
/ ['sh','-c',cmd] (POSIX); default shell:false.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import pathlib
import shlex
import shutil
import sys

from pydantic import BaseModel

from app.models.workspace import RepoProfile, VerifySource

log = logging.getLogger("hephaestus.backend.verify")

_IS_WIN = sys.platform.startswith("win")


class VerifyResult(BaseModel):
    ok: bool
    ran: list[str]
    failed_command: str | None = None
    log_path: pathlib.Path


class VerifyRunner:
    def __init__(self, ws: RepoProfile) -> None:
        self.ws = ws

    def resolve_commands(self) -> list[str]:
        if self.ws.verify_source is VerifySource.MANUAL:
            return list(self.ws.verify_commands_override)
        from app.services.project_memory import ProjectMemory

        return ProjectMemory(self.ws).read_verify_commands()

    def _argv_for(self, cmd: str) -> list[str]:
        """Resolve a verify command line into an argv list (R5).

        Default: split with posix=True and resolve argv[0] via shutil.which so Windows shims
        (.cmd/.bat) are found. An optional 'shell:' prefix forces shell execution.
        """
        stripped = cmd.strip()
        if stripped.startswith("shell:"):
            inner = stripped[len("shell:"):].strip()
            return ["cmd", "/c", inner] if _IS_WIN else ["sh", "-c", inner]
        argv = shlex.split(stripped, posix=True)
        if not argv:
            return []
        exe = shutil.which(argv[0]) or argv[0]  # picks up npm.cmd/pnpm.cmd on Windows
        return [exe, *argv[1:]]

    async def run(self, *, cwd: str, log_path: pathlib.Path, timeout_sec: int) -> VerifyResult:
        cmds = self.resolve_commands()
        ran: list[str] = []
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as logf:
            for cmd in cmds:
                argv = self._argv_for(cmd)
                if not argv:
                    continue
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *argv,
                        cwd=cwd,
                        stdout=logf,
                        stderr=asyncio.subprocess.STDOUT,
                        env=os.environ,
                    )
                except FileNotFoundError:
                    logf.write(f"\n[verify] command not found: {cmd}\n".encode())
                    return VerifyResult(ok=False, ran=ran, failed_command=cmd, log_path=log_path)
                try:
                    rc = await asyncio.wait_for(proc.wait(), timeout=timeout_sec)
                except (asyncio.TimeoutError, TimeoutError):
                    with contextlib.suppress(Exception):
                        proc.kill()
                        await proc.wait()
                    logf.write(f"\n[verify] timeout: {cmd}\n".encode())
                    return VerifyResult(ok=False, ran=ran, failed_command=cmd, log_path=log_path)
                ran.append(cmd)
                if rc != 0:
                    return VerifyResult(ok=False, ran=ran, failed_command=cmd, log_path=log_path)
        return VerifyResult(ok=True, ran=ran, failed_command=None, log_path=log_path)
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/unit/test_verify_runner.py -x
```
Ожидаемый вывод: на POSIX `6 passed, 1 skipped` (Windows-шим скипается); на `windows-latest` — `7 passed`.

- [ ] Commit:

```
git add backend/app/core/verify.py backend/tests/unit/test_verify_runner.py && git commit -m "feat(stage1): add cross-platform VerifyRunner (shutil.which shim resolution, replaces verify.sh)"
```

---

## Task 6: AgentRunner — _build_cmd и run_with_fallback поверх ProcessManager

- [ ] Создать падающий тест `backend/tests/unit/test_agent_runner_cmd.py`:

```python
"""Unit: AgentRunner._build_cmd — флаги opencode 1.16.0 (--format json, --agent/--model,
позиционный message). Подтверждено `opencode run --help`."""
from __future__ import annotations

import pathlib


def _runner():
    from app.core.process import ProcessManager
    from app.services.opencode_runner import AgentRunner

    return AgentRunner(ProcessManager())


def test_build_cmd_model_mode() -> None:
    from app.models.workspace import AgentRef

    ar = _runner()
    ref = AgentRef(provider="anthropic", model="claude-opus-4-8")
    cmd = ar._build_cmd(ref, "do the task", use_models=True)
    assert cmd[:4] == ["opencode", "run", "--format", "json"]
    assert "--model" in cmd and "anthropic/claude-opus-4-8" in cmd
    assert "--model-output-format" not in cmd and "--output" not in cmd and "--prompt" not in cmd
    assert cmd[-1] == "do the task"  # промпт — позиционный message


def test_build_cmd_agent_mode() -> None:
    from app.models.workspace import AgentRef

    ar = _runner()
    ref = AgentRef(provider="anthropic", model="claude-opus-4-8", agent="sisyphus")
    cmd = ar._build_cmd(ref, "do the task", use_models=False)
    assert "--agent" in cmd and "sisyphus" in cmd
    assert "--model" not in cmd
    assert "--format" in cmd and "json" in cmd


def test_build_cmd_agent_none_falls_back_to_model() -> None:
    from app.models.workspace import AgentRef

    ar = _runner()
    ref = AgentRef(provider="openai", model="gpt-4.1", agent=None)
    cmd = ar._build_cmd(ref, "do the task", use_models=False)
    assert "--model" in cmd and "openai/gpt-4.1" in cmd
    assert "--agent" not in cmd


def test_build_cmd_oversize_prompt_attaches_file(tmp_path: pathlib.Path) -> None:
    from app.models.workspace import AgentRef

    ar = _runner()
    ref = AgentRef(provider="openai", model="gpt-4.1")
    big = tmp_path / "p.md"
    cmd = ar._build_cmd(ref, "x" * 40000, use_models=True, attach_file=big)
    assert "-f" in cmd and str(big) in cmd
    assert ("x" * 40000) not in cmd  # огромный текст не инлайнится в аргумент
```

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/unit/test_agent_runner_cmd.py -x
```
Ожидаемый вывод: `ModuleNotFoundError: No module named 'app.services.opencode_runner'`.

- [ ] Создать `backend/app/services/opencode_runner.py`:

```python
"""AgentRunner — wraps `opencode run` with provider/model/agent selection (D2, R1/R2).

AgentRunner runs INSIDE a child process (orchestrator/profiler/scan) on that process's own
asyncio event loop. It owns its OWN asyncio.subprocess handle and awaits exactly that handle —
it NEVER touches ProcessManager private fields (_procs/_finalize) and concurrent calls never
share a session_name (each gets a unique output_path). The `pm` is kept only for API parity
(module-singleton wiring); AgentRunner does not supervise via it.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import pathlib

from pydantic import BaseModel

from app.core.process import ProcessManager
from app.models.workspace import AgentRef, AgentsConfig

log = logging.getLogger("hephaestus.backend.opencode")


class AgentResult(BaseModel):
    exit_code: int
    refused: bool
    output_path: pathlib.Path
    agent_label: str


class AgentRunner:
    def __init__(self, pm: ProcessManager) -> None:
        self._pm = pm  # parity only; AgentRunner never reads pm internals (R1)

    def _label(self, ref: AgentRef, use_models: bool) -> str:
        if ref.agent and not use_models:
            return ref.agent
        return f"{ref.provider}/{ref.model}"

    # opencode 1.16.0: `opencode run [message..]` — message ПОЗИЦИОННЫЙ (нет --prompt).
    # Машинный вывод: `--format json` в STDOUT (нет --output). Агент через --agent,
    # модель через --model provider/model. НЕ использовать --command (баг #2923).
    # Флаги подтверждены `opencode run --help` (v1.16.0).
    _MAX_INLINE_PROMPT = 28000  # запас под лимит длины аргумента CreateProcess (Windows)

    def _build_cmd(
        self,
        ref: AgentRef,
        prompt_text: str,
        *,
        use_models: bool,
        attach_file: pathlib.Path | None = None,
    ) -> list[str]:
        cmd = ["opencode", "run", "--format", "json"]
        if ref.agent and not use_models:
            cmd += ["--agent", ref.agent]
        else:
            cmd += ["--model", f"{ref.provider}/{ref.model}"]
        if attach_file is not None:
            # большой промпт: вложить файл и дать короткий позиционный message
            cmd += ["-f", str(attach_file),
                    "Follow the instructions in the attached file exactly."]
        else:
            cmd.append(prompt_text)  # позиционный message
        return cmd

    async def run(
        self,
        ref: AgentRef,
        *,
        prompt_file: pathlib.Path,
        cwd: str,
        output_path: pathlib.Path,
        timeout_sec: int,
        use_models: bool = False,
    ) -> AgentResult:
        label = self._label(ref, use_models)
        prompt_text = prompt_file.read_text(encoding="utf-8", errors="replace")
        attach = prompt_file if len(prompt_text) > self._MAX_INLINE_PROMPT else None
        cmd = self._build_cmd(ref, prompt_text, use_models=use_models, attach_file=attach)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Свой asyncio.subprocess на ТЕКУЩЕМ loop (внутри дочернего процесса). opencode
            # `--format json` пишет JSON-события в STDOUT → захватываем и сохраняем в
            # output_path. Уникальный output_path на вызов; общего session_name нет (R1/R2).
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=os.environ,
            )
        except FileNotFoundError:
            log.error("opencode CLI not found on PATH")
            return AgentResult(exit_code=-1, refused=False, output_path=output_path, agent_label=label)
        try:
            stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
            rc = proc.returncode if proc.returncode is not None else -1
        except (asyncio.TimeoutError, TimeoutError):
            with contextlib.suppress(Exception):
                proc.kill()
                await proc.wait()
            return AgentResult(exit_code=-1, refused=False, output_path=output_path, agent_label=label)
        with contextlib.suppress(OSError):
            output_path.write_bytes(stdout or b"")
        head = (stdout or b"")[:1000].decode("utf-8", errors="replace")
        refused = "REFUSED" in head
        return AgentResult(exit_code=rc, refused=refused, output_path=output_path, agent_label=label)

    async def run_with_fallback(
        self,
        agents: AgentsConfig,
        *,
        prompt_file: pathlib.Path,
        cwd: str,
        iter_dir: pathlib.Path,
        timeout_sec: int,
    ) -> AgentResult:
        primary_out = iter_dir / "output.primary.jsonl"
        res = await self.run(
            agents.primary,
            prompt_file=prompt_file,
            cwd=cwd,
            output_path=primary_out,
            timeout_sec=timeout_sec,
            use_models=agents.use_models,
        )
        if res.exit_code == 0 or res.refused:
            return res
        log.warning("primary agent failed (rc=%d), trying fallback", res.exit_code)
        fallback_out = iter_dir / "output.fallback.jsonl"
        return await self.run(
            agents.fallback,
            prompt_file=prompt_file,
            cwd=cwd,
            output_path=fallback_out,
            timeout_sec=timeout_sec,
            use_models=agents.use_models,
        )
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/unit/test_agent_runner_cmd.py -x
```
Ожидаемый вывод: `4 passed`.

- [ ] Commit:

```
git add backend/app/services/opencode_runner.py backend/tests/unit/test_agent_runner_cmd.py && git commit -m "feat(stage1): add AgentRunner wrapping opencode run (provider/model/agent)"
```

---

## Task 7: WorkspaceRegistry — реестр воркспейсов, активный, разрешение путей

- [ ] Создать падающий тест `backend/tests/unit/test_workspace_registry.py`:

```python
"""Unit: WorkspaceRegistry CRUD, idempotent create, path resolution."""
from __future__ import annotations

import pathlib
import subprocess

import pytest


def _git_init(p: pathlib.Path) -> None:
    p.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(p)], capture_output=True, timeout=30, check=True)


def _reg(home: pathlib.Path):
    from app.core.workspaces import WorkspaceRegistry

    return WorkspaceRegistry(home=home)


def test_create_idempotent(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "repo"
    _git_init(repo)
    reg = _reg(tmp_path / "home")
    a = reg.create(str(repo), name="repo")
    b = reg.create(str(repo))
    assert a.id == b.id
    assert len(reg.list()) == 1


def test_id_case_insensitive(tmp_path: pathlib.Path) -> None:
    from app.core.workspaces import WorkspaceRegistry

    repo = tmp_path / "Repo"
    _git_init(repo)
    id1 = WorkspaceRegistry.ws_id_for(str(repo))
    id2 = WorkspaceRegistry.ws_id_for(str(repo).upper())
    assert id1 == id2
    assert len(id1) == 16


def test_create_rejects_non_git(tmp_path: pathlib.Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    reg = _reg(tmp_path / "home")
    with pytest.raises(ValueError, match="not a git repository"):
        reg.create(str(plain))


def test_activate_and_active(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "repo"
    _git_init(repo)
    reg = _reg(tmp_path / "home")
    ws = reg.create(str(repo))
    assert reg.active() is None
    reg.activate(ws.id)
    assert reg.active().id == ws.id


def test_state_and_memory_dir(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "repo"
    _git_init(repo)
    home = tmp_path / "home"
    reg = _reg(home)
    ws = reg.create(str(repo))
    sd = reg.state_dir(ws)
    md = reg.memory_dir(ws)
    assert sd == home / "workspaces" / ws.id / "state"
    assert md == pathlib.Path(ws.repo_path) / ".hephaestus" / "memory"


def test_update_persists(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "repo"
    _git_init(repo)
    home = tmp_path / "home"
    reg = _reg(home)
    ws = reg.create(str(repo))
    reg.update(ws.id, {"onboarded": True, "strictness": "strict"})
    reg2 = _reg(home)
    got = reg2.get(ws.id)
    assert got.onboarded is True
    assert got.strictness == "strict"
```

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/unit/test_workspace_registry.py -x
```
Ожидаемый вывод: `ModuleNotFoundError: No module named 'app.core.workspaces'`.

- [ ] Создать `backend/app/core/workspaces.py`:

```python
"""WorkspaceRegistry — registry of onboarded repos + active selection (D9)."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import time

from app.models.workspace import AgentRef, AgentsConfig, RepoProfile
from app.services.hephaestus_home import hephaestus_home

log = logging.getLogger("hephaestus.backend.workspaces")

_NEUTRAL_AGENTS = AgentsConfig(
    primary=AgentRef(provider="anthropic", model="claude-opus-4-8"),
    fallback=AgentRef(provider="openai", model="gpt-4.1"),
)


class WorkspaceRegistry:
    def __init__(self, home: pathlib.Path | None = None) -> None:
        self._home = home or hephaestus_home()
        self._root = self._home / "workspaces"

    @staticmethod
    def ws_id_for(repo_path: str) -> str:
        norm = os.path.realpath(repo_path).casefold().encode()
        return hashlib.sha256(norm).hexdigest()[:16]

    def _profile_path(self, ws_id: str) -> pathlib.Path:
        return self._root / ws_id / "profile.json"

    def list(self) -> list[RepoProfile]:
        if not self._root.exists():
            return []
        out: list[RepoProfile] = []
        for d in sorted(self._root.glob("*")):
            pf = d / "profile.json"
            if pf.exists():
                try:
                    out.append(RepoProfile.model_validate_json(pf.read_text(encoding="utf-8")))
                except Exception:
                    log.warning("skipping invalid profile.json in %s", d)
        return out

    def get(self, ws_id: str) -> RepoProfile | None:
        pf = self._profile_path(ws_id)
        if not pf.exists():
            return None
        try:
            return RepoProfile.model_validate_json(pf.read_text(encoding="utf-8"))
        except Exception:
            return None

    def create(self, repo_path: str, *, name: str | None = None) -> RepoProfile:
        rp = pathlib.Path(repo_path)
        if not (rp / ".git").exists():
            raise ValueError("not a git repository")
        ws_id = self.ws_id_for(repo_path)
        existing = self.get(ws_id)
        if existing is not None:
            return existing
        ws = RepoProfile(
            id=ws_id,
            name=name or rp.name,
            repo_path=os.path.realpath(repo_path),
            agents=_NEUTRAL_AGENTS.model_copy(deep=True),
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            onboarded=False,
        )
        self._write(ws)
        return ws

    def _write(self, ws: RepoProfile) -> None:
        from app.core.state import _atomic_write

        d = self._root / ws.id
        d.mkdir(parents=True, exist_ok=True)
        _atomic_write(d / "profile.json", ws.model_dump_json(by_alias=True, indent=2))

    def update(self, ws_id: str, patch: dict) -> RepoProfile:
        ws = self.get(ws_id)
        if ws is None:
            raise ValueError(f"unknown workspace {ws_id}")
        merged = {**ws.model_dump(by_alias=True), **patch}
        new_ws = RepoProfile.model_validate(merged)
        self._write(new_ws)
        return new_ws

    def activate(self, ws_id: str) -> None:
        from app.core.state import _atomic_write

        self._root.mkdir(parents=True, exist_ok=True)
        _atomic_write(self._root / "active.json", json.dumps({"workspaceId": ws_id}))

    def active(self) -> RepoProfile | None:
        ap = self._root / "active.json"
        if not ap.exists():
            return None
        try:
            ws_id = json.loads(ap.read_text(encoding="utf-8")).get("workspaceId")
        except Exception:
            return None
        return self.get(ws_id) if ws_id else None

    def state_dir(self, ws: RepoProfile) -> pathlib.Path:
        return self._root / ws.id / "state"

    def memory_dir(self, ws: RepoProfile) -> pathlib.Path:
        return pathlib.Path(ws.repo_path) / ws.memory_dir


registry = WorkspaceRegistry()
```

- [ ] Запустить — ожидается PASS (gated на git):

```
cd backend && python -m pytest tests/unit/test_workspace_registry.py -x
```
Ожидаемый вывод: `6 passed`.

- [ ] Commit:

```
git add backend/app/core/workspaces.py backend/tests/unit/test_workspace_registry.py && git commit -m "feat(stage1): add WorkspaceRegistry (registry + active + path resolution)"
```

---

## Task 8: Profiler — парсинг ProfilerOutput + промпт profiler.md

- [ ] Создать падающий тест `backend/tests/unit/test_profiler_parse.py`:

```python
"""Unit: Profiler extracts last JSON block; tolerates non-JSON."""
from __future__ import annotations


def test_extract_last_json_block() -> None:
    from app.services.profiler import Profiler

    out = (
        'prose...\n{"tech_stack":["python"],"verify_commands":["uv run pytest"],'
        '"architecture_md":"A","conventions_md":"C","tech_debt_md":"D","base_branch":"main"}'
    )
    parsed = Profiler._parse_output(out)
    assert parsed.tech_stack == ["python"]
    assert parsed.verify_commands == ["uv run pytest"]
    assert parsed.base_branch == "main"


def test_parse_non_json_returns_blank() -> None:
    from app.services.profiler import Profiler

    parsed = Profiler._parse_output("the agent refused and wrote prose only")
    assert parsed.verify_commands == []
    assert parsed.tech_stack == []
```

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/unit/test_profiler_parse.py -x
```
Ожидаемый вывод: `ModuleNotFoundError: No module named 'app.services.profiler'`.

- [ ] Создать `prompts/profiler.md`:

```markdown
# Profiler — repository onboarding agent

Ты — Profiler. Проанализируй репозиторий и верни ОДИН JSON-объект последним сообщением.

## Detected context
- tech_stack: {{tech_stack}}
- structure: {{structure}}
- readme: {{readme}}

## Задача
1. Определи реальный стек проекта (НЕ предполагай pnpm — смотри на файлы).
2. Определи verify-команды проекта: test, lint, typecheck — только те, что реально есть.
3. Опиши архитектуру, конвенции, технический долг кратко.
4. Определи базовую ветку (main/master).

## Формат вывода (строго один JSON-объект последним сообщением)
{
  "tech_stack": ["python", "fastapi"],
  "verify_commands": ["uv run pytest -q", "uv run ruff check ."],
  "architecture_md": "## Modules ...",
  "conventions_md": "## Style ...",
  "tech_debt_md": "## Known debt ...",
  "base_branch": "main"
}

Никаких git-операций. Только анализ и JSON.
```

- [ ] Создать `backend/app/services/profiler.py`:

```python
"""Profiler — onboarding agent: detect stack, run agent, write memory (D4+D6)."""
from __future__ import annotations

import json
import logging
import pathlib

from pydantic import BaseModel

from app.models.workspace import RepoProfile, VerifySource
from app.services.opencode_runner import AgentRunner

log = logging.getLogger("hephaestus.backend.profiler")


class ProfilerOutput(BaseModel):
    tech_stack: list[str] = []
    verify_commands: list[str] = []
    architecture_md: str = ""
    conventions_md: str = ""
    tech_debt_md: str = ""
    base_branch: str | None = None


class Profiler:
    def __init__(self, ws: RepoProfile, runner: AgentRunner) -> None:
        self.ws = ws
        self.runner = runner

    @staticmethod
    def _parse_output(text: str) -> ProfilerOutput:
        """Extract the LAST balanced {...} block and parse it; blank on failure."""
        last: str | None = None
        depth = 0
        start = -1
        for i, ch in enumerate(text):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start >= 0:
                        last = text[start : i + 1]
        if last is None:
            return ProfilerOutput()
        try:
            data = json.loads(last)
            return ProfilerOutput.model_validate(data)
        except Exception:
            log.warning("profiler output not valid JSON — writing blanks")
            return ProfilerOutput()

    async def onboard(self) -> ProfilerOutput:
        from app.core.workspaces import registry
        from app.services.doc_reader import DocReader
        from app.services.project_memory import ProjectMemory
        from app.services.prompt_manager import PromptManager

        dr = DocReader(pathlib.Path(self.ws.repo_path))
        try:
            tech_stack = dr.detect_tech_stack()
            structure = dr.get_context_summary()
        except Exception:
            tech_stack, structure = [], ""

        pm = PromptManager()
        template = "Analyze the repository and return the required JSON object."
        try:
            got = pm.get_prompt("profiler")
            if isinstance(got, dict) and got.get("content"):
                template = str(got["content"])
        except Exception:
            pass
        prompt = (
            template.replace("{{tech_stack}}", ", ".join(tech_stack))
            .replace("{{structure}}", structure)
            .replace("{{readme}}", "")
        )
        state_dir = registry.state_dir(self.ws)
        state_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = state_dir / "profiler-prompt.md"
        prompt_file.write_text(prompt, encoding="utf-8")
        out_path = state_dir / "output.profiler.jsonl"

        await self.runner.run(
            self.ws.agents.primary,
            prompt_file=prompt_file,
            cwd=self.ws.repo_path,
            output_path=out_path,  # unique onboarding artifact; identity profiler-<ws.id> (R2)
            timeout_sec=self.ws.verify_timeout_sec,
            use_models=self.ws.agents.use_models,
        )
        raw = out_path.read_text(encoding="utf-8", errors="replace") if out_path.exists() else ""
        parsed = self._parse_output(raw)

        mem = ProjectMemory(self.ws)
        verify_body = "## commands\n```sh\n" + "\n".join(parsed.verify_commands) + "\n```\n"
        mem.write_doc("verify", verify_body, source="profiler")
        mem.write_doc("architecture", parsed.architecture_md or "## Modules\n", source="profiler")
        mem.write_doc("conventions", parsed.conventions_md or "## Style\n", source="profiler")
        mem.write_doc("tech-debt", parsed.tech_debt_md or "## Known debt\n", source="profiler")
        mem.bootstrap_index()

        patch: dict = {"onboarded": True, "verifySource": VerifySource.AGENT.value}
        if parsed.base_branch:
            patch["baseBranch"] = parsed.base_branch
        registry.update(self.ws.id, patch)
        return parsed
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/unit/test_profiler_parse.py -x
```
Ожидаемый вывод: `2 passed`.

- [ ] Commit:

```
git add backend/app/services/profiler.py prompts/profiler.md backend/tests/unit/test_profiler_parse.py && git commit -m "feat(stage1): add Profiler onboarding agent + profiler.md prompt"
```

---

## Task 9: де-HEPHAESTUS-ификация config.py

- [ ] Создать падающий тест `backend/tests/unit/test_config_dehephaestus.py`:

```python
"""Unit: config has no vendor agent defaults and no hardcoded Linux repo path."""
from __future__ import annotations


def test_no_vendor_agent_defaults() -> None:
    import importlib

    import app.config as cfg

    importlib.reload(cfg)
    eff = cfg._config_effective()
    blob = " ".join(str(v) for v in eff.values())
    for vendor in (
        "sisyphus",
        "atlas",
        "oracle",
        "librarian",
        "prometheus",
        "metis",
        "momus",
        "multimodal-looker",
        "sisyphus-junior",
    ):
        assert vendor not in blob, f"vendor default {vendor} still present"


def test_repo_default_not_hardcoded_linux(monkeypatch) -> None:
    import importlib

    monkeypatch.delenv("HEPHAESTUS_REPO", raising=False)
    import app.config as cfg

    importlib.reload(cfg)
    assert cfg.REPO != "/home/starsinc/hephaestus-repo"


def test_tier_presets_preserved() -> None:
    import app.config as cfg

    assert set(cfg.TIER_PRESETS) == {"strict", "standard", "permissive", "disabled"}
    assert cfg.TIER_PRESETS["standard"]["HEPHAESTUS_TIER1_APPROVE_THRESHOLD"] == "5"


def test_verify_and_agent_keys_whitelisted() -> None:
    import app.config as cfg

    for k in ("HEPHAESTUS_AGENT_PROVIDER", "HEPHAESTUS_AGENT_MODEL", "HEPHAESTUS_VERIFY_COMMANDS"):
        assert k in cfg.ALLOWED_CONFIG_KEYS
```

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/unit/test_config_dehephaestus.py -x
```
Ожидаемый вывод: `test_no_vendor_agent_defaults`/`test_repo_default_not_hardcoded_linux`/`test_verify_and_agent_keys_whitelisted` FAIL.

- [ ] В `backend/app/config.py` заменить хардкод `REPO` (строка 22):

```python
REPO = os.environ.get("HEPHAESTUS_REPO", "")
```

- [ ] В `backend/app/config.py` добавить новые ключи во `ALLOWED_CONFIG_KEYS` (после `"HEPHAESTUS_USE_MODELS",`):

```python
        "HEPHAESTUS_AGENT_PROVIDER",
        "HEPHAESTUS_AGENT_MODEL",
        "HEPHAESTUS_VERIFY_COMMANDS",
        "HEPHAESTUS_WORKSPACE_ID",
```

- [ ] В `backend/app/config.py` убрать vendor-дефолты из `_config_effective` — заменить блок строк 116-126 на нейтральный:

```python
        "HEPHAESTUS_PRIMARY_AGENT": os.environ.get("HEPHAESTUS_PRIMARY_AGENT", ""),
        "HEPHAESTUS_FALLBACK_AGENT": os.environ.get("HEPHAESTUS_FALLBACK_AGENT", ""),
        "HEPHAESTUS_MAX_ITER": os.environ.get("HEPHAESTUS_MAX_ITER", "50"),
        "HEPHAESTUS_TIER_REVIEW": os.environ.get("HEPHAESTUS_TIER_REVIEW", "on"),
        "HEPHAESTUS_AUTOPUSH": os.environ.get("HEPHAESTUS_AUTOPUSH", "off"),
        "HEPHAESTUS_ITER_TIMEOUT_SEC": os.environ.get("HEPHAESTUS_ITER_TIMEOUT_SEC", "2400"),
        "HEPHAESTUS_MAX_CONSEC_FAIL": os.environ.get("HEPHAESTUS_MAX_CONSEC_FAIL", "4"),
        "HEPHAESTUS_TIER1_AGENTS": os.environ.get("HEPHAESTUS_TIER1_AGENTS", ""),
        "HEPHAESTUS_TIER2_AGENTS": os.environ.get("HEPHAESTUS_TIER2_AGENTS", ""),
        "HEPHAESTUS_FINAL_AGENT": os.environ.get("HEPHAESTUS_FINAL_AGENT", ""),
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/unit/test_config_dehephaestus.py -x
```
Ожидаемый вывод: `4 passed`.

- [ ] Commit:

```
git add backend/app/config.py backend/tests/unit/test_config_dehephaestus.py && git commit -m "feat(stage1): de-HEPHAESTUS-ify config — drop vendor agent defaults + Linux repo path"
```

---

## Task 10: state.py — ws-scoped STATE_DIR + кроссплатформенный _StateLock

- [ ] Переписать падающий `backend/tests/contract/test_lock_contract.py` под чистый Python (без bash):

```python
"""Contract: _StateLock serializes in-process writes (cross-platform, no bash)."""
from __future__ import annotations

import pathlib

import pytest


def test_concurrent_writes_no_corruption(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path, raising=False)
    monkeypatch.setattr(state_mod, "LOCK_PATH", tmp_path / ".work-state.lock")
    (tmp_path / "work-state.json").write_text('{"items": []}')

    for i in range(100):
        with state_mod._StateLock():
            s = state_mod._read_state()
            s["items"].append({"id": f"item-{i}", "title": f"Item {i}", "status": "pending"})
            state_mod._write_state(s)

    final = state_mod._read_state()
    assert len(final["items"]) == 100
    assert {it["id"] for it in final["items"]} == {f"item-{i}" for i in range(100)}


def test_lock_reentrant_safe(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path, raising=False)
    monkeypatch.setattr(state_mod, "LOCK_PATH", tmp_path / ".work-state.lock")
    (tmp_path / "work-state.json").write_text('{"items": []}')
    with state_mod._StateLock():
        state_mod._write_state({"items": [{"id": "x", "title": "x", "status": "pending"}]})
    assert len(state_mod._read_state()["items"]) == 1
```

- [ ] Запустить — ожидается FAIL (STATE_DIR не разрешается через override):

```
cd backend && python -m pytest tests/contract/test_lock_contract.py -x
```
Ожидаемый вывод: ошибки путей (старый код использует модульный `STATE_DIR`, override не подхватывается).

- [ ] В `backend/app/core/state.py` заменить импорт (строка 19) и ввести `_state_dir()`:

```python
from app.config import LOCK_PATH
from app.config import STATE_DIR as _DEFAULT_STATE_DIR

# Test/override hook — if set, takes precedence over the active workspace.
_STATE_DIR_OVERRIDE: pathlib.Path | None = None


def _state_dir() -> pathlib.Path:
    """Resolve the active workspace state dir, falling back to the legacy global."""
    if _STATE_DIR_OVERRIDE is not None:
        return _STATE_DIR_OVERRIDE
    try:
        from app.core.workspaces import registry

        ws = registry.active()
        if ws is not None:
            return registry.state_dir(ws)
    except Exception:
        pass
    return _DEFAULT_STATE_DIR
```

- [ ] В `backend/app/core/state.py` заменить обращения к модульному `STATE_DIR` на `_state_dir()`. В `_StateLock.__enter__` (строка 65), `_read_state` (строка 112), `_write_state` (строки 154-155):

```python
                _state_dir().mkdir(parents=True, exist_ok=True)
```
```python
    p = _state_dir() / "work-state.json"
```
```python
    state_path = _state_dir() / "work-state.json"
    backup_path = _state_dir() / "work-state.json.bak"
```

- [ ] В `backend/app/core/state.py` добавить Windows-импорт рядом с `import fcntl`:

```python
try:
    import fcntl  # POSIX advisory lock

    HAVE_FCNTL = True
except ImportError:
    HAVE_FCNTL = False

try:
    import msvcrt  # Windows mandatory lock

    HAVE_MSVCRT = True
except ImportError:
    HAVE_MSVCRT = False
```

- [ ] В `_StateLock.__enter__` после блока `if HAVE_FCNTL:` (перед `else: self._fd = None`) добавить Windows-ветку:

```python
            elif HAVE_MSVCRT:
                _state_dir().mkdir(parents=True, exist_ok=True)
                self._fd = open(LOCK_PATH, "a+")
                deadline = time.monotonic() + 30
                while True:
                    try:
                        msvcrt.locking(self._fd.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[union-attr]
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            self._fd.close()  # type: ignore[union-attr]
                            self._fd = None
                            _thread_lock.release()
                            raise TimeoutError("could not acquire file lock within 30s")
                        time.sleep(0.1)
```

- [ ] Заменить `_StateLock.__exit__` целиком на ветвящуюся разблокировку:

```python
    def __exit__(self, *exc: object) -> None:
        try:
            if self._fd is not None:
                if HAVE_FCNTL:
                    fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)  # type: ignore[union-attr]
                elif HAVE_MSVCRT:
                    with contextlib.suppress(OSError):
                        msvcrt.locking(self._fd.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[union-attr]
                self._fd.close()  # type: ignore[union-attr]
        finally:
            _thread_lock.release()
```

- [ ] Запустить — ожидается PASS на текущей платформе:

```
cd backend && python -m pytest tests/contract/test_lock_contract.py -x
```
Ожидаемый вывод: `2 passed`.

- [ ] Запустить регрессию state/queue:

```
cd backend && python -m pytest tests/unit/test_state.py tests/unit/test_queue.py -x
```
Ожидаемый вывод: все `passed`.

- [ ] Commit:

```
git add backend/app/core/state.py backend/tests/contract/test_lock_contract.py && git commit -m "feat(stage1): ws-scoped STATE_DIR + cross-platform _StateLock (msvcrt/fcntl)"
```

---

## Task 11: migrate_legacy_state — идемпотентная миграция state/ -> workspaces/

- [ ] Создать падающий тест `backend/tests/contract/test_migrate_idempotent.py`:

```python
"""Contract: migrate_legacy_state is idempotent and sets workspaceId."""
from __future__ import annotations

import json
import pathlib
import subprocess

import pytest


def test_migrate_once_and_idempotent(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, timeout=30, check=True)

    legacy = tmp_path / "legacy-state"
    legacy.mkdir()
    (legacy / "work-state.json").write_text(json.dumps({"items": [{"id": "a", "title": "A", "status": "pending"}]}))
    (legacy / "decisions.log").write_text("x\n")

    home = tmp_path / "home"

    import app.core.migrate as migrate_mod

    monkeypatch.setattr(migrate_mod, "_LEGACY_STATE_DIR", legacy, raising=False)
    monkeypatch.setattr(migrate_mod, "_LEGACY_REPO", str(repo), raising=False)
    monkeypatch.setattr(migrate_mod, "_HOME", home, raising=False)

    res1 = migrate_mod.migrate_legacy_state()
    assert res1["migrated"] is True
    ws_id = res1["workspaceId"]
    moved = home / "workspaces" / ws_id / "state" / "work-state.json"
    assert moved.exists()
    items = json.loads(moved.read_text())["items"]
    assert items[0]["workspaceId"] == ws_id
    assert (home / "workspaces" / ".migrated").exists()

    res2 = migrate_mod.migrate_legacy_state()
    assert res2["migrated"] is False
```

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/contract/test_migrate_idempotent.py -x
```
Ожидаемый вывод: `ModuleNotFoundError: No module named 'app.core.migrate'`.

- [ ] Создать `backend/app/core/migrate.py`:

```python
"""One-shot idempotent migration of legacy state/ -> workspaces/<id>/state/ (umbrella §9)."""
from __future__ import annotations

import json
import logging
import pathlib
import shutil

log = logging.getLogger("hephaestus.backend.migrate")

# Overridable for tests; default to real config at call time.
_LEGACY_STATE_DIR: pathlib.Path | None = None
_LEGACY_REPO: str | None = None
_HOME: pathlib.Path | None = None


def _resolve() -> tuple[pathlib.Path, str, pathlib.Path]:
    from app.config import REPO, STATE_DIR
    from app.services.hephaestus_home import hephaestus_home

    legacy = _LEGACY_STATE_DIR or STATE_DIR
    repo = _LEGACY_REPO if _LEGACY_REPO is not None else REPO
    home = _HOME or hephaestus_home()
    return legacy, repo, home


def migrate_legacy_state() -> dict:
    legacy, repo, home = _resolve()
    ws_root = home / "workspaces"
    marker = ws_root / ".migrated"
    work_state = legacy / "work-state.json"

    if marker.exists() or not work_state.exists() or not repo:
        return {"migrated": False}

    from app.core.workspaces import WorkspaceRegistry

    if not (pathlib.Path(repo) / ".git").exists():
        log.warning("migrate: legacy REPO %s is not a git repo — skipping", repo)
        return {"migrated": False}

    reg = WorkspaceRegistry(home=home)
    ws = reg.create(repo, name=pathlib.Path(repo).name)
    dest = reg.state_dir(ws)
    dest.mkdir(parents=True, exist_ok=True)

    for entry in sorted(legacy.glob("*")):
        target = dest / entry.name
        if target.exists():
            continue
        if entry.is_dir():
            shutil.copytree(entry, target)
        else:
            shutil.copy2(entry, target)

    moved_state = dest / "work-state.json"
    try:
        data = json.loads(moved_state.read_text(encoding="utf-8"))
        for item in data.get("items", []):
            item.setdefault("workspaceId", ws.id)
        from app.core.state import _atomic_write

        _atomic_write(moved_state, json.dumps(data, indent=2, ensure_ascii=False))
    except Exception:
        log.warning("migrate: failed to stamp workspaceId on items")

    reg.update(ws.id, {"onboarded": False})
    reg.activate(ws.id)
    ws_root.mkdir(parents=True, exist_ok=True)
    marker.write_text(ws.id)
    log.info("migrate: legacy state migrated to workspace %s", ws.id)
    return {"migrated": True, "workspaceId": ws.id}
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/contract/test_migrate_idempotent.py -x
```
Ожидаемый вывод: `1 passed`.

- [ ] Commit:

```
git add backend/app/core/migrate.py backend/tests/contract/test_migrate_idempotent.py && git commit -m "feat(stage1): add idempotent migrate_legacy_state()"
```

---

## Task 12: driver.py — переписать loop-control поверх ProcessManager (без tmux)

- [ ] Создать падающий тест `backend/tests/integration/test_loop_start_stop.py`:

```python
"""Integration: driver start/stop via SYNC ProcessManager, no tmux, no asyncio.run(pm.*)."""
from __future__ import annotations

import pathlib
import sys


def test_start_then_status_running(monkeypatch, tmp_path: pathlib.Path) -> None:
    import app.core.driver as drv
    from app.core.process import ProcState

    monkeypatch.setattr(
        drv, "_loop_cmd", lambda: [sys.executable, "-c", "import time; time.sleep(30)"], raising=False
    )
    monkeypatch.setattr(drv, "_loop_cwd", lambda: str(tmp_path), raising=False)

    res = drv._start_loop({})
    assert res["ok"] is True
    st = drv._loop_status()
    assert st["process"]["state"] == ProcState.RUNNING.value
    assert "pid" in st["process"]  # R9
    res2 = drv._kill_loop_hard()
    assert res2["ok"] is True


def test_loop_status_idle_has_process_field() -> None:
    import app.core.driver as drv

    st = drv._loop_status()
    assert "process" in st
    assert "tmux" in st  # deprecated mirror retained
```

- [ ] Запустить — ожидается FAIL:

```
cd backend && python -m pytest tests/integration/test_loop_start_stop.py -x
```
Ожидаемый вывод: `AttributeError`/`ImportError` на старом tmux-driver.

- [ ] Переписать `backend/app/core/driver.py` целиком (**синхронно**, без `asyncio.run(pm.*)`, R1):

```python
"""Driver control via SYNC ProcessManager (D1, R1) — replaces tmux/pgrep/pkill loop mgmt.

All pm.* calls are synchronous; NEVER asyncio.run(pm.*). The loop is launched as a separate
supervised process: `python -m app.orchestrator.main --workspace <id>`.
"""
from __future__ import annotations

import logging
import sys

from app.core.process import ProcState, pm

log = logging.getLogger("hephaestus.backend.driver")


def _active_ws_id() -> str | None:
    try:
        from app.core.workspaces import registry

        ws = registry.active()
        return ws.id if ws is not None else None
    except Exception:
        return None


def _loop_cmd() -> list[str]:
    cmd = [sys.executable, "-m", "app.orchestrator.main"]
    ws_id = _active_ws_id()
    if ws_id:
        cmd += ["--workspace", ws_id]
    return cmd


def _loop_cwd() -> str:
    try:
        from app.core.workspaces import registry

        ws = registry.active()
        if ws is not None:
            return ws.repo_path
    except Exception:
        pass
    from app.config import LOOP_HOME

    return str(LOOP_HOME)


def _loop_status() -> dict:
    handle = pm.status("loop")  # sync (R1)
    return {
        "process": handle.model_dump(),  # contains 'pid' (R9)
        "tmux": handle.state == ProcState.RUNNING,  # deprecated mirror
        "driver_pid": handle.pid,  # deprecated; read process.pid
        "opencode_pids": handle.children,
    }


def _start_loop(opts: dict) -> dict:
    from app.config import _config_effective, filter_env_bits

    if pm.status("loop").state == ProcState.RUNNING:
        return {"ok": False, "error": "loop already running"}

    env_bits: dict[str, str] = dict(_config_effective())
    if "maxIter" in opts:
        try:
            env_bits["HEPHAESTUS_MAX_ITER"] = str(int(opts["maxIter"]))
        except (ValueError, TypeError):
            return {"ok": False, "error": "maxIter must be an integer"}
    if "tierReview" in opts:
        env_bits["HEPHAESTUS_TIER_REVIEW"] = "on" if opts["tierReview"] else "off"
    ws_id = _active_ws_id()
    if ws_id:
        env_bits["HEPHAESTUS_WORKSPACE_ID"] = ws_id
    env_bits = {k: str(v) for k, v in filter_env_bits(env_bits).items() if v not in (None, "")}

    try:
        handle = pm.start("loop", _loop_cmd(), cwd=_loop_cwd(), env=env_bits)
    except FileNotFoundError:
        return {"ok": False, "error": "python executable not found"}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "session": "loop", "env": env_bits, "pid": handle.pid}


def _stop_loop_soft() -> dict:
    pm.stop("loop")
    return {"ok": True, "note": "loop stop requested"}


def _kill_loop_hard() -> dict:
    if pm.status("loop").state != ProcState.RUNNING:
        return {"ok": True, "note": "loop was not running"}
    handle = pm.cancel("loop")
    return {"ok": True, "exit_code": handle.exit_code}
```

- [ ] Обновить `backend/app/core/scan.py` строки 11-18 — убрать `import shlex`, `import subprocess`, `from app.core.driver import _tmux_has`, `filter_env_bits` (если станет неиспользуем после Task 13). Заменить `_scan_running` (синхронно, **без** `asyncio.run`, R1):

```python
def _scan_running() -> bool:
    from app.core.process import ProcState, pm

    return pm.status("scan").state == ProcState.RUNNING
```

- [ ] Обновить `backend/app/core/iters.py` — удалить `from app.core.driver import _tmux_has` (строка 423) и заменить `loop_running = _tmux_has("hephaestus-loop")` (строка 429) синхронным чтением (**без** `asyncio.run`, R1):

```python
    from app.core.process import ProcState, pm

    loop_running = pm.status("loop").state == ProcState.RUNNING
```
(Строка 17 `from app.core.driver import _loop_status` остаётся валидной — функция сохранена.)

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/integration/test_loop_start_stop.py tests/unit/test_fsm.py -x
```
Ожидаемый вывод: все `passed`.

- [ ] Commit:

```
git add backend/app/core/driver.py backend/app/core/scan.py backend/app/core/iters.py backend/tests/integration/test_loop_start_stop.py && git commit -m "feat(stage1): rewrite driver/scan/iters loop-control on ProcessManager (drop tmux)"
```

---

## Task 13: scan.py — _scan_start через ProcessManager-стаб (без tmux)

- [ ] Переписать `_scan_start` в `backend/app/core/scan.py` (заменить блок строк 25-65):

```python
def _scan_start(opts: dict) -> dict:
    import sys

    from app.config import LOOP_HOME
    from app.core.process import ProcState, pm

    if pm.status("scan").state == ProcState.RUNNING:  # sync (R1)
        return {"ok": False, "error": "a scan is already running"}
    try:
        scanners_val = int(opts.get("scanners") or 6)
        if scanners_val < 1 or scanners_val > 50:
            return {"ok": False, "error": "scanners must be between 1 and 50"}
    except (ValueError, TypeError):
        return {"ok": False, "error": "scanners must be an integer"}
    try:
        reviewers_val = int(opts.get("reviewers") or 2)
        if reviewers_val < 1 or reviewers_val > 50:
            return {"ok": False, "error": "reviewers must be between 1 and 50"}
    except (ValueError, TypeError):
        return {"ok": False, "error": "reviewers must be an integer"}
    scope = (opts.get("scope") or "").strip()
    if scope and not re.match(r"^[A-Za-z0-9_./\- ]{1,200}$", scope):
        return {"ok": False, "error": "scope contains forbidden characters"}

    env_bits = {"SCANNERS": str(scanners_val), "REVIEWERS": str(reviewers_val)}
    if scope:
        env_bits["SCOPE"] = scope
    try:
        from app.core.workspaces import registry

        ws = registry.active()
        cwd = ws.repo_path if ws else str(LOOP_HOME)
        if ws is not None:
            env_bits["HEPHAESTUS_WORKSPACE_ID"] = ws.id
    except Exception:
        cwd = str(LOOP_HOME)

    # Stage 1: native map-reduce scan orchestration lands in Stage 2 (R19). Start a managed
    # placeholder process so the session lifecycle/UI plumbing works cross-platform.
    cmd = [sys.executable, "-c", "import time; time.sleep(1)"]
    try:
        pm.start("scan", cmd, cwd=cwd, env=env_bits)  # sync (R1)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {
        "ok": True,
        "session": "scan",
        "scanners": scanners_val,
        "reviewers": reviewers_val,
        "scope": scope,
    }
```

- [ ] Добавить тест в `backend/tests/integration/test_loop_start_stop.py`:

```python
def test_scan_start_uses_process_manager(tmp_path) -> None:
    import app.core.scan as scan_mod

    res = scan_mod._scan_start({"scanners": 2, "reviewers": 1, "scope": ""})
    assert res["ok"] is True
    assert res["session"] == "scan"
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/integration/test_loop_start_stop.py -x
```
Ожидаемый вывод: все `passed`.

- [ ] Commit:

```
git add backend/app/core/scan.py backend/tests/integration/test_loop_start_stop.py && git commit -m "feat(stage1): scan start via ProcessManager stub (drop tmux, ws-scoped)"
```

---

## Task 14: fsm.py — AgentRunner + VerifyRunner + ws-параметры (без bash)

- [ ] Создать страховочный интеграционный тест `backend/tests/integration/test_verify_from_memory.py`:

```python
"""Integration: FSM verify path delegates to VerifyRunner reading verify.md."""
from __future__ import annotations

import pathlib
import sys

import pytest


@pytest.mark.asyncio
async def test_verify_runner_from_memory(tmp_path: pathlib.Path) -> None:
    from app.core.verify import VerifyRunner
    from app.models.workspace import AgentRef, AgentsConfig, RepoProfile
    from app.services.project_memory import ProjectMemory

    ws = RepoProfile(
        id="abc123",
        name="demo",
        repo_path=str(tmp_path),
        agents=AgentsConfig(
            primary=AgentRef(provider="anthropic", model="claude-opus-4-8"),
            fallback=AgentRef(provider="openai", model="gpt-4.1"),
        ),
    )
    py = sys.executable.replace("\\", "/")
    ProjectMemory(ws).write_doc(
        "verify", f"## commands\n```sh\n\"{py}\" -c \"print('ok')\"\n```\n", source="profiler"
    )
    res = await VerifyRunner(ws).run(cwd=str(tmp_path), log_path=tmp_path / "verify.log", timeout_sec=30)
    assert res.ok is True
    assert "ok" in (tmp_path / "verify.log").read_text()
```

- [ ] Запустить — ожидается PASS (VerifyRunner готов из Task 5):

```
cd backend && python -m pytest tests/integration/test_verify_from_memory.py -x
```
Ожидаемый вывод: `1 passed`.

- [ ] В `backend/app/orchestrator/fsm.py` добавить разрешение ws в `OrchestratorFSM.__init__` (строки 58-62) и helper `_resolve_ws`:

```python
    def __init__(self) -> None:
        from app.core.process import pm

        self.phase: Phase = Phase.IDLE
        self.current_item: dict | None = None
        self.iter_dir: pathlib.Path | None = None
        self._stop_requested = False
        self._pm = pm                      # module-singleton (R15); never read pm internals
        self._ws = self._resolve_ws()

    def _resolve_ws(self):
        import os

        from app.core.workspaces import active_workspace, registry

        ws_id = os.environ.get("HEPHAESTUS_WORKSPACE_ID")
        if ws_id:
            ws = registry.get(ws_id)
            if ws is not None:
                return ws
        return active_workspace()
```

- [ ] Заменить `_run_opencode` (строки 237-269) и удалить `_run_opencode_subprocess` (строки 271-326). Новый `_run_opencode`:

```python
    async def _run_opencode(self, item: dict, prompt: str) -> int | None:
        from app.core.process import pm
        from app.services.opencode_runner import AgentRunner

        if self._ws is None or self.iter_dir is None:
            log.error("no active workspace / iter_dir for opencode run")
            return -1

        prompt_file = self.iter_dir / "prompt.md"
        prompt_file.write_text(prompt, encoding="utf-8")

        runner = AgentRunner(pm)
        result = await runner.run_with_fallback(
            self._ws.agents,
            prompt_file=prompt_file,
            cwd=self._ws.repo_path,
            iter_dir=self.iter_dir,
            timeout_sec=self._ws.verify_timeout_sec,
        )
        if result.refused:
            log.warning("Agent refused task")
            return None
        return result.exit_code
```

- [ ] Заменить `_verify` (строки 328-360):

```python
    async def _verify(self, item: dict) -> bool:
        from app.core.verify import VerifyRunner

        if self._ws is None:
            return True
        log_path = (self.iter_dir / "verify.log") if self.iter_dir else pathlib.Path("verify.log")
        res = await VerifyRunner(self._ws).run(
            cwd=self._ws.repo_path,
            log_path=log_path,
            timeout_sec=self._ws.verify_timeout_sec,
        )
        if not res.ok:
            log.warning("verify failed: %s", res.failed_command)
        return res.ok
```

- [ ] Обновить начало `_preflight` (строки 184-200) — читать из `self._ws`:

```python
    async def _preflight(self, item: dict) -> bool:
        from app.core.helpers import _run
        from app.core.state import _read_state, _StateLock, _write_state
        from app.core.workspaces import registry

        if self._ws is None:
            log.error("no active workspace")
            return False
        ws = self._ws
        item_id = item.get("id", "?")
        branch = f"{ws.branch_prefix}/{item_id[:40]}-{int(time.time())}"
        rc = _run(["git", "checkout", "-b", branch, f"{ws.remote}/{ws.base_branch}"], cwd=ws.repo_path)
        if not rc:
            log.error("Failed to create branch %s", branch)
            return False

        # Монотонный последовательный iter-NNNN (R12): max существующих + 1.
        # loop-сессия эксклюзивна (ProcessManager), поэтому single-writer — гонок нет.
        sd = registry.state_dir(ws)
        existing = [int(p.name[5:]) for p in sd.glob("iter-*") if p.name[5:].isdigit()]
        seq = (max(existing) + 1) if existing else 1
        self.iter_dir = sd / f"iter-{seq:04d}"
        self.iter_dir.mkdir(parents=True, exist_ok=True)
```
(Хвост `_preflight` — `run-tag`, state-update, `item["branch"]`/`item["lastIter"]` — без изменений.)

- [ ] Обновить `_commit` (строки 362-394) — заменить `from app.config import BASE_BRANCH, REMOTE, REPO` на:

```python
        if self._ws is None:
            return False
        ws = self._ws
        branch = item.get("branch")
        if not branch:
            return False
        ahead = _run(["git", "rev-list", "--count", f"{ws.remote}/{ws.base_branch}..{branch}"], cwd=ws.repo_path)
```
и далее по телу заменить `cwd=REPO` -> `cwd=ws.repo_path`.

- [ ] Обновить `_cleanup` (строки 455-478) и `_get_repo` (строки 480-483):

```python
    async def _cleanup(self, item: dict) -> None:
        from app.core.helpers import _run
        from app.core.workspaces import registry

        branch = item.get("branch")
        if branch and self._ws is not None and self._ws.autopush:
            _run(["git", "push", self._ws.remote, branch], cwd=self._get_repo())

        if self._ws is not None:
            cp_path = registry.state_dir(self._ws) / "fsm-checkpoint.json"
            with __import__("contextlib").suppress(Exception):
                cp_path.unlink(missing_ok=True)

        self.current_item = None
        self.iter_dir = None

    def _get_repo(self) -> str:
        return self._ws.repo_path if self._ws else ""
```

- [ ] Запустить регрессию FSM (тест может требовать создания tmp git-репо + активации ws через `monkeypatch.setenv("HEPHAESTUS_WORKSPACE_ID", ...)` если он завязан на REPO):

```
cd backend && python -m pytest tests/unit/test_fsm.py tests/integration/test_verify_from_memory.py -x
```
Ожидаемый вывод: все `passed`.

- [ ] Commit:

```
git add backend/app/orchestrator/fsm.py backend/tests/integration/test_verify_from_memory.py backend/tests/unit/test_fsm.py && git commit -m "feat(stage1): FSM uses AgentRunner+VerifyRunner, threads ws (no bash)"
```

---

## Task 15: GitService(ws) обёртка + MergePreflight-заглушки

- [ ] Добавить в конец `backend/app/core/git.py` (после `BRANCH_ACTIONS`, строка 250):

```python
from pydantic import BaseModel


class MergePreflight(BaseModel):
    clean_tree: bool
    verify_green: bool
    validation_passed: bool
    base_branch: str
    conflicts: list[str] = []
    ok: bool


class GitService:
    """Workspace-scoped git ops (umbrella §5.4). Merge bodies land in Stage 3."""

    def __init__(self, ws) -> None:  # ws: RepoProfile
        self.ws = ws

    def branches(self) -> list[dict]:
        raw = _run(
            [
                "git",
                "for-each-ref",
                "--sort=-committerdate",
                "--format=%(refname:short)|%(committerdate:iso8601)|%(subject)|%(objectname:short)",
                f"refs/heads/{self.ws.branch_prefix}/",
            ],
            cwd=self.ws.repo_path,
        )
        out: list[dict] = []
        for line in (raw or "").splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4:
                name, ts, subj, sha = parts
                ahead = _run(
                    ["git", "rev-list", "--count", f"{self.ws.remote}/{self.ws.base_branch}..{name}"],
                    cwd=self.ws.repo_path,
                    default="?",
                )
                out.append({"name": name, "lastCommitAt": ts, "subject": subj, "sha": sha, "ahead": ahead})
        return out

    def create_branch(self, name: str) -> bool:
        return bool(
            _run(
                ["git", "checkout", "-b", name, f"{self.ws.remote}/{self.ws.base_branch}"],
                cwd=self.ws.repo_path,
            )
        )

    def commit(self, msg: str) -> str | None:
        _run(["git", "add", "-A"], cwd=self.ws.repo_path)
        if not _run(["git", "diff", "--cached", "--stat"], cwd=self.ws.repo_path):
            return None
        _run(["git", "commit", "-m", msg], cwd=self.ws.repo_path)
        return _run(["git", "rev-parse", "--short", "HEAD"], cwd=self.ws.repo_path) or None

    def diff(self, branch: str) -> str:
        return _run(
            ["git", "diff", f"{self.ws.remote}/{self.ws.base_branch}..{branch}"],
            cwd=self.ws.repo_path,
            default="",
        )

    def merge_preflight(self, branch: str) -> MergePreflight:
        # Stage 3 fills verify_green/validation_passed/conflicts. Stage 1: clean-tree only.
        clean = not _run(["git", "status", "--porcelain"], cwd=self.ws.repo_path, default="x")
        return MergePreflight(
            clean_tree=clean,
            verify_green=False,
            validation_passed=False,
            base_branch=self.ws.base_branch,
            conflicts=[],
            ok=False,
        )

    async def merge_to_base(self, branch: str, *, push: bool) -> dict:
        # Body implemented in Stage 3 (D11). Stage 1 declares the contract.
        return {"ok": False, "error": "merge_to_base not implemented until Stage 3"}
```

- [ ] Создать тест `backend/tests/unit/test_git_service.py`:

```python
"""Unit: GitService is workspace-scoped and exposes Stage-3 stubs."""
from __future__ import annotations

import pathlib
import subprocess

import pytest


def _ws(tmp_path: pathlib.Path):
    from app.models.workspace import AgentRef, AgentsConfig, RepoProfile

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, timeout=30, check=True)
    return RepoProfile(
        id="abc",
        name="repo",
        repo_path=str(repo),
        agents=AgentsConfig(
            primary=AgentRef(provider="anthropic", model="claude-opus-4-8"),
            fallback=AgentRef(provider="openai", model="gpt-4.1"),
        ),
    )


def test_branches_empty(tmp_path: pathlib.Path) -> None:
    from app.core.git import GitService

    assert GitService(_ws(tmp_path)).branches() == []


def test_merge_preflight_shape(tmp_path: pathlib.Path) -> None:
    from app.core.git import GitService, MergePreflight

    pf = GitService(_ws(tmp_path)).merge_preflight("auto/x")
    assert isinstance(pf, MergePreflight)
    assert pf.base_branch == "main"
    assert pf.ok is False


@pytest.mark.asyncio
async def test_merge_to_base_stub(tmp_path: pathlib.Path) -> None:
    from app.core.git import GitService

    res = await GitService(_ws(tmp_path)).merge_to_base("auto/x", push=False)
    assert res["ok"] is False
    assert "Stage 3" in res["error"]
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/unit/test_git_service.py -x
```
Ожидаемый вывод: `3 passed`.

- [ ] Commit:

```
git add backend/app/core/git.py backend/tests/unit/test_git_service.py && git commit -m "feat(stage1): add GitService(ws) wrapper + MergePreflight stubs"
```

---

## Task 16: workspaces API-роутер + requests + main.py регистрация

- [ ] Добавить request-модели в конец `backend/app/models/requests.py`:

```python
class OnboardRequest(BaseModel):
    repoPath: str
    name: str | None = None


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = None
    baseBranch: str | None = None
    remote: str | None = None
    branchPrefix: str | None = None
    strictness: str | None = None
    agents: dict | None = None
    review: dict | None = None
    verifySource: str | None = None
    verifyCommandsOverride: list[str] | None = None
    verifyTimeoutSec: int | None = None
    autopush: bool | None = None
```

- [ ] Создать `backend/app/api/v1/workspaces.py`:

```python
"""Workspace registry endpoints (Stage 1).

Onboarding runs the Profiler as a SUPERVISED CHILD PROCESS via the sync ProcessManager
(pm.start("profiler", ...)), NOT in-process. Inside that process orchestrator/main.py
(--profile <id>) owns its own asyncio loop and calls Profiler.onboard() (R1/R2).
Status is read synchronously (pm.status), never via asyncio.run(pm.*).
"""
from __future__ import annotations

import logging
import sys

from fastapi import APIRouter

from app.core.process import ProcState, pm
from app.core.workspaces import registry
from app.models.requests import OnboardRequest, WorkspaceUpdateRequest

router = APIRouter()
log = logging.getLogger("hephaestus.backend.workspaces")


def _profiler_cmd(ws_id: str) -> list[str]:
    return [sys.executable, "-m", "app.orchestrator.main", "--profile", ws_id]


def _start_profiler(ws_id: str, repo_path: str) -> None:
    """Spawn the profiler as a supervised process (sync, R1). Best-effort."""
    if pm.status("profiler").state == ProcState.RUNNING:
        return
    try:
        pm.start("profiler", _profiler_cmd(ws_id), cwd=repo_path, env={"HEPHAESTUS_WORKSPACE_ID": ws_id})
    except Exception:  # noqa: BLE001 — onboarding launch must not crash the request
        log.exception("profiler launch failed for %s", ws_id)


@router.get("/api/v1/workspaces")
def list_workspaces() -> dict:
    active = registry.active()
    return {
        "ok": True,
        "workspaces": [w.model_dump(by_alias=True) for w in registry.list()],
        "activeId": active.id if active else None,
    }


@router.post("/api/v1/workspaces")
def create_workspace(body: OnboardRequest) -> dict:
    try:
        ws = registry.create(body.repoPath, name=body.name)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    _start_profiler(ws.id, ws.repo_path)
    return {"ok": True, "workspace": ws.model_dump(by_alias=True)}


@router.get("/api/v1/workspaces/{ws_id}")
def get_workspace(ws_id: str) -> dict:
    ws = registry.get(ws_id)
    if ws is None:
        return {"ok": False, "error": "workspace not found"}
    onboarding = pm.status("profiler")  # sync (R1)
    return {"ok": True, "workspace": ws.model_dump(by_alias=True), "onboarding": onboarding.model_dump()}


@router.put("/api/v1/workspaces/{ws_id}")
def update_workspace(ws_id: str, body: WorkspaceUpdateRequest) -> dict:
    patch = dict(body.model_dump(exclude_none=True))
    try:
        ws = registry.update(ws_id, patch)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "workspace": ws.model_dump(by_alias=True)}


@router.post("/api/v1/workspaces/{ws_id}/activate")
def activate_workspace(ws_id: str) -> dict:
    if registry.get(ws_id) is None:
        return {"ok": False, "error": "workspace not found"}
    registry.activate(ws_id)
    return {"ok": True, "activeId": ws_id}
```

- [ ] В `backend/app/main.py` добавить импорт (после строки 148):

```python
from app.api.v1.workspaces import router as workspaces_router  # noqa: E402
```
и include (после `app.include_router(repos_router)`):

```python
app.include_router(workspaces_router)
```

- [ ] В `backend/app/main.py` lifespan startup (строки 90-92) — убрать `tmux` и вызвать миграцию:

```python
    for tool_name in ("git", "opencode"):
        if not _check_tool_exists(tool_name):
            log.warning("startup check: '%s' not found on PATH", tool_name)

    from app.core.migrate import migrate_legacy_state

    with __import__("contextlib").suppress(Exception):
        migrate_legacy_state()
```

- [ ] В `backend/app/main.py` shutdown (строки 103-108) заменить `pkill` на синхронный `pm.cancel_all()` (R1, без `await`):

```python
    from app.core.process import pm

    with __import__("contextlib").suppress(Exception):
        pm.cancel_all()
```

- [ ] Создать тест `backend/tests/integration/test_onboard_flow.py`:

```python
"""Integration: POST /api/v1/workspaces onboards a git repo (Profiler mocked)."""
from __future__ import annotations

import pathlib
import subprocess

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def _patched_home(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HEPHAESTUS_HOME", str(tmp_path / "home"))
    import app.core.workspaces as wsmod

    monkeypatch.setattr(wsmod, "registry", wsmod.WorkspaceRegistry(home=tmp_path / "home"))
    import app.api.v1.workspaces as wsapi

    # Don't actually spawn a profiler process during the onboard test.
    monkeypatch.setattr(wsapi, "_start_profiler", lambda _ws_id, _repo: None)
    monkeypatch.setattr(wsapi, "registry", wsmod.registry)
    return tmp_path


def test_onboard_creates_profile(_patched_home: pathlib.Path) -> None:
    repo = _patched_home / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, timeout=30, check=True)

    from app.main import app

    client = TestClient(app)
    r = client.post("/api/v1/workspaces", json={"repoPath": str(repo), "name": "repo"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    ws_id = data["workspace"]["id"]

    r2 = client.post(f"/api/v1/workspaces/{ws_id}/activate")
    assert r2.json()["ok"] is True

    r3 = client.get("/api/v1/workspaces")
    assert r3.json()["activeId"] == ws_id


def test_onboard_rejects_non_git(_patched_home: pathlib.Path) -> None:
    plain = _patched_home / "plain"
    plain.mkdir()
    from app.main import app

    client = TestClient(app)
    r = client.post("/api/v1/workspaces", json={"repoPath": str(plain)})
    assert r.json()["ok"] is False
    assert "not a git repository" in r.json()["error"]
```

- [ ] Запустить — ожидается PASS:

```
cd backend && python -m pytest tests/integration/test_onboard_flow.py -x
```
Ожидаемый вывод: `2 passed`.

- [ ] Commit:

```
git add backend/app/api/v1/workspaces.py backend/app/models/requests.py backend/app/main.py backend/tests/integration/test_onboard_flow.py && git commit -m "feat(stage1): add workspaces router + onboarding flow + migrate on startup"
```

---

## Task 17: Task-поля в domain.py + loopStatus contract-тест

- [ ] Добавить поля в `backend/app/models/domain.py` `Item` (после строки 45, umbrella §4.2):

```python
    workspace_id: str | None = Field(None, alias="workspaceId")
    depends_on: list[str] = Field(default_factory=list, alias="dependsOn")
    blocks: list[str] = Field(default_factory=list)
    order_index: int = Field(0, alias="orderIndex")
    epic_id: str | None = Field(None, alias="epicId")
    parent: str | None = None
    conflict_group: str | None = Field(None, alias="conflictGroup")
    validation: dict | None = None
    result_summary: str = Field("", alias="resultSummary")
    diff_ref: str | None = Field(None, alias="diffRef")
```

- [ ] Создать `backend/tests/contract/test_loopstatus_shape.py`:

```python
"""Contract: GET /api/state exposes loop.process and deprecated tmux mirror."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_loopstatus_has_process_field() -> None:
    from app.main import app

    client = TestClient(app)
    r = client.get("/api/state")
    assert r.status_code == 200
    loop = r.json().get("loop") or {}
    assert "process" in loop
    assert set(loop["process"]).issuperset({"state", "pid", "children"})
    assert "tmux" in loop
```

- [ ] Запустить (контракт нового поля Task валидируется существующим `test_existing_state.py`):

```
cd backend && python -m pytest tests/contract/test_loopstatus_shape.py tests/contract/test_existing_state.py -x
```
Ожидаемый вывод: все `passed`.

- [ ] Commit:

```
git add backend/app/models/domain.py backend/tests/contract/test_loopstatus_shape.py && git commit -m "feat(stage1): add Task fields to domain model + loopStatus.process contract"
```

---

## Task 18: Frontend — типы, loop store, workspace store, views, router

- [ ] В `frontend/src/types/api.ts` заменить `LoopStatus` (строки 82-86) и добавить типы:

```typescript
export interface ProcessManagerStatus {
  state: 'idle' | 'running' | 'stopping' | 'exited'
  pid: number | null
  children: number[]
}
export interface LoopStatus {
  process: ProcessManagerStatus
  tmux?: boolean
  driver_pid?: number | null
  opencode_pids?: number[]
}
export interface AgentRef { provider: string; model: string; agent?: string | null }
export interface RepoProfile {
  id: string; name: string; repoPath: string; baseBranch: string; remote: string
  branchPrefix: string; strictness: string; onboarded: boolean
  agents: { useModels: boolean; primary: AgentRef; fallback: AgentRef }
  verifySource: 'agent' | 'manual'; verifyCommandsOverride: string[]
}
```

> Бэкенд `_loop_status()` отдаёт `process: ProcessHandle.model_dump()` с полем `pid` (R9 — единое имя сквозь стек). Frontend читает `process.pid` напрямую, без скрытого нормализатора `driverPid`. Legacy-поле `driver_pid` (snake) остаётся только как fallback-источник из старого `_loop_status`.

- [ ] Обновить `frontend/src/stores/loop.ts` — импорт типов, дефолт `status`, `pollLoop`:

```typescript
import type { LoopStatus, ProcessManagerStatus } from '@/types/api'
```
```typescript
  const status = ref<LoopStatus>({
    process: { state: 'idle', pid: null, children: [] },
    tmux: false, driver_pid: null, opencode_pids: [],
  })

  async function pollLoop() {
    try {
      loading.value = true
      const state = await api.getState()
      const ls = state.loopStatus
      const ps = ls.process ?? { state: 'idle', pid: null, children: [] }
      status.value = {
        process: {
          state: (ps.state as ProcessManagerStatus['state']) ?? 'idle',
          pid: ps.pid ?? ls.driver_pid ?? null,
          children: ps.children ?? ls.opencode_pids ?? [],
        },
        tmux: ls.tmux,
        driver_pid: ls.driver_pid,
        opencode_pids: ls.opencode_pids,
      }
      killswitchPresent.value = false
    } catch {
      // silent
    } finally {
      loading.value = false
    }
  }
```

- [ ] Создать `frontend/src/stores/workspace.ts`:

```typescript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { RepoProfile } from '@/types/api'
import { api } from '@/api/client'

export const useWorkspaceStore = defineStore('workspace', () => {
  const workspaces = ref<RepoProfile[]>([])
  const activeId = ref<string | null>(null)
  const active = computed(() => workspaces.value.find(w => w.id === activeId.value) ?? null)

  async function fetchWorkspaces(): Promise<void> {
    const res = await api.listWorkspaces()
    workspaces.value = res.workspaces
    activeId.value = res.activeId
  }
  async function onboard(repoPath: string, name?: string): Promise<RepoProfile> {
    const res = await api.onboard(repoPath, name)
    await fetchWorkspaces()
    return res.workspace
  }
  async function activate(id: string): Promise<void> {
    await api.activateWorkspace(id)
    activeId.value = id
  }
  async function updateProfile(id: string, patch: Partial<RepoProfile>): Promise<void> {
    await api.updateWorkspace(id, patch)
    await fetchWorkspaces()
  }

  return { workspaces, activeId, active, fetchWorkspaces, onboard, activate, updateProfile }
})
```

- [ ] Добавить методы в `frontend/src/api/client.ts` (импорт типов в начале + методы в объект `api`):

```typescript
import type { RepoProfile, ProcessManagerStatus } from '@/types/api'
```
```typescript
  listWorkspaces: () =>
    request<{ ok: boolean; workspaces: RepoProfile[]; activeId: string | null }>('/api/v1/workspaces'),
  onboard: (repoPath: string, name?: string) =>
    request<{ ok: boolean; workspace: RepoProfile }>('/api/v1/workspaces', {
      method: 'POST', body: JSON.stringify({ repoPath, name }),
    }),
  getWorkspace: (id: string) =>
    request<{ ok: boolean; workspace: RepoProfile; onboarding: ProcessManagerStatus }>(`/api/v1/workspaces/${id}`),
  updateWorkspace: (id: string, patch: Partial<RepoProfile>) =>
    request<{ ok: boolean; workspace: RepoProfile }>(`/api/v1/workspaces/${id}`, {
      method: 'PUT', body: JSON.stringify(patch),
    }),
  activateWorkspace: (id: string) =>
    request<{ ok: boolean; activeId: string }>(`/api/v1/workspaces/${id}/activate`, { method: 'POST' }),
```

- [ ] Создать `frontend/src/views/OnboardView.vue`:

```vue
<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useWorkspaceStore } from '@/stores/workspace'
import { api } from '@/api/client'

const router = useRouter()
const ws = useWorkspaceStore()
const repoPath = ref('')
const busy = ref(false)
const error = ref('')
const phase = ref('')

async function onOnboard() {
  error.value = ''
  busy.value = true
  try {
    const profile = await ws.onboard(repoPath.value.trim())
    phase.value = 'running'
    for (let i = 0; i < 120; i++) {
      const res = await api.getWorkspace(profile.id)
      phase.value = res.onboarding.state
      if (res.onboarding.state === 'exited' || res.onboarding.state === 'idle') break
      await new Promise(r => setTimeout(r, 1500))
    }
    await ws.activate(profile.id)
    router.push('/board')
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="onboard">
    <h1>Онбординг репозитория</h1>
    <input v-model="repoPath" placeholder="/абсолютный/путь/к/репо" :disabled="busy" />
    <button :disabled="busy || !repoPath" @click="onOnboard">Онбордить</button>
    <p v-if="phase">Profiler: {{ phase }}</p>
    <p v-if="error" class="err">{{ error }}</p>
  </div>
</template>
```

- [ ] Создать `frontend/src/views/SettingsView.vue`:

```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useWorkspaceStore } from '@/stores/workspace'
import type { RepoProfile } from '@/types/api'

const ws = useWorkspaceStore()
const draft = ref<Partial<RepoProfile>>({})

onMounted(async () => {
  await ws.fetchWorkspaces()
  if (ws.active) draft.value = { ...ws.active }
})

async function save() {
  if (!ws.activeId) return
  await ws.updateProfile(ws.activeId, draft.value)
}
</script>

<template>
  <div class="settings" v-if="ws.active">
    <h1>Настройки воркспейса</h1>
    <label>Strictness
      <select v-model="draft.strictness">
        <option value="strict">strict</option>
        <option value="standard">standard</option>
        <option value="permissive">permissive</option>
      </select>
    </label>
    <label>Verify source
      <select v-model="draft.verifySource">
        <option value="agent">agent</option>
        <option value="manual">manual</option>
      </select>
    </label>
    <button @click="save">Сохранить</button>
  </div>
  <div v-else>Нет активного воркспейса — <router-link to="/onboard">онбордить репо</router-link>.</div>
</template>
```

- [ ] Создать `frontend/src/components/WorkspaceSwitcher.vue`:

```vue
<script setup lang="ts">
import { onMounted } from 'vue'
import { useWorkspaceStore } from '@/stores/workspace'

const ws = useWorkspaceStore()
onMounted(() => ws.fetchWorkspaces())

async function onChange(e: Event) {
  const id = (e.target as HTMLSelectElement).value
  if (id) await ws.activate(id)
}
</script>

<template>
  <select :value="ws.activeId ?? ''" @change="onChange" class="ws-switch">
    <option value="" disabled>Воркспейс…</option>
    <option v-for="w in ws.workspaces" :key="w.id" :value="w.id">{{ w.name }}</option>
  </select>
</template>
```

- [ ] В `frontend/src/router.ts` добавить роуты в массив `routes`:

```typescript
  { path: '/onboard', name: 'onboard', component: () => import('@/views/OnboardView.vue') },
  { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
```

- [ ] В `frontend/src/components/AppShell.vue` добавить импорт/компонент и заменить `loopRunning`:

```typescript
import WorkspaceSwitcher from '@/components/WorkspaceSwitcher.vue'
const loopRunning = computed(() => loopStore.status.process.state === 'running')
```
(вставить `<WorkspaceSwitcher />` в топ-бар-шаблон рядом со Start/Stop кнопками.)

- [ ] Собрать и проверить типы:

```
cd frontend && pnpm install && pnpm exec vue-tsc --noEmit && pnpm build
```
Ожидаемый вывод: `vue-tsc` без ошибок; `build` создаёт `dist/`.

- [ ] Commit:

```
git add frontend/src && git commit -m "feat(stage1): frontend workspace store/views + LoopStatus.process"
```

---

## Task 19: Линтинг, типизация, полный прогон, CI matrix

- [ ] Прогнать ruff с автофиксом и проверкой (убрать неиспользуемые импорты в scan.py, мёртвые символы):

```
cd backend && python -m ruff check app/ --fix && python -m ruff check app/
```
Ожидаемый вывод: `All checks passed!`.

- [ ] Прогнать mypy --strict:

```
cd backend && python -m mypy --strict app/
```
Ожидаемый вывод: `Success: no issues found` (при ошибках в новых модулях — добавить аннотации; `type: ignore` только помеченные в плане).

- [ ] Прогнать весь backend-набор:

```
cd backend && python -m pytest tests -x
```
Ожидаемый вывод: все `passed`.

- [ ] Проверить отсутствие tmux/pgrep/pkill в backend (exit criteria §9.3) — Grep-инструментом по `backend/app` на паттерн `tmux|pgrep|pkill`. Ожидается ноль совпадений вне комментариев истории.

- [ ] Обновить `.github/workflows/hephaestus-loop-ci.yml` — `strategy.matrix.os: [ubuntu-latest, windows-latest]`; шаги `python -m ruff check app/`, `python -m mypy --strict app/`, `python -m pytest tests -x` (в `backend/`); frontend job — `pnpm exec vue-tsc --noEmit` + `pnpm exec vitest run`. (Если файла нет — создать минимальный workflow с этими шагами.)

- [ ] Commit:

```
git add backend frontend .github && git commit -m "chore(stage1): ruff/mypy clean, full test pass, Windows CI matrix"
```

---

## Task 20: Удаление bash/tmux/legacy-dashboard (последний коммит этапа)

> Выполнять ТОЛЬКО после того, как Task 1-19 зелёные на обеих ОС CI. Откат до этого коммита восстанавливает bash из git-истории (Rollback §10).

- [ ] Удалить bash-скрипты и central-config:

```
git rm driver.sh start-loop.sh verify.sh tier-review.sh repo-scan.sh prompt-build.sh lib/common.sh config.env
```

- [ ] Удалить legacy-dashboard:

```
git rm -r dashboard
```

- [ ] Проверить отсутствие ссылок на удалённые файлы — Grep-инструментом по всему репо на `verify.sh|driver.sh|repo-scan.sh|tier-review.sh|start-loop.sh|prompt-build.sh|lib/common.sh|dashboard/server`. Допустимы только упоминания в `docs/` (история/спека). При ссылках в коде — исправить.

- [ ] Прогнать полный backend-набор повторно (удаление ничего не сломало):

```
cd backend && python -m pytest tests -x
```
Ожидаемый вывод: все `passed`.

- [ ] Commit:

```
git commit -m "chore(stage1): remove bash scripts, config.env, legacy dashboard (D1/D7)"
```

---

## Exit Criteria (сверка перед завершением этапа)

- [ ] `pytest backend/tests -x` зелёный на ubuntu-latest и windows-latest (CI matrix).
- [ ] `ruff check backend/` и `mypy --strict backend/app/` без ошибок.
- [ ] Grep `tmux|pgrep|pkill` по `backend/app` пуст (кроме комментариев). Bash-скрипты и `dashboard/` удалены.
- [ ] `_config_effective()` не содержит vendor-дефолтов; `config.REPO` дефолт не `/home/starsinc/hephaestus-repo` (тест `test_config_dehephaestus.py`).
- [ ] На Windows: `POST /api/v1/workspaces {repoPath}` онбордит репо, создаёт `<repo>/.hephaestus/memory/{MEMORY,architecture,verify,conventions,tech-debt}.md` с валидным frontmatter; `POST /api/driver/start` поднимает loop (`process.state==running`), `/stop` гасит.
- [ ] `VerifyRunner` исполняет команды из `verify.md` (не pnpm); manual override работает (`test_verify_runner.py`).
- [ ] `pnpm build` во frontend зелёный; `vue-tsc --noEmit` чистый; OnboardView/SettingsView/WorkspaceSwitcher рендерятся; `LoopStatus.process` читается без tmux.
- [ ] `migrate_legacy_state()` идемпотентен; `.migrated`-маркер; `workspaceId` проставлен (`test_migrate_idempotent.py`).

---

## Out of Scope (Этапы 2/3)

- Этап 2: нативный map-reduce scan (`scan.py` orchestration), декомпозиция в `Task` с `depends_on`/`order_index`/`conflict_group`, `backend/app/core/task_graph.py` (DAG + `can_reorder`), `PATCH /api/v1/tasks/{id}/reorder`, scan/task-writers памяти, memory-эндпоинты `GET/PUT /api/v1/workspaces/{id}/memory/{doc}`.
- Этап 3: воронка валидации (D10) — validators/arbiters/final, `ValidationResult`, статусы `in_review`/`needs_revision`-петля, замена no-op `_tier_review`; `GitService.merge_to_base` тело + merge-preflight (D11), `GET/POST /api/v1/branches/{name}/merge[-preflight]`, frontend merge-UI и визуализация валидации.

Этап 1 готовит точки расширения: поля `RepoProfile.review/strictness/agents.validators` существуют; `GitService.merge_preflight/merge_to_base` объявлены заглушками; `scan.py` запускается через `ProcessManager`-стаб.

## Open Questions (требуют решения пользователя)

1. **Нейтральные дефолты агентов.** `WorkspaceRegistry._NEUTRAL_AGENTS` использует `anthropic/claude-opus-4-8` (primary) и `openai/gpt-4.1` (fallback) как плейсхолдеры до онбординга. Спека требует «нейтральные» дефолты, но конкретных моделей не фиксирует. Подтвердить выбор или задать через `HEPHAESTUS_AGENT_PROVIDER`/`HEPHAESTUS_AGENT_MODEL`.
2. **Флаги CLI `opencode run` — РЕШЕНО** (сверено с установленным **opencode 1.16.0** через `opencode run --help`). `_build_cmd` использует `opencode run --format json [--agent <a> | --model <provider/model>]` + промпт ПОЗИЦИОННЫМ message; флага `--output` нет — JSON-события идут в **stdout** и захватываются в `output_path`; `--prompt`/`--model-output-format` НЕ существуют; `--command` не использовать (баг #2923, JSON пропадает). Модель — формат `provider/model` (напр. `anthropic/claude-opus-4-8`). Большой промпт (> ~28000 символов) вкладывается через `-f <file>`. Перед прод-запуском желателен smoke с настроенным провайдером: `opencode run --format json --model <p/m> "reply OK"` → поток JSON-событий в stdout (учесть баг #29997: ранние версии не эмитят user-message — для 1.16.x проверить эмпирически).
3. **Имя файла CI-workflow.** В репо CI назван `hephaestus-loop-ci.yml` по спеке §7, но фактическое имя/наличие файла не подтверждено. Если workflow отсутствует — создать; если назван иначе — переиспользовать существующий.
