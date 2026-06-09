# Providers v2 + CLI Detection — Design

**Goal:** Let a user connect *all* the popular coding models without touching env files — by
**subscription/OAuth** where possible (Claude via `claude` login, GPT via Codex/ChatGPT login,
Copilot/Gemini via opencode), with **API keys** as the alternative. Detect which CLIs
(`claude` / `opencode` / `codex`) are actually installed + logged in, and only offer providers
whose engine is available. Sub-project #1 of the HEPHAESTUS v2 redesign (see
[[hephaestus-v2-redesign]]).

**Status:** approved (brainstorming 2026-06-07). Decisions: **3 engines** (claude + opencode +
**codex**, codex added now); **detect + instruct + re-check** for OAuth login (HEPHAESTUS never
drives the browser OAuth itself); **full catalog** (Claude-subscription, GLM/DeepSeek,
GPT/Gemini via opencode/codex, OpenRouter/Copilot). Extends the existing connections feature
(connections.json + presets + real-CLI test) — not a rewrite.

**Grounded CLI facts (probed 2026-06-07):** `claude` 2.1.140, `opencode` 1.16.2
(`auth list|login|logout`), `codex` 0.125.0 (`codex exec [OPTS] [PROMPT]`, prompt via stdin,
`-m/--model`, `codex login`). All three installed on the dev box.

---

## 1. Data model

### Connection (extend `app/models/connections.py`)
Add `auth_method: "subscription" | "api_key"` (alias `authMethod`, default `"api_key"`).
- **api_key**: `env` holds the endpoint + key (current behaviour), key masked in API responses.
- **subscription**: HEPHAESTUS stores **no secret**. `env` holds only non-secret hints (e.g.
  `ANTHROPIC_MODEL`); auth comes from the CLI's own login. `status`/`connected` is decided by
  the real-CLI test (which transitively proves the login).

`Connection.requires_login: bool` (computed/serialized): true when `auth_method=="subscription"`.

### Provider catalog (`PROVIDER_CATALOG` in `app/models/connections.py`, static)
Each catalog entry declares the provider and its valid `(engine, auth_method)` combinations,
each combo carrying how to build env, the model list, and (for subscription) the login command
+ a one-line human explanation. Shape:
```python
ProviderCatalogEntry(
  provider="anthropic", label="Claude (Anthropic)",
  blurb="Подписка Claude Max/Pro через `claude login`, без ключа. Либо ANTHROPIC API-ключ.",
  combos=[
    Combo(engine="claude",   auth_method="subscription", login_cmd="claude  (then /login)",
          models=["claude-opus-4-5","claude-sonnet-4-5","claude-haiku-3-5"]),
    Combo(engine="claude",   auth_method="api_key", key_env="ANTHROPIC_API_KEY",
          base_url=None, models=[…]),
    Combo(engine="opencode", auth_method="api_key", key_env="ANTHROPIC_API_KEY", models=[…]),
  ])
```
Initial catalog (per approved scope):

| provider | combos (engine · auth) | models |
|---|---|---|
| anthropic (Claude) | claude·subscription, claude·api_key, opencode·api_key | opus/sonnet/haiku |
| glm (z.ai) | claude·api_key (coding-plan token) | glm-4.6/4.5 |
| deepseek | claude·api_key, opencode·api_key | deepseek-chat/reasoner |
| openai (GPT) | codex·subscription, codex·api_key, opencode·api_key | gpt-5-codex/o4-mini/gpt-4o |
| gemini | opencode·subscription, opencode·api_key | gemini-2.5-pro/flash |
| openrouter | opencode·api_key | (gateway — free-form model id) |
| copilot | opencode·subscription | gpt/claude via copilot |

`build_env(provider, engine, auth_method, model, key)` returns the subprocess env:
- claude·subscription → `{ANTHROPIC_MODEL: model}` only (no token → uses `claude login`).
- claude·api_key → `{ANTHROPIC_BASE_URL?, ANTHROPIC_AUTH_TOKEN: key, ANTHROPIC_MODEL: model}`.
- opencode·* → `{}` for subscription (uses `opencode auth`), or `{<KEY_ENV>: key}` for api_key;
  model passed as `provider/model`.
- codex·subscription → `{}` (uses `codex login`); codex·api_key → `{OPENAI_API_KEY: key}`.

Unsupported `(provider, engine, auth_method)` combos raise `ValueError` (→ 400).

## 2. CLI detection (`app/services/cli_detect.py` + `GET /api/v1/clis`)

```python
detect_clis() -> { "claude": CliInfo, "opencode": CliInfo, "codex": CliInfo }
CliInfo(installed: bool, version: str | None, auth: AuthInfo)
```
- `installed` via `shutil.which`; `version` via `<cli> --version` (short timeout, never raises).
- `auth`:
  - opencode → parse `opencode auth list` into the set of logged-in providers.
  - claude/codex → no cheap `whoami`; report `auth.unknown=True` and treat the **connection
    test** as the source of truth for login (a green test ⇒ logged in). The capability screen
    shows "установлен, статус логина проверяется тестом".
- Endpoint returns the map; the frontend uses it to (a) show the engines panel and (b) filter
  which provider combos are offerable (engine must be installed).

## 3. Codex engine (`app/services/opencode_runner.py`, `engine="codex"`)

`_build_cmd_codex(ref)` → `["codex", "exec", "--model", ref.model]`; prompt fed via **stdin**
(like the claude engine). Output: probe `codex exec` for a JSON/stream flag during impl; if a
stable machine format exists use it, else capture raw text and wrap it as a single text event
(degrade gracefully — the funnel/parsers already tolerate non-JSONL via
`extract_assistant_text`). `_resolve_engine` already dispatches by name; add the `codex` branch
in `run()` alongside `claude`/opencode.

## 4. Login UX — detect + instruct + re-check

For a **subscription** connection, "Подключить" does NOT ask for a key. Flow:
1. Create the connection (`auth_method=subscription`, status `untested`).
2. "Проверить" runs the real-CLI test. Logged in → `connected`. Not logged in → `failed` with
   `last_error` = the exact login command for that engine (`claude` → run `claude` then `/login`;
   opencode → `opencode auth login`; codex → `codex login`) shown verbatim in the UI.
3. The user runs that command in their terminal, returns, clicks "Проверить снова".

HEPHAESTUS never spawns the interactive OAuth/browser flow itself (robustness).

## 5. Connection test (`app/services/connection_test.py`)

Already runs the engine on a 1-token prompt with the connection's env. Extend for codex
(`engine=="codex"`). For subscription connections (no key) the same test verifies login. On
non-zero with output mentioning auth, surface a friendly `failed` + the login command for that
engine. Never 500.

## 6. Backend endpoints

- `GET /api/v1/connection-presets` → **replace** the flat preset list with the
  `PROVIDER_CATALOG` (provider → combos → models + blurbs).
- `GET /api/v1/clis` → CLI detection map (§2).
- `POST /api/v1/connections` body gains `authMethod`; for `subscription`, `key` is omitted; env
  built per §1.
- `GET/DELETE/POST …/test` unchanged in shape (test now covers codex + subscription).

## 7. Frontend (`ConnectionsManager.vue` v2 + types + client)

- **Engines panel:** a card per CLI (claude/opencode/codex) showing installed ✓/✗ + version,
  from `GET /api/v1/clis`. Not-installed → greyed with "установите `codex` / `opencode`".
- **Add-connection form (with explanations):** provider `<select>` (catalog) → shows the
  provider `blurb` → engine `<select>` filtered to **installed** CLIs that the provider supports
  → auth `<select>` (subscription / api_key, per combo) → model `<select>` →
  if api_key: key input; if subscription: a login-status line + the exact "Войти" command (no
  key field) → "Проверить".
- Connection rows show provider/engine/model/auth-badge + status; subscription rows show
  "подписка" instead of a masked key.
- Types/client: `authMethod`, `requiresLogin`, `ProviderCatalogEntry`, `Combo`, `CliInfo`,
  `getClis()`.

## 8. Testing

- **Backend unit:** catalog shape + every `(provider,engine,auth)` `build_env` (incl.
  subscription → no secret); `cli_detect` with `shutil.which`/version mocked (installed,
  missing, version-fails); opencode `auth list` parsing; codex `_build_cmd`; bad-combo → 400.
- **Test endpoint:** mocked runner — codex success → connected; subscription not-logged-in
  (non-zero) → failed + login-command in error.
- **Frontend unit:** engines panel renders from `/clis`; engine options filtered to installed
  CLIs; subscription path hides the key field + shows the login command; api_key path requires a
  key; bad combo disabled.
- **Live (verify skill):** real `GET /api/v1/clis` (all three detected); connect **Claude via
  subscription** (no key) → "Проверить" → connected via the machine's `claude login`; connect
  **GPT via codex** → connected if `codex login` done, else failed with `codex login` shown.

## 9. Scope / out of scope

In: the connection data model, catalog, CLI detection, codex engine, login UX, the test, and
the ConnectionsManager rework. **Out** (later sub-projects): the first-launch onboarding wizard
and tab restructure (#2), removing autofix/changelog (#2), agent-role UX changes. The existing
`AgentRolesPicker` keeps working (connections still resolve to roles unchanged).

## 10. Risks

- **codex headless output format** unknown — mitigated by the text-degrade path (§3) +
  verifying `codex exec` flags during impl.
- **claude/codex login detection** has no cheap probe — mitigated by using the connection test
  as the source of truth (§2).
- Catalog model ids drift over time — kept in one static `PROVIDER_CATALOG` table, easy to edit;
  OpenRouter allows a free-form model id to avoid churn.
