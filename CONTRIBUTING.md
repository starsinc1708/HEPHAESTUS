# Contributing to HEPHAESTUS

Thank you for your interest in contributing to HEPHAESTUS! This document describes how to set up
a development environment, follow code conventions, and submit changes.

## Development Setup

### Prerequisites

- **Python 3.11+** with [uv](https://docs.astral.sh/uv/)
- **Node.js 18+** with **pnpm 9+**
- **Git** 2.30+
- An AI CLI tool for testing (opencode, Claude Code, or Codex)

### Initial Setup

Follow [GETTING_STARTED.md](GETTING_STARTED.md) for the basic setup, then install dev dependencies:

```bash
# Backend (includes ruff, mypy, pytest)
cd backend
uv sync --extra dev

# Frontend (includes vitest, vue-tsc)
cd frontend
pnpm install
```

### Running in Development Mode

```bash
# Terminal 1 — Backend (auto-reload on changes)
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8766 --reload

# Terminal 2 — Frontend (hot module replacement)
cd frontend
pnpm dev
```

## Code Style

### Backend (Python)

The backend uses strict type checking and automated formatting:

| Tool | Command | Config |
|------|---------|--------|
| **ruff** (linter + formatter) | `ruff check app tests` | `pyproject.toml [tool.ruff]` |
| **mypy** (type checker) | `mypy --strict app` | `pyproject.toml [tool.mypy]` |

Key conventions:
- `mypy --strict` — no `Any`, no `# type: ignore`, all functions typed
- `ruff` — enforces PEP 8 + import sorting + modern Python idioms
- Line length: 120 characters
- Target Python: 3.12

```bash
# Check everything
cd backend
ruff check app tests          # lint
mypy --strict app              # type check
```

### Frontend (TypeScript + Vue)

| Tool | Command | Config |
|------|---------|--------|
| **vue-tsc** | `npx vue-tsc -p tsconfig.app.json --noEmit` | `tsconfig.app.json` |
| **vitest** | `npx vitest run` | `vite.config.ts` |
| **vite build** | `pnpm build` | `vite.config.ts` |

> **Important**: Always use `vue-tsc -p tsconfig.app.json --noEmit`, NOT bare `vue-tsc --noEmit`.
> The root `tsconfig.json` has `files: []` which produces no meaningful output.

```bash
# Check everything
cd frontend
npx vue-tsc -p tsconfig.app.json --noEmit    # type check
npx vitest run                                 # tests
pnpm build                                     # production build
```

## Testing

### Backend Tests

```bash
cd backend

# Run all tests
.venv/Scripts/python.exe -m pytest -q    # Windows
python -m pytest -q                       # Linux/macOS

# Run a specific test file
python -m pytest tests/test_config.py -v

# Run with coverage
python -m pytest --cov=app tests/
```

- Test framework: **pytest** with **pytest-asyncio** (async mode: auto)
- Test directory: `backend/tests/`
- All new code should have corresponding tests

### Frontend Tests

```bash
cd frontend

# Run all tests
npx vitest run

# Run tests in watch mode
npx vitest

# Run a specific test file
npx vitest run src/components/__tests__/MyComponent.test.ts
```

- Test framework: **vitest** with **jsdom** environment
- Test files: co-located with components or in `__tests__/` directories
- Component testing: **@vue/test-utils**

## PR Process

### Before Submitting

1. **Type checks pass**: `mypy --strict app` (backend) and `vue-tsc -p tsconfig.app.json --noEmit` (frontend)
2. **Linter clean**: `ruff check app tests` (backend)
3. **Tests pass**: `pytest -q` (backend) and `vitest run` (frontend)
4. **Build succeeds**: `pnpm build` (frontend)

### Commit Messages

This project uses **[Conventional Commits](https://www.conventionalcommits.org/)** —
they drive automated releases via [release-please](https://github.com/googleapis/release-please).
Use a `type: subject` summary:

```
feat: add workspace deletion endpoint
fix: correct port mismatch in vite proxy config
docs: rewrite README for current architecture
refactor: extract phase handlers from FSM monolith
test: add unit tests for config validation
ci: cache the pnpm store
chore: bump dependencies
```

How it affects releases (on `main`):

- `fix:` → patch bump (e.g. `0.1.0 → 0.1.1`)
- `feat:` → minor bump (e.g. `0.1.0 → 0.2.0`)
- `feat!:` / `fix!:` or a `BREAKING CHANGE:` footer → major bump
- `docs:`, `ci:`, `chore:`, `refactor:`, `test:` → no version bump (still listed in the changelog)

release-please keeps an open **release PR** that updates `CHANGELOG.md` and the version
in `backend/pyproject.toml` + `frontend/package.json`. Merging that PR cuts the GitHub
Release + tag, which builds and publishes the Docker image to GHCR.

### Pull Request Template

PRs should include:

1. **What changed** — brief description of the change
2. **Why** — motivation and context
3. **How to verify** — steps to test the change
4. **Screenshots** — if UI changes are involved

### Review Criteria

- Code follows project style conventions
- New code has tests
- No type errors (mypy strict / vue-tsc)
- No regressions in existing tests
- Documentation updated if behavior changed

## Architecture Overview

For a high-level understanding, see the [main README](README.md#architecture).

Key files to understand the system:

| Area | Entry Point | Description |
|------|-------------|-------------|
| App factory | `backend/app/main.py` | FastAPI setup, auth, CORS, lifespan |
| Configuration | `backend/app/config.py` | Env vars, config overrides |
| FSM Orchestrator | `backend/app/orchestrator/fsm.py` | 9-phase state machine |
| API Routes | `backend/app/api/v1/` | 79 HTTP endpoints |
| Frontend Views | `frontend/src/views/` | Board, Agents, Tools, Settings |
| Pinia Stores | `frontend/src/stores/` | State management |
| Prompt Templates | `prompts/` | 19 markdown templates |

## Getting Help

- Open a GitHub Issue for bugs or feature requests
- Check [GETTING_STARTED.md](GETTING_STARTED.md) for setup troubleshooting
- Explore the API at http://localhost:8766/docs when running locally
