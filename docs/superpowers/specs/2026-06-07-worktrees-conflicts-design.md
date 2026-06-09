# Worktrees Tab + AI Conflict Resolution — Design

**Goal:** A full Worktrees tab that lists every task's branch/worktree linked to its task, shows
each branch's changed files + diff, flags branches that touch the **same files** (conflict-prone),
and lets the user merge each into base — with the existing AI layer resolving conflicts. Final
sub-project (#6) of the HEPHAESTUS v2 redesign ([[hephaestus-v2-redesign]]); builds on Epic 1.

**Status:** approved (brainstorming 2026-06-07). Decisions: overlap is detected from **git
changed-files per branch**; merge is **per-branch** (the existing AI-merge job — no cascade
"merge selected"); the "AI conflict layer" is the **existing** `ai_resolve` merge-job, surfaced.

**Current state (probed):** Epic 1 provides `GET /api/v1/branches/{name}/merge-preflight`,
`POST /api/v1/branches/{name}/merge` (`MergeRequest.aiResolve` → a merge-job that resolves
conflicts vs base via the merge agent), `/api/v1/active-merge-job`, `/merge-jobs/{id}` +
accept/reject, and the `MergeButton`/`MergeJobPanel` components. `POST /api/branch/{name}/{action}`
exists for branch actions. `GET /api/state` exposes `git.auto_branches`. #2 created a basic
`WorktreesView` that already lists `auto_branches` with a per-row `MergeButton`. Work-state items
carry a `branch` field linking task ↔ branch.

---

## 1. Backend — worktrees enumeration + overlap (`app/core/worktrees.py` + `GET /api/v1/worktrees`)

`list_worktrees(ws) -> list[Worktree]`, one per `auto/*` branch:
```jsonc
{ "branch": "auto/idea-x-1780…", "task": {"id":"idea-x","title":"…","status":"done"} | null,
  "changedFiles": ["frontend/src/a.ts", …], "changedCount": 7,
  "preflight": { cleanTree, verifyGreen, validationPassed, ok },   // reuse merge_preflight
  "conflictsWith": [ { "branch": "auto/idea-y-…", "task": {…}, "files": ["frontend/src/a.ts"] } ] }
```
- Branches from the same source as `git.auto_branches` (or `git branch --list 'auto/*'`).
- `changedFiles` = `git diff --name-only {remote}/{base}..{branch}` per branch (never-crash → []).
- Task link = the work-state item whose `branch == this branch` (None if unlinked).
- `preflight` reuses `GitService.merge_preflight` (clean/verify/validation/ok).
- **Overlap**: pairwise-intersect the `changedFiles` sets; each worktree lists every other branch
  it shares ≥1 file with + the shared files. O(n²) over branches — fine for realistic counts.
- Endpoint `GET /api/v1/worktrees` → `{ ok, worktrees: [...] }`.

## 2. Backend — per-branch diff

Surface the full diff `{base}..{branch}`: reuse the existing `branch_action(name, "diff")` if it
returns a unified diff, else add `GET /api/v1/branches/{name}/diff` (guarded by the same
`_is_safe_auto_branch` check as merge). Returns `text/plain` unified diff (capped length).

## 3. AI conflict resolution — surface the existing merge-job

No new AI layer. Each worktree's «Merge в base» uses the existing `POST
/api/v1/branches/{name}/merge {aiResolve:true}` → the merge-job resolves conflicts vs base via the
merge agent (Epic 1), driven by the existing `MergeButton`/`MergeJobPanel`. When two branches
touched the same file, merging the second after the first conflicts against the updated base →
the AI-merge resolves it. The **overlap badge (§1)** tells the user *in advance* which merges will
conflict. The single-active-merge guard (Epic 1) is unchanged.

## 4. Frontend — full `WorktreesView`

Enrich the #2 basic view into a list/table, one row per worktree:
- **Task** (id + title + status chip) · **branch** name · **changed files** (count +
  `data-test="wt-diff-toggle"` expands the unified diff via §2) · **overlap badge**
  (`data-test="wt-conflict"` = «⚠ пересекается с <task/branch> (N файлов)», expands the shared
  files) · **`MergeButton`** (existing → merge-job + `MergeJobPanel`) · **status** (merged /
  готов к merge / verify-not-green, from `preflight`).
- Overlapping branches are visually grouped/highlighted so same-file sets are obvious.
- Loads `GET /api/v1/worktrees`; refresh on merge completion + a manual refresh; reuse the diff
  renderer used elsewhere (iter/merge diff).

## 5. Testing

- **Backend unit (`worktrees.py`):** branch→task linkage (matched + unlinked); `changedFiles`
  from a temp git repo with two `auto/*` branches; **overlap** computed pairwise (two branches
  sharing a file → each lists the other + the file; non-overlapping → empty); never-crash on a
  bad branch / missing base. **Contract:** `GET /api/v1/worktrees` shape; the diff endpoint
  returns the unified diff and rejects a non-`auto/` name.
- **Frontend unit:** `WorktreesView` renders rows from a fixture (task, changed count, overlap
  badge, MergeButton present); the diff toggle expands; the conflict badge expands the shared
  files; clicking merge invokes the existing merge flow (mock `api`).
- **Live (verify skill):** in a throwaway repo, create two `auto/*` branches that both modify the
  same file → the tab lists both with «пересекаются (file)»; expand each diff; merge the first →
  ok; merge the second → conflict → the AI-merge job resolves → merged; a non-overlapping branch
  shows no badge. Capture evidence.

## 6. Out of scope

The cascade "merge selected in order" (per-branch only); changing the merge-job / AI-merge logic
(only enumeration + diff + overlap + surfacing); the dependency graph (#4); conversation viewer
(#5). GitHub/GitLab (#8) remains the last v2 sub-project.

## 7. Risks

- **Per-branch git calls** — N `diff --name-only` (+ optional full diffs on expand) per refresh;
  cheap but cache within a request and only full-diff on demand (the toggle), throttle auto-refresh.
- **Overlap O(n²)** — fine for realistic branch counts; cap/guard if a workspace has very many.
- **Active-merge guard** — only one merge-job at a time (Epic 1); the tab disables other merge
  buttons while a job is active (reuse the existing active-merge-job re-attach from this session).
- **Stale branches** — list only `auto/*`; unlinked branches (task deleted) still show with
  `task: null` and remain mergeable/deletable.
