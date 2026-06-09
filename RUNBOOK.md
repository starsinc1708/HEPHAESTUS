# RUNBOOK — hephaestus autonomous-loop

> **⚠️ DEPRECATED** — This document describes the old bash-based loop (`driver.sh`, `verify.sh`, `config.env`, `tmux`).
> That system no longer exists. The current system is a **FastAPI + Vue 3** application.
>
> For setup and usage instructions, see **[GETTING_STARTED.md](GETTING_STARTED.md)**.
> For contribution guidelines, see **[CONTRIBUTING.md](CONTRIBUTING.md)**.

---

The content below is preserved for historical reference only. Do not follow these instructions.

---

## 0. Mental model in one paragraph (OLD SYSTEM)

The driver picks one item from `plan-items.json`, opens a fresh `auto/<item-id>-<sha>` branch on the repo, builds a prompt, runs `opencode` (primary agent → fallback agent on failure), runs `pnpm typecheck + lint + tests` against the result, and **only commits if all three are green**. On any failure it `git reset --hard`s back to `origin/main` and marks the item failed. Then it sleeps a few seconds and repeats. A web dashboard at `:8765` shows everything live.

---

## 1. Single-item smoke run (do this first)

You want to see one full iteration end-to-end before you commit to a 50-iteration overnight run. Do exactly this:

```bash
ssh starsinc@192.168.0.103

# --- one-time pre-flight (skip if you've already done it) ---
cd /home/starsinc/hephaestus-repo
pnpm install                         # ~3-5 min first time, 10-30 s thereafter
pnpm run infra:up                    # postgres + redis docker compose
pnpm run db:deploy                   # prisma migrations
sudo ufw allow 8765/tcp 2>/dev/null || true   # if firewall is on

# --- start dashboard (window A) ---
tmux new -s hephaestus-dash
cd /home/starsinc/hephaestus-autonomous-loop
./start-dashboard.sh
# detach: Ctrl-b then d

# --- start loop for ONE iteration only (window B) ---
tmux new -s hephaestus-loop
cd /home/starsinc/hephaestus-autonomous-loop
HEPHAESTUS_MAX_ITER=1 ./start-loop.sh
# leave this window attached — you'll watch it
```

Then from any device on your LAN, open: **`http://192.168.0.103:8765/`**

The driver banner prints, sleeps 5 seconds (so you can Ctrl-C if you change your mind), then starts iteration 1.

---

## 2. What you'll see during one iteration (phase-by-phase)

Total time: ~15–25 minutes. Most of it is `pnpm test` (1160+ tests).

| t    | Phase shown on dashboard | What's happening                       | Dashboard signal |
|------|--------------------------|----------------------------------------|------------------|
| 0s   | `preflight`              | git fetch + reset to origin/main        | cyan pulse, "preflight" |
| ~5s  | `prompt`                 | composing `state/iter-0001/prompt.md`   | "prompt · composing" |
| ~10s | `opencode`               | `opencode run --agent sisyphus ...` running. This is the long one — opencode reads files, edits, possibly runs `pnpm` itself, then prints the result block. | "opencode · primary=sisyphus" — usually 2-10 minutes |
| ~?   | `verify`                 | `pnpm -w typecheck && lint && test` | "verify · typecheck+lint+tests" — usually 5-10 min for full test suite |
| end  | `commit`                 | `git add -A && git commit` on `auto/<id>` | "commit · git add + commit" — usually <2s |
| end  | `idle`                   | item moved to status `done`, branch shows in **auto/* branches** card | progress bar advances 1 / 16 |

### Expected dashboard outcome of one successful iter

- **Progress card:** total=16, done=1, pending=15, failed=0
- **Queue card:** the item you just ran has a green left-edge and `status: done`
- **auto/* branches card:** one row appears with `auto/<id>-<sha>  <short-sha>  +N`
- **Recent commits card:** one new row at the top — `<short-sha>  starsinc  auto(<id>): <title>`
- **Log tail card:** ends with `iter 1 DONE  id=<id>  branch=auto/...  sha=...  files=N  push=local-only`
- **Current strip:** back to grey `idle`

---

## 3. Three ways to monitor in parallel

Pick what works for you — they don't conflict.

### 3a. Web dashboard (primary)

`http://192.168.0.103:8765/` — auto-refreshes every 3 seconds. Works from any LAN device including your Windows machine. No JS framework, no build step, just `fetch` polling.

### 3b. tail -f run.log (deepest detail)

```bash
ssh starsinc@192.168.0.103 'tail -f /home/starsinc/hephaestus-autonomous-loop/state/run.log'
```

Every state transition and every opencode/verify start/end is recorded with a UTC timestamp. Grep-friendly:

```bash
ssh starsinc@192.168.0.103 'grep -E "(ERROR|WARN|DONE|FAILED)" /home/starsinc/hephaestus-autonomous-loop/state/run.log | tail -30'
```

### 3c. Watch current.json (one-liner status)

```bash
ssh starsinc@192.168.0.103 'watch -n 2 "cat /home/starsinc/hephaestus-autonomous-loop/state/current.json | jq ."'
```

Updates whenever the driver enters a new phase.

### 3d. Attach to the running tmux session

```bash
ssh starsinc@192.168.0.103
tmux attach -t hephaestus-loop      # see the driver output live
# detach without killing: Ctrl-b then d
```

This is also how you can `Ctrl-C` the driver immediately if you must.

---

## 4. Recognize success vs each failure mode

The driver writes one of these final statuses for each item. The dashboard colors each accordingly.

### ✅ success: `done`

- Green left-edge in queue
- New entry in `auto/* branches`
- New commit visible in `recent commits`
- Log tail ends with `iter N DONE`

What to do: nothing. Inspect the diff later with:

```bash
cd /home/starsinc/hephaestus-repo
git log --oneline auto/<the-branch>
git diff main..auto/<the-branch>
```

### ⚠️ `failed:no-changes`

opencode ran successfully but didn't change any files. Usually means:
- the item was already shipped (and the planning doc is stale)
- the prompt was ambiguous to the agent
- the agent refused (it does sometimes when the change seems risky)

Look at `state/iter-NNNN/output.primary.jsonl` — last few lines usually explain why.

What to do: usually skip. To retry, manually flip the item back to pending (§7).

### ⚠️ `failed:verify`

opencode changed files but `pnpm typecheck` or `lint` or `tests` failed afterward. The driver has already `git reset --hard`-ed the working tree.

Look at `state/iter-NNNN/verify.log` — search for the first `FAILED` and the surrounding context.

What to do: read the verify log, decide whether the test that broke is (a) a real regression the agent introduced, (b) a flaky test you'd skip, or (c) an issue with the plan item itself. Flip back to pending after fixing.

### 🔴 `failed:opencode`

Both primary and fallback agents exited non-zero. Usually:
- SOCKS5 proxy at `127.0.0.1:10808` went down → opencode can't reach models
- GLM quota / rate-limit hit AND deepseek also hit (unlikely both at once)
- bug in the prompt that opencode refuses to process

Diagnose:

```bash
ssh starsinc@192.168.0.103
ss -tnlp | grep 10808                                 # proxy still listening?
tail -30 /home/starsinc/hephaestus-autonomous-loop/state/iter-NNNN/output.primary.jsonl
tail -30 /home/starsinc/hephaestus-autonomous-loop/state/iter-NNNN/output.fallback.jsonl
```

What to do: fix the underlying cause, then flip back to pending. After 4 consecutive opencode failures the loop exits itself (`HEPHAESTUS_MAX_CONSEC_FAIL=4`).

---

## 5. Stop

### Soft stop (preferred — finishes current iter cleanly)

```bash
touch /home/starsinc/hephaestus-autonomous-loop/state/stop
```

Dashboard will show a red `STOP file present` tag. Loop exits at the top of the next iteration check (so it won't leave a half-applied change).

### Hard stop

```bash
tmux kill-session -t hephaestus-loop
```

If an opencode call was in flight, it gets SIGKILL'd. If git was mid-commit, the working tree may be in a weird state — recover with `cd /home/starsinc/hephaestus-repo && git checkout main && git reset --hard origin/main`.

---

## 6. Stop the dashboard

```bash
tmux kill-session -t hephaestus-dash
```

State files persist; you can restart the dashboard later and it'll show the latest snapshot.

---

## 7. Re-queue a failed item (or rerun a `done` one)

The work queue lives in `state/work-state.json`. Edit the item's `status` field manually:

```bash
ssh starsinc@192.168.0.103
cd /home/starsinc/hephaestus-autonomous-loop
# flip C-P0-2 back to pending (jq prints, mv saves)
jq '(.items[] | select(.id == "C-P0-2") | .status) |= "pending"' state/work-state.json > state/work-state.json.tmp
mv state/work-state.json.tmp state/work-state.json
```

Or wipe everything and start over (the next driver start re-initializes from `plan-items.json`):

```bash
rm state/work-state.json
rm -rf state/iter-*/
```

---

## 8. Promote one item to first in line

The driver picks `next_pending_id` = the **first** item in the array with `status=="pending"`. To run a specific one first, move it to the top of `state/work-state.json` `.items` array:

```bash
jq '.items |= ((map(select(.id == "U-P1-1"))) + (map(select(.id != "U-P1-1"))))' state/work-state.json > tmp && mv tmp state/work-state.json
```

(replace `U-P1-1` with the id you want).

---

## 9. Promote auto-branches to PRs

By default `HEPHAESTUS_AUTOPUSH=off` — branches stay local. To push manually:

```bash
ssh starsinc@192.168.0.103
cd /home/starsinc/hephaestus-repo
git push -u origin auto/<branch-name>
# then on github.com → "Compare & pull request"
```

Or enable autopush in `config.env`:

```bash
sed -i 's/HEPHAESTUS_AUTOPUSH=.*/HEPHAESTUS_AUTOPUSH=on/' config.env
```

Future iterations will `git push` feature branches to `origin` after each successful commit. `main` is still never pushed.

---

## 10. Full run (after smoke-test passes)

```bash
ssh starsinc@192.168.0.103
tmux new -s hephaestus-loop
cd /home/starsinc/hephaestus-autonomous-loop
./start-loop.sh           # default HEPHAESTUS_MAX_ITER=50
# detach: Ctrl-b then d
```

Walk away. Check the dashboard occasionally. Stop with `touch state/stop` anytime.

A full 50-iter run worst case (50 × 25 min) ≈ 21 hours. Realistically most items finish in 10-15 min, several will skip via `failed:no-changes`, so ~6-10 wall hours.

---

## 11. Tune the knobs

`config.env` knobs you may want to flip (all env-overridable):

| Var                       | Default      | Use this when                                              |
|---------------------------|--------------|------------------------------------------------------------|
| `HEPHAESTUS_MAX_ITER`          | 50           | one-task smoke: set to 1                                   |
| `HEPHAESTUS_MAX_CONSEC_FAIL`   | 4            | running unattended overnight: lower to 2 for safety        |
| `HEPHAESTUS_ITER_TIMEOUT_SEC`  | 2400 (40 min)| large items: bump to 3600. small items: drop to 1200       |
| `HEPHAESTUS_INTER_ITER_SLEEP`  | 20           | want a stricter pace: drop to 5                            |
| `HEPHAESTUS_PRIMARY_AGENT`     | sisyphus     | want oracle/prometheus instead: change                     |
| `HEPHAESTUS_FALLBACK_AGENT`    | atlas        | want metis (reasoning model) for harder items              |
| `HEPHAESTUS_USE_MODELS`        | 0            | bypass oh-my-openagent entirely: set 1 + edit MODEL vars   |
| `HEPHAESTUS_AUTOPUSH`          | off          | push auto-branches after every commit                      |
| `HEPHAESTUS_RUN_TESTS`         | 1            | skip the test suite temporarily (fast iteration): set 0    |

All can also be exported inline:

```bash
HEPHAESTUS_MAX_ITER=1 HEPHAESTUS_FALLBACK_AGENT=metis ./start-loop.sh
```

---

## 12. Health checklist (run before any new start)

```bash
ssh starsinc@192.168.0.103 'bash -lc "
  echo -n proxy:; ss -tnlp 2>/dev/null | grep -q 10808 && echo OK || echo DOWN
  echo -n disk:; df -h /home | awk \"NR==2{print \$4 \\\" free, \\\" \$5 \\\" used\\\"}\"
  echo -n opencode:; /home/starsinc/.npm-global/bin/opencode --version 2>/dev/null || echo MISSING
  echo -n pnpm:; /home/starsinc/.npm-global/bin/pnpm --version 2>/dev/null || echo MISSING
  echo -n postgres:; nc -z localhost 5432 && echo OK || echo DOWN
  echo -n redis:; nc -z localhost 6379 && echo OK || echo DOWN
  echo -n dashboard:; curl -sf http://localhost:8765/healthz >/dev/null && echo OK || echo DOWN
"'
```

Expected when ready to launch: proxy OK, disk >5 GB free, opencode + pnpm versioned, postgres + redis OK, dashboard OK.

---

## 13. Where to read everything

| Question                                  | File / command                                              |
|-------------------------------------------|-------------------------------------------------------------|
| What plan items are queued?               | `cat plan-items.json` or dashboard "queue"                  |
| What did opencode write for iter N?       | `state/iter-NNNN/output.primary.jsonl`                      |
| Did verify pass / what failed?            | `state/iter-NNNN/verify.log`                                |
| What was the exact prompt?                | `state/iter-NNNN/prompt.md`                                 |
| All events ever logged                    | `state/run.log`                                             |
| What changed in iter N's commit?          | `cd repo && git show <iter-N's sha>`                        |
| Which agents/models are configured?       | `~/.config/opencode/oh-my-openagent.json`                   |
| Operator manual / full design notes       | `README.md` (in the same dir as this file)                  |

---

## 14. Worst-case recovery

If something genuinely broke (driver crashed mid-commit, repo in weird state, dashboard returns 500, etc):

```bash
ssh starsinc@192.168.0.103
# 1. stop everything
tmux kill-session -t hephaestus-loop 2>/dev/null
tmux kill-session -t hephaestus-dash 2>/dev/null

# 2. reset the repo to a known good state
cd /home/starsinc/hephaestus-repo
git checkout main
git reset --hard origin/main
git branch --list 'auto/*' | xargs -r git branch -D     # nuke local auto branches

# 3. reset loop state (preserves plan-items.json + scripts, wipes runtime)
cd /home/starsinc/hephaestus-autonomous-loop
rm -f state/work-state.json state/current.json state/stop
rm -rf state/iter-*

# 4. restart cleanly
./start-dashboard.sh &   # or in tmux
./start-loop.sh          # in tmux
```
