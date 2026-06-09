---
title: HEPHAESTUS Epic 3 — Tracker Integrations (provider abstraction + GitHub + GitLab + Linear)
status: approved
date: 2026-06-06
audience: implementing engineer
language: prose=ru, identifiers/paths/commands=en
depends_on: [2026-06-05-universal-tool-overview-design, 2026-06-06-epic1-ai-powered-merge-design]
defines_for: [epic3-integrations-plan]
---

# Epic 3 — Tracker Integrations

Закрывает фичи #7 (GitHub/GitLab) и #8 (Linear) + GitHub changelog/PR/авто-фикс. Решения с пользователем:

- **D-e3-1.** Токены интеграций — из **env** (`GITLAB_TOKEN`, `LINEAR_API_KEY`); GitHub — через `gh`-логин. Токены НЕ хранятся в profile.json/файлах (безопасность).
- **D-e3-2.** GitLab — через **`glab` CLI** (по аналогии с `gh`); деградирует gracefully, если glab не установлен/не залогинен.
- **D-e3-3.** Авто-фикс issues — **кнопка «Sync» + опциональный фоновый poller** по метке → очередь → loop.
- **D-e3-4.** Создание PR/MR — **отдельное действие на ветке** (BranchesView/TaskDrawer), независимо от локального merge (Epic 1).

Переиспользуем: существующий `GitHubIssuesService` (`backend/app/services/github_issues.py`, gh CLI) — issues CRUD + `sync_to_queue` + `sync_status_to_issue` уже есть; расширяем, не дублируем. `_run`/subprocess-паттерн из `helpers.py`/`git.py`. Background-task паттерн `state_broadcaster` (`broadcaster.py`) для poller'а.

---

## 1. Карта компонентов

| Часть | Артефакт | Статус |
|---|---|---|
| 3A | `IntegrationProvider` Protocol + `ProviderCapabilities` в `backend/app/services/integrations/base.py` | новый |
| 3A | `provider_registry()` (env-detected: github/gitlab/linear) в `integrations/registry.py` | новый |
| 3A | config: `HEPHAESTUS_AUTOFIX_LABEL`, `HEPHAESTUS_AUTOFIX_POLL_SEC`, `HEPHAESTUS_AUTOFIX_ENABLED`, provider-enabled флаги | правка `config.py` |
| 3B | GitHub: `create_pr()` (gh pr create) в `github_issues.py` (или новый `github_pr.py`) | правка |
| 3B | changelog: `generate_changelog(ws, *, since)` (git log → LLM) в `integrations/changelog.py` + `prompts/changelog.md` | новый |
| 3B | autofix poller: background task `autofix_poller()` (label → sync_to_queue) в `integrations/autofix.py` | новый |
| 3C | GitLab provider: `GitLabService` (`glab` CLI) в `integrations/gitlab_service.py` | новый |
| 3D | Linear provider: `LinearService` (GraphQL via httpx) в `integrations/linear_service.py` | новый |
| API | `api/v1/integrations.py`: providers list, create-pr, changelog, autofix toggle; extend `issues.py` | новый+правка |
| UI | provider-выбор + «Create PR/MR» на ветке + changelog-панель + autofix-toggle | правка |

**Границы.** Каждый провайдер — самостоятельный класс с одним назначением (один трекер). `base.py` — только контракт. `registry.py` — только выбор доступных. Poller/changelog — отдельные модули, не знают про конкретный провайдер сверх протокола.

---

## 2. Часть 3A — Provider abstraction

`backend/app/services/integrations/base.py`:
```python
from typing import Protocol, Any
from pydantic import BaseModel


class ProviderCapabilities(BaseModel):
    issues: bool = False        # list/import issues + status sync
    pull_requests: bool = False # create_pr/MR
    changelog: bool = False     # changelog from git history


class IntegrationProvider(Protocol):
    name: str                                   # "github" | "gitlab" | "linear"
    def available(self) -> bool: ...            # CLI present / token set
    def capabilities(self) -> ProviderCapabilities: ...
    def list_issues(self, *, labels: list[str] | None = None, state: str = "open",
                    limit: int = 50) -> list[dict[str, Any]]: ...
    def import_to_queue(self, *, label: str) -> dict[str, Any]: ...   # labeled issues -> tasks
    def sync_status(self, item: dict[str, Any]) -> None: ...
    def create_pr(self, branch: str, *, title: str, body: str,
                  base: str) -> dict[str, Any] | None: ...            # None if unsupported
```
- Linear: `capabilities = {issues:True, pull_requests:False, changelog:False}`; `create_pr` returns `None`.
- GitHub/GitLab: all three True.

`backend/app/services/integrations/registry.py`:
```python
def provider_registry() -> dict[str, IntegrationProvider]:
    """All providers whose `available()` is True (env/CLI detected)."""
def get_provider(name: str) -> IntegrationProvider | None: ...
def default_provider() -> IntegrationProvider | None:
    """First available, preferring the one matching the active repo's remote host."""
```
Detection: github = `gh` on PATH (and a github.com remote); gitlab = `glab` on PATH OR `GITLAB_TOKEN` set (and gitlab remote); linear = `LINEAR_API_KEY` set. `available()` is cheap and never raises.

GitHub adapter: wrap existing `GitHubIssuesService` to satisfy the protocol (`import_to_queue` delegates to `sync_to_queue`; `sync_status` to `sync_status_to_issue`; add `create_pr`, `capabilities`, `available`).

Config keys (`config.py` ALLOWED_CONFIG_KEYS + defaults): `HEPHAESTUS_AUTOFIX_LABEL` (default `hephaestus:autofix`), `HEPHAESTUS_AUTOFIX_POLL_SEC` (default 0 = off), `HEPHAESTUS_AUTOFIX_ENABLED` (default off), `HEPHAESTUS_DEFAULT_PROVIDER` (optional).

---

## 3. Часть 3B — GitHub: PR + changelog + autofix

### 3B.1 create_pr (gh pr create)
Add to GitHub adapter:
```python
def create_pr(self, branch, *, title, body, base) -> dict | None:
    # gh pr create --head <branch> --base <base> --title <t> --body <b> --json number,url
    # branch must be pushed to origin first (push if needed). Returns {number, url} or None.
```
Push the branch to remote before `gh pr create` (PR needs the head on origin). Reuse `_run`/subprocess. On `gh` absent/fail → return None (surfaced as a clear API error, not a crash).

### 3B.2 changelog (`integrations/changelog.py`)
```python
async def generate_changelog(ws, *, since: str | None, runner) -> dict:
    # git log <since>..HEAD --pretty=... (or all if since None) -> render prompts/changelog.md
    # -> agent -> parse CHANGELOG_BEGIN{...}CHANGELOG_END or markdown -> {markdown, version_suggestion}
```
`prompts/changelog.md`: input = commit list (+ optional completed-task summaries); output = grouped changelog (Features / Improvements / Fixes) in keep-a-changelog markdown + a suggested semver bump. Never raises (empty log → empty changelog). Optional `gh release create` is a SEPARATE explicit action (not auto).

### 3B.3 autofix poller (`integrations/autofix.py`)
```python
async def autofix_poller(interval_sec: int, label: str) -> None:
    # background asyncio task (started in app/main.py lifespan when HEPHAESTUS_AUTOFIX_ENABLED).
    # each tick: default_provider().import_to_queue(label=label); log added count.
    # never raises; sleeps interval; respects a stop event.
```
Manual button → `POST /api/v1/integrations/autofix/sync` (one-shot `import_to_queue`). Toggle → `POST /api/v1/integrations/autofix {enabled, intervalSec, label}` persists config; the lifespan task reads it. Poller does NOT auto-start the loop — it only fills the queue (operator/Ralph drains it).

---

## 4. Часть 3C — GitLab (`integrations/gitlab_service.py`)

`GitLabService` mirrors `GitHubIssuesService` but via `glab` CLI:
```python
class GitLabService:
    def available(self) -> bool:        # shutil.which("glab") is not None
    def _glab(self, args) -> ...:       # subprocess like _gh; --repo <project>; JSON out
    def list_issues(...): ...           # glab issue list --output json
    def import_to_queue(*, label): ...  # labeled issues -> _queue_add (ids "gl-<iid>")
    def sync_status(item): ...          # glab issue note / label by status (source_issue + provider tag)
    def create_pr(branch, *, title, body, base):  # glab mr create --source-branch ... --json
    def capabilities(): return ProviderCapabilities(issues=True, pull_requests=True, changelog=True)
```
Project detection from the active repo's gitlab remote (parse `git remote get-url origin`). Auth: glab login OR `GITLAB_TOKEN` env (glab reads it). glab absent → `available()` False; service methods return empty/None (no crash). Task ids prefixed `gl-` to avoid collision with `gh-`. Item carries `source_issue` + a `source_provider="gitlab"` tag so `sync_status` routes correctly.

---

## 5. Часть 3D — Linear (`integrations/linear_service.py`)

`LinearService` via Linear GraphQL API (`https://api.linear.app/graphql`, header `Authorization: <LINEAR_API_KEY>`), using `httpx` (already a dep):
```python
class LinearService:
    def available(self) -> bool:        # bool(os.environ.get("LINEAR_API_KEY"))
    def _gql(self, query, variables) -> dict:   # httpx POST; never raises -> {} on error
    def list_issues(*, labels=None, state="open", limit=50): ...  # issues(filter:...) query
    def import_to_queue(*, label): ...  # issues with label -> _queue_add (ids "ln-<identifier>")
    def sync_status(item): ...          # issueUpdate mutation: stateId by status map + comment
    def create_pr(...): return None     # Linear is a tracker, not a git host
    def capabilities(): return ProviderCapabilities(issues=True, pull_requests=False, changelog=False)
```
State mapping (status → Linear workflow state) is configurable but ships sane defaults (pending→Todo, in_progress→In Progress, done→Done, merged→Done). Missing/invalid key → `available()` False. Task ids prefixed `ln-`. `source_provider="linear"`.

---

## 6. API (`backend/app/api/v1/integrations.py`) + extend issues.py

| Метод+путь | Назначение |
|---|---|
| `GET /api/v1/integrations` | `{providers:[{name, available, capabilities}], default}` |
| `POST /api/v1/integrations/{name}/import` `{label}` | labeled issues → queue (any provider) |
| `POST /api/v1/integrations/{name}/sync-status/{itemId}` | push one item's status to its tracker |
| `POST /api/v1/integrations/pr` `{branch, provider?, title?, body?, base?}` | create PR/MR from a branch |
| `POST /api/v1/integrations/changelog` `{since?}` | generate changelog markdown |
| `GET /api/v1/integrations/autofix` · `POST /api/v1/integrations/autofix` `{enabled, intervalSec, label}` | autofix poller config |
| `POST /api/v1/integrations/autofix/sync` | one-shot autofix import |

Existing `api/v1/issues.py` GitHub endpoints stay (back-compat). New generic endpoints route by `provider` (default = `default_provider()`). All return `{ok, ...}` / `{ok:false, error}`; unavailable provider → clear 409 (`"<name> not available (CLI/token missing)"`), never a 500 crash.

---

## 7. Безопасность

- Токены только из env; никогда не логируются, не пишутся в state/profile, не возвращаются в API.
- Все провайдер-методы graceful при отсутствии CLI/токена (`available()` False → 409, не 500).
- `create_pr` пушит ветку на origin перед PR; только safe `auto/*`/feature-ветки (валидация имени как в Epic 1 `_is_safe_auto_branch` где применимо).
- Poller: bounded interval (мин. 30с), never-raise, останавливается по stop-event на shutdown.
- Task id namespacing (`gh-`/`gl-`/`ln-`) — нет коллизий между трекерами.

---

## 8. Тестирование (TDD)

**Юнит (CLI/HTTP застаблены):**
- `provider_registry`/`get_provider`/`default_provider` с подменённым `shutil.which`/env.
- GitHub `create_pr` — застабить `_gh`/subprocess, проверить аргументы `gh pr create` + push-before.
- GitLab `GitLabService` — застабить `_glab` subprocess; list/import/create_mr аргументы; `available()` False без glab.
- Linear `_gql` — застабить httpx; list/import/sync mutation payloads; `available()` False без ключа.
- changelog parse (git log застаблен + stub runner) → markdown.
- autofix poller — один tick с застабленным провайдером добавляет задачи; never-raise на ошибке провайдера.

**Контракт (FastAPI TestClient, провайдеры замоканы):**
- `GET /api/v1/integrations` форма; unavailable provider → 409 на import/pr; `POST .../pr` → {number,url}; `POST .../changelog` → markdown; autofix toggle persist.

**Кроссплатформа:** subprocess (gh/glab) и httpx — CI windows+ubuntu; CLI всегда застаблен в CI.

---

## 9. Вне scope Эпика 3

- Webhooks (push-уведомления от трекеров) — pull-only (poller).
- Линковка PR-ревью-комментов обратно в задачи (parallel-specialist PR review Aperant) — отдельный эпик.
- Двусторонний rich-синк (только статус + импорт; не правим issue-тела из HEPHAESTUS сверх комментов/меток).
- Insights/Ideas (Эпик 4).
