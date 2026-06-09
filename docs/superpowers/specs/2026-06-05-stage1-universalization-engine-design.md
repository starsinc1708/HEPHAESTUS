---
title: "Этап 1 — Универсализация + кроссплатформенный движок (фундамент): Design Spec"
status: design
date: 2026-06-05
audience: tool author (user) + implementing engineer
language: prose=ru, identifiers/paths/commands=en
depends_on: [2026-06-05-universal-tool-overview-design.md]
covers_vision: [1, 2, "3-partial", "foundation for 4-9"]
---

# Этап 1 — Универсализация + кроссплатформенный движок (фундамент)

> Этот документ — детальная спека первого из трёх этапов. Якорные контракты (доменные типы `Workspace`/`RepoProfile`/`Task`, интерфейсы движка `ProcessManager`/`AgentRunner`/`VerifyRunner`/`GitService`, API-конвенции, memory-раскладка, инварианты §10) определены в umbrella-спеке `docs/superpowers/specs/2026-06-05-universal-tool-overview-design.md` и здесь не переопределяются, а реализуются и уточняются. Любое расхождение разрешается в пользу umbrella.

---

## 1. Goal

Превратить движок из bash/tmux-центричного HEPHAESTUS-loop над одним хардкод-репозиторием в кроссплатформенный нативный Python: ввести понятие `Workspace` (онбординг локального репо Profiler-агентом в `.hephaestus/memory/*.md` + `RepoProfile`), заменить tmux/`pgrep`/`pkill` на `ProcessManager`, `verify.sh` на `VerifyRunner`, де-HEPHAESTUS-ифицировать `config.py`, портировать FSM/driver/scan на чистый Python без bash-скриптов, мигрировать существующий `state/` в Workspace-структуру и вывести legacy `dashboard/` из эксплуатации. Этот этап закладывает фундамент под скан/декомпозицию (Этап 2) и воронку/merge (Этап 3), покрывая пункты видения 1, 2 и частично 3.

---

## 2. Confirmed decisions (релевантные этому этапу)

| ID | Решение в контексте Этапа 1 |
|----|------------------------------|
| D1 | Кроссплатформенный нативный движок. Ввести **синхронный PID-based** `ProcessManager` (`backend/app/core/process.py`) как замену tmux/`pgrep`/`pkill`. `loop` (`python -m app.orchestrator.main --workspace <id>`), `scan`, `profiler` — отдельные супервизируемые долгоживущие дочерние процессы, запускаемые через `subprocess.Popen`; `status()`/`stop()`/`cancel()` синхронны (R1). Никакого bash. |
| D2 | Агенты через CLI `opencode`. Выбор модели = `AgentRef{provider, model, agent}` из `RepoProfile.agents`. `AgentRunner` (`backend/app/services/opencode_runner.py`) обёртывает `opencode run`; поток `output.primary.jsonl`/`output.fallback.jsonl` сохраняется. |
| D4 | Verify-команды определяет Profiler при онбординге в `<repo>/.hephaestus/memory/verify.md`. `VerifyRunner` (`backend/app/core/verify.py`) читает их; `verify_source=manual` берёт `RepoProfile.verify_commands_override`. |
| D6 | Память — md под git внутри целевого репо: `<repo>/.hephaestus/memory/*.md`. Profiler создаёт `MEMORY.md`, `architecture.md`, `verify.md`, `conventions.md`, `tech-debt.md` при онбординге. |
| D7 | HEPHAESTUS остаётся брендом и неймспейсом `HEPHAESTUS_*`. Убирается HEPHAESTUS-как-цель: хардкод `REPO=/home/starsinc/hephaestus-repo`, pnpm-привязка, security-домен по умолчанию, vendor-дефолты агентов (`sisyphus`/`atlas`/`oracle`). Legacy `dashboard/` выводится из эксплуатации. |
| D8 | Эволюционно, in-place: расширяем `fsm.py`, `driver.py`, `scan.py`, `git.py`, `config.py`, `state.py`; переиспользуем существующие api-роутеры и frontend. |
| D9 | Понятие `Workspace`: реестр воркспейсов, активный воркспейс. Все глобали (`config.REPO`/`BASE_BRANCH`/`REMOTE`/`BRANCH_PREFIX`) становятся производными от активного `Workspace`. |

Воронка валидации (D10), merge-UI (D11), reorder/DAG (D5), нативный map-reduce scan и scan/task-writers памяти — в Этапах 2/3 (см. §10). Этап 1 предоставляет под них точки расширения и контракты.

---

## 3. Затрагиваемые и новые файлы

### 3.1 Новые файлы (backend)

| Путь | Назначение |
|---|---|
| `backend/app/core/process.py` | `ProcessManager`, `ProcessHandle`, `ProcState` (D1). Кроссплатформенный пуск/стоп/статус/отмена именованных сессий. |
| `backend/app/core/verify.py` | `VerifyRunner`, `VerifyResult` (D4). Читает verify-команды из памяти/override, исполняет кроссплатформенно. |
| `backend/app/services/opencode_runner.py` | `AgentRunner`, `AgentResult` (D2). Обёртка `opencode run` с выбором provider/model/agent. |
| `backend/app/services/project_memory.py` | `ProjectMemory` — чтение/запись `<repo>/.hephaestus/memory/*.md` с frontmatter; в Этапе 1 — Profiler-bootstrap + `read_verify_commands`. |
| `backend/app/services/profiler.py` | `Profiler` — онбординг-агент: детект стека (через `DocReader`), запуск Profiler-промпта через `AgentRunner`, запись памяти. |
| `backend/app/models/workspace.py` | `RepoProfile`, `AgentsConfig`, `AgentRef`, `ReviewConfig`, `VerifySource` (умбрелла §4.1, реализация здесь). |
| `backend/app/core/workspaces.py` | `WorkspaceRegistry` + singleton `registry` + модульная `active_workspace()` (R4, umbrella §10.1) — CRUD реестра, активный воркспейс, разрешение путей. |
| `backend/app/core/migrate.py` | `migrate_legacy_state()` — одноразовая идемпотентная миграция `state/` в `workspaces/<id>/state/` (умбрелла §9). |
| `backend/app/api/v1/workspaces.py` | Роутер: list/create(onboard)/get/update/activate воркспейсов. |
| `backend/app/services/hephaestus_home.py` | `hephaestus_home()` — путь реестра (`~/.hephaestus` или `HEPHAESTUS_HOME`); единая точка для путей вне репозитория. |
| `prompts/profiler.md` | Промпт Profiler-агента (структура вывода — §4.6). |

### 3.2 Новые файлы (frontend)

| Путь | Назначение |
|---|---|
| `frontend/src/stores/workspace.ts` | `useWorkspaceStore` — список воркспейсов, активный, онбординг, обновление профиля. |
| `frontend/src/views/OnboardView.vue` | Wizard: ввод пути к репо, онбординг, прогресс Profiler, редирект на board. |
| `frontend/src/components/WorkspaceSwitcher.vue` | Переключатель активного воркспейса в `AppShell`. |
| `frontend/src/views/SettingsView.vue` | Настройки воркспейса (R3): provider/model/agent для primary+fallback (+ toggle use_models) и размеры/модели пулов validators/arbiters/final, strictness, ревью-пороги, verify-override. Шлёт через `WorkspaceUpdateRequest.agents`. |

### 3.3 Модифицируемые файлы (backend)

| Путь | Существующие символы и изменение |
|---|---|
| `backend/app/config.py` | Убрать хардкод `REPO=/home/starsinc/hephaestus-repo` (стр. 22) в пользу разрешения из активного `Workspace`; убрать vendor-дефолты `_config_effective` (стр. 116-126: `sisyphus`/`atlas`/`oracle`) в нейтральные; `TIER_PRESETS`, `ALLOWED_CONFIG_KEYS`, `filter_env_bits`, `_validate_config_int`, `_config_preset` сохраняются; добавить `HEPHAESTUS_AGENT_*`/`HEPHAESTUS_VERIFY_COMMANDS` в whitelist. |
| `backend/app/core/driver.py` | Полностью переписать `_tmux_has`/`_loop_status`/`_start_loop`/`_stop_loop_soft`/`_kill_loop_hard` поверх **синхронного** `ProcessManager` (вызовы `pm.start`/`pm.status`/`pm.stop`/`pm.cancel` напрямую, **без** `asyncio.run(pm.*)`, R1). loop запускается как отдельный процесс `python -m app.orchestrator.main --workspace <id>`. Удалить `tmux`/`pgrep`/`pkill`/bash-prefix. |
| `backend/app/core/scan.py` | `_scan_start`/`_scan_running` — заменить tmux на синхронный `pm.start(name="scan", ...)` / `pm.status("scan")` (**без** `asyncio.run`, R1); в Этапе 1 запуск ставится на native-Python orchestrator-стаб (полный map-reduce — Этап 2). Сохранить `_scan_list`/`_scan_status`/`_scan_results`/`_scan_import` (ws-scoped пути). |
| `backend/app/orchestrator/fsm.py` | Извлечь фазу PROMPT_BUILD в метод `_build_prompt(item) -> str` (R14, используется Этапом 3 в петле ревизий); `_run_opencode(self, item, prompt)` (R15: `ws` через `self._ws`, без третьего аргумента) делегирует `AgentRunner.run_with_fallback`; убрать хардкод `sisyphus`/`atlas` и suffix-эвристику (стр. 248,280); `_verify` использует `VerifyRunner` (убрать `bash verify.sh`, стр. 328-360); `_preflight`/`_commit`/`_cleanup`/`_get_repo` читают `self._ws: RepoProfile`. `_tier_review` остаётся no-op (Этап 3). |
| `backend/app/core/git.py` | Обернуть функции в `GitService(ws)`; убрать модульные `from app.config import BASE_BRANCH, BRANCH_PREFIX, REMOTE, REPO`; `BRANCH_ACTIONS` остаётся для legacy-роутера. Merge-методы — заглушки, тело в Этапе 3. |
| `backend/app/core/state.py` | `STATE_DIR` становится ws-scoped (через `WorkspaceRegistry`); `_StateLock` — кроссплатформенный лок (msvcrt/fcntl) либо thread-only (умбрелла §9); сигнатуры `_read_state`/`_write_state`/`_atomic_write` неизменны. |
| `backend/app/core/iters.py` | `_loop_status()` (стр. 423,429) — убрать `_tmux_has("hephaestus-loop")`, читать синхронно `pm.status("loop").state == ProcState.RUNNING` (**без** `asyncio.run`, R1). |
| `backend/app/services/doc_reader.py` | `DocReader.__init__` уже принимает `repo_path` — использовать ws-scoped аргумент при вызовах; обратносовместимый дефолт оставить. |
| `backend/app/main.py` | Startup-check (стр. 90): убрать `tmux`, оставить `git`/`opencode`. Shutdown (стр. 104-108): убрать `pkill -f opencode/verify.sh` в пользу `ProcessManager.cancel_all()`. Зарегистрировать `workspaces_router`. Вызвать `migrate_legacy_state()` в `lifespan` startup. |
| `backend/app/api/v1/loop.py` | `driver_start`/`driver_stop`/`driver_kill` — добавить разрешение активного воркспейса; форма ответа неизменна. |
| `backend/app/models/requests.py` | `DriverStartRequest` сохраняется; добавить `OnboardRequest`, `WorkspaceUpdateRequest`. |
| `backend/app/orchestrator/main.py` | `main()` парсит `--workspace <id>` (loop) / `--profile <id>` (profiler) и разрешает `Workspace` через `registry.get(id)`/`active_workspace()`; держит собственный единый asyncio event loop (R1); signal-handling уже Windows-safe (`contextlib.suppress(NotImplementedError)`). |

### 3.4 Модифицируемые файлы (frontend)

| Путь | Изменение |
|---|---|
| `frontend/src/types/api.ts` | `LoopStatus` (стр. 82-86): `tmux: boolean` в `process: ProcessManagerStatus`; временно дублировать `tmux = state==='running'`. Добавить типы `Workspace`, `RepoProfile`, `AgentRef`, `ProcessManagerStatus`. `EffectiveConfig` (стр. 202-215) дополнить `HEPHAESTUS_AGENT_*`/`HEPHAESTUS_VERIFY_COMMANDS`. |
| `frontend/src/stores/loop.ts` | `status` дефолт `{ tmux:false, ... }` в `{ process: { state:'idle', pid:null, children:[] } }` (R9: `pid`, не `driverPid`); `pollLoop` читает `state.loopStatus.process.pid` напрямую, без скрытого нормализатора. |
| `frontend/src/router.ts` | Добавить роуты `/onboard` (OnboardView) и `/settings` (SettingsView). |
| `frontend/src/components/AppShell.vue` | Вставить `WorkspaceSwitcher`; `loopRunning` = `loopStore.status.process.state === 'running'`. |
| `frontend/src/components/TaskCard.vue` | Стр. 66: убрать хардкод дефолта `'sisyphus'` для `agent_override` в `ws.agents.primary.agent ?? primary.model`. |
| `frontend/src/views/ConfigView.vue` | Перенаправить vendor-специфичные поля в `SettingsView`; `PRESETS`/`EDITABLE_KEYS` остаются. |

### 3.5 Удаляемые файлы (D1, D7)

`driver.sh`, `start-loop.sh`, `verify.sh`, `tier-review.sh`, `repo-scan.sh`, `prompt-build.sh`, `lib/common.sh`, `config.env` (как central source), `dashboard/` (legacy http.server + `server.py` + `index.html`). Удаление — последним коммитом этапа, после того как замены проходят тесты (см. §9, §10 Rollback).

---

## 4. Ключевые контракты

### 4.1 ProcessManager — backend/app/core/process.py (D1, R1)

Супервизит **только верхнеуровневые долгоживущие ДОЧЕРНИЕ процессы по PID, синхронно и кроссплатформенно** (R1). Логические сессии: `loop` (оркестратор как отдельный процесс `python -m app.orchestrator.main --workspace <id>`), `scan` (нативный map-reduce, отдельный процесс — детализация в Этапе 2), `profiler` (онбординг). Один экземпляр-синглтон на backend-процесс; сериализация через `threading.Lock` (**НЕ** `asyncio.Lock`). `pm` — обычный **sync-объект**: он НЕ хранит `asyncio.subprocess.Process`, а хранит `subprocess.Popen` + PID-дерево, которое персистится в `<state>/process.json`. Запуск — через `subprocess.Popen` (НЕ `asyncio.create_subprocess_*`), с `start_new_session=True` (POSIX) / `creationflags=CREATE_NEW_PROCESS_GROUP` (Windows), чтобы убивать всё дерево. `status()`/`stop()`/`cancel()` **синхронны** и вызываются из sync FastAPI-роутов напрямую — **ЗАПРЕЩЕНО** `asyncio.run(pm.*)`.

```python
# backend/app/core/process.py
from __future__ import annotations
import os, signal, subprocess, sys, threading, time, pathlib
from enum import StrEnum
from pydantic import BaseModel

class ProcState(StrEnum):
    IDLE = "idle"; RUNNING = "running"; STOPPING = "stopping"; EXITED = "exited"

class ProcessHandle(BaseModel):
    name: str
    pid: int | None = None           # PID супервизируемого дочернего процесса (R9: единое имя 'pid')
    state: ProcState = ProcState.IDLE
    started_at_ms: int | None = None
    exit_code: int | None = None
    children: list[int] = []         # PID-дерево (best-effort), персистится в state/process.json

_IS_WIN = sys.platform.startswith("win")

class ProcessManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()                 # НЕ asyncio.Lock
        self._procs: dict[str, subprocess.Popen] = {}  # Popen, НЕ asyncio.subprocess.Process
        self._handles: dict[str, ProcessHandle] = {}

    def start(self, name: str, cmd: list[str], *, cwd: str,
              env: dict[str, str], output_path: pathlib.Path | None = None,
              timeout_sec: int | None = None) -> ProcessHandle:
        """SYNC. subprocess.Popen. Если name уже RUNNING (os.kill(pid,0)) — ValueError.
        stdout/stderr пишутся в output_path (append-binary). POSIX: start_new_session=True.
        Windows: creationflags=CREATE_NEW_PROCESS_GROUP. Сохраняет pid + PID-дерево
        в state/process.json и возвращает ProcessHandle (.pid)."""

    def stop(self, name: str, *, grace_sec: float = 10.0) -> ProcessHandle:
        """SYNC graceful: POSIX killpg(SIGTERM); Windows CTRL_BREAK_EVENT/terminate().
        Ждёт grace_sec, затем cancel()."""

    def cancel(self, name: str) -> ProcessHandle:
        """SYNC hard kill дерева: POSIX killpg(SIGKILL); Windows taskkill /F /T /PID.
        Заменяет _kill_loop_hard."""

    def status(self, name: str) -> ProcessHandle:
        """SYNC. Liveness через os.kill(pid, 0); восстановление из state/process.json."""
    def list(self) -> list[ProcessHandle]: ...
    def cancel_all(self) -> None:
        """SYNC shutdown-hook (заменяет pkill в main.lifespan)."""

# Module singleton:
pm = ProcessManager()
```

Псевдокод `cancel` (кроссплатформенное убийство дерева, синхронно):

```
proc = self._procs.get(name)
if proc is None or proc.poll() is not None: return EXITED-handle
if _IS_WIN:
    subprocess.run(["taskkill","/F","/T","/PID",str(proc.pid)], timeout=15)
else:
    try: os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except ProcessLookupError: pass
proc.wait()
handle.state = EXITED; handle.exit_code = proc.returncode
```

**Граница ответственности (R1, R2).** `AgentRunner` НЕ обращается к приватным полям `ProcessManager` (`_procs`/`_finalize`). Внутри дочернего процесса (оркестратор/скан) живёт собственный единый asyncio event loop; там `AgentRunner` запускает `opencode` через `asyncio.subprocess` НА ТЕКУЩЕМ loop, управляет СВОИМ subprocess-хэндлом и `await`'ит именно его. Конкурентные агенты воронки (Этап 3) не делят общий `session_name`; у каждого уникальный артефакт-путь (R2).

### 4.2 AgentRunner — backend/app/services/opencode_runner.py (D2)

```python
class AgentResult(BaseModel):
    exit_code: int           # 0 ok; -1 timeout/launch-error
    refused: bool            # 'REFUSED' в первых 1000 байт output
    output_path: pathlib.Path
    agent_label: str         # 'anthropic/claude-opus-4-8' | 'sisyphus' для логов/UI

class AgentRunner:
    def __init__(self, pm: ProcessManager) -> None: ...

    # opencode 1.16.0: message ПОЗИЦИОННЫЙ (нет --prompt/--output); вывод --format json в stdout.
    _MAX_INLINE_PROMPT = 28000

    def _build_cmd(self, ref: AgentRef, prompt_text: str, *,
                   use_models: bool, attach_file: pathlib.Path | None = None) -> list[str]:
        cmd = ["opencode", "run", "--format", "json"]
        if ref.agent and not use_models:
            cmd += ["--agent", ref.agent]
        else:
            cmd += ["--model", f"{ref.provider}/{ref.model}"]
        if attach_file is not None:
            cmd += ["-f", str(attach_file), "Follow the instructions in the attached file exactly."]
        else:
            cmd.append(prompt_text)
        return cmd

    async def run(self, ref: AgentRef, *, prompt_file: pathlib.Path, cwd: str,
                  output_path: pathlib.Path, timeout_sec: int,
                  use_models: bool = False) -> AgentResult:
        """Запускает СВОЙ asyncio.subprocess на ТЕКУЩЕМ event loop (внутри дочернего
        процесса). opencode `--format json` пишет JSON-события в STDOUT → захватываем в
        output_path (НЕ через флаг --output, его нет). НЕ обращается к приватным полям pm,
        НЕ использует общий session_name (R1/R2). Промпт читается из prompt_file и
        передаётся позиционным message (при размере > _MAX_INLINE_PROMPT — вложением -f).
        После выхода читает stdout[:1000] на 'REFUSED'."""

    async def run_with_fallback(self, agents: AgentsConfig, *, prompt_file: pathlib.Path,
                                cwd: str, iter_dir: pathlib.Path,
                                timeout_sec: int) -> AgentResult:
        """primary в output.primary.jsonl; при rc!=0 и не refused —
        fallback в output.fallback.jsonl. Заменяет fsm._run_opencode +
        _run_opencode_subprocess; имена потоков детерминированы (primary/fallback),
        НЕ по suffix-эвристике агента."""
```

Контракт CLI (opencode 1.16.0, подтверждён `opencode run --help`): `opencode run --format json [--agent <a> | --model <provider/model>] <message>`. Промпт — ПОЗИЦИОННЫЙ message (нет `--prompt`); вывод JSON-событий в stdout (нет `--output`) → захватываем в `output_path`; не использовать `--command` (баг #2923). Источник имени агента/модели — `AgentRef` из `RepoProfile.agents` (а не env-дефолт `sisyphus`). **Граница (R1):** `AgentRunner` запускается ВНУТРИ дочернего процесса (оркестратор/профайлер), на его собственном asyncio loop, и владеет своим subprocess-хэндлом; он НЕ супервизируется backend-`ProcessManager` и не делит с ним `session_name`.

### 4.3 VerifyRunner — backend/app/core/verify.py (D4)

```python
class VerifyResult(BaseModel):
    ok: bool
    ran: list[str]
    failed_command: str | None = None
    log_path: pathlib.Path

class VerifyRunner:
    def __init__(self, ws: RepoProfile) -> None: ...

    def resolve_commands(self) -> list[str]:
        """verify_source==MANUAL берёт ws.verify_commands_override.
        verify_source==AGENT берёт ProjectMemory(ws).read_verify_commands().
        Пустой список — run() вернёт ok=True (no-op verify)."""

    async def run(self, *, cwd: str, log_path: pathlib.Path,
                  timeout_sec: int) -> VerifyResult:
        """Исполняет команды по порядку через asyncio.create_subprocess_exec.
        Парсинг команды: shlex.split(cmd, posix=True) (НЕ posix=False); первый токен
        резолвится через shutil.which перед exec (Windows подхватывает .cmd/.bat/.exe-шимы
        вроде npm.cmd/pnpm.cmd) (R5). Первая команда с rc!=0 — ok=False,
        failed_command=cmd, остановка. Конвенция: rc==0=green."""
```

**Контракт verify-команд (R5).** Каждая команда — **одна программа + аргументы на строку, без shell-операторов** (`&&`, `|`, `>`, `$VAR`) — этот контракт зафиксирован также в `prompts/profiler.md` и формате `.hephaestus/memory/verify.md`. По умолчанию `shell: false`. Опциональный manual-override может пометить команду `shell: true` → тогда запуск через `['cmd', '/c', cmd]` (Windows) / `['sh', '-c', cmd]` (POSIX). На Windows НЕ использовать `shlex.split(..., posix=False)` для путей — разбор всегда `posix=True` (он корректно снимает кавычки, а argv передаётся в `create_subprocess_exec`, никогда не в shell); первый токен резолвится `shutil.which`.

Псевдокод `run`:

```
cmds = self.resolve_commands()
ran = []
with log_path.open("ab") as logf:
    for cmd in cmds:
        argv = shlex.split(cmd, posix=True)
        if not argv: continue
        exe = shutil.which(argv[0]) or argv[0]   # подхватывает npm.cmd/pnpm.cmd на Windows
        proc = await create_subprocess_exec(exe, *argv[1:], cwd=cwd,
                   stdout=logf, stderr=STDOUT, env=os.environ)
        try: rc = await wait_for(proc.wait(), timeout=timeout_sec)
        except TimeoutError: kill-tree; return VerifyResult(ok=False, ran, failed_command=cmd)
        ran.append(cmd)
        if rc != 0: return VerifyResult(ok=False, ran, failed_command=cmd)
return VerifyResult(ok=True, ran, failed_command=None)
```

### 4.4 WorkspaceRegistry — backend/app/core/workspaces.py (D9)

Реестр под `hephaestus_home()/workspaces/`. `id = sha256(os.path.realpath(repo_path).casefold().encode())[:16]` (умбрелла §4.1; casefold для Windows-нечувствительности к регистру).

```python
class WorkspaceRegistry:
    def __init__(self, home: pathlib.Path | None = None) -> None: ...
    def list(self) -> list[RepoProfile]: ...
    def get(self, ws_id: str) -> RepoProfile | None: ...
    def create(self, repo_path: str, *, name: str | None = None) -> RepoProfile:
        """Валидирует git-репо (.git); id из realpath. Если уже есть —
        возвращает существующий (идемпотентно). Пишет profile.json, onboarded=False.
        Заполняет дефолтные пулы agents (R3): primary, fallback, validators (>=5 AgentRef,
        по одной на линзу correctness/tests/security/conventions/scope), arbiters (>=2),
        final (1) — производными от выбранного провайдера/модели (env HEPHAESTUS_AGENT_PROVIDER /
        HEPHAESTUS_AGENT_MODEL, иначе нейтральный плейсхолдер)."""
    def update(self, ws_id: str, patch: dict) -> RepoProfile: ...
    def activate(self, ws_id: str) -> None:
        """Пишет active.json = {workspaceId: ws_id}."""
    def active(self) -> RepoProfile | None: ...
    def state_dir(self, ws: RepoProfile) -> pathlib.Path:
        """hephaestus_home()/workspaces/<id>/state — заменяет глобальный STATE_DIR."""
    def memory_dir(self, ws: RepoProfile) -> pathlib.Path:
        """<repo_path>/<ws.memory_dir> — под git (D6)."""
    @staticmethod
    def ws_id_for(repo_path: str) -> str: ...   # общий с migrate.py

registry = WorkspaceRegistry()  # module singleton


def active_workspace() -> RepoProfile | None:   # umbrella §10.1, R4
    return registry.active()
```

**Контракт `active_workspace()` (R4, umbrella §10.1).** Единый источник активного воркспейса — `backend/app/core/workspaces.py`: класс `WorkspaceRegistry`, singleton `registry`, метод `registry.active()` И модульная функция-обёртка `active_workspace()`. Этапы 2/3 импортируют `from app.core.workspaces import active_workspace, registry`. **Запрещён** несуществующий модуль `app.core.workspace_registry`.

### 4.5 ProjectMemory — backend/app/services/project_memory.py (D6)

```python
_DOC_TYPES = ("index", "architecture", "verify", "conventions", "tech-debt")
_FILE_FOR = {"index": "MEMORY.md", "architecture": "architecture.md",
             "verify": "verify.md", "conventions": "conventions.md",
             "tech-debt": "tech-debt.md"}

class ProjectMemory:
    def __init__(self, ws: RepoProfile) -> None: ...
    def ensure_dir(self) -> pathlib.Path: ...  # mkdir <repo>/.hephaestus/memory
    def write_doc(self, doc: str, body: str, *, source: str) -> pathlib.Path:
        """Пишет файл с YAML-frontmatter (doc, workspace_id, updated_at, source, schema=1)
        плюс body. Atomic write. source in {profiler|scan|task|manual}."""
    def read_doc(self, doc: str) -> tuple[dict, str]:
        """Возвращает (frontmatter_dict, body). Парсинг frontmatter — строгий regex
        по разделителям ---; невалидный — ({}, raw)."""
    def read_verify_commands(self) -> list[str]:
        """Читает verify.md, извлекает строки из первого sh-блока под
        '## commands'; trim, drop пустые/комментарии (#)."""
    def bootstrap_index(self) -> None:
        """Пишет MEMORY.md со ссылками на существующие doc-файлы плюс updated_at."""
```

Псевдокод `read_verify_commands` (детерминированный, без bash):

```
fm, body = self.read_doc("verify")
m = re.search(commands-fence-regex, body, re.S)   # ищет '## commands' + sh-fence
if not m: return []
return [ln.strip() for ln in m.group(1).splitlines()
        if ln.strip() and not ln.strip().startswith("#")]
```

### 4.6 Profiler — backend/app/services/profiler.py (D4 + D6) и prompts/profiler.md

Profiler — онбординг-агент с идентичностью `profiler-<ws.id>` (R2). Шаги: (1) `DocReader(ws.repo_path).detect_tech_stack()` + `get_context_summary()` для детерминированного контекста; (2) рендер `prompts/profiler.md` с этим контекстом; (3) запуск через `AgentRunner.run(ws.agents.primary, ...)` (уникальный `output_path` онбординга, без общего `session_name`); (4) парсинг JSON-вывода агента; (5) запись `.hephaestus/memory/*.md` через `ProjectMemory`; (6) `registry.update(ws.id, {"onboarded": True, ...verify...})`.

```python
class ProfilerOutput(BaseModel):
    tech_stack: list[str]
    verify_commands: list[str]      # в verify.md
    architecture_md: str            # тело architecture.md
    conventions_md: str             # тело conventions.md
    tech_debt_md: str               # тело tech-debt.md
    base_branch: str | None = None  # детект default-ветки

class Profiler:
    def __init__(self, ws: RepoProfile, runner: AgentRunner) -> None: ...
    async def onboard(self) -> ProfilerOutput:
        """Полный пайплайн. Идемпотентен: повторный вызов перезаписывает память
        (source=profiler, schema=1). Не падает при пустом репо — пишет минимальные
        заготовки и verify_commands=[]."""
```

Структура вывода Profiler-агента (контракт `prompts/profiler.md`). Агент обязан вывести единственный JSON-объект (последним текстовым сообщением), который `Profiler.onboard` извлекает по последнему фигурно-скобочному блоку:

```json
{
  "tech_stack": ["python", "fastapi"],
  "verify_commands": ["uv run pytest -q", "uv run ruff check ."],
  "architecture_md": "## Modules ...",
  "conventions_md": "## Style ...",
  "tech_debt_md": "## Known debt ...",
  "base_branch": "main"
}
```

`prompts/profiler.md` (новый) инструктирует агента: проанализировать `{{tech_stack}}`/`{{structure}}`/`{{readme}}`, определить реальные verify-команды проекта (test/lint/typecheck — то, что есть, БЕЗ предположения pnpm), и вернуть строго описанный JSON. Никаких side-effect git-операций в Profiler-прогоне. **Память — короткая** (research): каждый md ≤ ~150 строк, только неочевидные gotchas, без пересказа README — длинные/очевидные context-файлы снижают success rate и растят cost (ETH Zurich по AGENTS.md, 2026; см. `docs/research/2026-06-05-prior-art-and-best-practices.md`).

### 4.7 API-эндпоинты Этапа 1 (форма ответа ok|error как в main.py)

| Метод и путь | Тело / параметры | Возврат |
|---|---|---|
| `GET /api/v1/workspaces` | — | `{ok:true, workspaces:[RepoProfile...], activeId:str|null}` |
| `POST /api/v1/workspaces` | `OnboardRequest{repoPath, name?}` | `{ok:true, workspace:RepoProfile}` (запускает Profiler фоном через pm.start("profiler")) |
| `GET /api/v1/workspaces/{id}` | — | `{ok:true, workspace:RepoProfile, onboarding:ProcessHandle}` |
| `PUT /api/v1/workspaces/{id}` | `WorkspaceUpdateRequest` | `{ok:true, workspace:RepoProfile}` |
| `POST /api/v1/workspaces/{id}/activate` | — | `{ok:true, activeId:id}` |
| `POST /api/driver/start` (legacy путь) | `DriverStartRequest` | `{ok:true, session:"loop", env:{...}}` — теперь через ProcessManager |
| `POST /api/driver/stop` / `kill` | — | `{ok:true, ...}` |
| `GET /api/state` (расширяется) | — | `loopStatus = {process:{state,pid,children}, tmux:<deprecated>}` (R9: единое имя `pid`) |

```python
class OnboardRequest(BaseModel):
    repoPath: str
    name: str | None = None

class WorkspaceUpdateRequest(BaseModel):
    name: str | None = None
    baseBranch: str | None = None
    remote: str | None = None
    branchPrefix: str | None = None
    strictness: str | None = None              # strict|standard|permissive
    agents: dict | None = None                 # AgentsConfig-shape
    review: dict | None = None                 # ReviewConfig-shape
    verifySource: str | None = None            # agent|manual
    verifyCommandsOverride: list[str] | None = None
    verifyTimeoutSec: int | None = None
    autopush: bool | None = None
```

### 4.8 Frontend-контракты

```typescript
// frontend/src/types/api.ts (добавления)
export interface ProcessManagerStatus {
  state: 'idle' | 'running' | 'stopping' | 'exited'
  pid: number | null        // R9: единое имя сквозь стек (ProcessHandle.pid → JSON → TS)
  children: number[]
}
export interface LoopStatus {
  process: ProcessManagerStatus
  tmux?: boolean            // deprecated mirror: state === 'running'
  driver_pid?: number | null  // deprecated; читать process.pid
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

```typescript
// frontend/src/stores/workspace.ts
export const useWorkspaceStore = defineStore('workspace', () => {
  const workspaces = ref<RepoProfile[]>([])
  const activeId = ref<string | null>(null)
  const active = computed(() => workspaces.value.find(w => w.id === activeId.value) ?? null)
  async function fetchWorkspaces(): Promise<void>
  async function onboard(repoPath: string, name?: string): Promise<RepoProfile>
  async function activate(id: string): Promise<void>
  async function updateProfile(id: string, patch: Partial<RepoProfile>): Promise<void>
  return { workspaces, activeId, active, fetchWorkspaces, onboard, activate, updateProfile }
})
```

`OnboardView.vue` — wizard: поле `repoPath`, кнопка Онбордить, поллинг `GET /api/v1/workspaces/{id}` (поле onboarding.state) до `exited`, затем `activate` плюс редирект на `/board`. `SettingsView.vue` (R3, закрывает видение п.2) редактирует `RepoProfile` через `PUT`, отправляя изменения через `WorkspaceUpdateRequest.agents`: модели — AgentRef-блоки `primary` и `fallback` с полями provider/model/agent плюс toggle `use_models`, А ТАКЖЕ размеры и модели пулов `validators`/`arbiters`/`final` воронки; strictness — селектор strict|standard|permissive; review — пороги (`tier1Threshold`/`tier2Threshold`/`maxRevisions`); verify — переключатель agent|manual плюс textarea команд при manual.

---

## 5. Поток данных в этом этапе

Онбординг (видение п.1-3):

```
UI OnboardView  POST /api/v1/workspaces {repoPath}
  WorkspaceRegistry.create() (валидирует .git, id=sha256(realpath), заполняет дефолтные пулы agents R3)
  pm.start("profiler", [python -m app.orchestrator.main --profile <id>])  # отдельный супервизируемый процесс (R1)
  ВНУТРИ процесса profiler — собственный asyncio loop:
    Profiler.onboard(): DocReader.detect_tech_stack  render prompts/profiler.md
      AgentRunner.run(ws.agents.primary)  output.profiler.jsonl  # своя asyncio.subprocess (R1/R2)
      parse ProfilerOutput JSON
      ProjectMemory.write_doc(verify|architecture|conventions|tech-debt) + bootstrap_index()
      registry.update(onboarded=True, verify_source=AGENT)
  UI поллит GET /api/v1/workspaces/{id} до onboarding.state==exited (pm.status("profiler"), sync)
  UI POST /activate  SettingsView (provider/model/agent primary+fallback + пулы validators/arbiters/final R3)
```

Loop (фундамент под п.5-8; исполнение задач детально в Этапах 2/3):

```
UI  POST /api/driver/start  (sync route)
  registry.active() = ws
  pm.start("loop", [python -m app.orchestrator.main --workspace ws.id], env c HEPHAESTUS_WORKSPACE_ID=ws.id)  # sync (R1)
  ВНУТРИ процесса loop — собственный единый asyncio loop:
    OrchestratorFSM().run() (self._ws разрешён из HEPHAESTUS_WORKSPACE_ID): per item
      PREFLIGHT: GitService(ws).create_branch(auto/<id>-<ts>) на ws.repo_path; iter-NNNN (монотонный, R12)
      PROMPT_BUILD: prompt = self._build_prompt(item)  # PromptManager+DocReader+ProjectMemory (R14)
      OPENCODE: self._run_opencode(item, prompt)  -> AgentRunner.run_with_fallback(ws.agents)  output.{primary,fallback}.jsonl (R15)
      VERIFY: VerifyRunner(ws).run() (команды из .hephaestus/memory/verify.md)
      COMMIT: GitService(ws).commit(msg)
      PARSE_RESULT: result.json  selfReportedFailure
      TIER_REVIEW: no-op (Этап 3)
      CLEANUP: autopush опционально; чекпойнт
  state пишется в registry.state_dir(ws)/work-state.json (ws-scoped)
UI GET /api/state  loopStatus.process = pm.status("loop")  # sync, читает pid
```

Миграция (один раз, в lifespan startup):

```
migrate_legacy_state():
  if state/work-state.json exists AND no workspaces/ registry:
    ws = registry.create(config.REPO, name=basename)  # id из realpath(REPO)
    move state/{work-state.json,iter-*,scans/*,decisions.log,*.json}  workspaces/<id>/state/
    for item in work-state: item.setdefault("workspaceId", ws.id)
    registry.update(ws.id, onboarded=False); registry.activate(ws.id)
  idempotent: marker workspaces/.migrated
```

---

## 6. Обработка ошибок и граничные случаи

1. opencode не на PATH. `AgentRunner.run` ловит `FileNotFoundError` при запуске СВОЕЙ `asyncio.create_subprocess_exec` — `AgentResult(exit_code=-1, refused=False)`; FSM — `failed:opencode`; UI получает ошибку в decisions. Startup-check логирует warning, но не падает.
2. Невалидный путь репо при онбординге. `WorkspaceRegistry.create` проверяет `(Path(repo_path)/".git").exists()`; иначе `error_response("not a git repository", 400)`.
3. Повторный онбординг того же репо. `id` детерминирован — `create` возвращает существующий профиль (идемпотентно), Profiler перезаписывает память (source=profiler).
4. Profiler-агент вернул не-JSON / refused. `Profiler.onboard` извлекает последний фигурно-скобочный блок; при неудаче парсинга пишет минимальные заготовки (verify_commands=[], заглушки md), onboarded=True, лог warning. Пользователь правит verify через manual override.
5. Пустой verify.md / verify_commands=[]. `VerifyRunner.run` — `VerifyResult(ok=True, ran=[])` (no-op verify, как текущее поведение отсутствующего verify.sh).
6. Verify-команда тайм-аутит. `VerifyRunner` убивает дерево, ok=False, failed_command=cmd. FSM — `failed:verify`.
7. `ProcessManager.start` на уже RUNNING-сессии. `ValueError("session 'loop' already running")` — `_start_loop` возвращает `{"ok": False, "error": "loop already running"}` (паритет с tmux-поведением).
8. Backend упал во время loop. Дочерние процессы в отдельной process-group переживают backend; при рестарте `migrate_legacy_state` пропускается, `_recover_checkpoint` чистит stale-чекпойнт; `process.json` (опциональный реестр PID) позволяет cancel осиротевших.
9. Windows: нет SIGKILL/os.killpg. `ProcessManager` ветвится по sys.platform: CREATE_NEW_PROCESS_GROUP плюс taskkill /F /T. Signal-handler в orchestrator/main.py уже обёрнут suppress(NotImplementedError).
10. Кроссплатформенный лок (state.py). Поскольку bash-сторона удалена, единственный писатель — backend; `_StateLock` использует fcntl.flock (POSIX) / msvcrt.locking (Windows) для защиты от второго инстанса backend, иначе `_thread_lock` достаточно. На Windows перед `msvcrt.locking` обязателен `self._fd.seek(0)` и блокировка фиксированного байта offset 0 (и `seek(0)` при разблокировке), иначе взаимного исключения нет (R13). На Windows никогда не молчаливый no-op.
11. Нет активного воркспейса. Любой ws-scoped эндпоинт при `registry.active() is None` — `error_response("no active workspace — onboard a repo first", 409)`.
12. Путь с пробелами/юникодом (Windows). Все пути — pathlib.Path; команды — список аргументов (никогда string-shell); output_path открывается в binary. Encoding при чтении JSONL — errors="replace".
13. Файло-конфликт миграции. `migrate_legacy_state` пропускает уже перемещённые файлы (проверка существования), пишет .migrated-маркер; повторный запуск — no-op.

---

## 7. Тестирование

Все тесты — pytest, без bash, должны проходить на Windows и POSIX (CI-matrix). Существующий `backend/tests/{unit,contract}/` расширяется. Bash-зависимый `test_lock_contract.py` (Phase 0, flock-subprocess) переписывается под чистый Python (двойной `_StateLock` внутри процесса).

Unit (backend/tests/unit/):

- `test_process_manager.py` — start/status/stop/cancel/cancel_all на кроссплатформенной команде (`[sys.executable, "-c", "import time; time.sleep(30)"]`). Проверяет: IDLE-RUNNING-EXITED; cancel завершает дерево менее чем за 5s; повторный start RUNNING — ValueError. Без tmux/pgrep.
- `test_verify_runner.py` — resolve_commands для agent/manual; run c `[sys.executable,"-c","sys.exit(0)"]` (green) и sys.exit(1) (fail, failed_command корректен); тайм-аут убивает дерево; пустой список — ok=True. На `windows-latest` (gated на sys.platform) — отдельный тест с `.cmd`-шимом (создать `tool.cmd` в tmp, добавить в PATH) и проверка резолва через `shutil.which` (R5).
- `test_workspace_registry.py` — create идемпотентен (один id на realpath, регистронезависимо); activate/active; state_dir/memory_dir пути; не-git-путь — ошибка.
- `test_project_memory.py` — write_doc пишет валидный frontmatter (schema:1, workspace_id); read_doc round-trip; read_verify_commands извлекает команды из sh-блока, дропает комментарии/пустые; невалидный verify.md — [].
- `test_agent_runner_cmd.py` — _build_cmd: всегда `--format json`; use_models=True даёт `--model provider/model`; agent задан и use_models=False даёт `--agent <a>`; промпт — позиционный message (последний аргумент); oversize-промпт → вложение `-f <file>`; нет `--prompt`/`--output`/`--model-output-format`.
- `test_profiler_parse.py` — извлечение последнего JSON-блока из mock-вывода; устойчивость к не-JSON (заготовки плюс onboarded=True).
- `test_config_dehephaestus.py` — _config_effective() НЕ содержит vendor-дефолтов; config.REPO дефолт не /home/starsinc/hephaestus-repo; TIER_PRESETS/filter_env_bits сохраняют поведение.

Contract (backend/tests/contract/):

- `test_workspace_schema.py` — RepoProfile.model_validate round-trip с camelCase-алиасами; model_dump(by_alias=True) даёт repoPath/baseBranch/verifySource.
- `test_loopstatus_shape.py` — GET /api/state (TestClient) возвращает loopStatus.process.{state,pid,children} (R9) и deprecated tmux-зеркало.
- `test_existing_state.py` (существующий) — каждый item state/work-state.json валидируется как Task (расширенный Item) без исключений; добавленные поля опциональны.
- `test_migrate_idempotent.py` — migrate_legacy_state дважды — второй вызов no-op, .migrated-маркер, workspaceId проставлен.

Integration (backend/tests/integration/, кроссплатформенные):

- `test_onboard_flow.py` — POST /api/v1/workspaces на временном git-репо (git init через subprocess; gated на наличие git); проверяет создание профиля, статус онбординга, активацию. AgentRunner мокается (Profiler-вывод — фикстура JSON), реальный opencode не требуется.
- `test_loop_start_stop.py` — POST /api/driver/start даёт pm.status("loop").state==running, затем /stop даёт idle/exited. Orchestrator-команда заменяется на короткий stub (sys.executable -c), opencode не нужен.
- `test_verify_from_memory.py` — записать .hephaestus/memory/verify.md с sys.executable -c print('ok'), VerifyRunner(ws).run() даёт ok=True, лог содержит вывод.

CI. `.github/workflows/hephaestus-loop-ci.yml` — matrix os: [ubuntu-latest, windows-latest], шаги ruff check, mypy --strict backend/, pytest backend/tests -x. `windows-latest` обязан гонять verify-тест с `.cmd`-шимом (R5). Frontend job: vue-tsc --noEmit плюс vitest run (включая type-проверку Workspace/ProcessManagerStatus).

---

## 8. Зависимости / пины

Новых runtime-зависимостей не добавляется — `ProcessManager` (sync, `subprocess.Popen` + `threading.Lock`) и `VerifyRunner`/`AgentRunner` (asyncio внутри дочернего процесса) используют только stdlib (asyncio, subprocess, signal, os, shlex, shutil, threading, pathlib, msvcrt/fcntl). YAML-frontmatter парсится вручную (regex), без pyyaml. Существующие пины backend/pyproject.toml сохраняются (fastapi ^0.115, pydantic ^2.11, pydantic-settings ^2.9, pytest ^8.3, pytest-asyncio ^0.25). CI добавляет windows-latest в matrix. Внешние требования (не пины Python): установленный opencode CLI плюс ключи провайдеров, git на PATH (D2).

---

## 9. Exit criteria (проверяемые)

1. pytest backend/tests -x зелёный на обоих ubuntu-latest и windows-latest (CI matrix).
2. ruff check backend/ и mypy --strict backend/ без ошибок.
3. Поиск tmux|pgrep|pkill по backend/app пуст (кроме комментариев истории). driver.sh, start-loop.sh, verify.sh, tier-review.sh, repo-scan.sh, prompt-build.sh, lib/common.sh, dashboard/ удалены из репозитория.
4. _config_effective() не содержит vendor-дефолтов (sisyphus/atlas/oracle/librarian/prometheus/metis/momus/multimodal-looker/sisyphus-junior); config.REPO дефолт не /home/starsinc/hephaestus-repo.
5. На чистой Windows-машине (без WSL, без tmux): POST /api/v1/workspaces {repoPath} онбордит репо, создаёт <repo>/.hephaestus/memory/{MEMORY,architecture,verify,conventions,tech-debt}.md с валидным frontmatter; POST /api/driver/start поднимает loop-сессию (process.state==running), /stop гасит её.
6. VerifyRunner исполняет команды из verify.md (не pnpm-хардкод); manual override работает.
7. pnpm build во frontend/ успешен; vue-tsc --noEmit чистый; OnboardView/SettingsView/WorkspaceSwitcher рендерятся, LoopStatus.process читается без tmux.
8. migrate_legacy_state() мигрирует существующий state/ в workspaces/<id>/state/ идемпотентно; старая доска видна на board активного воркспейса.

---

## 10. Out of scope + Rollback

Out of scope (другие этапы):

- Этап 2: нативный map-reduce scan (полная реализация scan.py orchestration), декомпозиция находок в Task с depends_on/order_index/conflict_group, backend/app/core/task_graph.py (DAG плюс can_reorder), PATCH /api/v1/tasks/{id}/reorder с DAG-проверкой (D5), scan/task-writers памяти (source: scan|task), memory-эндпоинты GET/PUT /api/v1/workspaces/{id}/memory/{doc}.
- Этап 3: воронка валидации (D10) — validators/arbiters/final слои, ValidationResult, статусы in_review/needs_revision-петля, замена no-op _tier_review; merge-preflight плюс merge_to_base тело (D11), GET/POST /api/v1/branches/{name}/merge[-preflight], frontend merge-UI и визуализация валидации.

Этап 1 только готовит под них: поля RepoProfile.review/strictness/agents.validators существуют; GitService.merge_preflight/merge_to_base объявлены как заглушки; scan.py запускается через ProcessManager, но полный map-reduce — Этап 2.

Rollback. Этап разбит на коммиты: (a) ввод Workspace/registry/migrate (аддитивно, старые пути живы); (b) ProcessManager плюс AgentRunner плюс VerifyRunner (driver/scan/fsm переключаются, bash-замены ещё на диске); (c) frontend онбординг/настройки; (d) удаление bash/tmux/dashboard. Откат до коммита (d) восстанавливает bash-скрипты из git-истории; откат до (a) полностью возвращает tmux-движок. Память .hephaestus/memory/ живёт под git целевого репо — откат инструмента её не трогает. migrate_legacy_state копирует (не уничтожает) исходные пути до подтверждения; .migrated-маркер можно удалить для повторного прогона. Контракт Item/StateSnapshot остаётся обратносовместимым (умбрелла §10.4), поэтому старый frontend и legacy /api/...-роутеры работают на каждом промежуточном коммите.
