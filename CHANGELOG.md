# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-06-09

First tagged release. HEPHAESTUS is a self-hosted autonomous development loop: define a
goal → it decomposes the goal into tasks, executes each via an AI agent, verifies
the result (typecheck/lint/tests), and merges clean commits — all visible in a live
web dashboard.

### Added
- **Core loop:** goal decomposition, per-task agent execution (opencode / Claude /
  Codex), a map-reduce review funnel (lenses → arbiters → gate), verify gates, and
  branch-isolated commits with an AI-assisted merge flow.
- **Dashboard (Vue 3):** Kanban board with dependency graph, live agent conversation
  view, task drawer (description / iterations / diff / review / checks), run history
  and cost cards, onboarding wizard, settings, tools (scans / ideas / insights),
  agents-and-run, and worktrees views.
- **Bilingual UI (en/ru):** full vue-i18n setup with a language toggle (persisted),
  English fallback, and correct Russian pluralization.
- **Reliability:** crash-recovery checkpoints with resume-from-commit, WebSocket
  state push with polling fallback, rolling iteration retention, and run-history
  persistence.
- **Providers:** connection manager for multiple model providers/engines, optional
  GitHub/GitLab integration (issue import, PR/MR), and optional ntfy.sh notifications.
- **API niceties:** offset/limit pagination on accumulating list endpoints.

### Project / OSS
- MIT license, SECURITY policy with an honest threat model, Code of Conduct, issue/PR
  templates, and Dependabot.
- Multi-stage Docker image + `docker-compose.yml` (build the SPA, serve API + UI).
- CI (GitHub Actions): backend ruff + `mypy --strict app` (platform-pinned) + pytest;
  frontend type-check + build + vitest.

[Unreleased]: https://github.com/starsinc1708/HEPHAESTUS/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/starsinc1708/HEPHAESTUS/releases/tag/v0.1.0
