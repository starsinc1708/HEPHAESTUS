# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.4](https://github.com/starsinc1708/HEPHAESTUS/compare/v1.0.3...v1.0.4) (2026-06-10)


### Bug Fixes

* **prompts:** resolve prompts under LOOP_HOME, not __file__ (fixes Docker validate crash) ([67d512a](https://github.com/starsinc1708/HEPHAESTUS/commit/67d512ae384bad6e98525a33b51fc87672bca889))

## [1.0.3](https://github.com/starsinc1708/HEPHAESTUS/compare/v1.0.2...v1.0.3) (2026-06-10)


### Features

* **verify:** baseline-aware auto-detection (don't gate on a red baseline) ([921df16](https://github.com/starsinc1708/HEPHAESTUS/commit/921df16d54debe5c1532fed9eb39c529157c2003))


### Bug Fixes

* **docker:** trust mounted repos so git works (fixes tasks stuck "queued") ([62ede2c](https://github.com/starsinc1708/HEPHAESTUS/commit/62ede2c4d5c1194639ea48e6b30d91790d1898a2))


### Miscellaneous Chores

* release 1.0.3 ([0061375](https://github.com/starsinc1708/HEPHAESTUS/commit/0061375c3b8a74038d11f27421bcc5cccf798b3d))

## [1.0.2](https://github.com/starsinc1708/HEPHAESTUS/compare/v1.0.1...v1.0.2) (2026-06-09)


### Features

* **settings:** browse-and-pick repository in Settings (reuse RepoPicker) ([d1a3b58](https://github.com/starsinc1708/HEPHAESTUS/commit/d1a3b584750d5daca8d795e9b6cf0bde0837ddcc))


### Miscellaneous Chores

* release 1.0.2 ([f1115bf](https://github.com/starsinc1708/HEPHAESTUS/commit/f1115bffc6346780e9b48881976a30cfbfa149aa))

## [1.0.1](https://github.com/starsinc1708/HEPHAESTUS/compare/v0.1.0...v1.0.1) (2026-06-09)


### Features

* **onboarding:** browse-and-pick repository from the server filesystem ([dc973cd](https://github.com/starsinc1708/HEPHAESTUS/commit/dc973cd3c194271f8311502a7c96ee4e942682a4))


### Bug Fixes

* **onboarding:** show full path in repo picker (correct bidi truncation) ([341600c](https://github.com/starsinc1708/HEPHAESTUS/commit/341600cdfb3a149e86d4780bce66bdd0b63ddf01))

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
