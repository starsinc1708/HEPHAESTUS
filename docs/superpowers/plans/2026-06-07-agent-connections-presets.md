# Agent Connections & Presets — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace HEPHAESTUS's raw agent-settings editor with a two-stage preset flow — globally *connect* models (DeepSeek via opencode/claude, GLM via z.ai), test each with a real CLI call, then per-workspace *assign* connected models to agent roles.

**Architecture:** A global `state/connections.json` store holds reusable `Connection`s (provider+engine+model+env+status). A static preset catalog drives the add-connection form. Workspaces store only `roleConnections: {role → connectionId}`; the registry resolves IDs into the in-memory `RepoProfile` (`agents` + `engine_profiles`) at load, so `opencode_runner`/FSM are unchanged. Frontend replaces the raw editor with two sections: global Connections + per-workspace Roles.

**Tech Stack:** FastAPI + Pydantic v2 (camelCase via `Field(alias=...)`), Vue 3 + Pinia + TypeScript, pytest, vitest. Cross-platform (Windows): argv lists, `shutil.which`, never-crash.

**Gates (run after every task that touches them):**
- backend: `backend/.venv/Scripts/python.exe -m pytest -q` + `ruff check app tests` + `mypy --strict app/`
- frontend: `npx vitest run` + `npx vue-tsc --noEmit` + `npm run build`

---

### Task 1: Connection models + preset catalog

**Files:**
- Create: `backend/app/models/connections.py`
- Test: `backend/tests/unit/test_connections_model.py`

- [ ] **Step 1: Write the failing test**
```python
# backend/tests/unit/test_connections_model.py
from app.models.connections import PRESETS, ConnectionPreset, build_env, mask_env


def test_presets_cover_deepseek_and_glm():
    by = {p.provider: p for p in PRESETS}
    assert set(by) == {"deepseek", "glm"}
    assert by["deepseek"].engines == ["claude", "opencode"]
    assert by["glm"].engines == ["claude"]
    assert "deepseek-chat" in by["deepseek"].models
    assert "glm-4.6" in by["glm"].models


def test_build_env_claude_deepseek():
    env = build_env("deepseek", "claude", "deepseek-chat", "sk-KEY")
    assert env == {
        "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
        "ANTHROPIC_AUTH_TOKEN": "sk-KEY",
        "ANTHROPIC_MODEL": "deepseek-chat",
    }


def test_build_env_claude_glm():
    env = build_env("glm", "claude", "glm-4.6", "zk-KEY")
    assert env["ANTHROPIC_BASE_URL"] == "https://api.z.ai/api/anthropic"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "zk-KEY"
    assert env["ANTHROPIC_MODEL"] == "glm-4.6"


def test_build_env_opencode_deepseek():
    env = build_env("deepseek", "opencode", "deepseek-chat", "sk-KEY")
    assert env == {"DEEPSEEK_API_KEY": "sk-KEY"}


def test_build_env_rejects_unsupported_engine():
    import pytest
    with pytest.raises(ValueError):
        build_env("glm", "opencode", "glm-4.6", "k")  # glm has no opencode engine


def test_mask_env_hides_secrets_keeps_url():
    masked = mask_env({"ANTHROPIC_BASE_URL": "https://x", "ANTHROPIC_AUTH_TOKEN": "sk-abcdef1234"})
    assert masked["ANTHROPIC_BASE_URL"] == "https://x"
    assert masked["ANTHROPIC_AUTH_TOKEN"].startswith("sk-") and "***" in masked["ANTHROPIC_AUTH_TOKEN"]
    assert "abcdef" not in masked["ANTHROPIC_AUTH_TOKEN"]
```

- [ ] **Step 2: Run to verify it fails** — `…pytest tests/unit/test_connections_model.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement**
```python
# backend/app/models/connections.py
"""Connection + preset catalog for the agent-settings redesign (global model connections)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Connection(BaseModel):
    """A globally-stored, reusable model endpoint (provider + engine + model + env)."""
    model_config = ConfigDict(populate_by_name=True)
    id: str
    label: str
    provider: str                      # "deepseek" | "glm"
    engine: str                        # "claude" | "opencode"
    model: str
    env: dict[str, str] = Field(default_factory=dict)
    status: str = "untested"           # untested | connected | failed
    last_tested_at: str | None = Field(None, alias="lastTestedAt")
    last_error: str | None = Field(None, alias="lastError")


class ConnectionPreset(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    provider: str
    label: str
    engines: list[str]
    models: list[str]
    base_url: str | None = Field(None, alias="baseUrl")
    key_env: str = Field("ANTHROPIC_AUTH_TOKEN", alias="keyEnv")


PRESETS: list[ConnectionPreset] = [
    ConnectionPreset(
        provider="deepseek", label="DeepSeek", engines=["claude", "opencode"],
        models=["deepseek-chat", "deepseek-reasoner"],
        base_url="https://api.deepseek.com/anthropic",
    ),
    ConnectionPreset(
        provider="glm", label="GLM (z.ai coding plan)", engines=["claude"],
        models=["glm-4.6", "glm-4.5"],
        base_url="https://api.z.ai/api/anthropic",
    ),
]

_PRESET_BY = {p.provider: p for p in PRESETS}


def build_env(provider: str, engine: str, model: str, key: str) -> dict[str, str]:
    """Engine-specific subprocess env for a connection. Raises ValueError on bad combo."""
    preset = _PRESET_BY.get(provider)
    if preset is None or engine not in preset.engines:
        raise ValueError(f"unsupported provider/engine: {provider}/{engine}")
    if engine == "claude":
        return {
            "ANTHROPIC_BASE_URL": preset.base_url or "",
            "ANTHROPIC_AUTH_TOKEN": key,
            "ANTHROPIC_MODEL": model,
        }
    # opencode (deepseek only): opencode reads DEEPSEEK_API_KEY; model passed as deepseek/<model>
    return {"DEEPSEEK_API_KEY": key}


_SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def mask_env(env: dict[str, str]) -> dict[str, str]:
    """Mask secret-looking values (…KEY/…TOKEN) for API responses; keep URLs/models visible."""
    out: dict[str, str] = {}
    for k, v in env.items():
        if any(h in k.upper() for h in _SECRET_HINTS) and v:
            out[k] = (v[:3] + "***" + v[-2:]) if len(v) > 6 else "***"
        else:
            out[k] = v
    return out
```

- [ ] **Step 4: Run to verify it passes** — `…pytest tests/unit/test_connections_model.py -q` → PASS.
- [ ] **Step 5: Gates** — ruff + `mypy --strict app/` clean. **Commit:** `feat(connections): connection + preset models, env builder, key masking`.

---

### Task 2: Global connections store (CRUD)

**Files:**
- Create: `backend/app/services/connections.py`
- Test: `backend/tests/unit/test_connections_store.py`

Store path: `STATE_DIR / "connections.json"` (import `from app.config import STATE_DIR`). Use `from app.core.state import _atomic_write` for writes. ID = `"conn-" + uuid4().hex[:8]` — but `uuid`/`random` are fine here (this is request-time, not the workflow runtime).

- [ ] **Step 1: Write the failing test**
```python
# backend/tests/unit/test_connections_store.py
import app.services.connections as cs


def test_add_get_list_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "_STORE", tmp_path / "connections.json")
    c = cs.add_connection(provider="deepseek", engine="claude", model="deepseek-chat",
                          key="sk-secret123", label="DS")
    assert c.id.startswith("conn-")
    assert c.status == "untested"
    assert cs.get_connection(c.id).env["ANTHROPIC_AUTH_TOKEN"] == "sk-secret123"  # raw kept server-side
    masked = cs.list_connections_masked()
    assert masked[0]["env"]["ANTHROPIC_AUTH_TOKEN"] != "sk-secret123"
    assert cs.delete_connection(c.id) is True
    assert cs.get_connection(c.id) is None
    assert cs.delete_connection("nope") is False


def test_corrupt_store_is_empty(tmp_path, monkeypatch):
    p = tmp_path / "connections.json"
    p.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(cs, "_STORE", p)
    assert cs.list_connections() == []  # never raises


def test_set_status(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "_STORE", tmp_path / "connections.json")
    c = cs.add_connection(provider="glm", engine="claude", model="glm-4.6", key="zk-1", label="G")
    cs.set_status(c.id, "connected", error=None, tested_at="2026-06-07T00:00:00Z")
    assert cs.get_connection(c.id).status == "connected"
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement**
```python
# backend/app/services/connections.py
"""Global connections store: state/connections.json. Single source of truth for model
endpoints/keys; resolved into per-workspace agent config at registry load."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.config import STATE_DIR
from app.core.state import _atomic_write
from app.models.connections import Connection, build_env, mask_env

log = logging.getLogger("hephaestus.backend.connections")
_STORE = STATE_DIR / "connections.json"


def list_connections() -> list[Connection]:
    if not _STORE.exists():
        return []
    try:
        data = json.loads(_STORE.read_text(encoding="utf-8"))
        return [Connection.model_validate(c) for c in data.get("connections", [])]
    except Exception:
        log.warning("connections.json unreadable — treating as empty", exc_info=True)
        return []


def _save(conns: list[Connection]) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"connections": [c.model_dump(by_alias=True) for c in conns]}
    _atomic_write(_STORE, json.dumps(payload, indent=2, ensure_ascii=False))


def get_connection(conn_id: str) -> Connection | None:
    return next((c for c in list_connections() if c.id == conn_id), None)


def add_connection(*, provider: str, engine: str, model: str, key: str, label: str | None = None) -> Connection:
    env = build_env(provider, engine, model, key)  # raises ValueError on bad combo
    conn = Connection(
        id="conn-" + uuid.uuid4().hex[:8],
        label=label or f"{provider} ({engine})",
        provider=provider, engine=engine, model=model, env=env, status="untested",
    )
    conns = list_connections()
    conns.append(conn)
    _save(conns)
    return conn


def delete_connection(conn_id: str) -> bool:
    conns = list_connections()
    kept = [c for c in conns if c.id != conn_id]
    if len(kept) == len(conns):
        return False
    _save(kept)
    return True


def set_status(conn_id: str, status: str, *, error: str | None, tested_at: str | None) -> None:
    conns = list_connections()
    for c in conns:
        if c.id == conn_id:
            c.status, c.last_error, c.last_tested_at = status, error, tested_at
    _save(conns)


def list_connections_masked() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in list_connections():
        d = c.model_dump(by_alias=True)
        d["env"] = mask_env(c.env)
        out.append(d)
    return out
```

- [ ] **Step 4: Run → PASS. Step 5: Gates + Commit** `feat(connections): global connections.json store (CRUD, masking, never-crash)`.

---

### Task 3: Connection test service (real CLI)

**Files:**
- Create: `backend/app/services/connection_test.py`
- Test: `backend/tests/unit/test_connection_test.py`

Uses the existing `AgentRunner` (`app/services/opencode_runner.py`): build a one-off runner with an `EngineProfile(name="__test__", engine=conn.engine, env=conn.env)` and an `AgentRef(provider, model, engine_profile="__test__")`, run a tiny prompt, inspect `AgentResult.exit_code` + output file. `pm` via `from app.core.process import pm`.

- [ ] **Step 1: Write the failing test** (mock the runner — no real CLI in unit tests)
```python
# backend/tests/unit/test_connection_test.py
import asyncio
import pathlib
from app.models.connections import Connection
import app.services.connection_test as ct


class _FakeRunner:
    def __init__(self, rc, text):
        self._rc, self._text = rc, text
    async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec, use_models=False):
        pathlib.Path(output_path).write_text(self._text, encoding="utf-8")
        from app.services.opencode_runner import AgentResult
        return AgentResult(exit_code=self._rc, refused=False, output_path=output_path, agent_label="x")


def _conn():
    return Connection(id="c1", label="DS", provider="deepseek", engine="claude",
                      model="deepseek-chat", env={"ANTHROPIC_AUTH_TOKEN": "k"})


def test_success_is_connected(monkeypatch):
    monkeypatch.setattr(ct, "_make_runner", lambda conn: _FakeRunner(0, "HEPHAESTUS_CONN_OK"))
    status, err = asyncio.run(ct.test_connection(_conn()))
    assert status == "connected" and err is None


def test_nonzero_is_failed(monkeypatch):
    monkeypatch.setattr(ct, "_make_runner", lambda conn: _FakeRunner(1, ""))
    status, err = asyncio.run(ct.test_connection(_conn()))
    assert status == "failed" and err


def test_runner_minus_one_is_failed_cli_missing(monkeypatch):
    monkeypatch.setattr(ct, "_make_runner", lambda conn: _FakeRunner(-1, ""))
    status, err = asyncio.run(ct.test_connection(_conn()))
    assert status == "failed"
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement**
```python
# backend/app/services/connection_test.py
"""Real-CLI connection test: run the connection's engine on a 1-token prompt (mirrors the
manual HEPHAESTUS_DS_OK smoke test). Never raises — returns (status, error)."""
from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

from app.models.connections import Connection
from app.models.workspace import AgentRef, EngineProfile

log = logging.getLogger("hephaestus.backend.connection_test")
_PROMPT = "Reply with exactly this token and nothing else: HEPHAESTUS_CONN_OK"


def _make_runner(conn: Connection):  # patched in tests
    from app.core.process import pm
    from app.services.opencode_runner import AgentRunner
    return AgentRunner(pm, engine=conn.engine,
                       profiles=[EngineProfile(name="__test__", engine=conn.engine, env=conn.env)])


async def test_connection(conn: Connection) -> tuple[str, str | None]:
    ref = AgentRef(provider=conn.provider, model=conn.model, engine_profile="__test__")
    runner = _make_runner(conn)
    with tempfile.TemporaryDirectory() as d:
        pf = Path(d) / "prompt.md"
        pf.write_text(_PROMPT, encoding="utf-8")
        out = Path(d) / "out.jsonl"
        try:
            res = await runner.run(ref, prompt_file=pf, cwd=d, output_path=out,
                                   timeout_sec=60, use_models=True)
        except Exception as exc:  # never crash the endpoint
            return "failed", f"runner error: {exc}"
        text = out.read_text(encoding="utf-8", errors="replace") if out.exists() else ""
        if res.exit_code == 0 and text.strip():
            return "connected", None
        if res.exit_code == -1:
            return "failed", f"{conn.engine} CLI not found or failed to start"
        tail = (text or "").strip()[-300:]
        return "failed", f"exit {res.exit_code}: {tail or 'no output'}"
```

- [ ] **Step 4: Run → PASS. Step 5: Gates + Commit** `feat(connections): real-CLI connection test service`.

---

### Task 4: Connections API router

**Files:**
- Create: `backend/app/api/v1/connections.py`
- Modify: `backend/app/main.py` (register router — add import near line 179 and `app.include_router(connections_router)` near line 199)
- Test: `backend/tests/contract/test_connections_api.py`

Routes: `GET /api/v1/connection-presets`, `GET /api/v1/connections`, `POST /api/v1/connections`, `DELETE /api/v1/connections/{id}`, `POST /api/v1/connections/{id}/test`. Follow the JSONResponse-on-error convention (see `app/api/v1/merge.py`).

- [ ] **Step 1: Write the failing test**
```python
# backend/tests/contract/test_connections_api.py
_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


def _patch_store(tmp_path, monkeypatch):
    import app.services.connections as cs
    monkeypatch.setattr(cs, "_STORE", tmp_path / "connections.json")


def test_presets(client):
    r = client.get("/api/v1/connection-presets")
    assert r.status_code == 200
    provs = {p["provider"] for p in r.json()["presets"]}
    assert provs == {"deepseek", "glm"}


def test_create_list_masks_key_then_delete(client, tmp_path, monkeypatch):
    _patch_store(tmp_path, monkeypatch)
    r = client.post("/api/v1/connections", headers=_CSRF, json={
        "provider": "deepseek", "engine": "claude", "model": "deepseek-chat", "key": "sk-supersecret9"})
    assert r.status_code == 200
    cid = r.json()["connection"]["id"]
    lst = client.get("/api/v1/connections").json()["connections"]
    assert lst[0]["env"]["ANTHROPIC_AUTH_TOKEN"] != "sk-supersecret9"  # masked
    assert client.delete(f"/api/v1/connections/{cid}", headers=_CSRF).status_code == 200


def test_create_bad_combo_400(client, tmp_path, monkeypatch):
    _patch_store(tmp_path, monkeypatch)
    r = client.post("/api/v1/connections", headers=_CSRF, json={
        "provider": "glm", "engine": "opencode", "model": "glm-4.6", "key": "k"})
    assert r.status_code == 400


def test_test_endpoint(client, tmp_path, monkeypatch):
    _patch_store(tmp_path, monkeypatch)
    cid = client.post("/api/v1/connections", headers=_CSRF, json={
        "provider": "deepseek", "engine": "claude", "model": "deepseek-chat", "key": "k"}).json()["connection"]["id"]
    import app.api.v1.connections as mod
    async def _fake(conn):
        return "connected", None
    monkeypatch.setattr(mod, "test_connection", _fake)
    r = client.post(f"/api/v1/connections/{cid}/test", headers=_CSRF)
    assert r.status_code == 200 and r.json()["status"] == "connected"
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** the router with a `CreateConnectionRequest(BaseModel)` (`provider, engine, model, key, label: str | None = None`), `response_model=None` on each route, `add_connection` (catch `ValueError`→400), `list_connections_masked`, `delete_connection` (→404 when False), and `/test` (load conn→404 if missing, `await test_connection`, `set_status`, return `{ok, status, error}` with `time.strftime` for `tested_at`). Register in `app/main.py`.

- [ ] **Step 4: Run → PASS. Step 5: Gates + Commit** `feat(connections): REST API (presets, CRUD, test) + register router`.

---

### Task 5: RoleConnections on RepoProfile + workspace PATCH

**Files:**
- Modify: `backend/app/models/workspace.py` (add `RoleConnections` model + `role_connections` field on `RepoProfile`)
- Modify: `backend/app/models/requests.py:90` (`WorkspaceUpdateRequest` — add `roleConnections: dict[str, Any] | None = None`)
- Modify: `backend/app/api/v1/workspaces.py:76` (`update_workspace` — validate ids exist before `registry.update`)
- Test: `backend/tests/contract/test_workspace_roles.py`

`RoleConnections` (all optional; camelCase alias `roleConnections`):
```python
class RoleConnections(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    primary: str | None = None
    fallback: str | None = None
    planner: str | None = None
    final: str | None = None
    merge: str | None = None
    validators: list[str] = Field(default_factory=list)
    arbiters: list[str] = Field(default_factory=list)
```
On `RepoProfile`: `role_connections: RoleConnections | None = Field(None, alias="roleConnections")`.

- [ ] **Step 1: Write the failing test**
```python
# backend/tests/contract/test_workspace_roles.py
_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


def test_patch_rejects_unknown_connection_id(client, monkeypatch):
    import app.api.v1.workspaces as w
    import app.services.connections as cs
    monkeypatch.setattr(cs, "get_connection", lambda cid: None)
    monkeypatch.setattr(w.registry, "get", lambda i: object())  # ws exists
    r = client.patch("/api/v1/workspaces/ws1", headers=_CSRF,
                     json={"roleConnections": {"primary": "conn-nope"}})
    assert r.status_code == 400
    assert "conn-nope" in r.json()["error"]
```
(Adjust the existing-workspace mock to match `update_workspace`'s actual `registry` usage.)

- [ ] **Step 2: Run → FAIL. Step 3: Implement** — in `update_workspace`, when `body.roleConnections` set, collect every id (singles + list items), and for any id where `connections.get_connection(id) is None` return `error_response(f"unknown connection id: {id}", status=400)`; else include `roleConnections` in the patch dict passed to `registry.update`.
- [ ] **Step 4: Run → PASS. Step 5: Gates + Commit** `feat(connections): roleConnections on profile + validated workspace PATCH`.

---

### Task 6: Load-time role resolver (registry)

**Files:**
- Modify: `backend/app/core/workspaces.py` (`_load_profile` — call a new `_resolve_role_connections(ws)` before returning)
- Test: `backend/tests/unit/test_role_resolver.py`

Resolver: for each role in `roleConnections`, look up the connection; set `ws.agents.{role}` to `AgentRef(provider, model, engineProfile=conn.id)` and add `EngineProfile(name=conn.id, engine=conn.engine, env=conn.env)` to `ws.engine_profiles`. Dangling id → skip (keep existing agents ref) + append to `ws.role_warnings` (extra field; `RepoProfile` is `extra="allow"`). Then `ws.engine_profiles = list(<merged by name>)`.

- [ ] **Step 1: Write the failing test**
```python
# backend/tests/unit/test_role_resolver.py
from app.core.workspaces import _resolve_role_connections
from app.models.connections import Connection
from app.models.workspace import AgentRef, AgentsConfig, RepoProfile, RoleConnections
import app.core.workspaces as wsmod


def _ws(role_conns):
    base = AgentRef(provider="x", model="m", engine_profile=None)
    return RepoProfile(id="w", name="w", repoPath="/tmp/x",
                       agents=AgentsConfig(primary=base, fallback=base),
                       role_connections=role_conns)


def test_resolves_role_to_agentref_and_profile(monkeypatch):
    conn = Connection(id="conn-1", label="DS", provider="deepseek", engine="claude",
                      model="deepseek-chat", env={"ANTHROPIC_AUTH_TOKEN": "k"})
    monkeypatch.setattr(wsmod, "get_connection", lambda cid: conn if cid == "conn-1" else None)
    ws = _resolve_role_connections(_ws(RoleConnections(primary="conn-1", validators=["conn-1"])))
    assert ws.agents.primary.model == "deepseek-chat"
    assert ws.agents.primary.engine_profile == "conn-1"
    assert ws.agents.validators[0].engine_profile == "conn-1"
    assert any(p.name == "conn-1" and p.engine == "claude" for p in ws.engine_profiles)


def test_dangling_id_falls_back_and_warns(monkeypatch):
    monkeypatch.setattr(wsmod, "get_connection", lambda cid: None)
    ws = _resolve_role_connections(_ws(RoleConnections(primary="conn-gone")))
    assert ws.agents.primary.model == "m"  # unchanged
    assert "conn-gone" in getattr(ws, "role_warnings", [])
```

- [ ] **Step 2: Run → FAIL. Step 3: Implement** `_resolve_role_connections(ws)` per above (import `get_connection` at module top as `from app.services.connections import get_connection` so tests can monkeypatch `wsmod.get_connection`); call it at the end of `_load_profile` only when `ws.role_connections` is truthy.
- [ ] **Step 4: Run → PASS. Step 5: Gates + Commit** `feat(connections): resolve roleConnections → agents/profiles at registry load`.

---

### Task 7: Frontend types + API client

**Files:**
- Modify: `frontend/src/types/api.ts` (add `Connection`, `ConnectionPreset`, `RoleConnections`)
- Modify: `frontend/src/api/client.ts` (add 5 methods; allow `roleConnections` in the workspace-update payload)
- Test: `frontend/src/api/__tests__/connections.client.spec.ts`

Types:
```ts
export interface ConnectionPreset { provider: string; label: string; engines: string[]; models: string[]; baseUrl?: string; keyEnv?: string }
export interface Connection { id: string; label: string; provider: string; engine: string; model: string; env: Record<string,string>; status: 'untested'|'connected'|'failed'; lastTestedAt?: string|null; lastError?: string|null }
export interface RoleConnections { primary?: string|null; fallback?: string|null; planner?: string|null; final?: string|null; merge?: string|null; validators?: string[]; arbiters?: string[] }
```
Client methods: `getConnectionPresets()→{presets}`, `getConnections()→{connections}`, `createConnection(body)→{ok,connection}`, `deleteConnection(id)`, `testConnection(id)→{ok,status,error}`.

- [ ] **Step 1: Write a vitest** mocking `fetch`/`request` that asserts `createConnection` POSTs to `/api/v1/connections` with the body and `testConnection` POSTs to `/api/v1/connections/{id}/test`. **Step 2: FAIL. Step 3: Implement. Step 4: PASS. Step 5: Gates (`vue-tsc`,`vitest`) + Commit** `feat(connections): frontend types + api client`.

---

### Task 8: ConnectionsManager.vue (global section)

**Files:**
- Create: `frontend/src/components/ConnectionsManager.vue`
- Test: `frontend/src/components/__tests__/ConnectionsManager.spec.ts`

Behavior: on mount loads presets + connections. Renders each connection row with `data-test="conn-row"`, a status badge (`data-test="conn-status"` text `untested|connected|failed`), masked key, and a **«Проверить»** button (`data-test="conn-test"`) that calls `testConnection` and refreshes status, and a delete button (`data-test="conn-del"`). An **«Добавить»** form: provider `<select>` (`data-test="conn-provider"`) → engine `<select>` (`data-test="conn-engine"`, options = chosen preset's `engines`) → model `<select>` (`data-test="conn-model"`) → key `<input data-test="conn-key">` → submit (`data-test="conn-add"`) calls `createConnection`.

- [ ] **Step 1: Write the spec** — mock `@/api/client`; assert: (a) renders a connection from `getConnections`; (b) selecting provider=glm limits engine options to `['claude']`; (c) clicking «Проверить» calls `api.testConnection` and shows the returned status; (d) submitting the add form calls `api.createConnection` with `{provider,engine,model,key}`. **Step 2: FAIL. Step 3: Implement** (follow existing component style in `src/components`; scoped styles; status badge colors green/red/grey). **Step 4: PASS. Step 5: Gates + Commit** `feat(connections): ConnectionsManager.vue + spec`.

---

### Task 9: AgentRolesPicker.vue (per-workspace section)

**Files:**
- Create: `frontend/src/components/AgentRolesPicker.vue`
- Test: `frontend/src/components/__tests__/AgentRolesPicker.spec.ts`

Props: `:connections` (Connection[]), `:modelValue` (RoleConnections). Renders a `<select data-test="role-<name>">` per single role (primary/fallback/planner/final/merge) and N rows for validators(×5)/arbiters(×2) (`data-test="role-validators-<i>"`). Options = **only** connections with `status==='connected'` (others rendered `disabled` with " (не проверено)"/" (ошибка)"). Emits `update:modelValue` with the new `RoleConnections`. A **«Применить ко всем»** button (`data-test="roles-apply-all"`) sets every role to the selected connection. Includes a `data-test="role-warning"` banner when a prop `:warnings` lists dangling ids.

- [ ] **Step 1: Write the spec** — assert: (a) only connected connections appear as enabled options; (b) a failed connection is rendered disabled; (c) changing `role-primary` emits `update:modelValue` with `primary` set; (d) «Применить ко всем» sets all single roles + fills the lists. **Step 2: FAIL. Step 3: Implement. Step 4: PASS. Step 5: Gates + Commit** `feat(connections): AgentRolesPicker.vue + spec`.

---

### Task 10: SettingsView integration + migration helper

**Files:**
- Modify: `frontend/src/views/SettingsView.vue` (remove the raw engine/`engineEnv`/`engineProfiles` + `AgentRefEditor`/`AgentListEditor` blocks; mount `<ConnectionsManager/>` + `<AgentRolesPicker v-model="roleConnections" :connections :warnings/>`; save `roleConnections` via the existing workspace-update call)
- Modify (optional, keep if used elsewhere): leave `AgentRefEditor.vue`/`AgentListEditor.vue` files in place but unreferenced if other views import them; otherwise delete.
- Test: extend `frontend/src/components/__tests__/` settings spec or add `SettingsView.connections.spec.ts`

Migration helper (in `ConnectionsManager.vue`): an **«Импортировать текущий deepseek-профиль»** button (`data-test="conn-import"`) shown when the active workspace has an `engineProfiles` entry named `deepseek`; clicking it calls `createConnection` with that profile's provider/model + the key from its env (read from the workspace profile already in the settings draft), giving a one-click adoption path.

- [ ] **Step 1: Write a spec** asserting SettingsView renders `ConnectionsManager` + `AgentRolesPicker` and that saving calls the workspace update with `roleConnections`. **Step 2: FAIL. Step 3: Implement** the wiring (load connections into SettingsView state, bind `roleConnections` from the workspace draft, persist on save). **Step 4: PASS. Step 5: Full gates (backend + frontend) + Commit** `feat(connections): two-section Settings replaces raw editor + import helper`.

---

### Final: end-to-end verification (after all tasks)

- [ ] Full gates green (backend `pytest`/`ruff`/`mypy --strict`; frontend `vitest`/`vue-tsc`/`build`).
- [ ] **Live (verify skill):** restart local backend on the branch; in the UI add a DeepSeek/claude connection with the existing key → «Проверить» → `connected` (real `HEPHAESTUS_CONN_OK`); add a GLM/z.ai connection with the provided z.ai key → «Проверить» → `connected`; assign GLM to a role and confirm the resolved profile drives `claude --model glm-4.6`. Capture evidence.
- [ ] Finish branch (merge to master) per superpowers:finishing-a-development-branch.
