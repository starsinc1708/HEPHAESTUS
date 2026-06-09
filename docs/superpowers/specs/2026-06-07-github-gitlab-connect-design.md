# GitHub/GitLab Connect (UI, no env) — Design

**Goal:** Connect GitHub and GitLab (incl. a self-hosted GitLab host) from the UI with a Personal
Access Token — no env files — verify the connection, and remove the unused Linear integration.
The kept actions (import issues → tasks, create PR/MR, sync status) read the stored credential
instead of env. Final sub-project (#8) of the HEPHAESTUS v2 redesign ([[hephaestus-v2-redesign]]).

**Status:** approved (brainstorming 2026-06-07). Decisions: auth via **PAT in the UI** (no
OAuth); **remove Linear**.

**Current state (probed):** a provider registry (`app/services/integrations/registry.py`) holds
github/gitlab/linear providers, each with `.available()` (true when its **env token** is set —
e.g. `linear_service` reads `LINEAR_API_KEY`) + `.capabilities()`; the default provider is
matched by the active repo's git-remote host. `GET /api/v1/integrations` returns providers with
`available` + capabilities; `POST …/{name}/import` (issues→tasks), `POST …/pr`, `POST
…/{name}/sync-status/{item_id}` are kept (autofix/changelog were removed in #2). `IntegrationsPanel`
(trimmed in #2) only lists providers — there is **no connect UI** (auth is env-only).

---

## 1. Stored credential model (`state/integrations.json`)

A global credential store next to `connections.json` (mirrors that pattern):
```jsonc
{ "github": { "token": "ghp_…", "status": "connected", "lastTestedAt": "…", "lastError": null },
  "gitlab": { "token": "glpat_…", "host": "https://gitlab.example.com", "status": "connected", … } }
```
- Tokens stored plaintext on disk (same as `connections.json`) but **masked in every API
  response** (reuse `mask_env`-style masking). GitLab carries a **`host`** (default
  `https://gitlab.com`; a self-hosted base URL otherwise). New `app/services/integrations/creds.py`:
  `get_cred(name)`, `set_cred(name, token, host=None)`, `clear_cred(name)`, `set_status(...)`,
  `list_masked()`. Never-crash on a corrupt store (→ empty).

## 2. Connect / verify / disconnect + provider auth from the store

- `POST /api/v1/integrations/{name}/connect {token, host?}` → store the cred, then **verify** with
  a real API call: GitHub `GET https://api.github.com/user` (header `Authorization: Bearer
  <token>`); GitLab `GET {host}/api/v4/user` (header `PRIVATE-TOKEN: <token>`). 2xx → `connected`;
  else → `failed` + a friendly `lastError` (401 → "неверный токен", network → "недоступен").
  Never 500.
- `POST /api/v1/integrations/{name}/disconnect` → `clear_cred`.
- `GET /api/v1/integrations` (existing) → augment each provider with `connected` + masked-token
  presence + `host`.
- `app/services/integrations/gitlab_service.py` / `github_issues.py`: read the token (and GitLab
  `host`/API base) from `creds.py` **instead of env**; `.available()` = a stored token exists.
  (Keep an env-token fallback only if trivial; otherwise the store is the single source.)

## 3. Remove Linear

Delete `app/services/integrations/linear_service.py`, its registry registration, any
Linear-specific config keys, and its tests. The registry then holds only `github` + `gitlab`.
Grep `linear` over `backend/app` + `frontend/src` → clean.

## 4. Frontend — `IntegrationsPanel` connect UI (Settings)

GitHub + GitLab cards, each:
- status chip (подключён / не подключён, from `connected`);
- **«Подключить»** → token `<input type=password data-test="int-token-<name>">` + (GitLab only) a
  **host** `<input data-test="int-host-gitlab">` (default `https://gitlab.com`) → submit
  (`data-test="int-connect-<name>"`) calls `/connect` → shows the verify result;
- masked token + **«Проверить»** (re-verify) + **«Отключить»** when connected;
- capabilities (импорт issues, PR/MR) shown when connected — the existing `/import` + `/pr`
  actions, now backed by the stored credential.

## 5. Kept actions (now store-backed)

`/import` (issues → `pending` tasks), `/pr` (create PR/MR), `/sync-status` are unchanged in shape;
only the credential source moves env → store. The board's import flow (#7) is unaffected.

## 6. Testing

- **Backend unit:** `creds.py` CRUD + masking + corrupt-store→empty; `connect` verify (mock HTTP:
  200→connected, 401→failed+message, network-error→failed, never raises); gitlab host used in the
  verify URL; provider `.available()` reads the store; Linear is gone from the registry.
- **Backend contract:** `/connect` (github + gitlab w/ host), `/disconnect`, `/integrations`
  exposes `connected`+masked token+host; `/import`+`/pr` resolve the stored credential.
- **Frontend unit:** GitHub/GitLab cards render; connect sends `{token, host?}`; GitLab shows the
  host field, GitHub does not; verify updates the status chip; masked token; disconnect clears.
- **Live (verify skill):** connect GitHub with a real PAT → verify → `connected` (`GET /user`);
  connect GitLab (gitlab.com or a self-hosted host) with a PAT → verify; a bad token → `failed`
  with the message; (if access) import an issue → a `pending` task appears. Capture evidence.

## 7. Out of scope

OAuth (PAT chosen); new providers; webhooks/push events; autofix/changelog (removed in #2);
changing the import/PR logic (only the credential source changes).

## 8. Risks

- **Tokens plaintext** in `state/integrations.json` — same posture as `connections.json`; mask in
  every API response, keep the store out of git, never log the token.
- **Verify network/timeout** — short timeout, never-crash → `failed` with a clear message.
- **Self-hosted host** — validate the URL (https scheme, no path traversal) before building the
  `{host}/api/v4/...` URL.
- **Env→store migration** — if a user already had `GITHUB_TOKEN`/`GITLAB_TOKEN` in env, optionally
  seed the store from env on first read so they aren't logged out; otherwise they reconnect once.
