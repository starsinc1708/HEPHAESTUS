# Running HEPHAESTUS in Docker

This guide takes you from zero to a working HEPHAESTUS instance in Docker — running the
dashboard, mounting a repository, and connecting a model provider (by **API key** or by
**subscription login**).

> **Before you start:** HEPHAESTUS runs AI agents that execute arbitrary code on the
> repository you point it at, with the container user's privileges. Read
> [SECURITY.md](../SECURITY.md) and only point it at repositories you trust.

---

## Two images

| Image | Contains | Use it to |
|-------|----------|-----------|
| **`ghcr.io/starsinc1708/hephaestus:latest`** | dashboard + API + review/merge UI | try the UI. **Cannot run the loop** (no agent CLIs). |
| **agent image** — built from [`Dockerfile.agent`](../Dockerfile.agent) | the above **+ `git`, Node, and the agent CLIs** (`claude` / `opencode` / `codex`) | **use the app for real** — the autonomous loop executes tasks. |

The base image is slim on purpose. The agent CLIs are third-party tools, so they live in the
separate agent image.

---

## 1. Run it (agent image)

### With Docker Compose (recommended)

```bash
git clone https://github.com/starsinc1708/HEPHAESTUS.git
cd HEPHAESTUS

# Edit docker-compose.yml: uncomment the "/projects" volume and point it at the
# folder that holds the repo(s) you want HEPHAESTUS to work on.

docker compose up --build          # builds the agent image + starts it
# open http://localhost:8765
```

### With plain `docker run`

```bash
docker build -f Dockerfile.agent -t hephaestus-agent:local .

docker run -d --name hephaestus \
  -p 8765:8765 \
  -v hephaestus-state:/app/state \
  -v hephaestus-home:/home/hephaestus \
  -v /ABSOLUTE/PATH/TO/your-repos:/projects \
  hephaestus-agent:local
# open http://localhost:8765
```

### What the volumes are for

| Volume / mount | Purpose | Why you want it |
|---|---|---|
| `hephaestus-state:/app/state` | workspaces, connections, run history | survives restarts |
| `hephaestus-home:/home/hephaestus` | **agent CLI logins / credentials** | a subscription login (below) survives `docker rm` |
| `/your-repos:/projects` | the repositories HEPHAESTUS operates on | you can't onboard a repo the container can't see |

> Windows host paths in `docker run`: use the `/c/Users/...` form (Git Bash) or `C:\Users\...`
> (PowerShell). In Compose, an absolute host path works on all platforms.

---

## 2. Onboarding (in the browser)

Open **http://localhost:8765** — the onboarding wizard appears.

### Step 1 — connect a model provider

Pick **one** of the two auth styles:

#### A) API key (simplest)

Provider → Engine → **API key** → Model → paste your key → **Verify**. Done.

#### B) Subscription / login (Claude Max/Pro, ChatGPT, …)

Subscription auth uses the **CLI's own login**, which must be done **inside the container**
(its token is stored there — in the `hephaestus-home` volume, so it persists). Run the login
in **your own terminal** (it needs a TTY and your browser):

```bash
# Claude (Max/Pro):
docker exec -it hephaestus claude setup-token
# Codex (ChatGPT):
docker exec -it hephaestus codex login
# opencode:
docker exec -it hephaestus opencode auth login
```

Each prints a **URL** → open it in your browser (where you're signed in to that provider) →
authorize → paste the **code** back into the terminal. The token is saved in the container's
home (persisted by the `hephaestus-home` volume).

Then, in the dashboard, add a connection for that provider with **"Login method =
subscription / login"** — no API key needed.

> Why a terminal and not the dashboard button? The login is an interactive OAuth flow tied to
> *your* account and browser. `setup-token` / `login` use a paste-the-code flow that works in a
> headless container (no localhost redirect needed).

### Step 2 — CLIs (informational)

The wizard shows which CLIs are installed. In the agent image, `claude` / `opencode` / `codex`
are all present.

### Step 3 — connect a repository

The wizard shows a **directory browser** of the filesystem the container can see. It starts at
`/projects` (your mount); open folders to navigate, and pick a git repository (marked **◆ git**)
or the current folder. You can also paste a path manually.

Either way the path is the one **as seen inside the container**, i.e. under `/projects`:

```
/projects/my-repo
```

Not the host path (`C:\...` or `/home/you/...`) — the container only sees what you mounted at
`/projects`. If the browser is empty, you didn't mount anything at `/projects` (uncomment the
volume in `docker-compose.yml`).

---

## 3. Use it

Create a goal → HEPHAESTUS decomposes it into tasks → runs each via the agent → verifies →
merges. Everything is visible on the board. Bound a run with the cost / iteration / failure
budgets in **Settings → Base parameters**.

---

## Managing the container

```bash
docker logs -f hephaestus        # follow logs
docker stop hephaestus           # stop (state + logins preserved)
docker start hephaestus          # start again
docker rm -f hephaestus          # remove the container (volumes survive)
docker volume rm hephaestus-state hephaestus-home   # wipe state + logins (full reset)
```

`docker stop`/`start` keeps everything. Logins and state survive `docker rm` too, because they
live in the named volumes — only removing the volumes resets them.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Engine dropdown empty / "install claude/opencode/codex" | You're on the **base** image. Use the **agent** image (`Dockerfile.agent` / `docker compose up --build`). |
| Subscription connection won't verify | Run the CLI login first: `docker exec -it hephaestus claude setup-token` (or `codex login` / `opencode auth login`). |
| "repo not found" when onboarding | Use the in-container path `/projects/<repo>`, and make sure that repo is under the host folder you mounted at `/projects`. |
| Task stuck "queued" / loop log shows `Failed to create branch` / git `detected dubious ownership` | A mounted repo is owned by a different uid than the container user, so git refuses to touch it. Recent images fix this automatically; on an older image run once: `docker exec hephaestus git config --global --add safe.directory '*'` (persists in the `hephaestus-home` volume). |
| Login lost after recreating the container | Mount `-v hephaestus-home:/home/hephaestus` (Compose does this) so credentials persist. |
| Dashboard not reachable | `docker logs hephaestus`; confirm `-p 8765:8765` and that the port is free. |
