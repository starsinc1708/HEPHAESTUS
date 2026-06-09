# Epic 3 — Tracker Integrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A provider abstraction over issue trackers + GitHub PR creation / changelog / autofix poller, plus GitLab (glab CLI) and Linear (GraphQL) providers.

**Architecture:** `IntegrationProvider` protocol with capability flags; a registry that surfaces only env/CLI-available providers. GitHub adapter wraps the existing `GitHubIssuesService` (+ create_pr); GitLab via `glab` subprocess; Linear via httpx GraphQL. A changelog module (git log → LLM) and a background autofix poller (label → queue). A generic `/api/v1/integrations` router routes by provider.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 / pytest; subprocess (gh/glab) + httpx (Linear); Vue 3 / Vitest.

**Spec:** `docs/superpowers/specs/2026-06-06-epic3-integrations-design.md` — source of truth; read first.

**Commands (EXACT):**
- Backend tests: `cd backend && .venv/Scripts/python.exe -m pytest tests/<path> -v`
- Lint/types: `cd backend && .venv/Scripts/python.exe -m ruff check .` and `.venv/Scripts/python.exe -m mypy --strict app/` (keep both clean; tests/ untyped pre-existing — ignore)
- Frontend: `cd frontend && npx vitest run` / `npx vue-tsc --noEmit` / `npm run build`

**Conventions / read first:**
- `backend/app/services/github_issues.py` — `GitHubIssuesService` (gh CLI wrapper `_gh`, list/get/create/update issues, `sync_to_queue`, `sync_status_to_issue`, `create_from_task`). The GitHub adapter wraps THIS.
- `backend/app/api/v1/issues.py` — existing GitHub issue endpoints (keep).
- `backend/app/core/helpers.py` `_run`, `_active_git`; `backend/app/core/queue.py` `_queue_add`/`add_proposals_to_queue`.
- `backend/app/core/broadcaster.py` `state_broadcaster` — background-task pattern for the poller; `backend/app/main.py` lifespan — where to start it.
- `backend/app/services/prompt_manager.py` `render_prompt`; `backend/app/services/opencode_runner.py` `AgentRunner` (for changelog LLM).
- `backend/app/config.py` ALLOWED_CONFIG_KEYS pattern.
- httpx is already a dependency (`backend/.venv` has httpx) — use it for Linear.
- Test patterns: `backend/tests/contract/test_merge_api.py`, `backend/tests/unit/test_*`.

Branch `feat/epic3-integrations`. One commit per task.

---

## File Structure
**New:** `backend/app/services/integrations/__init__.py`, `base.py`, `registry.py`, `github_provider.py` (adapter), `gitlab_service.py`, `linear_service.py`, `changelog.py`, `autofix.py`; `backend/app/api/v1/integrations.py`; `prompts/changelog.md`.
**Modified:** `backend/app/services/github_issues.py` (+create_pr), `backend/app/config.py`, `backend/app/main.py` (register router + start poller), frontend `types/api.ts`/`api/client.ts` + new `IntegrationsPanel.vue` + `BranchesView.vue`/`TaskDrawer.vue` (Create PR/MR button).

---

## BATCH A — Provider abstraction + GitHub adapter + create_pr + config

### Task A1: base protocol + capabilities
**Files:** Create `backend/app/services/integrations/__init__.py`, `backend/app/services/integrations/base.py`; Test `backend/tests/unit/test_integration_base.py`.
- [ ] Test: `ProviderCapabilities` defaults all False; round-trips; can construct `{issues:True, pull_requests:True, changelog:True}`.
- [ ] Implement `ProviderCapabilities(BaseModel)` (issues/pull_requests/changelog bools) and `IntegrationProvider(Protocol)` exactly per spec §2. `__init__.py` exports them.
- [ ] ruff + mypy app/ clean. Commit: `feat(epic3): IntegrationProvider protocol + capabilities`

### Task A2: GitHub create_pr + adapter
**Files:** Modify `backend/app/services/github_issues.py` (+`create_pr`, `available`, `capabilities`); Create `backend/app/services/integrations/github_provider.py` (thin adapter to the protocol); Test `backend/tests/unit/test_github_pr.py`.
- [ ] **Test** (stub `_gh` + a push runner): `create_pr("auto/x", title="T", body="B", base="main")` → calls `gh pr create --head auto/x --base main --title T --body B --json number,url` and returns `{number, url}`; pushes the branch first. Patch `subprocess.run`/`_run` to capture argv; assert the push and the pr-create commands. Also test: when gh missing (`available()` False), `create_pr` returns None.
```python
def test_create_pr_pushes_then_creates(monkeypatch):
    svc = GitHubIssuesService("owner/repo")
    calls = []
    def fake_gh(args, input_data=None):
        calls.append(args)
        return {"number": 7, "url": "https://github.com/owner/repo/pull/7"}
    monkeypatch.setattr(svc, "_gh", fake_gh)
    pushes = []
    monkeypatch.setattr("app.services.github_issues._run",
                        lambda cmd, **kw: pushes.append(cmd) or "")
    res = svc.create_pr("auto/x", title="T", body="B", base="main")
    assert res["number"] == 7
    assert any("pr" in a and "create" in a for a in calls)
    assert any("push" in c for c in pushes)  # branch pushed before PR
```
- [ ] Implement `create_pr` in `GitHubIssuesService` (push `auto/x` to origin via `_run(["git","push","-u","origin",branch], cwd=repo)`, then `self._gh(["pr","create","--head",branch,"--base",base,"--title",title,"--body",body,"--json","number,url"])`; return its dict or None). Add `available()` (`shutil.which("gh") is not None`) and `capabilities()` (issues/pr/changelog all True).
- [ ] Implement `github_provider.py`: a `GitHubProvider` class with `name="github"` implementing the protocol by delegating to `GitHubIssuesService` (`import_to_queue`→`sync_to_queue`; `sync_status`→`sync_status_to_issue`; `list_issues`/`create_pr` direct; `available`/`capabilities`).
- [ ] Tests + ruff + mypy app/ clean. Commit: `feat(epic3): GitHub create_pr + provider adapter`

### Task A3: registry + config keys
**Files:** Create `backend/app/services/integrations/registry.py`; Modify `backend/app/config.py`; Test `backend/tests/unit/test_provider_registry.py`.
- [ ] **Test** (monkeypatch `shutil.which` + env): with gh present → registry has "github"; with `LINEAR_API_KEY` set → has "linear"; with neither glab nor token → no "gitlab"; `get_provider("github")` returns it; `default_provider()` returns an available one or None.
- [ ] Implement `registry.py`: `provider_registry()` builds GitHubProvider/GitLabService/LinearService (import lazily to avoid hard deps), includes only those whose `available()` is True; `get_provider(name)`; `default_provider()` (prefer the provider matching the active repo remote host, else first available). Must NOT raise if a provider module import fails — skip it.
- [ ] Add config keys to `ALLOWED_CONFIG_KEYS` + defaults: `HEPHAESTUS_AUTOFIX_LABEL` (`hephaestus:autofix`), `HEPHAESTUS_AUTOFIX_POLL_SEC` (0), `HEPHAESTUS_AUTOFIX_ENABLED` (off), `HEPHAESTUS_DEFAULT_PROVIDER` (empty).
- [ ] Tests + gates. Commit: `feat(epic3): provider registry + autofix config keys`

---

## BATCH B — GitHub changelog + autofix poller

### Task B1: changelog
**Files:** Create `backend/app/services/integrations/changelog.py`, `prompts/changelog.md`; Test `backend/tests/integration/test_changelog.py`.
- [ ] **Test** (stub git log via monkeypatching `_run` to return a fixed commit list; stub runner writing a CHANGELOG block): `generate_changelog(ws, since="v1.0", runner=stub)` → returns `{markdown, versionSuggestion}` with the grouped sections present. Empty log → empty-ish markdown, no raise.
- [ ] Implement `prompts/changelog.md` (input `commits`, output grouped Features/Improvements/Fixes keep-a-changelog markdown + a `versionSuggestion`; wrap machine output in `CHANGELOG_BEGIN{...}CHANGELOG_END` OR just markdown — parse leniently). Implement `generate_changelog(ws, *, since, runner)`: `git log [since..HEAD] --pretty=format:%h %s (%an)` via `_run`, render prompt, run agent, parse → `{markdown, versionSuggestion}`. Never raise.
- [ ] Gates. Commit: `feat(epic3): changelog generation from git history`

### Task B2: autofix poller
**Files:** Create `backend/app/services/integrations/autofix.py`; Modify `backend/app/main.py` (start in lifespan when enabled); Test `backend/tests/unit/test_autofix_poller.py`.
- [ ] **Test:** a single `_autofix_tick(label)` with `default_provider` monkeypatched (returns a fake whose `import_to_queue` returns `{added:["gh-1"]}`) → returns the added list; when the provider raises, the tick swallows it and returns `{added:[],errors:[...]}` (never raises). (Test the tick function, NOT an infinite loop.)
- [ ] Implement `autofix.py`: `async def _autofix_tick(label) -> dict` (calls `default_provider().import_to_queue(label=label)`, never raises) and `async def autofix_poller(interval_sec, label, stop_event)` (loop: tick, sleep `max(30, interval_sec)`, break on stop_event). In `main.py` lifespan: when `HEPHAESTUS_AUTOFIX_ENABLED` and `HEPHAESTUS_AUTOFIX_POLL_SEC>0`, create the poller task with an `asyncio.Event` stop, cancel on shutdown (mirror `state_broadcaster` lifecycle).
- [ ] Gates. Commit: `feat(epic3): autofix poller (label -> queue) + lifespan wiring`

---

## BATCH C — GitLab + Linear providers

### Task C1: GitLab (glab)
**Files:** Create `backend/app/services/integrations/gitlab_service.py`; Test `backend/tests/unit/test_gitlab_service.py`.
- [ ] **Test** (monkeypatch `shutil.which` + a fake `_glab`): `available()` True only when glab present; `list_issues` parses fake JSON; `import_to_queue(label=...)` enqueues `gl-<iid>` items (patch `_queue_add`); `create_pr` (MR) builds `glab mr create --source-branch ... --target-branch ... --title ... --json`. `available()` False → methods return empty/None, no crash.
- [ ] Implement `GitLabService` mirroring `GitHubIssuesService` shape but via `glab`: `available()` (`shutil.which("glab")`), `_glab(args)` (subprocess JSON, like `_gh`), project detection from gitlab remote, `list_issues`/`import_to_queue` (ids `gl-`, item `source_issue`+`source_provider="gitlab"`)/`sync_status`/`create_pr`/`capabilities` (all True). Never raise on glab absent.
- [ ] Gates. Commit: `feat(epic3): GitLab provider via glab CLI`

### Task C2: Linear (GraphQL)
**Files:** Create `backend/app/services/integrations/linear_service.py`; Test `backend/tests/unit/test_linear_service.py`.
- [ ] **Test** (monkeypatch env `LINEAR_API_KEY` + httpx): `available()` True only with the key; `_gql` posts to the Linear endpoint with the auth header (patch `httpx.Client.post`/`httpx.post` to capture + return a fake response); `list_issues` parses the GraphQL response; `import_to_queue` enqueues `ln-<identifier>` items; `sync_status` builds an `issueUpdate` mutation; `create_pr` returns None; `capabilities` = issues only. No key → `available()` False, methods return empty/None.
- [ ] Implement `LinearService`: `available()` (`bool(os.environ.get("LINEAR_API_KEY"))`), `_gql(query, variables)` via httpx (timeout, never raise → `{}` on error), `list_issues`/`import_to_queue`/`sync_status` (state map with defaults)/`create_pr`→None/`capabilities`. ids `ln-`, `source_provider="linear"`.
- [ ] Gates. Commit: `feat(epic3): Linear provider via GraphQL`

---

## BATCH D — Integrations API

### Task D1: `/api/v1/integrations` router
**Files:** Create `backend/app/api/v1/integrations.py`; Modify `backend/app/main.py` (register); Test `backend/tests/contract/test_integrations_api.py`.
- [ ] **Test** (patch `provider_registry`/`get_provider`/`default_provider` with fakes): `GET /api/v1/integrations` → `{providers:[{name,available,capabilities}], default}`; `POST /api/v1/integrations/github/import {label}` → added list; unavailable provider → 409; `POST /api/v1/integrations/pr {branch}` → `{number,url}` (fake create_pr); `POST /api/v1/integrations/changelog {since}` → markdown; autofix GET/POST persists config.
- [ ] Implement the router per spec §6. Route by `{name}` or `default_provider()`. Unavailable/None provider → 409 JSON. PR endpoint validates branch name (reuse `_is_safe_auto_branch` where applicable, else a safe regex). Register the router in `main.py`.
- [ ] Gates (full suite). Commit: `feat(epic3): integrations API router`

---

## BATCH E — Frontend
### Task E1: types + client
- [ ] `types/api.ts`: `IntegrationProvider` (`{name, available, capabilities:{issues,pullRequests,changelog}}`), `Changelog` (`{markdown, versionSuggestion}`). `api/client.ts`: `listIntegrations()`, `importIssues(provider,label)`, `createPr(branch, opts)`, `generateChangelog(since?)`, `getAutofix()`, `setAutofix(opts)`, `syncAutofix()`. `vue-tsc` clean. Commit: `feat(epic3): frontend integration types + client`

### Task E2: IntegrationsPanel + Create PR/MR button + changelog
**Files:** Create `frontend/src/components/IntegrationsPanel.vue`; Modify `frontend/src/views/BranchesView.vue` (+ Create PR/MR action) and a place for the panel (e.g. `ToolsView.vue`); Test `frontend/src/components/__tests__/IntegrationsPanel.spec.ts`.
- [ ] **IntegrationsPanel.vue:** lists providers (name + available badge + capabilities), an autofix toggle + label + interval (calls `setAutofix`), a "Sync issues" button (`importIssues`), and a changelog generator (button → `generateChangelog` → render markdown in a `<pre>`). Mount in ToolsView.
- [ ] **BranchesView.vue:** add a "Create PR/MR" action per `auto/*` branch (`data-test="create-pr"`) → `api.createPr(branch)` → toast with the returned URL. Disabled when no PR-capable provider available.
- [ ] **Test** (mock `@/api/client`): IntegrationsPanel renders providers from `listIntegrations`; clicking "Sync issues" calls `importIssues`; changelog button renders markdown. Keep existing specs green.
- [ ] `vitest` + `vue-tsc` + `build` clean. Commit: `feat(epic3): IntegrationsPanel + Create PR/MR + changelog UI`

---

## BATCH F — Integration verify + final review
- [ ] Full backend suite green + ruff + mypy app/ clean; frontend vitest + vue-tsc + build clean.
- [ ] Final reviewer subagent over `git diff master..HEAD`: focus — providers never raise on missing CLI/token (graceful 409 not 500), no token leakage into logs/state/API, task-id namespacing (gh-/gl-/ln-) no collisions, poller bounded + never-raise + clean shutdown, create_pr pushes before PR + validates branch. Apply fixes.

---

## Self-Review (applied)
- **Spec coverage:** §2→A1/A3; §3→A2(PR)/B1(changelog)/B2(poller); §4→C1; §5→C2; §6→D1; §7 safety→every provider never-raise + 409 + token-from-env; §8 testing→every task TDD with stubs; UI→E1/E2.
- **Carried unknowns:** glab/gh/httpx exact JSON shapes — implementers stub them; the GitHub adapter must not change existing `issues.py` behavior (keep back-compat).
- **Type consistency:** `ProviderCapabilities`/`IntegrationProvider`/`provider_registry`/`get_provider`/`default_provider`/`create_pr`/`generate_changelog`/`import_to_queue`/`sync_status` names consistent across tasks; frontend `pullRequests` camelCase matches `pull_requests` alias.
