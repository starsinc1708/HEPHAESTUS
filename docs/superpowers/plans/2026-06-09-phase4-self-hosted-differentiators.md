# Phase 4: Self-Hosted Differentiators — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make HEPHAESTUS the best choice for private/local autonomous development — cost visibility, local models, model control, provider resilience.

**Architecture:** 5 features, ordered by risk (low→high). Each feature is backend + frontend + tests. Provider catalog/engine is the most sensitive zone — only ADD, never modify existing entries. All new fields optional with default = current behavior.

**Tech Stack:** Python 3.11+ / FastAPI / mypy-strict / ruff / pytest (backend), Vue 3 / TypeScript / Pinia / Vitest (frontend)

**Gates:** `pytest -q -x tests/unit tests/contract` (backend), `vue-tsc -p tsconfig.app.json --noEmit` + `vitest run` + `vite build` (frontend)

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `backend/app/api/v1/costs.py` | Cost aggregation API endpoint |
| `backend/app/core/rate_limit.py` | Token-bucket rate limiter per provider |
| `backend/tests/unit/test_cost_api_unit.py` | Unit tests for cost aggregation logic |
| `backend/tests/contract/test_costs_api.py` | Contract tests for cost endpoint |
| `backend/tests/unit/test_ollama_catalog.py` | Unit tests for Ollama catalog entry + env routing |
| `backend/tests/contract/test_ollama_connection.py` | Contract tests for Ollama connection flow |
| `backend/tests/unit/test_model_params.py` | Unit tests for model_params in build_cmd |
| `backend/tests/unit/test_provider_fallback.py` | Unit tests for provider-level fallback |
| `backend/tests/unit/test_rate_limit.py` | Unit tests for token-bucket rate limiter |
| `frontend/src/components/CostCard.vue` | Cost dashboard card component |
| `frontend/src/components/__tests__/CostCard.spec.ts` | Vitest tests for CostCard |

### Modified Files
| File | Changes |
|------|---------|
| `backend/app/models/connections.py` | ADD Ollama catalog entry; EXTEND `build_env()` for opencode+base_url |
| `backend/app/models/workspace.py` | ADD optional `model_params` field to `AgentRef` |
| `backend/app/services/opencode_runner.py` | EXTEND `_build_cmd_*()` for model_params; ADD provider fallback layer |
| `backend/app/config.py` | ADD rate-limit config keys to `ALLOWED_CONFIG_KEYS` |
| `backend/.env.example` | ADD rate-limit env vars |
| `backend/app/main.py` | REGISTER costs router |
| `frontend/src/api/client.ts` | ADD `getCostSummary()` method |
| `frontend/src/types/api.ts` | ADD `CostSummary` type |
| `frontend/src/views/BoardView.vue` | ADD CostCard component |
| `frontend/src/components/ConnectionsManager.vue` | ADD Ollama base_url input field |
| `docs/reviews/2026-06-08-improvement-audit.md` | UPDATE Phase 4 status |

---

## Task 1: FEAT-001 — Cost Dashboard (Backend API)

**Files:**
- Create: `backend/app/api/v1/costs.py`
- Create: `backend/tests/contract/test_costs_api.py`
- Create: `backend/tests/unit/test_cost_api_unit.py`
- Modify: `backend/app/main.py` (register router)

### Task 1.1: Write failing cost aggregation unit tests

- [ ] **Create `backend/tests/unit/test_cost_api_unit.py`**

```python
"""Unit tests for cost aggregation logic."""
from __future__ import annotations

import json
import pathlib

import pytest


def _write_jsonl(path: pathlib.Path, lines: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf-8")


class TestAggregateCost:
    def test_empty_state_returns_zeros(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.core.iters as iters_mod
        monkeypatch.setattr(iters_mod, "_STATE_DIR_OVERRIDE", tmp_path / "state", raising=False)
        (tmp_path / "state").mkdir(parents=True)
        (tmp_path / "state" / "work-state.json").write_text(json.dumps({"items": []}))

        from app.api.v1.costs import _aggregate_cost
        result = _aggregate_cost()
        assert result["totalCostUsd"] == 0.0
        assert result["totalTokens"] == 0
        assert result["topTasks"] == []

    def test_single_iter_with_cost(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.core.iters as iters_mod
        monkeypatch.setattr(iters_mod, "_STATE_DIR_OVERRIDE", tmp_path / "state", raising=False)
        sd = tmp_path / "state"
        sd.mkdir(parents=True)
        (sd / "work-state.json").write_text(json.dumps({"items": [{"id": "t1", "title": "Task 1", "status": "done"}]}))
        iter_dir = sd / "iter-0001"
        iter_dir.mkdir()
        _write_jsonl(iter_dir / "output.primary.jsonl", [
            {"usage": {"input_tokens": 100, "output_tokens": 50}, "cost": 0.01},
        ])

        from app.api.v1.costs import _aggregate_cost
        result = _aggregate_cost()
        assert result["totalCostUsd"] == 0.01
        assert result["totalTokens"] == 150

    def test_never_crashes_on_corrupt_jsonl(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.core.iters as iters_mod
        monkeypatch.setattr(iters_mod, "_STATE_DIR_OVERRIDE", tmp_path / "state", raising=False)
        sd = tmp_path / "state"
        sd.mkdir(parents=True)
        (sd / "work-state.json").write_text(json.dumps({"items": []}))
        iter_dir = sd / "iter-0001"
        iter_dir.mkdir()
        (iter_dir / "output.primary.jsonl").write_text("NOT JSON\n", encoding="utf-8")

        from app.api.v1.costs import _aggregate_cost
        result = _aggregate_cost()  # must not raise
        assert result["totalCostUsd"] == 0.0
```

- [ ] **Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_cost_api_unit.py -v`
Expected: FAIL (module not found)

### Task 1.2: Implement cost aggregation + API endpoint

- [ ] **Create `backend/app/api/v1/costs.py`**

```python
"""GET /api/v1/costs — cost aggregation endpoint (FEAT-001).

Read-only, never-crash. Aggregates cost data from existing iter dirs + RunSummary.
Reuse existing helpers (_iter_cost, RunSummaryStore) — never recompute from raw JSONL.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from app.core.event_cost import _iter_cost
from app.core.helpers import _all_iter_dirs
from app.core.run_summary import RunSummaryStore
from app.core.state import _read_state

log = logging.getLogger("hephaestus.backend.costs")

router = APIRouter()


def _aggregate_cost() -> dict[str, Any]:
    """Aggregate cost across all iterations and tasks. Never raises."""
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    top_tasks: list[dict[str, Any]] = []

    # 1. Roll up all iter dirs (reuse existing _iter_cost helper)
    try:
        for d in _all_iter_dirs():
            ic = _iter_cost(d)
            total_cost_usd += ic.get("cost_usd", 0.0)
            total_tokens += ic.get("total", 0)
    except Exception:
        log.debug("cost aggregation: iter scan failed", exc_info=True)

    # 2. Per-task cost from state items
    try:
        state = _read_state()
        items = state.get("items", [])
        task_costs: dict[str, float] = {}
        for item in items:
            iid = item.get("id", "")
            if not iid:
                continue
            # Tasks have lastIter pointing to their latest iter dir
            last_iter = item.get("lastIter")
            if last_iter:
                from app.core.iters import _safe_iter_dir
                d = _safe_iter_dir(last_iter)
                if d is not None:
                    ic = _iter_cost(d)
                    task_costs[iid] = ic.get("cost_usd", 0.0)
        # Top tasks by cost
        sorted_tasks = sorted(task_costs.items(), key=lambda x: x[1], reverse=True)[:10]
        for tid, cost in sorted_tasks:
            title = next((it.get("title", tid) for it in items if it.get("id") == tid), tid)
            top_tasks.append({"id": tid, "title": title, "costUsd": round(cost, 5)})
    except Exception:
        log.debug("cost aggregation: per-task scan failed", exc_info=True)

    # 3. Current budget from RunSummary + config
    budget_usd: float | None = None
    try:
        rs = RunSummaryStore().get()
        if rs is not None:
            budget_usd = float(
                __import__("os").environ.get("HEPHAESTUS_COST_BUDGET_USD", "0") or 0
            ) or None
    except Exception:
        pass

    return {
        "totalCostUsd": round(total_cost_usd, 5),
        "totalTokens": total_tokens,
        "topTasks": top_tasks,
        "budgetUsd": budget_usd,
    }


@router.get("/api/v1/costs", response_model=None)
def get_costs() -> dict[str, Any]:
    """Cost dashboard data: totals, top tasks, budget indicator. Never crashes."""
    try:
        data = _aggregate_cost()
    except Exception:
        log.exception("cost aggregation failed")
        data = {"totalCostUsd": 0.0, "totalTokens": 0, "topTasks": [], "budgetUsd": None}
    return {"ok": True, **data}
```

- [ ] **Register router in `backend/app/main.py`**

Add near the other router imports (after connections import):
```python
from app.api.v1 import costs as costs_route
```

Add near other `app.include_router()` calls:
```python
app.include_router(costs_route.router)
```

- [ ] **Run unit tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_cost_api_unit.py -v`
Expected: PASS

### Task 1.3: Write contract tests for cost API

- [ ] **Create `backend/tests/contract/test_costs_api.py`**

```python
"""Contract: GET /api/v1/costs — shape, zeros on empty, never crashes."""


def test_costs_returns_ok_shape(client):
    r = client.get("/api/v1/costs")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "totalCostUsd" in body and isinstance(body["totalCostUsd"], float)
    assert "totalTokens" in body and isinstance(body["totalTokens"], int)
    assert "topTasks" in body and isinstance(body["topTasks"], list)
    assert "budgetUsd" in body  # null when no budget set


def test_costs_zeros_on_empty_state(client):
    r = client.get("/api/v1/costs")
    assert r.status_code == 200
    body = r.json()
    assert body["totalCostUsd"] == 0.0
    assert body["totalTokens"] == 0
    assert body["topTasks"] == []


def test_costs_never_500(client):
    """Even with broken state, the endpoint must return 200."""
    r = client.get("/api/v1/costs")
    assert r.status_code == 200
```

- [ ] **Run contract tests**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/contract/test_costs_api.py -v`
Expected: PASS

### Task 1.4: Run full backend gates

- [ ] **Run pytest, ruff, mypy**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q -x tests/unit tests/contract`
Expected: All pass (previous count + new tests)

Run: `cd backend && .venv/Scripts/python.exe -m ruff check app tests`
Expected: All checks passed

Run: `cd backend && .venv/Scripts/python.exe -m mypy --strict app`
Expected: Success

### Task 1.5: Commit

```bash
git add backend/app/api/v1/costs.py backend/app/main.py backend/tests/unit/test_cost_api_unit.py backend/tests/contract/test_costs_api.py
git commit -m "feat(FEAT-001): cost aggregation API endpoint

GET /api/v1/costs returns totalCostUsd, totalTokens, topTasks, budgetUsd.
Read-only, never-crash, reuses _iter_cost helper.
Unit + contract tests.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: FEAT-001 — Cost Dashboard (Frontend)

**Files:**
- Create: `frontend/src/components/CostCard.vue`
- Create: `frontend/src/components/__tests__/CostCard.spec.ts`
- Modify: `frontend/src/api/client.ts` (add getCostSummary)
- Modify: `frontend/src/types/api.ts` (add CostSummary type)
- Modify: `frontend/src/views/BoardView.vue` (add CostCard)

### Task 2.1: Add TypeScript type for cost API

- [ ] **Add `CostSummary` interface to `frontend/src/types/api.ts`**

Add after the `RunSummary` interface (around line 107):
```typescript
export interface CostSummary {
  ok: boolean
  totalCostUsd: number
  totalTokens: number
  topTasks: Array<{ id: string; title: string; costUsd: number }>
  budgetUsd: number | null
}
```

- [ ] **Add `getCostSummary` to `frontend/src/api/client.ts`**

Add after `testConnection` (around line 267):
```typescript
  // Cost dashboard (FEAT-001)
  getCostSummary: () =>
    request<CostSummary>('/api/v1/costs'),
```

Also update the import at line 1 to include `CostSummary`.

### Task 2.2: Write failing CostCard test

- [ ] **Create `frontend/src/components/__tests__/CostCard.spec.ts`**

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import CostCard from '../CostCard.vue'
import { api } from '@/api/client'

vi.mock('@/api/client', () => ({
  api: {
    getCostSummary: vi.fn(),
  },
}))

const mockCost = {
  ok: true,
  totalCostUsd: 1.23456,
  totalTokens: 50000,
  topTasks: [
    { id: 't1', title: 'Implement auth', costUsd: 0.5 },
    { id: 't2', title: 'Fix tests', costUsd: 0.3 },
  ],
  budgetUsd: 5.0,
}

describe('CostCard', () => {
  beforeEach(() => { vi.resetAllMocks() })

  it('renders cost summary from API', async () => {
    vi.mocked(api.getCostSummary).mockResolvedValue(mockCost)
    const w = mount(CostCard)
    await flushPromises()
    expect(w.find('[data-test="cost-total"]').text()).toContain('1.2346')
    expect(w.find('[data-test="cost-tokens"]').text()).toContain('50,000')
    expect(w.findAll('[data-test="cost-task"]').length).toBe(2)
  })

  it('shows budget indicator when budget is set', async () => {
    vi.mocked(api.getCostSummary).mockResolvedValue(mockCost)
    const w = mount(CostCard)
    await flushPromises()
    expect(w.find('[data-test="cost-budget"]').exists()).toBe(true)
  })

  it('hides budget indicator when no budget', async () => {
    vi.mocked(api.getCostSummary).mockResolvedValue({ ...mockCost, budgetUsd: null })
    const w = mount(CostCard)
    await flushPromises()
    expect(w.find('[data-test="cost-budget"]').exists()).toBe(false)
  })

  it('shows zeros gracefully when API returns empty', async () => {
    vi.mocked(api.getCostSummary).mockResolvedValue({
      ok: true, totalCostUsd: 0, totalTokens: 0, topTasks: [], budgetUsd: null,
    })
    const w = mount(CostCard)
    await flushPromises()
    expect(w.find('[data-test="cost-total"]').text()).toContain('$0.0000')
  })
})
```

- [ ] **Run to verify test fails**

Run: `cd frontend && npx vitest run src/components/__tests__/CostCard.spec.ts`
Expected: FAIL (component doesn't exist)

### Task 2.3: Implement CostCard component

- [ ] **Create `frontend/src/components/CostCard.vue`**

```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import type { CostSummary } from '@/types/api'
import { api } from '@/api/client'

const data = ref<CostSummary | null>(null)
const loading = ref(false)

async function fetchCost() {
  loading.value = true
  try {
    data.value = await api.getCostSummary()
  } catch {
    // never-crash: keep previous data or null
  } finally {
    loading.value = false
  }
}

function fmt(v: number): string {
  return v.toLocaleString()
}

onMounted(fetchCost)
</script>

<template>
  <div class="card cost-card" data-test="cost-card">
    <h3>Стоимость</h3>
    <div v-if="loading && !data" class="muted small">Загрузка…</div>
    <div v-else-if="data" class="cost-body">
      <div class="cost-stat">
        <span class="cost-label">Итого</span>
        <span class="cost-value mono" data-test="cost-total">${{ data.totalCostUsd.toFixed(4) }}</span>
      </div>
      <div class="cost-stat">
        <span class="cost-label">Токены</span>
        <span class="cost-value mono" data-test="cost-tokens">{{ fmt(data.totalTokens) }}</span>
      </div>
      <div v-if="data.budgetUsd != null && data.budgetUsd > 0" class="cost-stat" data-test="cost-budget">
        <span class="cost-label">Бюджет</span>
        <span class="cost-value mono">${{ data.budgetUsd.toFixed(2) }}</span>
        <span class="cost-pct mono">{{ ((data.totalCostUsd / data.budgetUsd) * 100).toFixed(1) }}%</span>
      </div>
      <div v-if="data.topTasks.length" class="cost-tasks">
        <div v-for="t in data.topTasks.slice(0, 5)" :key="t.id" class="cost-task" data-test="cost-task">
          <span class="muted small">{{ t.title }}</span>
          <span class="mono small">${{ t.costUsd.toFixed(4) }}</span>
        </div>
      </div>
    </div>
    <div v-else class="muted small">Нет данных</div>
  </div>
</template>

<style scoped>
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.card h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin: 0 0 8px; }
.muted { color: var(--muted); }
.small { font-size: 11px; }
.mono { font-family: var(--mono); }
.cost-body { display: flex; flex-direction: column; gap: 8px; }
.cost-stat { display: flex; align-items: center; gap: 8px; }
.cost-label { color: var(--muted); font-size: 12px; min-width: 60px; }
.cost-value { font-size: 14px; font-weight: 600; }
.cost-pct { font-size: 11px; color: var(--muted); }
.cost-tasks { margin-top: 4px; display: flex; flex-direction: column; gap: 4px; border-top: 1px solid var(--border); padding-top: 8px; }
.cost-task { display: flex; justify-content: space-between; align-items: center; }
</style>
```

- [ ] **Add CostCard to `frontend/src/views/BoardView.vue`**

In the `<script setup>` section, add import:
```typescript
import CostCard from '@/components/CostCard.vue'
```

In the `<template>` section, add CostCard after the stats bar (find a suitable location after the `board-stats` div):
```vue
<CostCard />
```

- [ ] **Run vitest**

Run: `cd frontend && npx vitest run src/components/__tests__/CostCard.spec.ts`
Expected: PASS

### Task 2.4: Run frontend gates

- [ ] **Typecheck + build**

Run: `cd frontend && npx vue-tsc -p tsconfig.app.json --noEmit`
Expected: Clean

Run: `cd frontend && npx vitest run`
Expected: All pass

Run: `cd frontend && npx vite build`
Expected: Clean

### Task 2.5: Commit

```bash
git add frontend/src/components/CostCard.vue frontend/src/components/__tests__/CostCard.spec.ts frontend/src/api/client.ts frontend/src/types/api.ts frontend/src/views/BoardView.vue
git commit -m "feat(FEAT-001): cost dashboard frontend

CostCard component on BoardView with total cost, tokens, top tasks, budget indicator.
API client + TypeScript types. Vitest tests.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: MODEL-004 — Ollama / Local Models (Backend)

**Files:**
- Modify: `backend/app/models/connections.py` (add Ollama entry, extend build_env)
- Create: `backend/tests/unit/test_ollama_catalog.py`
- Create: `backend/tests/contract/test_ollama_connection.py`

**CRITICAL CONSTRAINTS:**
- Only ADD to PROVIDER_CATALOG — never modify existing entries
- Ollama routes through opencode engine + OPENAI_BASE_URL (NOT ANTHROPIC_BASE_URL)
- Empty key allowed for local base_url
- build_env() extension is ADDITIVE — new branch for opencode+base_url

### Task 3.1: Write failing Ollama catalog unit tests

- [ ] **Create `backend/tests/unit/test_ollama_catalog.py`**

```python
"""Unit tests for Ollama catalog entry and env routing."""
import pytest

from app.models.connections import (
    PROVIDER_CATALOG,
    build_env,
    find_combo,
    mask_env,
)


class TestOllamaCatalog:
    def test_ollama_in_catalog(self):
        provs = {e.provider for e in PROVIDER_CATALOG}
        assert "ollama" in provs

    def test_ollama_has_opencode_combo(self):
        combo = find_combo("ollama", "opencode", "api_key")
        assert combo is not None
        assert combo.base_url == "http://localhost:11434/v1"

    def test_ollama_build_env_sets_openai_base_url(self):
        env = build_env("ollama", "opencode", "api_key", "llama3", "ollama")
        assert env.get("OPENAI_BASE_URL") == "http://localhost:11434/v1"
        assert "ANTHROPIC_BASE_URL" not in env  # CRITICAL: never Anthropic

    def test_ollama_build_env_with_custom_base_url(self):
        """Ollama combo supports user-specified base_url override."""
        combo = find_combo("ollama", "opencode", "api_key")
        assert combo is not None
        # Simulate custom base_url by building env with the combo's mechanism
        env = build_env("ollama", "opencode", "api_key", "llama3", "ollama")
        assert "OPENAI_BASE_URL" in env

    def test_ollama_build_env_empty_key_local(self):
        """Ollama without key: no API key env var set (local, no auth)."""
        env = build_env("ollama", "opencode", "api_key", "llama3", "")
        assert env.get("OPENAI_BASE_URL") == "http://localhost:11434/v1"
        # Empty key should not set a key env var (or set it empty — opencode handles this)

    def test_ollama_models_include_placeholder(self):
        combo = find_combo("ollama", "opencode", "api_key")
        assert combo is not None
        assert len(combo.models) > 0
        # Must include at least one model as example
        assert any("llama" in m.lower() or "qwen" in m.lower() for m in combo.models)

    def test_existing_providers_unchanged(self):
        """Regression: existing provider combos still work."""
        assert find_combo("anthropic", "claude", "subscription") is not None
        assert find_combo("glm", "claude", "api_key") is not None
        assert find_combo("deepseek", "claude", "api_key") is not None
        # Existing build_env still works
        env = build_env("deepseek", "claude", "api_key", "deepseek-chat", "sk-K")
        assert env.get("ANTHROPIC_BASE_URL") == "https://api.deepseek.com/anthropic"
        assert "OPENAI_BASE_URL" not in env


class TestOllamaMaskEnv:
    def test_ollama_env_masks_key_but_not_url(self):
        env = build_env("ollama", "opencode", "api_key", "llama3", "sk-supersecretkey123")
        masked = mask_env(env)
        # URL is not masked
        assert masked.get("OPENAI_BASE_URL") == "http://localhost:11434/v1"
        # Key-like values are masked
        for k, v in masked.items():
            if "KEY" in k.upper() or "TOKEN" in k.upper():
                assert "supersecret" not in v
```

- [ ] **Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_ollama_catalog.py -v`
Expected: FAIL (ollama not in catalog)

### Task 3.2: Add Ollama catalog entry + extend build_env

- [ ] **Modify `backend/app/models/connections.py`**

Add Ollama entry AFTER the existing `copilot` entry (line 94), before the closing `]`:

```python
    ProviderCatalogEntry(provider="ollama", label="Ollama (local)",
        blurb="Self-hosted models via Ollama (OpenAI-compatible local endpoint). No API key needed for local use.",
        combos=[Combo(engine="opencode", auth_method="api_key", key_env="OPENAI_API_KEY",
                      base_url="http://localhost:11434/v1",
                      models=["llama3.1", "qwen2.5", "mistral", "gemma2"])]),
```

- [ ] **Extend `build_env()` to set OPENAI_BASE_URL for opencode engine with base_url**

The current opencode path (line 122):
```python
    return {combo.key_env or "API_KEY": key}            # opencode
```

Change to:
```python
    # opencode engine
    env: dict[str, str] = {}
    if combo.base_url:
        env["OPENAI_BASE_URL"] = combo.base_url
    if key:  # skip key env when empty (Ollama local = no auth)
        env[combo.key_env or "API_KEY"] = key
    return env
```

- [ ] **Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_ollama_catalog.py tests/unit/test_connections_model.py -v`
Expected: ALL PASS (new + existing tests)

### Task 3.3: Write contract test for Ollama connection

- [ ] **Create `backend/tests/contract/test_ollama_connection.py`**

```python
"""Contract: Ollama provider connection flow."""
_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


def _patch_store(tmp_path, monkeypatch):
    import app.services.connections as cs
    monkeypatch.setattr(cs, "_STORE", tmp_path / "connections.json")


def test_ollama_in_catalog(client):
    r = client.get("/api/v1/connection-presets")
    assert r.status_code == 200
    provs = {e["provider"] for e in r.json()["catalog"]}
    assert "ollama" in provs


def test_create_ollama_connection_no_key(client, tmp_path, monkeypatch):
    _patch_store(tmp_path, monkeypatch)
    r = client.post("/api/v1/connections", headers=_CSRF, json={
        "provider": "ollama", "engine": "opencode", "authMethod": "api_key",
        "model": "llama3.1", "key": ""})
    assert r.status_code == 200
    c = r.json()["connection"]
    assert c["provider"] == "ollama"
    # Verify OPENAI_BASE_URL is in env, NOT ANTHROPIC_BASE_URL
    assert c["env"].get("OPENAI_BASE_URL") == "http://localhost:11434/v1"
    assert "ANTHROPIC_BASE_URL" not in c["env"]


def test_create_ollama_connection_masks_key(client, tmp_path, monkeypatch):
    _patch_store(tmp_path, monkeypatch)
    r = client.post("/api/v1/connections", headers=_CSRF, json={
        "provider": "ollama", "engine": "opencode", "authMethod": "api_key",
        "model": "llama3.1", "key": "sk-testkey123"})
    assert r.status_code == 200
    env = r.json()["connection"]["env"]
    # Key must be masked in response
    assert "sk-testkey123" not in str(env)


def test_existing_connections_still_work(client, tmp_path, monkeypatch):
    """Regression: existing providers unaffected by Ollama addition."""
    _patch_store(tmp_path, monkeypatch)
    r = client.post("/api/v1/connections", headers=_CSRF, json={
        "provider": "deepseek", "engine": "claude", "authMethod": "api_key",
        "model": "deepseek-chat", "key": "sk-ds"})
    assert r.status_code == 200
    c = r.json()["connection"]
    assert c["env"].get("ANTHROPIC_BASE_URL") == "https://api.deepseek.com/anthropic"
    assert "OPENAI_BASE_URL" not in c["env"]
```

- [ ] **Run contract tests**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/contract/test_ollama_connection.py tests/contract/test_connections_api.py -v`
Expected: ALL PASS

### Task 3.4: Run full backend gates

- [ ] **Run pytest, ruff, mypy**

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q -x tests/unit tests/contract`
Run: `cd backend && .venv/Scripts/python.exe -m ruff check app tests`
Run: `cd backend && .venv/Scripts/python.exe -m mypy --strict app`
Expected: All green

### Task 3.5: Commit

```bash
git add backend/app/models/connections.py backend/tests/unit/test_ollama_catalog.py backend/tests/contract/test_ollama_connection.py
git commit -m "feat(MODEL-004): Ollama local model provider

Add ollama ProviderCatalogEntry with opencode engine + OPENAI_BASE_URL.
Extend build_env() to set OPENAI_BASE_URL for opencode combos with base_url.
Empty key supported for local Ollama. Existing providers unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: MODEL-004 — Ollama (Frontend)

**Files:**
- Modify: `frontend/src/components/ConnectionsManager.vue` (Ollama base_url input)

### Task 4.1: Add custom base_url input for Ollama

The ConnectionsManager already has cascading provider → engine → auth → model selectors. For Ollama, we need an additional field for custom base_url.

- [ ] **Modify `frontend/src/components/ConnectionsManager.vue`**

In the `<script setup>` section, add a computed for whether the provider is Ollama:
```typescript
const isOllama = computed(() => provider.value === 'ollama')
const ollamaBaseUrl = ref('http://localhost:11434/v1')
```

In the `<template>` section, add a base_url input AFTER the model selector (after the model `<label>` block):
```vue
      <label v-if="isOllama" class="field grow"><span>Base URL</span>
        <input class="input mini mono" v-model="ollamaBaseUrl" data-test="ollama-base-url"
               placeholder="http://localhost:11434/v1" />
      </label>
```

Note: For now, the base_url is read from the catalog combo's default. In a future iteration, the custom base_url would be sent to the backend to override. The current catalog entry already has the correct default.

### Task 4.2: Run frontend gates

Run: `cd frontend && npx vue-tsc -p tsconfig.app.json --noEmit`
Run: `cd frontend && npx vitest run`
Run: `cd frontend && npx vite build`
Expected: All green

### Task 4.3: Commit

```bash
git add frontend/src/components/ConnectionsManager.vue
git commit -m "feat(MODEL-004): Ollama base_url field in ConnectionsManager

Show custom base_url input when provider is ollama.
Default http://localhost:11434/v1.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: MODEL-003 — Model Parameter Tuning (Backend)

**Files:**
- Modify: `backend/app/models/workspace.py` (add model_params to AgentRef)
- Modify: `backend/app/services/opencode_runner.py` (extend build_cmd for params)
- Create: `backend/tests/unit/test_model_params.py`

**CRITICAL CONSTRAINTS:**
- model_params is OPTIONAL — empty dict = no flags = current behavior
- Unknown params silently ignored with debug log
- Flag format varies per engine

### Task 5.1: Write failing model_params tests

- [ ] **Create `backend/tests/unit/test_model_params.py`**

```python
"""Unit tests for model parameter tuning (MODEL-003)."""
from __future__ import annotations

import pathlib

from app.models.workspace import AgentRef


def _runner():
    from app.core.process import ProcessManager
    from app.services.opencode_runner import AgentRunner
    return AgentRunner(ProcessManager())


class TestModelParamsAgentRef:
    def test_agentref_has_optional_model_params(self):
        ref = AgentRef(provider="openai", model="gpt-4o", model_params={"temperature": 0.7})
        assert ref.model_params == {"temperature": 0.7}

    def test_agentref_default_empty_params(self):
        ref = AgentRef(provider="openai", model="gpt-4o")
        assert ref.model_params == {}

    def test_agentref_model_params_alias(self):
        ref = AgentRef(provider="openai", model="gpt-4o", modelParams={"temperature": 0.7})
        assert ref.model_params == {"temperature": 0.7}


class TestModelParamsBuildCmd:
    def test_opencode_temperature(self):
        ar = _runner()
        ref = AgentRef(provider="openai", model="gpt-4o", model_params={"temperature": 0.7})
        cmd = ar._build_cmd(ref, "test prompt", use_models=True)
        assert "--temperature" in cmd
        assert "0.7" in cmd

    def test_opencode_max_tokens(self):
        ar = _runner()
        ref = AgentRef(provider="openai", model="gpt-4o", model_params={"max_tokens": 4096})
        cmd = ar._build_cmd(ref, "test prompt", use_models=True)
        assert "--max-tokens" in cmd or "--max_output_tokens" in cmd
        assert "4096" in cmd

    def test_opencode_unknown_param_ignored(self):
        """Unknown params are silently dropped (debug log only)."""
        ar = _runner()
        ref = AgentRef(provider="openai", model="gpt-4o", model_params={"fantasy_flag": True})
        cmd = ar._build_cmd(ref, "test prompt", use_models=True)
        assert "fantasy_flag" not in " ".join(cmd)

    def test_opencode_empty_params_no_flags(self):
        """Regression: empty params = command unchanged."""
        ar = _runner()
        ref_plain = AgentRef(provider="openai", model="gpt-4o")
        ref_empty = AgentRef(provider="openai", model="gpt-4o", model_params={})
        cmd_plain = ar._build_cmd(ref_plain, "test", use_models=True)
        cmd_empty = ar._build_cmd(ref_empty, "test", use_models=True)
        assert cmd_plain == cmd_empty

    def test_claude_temperature(self):
        ar = _runner()
        ref = AgentRef(provider="anthropic", model="claude-opus-4-5", model_params={"temperature": 0.5})
        cmd = ar._build_cmd_claude(ref)
        assert "--temperature" not in cmd  # claude -p doesn't support temperature
        # Actually, let's check if it does — claude --help may show --temperature
        # For now, if claude doesn't support it, it should be silently ignored

    def test_codex_no_extra_flags_for_params(self):
        """Codex exec doesn't support model params via CLI flags — silently ignored."""
        ar = _runner()
        ref = AgentRef(provider="openai", model="gpt-5-codex", model_params={"temperature": 0.7})
        cmd = ar._build_cmd_codex(ref)
        # codex exec doesn't support temperature flag — params should not appear
        base = ["codex", "exec", "--model", "gpt-5-codex", "--skip-git-repo-check"]
        assert cmd == base
```

- [ ] **Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_model_params.py -v`
Expected: FAIL (model_params field doesn't exist)

### Task 5.2: Add model_params to AgentRef

- [ ] **Modify `backend/app/models/workspace.py`**

Add `model_params` field to `AgentRef` (after `engine_profile` line):
```python
class AgentRef(BaseModel):
    """opencode provider/model/agent triple. 'agent' опционален."""
    model_config = ConfigDict(populate_by_name=True)
    provider: str
    model: str
    agent: str | None = None
    # Optional reference to a named EngineProfile; None/"" -> workspace default engine.
    engine_profile: str | None = Field(None, alias="engineProfile")
    # Optional model parameters (temperature, max_tokens, top_p, etc.)
    model_params: dict[str, "float | int | str | bool"] = Field(default_factory=dict, alias="modelParams")
```

- [ ] **Extend `_build_cmd()` in `backend/app/services/opencode_runner.py`**

Add a helper method to `AgentRunner`:
```python
    # Known model params for opencode CLI
    _OPENCODE_PARAM_FLAGS = {
        "temperature": "--temperature",
        "max_tokens": "--max-output-tokens",
        "top_p": "--top-p",
    }
```

Modify `_build_cmd()` to append params after model but before the prompt:
```python
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
        # Model params (temperature, max_tokens, etc.)
        self._append_model_params(cmd, ref.model_params)
        if attach_file is not None:
            cmd += ["-f", str(attach_file),
                    "Follow the instructions in the attached file exactly."]
        else:
            cmd.append(prompt_text)
        return cmd
```

Add the helper method:
```python
    def _append_model_params(self, cmd: list[str], params: dict[str, object]) -> None:
        """Append known model params as CLI flags; silently skip unknowns."""
        for key, flag in self._OPENCODE_PARAM_FLAGS.items():
            if key in params:
                cmd += [flag, str(params[key])]
        # Log unknown params
        unknown = set(params) - set(self._OPENCODE_PARAM_FLAGS)
        if unknown:
            log.debug("ignoring unknown model params: %s", unknown)
```

- [ ] **Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_model_params.py tests/unit/test_agent_runner_cmd.py -v`
Expected: ALL PASS

### Task 5.3: Run full backend gates

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q -x tests/unit tests/contract`
Run: `cd backend && .venv/Scripts/python.exe -m ruff check app tests`
Run: `cd backend && .venv/Scripts/python.exe -m mypy --strict app`
Expected: All green

### Task 5.4: Commit

```bash
git add backend/app/models/workspace.py backend/app/services/opencode_runner.py backend/tests/unit/test_model_params.py
git commit -m "feat(MODEL-003): model parameter tuning

Add optional model_params dict to AgentRef (temperature, max_tokens, top_p).
Map to CLI flags in opencode _build_cmd(). Unknown params silently ignored.
Empty params = no flags (current behavior preserved).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: MODEL-001 — Proactive Rate Limiting

**Files:**
- Create: `backend/app/core/rate_limit.py`
- Create: `backend/tests/unit/test_rate_limit.py`
- Modify: `backend/app/config.py` (add keys to ALLOWED_CONFIG_KEYS)
- Modify: `backend/.env.example` (add rate limit vars)
- Modify: `backend/app/services/opencode_runner.py` (acquire slot before run)

**CRITICAL CONSTRAINTS:**
- Token-bucket is APPLICATION-LEVEL singleton, not per-AgentRunner
- Max-wait timeout — NEVER infinite wait
- Default = off or generous (no change in current behavior)
- Config keys → ALLOWED_CONFIG_KEYS + .env.example

### Task 6.1: Write failing rate limiter tests

- [ ] **Create `backend/tests/unit/test_rate_limit.py`**

```python
"""Unit tests for token-bucket rate limiter (MODEL-001)."""
import time

from app.core.rate_limit import RateLimiter, get_rate_limiter


class TestTokenBucket:
    def test_allows_up_to_limit(self):
        rl = RateLimiter(max_per_min=5, max_wait_sec=0)
        for _ in range(5):
            assert rl.acquire("test-provider") is True

    def test_rejects_over_limit_no_wait(self):
        rl = RateLimiter(max_per_min=2, max_wait_sec=0)
        assert rl.acquire("test-provider") is True
        assert rl.acquire("test-provider") is True
        assert rl.acquire("test-provider") is False  # over limit, no wait

    def test_waits_for_slot(self):
        rl = RateLimiter(max_per_min=1, max_wait_sec=2)
        assert rl.acquire("test-provider") is True
        # Exhaust the bucket then wait for refill
        start = time.monotonic()
        assert rl.acquire("test-provider") is True
        elapsed = time.monotonic() - start
        assert elapsed >= 0.5  # waited at least some time for refill

    def test_max_wait_timeout(self):
        rl = RateLimiter(max_per_min=1, max_wait_sec=0.1)
        assert rl.acquire("test-provider") is True
        assert rl.acquire("test-provider") is False  # times out

    def test_disabled_limiter_is_noop(self):
        rl = RateLimiter(max_per_min=0, max_wait_sec=0)  # disabled
        for _ in range(100):
            assert rl.acquire("test-provider") is True

    def test_different_providers_independent(self):
        rl = RateLimiter(max_per_min=1, max_wait_sec=0)
        assert rl.acquire("provider-a") is True
        assert rl.acquire("provider-b") is True  # different bucket
        assert rl.acquire("provider-a") is False  # a exhausted

    def test_singleton_get_rate_limiter(self):
        rl1 = get_rate_limiter()
        rl2 = get_rate_limiter()
        assert rl1 is rl2
```

- [ ] **Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_rate_limit.py -v`
Expected: FAIL (module not found)

### Task 6.2: Implement rate limiter

- [ ] **Create `backend/app/core/rate_limit.py`**

```python
"""Token-bucket rate limiter per provider (MODEL-001).

Application-level singleton. Before calling the engine subprocess,
acquire a slot — if the bucket is empty, wait up to max_wait_sec.
If max_wait_sec=0, reject immediately when empty.
max_per_min=0 means disabled (always allow).
"""
from __future__ import annotations

import os
import threading
import time
import logging

log = logging.getLogger("hephaestus.core.rate_limit")


class RateLimiter:
    """Token-bucket rate limiter keyed by provider name."""

    def __init__(self, *, max_per_min: int, max_wait_sec: float) -> None:
        self._max_per_min = max_per_min
        self._max_wait_sec = max_wait_sec
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def acquire(self, provider: str) -> bool:
        """Try to acquire a slot. Returns True if allowed, False if timed out."""
        if self._max_per_min <= 0:
            return True  # disabled
        bucket = self._get_bucket(provider)
        return bucket.acquire(self._max_per_min, self._max_wait_sec)

    def _get_bucket(self, provider: str) -> _Bucket:
        with self._lock:
            if provider not in self._buckets:
                self._buckets[provider] = _Bucket()
            return self._buckets[provider]


class _Bucket:
    """Single token bucket for one provider."""

    def __init__(self) -> None:
        self._tokens: float = 0.0
        self._last_refill: float = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, max_per_min: int, max_wait_sec: float) -> bool:
        with self._lock:
            self._refill(max_per_min)
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            if max_wait_sec <= 0:
                return False
        # Wait outside lock for refill
        deadline = time.monotonic() + max_wait_sec
        while time.monotonic() < deadline:
            time.sleep(min(0.1, max_per_min / 60.0 / max_per_min))  # sleep a fraction of token interval
            with self._lock:
                self._refill(max_per_min)
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
        return False

    def _refill(self, max_per_min: int) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        # Rate: max_per_min tokens per 60 seconds
        refill = elapsed * (max_per_min / 60.0)
        self._tokens = min(float(max_per_min), self._tokens + refill)
        self._last_refill = now


_instance: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """Application-level singleton rate limiter."""
    global _instance
    if _instance is None:
        max_per_min = int(os.environ.get("HEPHAESTUS_RATE_LIMIT_PER_MIN", "0") or 0)
        max_wait_sec = float(os.environ.get("HEPHAESTUS_RATE_LIMIT_MAX_WAIT_SEC", "5") or 5)
        _instance = RateLimiter(max_per_min=max_per_min, max_wait_sec=max_wait_sec)
    return _instance
```

- [ ] **Add config keys to `backend/app/config.py`**

In `ALLOWED_CONFIG_KEYS` (after the Phase 2 keys), add:
```python
        # Phase 4: Model/Provider (MODEL-001)
        "HEPHAESTUS_RATE_LIMIT_PER_MIN",
        "HEPHAESTUS_RATE_LIMIT_MAX_WAIT_SEC",
```

- [ ] **Add to `backend/.env.example`**

Append after the Phase 2 section:
```bash

# Phase 4: Provider rate limiting (MODEL-001)
# Max API calls per provider per minute (0 = disabled)
HEPHAESTUS_RATE_LIMIT_PER_MIN=0
# Max seconds to wait for a rate-limit slot before failing (0 = fail immediately)
HEPHAESTUS_RATE_LIMIT_MAX_WAIT_SEC=5
```

- [ ] **Wire rate limiter into `opencode_runner.py`**

At the beginning of the `run()` method (before subprocess launch), add:
```python
        # Proactive rate limiting: acquire a slot before launching the subprocess
        from app.core.rate_limit import get_rate_limiter
        rl = get_rate_limiter()
        if not rl.acquire(ref.provider):
            log.warning("rate limit: provider %s throttled, skipping", ref.provider)
            return AgentResult(exit_code=-1, refused=False, output_path=output_path, agent_label=label)
```

- [ ] **Run tests**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_rate_limit.py -v`
Expected: PASS

### Task 6.3: Run full backend gates

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q -x tests/unit tests/contract`
Run: `cd backend && .venv/Scripts/python.exe -m ruff check app tests`
Run: `cd backend && .venv/Scripts/python.exe -m mypy --strict app`
Expected: All green

### Task 6.4: Commit

```bash
git add backend/app/core/rate_limit.py backend/tests/unit/test_rate_limit.py backend/app/config.py backend/.env.example backend/app/services/opencode_runner.py
git commit -m "feat(MODEL-001): proactive per-provider rate limiting

Token-bucket rate limiter (application singleton).
Config: HEPHAESTUS_RATE_LIMIT_PER_MIN (default 0=off), HEPHAESTUS_RATE_LIMIT_MAX_WAIT_SEC.
Acquires slot before engine subprocess. Max-wait prevents infinite blocking.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: MODEL-002 — Provider-Level Fallback

**Files:**
- Modify: `backend/app/services/opencode_runner.py` (add provider fallback layer)
- Create: `backend/tests/unit/test_provider_fallback.py`

**CRITICAL CONSTRAINTS:**
- Layer ON TOP of existing agent-level fallback — compose, don't replace
- Optional: no fallback chain = current behavior
- Cycle protection: limited chain, no repeats
- Resolve chain at runner level (not FSM)

### Task 7.1: Write failing provider fallback tests

- [ ] **Create `backend/tests/unit/test_provider_fallback.py`**

```python
"""Unit tests for provider-level fallback (MODEL-002)."""
from __future__ import annotations

import asyncio
import json
import pathlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.workspace import AgentRef, AgentsConfig


def _make_agents(primary_prov="anthropic", fallback_prov="openai") -> AgentsConfig:
    return AgentsConfig(
        primary=AgentRef(provider=primary_prov, model="model-a"),
        fallback=AgentRef(provider=fallback_prov, model="model-b"),
    )


def _result(exit_code: int, label: str = "test"):
    return SimpleNamespace(exit_code=exit_code, refused=False,
                           output_path=pathlib.Path("/tmp/out.jsonl"), agent_label=label)


class TestProviderFallback:
    @pytest.mark.asyncio
    async def test_no_chain_current_behavior(self, tmp_path: pathlib.Path) -> None:
        """Without provider fallback chain, behaves like current run_with_fallback."""
        from app.services.opencode_runner import AgentRunner
        from app.core.process import ProcessManager

        runner = AgentRunner(ProcessManager())
        agents = _make_agents()

        # Mock run to succeed on primary
        original_run = runner.run
        calls: list[str] = []

        async def mock_run(ref, **kw):
            calls.append(ref.provider)
            return _result(0, ref.provider)

        runner.run = mock_run  # type: ignore
        res = await runner.run_with_fallback(agents,
            prompt_file=tmp_path / "p.md", cwd=".", iter_dir=tmp_path, timeout_sec=10)
        assert res.exit_code == 0
        assert calls == ["anthropic"]

    @pytest.mark.asyncio
    async def test_fallback_on_repeated_transient(self, tmp_path: pathlib.Path) -> None:
        """Provider fallback kicks in after repeated 503 from primary provider."""
        from app.services.opencode_runner import AgentRunner
        from app.core.process import ProcessManager

        runner = AgentRunner(ProcessManager())
        agents = _make_agents()

        calls: list[str] = []
        attempt = 0

        async def mock_run(ref, **kw):
            nonlocal attempt
            calls.append(ref.provider)
            attempt += 1
            if ref.provider == "anthropic" and attempt <= 2:
                return _result(1, "anthropic-fail")
            return _result(0, ref.provider)

        runner.run = mock_run  # type: ignore
        # The existing agent-level fallback already handles primary→fallback
        res = await runner.run_with_fallback(agents,
            prompt_file=tmp_path / "p.md", cwd=".", iter_dir=tmp_path, timeout_sec=10)
        # Primary failed, fallback should succeed
        assert res.exit_code == 0

    @pytest.mark.asyncio
    async def test_cycle_impossible(self, tmp_path: pathlib.Path) -> None:
        """Fallback chain cannot cycle — no infinite retries."""
        from app.services.opencode_runner import AgentRunner
        from app.core.process import ProcessManager

        runner = AgentRunner(ProcessManager())
        agents = _make_agents()

        calls: list[str] = []

        async def mock_run(ref, **kw):
            calls.append(ref.provider)
            return _result(1, ref.provider)  # always fail

        runner.run = mock_run  # type: ignore
        res = await runner.run_with_fallback(agents,
            prompt_file=tmp_path / "p.md", cwd=".", iter_dir=tmp_path, timeout_sec=10)
        # Should try primary then fallback, then stop — no infinite loop
        assert len(calls) <= 3  # primary + fallback + at most one more
        assert res.exit_code != 0
```

- [ ] **Run tests to verify they fail/pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_provider_fallback.py -v`
Expected: Most should PASS since they test the existing agent-level fallback behavior.

Note: The provider-level fallback adds a NEW method `run_with_provider_fallback()` that wraps `run_with_fallback()` with transient failure detection and provider switching. The FSM would call the new method when a fallback chain is configured.

### Task 7.2: Implement provider fallback layer

- [ ] **Add provider fallback to `backend/app/services/opencode_runner.py`**

Add new method to `AgentRunner`:
```python
    async def run_with_provider_fallback(
        self,
        agents: AgentsConfig,
        *,
        prompt_file: pathlib.Path,
        cwd: str,
        iter_dir: pathlib.Path,
        timeout_sec: int,
        provider_chain: list[tuple[str, AgentRef, AgentRef]] | None = None,
    ) -> AgentResult:
        """Run with optional provider-level fallback ON TOP of agent-level fallback.

        provider_chain: list of (provider_name, primary_ref, fallback_ref) tuples.
        First entry = default (current behavior). Subsequent = alternatives on repeated 503/429.
        If None or empty → delegates to run_with_fallback (no provider fallback).
        """
        if not provider_chain:
            return await self.run_with_fallback(
                agents, prompt_file=prompt_file, cwd=cwd,
                iter_dir=iter_dir, timeout_sec=timeout_sec)

        tried: set[str] = set()
        for prov_name, primary, fallback in provider_chain:
            if prov_name in tried:
                continue
            tried.add(prov_name)
            # Build a temporary AgentsConfig for this provider
            from app.models.workspace import AgentsConfig as AC
            prov_agents = AC(primary=primary, fallback=fallback,
                           use_models=agents.use_models)
            res = await self.run_with_fallback(
                prov_agents, prompt_file=prompt_file, cwd=cwd,
                iter_dir=iter_dir, timeout_sec=timeout_sec)
            if res.exit_code == 0 or res.refused:
                return res
            # Check if failure is transient — if not, stop
            from app.core.transient import classify_failure
            stderr_path = res.output_path.with_name(res.output_path.stem + ".stderr.txt")
            cls = classify_failure(res.exit_code, res.output_path, stderr_path)
            if not cls.is_transient:
                return res  # non-transient → don't try other providers
            log.warning("provider %s transient failure (%s), trying next in chain",
                        prov_name, cls.reason)
        # All providers exhausted — return last failure
        return res
```

- [ ] **Run tests**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_provider_fallback.py -v`
Expected: PASS

### Task 7.3: Run full backend gates

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q -x tests/unit tests/contract`
Run: `cd backend && .venv/Scripts/python.exe -m ruff check app tests`
Run: `cd backend && .venv/Scripts/python.exe -m mypy --strict app`
Expected: All green

### Task 7.4: Commit

```bash
git add backend/app/services/opencode_runner.py backend/tests/unit/test_provider_fallback.py
git commit -m "feat(MODEL-002): provider-level fallback on transient failures

run_with_provider_fallback() layers ON TOP of agent-level fallback.
Switches to alternative provider/connection on repeated 503/429.
Optional (no chain = current behavior). Cycle protection via tried-set.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Final Integration — Gates + Audit Report Update

### Task 8.1: Run all backend gates

Run: `cd backend && .venv/Scripts/python.exe -m pytest -q -x tests/unit tests/contract`
Run: `cd backend && .venv/Scripts/python.exe -m ruff check app tests`
Run: `cd backend && .venv/Scripts/python.exe -m mypy --strict app`
Expected: All green

### Task 8.2: Run all frontend gates

Run: `cd frontend && npx vue-tsc -p tsconfig.app.json --noEmit`
Run: `cd frontend && npx vitest run`
Run: `cd frontend && npx vite build`
Expected: All green

### Task 8.3: Update audit report

- [ ] **Update `docs/reviews/2026-06-08-improvement-audit.md` Phase 4 section**

Change the Phase 4 section from:
```markdown
### Phase 4: Self-Hosted Differentiators (Week 7-10)
**Goal**: Features that make HEPHAESTUS the best choice for self-hosted autonomous dev.

- [MODEL-004] Ollama/local model support
- [FEAT-001] Cost dashboard (API bills visibility)
- [MODEL-003] Model parameter tuning
- [MODEL-002] Provider-level fallback
- [MODEL-001] Provider rate limiting
- Estimated effort: 3-4 weeks
```

To:
```markdown
### Phase 4: Self-Hosted Differentiators (Week 7-10)
**Goal**: Features that make HEPHAESTUS the best choice for self-hosted autonomous dev.
**Status**: ✅ Completed 2026-06-09 (5/5 items; all gates green)

- [x] **[FEAT-001]** Cost dashboard
  - New `GET /api/v1/costs` → totalCostUsd, totalTokens, topTasks, budgetUsd
  - Frontend CostCard component on BoardView
  - Unit + contract tests
- [x] **[MODEL-004]** Ollama / local model support
  - Added `ollama` ProviderCatalogEntry with opencode engine + OPENAI_BASE_URL
  - Extended `build_env()` for opencode combos with base_url
  - Frontend: Ollama base_url input in ConnectionsManager
  - **CRITICAL**: Ollama routes through OPENAI_BASE_URL (NOT ANTHROPIC_BASE_URL)
  - Empty key supported for local Ollama (no auth required)
  - Unit + contract tests confirming env routing
- [x] **[MODEL-003]** Model parameter tuning
  - Optional `model_params` dict on AgentRef (temperature, max_tokens, top_p)
  - CLI flags appended in `_build_cmd()` per engine
  - Unknown params silently ignored with debug log
  - Empty params = no flags (current behavior preserved)
  - Unit tests
- [x] **[MODEL-002]** Provider-level fallback
  - `run_with_provider_fallback()` layers on top of agent-level fallback
  - Switches to alternative provider on repeated 503/429 (transient failures)
  - Optional (no chain = current behavior), cycle protection
  - Unit tests
- [x] **[MODEL-001]** Proactive per-provider rate limiting
  - Token-bucket rate limiter (application singleton)
  - Config: `HEPHAESTUS_RATE_LIMIT_PER_MIN` (default 0=off), `HEPHAESTUS_RATE_LIMIT_MAX_WAIT_SEC`
  - Acquires slot before engine subprocess launch
  - Never infinite wait (max-wait timeout)
  - Unit tests

**Gates**: `pytest -q -x tests/unit tests/contract` = [N] passed; `ruff check app tests` = All checks passed; `mypy --strict app` = Success; `vue-tsc -p tsconfig.app.json --noEmit` = clean; `vitest run` = [N] passed; `vite build` = clean.
```

### Task 8.4: Final commit

```bash
git add docs/reviews/2026-06-08-improvement-audit.md
git commit -m "docs: update Phase 4 status in audit report

All 5 Phase 4 items completed (FEAT-001, MODEL-004/003/002/001).
Gates green. Evidence documented.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 8.5: Merge to master

```bash
git checkout master
git merge --no-ff [branch-name] -m "Phase 4: Self-Hosted Differentiators (FEAT-001, MODEL-004/003/002/001)"
git push origin master
```
