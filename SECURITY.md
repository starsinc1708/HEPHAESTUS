# Security Policy

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately via GitHub's **[Report a vulnerability](https://github.com/starsinc1708/HEPHAESTUS/security/advisories/new)**
(Security → Advisories → "Report a vulnerability"). If that is unavailable, open a
minimal public issue titled "security contact request" (no details) and a maintainer
will arrange a private channel.

Please include: affected version/commit, a description, reproduction steps, and the
impact you observed. We aim to acknowledge within a few days. This is a
community-maintained project with no formal SLA, but security reports are
prioritized.

Supported: security fixes target the `master` branch (the latest state). There are no
separately maintained release branches yet.

---

## Security model — read this before running HEPHAESTUS

HEPHAESTUS is a **powerful local automation tool, not a sandbox.** Understanding its trust
model is essential to using it safely.

### What HEPHAESTUS does on your machine

- **Runs AI agents that execute arbitrary code.** The core loop invokes external agent
  CLIs (`claude`, `opencode`, `codex`) which run shell commands, edit files, and perform
  `git` operations on the target repository. There is **no sandbox or container
  isolation** around agent execution — agents run with **the same privileges as the
  user running HEPHAESTUS**.
- **Runs your configured verify commands** (tests/lint/typecheck) against agent-produced
  code, including on merged trees.
- **Performs git operations** — creates working branches, commits, merges into your base
  branch, and (if `autopush` is on) pushes to your remote.

### Implications

- **Only point HEPHAESTUS at repositories you trust**, and run it as a user whose privileges
  you are comfortable handing to an autonomous agent. Treat a running HEPHAESTUS instance like
  a developer with shell access to that repo.
- Prefer running it against a **dedicated clone / throwaway working copy**, not a
  repository with production credentials or secrets in the working tree.
- An autonomous loop can consume provider API budget and make many commits. Use the
  cost/iteration/consecutive-failure budgets in **Settings → Base parameters** to bound a
  run.

### Credentials & secrets

- Provider API keys and tracker tokens (GitHub/GitLab PATs) are stored **locally** in the
  workspace state under `<repo>/.hephaestus/`, and are **masked** in API responses and logs.
- They are **not** committed to git: `.hephaestus/`, `state/`, and `.env` are git-ignored.
- Anyone with read access to the host filesystem or to a running HEPHAESTUS instance can reach
  those credentials. Do not expose the dashboard to untrusted networks.

### Network exposure

- The dashboard/API binds to `127.0.0.1` by default. Binding to `0.0.0.0` exposes it on
  your network **with no authentication** — the API is meant for a trusted local/LAN
  context. Do not expose it to the public internet. Put it behind your own
  authenticating reverse proxy / VPN if remote access is required.

### Reducing risk

- Run against a disposable clone; keep secrets out of the working tree.
- Leave `autopush` off until you trust a workflow; review diffs in the dashboard before
  merging.
- Keep agent CLIs and their auth scoped to what you need.
- Set conservative budgets for unattended runs.
