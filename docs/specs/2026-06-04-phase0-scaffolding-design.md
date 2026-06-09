# Phase 0 — Freeze + Scaffolding: Design Spec

**Date:** 2026-06-04
**Status:** Approved
**Parent plan:** `docs/2026-06-04-vue-fastapi-kanban-rewrite.md`
**Repo:** `https://github.com/starsinc1708/HEPHAESTUS.git`
**Branch:** `feature/vue-fastapi-rewrite-phase-0`

---

## 1. Goal

Prepare `backend/` and `frontend/` skeletons adjacent to `dashboard/` without disrupting the running loop. The loop continues shipping items overnight. No production files are modified.

## 2. Confirmed decisions

| Decision | Choice |
|---|---|
| Vue dev-server | Prebuilt `dist/` only — scp to host, no HMR on host |
| FastAPI port (Phase 1) | Adjacent-port A/B: 8765 legacy, 8766 new |
| Auth (Phase 1) | None (same as now, HOST=127.0.0.1 default) |
| Loop status | Running — do NOT touch tmux sessions, state/, start-dashboard.sh |
| Workstation | Windows, Python 3.12 + Node 22 + pnpm ready |

## 3. File structure (all new files)

```
backend/
├── pyproject.toml
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI() + GET /healthz + lifespan
│   ├── config.py                # pydantic-settings + ALLOWED_CONFIG_KEYS allowlist
│   ├── core/
│   │   ├── __init__.py
│   │   ├── state.py             # _StateLock, _atomic_write, _read_state, _write_state, _LKG_STATE
│   │   └── events.py            # _summarize_event, _parse_events, _sum_usage, _iter_cost
│   └── models/
│       ├── __init__.py
│       └── domain.py            # Pydantic Item model with extra='allow'
├── tests/
│   ├── contract/
│   │   ├── __init__.py
│   │   ├── test_existing_state.py
│   │   └── test_lock_contract.py
│   └── unit/
│       ├── __init__.py
│       └── test_state.py
└── .env.example

frontend/
├── package.json
├── vite.config.ts
├── tailwind.config.ts
├── tsconfig.json
└── src/
    ├── main.ts
    ├── App.vue
    ├── styles/
    │   └── tokens.css
    └── types/
        └── api.ts

.github/
└── workflows/
    └── hephaestus-loop-ci.yml

state/
└── runtime-versions.json
```

## 4. Key contracts

### 4.1 `backend/app/core/state.py`

Port of `server.py:101-183`. Verbatim except:
- `STATE_DIR` configurable via `LOOP_HOME` env var (default: parent of `backend/`)
- Module-level `STATE_DIR`, `LOCK_PATH`, `LOOP_HOME` computed once at import

Functions:
- `_StateLock` — context manager, `fcntl.flock(LOCK_EX)` on `.work-state.lock` + threading.Lock for in-process serialization
- `_atomic_write(path, data_str)` — tmp + fsync + os.replace
- `_read_state()` — reads `work-state.json`, falls back to `_LKG_STATE` on parse error
- `_write_state(state)` — adds `updatedAt`, validates JSON, atomic write, updates `_LKG_STATE`
- `_LKG_STATE` — dict `{"value": None}` cache

### 4.2 `backend/app/core/events.py`

Port of `server.py:235-301` (`_sum_usage`, `_iter_cost`) and `server.py:405-584` (`_summarize_event`, `_parse_events`). Verbatim. Defensive JSONL parsing preserved byte-for-byte.

### 4.3 `backend/app/models/domain.py`

```python
class Item(BaseModel):
    model_config = ConfigDict(extra='allow', populate_by_name=True)
    id: str
    title: str
    status: str                          # NOT Literal — failed:X variants
    attempts: int = 0
    proposal: str = ""
    why: str = ""
    acceptance: str = ""
    touches: list[str] = []
    branch: str | None = None
    last_iter: str | None = Field(None, alias="lastIter")
    previous_branches: list[str] = Field(default_factory=list, alias="previousBranches")
    commit: str | None = None
    plan_file: str = ""
    plan_section: str = ""
    wave: str = ""
    severity: str | None = None
    category: str | None = None
    source_scan: str | None = None
    self_reported_failure: bool = Field(False, alias="selfReportedFailure")
    requeued_at: datetime | None = None
    review: str | dict | None = None
    merge_commit: str | None = Field(None, alias="mergeCommit")
    merged_at: datetime | None = Field(None, alias="mergedAt")
```

Serialization: `model_dump(by_alias=True)` — camelCase output matching bash contract.

### 4.4 Contract tests

**`test_existing_state.py`:** Load `state/work-state.json` (or fixture). For each item: `Item.model_validate(it)` must not raise. CI gate.

**`test_lock_contract.py`:** On Linux only (skip on Windows):
1. Bash subprocess: `(flock -x 9; sleep 5) 9>state/.work-state.lock` in background
2. Python: `start = time.monotonic(); _StateLock().__enter__(); elapsed = time.monotonic() - start`
3. Assert `elapsed >= 4.0` (allow 1s tolerance)
4. Assert `_write_state` inside lock produces valid JSON

**`test_state.py`:** Unit tests for `_atomic_write`, `_read_state`, `_write_state`, `_LKG_STATE` fallback.

### 4.5 `backend/app/config.py`

Pydantic-settings class with `LOOP_HOME`, `STATE_DIR`, `REPO`, `PORT`, `HOST`, `BRANCH_PREFIX`, `BASE_BRANCH`, `REMOTE`. `ALLOWED_CONFIG_KEYS` frozenset byte-for-byte from `server.py:57-68`.

### 4.6 `backend/app/main.py`

```python
app = FastAPI(title="HEPHAESTUS Loop API", version="0.1.0")

@app.get("/healthz")
async def healthz():
    return {"status": "ok", "version": "0.1.0"}
```

No routers, no WebSocket, no static files yet.

## 5. Pinned dependencies

### `backend/pyproject.toml`

```
python = ">=3.12,<3.13"
fastapi = "^0.115.0"
uvicorn = {extras = ["standard"], version = "^0.34.0"}
pydantic = "^2.11"
pydantic-settings = "^2.9"
httpx = "^0.28"
aiofiles = "^24.1"
watchfiles = "^1.0"
ruff = "^0.11"
mypy = "^1.15"
pytest = "^8.3"
pytest-asyncio = "^0.25"
```

### `frontend/package.json`

```
vue: "^3.5"
vite: "^6"
pinia: "^2"
vue-router: "^4"
tailwindcss: "^4"
typescript: "~5.7"
vitest: "^3"
vue-tsc: "^2"
```

## 6. CI workflow

`.github/workflows/hephaestus-loop-ci.yml`:
- Trigger: push/PR to `main`, paths: `backend/**`, `frontend/**`
- Backend job: `ruff check`, `mypy --strict`, `pytest -x`
- Frontend job: `pnpm install`, `vue-tsc --noEmit`, `vitest run`

## 7. CSS design tokens

`frontend/src/styles/tokens.css` — verbatim from `index.html:8-16`:
```css
:root {
  --bg: #0a0a0a;
  --panel: #131313;
  --panel-2: #1a1a1a;
  --panel-3: #202020;
  --border: #232323;
  --border-2: #2f2f2f;
  --primary: #faff69;
  --on-primary: #0a0a0a;
  --text: #e6e6e6;
  --muted: #888;
  --muted-soft: #7a7a7a;
  --green: #34d399;
  --rose: #f87171;
  --amber: #fbbf24;
  --blue: #60a5fa;
  --cyan: #22d3ee;
  --violet: #a78bfa;
  --pink: #f472b6;
}
```

## 8. Exit criteria

1. `pytest backend/tests/` green (including contract tests where applicable)
2. `ruff check backend/` clean
3. `mypy --strict backend/` clean
4. `pnpm build` in `frontend/` succeeds
5. Loop continues running on host

## 9. Rollback

`rm -rf backend/ frontend/ .github/` — no production paths touched.

## 10. Out of scope

- HTTP endpoints beyond /healthz
- WebSocket
- Changes to dashboard/server.py, index.html, driver.sh, lib/, prompts/
- Changes to start-dashboard.sh
- FastAPI server startup
- Vue components beyond App.vue placeholder
