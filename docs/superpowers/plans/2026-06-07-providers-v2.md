# Providers v2 + CLI Detection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Connect any popular model by subscription/OAuth (Claude/Codex/opencode logins) or API key, gated by which CLIs are installed — extending the existing connections feature.

**Architecture:** Add `authMethod` to `Connection`; replace the flat `PRESETS` with a `PROVIDER_CATALOG` of `(engine, authMethod)` combos; `build_env` becomes catalog-driven (subscription → no secret). Add `cli_detect` + `GET /api/v1/clis`. Add a `codex` engine to the runner. Rework `ConnectionsManager.vue` into an engines panel + a catalog/auth-aware add form. The load-time role resolver, AgentRolesPicker, FSM and runner dispatch are otherwise unchanged.

**Tech Stack:** FastAPI + Pydantic v2 (camelCase via `Field(alias=...)`, `populate_by_name=True`), Vue 3 + Pinia + TS, pytest, vitest. Cross-platform (Windows): argv lists, `shutil.which`, never-crash.

**Gates (after every task that touches them):** backend `backend/.venv/Scripts/python.exe -m pytest -q` + `ruff check app tests` + `mypy --strict app/`; frontend `npx vitest run` + `npx vue-tsc --noEmit` + `npm run build`.

**Grounded CLI facts:** `claude` 2.1.140 (`claude -p`, OAuth via `claude` `/login`), `opencode` 1.16.2 (`opencode auth list|login|logout`, `opencode run --model provider/model`), `codex` 0.125.0 (`codex exec [OPTS] [PROMPT]`, prompt via stdin, `-m/--model`, `codex login`).

---

### Task 1: Connection.authMethod + PROVIDER_CATALOG + catalog-driven build_env

**Files:** Modify `backend/app/models/connections.py`, `backend/app/services/connections.py`; Test `backend/tests/unit/test_connections_model.py` (extend), `backend/tests/unit/test_connections_store.py` (extend).

- [ ] **Step 1: failing tests** (append to `test_connections_model.py`)
```python
from app.models.connections import PROVIDER_CATALOG, build_env, find_combo


def test_catalog_has_expected_providers():
    provs = {e.provider for e in PROVIDER_CATALOG}
    assert {"anthropic", "glm", "deepseek", "openai", "gemini", "openrouter", "copilot"} <= provs


def test_find_combo_and_bad_combo():
    assert find_combo("anthropic", "claude", "subscription") is not None
    assert find_combo("glm", "opencode", "api_key") is None  # glm is claude-only


def test_build_env_subscription_stores_no_secret():
    env = build_env("anthropic", "claude", "subscription", "claude-opus-4-5", key="")
    assert env == {"ANTHROPIC_MODEL": "claude-opus-4-5"}           # no token at all
    assert build_env("openai", "codex", "subscription", "gpt-5-codex", key="") == {}
    assert build_env("copilot", "opencode", "subscription", "gpt-4o", key="") == {}


def test_build_env_api_key_per_engine():
    assert build_env("deepseek", "claude", "api_key", "deepseek-chat", "sk-K") == {
        "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
        "ANTHROPIC_AUTH_TOKEN": "sk-K", "ANTHROPIC_MODEL": "deepseek-chat"}
    assert build_env("openai", "codex", "api_key", "gpt-5-codex", "sk-K") == {"OPENAI_API_KEY": "sk-K"}
    assert build_env("openrouter", "opencode", "api_key", "x/y", "sk-K") == {"OPENROUTER_API_KEY": "sk-K"}


def test_build_env_rejects_bad_combo():
    import pytest
    with pytest.raises(ValueError):
        build_env("glm", "opencode", "api_key", "glm-4.6", "k")
```

- [ ] **Step 2: run → FAIL.**
- [ ] **Step 3: implement** (`connections.py` — add models + catalog, rewrite `build_env`, keep `Connection`/`mask_env`; add `auth_method` field to `Connection`)
```python
class Combo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    engine: str                                  # claude | opencode | codex
    auth_method: str = Field(alias="authMethod") # subscription | api_key
    models: list[str]
    base_url: str | None = Field(None, alias="baseUrl")
    key_env: str | None = Field(None, alias="keyEnv")
    login_cmd: str | None = Field(None, alias="loginCmd")


class ProviderCatalogEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    provider: str
    label: str
    blurb: str
    combos: list[Combo]


PROVIDER_CATALOG: list[ProviderCatalogEntry] = [
    ProviderCatalogEntry(provider="anthropic", label="Claude (Anthropic)",
        blurb="Подписка Claude Max/Pro через вход в `claude` (без ключа). Либо ANTHROPIC API-ключ.",
        combos=[
            Combo(engine="claude", authMethod="subscription",
                  models=["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-3-5"],
                  loginCmd="claude   (затем /login)"),
            Combo(engine="claude", authMethod="api_key", keyEnv="ANTHROPIC_API_KEY",
                  models=["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-3-5"]),
            Combo(engine="opencode", authMethod="api_key", keyEnv="ANTHROPIC_API_KEY",
                  models=["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-3-5"]),
        ]),
    ProviderCatalogEntry(provider="glm", label="GLM (z.ai coding plan)",
        blurb="z.ai coding plan — токен подписки (ANTHROPIC-совместимый эндпоинт).",
        combos=[Combo(engine="claude", authMethod="api_key", keyEnv="ANTHROPIC_AUTH_TOKEN",
                      base_url="https://api.z.ai/api/anthropic", models=["glm-4.6", "glm-4.5"])]),
    ProviderCatalogEntry(provider="deepseek", label="DeepSeek",
        blurb="DeepSeek API-ключ (ANTHROPIC-совместимый эндпоинт), либо через opencode.",
        combos=[
            Combo(engine="claude", authMethod="api_key", keyEnv="ANTHROPIC_AUTH_TOKEN",
                  base_url="https://api.deepseek.com/anthropic", models=["deepseek-chat", "deepseek-reasoner"]),
            Combo(engine="opencode", authMethod="api_key", keyEnv="DEEPSEEK_API_KEY",
                  models=["deepseek-chat", "deepseek-reasoner"]),
        ]),
    ProviderCatalogEntry(provider="openai", label="OpenAI / GPT",
        blurb="Подписка ChatGPT через вход в `codex`, либо OpenAI API-ключ (codex/opencode).",
        combos=[
            Combo(engine="codex", authMethod="subscription",
                  models=["gpt-5-codex", "o4-mini", "gpt-4o"], loginCmd="codex login"),
            Combo(engine="codex", authMethod="api_key", keyEnv="OPENAI_API_KEY",
                  models=["gpt-5-codex", "o4-mini", "gpt-4o"]),
            Combo(engine="opencode", authMethod="api_key", keyEnv="OPENAI_API_KEY",
                  models=["gpt-4o", "o4-mini"]),
        ]),
    ProviderCatalogEntry(provider="gemini", label="Google Gemini",
        blurb="Gemini через opencode — вход `opencode auth login` или Google API-ключ.",
        combos=[
            Combo(engine="opencode", authMethod="subscription",
                  models=["gemini-2.5-pro", "gemini-2.5-flash"], loginCmd="opencode auth login"),
            Combo(engine="opencode", authMethod="api_key", keyEnv="GEMINI_API_KEY",
                  models=["gemini-2.5-pro", "gemini-2.5-flash"]),
        ]),
    ProviderCatalogEntry(provider="openrouter", label="OpenRouter (шлюз)",
        blurb="OpenRouter API-ключ — доступ к множеству моделей; модель указывается как `vendor/model`.",
        combos=[Combo(engine="opencode", authMethod="api_key", keyEnv="OPENROUTER_API_KEY",
                      models=["anthropic/claude-sonnet-4-5", "openai/gpt-4o", "google/gemini-2.5-pro"])]),
    ProviderCatalogEntry(provider="copilot", label="GitHub Copilot",
        blurb="Подписка GitHub Copilot через `opencode auth login` (OAuth).",
        combos=[Combo(engine="opencode", authMethod="subscription",
                      models=["gpt-4o", "claude-sonnet-4-5"], loginCmd="opencode auth login")]),
]


def find_combo(provider: str, engine: str, auth_method: str) -> Combo | None:
    for e in PROVIDER_CATALOG:
        if e.provider == provider:
            for c in e.combos:
                if c.engine == engine and c.auth_method == auth_method:
                    return c
    return None


def build_env(provider: str, engine: str, auth_method: str, model: str, key: str) -> dict[str, str]:
    """Subprocess env for a connection. Subscription → no secret. Raises ValueError on bad combo."""
    combo = find_combo(provider, engine, auth_method)
    if combo is None:
        raise ValueError(f"unsupported combo: {provider}/{engine}/{auth_method}")
    if auth_method == "subscription":
        return {"ANTHROPIC_MODEL": model} if engine == "claude" else {}
    # api_key
    if engine == "claude":
        return {"ANTHROPIC_BASE_URL": combo.base_url or "",
                "ANTHROPIC_AUTH_TOKEN": key, "ANTHROPIC_MODEL": model}
    if engine == "codex":
        return {"OPENAI_API_KEY": key}
    return {combo.key_env or "API_KEY": key}            # opencode
```
Add `auth_method: str = Field("api_key", alias="authMethod")` to `Connection` (after `model`). Keep `mask_env`. Remove the old `ConnectionPreset`/`PRESETS`/`_PRESET_BY` (replaced; grep for importers — only `api/v1/connections.py` and tests, fixed in Task 4).

- [ ] **Step 4: update `services/connections.py` `add_connection`** — signature `add_connection(*, provider, engine, auth_method, model, key="", label=None)`; `env = build_env(provider, engine, auth_method, model, key)`; set `Connection(..., auth_method=auth_method, ...)`. Update `test_connections_store.py` calls to pass `auth_method="api_key"`.
- [ ] **Step 4b: fix the now-broken existing tests** — the old `test_build_env_*` tests in `test_connections_model.py` use the 4-arg `build_env(provider,engine,model,key)` and the old `PRESETS`/`ConnectionPreset` import; replace them with the new-signature assertions from Step 1 (delete the obsolete ones — DeepSeek/GLM are still covered by the new `test_build_env_api_key_per_engine`). Run the full unit suite to confirm none reference the removed `PRESETS`/`ConnectionPreset`/`mask_env`-unchanged symbols.
- [ ] **Step 5: run → PASS; gates; commit** `feat(providers): authMethod + PROVIDER_CATALOG + catalog-driven build_env`.

---

### Task 2: CLI detection service + endpoint

**Files:** Create `backend/app/services/cli_detect.py`, `backend/app/api/v1/clis.py`; Modify `backend/app/main.py` (register router); Test `backend/tests/unit/test_cli_detect.py`, `backend/tests/contract/test_clis_api.py`.

- [ ] **Step 1: failing test** (`test_cli_detect.py`)
```python
import app.services.cli_detect as cd


def test_detect_marks_installed_and_version(monkeypatch):
    monkeypatch.setattr(cd.shutil, "which", lambda name: f"/usr/bin/{name}" if name in ("claude", "codex") else None)
    monkeypatch.setattr(cd, "_version", lambda exe: "1.2.3")
    monkeypatch.setattr(cd, "_opencode_providers", lambda: [])
    out = cd.detect_clis()
    assert out["claude"]["installed"] is True and out["claude"]["version"] == "1.2.3"
    assert out["opencode"]["installed"] is False
    assert out["codex"]["installed"] is True


def test_opencode_auth_parsing(monkeypatch):
    sample = "Providers\n  anthropic  logged in\n  openai     api key\n"
    monkeypatch.setattr(cd, "_run", lambda *a, **k: sample)
    assert set(cd._parse_opencode_auth(sample)) >= {"anthropic", "openai"}
```

- [ ] **Step 2: FAIL. Step 3: implement** `cli_detect.py`
```python
"""Detect which agent CLIs are installed/logged in → drives capability gating."""
from __future__ import annotations
import shutil, subprocess
from typing import Any

_CLIS = ("claude", "opencode", "codex")


def _run(argv: list[str], timeout: int = 8) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _version(exe: str) -> str | None:
    out = _run([exe, "--version"]).strip()
    return out.splitlines()[0] if out else None


def _parse_opencode_auth(text: str) -> list[str]:
    provs: list[str] = []
    for ln in text.splitlines():
        s = ln.strip()
        if s and " " in s and not s.lower().startswith("provider"):
            provs.append(s.split()[0])
    return provs


def _opencode_providers() -> list[str]:
    return _parse_opencode_auth(_run(["opencode", "auth", "list"]))


def detect_clis() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name in _CLIS:
        exe = shutil.which(name)
        info: dict[str, Any] = {"installed": exe is not None, "version": None, "auth": {}}
        if exe:
            info["version"] = _version(exe)
            if name == "opencode":
                info["auth"] = {"providers": _opencode_providers()}
            else:
                info["auth"] = {"unknown": True}  # no cheap whoami → the connection test is the truth
        out[name] = info
    return out
```
`clis.py`: `GET /api/v1/clis` → `{"ok": True, "clis": detect_clis()}` (`response_model=None`). Register in `main.py` next to the connections router.

- [ ] **Step 4: contract test** (`test_clis_api.py`): monkeypatch `app.api.v1.clis.detect_clis` → fixed map; assert 200 + keys `claude/opencode/codex`.
- [ ] **Step 5: PASS; gates; commit** `feat(providers): CLI detection service + /api/v1/clis`.

---

### Task 3: Codex engine in the runner

**Files:** Modify `backend/app/services/opencode_runner.py`; Test `backend/tests/unit/test_codex_engine.py`.

- [ ] **Step 1: failing test**
```python
from app.models.workspace import AgentRef
from app.services.opencode_runner import AgentRunner


def test_codex_cmd_and_stdin():
    r = AgentRunner(None, engine="codex")  # type: ignore[arg-type]
    cmd = r._build_cmd_codex(AgentRef(provider="openai", model="gpt-5-codex"))
    assert cmd == ["codex", "exec", "--model", "gpt-5-codex"]
    assert r._label(AgentRef(provider="openai", model="gpt-5-codex"), True, "codex") == "codex:gpt-5-codex"
```

- [ ] **Step 2: FAIL. Step 3: implement** — in `opencode_runner.py`:
  - add `_build_cmd_codex(self, ref) -> list[str]: return ["codex", "exec", "--model", ref.model]` (model required; prompt fed via stdin like claude).
  - in `_label`: `if engine == "codex": return f"codex:{ref.model or 'default'}"`.
  - in `run()`, extend the engine branch: `if engine in ("claude", "codex"):` build the respective cmd and set `stdin_data = prompt_text.encode(...)` (both feed the prompt via stdin). Keep the claude `ANTHROPIC_API_KEY→ANTHROPIC_AUTH_TOKEN` routing **claude-only**. For codex the env (`OPENAI_API_KEY` for api_key, nothing for subscription) passes through `sub_env` as-is.
  - **codex output format:** run `codex exec --help` to check for a JSON/stream flag; if a stable machine format exists, add it to the cmd and parse like the claude JSONL; otherwise leave plain text — `extract_assistant_text()` (app/core/events.py) already passes raw text through, and `connection_test` only needs exit 0 + non-empty stdout. Note the decision in the commit body.

- [ ] **Step 4: PASS; gates; commit** `feat(providers): codex engine (codex exec --model, prompt via stdin)`.

---

### Task 4: API — catalog endpoint + authMethod on create + subscription login hint

**Files:** Modify `backend/app/api/v1/connections.py`, `backend/app/services/connection_test.py`; Test `backend/tests/contract/test_connections_api.py` (update), `backend/tests/unit/test_connection_test.py` (extend).

- [ ] **Step 1: update/failing tests**
```python
# test_connections_api.py — replace the old presets test
def test_catalog(client):
    r = client.get("/api/v1/connection-presets")
    assert r.status_code == 200
    provs = {e["provider"] for e in r.json()["catalog"]}
    assert {"anthropic", "openai", "glm", "copilot"} <= provs


def test_create_subscription_no_key(client, tmp_path, monkeypatch):
    import app.services.connections as cs
    monkeypatch.setattr(cs, "_STORE", tmp_path / "connections.json")
    r = client.post("/api/v1/connections", headers=_CSRF, json={
        "provider": "anthropic", "engine": "claude", "authMethod": "subscription",
        "model": "claude-opus-4-5"})
    assert r.status_code == 200
    c = r.json()["connection"]
    assert c["authMethod"] == "subscription"
    assert "ANTHROPIC_AUTH_TOKEN" not in c["env"]  # no secret for subscription
```
```python
# test_connection_test.py — subscription failure surfaces the login command
def test_subscription_failure_shows_login(monkeypatch):
    import app.services.connection_test as ct
    from app.models.connections import Connection
    monkeypatch.setattr(ct, "_make_runner", lambda conn: _FakeRunner(1, ""))  # not logged in
    conn = Connection(id="c", label="Claude", provider="anthropic", engine="claude",
                      model="claude-opus-4-5", auth_method="subscription", env={"ANTHROPIC_MODEL": "claude-opus-4-5"})
    status, err = asyncio.run(ct.test_connection(conn))
    assert status == "failed" and "claude" in err.lower()  # login hint mentions the cli
```

- [ ] **Step 2: FAIL. Step 3: implement**
  - `connections.py` (api): `CreateConnectionRequest` gains `auth_method: str = Field("api_key", alias="authMethod")` and `key: str = ""`. `create_connection` passes `auth_method=body.auth_method`. Replace `get_presets` → return `{"ok": True, "catalog": [e.model_dump(by_alias=True) for e in PROVIDER_CATALOG]}` (import `PROVIDER_CATALOG`); keep the route path `/api/v1/connection-presets`.
  - `connection_test.py`: when `status == "failed"` and `conn.auth_method == "subscription"`, append the login command from `find_combo(conn.provider, conn.engine, "subscription").login_cmd` (fallback per engine: claude→"claude (/login)", codex→"codex login", opencode→"opencode auth login") to the error string.
  - `services/connections.py` `add_connection` already takes `auth_method` (Task 1); ensure the masked/list responses include `authMethod`.
- [ ] **Step 4: PASS; gates; commit** `feat(providers): catalog endpoint + authMethod create + subscription login hint`.

---

### Task 5: Frontend types + API client

**Files:** Modify `frontend/src/types/api.ts`, `frontend/src/api/client.ts`; Test `frontend/src/api/__tests__/connections.client.spec.ts` (extend).

- [ ] **Step 1–5 (TDD):** add types `Combo {engine; authMethod; models; baseUrl?; keyEnv?; loginCmd?}`, `ProviderCatalogEntry {provider; label; blurb; combos: Combo[]}`, `CliInfo {installed; version?: string|null; auth: Record<string,unknown>}`; extend `Connection` with `authMethod: 'subscription'|'api_key'`. Client: `getClis()→{ok; clis: Record<string,CliInfo>}`; change `getConnectionPresets()` return to `{ok; catalog: ProviderCatalogEntry[]}`; `createConnection(body)` body adds `authMethod` + optional `key`. Spec asserts `getClis` GETs `/api/v1/clis` and `createConnection` POSTs `authMethod`. Gates + commit `feat(providers): frontend types + clis client`.

---

### Task 6: ConnectionsManager v2 (engines panel + catalog/auth form)

**Files:** Modify `frontend/src/components/ConnectionsManager.vue`; Test `frontend/src/components/__tests__/ConnectionsManager.spec.ts` (rewrite).

- [ ] **Behaviour:** on mount load `getClis()` + `getConnectionPresets()` (catalog) + `getConnections()`.
  - **Engines panel** (`data-test="engines-panel"`): a row per `claude/opencode/codex` (`data-test="engine-<name>"`) showing installed ✓/✗ + version; not-installed greyed with "установите `<name>`".
  - **Add form:** provider `<select data-test="conn-provider">` (catalog) → shows the entry `blurb` (`data-test="conn-blurb"`) → engine `<select data-test="conn-engine">` whose options are the provider's combo engines **filtered to installed CLIs** → auth `<select data-test="conn-auth">` (the chosen engine's available `authMethod`s) → model `<select data-test="conn-model">` (chosen combo's `models`) → **if `api_key`**: key `<input data-test="conn-key" type=password>`; **if `subscription`**: no key field, show the combo `loginCmd` (`data-test="conn-login-cmd"`) → submit (`data-test="conn-add"`) calls `createConnection({provider, engine, authMethod, model, key?})`.
  - Connection rows show an auth badge (`data-test="conn-auth-badge"` = "подписка"/"ключ"); subscription rows show "подписка" instead of a masked key. «Проверить»/delete unchanged; keep emitting `changed` (incl. on test catch — preserve the existing fix).
- [ ] **Spec asserts:** engines panel renders installed/missing from `getClis`; choosing provider=glm limits engine options to those installed AND in the catalog; selecting `authMethod=subscription` hides the key input and shows `loginCmd`; selecting `api_key` shows the key input; submit sends the right payload incl `authMethod`; «Проверить» emits `changed`. Gates (vitest+vue-tsc+build) + commit `feat(providers): ConnectionsManager v2 — engines panel + catalog/auth form`.

---

### Final: end-to-end verification

- [ ] Full gates green (backend + frontend).
- [ ] **Live (verify skill):** `GET /api/v1/clis` detects all three (claude/opencode/codex installed). Create **Claude subscription** connection (no key) → «Проверить» → `connected` via the machine's `claude` login. Create **GPT via codex subscription** → `connected` if `codex login` done, else `failed` with `codex login` shown. Capture evidence.
- [ ] Finish branch per superpowers:finishing-a-development-branch (merge to master).
- [ ] Migration note: existing connections (no `authMethod`) default to `api_key` — keep working; the resolver/AgentRolesPicker are unchanged.
```
