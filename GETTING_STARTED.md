# Getting Started with HEPHAESTUS

This guide walks you through setting up HEPHAESTUS from a fresh clone to your first successful run.
Target time: **~15 minutes**.

## Prerequisites

| Tool | Version | Why | Install |
|------|---------|-----|---------|
| **Python** | 3.11+ | Backend runtime | [python.org](https://python.org) |
| **uv** | latest | Python package manager (faster than pip) | `pip install uv` or [astral.sh/uv](https://docs.astral.sh/uv/) |
| **Node.js** | 18+ | Frontend runtime | [nodejs.org](https://nodejs.org) |
| **pnpm** | 9+ | Frontend package manager | `npm install -g pnpm` |
| **Git** | 2.30+ | Branch management | system package manager |
| **AI CLI** | any | At least one: opencode, Claude Code, or Codex | see below |

### AI Engine CLIs

HEPHAESTUS works with multiple AI agent CLIs. Install at least one:

| Engine | Install | Notes |
|--------|---------|-------|
| **opencode** | [github.com/opencode-ai/opencode](https://github.com/opencode-ai/opencode) | Supports 7+ providers |
| **Claude Code** | `npm install -g @anthropic-ai/claude-code` | Anthropic's agent |
| **Codex** | `npm install -g @openai/codex` | OpenAI's agent |

The onboarding wizard auto-detects which CLIs are installed and available.

## Setup

### 1. Clone the Repository

```bash
git clone https://github.com/your-org/hephaestus-autonomous-loop.git
cd hephaestus-autonomous-loop
```

### 2. Backend Setup

```bash
cd backend

# Install Python dependencies
uv sync

# Create your environment file
cp .env.example .env
```

Edit `backend/.env` — the two paths you **must** set:

```bash
HEPHAESTUS_LOOP_HOME=/path/to/hephaestus-autonomous-loop    # where you cloned this repo
HEPHAESTUS_REPO=/path/to/your-target-repo               # the repo HEPHAESTUS will work on
```

Start the backend:

```bash
# Option A: via uvicorn directly
uvicorn app.main:app --host 127.0.0.1 --port 8766

# Option B: via the startup script (Linux/macOS)
bash start-backend.sh
```

The backend starts on **http://localhost:8766** by default.

> **Authentication**: By default, the dashboard has no password (suitable for localhost).
> Set `HEPHAESTUS_DASHBOARD_PASSWORD` in `.env` to enable auth.

### 3. Frontend Setup

Open a new terminal:

```bash
cd frontend

# Install Node dependencies (use pnpm, NOT npm)
pnpm install

# Start the dev server
pnpm dev
```

The frontend starts on **http://localhost:5173** and proxies API calls to the backend on `:8766`.

### 4. Verify First Run

1. Open **http://localhost:5173** in your browser
2. The **onboarding wizard** should appear:
   - **Step 1**: Connect an AI provider (add an API key for at least one provider)
   - **Step 2**: CLI detection (informational — shows which agent CLIs are installed)
   - **Step 3**: Select a git repository (the repo HEPHAESTUS will work on)
3. After completing the wizard, you'll see the main dashboard (Board view)

### 5. Run Your First Goal

1. Go to the **Board** view
2. Create a new goal (e.g. "Add a hello world endpoint")
3. Start the loop — watch tasks get decomposed, executed, verified, and committed

## API Documentation

FastAPI auto-generates interactive API documentation:

- **Swagger UI**: http://localhost:8766/docs
- **ReDoc**: http://localhost:8766/redoc
- **OpenAPI JSON**: http://localhost:8766/openapi.json

These are useful for understanding the full API surface (79 endpoints) and for debugging.

## Environment Variables

All configuration is done via environment variables. The full reference is in `backend/.env.example`.

### Core Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HEPHAESTUS_LOOP_HOME` | auto-detected | Root path of this repo |
| `HEPHAESTUS_REPO` | `""` | Target repository for tasks |
| `HEPHAESTUS_DASHBOARD_PORT` | `8766` | Backend port |
| `HEPHAESTUS_DASHBOARD_HOST` | `127.0.0.1` | Backend bind address |
| `HEPHAESTUS_DASHBOARD_PASSWORD` | (none) | Set to enable dashboard auth |

### Agent Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HEPHAESTUS_PRIMARY_AGENT` | `sisyphus` | Primary AI agent |
| `HEPHAESTUS_FALLBACK_AGENT` | `atlas` | Fallback agent on failure |
| `HEPHAESTUS_PRIMARY_MODEL` | `""` | Override primary model |
| `HEPHAESTUS_FALLBACK_MODEL` | `""` | Override fallback model |

### Loop Control

| Variable | Default | Description |
|----------|---------|-------------|
| `HEPHAESTUS_MAX_ITER` | `50` | Max iterations per run |
| `HEPHAESTUS_MAX_PARALLEL` | `1` | Parallel task limit |
| `HEPHAESTUS_ITER_TIMEOUT_SEC` | `2400` | Per-iteration timeout (40 min) |
| `HEPHAESTUS_MAX_CONSEC_FAIL` | `4` | Consecutive failures before stopping |
| `HEPHAESTUS_AUTOPUSH` | `off` | Auto-push feature branches to remote |

### Variables can be set in three ways:

1. **`.env` file**: `backend/.env` (loaded by start-backend.sh)
2. **Dashboard settings**: the Settings page in the UI
3. **`state/config.json`**: programmatic overrides (takes highest priority)

## Cross-Platform Notes

HEPHAESTUS works on **Windows, macOS, and Linux**.

### Windows

```powershell
# Backend — PowerShell
cd backend
uv sync
cp .env.example .env
# Edit .env with your paths (use forward slashes or escaped backslashes)
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8766

# Frontend — new PowerShell terminal
cd frontend
pnpm install
pnpm dev
```

> **Note**: The Python virtual environment is at `backend/.venv/Scripts/` on Windows
> (not `bin/` as on Unix). The `start-backend.sh` script is for Unix only;
> on Windows, run uvicorn directly as shown above.

### Linux / macOS

```bash
# Backend
cd backend
uv sync
cp .env.example .env
bash start-backend.sh   # or: uvicorn app.main:app --host 127.0.0.1 --port 8766

# Frontend (new terminal)
cd frontend
pnpm install
pnpm dev
```

### WSL (Windows Subsystem for Linux)

Follow the Linux instructions. Make sure your AI CLI tools are accessible from within WSL.
If the repo is on the Windows filesystem, access it via `/mnt/c/...` paths.

## Troubleshooting

### Frontend can't connect to backend

**Symptom**: Dashboard shows connection errors or loading forever.

- Verify the backend is running: `curl http://localhost:8766/healthz`
- Check the port matches: frontend proxy targets `127.0.0.1:8766`
- Check `HEPHAESTUS_DASHBOARD_PORT` in your `.env` — it must be `8766` (or update `frontend/vite.config.ts`)

### Backend fails to start

**Symptom**: `ModuleNotFoundError` or import errors.

- Run `uv sync` inside the `backend/` directory
- Make sure you're running from within `backend/` (uvicorn needs `app.main:app` to resolve)
- Check Python version: `python --version` — needs 3.11+

### No AI CLIs detected

**Symptom**: Onboarding wizard Step 2 shows all CLIs as not installed.

- Verify the CLI is in your PATH: `which opencode` / `where opencode`
- The backend detects CLIs — restart the backend after installing a new CLI
- This step is informational — you can proceed even with no CLIs detected

### `pnpm install` fails

- Ensure you're using **pnpm**, not npm: `pnpm --version`
- If node_modules is corrupted: `rm -rf node_modules && pnpm install`
- Check Node.js version: needs 18+

### State directory issues

**Symptom**: Backend errors about missing state files.

- The `state/` directory is created automatically on first run
- If you cloned fresh, there should be no `state/` yet — it's git-ignored
- To reset state: delete `state/` directory and restart the backend

### Authentication issues

**Symptom**: Dashboard shows "Unauthorized" after setting a password.

- Verify `HEPHAESTUS_DASHBOARD_PASSWORD` in `.env` matches what you're entering
- Restart the backend after changing `.env`
- Without the password variable set, auth is disabled (open access on localhost)

## Next Steps

- Read [CONTRIBUTING.md](CONTRIBUTING.md) to set up a development environment
- Explore the API at http://localhost:8766/docs
- Check the [main README](README.md) for architecture overview and configuration details
