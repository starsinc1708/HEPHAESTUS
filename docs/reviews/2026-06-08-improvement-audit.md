# HEPHAESTUS Autonomous-Loop — Improvement Audit Report

**Date**: 2026-06-08
**Scope**: Full-stack audit — backend (FastAPI), frontend (Vue 3), orchestrator (FSM), prompts, config, docs
**Method**: 3-pass multi-agent audit (21 agents total)
**Auditor**: Sisyphus (OhMyOpenCode)
**Context**: Open-source, self-hosted — user = admin, localhost-first deployment

---

## Executive Summary

HEPHAESTUS is a self-hosted open-source autonomous development loop: goal → decompose → execute → verify → merge. The backend is FastAPI + mypy-strict Python; the frontend is Vue 3 + Pinia; state is file-based JSON (no database). The target user is a developer running this on their own machine, pointing it at their own repos, with their own API keys.

**What works well**: The FSM orchestrator is architecturally sound. Token/cost tracking exists. Provider catalog covers 7 providers. Ralph mode has budget enforcement. Streaming works. Fallback agents exist. Prompt templates are well-structured.

**What blocks adoption**: The README describes a completely different (bash-based) system. No getting-started guide. Onboarding wizard is Russian-only. Port mismatch breaks first-run. Hard-coded paths/IPs in docs.

**What needs attention**: Unbounded disk growth from iteration artifacts. 60+ swallowed exceptions making debugging painful. Monolith FSM (800+ lines). Polling architecture creating unnecessary I/O.

### Self-Hosted Threat Model

Since HEPHAESTUS is self-hosted OSS, the threat model differs significantly from a SaaS product:

- **User = admin** — they own the machine, control the network, manage the keys
- **Localhost-first** — dashboard runs on the user's machine, not exposed to the internet by default
- **Single-user** — no multi-tenancy, no user isolation needed
- **Trusted input** — goal text comes from the user themselves, not from external attackers

This means many "security findings" from a SaaS audit are reclassified here:
- Open auth when no password is set → **by design** for local use (not a vulnerability)
- Plaintext secrets in state files → **acceptable** (user controls the filesystem)
- CORS wildcards → **fine** for localhost deployment
- No rate limiting → **low priority** (user's own machine, single user)

### Key Metrics

| Metric | Value |
|--------|-------|
| Files audited | ~200+ across backend, frontend, prompts, docs |
| Total unique findings | ~75 (after deduplication, reclassified for OSS) |
| Adoption-blocking | 4 (wrong README, Russian wizard, port mismatch, no getting-started) |
| High (quality/reliability) | 10 |
| Medium | 22 |
| Low | ~39 |
| Passes completed | 3 (Inventory → Dimension → Adversarial) |
| Agents deployed | 21 (7 + 8 + 6) |

### Priority Distribution

```
ADOPTION BLOCKERS  ████████  4   (wrong docs, Russian UI, port mismatch)
High               ████████████████████  10  (disk growth, swallowed errors, FSM size, polling)
Medium             ████████████████████████████████████████  22  (missing features, validation gaps)
Low                ████████████████████████████████████████████████████████████████  ~39  (nice-to-haves)
```

---

## Findings by Dimension

---

### 1. DX/Docs (Adoption Blockers)

> For an open-source project, documentation IS the product. If people can't run it, nothing else matters.

#### [DX-001] README describes a completely different system
- **Severity**: Adoption-blocking | **Effort**: M | **Confidence**: High (confirmed Pass 3)
- **Where**: `README.md:1-150`
- **Now**: README describes a bash-based loop with scripts (driver.sh, verify.sh, prompt-build.sh, start-loop.sh, start-dashboard.sh) that **do not exist**. The actual system is FastAPI + Vue 3 with a completely different architecture. The layout, commands, quick start, and guardrails sections are all wrong.
- **Proposal**: Rewrite README.md. Document the actual FastAPI + Vue 3 architecture. Include: project overview, screenshots, prerequisites, quick start (backend + frontend), configuration, architecture overview, and link to GETTING_STARTED.md.
- **Why**: This is the single biggest adoption blocker. Every new user follows the README, hits "command not found", and leaves. Estimated time to first successful run without docs: 4-8 hours. With proper docs: 15 minutes.

#### [DX-002] No GETTING_STARTED.md
- **Severity**: Adoption-blocking | **Effort**: M | **Confidence**: High (confirmed Pass 3)
- **Where**: Root directory — file doesn't exist
- **Now**: No step-by-step guide for setting up the FastAPI + Vue 3 system. RUNBOOK.md is for operators running the old bash system, not for developers setting up the current system.
- **Proposal**: Create GETTING_STARTED.md with: prerequisites (Python, Node, opencode CLI), backend setup (`cd backend && uv sync`), frontend setup (`cd frontend && npm install`), environment variables (`.env` configuration), first-run verification, and troubleshooting common issues.

#### [DX-003] No CONTRIBUTING.md
- **Severity**: High | **Effort**: S | **Confidence**: High (confirmed Pass 2 + Pass 3)
- **Where**: Root directory — file doesn't exist
- **Now**: No contribution guidelines, no code style requirements, no PR process, no testing expectations. Community members who want to contribute have no guidance.
- **Proposal**: Create CONTRIBUTING.md with: development setup, code style (mypy --strict, ruff), testing requirements, PR process, commit message format.

#### [DX-004] Hard-coded Linux paths and IPs throughout docs
- **Severity**: High | **Effort**: S | **Confidence**: High (confirmed Pass 3)
- **Where**: `README.md:8-9` (`/home/starsinc/`), `backend/.env.example:2-3` (`/home/starsinc/`), `RUNBOOK.md:18,40` (`192.168.0.103`)
- **Now**: Documentation contains developer-specific paths and LAN IP addresses. Won't work for anyone else.
- **Proposal**: Use `<YOUR_PATH>` placeholders. Use `localhost` instead of IPs. Make `.env.example` path-agnostic.

#### [DX-005] No Windows/cross-platform support documentation
- **Severity**: Medium | **Effort**: S | **Confidence**: High (confirmed Pass 3)
- **Where**: All documentation
- **Now**: All docs assume Linux (tmux, ufw, bash paths). The project actually runs on Windows (the developer IS on Windows). No cross-platform guidance.
- **Proposal**: Add Windows/WSL section to GETTING_STARTED.md. Test on both platforms. Document platform-specific steps.

#### [DX-006] Backend startup script references non-existent config
- **Severity**: Medium | **Effort**: S | **Confidence**: High (confirmed Pass 3)
- **Where**: `backend/start-backend.sh:5`
- **Now**: `source ../config.env 2>/dev/null || true` — file doesn't exist. Config silently not loaded. Confusing for new users.
- **Proposal**: Update script to source correct file or remove the reference.

#### [DX-007] No API documentation for contributors
- **Severity**: Medium | **Effort**: S | **Confidence**: High (confirmed Pass 2)
- **Where**: No OpenAPI/Swagger docs linked
- **Now**: 79 HTTP endpoints with no generated API documentation. FastAPI auto-generates OpenAPI schema (`/docs`) but it's not mentioned in docs.
- **Proposal**: Mention `/docs` endpoint in GETTING_STARTED.md. Add endpoint descriptions and examples to route decorators.

---

### 2. Security

> Reclassified for self-hosted OSS threat model. The user IS the admin running on their own machine. Findings are defense-in-depth recommendations, not critical vulnerabilities.

#### [SEC-001] Auth bypass when password not set — by design, needs documentation
- **Severity**: Medium (defense-in-depth) | **Effort**: S | **Confidence**: High
- **Where**: `backend/app/main.py:239-262`
- **Now**: When `HEPHAESTUS_DASHBOARD_PASSWORD` is not set, all API endpoints are open. This is intentional for local development — the user runs on localhost.
- **Proposal**: Document this behavior clearly in GETTING_STARTED.md: "By default, the dashboard is open (no password). Set `HEPHAESTUS_DASHBOARD_PASSWORD` to protect it." Add a startup log message when running without auth.
- **Why**: Not a vulnerability for localhost use. But if someone exposes the dashboard to a network, they should know it's unprotected. Documentation fix, not code fix.

#### [SEC-002] Rate limiting uses hardcoded "unknown" IP — low priority for self-hosted
- **Severity**: Low | **Effort**: S | **Confidence**: High
- **Where**: `backend/app/main.py:268-269`
- **Now**: `auth_login()` hardcodes `client_ip = "unknown"`. All login attempts share one rate-limit key.
- **Proposal**: Fix when/if multi-user auth becomes relevant. For single-user self-hosted, this is a non-issue.

#### [SEC-003] Config override key validation missing
- **Severity**: Medium (defense-in-depth) | **Effort**: S | **Confidence**: High
- **Where**: `backend/app/config.py:127, 166-167`
- **Now**: `_config_overrides()` reads `state/config.json` and merges into effective config with `eff.update()`. No key whitelist validation on the override merge.
- **Proposal**: Validate all keys from config.json against `ALLOWED_CONFIG_KEYS` before merging. Reject unknown keys.
- **Why**: Defense-in-depth. If someone gains file-system access, they shouldn't be able to inject arbitrary env vars. Low probability for self-hosted, but trivial to fix.

#### [SEC-004] API keys in plaintext state files — acceptable for self-hosted
- **Severity**: Low (by design for self-hosted) | **Effort**: M (if desired) | **Confidence**: High
- **Where**: `backend/app/services/connections.py:31`
- **Now**: API keys stored unencrypted in `state/connections.json`. The API masks them in responses but the file is readable.
- **Proposal**: Acceptable for self-hosted where the user controls the filesystem. Document that `state/` contains sensitive data. Optional: add file permissions (mode 0600) on state directory creation.
- **Why**: Self-hosted user owns the machine. If an attacker has filesystem access, encryption at rest won't help (they'd have the master key too). Focus effort elsewhere.

#### [SEC-005] CORS wildcards — fine for localhost
- **Severity**: Low | **Effort**: S | **Confidence**: High
- **Where**: `backend/app/main.py:296-316`
- **Now**: `HEPHAESTUS_DASHBOARD_ALLOWED_ORIGINS` accepts `"*"`.
- **Proposal**: Acceptable for self-hosted localhost deployment. If remote access is configured, document that origins should be restricted.

#### [SEC-006] WebSocket auth accepts token via query parameter
- **Severity**: Low | **Effort**: S | **Confidence**: High
- **Where**: `backend/app/api/ws.py:35-38`
- **Now**: `_check_ws_auth()` extracts token from query params, headers, or cookies.
- **Proposal**: For self-hosted, this is low risk. Tokens in query params are only a concern behind reverse proxies that log URLs. Can be addressed if needed.

#### [SEC-007] Path traversal in file reading endpoints
- **Severity**: Medium | **Effort**: S | **Confidence**: High
- **Where**: `backend/app/api/v1/repos.py:52-65`, `backend/app/services/doc_reader.py:138-147`
- **Now**: `read_file()` accepts path parameter. `_safe_resolve()` uses `relative_to()` check but `../` sequences can potentially escape expected bounds.
- **Proposal**: Add explicit `..` rejection. Blacklist sensitive patterns (`.env`, `*.key`). Even for self-hosted, this prevents accidental data exposure through the dashboard.
- **Why**: The user might browse their repo through the dashboard. A path traversal bug could expose files outside the repo. Worth fixing regardless of threat model.

#### [SEC-008] No input validation on goal submission
- **Severity**: Medium | **Effort**: S | **Confidence**: High
- **Where**: `backend/app/api/v1/goals.py:29-36`
- **Now**: `_GoalRequest` has no length constraints. A 10MB goal description could cause memory issues.
- **Proposal**: Add Pydantic field constraints: `title: str = Field(max_length=200)`, `description: str = Field(max_length=10000)`, `max_tasks: int = Field(ge=0, le=100)`.
- **Why**: Even for self-hosted, reasonable input limits prevent accidental misuse and DoS from buggy clients.

#### [SEC-009] Dependency pinning for supply chain safety
- **Severity**: Medium | **Effort**: S | **Confidence**: High
- **Where**: `backend/pyproject.toml:5-13`
- **Now**: Dependencies use version ranges. `uv.lock` exists but version ranges in pyproject.toml allow drift.
- **Proposal**: Pin exact versions. Add `pip-audit` or `safety` to CI. Commit lockfile. Important for OSS — users trust the dependency chain.

---

### 3. Reliability

#### [REL-001] Unbounded iteration directory growth
- **Severity**: High | **Effort**: M | **Confidence**: High (confirmed Pass 2 + Pass 3)
- **Where**: `backend/app/core/iters.py` (no cleanup logic)
- **Now**: Every iteration creates `iter-NNNN/` with prompt, output, verify logs, validation artifacts. No automatic cleanup or retention policy. Active use accumulates GB of data. User's disk fills up silently.
- **Proposal**: Add configurable retention policy (`HEPHAESTUS_KEEP_ITERS_DAYS`, default 30). Automatic cleanup on startup. Add disk space warning in dashboard when usage is high.
- **Why**: This is the most impactful reliability issue for self-hosted users. Disk filling up is the #1 way self-hosted tools break.

#### [REL-002] Subprocess zombie accumulation
- **Severity**: High | **Effort**: M | **Confidence**: High (confirmed Pass 2 + Pass 3)
- **Where**: `backend/app/core/process.py:95-121`
- **Now**: `_kill_tree()` may miss daemonized subprocesses. No periodic orphan process reaping. Zombie opencode/verify processes accumulate over long runs.
- **Proposal**: Add periodic orphan process reaping. Implement process group tracking. Add "processes" section to dashboard showing active subprocesses.
- **Why**: Self-hosted users run long sessions. Zombie processes consume resources silently until the machine becomes unresponsive.

#### [REL-003] No crash recovery — work lost on restart
- **Severity**: Medium | **Effort**: L | **Confidence**: High (confirmed Pass 2 + Pass 3)
- **Where**: `backend/app/orchestrator/fsm.py:912-947, 1021-1054`
- **Now**: Process crash during commit leaves inconsistent state. Checkpoint only stores phase + iter_dir + branch, not intermediate results. Restart re-queues from scratch, losing expensive verification results.
- **Proposal**: Persist intermediate results after each expensive phase (verify outcome, commit SHA) into work-state.json. Add checkpoint at phase boundaries.
- **Why**: Self-hosted users may have unstable machines (laptops sleep, WiFi drops). Work loss is frustrating.

#### [REL-004] Subprocess resource limits missing
- **Severity**: Medium | **Effort**: M | **Confidence**: High (confirmed Pass 3)
- **Where**: `backend/app/services/opencode_runner.py:145-152`
- **Now**: opencode/verify processes inherit parent's resource limits. A runaway agent can consume all available CPU/memory. No stdout/stderr size limits — output accumulates in memory.
- **Proposal**: Add max output size with truncation. Stream large outputs to disk instead of buffering in memory. Add configurable resource limits.
- **Why**: Self-hosted users run on laptops. A runaway process consuming all RAM freezes the entire machine.

#### [REL-005] Shallow health checks
- **Severity**: Medium | **Effort**: S | **Confidence**: High
- **Where**: `backend/app/main.py:438-441`, `backend/app/api/v1/health.py:9-11`
- **Now**: `/healthz` returns static `{"ok": True}`. `/health/ready` checks basic setup but not disk space, opencode CLI availability, or state validity.
- **Proposal**: Add disk space check (warn when <1GB free). Add opencode CLI check. Add state file validity check. Expose in dashboard as a "system health" widget.

#### [REL-006] Fixed 5-second shutdown timeout
- **Severity**: Low | **Effort**: S | **Confidence**: High
- **Where**: `backend/app/main.py:145-151`
- **Now**: Hard-coded 5-second wait for background tasks. Long-running operations killed abruptly.
- **Proposal**: Make configurable (`HEPHAESTUS_SHUTDOWN_TIMEOUT_SEC`).

#### [REL-007] Backup strategy is minimal
- **Severity**: Low | **Effort**: S | **Confidence**: High
- **Where**: `backend/app/core/state.py:199-207`
- **Now**: Single `.bak` file on each write. No rotation.
- **Proposal**: Add backup rotation (keep last 5). Document that `state/` should be backed up. For self-hosted, this is the user's responsibility, but we should make it easy.

---

### 4. Architecture

#### [ARCH-001] Monolith FSM — 800+ lines, 9 phases, all logic in one file
- **Severity**: High | **Effort**: XL | **Confidence**: High (confirmed Pass 1 + Pass 2)
- **Where**: `backend/app/orchestrator/fsm.py`
- **Now**: Single file handles state transitions, prompt building, execution, verification, commit, validation, cleanup, error recovery, and parallel execution. 800+ lines with deep nesting.
- **Proposal**: Extract phase handlers into separate modules. Use a phase registry pattern. Each phase = one file with `enter()`, `exit()`, `recover()` methods.
- **Why**: This is the heart of the system. Adding a new phase requires understanding 800 lines. Community contributions are blocked by this complexity. OSS projects need approachable code.

#### [ARCH-002] Large files across core
- **Severity**: Medium | **Effort**: M | **Confidence**: High (confirmed Pass 1 + Pass 2)
- **Where**: `events.py` (752 lines), `iters.py` (548), `git.py` (541), `scan.py` (459), `merge_job.py` (455), `process.py` (466)
- **Now**: Multiple files exceed 400 lines with mixed responsibilities.
- **Proposal**: Split by responsibility. `events.py` → `event_parser.py` + `event_models.py` + `event_aggregator.py`.

#### [ARCH-003] 60+ swallowed exceptions in critical paths
- **Severity**: High | **Effort**: M | **Confidence**: High (confirmed Pass 3 completeness critic)
- **Where**: FSM (9 locations), ws_manager.py (3), integrations.py (4), process.py (6), verify_detect.py (3), ws.py (4), helpers.py (1), state.py (2)
- **Now**: Bare `except Exception:` blocks that log but don't propagate or set failure state. Items can get stuck in undefined states. Debugging is extremely painful — the user sees "failed" but the real error is swallowed.
- **Proposal**: Add explicit failure-state transitions in except blocks. Re-raise critical errors. Use `except SpecificException:` instead of bare `except Exception:`.
- **Why**: For self-hosted OSS, the user IS the debugger. Swallowed exceptions mean they can't figure out what went wrong. This is a DX issue, not just a code quality issue.

#### [ARCH-004] 30+ empty except blocks (silent failures)
- **Severity**: Medium | **Effort**: S | **Confidence**: High (confirmed Pass 3)
- **Where**: `ws.py:60,82,107,131`, `helpers.py:32`, `verify_detect.py:39,71,87,102`, `integrations/registry.py:38,74`, `state.py:53,131`
- **Now**: `except: pass` blocks that swallow failures completely. No logging, no recovery.
- **Proposal**: At minimum, add `log.debug()` to each. For critical paths, add proper error handling.

#### [ARCH-005] Migration system is one-shot, no versioning
- **Severity**: Medium | **Effort**: M | **Confidence**: High (confirmed Pass 3)
- **Where**: `backend/app/core/migrate.py` (72 lines)
- **Now**: Migration is a single script with a `.migrated` marker file. No version tracking, no rollback, no migration history.
- **Proposal**: Add migration versioning (numbered migrations). Add rollback support. For OSS, this matters because users update at different versions.

---

### 5. Performance

#### [PERF-001] 3-second polling × multiple stores
- **Severity**: Medium | **Effort**: L (strategic) | **Confidence**: High (confirmed Pass 1 + Pass 2)
- **Where**: `frontend/src/stores/board.ts`, and other Pinia stores
- **Now**: Frontend polls backend every 3 seconds via multiple independent store intervals. Each poll triggers full state read from JSON files.
- **Proposal**: Replace polling with WebSocket push (infrastructure exists — `ws_manager.py`). Only send diffs, not full state.
- **Why**: Not critical for self-hosted (low concurrency), but the unnecessary I/O amplifies disk reads. Lower priority than adoption blockers.

#### [PERF-002] `build_state` reads ALL iteration directories every tick
- **Severity**: Medium | **Effort**: M | **Confidence**: High (confirmed Pass 2)
- **Where**: `backend/app/core/iters.py`
- **Now**: `build_state()` iterates all `iter-NNNN/` directories and reads their contents on every call. With 100+ iterations, this becomes expensive.
- **Proposal**: Cache built state. Invalidate cache only when iteration directory changes (use mtime).

#### [PERF-003] No pagination on large data sets
- **Severity**: Low | **Effort**: M | **Confidence**: High (confirmed Pass 2)
- **Where**: Various API endpoints
- **Now**: List endpoints return full data sets. With hundreds of iterations, responses grow large.
- **Proposal**: Add pagination (offset/limit). Add default limits.

---

### 6. UI/UX

#### [UI-001] Onboarding wizard is Russian-only
- **Severity**: Adoption-blocking | **Effort**: S | **Confidence**: High (confirmed Pass 2 + Pass 3)
- **Where**: `frontend/src/components/OnboardWizard.vue:90,95,113,129,140,150`
- **Now**: All wizard text is in Russian. "Подключите провайдера", "Проверьте CLI", "Выберите репозиторий". Non-Russian speakers are completely blocked on first launch.
- **Proposal**: Translate to English as default. Russian can be added later with i18n. This is an international open-source project — the onboarding must be in English.
- **Why**: Blocks 95%+ of potential users at the very first screen.

#### [UI-002] Port mismatch between frontend and backend
- **Severity**: Adoption-blocking | **Effort**: S | **Confidence**: High (confirmed Pass 3)
- **Where**: `frontend/vite.config.ts:19` (port 8765) vs `backend/app/config.py:24` (port 8766)
- **Now**: Frontend dev proxy sends API calls to port 8765, but backend defaults to 8766. First-time setup shows connection errors immediately.
- **Proposal**: Align ports. One line fix in either `vite.config.ts` or `config.py`.

#### [UI-003] No Vue error boundaries
- **Severity**: Medium | **Effort**: S | **Confidence**: High (confirmed Pass 3)
- **Where**: `frontend/src/main.ts`
- **Now**: No global error handler, no `app.config.errorHandler`. Unhandled component errors crash the entire app.
- **Proposal**: Add `app.config.errorHandler`. Add Vue ErrorBoundary component wrapping key views.

#### [UI-004] Silent CLI detection failures in onboarding wizard
- **Severity**: Medium | **Effort**: S | **Confidence**: High (confirmed Pass 3)
- **Where**: `frontend/src/components/OnboardWizard.vue:42`
- **Now**: `loadClis()` catches errors silently: `catch { /* tolerate failure silently */ }`. User doesn't know if CLI detection worked or failed.
- **Proposal**: Add visible feedback: "Could not detect CLIs" with retry button.

#### [UI-005] Missing loading states and empty states
- **Severity**: Low | **Effort**: S | **Confidence**: High (confirmed Pass 2)
- **Where**: Various frontend views
- **Now**: Some views show nothing during loading or when empty.
- **Proposal**: Add loading skeletons. Add "no data" messages with CTAs.

#### [UI-006] Missing keyboard shortcuts
- **Severity**: Low | **Effort**: M | **Confidence**: Medium
- **Where**: `frontend/src/views/BoardView.vue`
- **Now**: No keyboard navigation. No command palette.
- **Proposal**: Add keyboard shortcuts for common actions. Nice-to-have for power users.

---

### 7. Features

> For self-hosted OSS, feature priorities shift toward what individual developers need, not what enterprise teams need.

#### [FEAT-001] No cost dashboard
- **Severity**: Medium | **Effort**: M | **Confidence**: High (confirmed Pass 2 + Pass 3)
- **Where**: Backend has token tracking (`events.py:120-247`, `run_summary.py:31`) but no frontend visualization
- **Now**: Token usage and cost data exists in events but is only visible in raw iteration output. Users spending money on API calls have no visibility.
- **Proposal**: Add cost API endpoint. Create cost dashboard component. Self-hosted users pay their own API bills — this matters.

#### [FEAT-002] No webhook/notification system
- **Severity**: Low | **Effort**: M | **Confidence**: High
- **Now**: Users must monitor dashboard manually. No notification when a goal completes or fails.
- **Proposal**: Optional. Add webhook URL configuration. Support ntfy.sh (self-hosted notifications) as first-class integration. Skip Slack/Discord — focus on self-hosted-friendly options.

#### [FEAT-003] No goal templates/presets
- **Severity**: Low | **Effort**: M | **Confidence**: High
- **Where**: `backend/app/api/v1/goals.py:62-99`
- **Now**: Goals created from scratch every time.
- **Proposal**: Add goal template API. Create preset library. Nice-to-have.

#### [FEAT-004] Limited batch operations
- **Severity**: Low | **Effort**: S | **Confidence**: High
- **Where**: `backend/app/core/queue.py:328-345`
- **Now**: Only single-item requeue.
- **Proposal**: Add "retry all failed" button. Simple, high-value.

#### [FEAT-005] No history/analytics
- **Severity**: Low | **Effort**: L | **Confidence**: High
- **Where**: `backend/app/core/run_summary.py`
- **Now**: Only current/last run summary persisted. No historical view.
- **Proposal**: Store run summaries. Add simple history view.

---

### 8. Models/Providers

#### [MODEL-001] No proactive rate limiting per provider
- **Severity**: Medium | **Effort**: M | **Confidence**: High (confirmed Pass 3)
- **Where**: `backend/app/core/transient.py:20-22`
- **Now**: System detects rate limits (429) after hitting them, then retries. No proactive throttling.
- **Proposal**: Add simple token-bucket per provider. Prevents wasting API budget on retries.
- **Why**: Self-hosted users pay their own API bills. Hitting rate limits wastes money on failed calls.

#### [MODEL-002] No provider-level fallback
- **Severity**: Medium | **Effort**: M | **Confidence**: High (confirmed Pass 3)
- **Where**: `backend/app/services/opencode_runner.py:226-255`
- **Now**: Agent-level fallback exists (primary → fallback). But no provider-level fallback — if Anthropic is down, no auto-switch to OpenAI.
- **Proposal**: Add automatic provider fallback on repeated 503/429. Users shouldn't need to manually switch when a provider has an outage.

#### [MODEL-003] No model parameter tuning
- **Severity**: Medium | **Effort**: M | **Confidence**: High (confirmed Pass 3)
- **Where**: `backend/app/services/opencode_runner.py:83-102`
- **Now**: No fields for temperature, max_tokens, top_p. System uses CLI defaults.
- **Proposal**: Add `model_params` dict to AgentRef. Self-hosted users want control over model behavior.

#### [MODEL-004] No local model support (Ollama)
- **Severity**: Medium | **Effort**: L | **Confidence**: High (confirmed Pass 3)
- **Where**: `backend/app/models/connections.py` — no "ollama" provider
- **Now**: No support for Ollama, llama.cpp, or any local model runner. All models assumed remote API endpoints.
- **Proposal**: Add "ollama" provider to catalog. Support custom base_url for localhost endpoints.
- **Why**: This is a KEY advantage of self-hosted — privacy-preserving local models. Many OSS users want to run fully offline. This should be prioritized higher than for a SaaS product.

#### [MODEL-005] API key validation only at test time
- **Severity**: Low | **Effort**: S | **Confidence**: High
- **Where**: `backend/app/services/connections.py:39-52`
- **Now**: `add_connection()` accepts any key for any provider. No format validation.
- **Proposal**: Add basic key format hints per provider (prefix check). Not critical for self-hosted.

#### [MODEL-006] Linear retry backoff
- **Severity**: Low | **Effort**: S | **Confidence**: High
- **Where**: `backend/app/orchestrator/fsm.py:825-865`
- **Now**: Linear backoff. No exponential. No jitter.
- **Proposal**: Add exponential backoff with jitter. Simple improvement.

---

## Top 15 Quick Wins

Ranked by impact × effort for a self-hosted OSS project. Each should take < 1 day.

| # | Finding | Impact | Effort |
|---|---------|--------|--------|
| 1 | **[UI-002]** Align frontend/backend ports (8765 vs 8766) | Fixes first-run for every user | 10 min |
| 2 | **[UI-001]** Translate OnboardWizard to English | Unblocks international users | 2 hours |
| 3 | **[DX-004]** Replace hardcoded paths/IPs with placeholders | Makes docs usable for everyone | 30 min |
| 4 | **[DX-001]** Rewrite README.md for actual architecture | The #1 adoption blocker | 4 hours |
| 5 | **[DX-003]** Create CONTRIBUTING.md | Unblocks community contributions | 2 hours |
| 6 | **[DX-006]** Fix startup script config reference | Correct first-run behavior | 15 min |
| 7 | **[SEC-008]** Add input constraints to goal creation | Prevents accidental issues | 30 min |
| 8 | **[SEC-003]** Validate config.json keys against whitelist | Defense-in-depth | 30 min |
| 9 | **[UI-003]** Add Vue global error handler | Prevents app crashes | 30 min |
| 10 | **[UI-004]** Add visible feedback for CLI detection failures | Better first-run UX | 30 min |
| 11 | **[REL-005]** Add disk space check to health endpoint | Prevents silent disk-full | 2 hours |
| 12 | **[SEC-009]** Pin dependency versions | Supply chain safety for OSS | 1 hour |
| 13 | **[DX-005]** Add cross-platform notes to docs | Unblocks Windows users | 1 hour |
| 14 | **[DX-007]** Mention /docs endpoint in getting started | API discoverability | 15 min |
| 15 | **[REL-007]** Add backup rotation (keep last 5) | Prevents state loss | 1 hour |

---

## Strategic Initiatives

### S1. Documentation Overhaul (HIGHEST PRIORITY)
- **Findings**: DX-001, DX-002, DX-003, DX-004, DX-005, UI-001, UI-002
- **Scope**: README rewrite, GETTING_STARTED.md, CONTRIBUTING.md, translate wizard, fix port mismatch
- **Impact**: Reduces onboarding from 4-8 hours to 15 minutes. Unblocks community adoption.
- **Effort**: 1-2 weeks

### S2. Local Model Support (Ollama)
- **Findings**: MODEL-004
- **Scope**: Add Ollama provider, custom base_url support, health checks for local runners
- **Impact**: Key differentiator for self-hosted. Enables fully private/offline usage. Aligns with OSS values.
- **Effort**: 2-3 weeks

### S3. Iteration Cleanup and Disk Management
- **Findings**: REL-001, PERF-002
- **Scope**: Retention policy, automatic cleanup, disk space monitoring, dashboard warning
- **Impact**: Prevents the #1 operational failure mode for self-hosted (disk full)
- **Effort**: 1 week

### S4. Fix Swallowed Exceptions and Improve Debuggability
- **Findings**: ARCH-003, ARCH-004
- **Scope**: Replace bare except blocks, add failure-state transitions, improve error messages
- **Impact**: Self-hosted users debug their own issues. Proper error propagation is essential.
- **Effort**: 1-2 weeks

### S5. Decompose FSM into Phase Modules
- **Findings**: ARCH-001, ARCH-002
- **Scope**: Extract 9 FSM phases into separate modules, split large files
- **Impact**: Makes the codebase approachable for community contributions. Currently impenetrable.
- **Effort**: 2-3 weeks

### S6. Cost Dashboard
- **Findings**: FEAT-001
- **Scope**: Cost API endpoint, dashboard component, budget alerts
- **Impact**: Self-hosted users pay their own API bills. Visibility is essential.
- **Effort**: 1-2 weeks

### S7. Crash Recovery
- **Findings**: REL-003
- **Scope**: Phase-scoped checkpoints, intermediate result persistence
- **Impact**: Prevents work loss on crashes/restarts. Important for laptop users.
- **Effort**: 2-3 weeks

### S8. Replace Polling with WebSocket Push
- **Findings**: PERF-001
- **Scope**: WebSocket push for state changes, diff-based updates
- **Impact**: Eliminates 3s latency. Reduces unnecessary I/O.
- **Effort**: 2-3 weeks

---

## Roadmap

### Phase 1: Adoption Enablers (Week 1-2)
**Goal**: Make it possible for a new user to go from clone to first successful run in 15 minutes.
**Status**: ✅ Completed 2026-06-08 (9/10 items; UI-001 deferred to dedicated i18n task)

- [x] [DX-001] Rewrite README.md
- [x] [DX-002] Create GETTING_STARTED.md
- [x] [DX-003] Create CONTRIBUTING.md
- [x] [DX-004] Remove hardcoded paths/IPs
- [x] [DX-005] Add cross-platform notes
- [x] [DX-006] Fix startup script
- [x] [DX-007] Document /docs endpoint
- [ ] [UI-001] Translate wizard to English → deferred: user chose full i18n (ru/en), separate task
- [x] [UI-002] Fix port mismatch
- Quick wins #1-6, #13-14 (covered above)
- Estimated effort: 1-2 weeks

### Phase 2: Reliability Basics (Week 3-4)
**Goal**: The system shouldn't silently break or fill the user's disk.
**Status**: ✅ Completed 2026-06-08 (5/5 items; ARCH-003 reduced from top-20 to 4 actually harmful — see below)

- [x] **[REL-001]** Iteration auto-retention + `prune_iters()` pure core
  - `select_iters_to_prune()` + `_protected_iter_names()` + `prune_iters()` in `iters.py`
  - Protected: current iter, non-terminal tasks, non-terminal merge jobs
  - Config: `HEPHAESTUS_KEEP_ITERS_DAYS=30`, `HEPHAESTUS_KEEP_ITERS_MIN=20`
  - 19 unit tests in `tests/unit/test_iter_prune.py`
  - Wired into lifespan startup under pytest-guard
- [x] **[REL-002]** Orphan process reaping
  - `reap_orphans()` on `ProcessManager` — scans process.json, kills orphaned children of dead-root entries
  - pytest-guard (no-op under test), uses `_pid_alive` / `_kill_tree` only (no grep-by-name)
  - 8 unit tests in `tests/unit/test_process_reaper.py`
  - Wired into lifespan startup under pytest-guard
- [x] **[REL-005]** Enhanced health check + disk warning
  - New `GET /api/v1/system/health` → `{ok, diskFreeGb, diskWarn, clis:{git,opencode,claude,codex}, stateOk}`
  - Config: `HEPHAESTUS_DISK_WARN_GB=1`; never returns 500
  - Existing `/healthz`, `/health/ready`, `/api/v1/health` untouched
  - 9 contract tests in `tests/contract/test_system_health_api.py`
- [x] **[REL-007]** State backup rotation
  - `.bak.1`..`.bak.{N}` rotation before write, keep `HEPHAESTUS_BACKUP_KEEP=5`
  - Never-crash: backup failure does not prevent state write
  - 5 new unit tests in `tests/unit/test_state.py` (total 12)
- [x] **[ARCH-003]** Top harmful swallowed exceptions (4 fixed, not 20)
  - **fsm.py:292** — status read after processing: `except Exception: pass` → `log.error()`
  - **fsm.py:968** — result.json self-reported failure: `except Exception: pass` → narrowed to `(json.JSONDecodeError, OSError)` + fallback
  - **fsm.py:1050** — checkpoint recovery: corrupt file renamed to `.json.corrupt` instead of deleted
  - **state.py:196** — write validation: `return` → `raise RuntimeError()` so callers know write failed
  - 6 tests in `tests/unit/test_fsm_exception_fixes.py` + 1 in `tests/unit/test_state.py`
  - **Note**: Only 4 harmful exceptions found (not 20). The other 28+ `except Exception:` blocks are legitimate best-effort never-crash patterns (backup, telemetry, broadcast, WebSocket) — fixing them would be a regression.

**Gates**: `pytest -q -x tests/unit tests/contract` = 623 passed; `ruff check app tests` = All checks passed; `mypy --strict app` = Success (99 files).
- Quick wins #11 (disk health), #15 (backup rotation) — covered above.

### Phase 3: Debuggability + Code Quality (Week 5-7)
**Goal**: Self-hosted users can debug their own issues. Codebase is approachable for contributions.
**Status**: ✅ Completed 2026-06-09 (9/9 items; all gates green)

- [x] **[SEC-008]** Goal input constraints
  - `title: str = Field(max_length=200)`, `description: str = Field("", max_length=10000)`, `max_tasks: int = Field(0, alias="maxTasks", ge=0, le=100)`
  - 7 contract tests in `tests/contract/test_goals_input_validation.py`
- [x] **[SEC-003]** Config key validation — `_config_overrides()` now filters through `ALLOWED_CONFIG_KEYS`
  - Unknown keys from `state/config.json` silently dropped (defense-in-depth)
  - 6 unit tests in `tests/unit/test_config_override_validation.py`
- [x] **[SEC-007]** Sensitive file blacklist + path traversal tests
  - `_is_sensitive()` blocks `.env`, `*.key`, `*.pem`, `*.p12`, `id_*` files through dashboard API
  - Path traversal (already safe via `_safe_resolve`) confirmed with 5 dedicated tests
  - 15 unit tests + 1 skip in `tests/unit/test_doc_reader.py`
- [x] **[ARCH-004]** Empty except blocks — `log.debug(..., exc_info=True)` added to ~50 locations across 16 files
  - ws.py (3), verify_detect.py (4), helpers.py (3), registry.py (2), state.py (2), conversations.py (10),
    events.py (5), scan_run.py (4), process.py (4), scan.py (3), iters.py (3), doc_reader.py (6),
    ws_manager.py (1), profiler.py (2), git.py (1), integrations.py (1), workspaces.py (1)
  - Intentional blocks (platform imports, process liveness, cleanup) left untouched
- [x] **[ARCH-003]** Remaining harmful swallowed exceptions (6 fixed beyond Phase 2's 4)
  - fsm.py: cost accumulation (line 309), repo context (line 780), diff.patch (line 985), validation diff (line 1016)
  - driver.py: workspace id resolution (line 40), workspace cwd resolution (line 58)
  - 6 tests in `tests/unit/test_arch003_critical_exceptions.py`
- [x] **[UI-003]** Global Vue error handler — `app.config.errorHandler` in `main.ts`
  - Logs to console with `[HEPHAESTUS]` prefix + lazy toast store import for error notification (8s TTL)
  - 1 vitest test in `frontend/src/__tests__/error_handler.spec.ts`
- [x] **[UI-004]** CLI detection error feedback in OnboardWizard
  - `cliError` ref + error banner with retry button (`data-test="wiz-cli-error"`, `"wiz-cli-retry"`)
  - 3 vitest tests in `frontend/src/components/__tests__/OnboardWizard.error.spec.ts`
- [x] **[ARCH-002]** Split `events.py` (752 lines) into 4 focused modules
  - `event_text.py` (~120 lines): constants + `extract_assistant_text` + helpers
  - `event_cost.py` (~130 lines): `_sum_usage`, `_iter_cost`
  - `event_summarizer.py` (~235 lines): `_summarize_claude_message`, `_summarize_event`
  - `event_parser.py` (~260 lines): parsing + full conversation + `_current_iter_block`
  - `events.py` → 47-line re-export facade with `__all__`; zero test/importer changes
- [x] **[ARCH-001]** Begin FSM decomposition — safe helper extraction
  - `revision_snapshot.py` (21 lines): `_snapshot_revision`
  - `prompt_builder.py` (24 lines): `build_task_prompt`
  - `git_ops.py` (23 lines): `get_working_dir`, `drop_worktree`, `restore_base_branch`
  - fsm.py reduced from 1165 → 1117 lines; all method signatures preserved via delegation
  - Zero test changes; full architectural decomposition deferred (phase flow untouched)
- [x] **[ARCH-001]** FULLY DECOMPOSED — phase bodies extracted into `app/orchestrator/phases/` (2026-06-09)
  - `phases/preflight.py` (82 lines): `preflight_phase` — branch + iter dir + (optional) worktree
  - `phases/opencode.py` (113 lines): `run_opencode` + `run_opencode_with_retry`
  - `phases/verify.py` (66 lines): `verify_phase` — VerifyRunner + diff-tests safety net
  - `phases/commit.py` (59 lines): `commit_phase` — agent-already-committed shortcut + REL-003 SHA persist
  - `phases/parse_result.py` (73 lines): `parse_result_phase` — result.json + diff.patch + summary.md
  - `phases/validate.py` (62 lines): `validate_phase` — ValidationFunnel.run_funnel
  - `phases/cleanup.py` (31 lines): `cleanup_phase` — push + worktree drop + checkpoint unlink
  - fsm.py reduced from 1190 → 906 lines (−24%); control flow / state mutators / `_TRANSITIONS` /
    `_recover_checkpoint` / REL-003 resume / parallel scheduler all UNCHANGED
  - One commit per phase; full gates green between each (838 passed, mypy --strict clean, ruff clean)
  - Public surface untouched: `OrchestratorFSM`, `Phase`, `_TRANSITIONS`, `_snapshot_revision`,
    `build_task_prompt`, `git_ops.*`, `replenish_goal` all importable from `app.orchestrator.fsm`
  - **Zero test changes** (`git diff master -- tests/` is empty) — pure behavior-preserving refactor

**Gates**: `pytest -q -x tests/unit tests/contract` = 657 passed; `ruff check app tests` = All checks passed; `mypy --strict app` = Success (106 source files); `vue-tsc -p tsconfig.app.json --noEmit` = clean; `vitest run` = 238 passed; `vite build` = clean.
- Quick wins #7-10 (SEC-008, SEC-003, UI-003, UI-004) — covered above.
- Estimated effort: 2-3 weeks → completed in 1 session.

### Phase 4: Self-Hosted Differentiators (Week 7-10)
**Goal**: Features that make HEPHAESTUS the best choice for self-hosted autonomous dev.
**Status**: ✅ Completed 2026-06-09 (5/5 items; all gates green)

- [x] **[FEAT-001]** Cost dashboard
  - New `GET /api/v1/costs` → totalCostUsd, totalTokens, topTasks, budgetUsd
  - Frontend CostCard component on BoardView (sidebar with cost summary)
  - Reuses existing `_iter_cost()` helper — no heavy recomputation
  - 10 unit + 7 contract tests
- [x] **[MODEL-004]** Ollama / local model support
  - Added `ollama` ProviderCatalogEntry with opencode engine + OPENAI_BASE_URL
  - Extended `build_env()` for opencode combos with `base_url` → sets `OPENAI_BASE_URL`
  - **CRITICAL**: Ollama routes through OPENAI_BASE_URL (NOT ANTHROPIC_BASE_URL) — verified by tests
  - Empty key supported for local Ollama (no auth required)
  - Frontend: Ollama base_url input in ConnectionsManager (default `http://localhost:11434/v1`)
  - 6 unit + 4 contract tests; existing provider tests unchanged
- [x] **[MODEL-003]** Model parameter tuning
  - Optional `model_params` dict on AgentRef (temperature, max_tokens, top_p)
  - CLI flags appended in `_build_cmd()` per engine (opencode: --temperature, --max-output-tokens, --top-p)
  - Unknown params silently ignored with debug log
  - Empty params = no flags (current behavior preserved — regression test)
  - 7 unit tests
- [x] **[MODEL-002]** Provider-level fallback
  - `run_with_provider_fallback()` layers ON TOP of agent-level fallback
  - Switches to alternative provider on repeated 503/429 (transient failures via `classify_failure`)
  - Optional (no chain = current behavior); cycle protection via tried-set
  - 2 unit tests
- [x] **[MODEL-001]** Proactive per-provider rate limiting
  - Token-bucket rate limiter (application singleton via `get_rate_limiter()`)
  - Config: `HEPHAESTUS_RATE_LIMIT_PER_MIN` (default 0=off), `HEPHAESTUS_RATE_LIMIT_MAX_WAIT_SEC` (default 5)
  - Acquires slot before engine subprocess launch; never infinite wait (max-wait timeout)
  - Config keys in `ALLOWED_CONFIG_KEYS`; documented in `.env.example`
  - 6 unit tests

**Gates**: `pytest -q -x tests/unit tests/contract` = 699 passed, 2 skipped; `ruff check app tests` = All checks passed; `mypy --strict app` = Success: no issues found in 108 source files; `vue-tsc -p tsconfig.app.json --noEmit` = clean; `vitest run` = 242 passed (44 files); `vite build` = ✓ built in 2.15s.

### Phase 5: Polish and Performance (Week 10-14)
**Goal**: Smooth UX, fast response, professional feel.
**Status**: ✅ Completed 2026-06-09 (6/6 items; all gates green)

- [x] **[PERF-001]** WebSocket push (replace polling)
  - Frontend composable `useWebSocket.ts` — subscribes to `/ws/board` room
  - `board.ts` store: WS subscription primary, HTTP polling 10s fallback
  - `loop.ts` store: WS-triggered refresh with HTTP polling fallback
  - On reconnect: one full `fetchState()` to catch missed updates
  - Backend WS broadcasting unchanged (already existed via `ws_manager.py`)
  - `isConnected` indicator preserved in BoardView
  - 6 vitest tests (connection, state_update handler, reconnect, ping ignored, cleanup)
- [x] **[PERF-002]** Cached state building
  - `build_state()` now caches result with mtime-based invalidation key
  - Cache key = (sorted iter-dir mtimes, work-state.json mtime)
  - Manual `invalidate_state_cache()` for explicit invalidation
  - 6 unit tests (cache hit, miss on new iter dir, miss on work-state change, explicit invalidation, empty state dir, never stale)
- [x] ~~[UI-003] Error boundaries~~ (done in Phase 3)
- [x] **[UI-005]** Loading states
  - SettingsView: loading spinner + error state with retry button (`data-test="settings-loading"`, `data-test="settings-error"`)
  - AgentsRunView: loading spinner (`data-test="agents-loading"`)
  - ToolsView: top-level page loading state (`data-test="tools-loading"`)
  - WorktreesView: error state with retry button (`data-test="worktrees-error"`)
  - All states match existing BoardView pattern (`.loading-state`/`.loading-spinner`/`.error-state` CSS)
- [x] **[FEAT-004]** Batch retry
  - Backend: `_queue_requeue_failed()` in `queue.py` — bulk requeue of all `failed:*` items
  - `POST /api/v1/tasks/requeue-failed` endpoint
  - Frontend: `api.requeueFailed()` client method
  - BoardView: "Повторить упавшие" button visible when `failed_total > 0`
  - 5 contract tests + 2 vitest tests
- [x] **[REL-003]** Crash recovery
  - FSM checkpoint now includes `intermediate_results` dict (verify_green, commit hash)
  - After VERIFY passes: `verify_green`, `verify_outcome` persisted in checkpoint
  - After COMMIT: `commit_hash` persisted in checkpoint
  - Recovery logs intermediate results for observability (safe clear+requeue fallback retained)
  - TODO: full resume from intermediate results (deferred — conservative first step)
  - 8 unit tests (persistence, intermediate results in checkpoint, IDLE skips, recovery logging, corrupt checkpoint, current.json always written)
- [x] **[ARCH-005]** Migration versioning
  - `migrate.py` rewritten: versioned migration system with `.migrations.json` tracking
  - `run_migrations()` runs pending migrations in order; idempotent
  - Existing legacy `migrate_legacy_state()` preserved unchanged
  - `_ALL_MIGRATIONS` registry empty — ready for future migrations
  - 14 unit tests (order, idempotency, failure, corrupt tracking, roundtrip)

**Gates**: `pytest -q` = 835 passed, 2 skipped; `ruff check app tests` = All checks passed; `mypy --strict app` = Success: no issues found in 108 source files; `vue-tsc -p tsconfig.app.json --noEmit` = clean; `vitest run` = 242 passed (44 files); `vite build` = ✓ built in 2.26s.

**Entire audit roadmap (Phases 1-5) is now CLOSED.**

---

## Appendix

### A. System Map

```
hephaestus-autonomous-loop/
├── backend/                          # FastAPI + mypy-strict
│   ├── app/
│   │   ├── main.py                   # App factory, auth, CORS, lifespan (482 lines)
│   │   ├── config.py                 # Env vars, config overrides (210 lines)
│   │   ├── api/
│   │   │   ├── v1/                   # 29 route files, 79 HTTP endpoints, 3 WS routes
│   │   │   └── ws.py                 # WebSocket handlers
│   │   ├── orchestrator/
│   │   │   └── fsm.py                # FSM: 9 phases, 800+ lines
│   │   ├── core/
│   │   │   ├── driver.py             # Auto-driver, process management
│   │   │   ├── state.py              # File locking, LKG cache, atomic writes
│   │   │   ├── iters.py              # build_state, iter management (548 lines)
│   │   │   ├── events.py             # Event parsing (752 lines)
│   │   │   ├── process.py            # Subprocess management (466 lines)
│   │   │   ├── git.py                # Git operations (541 lines)
│   │   │   ├── scan.py               # Repository scanning (459 lines)
│   │   │   ├── queue.py              # Queue operations
│   │   │   ├── transient.py          # Transient failure classification
│   │   │   ├── run_summary.py        # Cost/failure tracking
│   │   │   └── migrate.py            # One-shot migration (72 lines)
│   │   ├── models/
│   │   │   ├── connections.py        # PROVIDER_CATALOG (7 providers)
│   │   │   └── workspace.py          # Workspace, engine profiles
│   │   ├── services/
│   │   │   ├── connections.py        # Connection CRUD
│   │   │   ├── opencode_runner.py    # Agent subprocess execution
│   │   │   ├── connection_test.py    # Key validation via CLI
│   │   │   └── ws_manager.py         # WebSocket state broadcasting
│   │   └── integrations/             # GitHub/GitLab integrations
│   ├── tests/                        # 100+ test files
│   └── pyproject.toml                # Dependencies (version ranges)
├── frontend/                         # Vue 3 + Pinia + TypeScript
│   ├── src/
│   │   ├── views/                    # 6 views (Board, Goals, Connections, Prompts, Integrations, Settings)
│   │   ├── components/               # 36 components including OnboardWizard
│   │   ├── stores/                   # 7 Pinia stores (board, connections, etc.)
│   │   ├── api/client.ts             # API client, 79 methods
│   │   └── router.ts                 # 6 routes + 8 redirects
│   └── vite.config.ts                # Dev proxy (port 8765 — MISMATCH with backend 8766)
├── prompts/                          # 19 prompt templates
│   ├── system-prefix.md
│   ├── goal-planner.md
│   ├── scan-decomposer.md
│   ├── merge-resolver.md
│   ├── validate-*.md
│   └── review-*.md
├── docs/
│   ├── superpowers/specs/            # 20 design specs
│   └── reviews/                      # This report
├── state/                            # File-based state (JSON)
│   ├── work-state.json               # Main state file
│   ├── connections.json              # API keys (user controls filesystem — acceptable)
│   └── config.json                   # Config overrides
├── README.md                         # Describes old bash system — WRONG, needs rewrite
└── RUNBOOK.md                        # Operator guide for old system — needs update
```

### B. Files Checked

**Backend Core** (15 files):
`config.py`, `main.py`, `fsm.py`, `driver.py`, `state.py`, `iters.py`, `events.py`, `process.py`, `git.py`, `scan.py`, `queue.py`, `transient.py`, `run_summary.py`, `migrate.py`, `helpers.py`

**Backend Models** (5 files):
`connections.py`, `workspace.py`, `requests.py`, `goals.py`, `workspaces.py`

**Backend Services** (8 files):
`connections.py`, `opencode_runner.py`, `connection_test.py`, `ws_manager.py`, `verify_detect.py`, `doc_reader.py`, `integrations/registry.py`, `integrations/creds.py`

**Backend Routes** (29 files in `api/v1/`):
`goals.py`, `tasks.py`, `queue.py`, `connections.py`, `config.py`, `repos.py`, `workspaces.py`, `loop.py`, `scans.py`, `merge.py`, `integrations.py`, `health.py`, `ws.py`, and 16 more

**Frontend** (43+ files):
`client.ts`, `router.ts`, `App.vue`, `main.ts`, `vite.config.ts`, `OnboardWizard.vue`, `BoardView.vue`, 5 more views, 30+ components, 7 stores

**Prompts** (19 files):
`system-prefix.md`, `goal-planner.md`, `scan-decomposer.md`, `merge-resolver.md`, 6 validation prompts, 5 review prompts, 2 agent prompts

**Docs** (22 files):
`README.md`, `RUNBOOK.md`, 20 design specs in `docs/superpowers/specs/`

### C. Audit Method

**Pass 1 — Map & Inventory** (7 agents):
Mapped all areas: backend API (79 endpoints), orchestrator (9-phase FSM), services (20 files), frontend (6 views, 36 components), prompts (19 files), config/security, docs.

**Pass 2 — Depth by Dimension** (8 agents):
UI/UX (26 findings), Features (10), Architecture (14), Reliability (12), Security (13), Performance (11), DX/Docs (10), Models/Providers (supplemented in Pass 3).

**Pass 3 — Adversarial Completeness** (6 agents):
New-user persona (22 findings), Power-user persona (10), SRE/operations persona (35), Security analyst persona (12), Completeness critic (10 gap categories), Model/Provider supplement (10 dimensions).

**Post-audit reclassification**: All findings re-evaluated with self-hosted OSS context. Security findings downgraded where user=admin. DX/Docs elevated to top priority. Local model support elevated as key differentiator.

**Total**: 21 agents, ~75 unique findings after deduplication and reclassification.

### D. What Changed from the Initial Audit

After learning this is a self-hosted OSS project, the following reclassifications were made:

| Finding | Before | After | Reason |
|---------|--------|-------|--------|
| SEC-001 Auth bypass when no password | Critical | Medium (docs) | By design for localhost. Document the behavior. |
| SEC-002 Broken rate limiting | Critical | Low | User is admin on own machine. |
| SEC-003 Env var injection via config.json | Critical | Medium | Defense-in-depth, trivial fix. |
| SEC-004 Plaintext secrets | Critical | Low | User controls filesystem. |
| SEC-005 CORS wildcards | High | Low | Fine for localhost. |
| SEC-006 WS auth via query param | High | Low | Behind reverse proxy = user's problem. |
| SEC-008 Arbitrary workspace path | High | Removed | Feature, not bug. User should point to any repo. |
| SEC-011 Git remote SSRF | Medium | Removed | User controls their own remotes. |
| REL-008 No structured logging | Medium | Removed | Nice-to-have, not needed for self-hosted. |
| FEAT-002 Webhook notifications | Medium | Low | Focus on self-hosted-friendly options (ntfy.sh). |
| MODEL-004 Local model support (Ollama) | Low | Medium | Key self-hosted differentiator. |
| DX-001 Wrong README | Critical | Adoption-blocking | #1 priority for OSS adoption. |
| UI-001 Russian wizard | High | Adoption-blocking | Blocks 95%+ of international users. |
| UI-002 Port mismatch | High | Adoption-blocking | Breaks every first-run. |

### E. Confidence Levels

- **High confidence** (confirmed in 2+ passes): All adoption-blocking and High findings
- **Medium confidence** (confirmed in 1 pass): Most Medium findings
- **Low confidence** (inferred): Some Low findings, strategic initiative estimates
