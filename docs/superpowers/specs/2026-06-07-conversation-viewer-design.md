# Per-task / per-stage Conversation Viewer — Design

**Goal:** Browse, per task, every stage's agent conversation — the implementer plus each
reviewer (validators, arbiters, final) and each revision — rendered richly like OpenCode
(markdown messages, collapsible thinking, expandable tool calls), with history preserved across
revisions (nothing overwritten). Sub-project #5 of the HEPHAESTUS v2 redesign ([[hephaestus-v2-redesign]]).

**Status:** approved (brainstorming 2026-06-07). Decisions: a **dedicated roomy screen**; a
**sidebar tree** (iteration → stage → agent) + conversation pane; **full OpenCode-level render**
(markdown / collapsible thinking / expandable tools / tokens-cost).

**Current state (probed):** `events.py` already parses Claude stream-json into structured events
(`kind`: text / tool_call / tool_result / reasoning(thinking), role, ts, `output_full`). The
validation funnel writes per-agent artifacts under `iter_dir/validation/{layer1,layer2,layer3}/`
(each lens/arbiter/final = its own JSONL via a unique `output_path`). `iters` API exposes
`/api/iter/{dir}/raw?stream=X` (parsed events, truncated, limit 400) and `/stream?stream=X`
(live SSE). **Gap:** the revision loop reuses one iter dir and **overwrites**
`output.primary.jsonl` + `validation/` each revision (only the last survives); there is **no
enumeration** of a task's stages×agents, **no untruncated** full-conversation parse, and **no
markdown renderer** on the frontend.

---

## 1. Preserve per-revision history (FSM, non-breaking)

In the revision loop (`fsm._process_item`), **before** each revision re-runs opencode / re-runs
the funnel (which overwrites `output.primary.jsonl` and `validation/`), **snapshot** the current
outputs to an attempt-namespaced archive:
- `output.primary.jsonl` → `output.primary.r{prev_attempt}.jsonl`
- `validation/` → `validation.r{prev_attempt}/` (copytree)

The latest revision always remains in the canonical `output.primary.jsonl` / `validation/`, so
**every existing consumer (LiveConsole, `/raw`, `/stream`, `parse_result`) is unaffected**. The
archives `r0…r{N-1}` hold the earlier revisions. (Cross-run history already exists — each requeue
makes a fresh iter dir.) Use `shutil.copy2`/`copytree`; best-effort, never crash a run.

## 2. Enumeration endpoint

`GET /api/v1/tasks/{id}/conversations` → the task's iterations and, per iteration, the
stages×agent-runs:
```jsonc
{ "ok": true, "iterations": [
  { "dir": "iter-1780…", "createdAt": "…", "attempts": 2, "stages": [
     { "stage": "implement", "agents": [
        { "stream": "output.primary.r0", "role": "implementer", "revision": 0, "model": "…",
          "status": "needs_revision", "messages": 42, "costUsd": 0.0 },
        { "stream": "output.primary.r1", "role": "implementer", "revision": 1, … },
        { "stream": "output.primary",    "role": "implementer", "revision": 2, "current": true, … } ] },
     { "stage": "validate", "agents": [
        { "stream": "validation/layer1/correctness", "role": "validator:correctness", … },
        … 5 lenses, arbiters (layer2), final (layer3) …,
        { "stream": "validation.r0/layer1/correctness", "role": "validator:correctness", "revision": 0, … } ] } ] } ] }
```
A backend helper enumerates the iter dir: maps `output.primary[.r{N}].jsonl` → implementer runs,
`validation[.r{N}]/layer{1,2,3}/*` → validator/arbiter/final runs, derives role/revision/model
(from the file or the persisted validation result) and a cheap `messages` count + cost.

## 3. Full conversation parse

`GET /api/iter/{dir}/conversation?stream=X` → the stream's **full** messages (no truncation):
each item `{ role, kind, text(full markdown), thinking(full), tool: {name, input, output(full)},
tsMs, tokens? }`. Reuse the `events.py` block parsing in a **non-truncating** mode (a `full=True`
path on `_summarize_claude_message` / a sibling `parse_full_message`). The `stream` arg accepts
the archived names from §2 (validate the path stays inside the iter dir — no traversal).

## 4. Frontend — the viewer

- Route `/board/task/:id/conversation` → `ConversationView.vue` (full-screen, opened over/instead
  of the board). Loads `GET …/conversations`.
- **Left `ConversationTree.vue`:** iteration → stage → agent rows (status icon + role + model +
  revision); selecting an agent loads its conversation. `data-test="conv-tree"`,
  `data-test="conv-agent-<stream>"`.
- **Right `ConversationPane.vue`** (OpenCode-style): renders the selected stream's full messages —
  user prompt + assistant **markdown** messages, **collapsible** thinking blocks
  (`data-test="msg-thinking"`), **expandable** tool cards (name + input JSON + output,
  `data-test="msg-tool"`), per-message tokens/cost. A running stream **live-tails** via the
  existing `/api/iter/{dir}/stream?stream=X` SSE; finished streams render statically.
- **Markdown:** add `markdown-it` (small) + sanitize output (escape HTML / a sanitizer) to avoid
  XSS from agent text.

## 5. Entry point

A «Переписки» button in the `TaskDrawer` (and/or the task card) routes to
`/board/task/:id/conversation`.

## 6. Testing

- **Backend unit:** the iter-dir enumeration (maps primary + `r{N}` archives + validation layers
  → agent runs with role/revision); the full parse (thinking/tool/text untruncated; an
  opencode-style and a claude-style fixture); the revision snapshot helper (r0 preserved after a
  simulated revision; latest stays canonical; never raises on a missing dir).
- **Backend contract:** `/tasks/{id}/conversations` shape; `/conversation?stream=…` returns
  messages and rejects path traversal (`../`).
- **Frontend unit:** `ConversationTree` renders iterations/stages/agents from a fixture and emits
  the selected stream; `ConversationPane` renders markdown, collapses thinking, expands a tool
  card, and shows tokens; the «Переписки» entry routes correctly.
- **Live (verify skill):** run/seed a task that went through ≥1 revision → the tree shows
  implementer r0 **and** r1 (history preserved) plus the validator/arbiter/final runs; open an
  implementer stream → messages + thinking + tool calls render; open a validator → its verdict
  conversation; switching agents works; a running stream live-tails.

## 7. Out of scope

Changing the funnel/FSM decision logic (we only **archive** outputs + render); editing
conversations; search across conversations; the worktrees tab (#6); goal→decompose (#7).

## 8. Risks

- **FSM snapshot must not break live consumers** — the canonical `output.primary.jsonl` /
  `validation/` stay the latest; archives are additive; copy is best-effort.
- **Large conversations** — cap/virtualize the pane; the parse endpoint can paginate if needed.
- **Markdown XSS** — sanitize rendered agent output.
- **Path safety** — the `stream` arg must resolve inside the iter dir only.
