# Agent Settings → Presets & Global Connections — Design

**Goal:** Replace HEPHAESTUS's low-level agent settings (raw provider/model/engineProfile editors)
with a two-stage, preset-driven flow: (1) globally **connect** the models you want — pick a
preset, choose the connection engine, enter a key, and **test** it with a real CLI call; then
(2) per workspace, **assign** a successfully-connected model to each agent role. Add **GLM via
the z.ai coding plan** as a connectable model, and let **DeepSeek** connect via either
**opencode** or **claude**.

**Status:** approved (brainstorming 2026-06-07). Decisions: connections are **global**;
providers shipped now are **DeepSeek + GLM**; the old raw editor is **replaced**; connection
test is a **real CLI call**; mapping uses **`role→connectionId`, resolved at load (Approach B)**.

---

## 1. Concepts

- **Connection** — a globally-stored, reusable model endpoint: a provider + an engine
  (connection method) + a model + the env needed to reach it (endpoint + key), plus a tested
  status. Connect once, use in any workspace.
- **Preset** — a static catalog entry that pre-fills a connection form (endpoint, model list,
  allowed engines, which env var carries the key). The user only adds the key.
- **Role assignment** — per workspace, each agent role (`primary`, `fallback`, `planner`,
  `final`, `merge`, and the `validators[]` / `arbiters[]` lists) points at a connection **id**.

## 2. Data model

### Global `state/connections.json` (next to `state/config.json`)
```jsonc
{
  "connections": [
    {
      "id": "conn-ab12cd",            // stable, generated
      "label": "DeepSeek (Claude CLI)",
      "provider": "deepseek",          // deepseek | glm
      "engine": "claude",              // claude | opencode
      "model": "deepseek-chat",
      "env": {                         // endpoint + key, engine-specific (see §3)
        "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
        "ANTHROPIC_AUTH_TOKEN": "sk-…",
        "ANTHROPIC_MODEL": "deepseek-chat"
      },
      "status": "connected",           // untested | connected | failed
      "lastTestedAt": "2026-06-07T…Z",
      "lastError": null
    }
  ]
}
```
Keys are stored plaintext (same as today's `profile.json`) but **masked** in every API
response (`sk-…1207` → `sk-…***`). The raw `env` is only ever read server-side.

### Workspace `profile.json` — new field
```jsonc
"roleConnections": {
  "primary": "conn-ab12cd",
  "fallback": "conn-ab12cd",
  "planner": "conn-ab12cd",
  "final": "conn-ab12cd",
  "merge": "conn-ab12cd",
  "validators": ["conn-ab12cd", "conn-ab12cd", …],
  "arbiters": ["conn-ab12cd", …]
}
```
Optional. When absent, the workspace keeps using its existing `agents` / `engineProfiles`
(back-compat). The existing `agents` block stays in the schema as the resolved/fallback target.

## 3. Preset catalog (static, in code, served read-only)

`GET /api/v1/connection-presets`:
- **DeepSeek** — `engines: [claude, opencode]`, `models: [deepseek-chat, deepseek-reasoner]`.
  - `claude`: `env = { ANTHROPIC_BASE_URL: https://api.deepseek.com/anthropic,
    ANTHROPIC_AUTH_TOKEN: <key>, ANTHROPIC_MODEL: <model> }`; AgentRef `provider=deepseek`,
    `model=<model>`.
  - `opencode`: `env = { DEEPSEEK_API_KEY: <key> }`; AgentRef `provider=deepseek`,
    `model=<model>` (opencode invoked as `--model deepseek/<model>`).
- **GLM (z.ai coding plan)** — `engines: [claude]`, `models: [glm-4.6, glm-4.5]`,
  `env = { ANTHROPIC_BASE_URL: https://api.z.ai/api/anthropic, ANTHROPIC_AUTH_TOKEN: <key>,
  ANTHROPIC_MODEL: <model> }`; AgentRef `provider=glm`, `model=<model>`.

A preset declares `keyEnv` (which env var holds the key) so the form is generic.

## 4. Backend

New module `app/services/connections.py` (store + CRUD + masking + preset catalog) and
`app/services/connection_test.py` (real CLI test). New router `app/api/v1/connections.py`:

- `GET  /api/v1/connection-presets` → catalog (§3).
- `GET  /api/v1/connections` → list, keys masked.
- `POST /api/v1/connections` → `{ presetProvider, engine, model, label?, key }` → builds `env`
  from the preset + key, generates id, status `untested`, persists.
- `DELETE /api/v1/connections/{id}` → remove (and surface any workspace role still using it).
- `POST /api/v1/connections/{id}/test` → run the connection's **engine on a 1-token prompt**
  with its `env`, via the existing `AgentRunner` (claude → `claude -p --model <m>`; opencode →
  `opencode run --model <prov>/<m>`). Exit 0 + non-empty output → `status=connected`; else
  `failed` + `lastError` (e.g. "claude CLI not found", "401", "unknown model"). Mirrors the
  manual `HEPHAESTUS_DS_OK` smoke test. Timeout ~60s.

### Load-time resolver (registry)
In `app/core/workspaces.py::_load_profile`, after parsing the profile: if `roleConnections`
is present, resolve each id against the global store and **populate the in-memory
`RepoProfile`** — set `agents.{role}` to an `AgentRef(provider, model, engineProfile=<connId>)`
and add an in-memory `EngineProfile(name=<connId>, engine=<conn.engine>, env=<conn.env>)` to
`engine_profiles`. Result: the runner sees a fully-populated profile exactly as today —
**`opencode_runner` and the FSM are unchanged**. A dangling id (deleted connection) → that
role falls back to the existing `agents` config and logs a warning; the API exposes
`roleWarnings` so the UI can flag it. Keys are **never written** into `profile.json`.

### Role assignment endpoint
Extend `WorkspaceUpdateRequest` + `PATCH /api/v1/workspaces/{id}` to accept `roleConnections`
(persisted verbatim to `profile.json` via `registry.update`). Validation: every referenced id
must exist in the global store (else 400 naming the bad id).

## 5. Frontend

Replace the engine/agents portion of `views/SettingsView.vue` and retire `AgentRefEditor.vue` /
`AgentListEditor.vue`'s raw-engine usage. Two sections (new components):

- **`ConnectionsManager.vue` — «Подключения» (global):** list of connections with a status
  badge (`untested`/`connected`/`failed`) + masked key; **«Добавить»** opens a form (preset →
  engine → model → key) with a **«Проверить»** button that calls `/test` and shows the result;
  delete with a guard if a workspace role uses it.
- **`AgentRolesPicker.vue` — «Роли агентов» (per-workspace):** each role is a `<select>` of
  **connected** connections only (untested/failed are disabled with a hint); lists render N
  rows (validators×5, arbiters×2) each independently assignable; a **«Применить ко всем»**
  shortcut sets every role to one connection. Saves `roleConnections` via the workspace PATCH.

API client + types: `Connection`, `ConnectionPreset`, `RoleConnections`; methods
`getConnectionPresets`, `getConnections`, `createConnection`, `deleteConnection`,
`testConnection`, and `roleConnections` on the workspace update.

## 6. Back-compat & migration

- Workspaces without `roleConnections` keep working unchanged (resolver no-ops; existing
  `agents`/`engineProfiles` used as today).
- One-click **«Импортировать текущий профиль как подключение»**: reads the active workspace's
  existing `deepseek` engineProfile → creates a global connection from it → sets
  `roleConnections` for all roles to that connection. Lets existing setups adopt the new flow
  without re-entering the key.

## 7. Error handling

- Missing CLI on test → `failed` + clear `lastError` ("claude CLI not found on PATH"); never a
  500.
- Bad key / unknown model on test → `failed` + the engine's stderr summary.
- Dangling connection id at load → role fallback + `roleWarnings` (no crash).
- Assigning an unknown id via PATCH → 400 naming the id.
- Global store unreadable/corrupt → treated as empty list + logged (never crashes the app).

## 8. Testing

- **Backend unit:** preset catalog shape; connection CRUD + key masking; env-build per
  (provider, engine); the load-time resolver (happy path + dangling-id fallback); PATCH
  validation of unknown ids. Test endpoint with a **mocked** `AgentRunner` (success → connected;
  non-zero/empty → failed; runner-not-found → failed).
- **Frontend unit:** add-connection form builds the right payload; status badges; role
  `<select>` only offers connected connections; "apply to all"; delete-guard.
- **Live (verify skill):** real `Проверить` on the existing DeepSeek key (expect `connected`),
  and on a GLM/z.ai key if provided; assign to a role and confirm the resolved profile drives
  `claude --model …` correctly.

## 9. Out of scope (YAGNI)

Anthropic-direct / OpenAI presets; encryption-at-rest for keys; per-connection rate/cost
config; editing a connection in place (delete + re-add covers it for now).
