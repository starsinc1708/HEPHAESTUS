"""Orchestrator FSM — async state machine for the HEPHAESTUS improvement loop.

States:
IDLE → PREFLIGHT → PROMPT_BUILD → OPENCODE → VERIFY → COMMIT → PARSE_RESULT
              ↓                                                     │
          TIER_REVIEW ←──────────────────────────────────────────────┤
              ↓                                                     │
          CLEANUP → IDLE                                            │
              └── failed:refused ───────────────────────────────────→┘
"""

from __future__ import annotations

import contextlib
import json
import logging
import pathlib
import time
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from app.core.verify import VerifyOutcome
    from app.models.validation import ValidationResult
    from app.models.workspace import RepoProfile

log = logging.getLogger("hephaestus.orchestrator")

# C3: module-level import so tests can monkeypatch app.orchestrator.fsm.replenish_goal.
# goals.py is always importable (pure Python, no subprocess deps).
from app.core.goals import replenish_goal  # noqa: E402

# Extracted pure helpers — re-exported so existing test imports remain valid.
from app.orchestrator.git_ops import drop_worktree, get_working_dir, restore_base_branch  # noqa: E402, F401
from app.orchestrator.prompt_builder import build_task_prompt  # noqa: E402, F401
from app.orchestrator.revision_snapshot import _snapshot_revision  # noqa: E402, F401


class Phase(StrEnum):
    IDLE = "idle"
    PREFLIGHT = "preflight"
    PROMPT_BUILD = "prompt_build"
    OPENCODE = "opencode"
    VERIFY = "verify"
    COMMIT = "commit"
    PARSE_RESULT = "parse_result"
    VALIDATE = "validate"          # was TIER_REVIEW
    CLEANUP = "cleanup"


_TRANSITIONS: dict[Phase, set[Phase]] = {
    Phase.IDLE: {Phase.PREFLIGHT},
    Phase.PREFLIGHT: {Phase.PROMPT_BUILD, Phase.IDLE},
    Phase.PROMPT_BUILD: {Phase.OPENCODE, Phase.IDLE},
    Phase.OPENCODE: {Phase.VERIFY, Phase.IDLE},
    Phase.VERIFY: {Phase.COMMIT, Phase.IDLE},
    Phase.COMMIT: {Phase.PARSE_RESULT, Phase.IDLE},
    Phase.PARSE_RESULT: {Phase.VALIDATE, Phase.IDLE},
    Phase.VALIDATE: {Phase.OPENCODE, Phase.CLEANUP, Phase.IDLE},  # VALIDATE→OPENCODE = revision loop
    Phase.CLEANUP: {Phase.IDLE},
}


# _snapshot_revision is now in app.orchestrator.revision_snapshot — re-exported above.


class OrchestratorFSM:
    """Async state machine for the HEPHAESTUS improvement loop.

    Usage::

        fsm = OrchestratorFSM()
        await fsm.run()  # runs forever, picking items from queue
    """

    def __init__(self) -> None:
        from app.core.process import pm

        self.phase: Phase = Phase.IDLE
        self.current_item: dict[str, Any] | None = None
        self.iter_dir: pathlib.Path | None = None
        self._stop_requested = False
        self._pm = pm
        self._ws: RepoProfile | None = self._resolve_ws()
        # Parallel worker: run this item in an isolated git worktree (_worktree set by
        # _preflight). False = sequential, run in the main working tree (unchanged).
        self._parallel: bool = False
        self._worktree: str | None = None
        # REL-003: intermediate results persisted in checkpoint for crash recovery.
        # Populated after each expensive phase so recovery can skip re-execution.
        self._intermediate_results: dict[str, Any] = {}

    def _resolve_ws(self) -> RepoProfile | None:
        import os

        from app.core.workspaces import active_workspace, registry

        ws_id = os.environ.get("HEPHAESTUS_WORKSPACE_ID")
        if ws_id:
            ws = registry.get(ws_id)
            if ws is not None:
                return ws
        return active_workspace()

    def request_stop(self) -> None:
        """Request graceful stop after current iteration."""
        self._stop_requested = True

    def _ensure_verify_configured(self) -> None:
        """Improvement 2 wiring: if the active workspace has no verify commands, auto-detect
        and write them so an already-onboarded workspace doesn't no-op the verify gate (the
        per-iteration diff-test net only covers files a task touched). Best-effort, logged,
        never fatal."""
        try:
            from app.core.workspaces import active_workspace
            from app.services.project_memory import init_verify_if_empty

            ws = active_workspace()
            if ws is not None and init_verify_if_empty(ws):
                log.info("verify.md was empty — auto-populated from the project detector")
        except Exception:
            log.debug("ensure-verify-configured skipped", exc_info=True)

    async def run(self) -> None:
        """Main loop — picks items, runs them, repeats.

        Honours HEPHAESTUS_MAX_ITER: stop after that many processed items (0/unset = unlimited).
        This is the cost control — set it to 1 to run a single task and stop.

        C3: In ralph run-mode (HEPHAESTUS_RUN_MODE=ralph, sequential only), the loop also
        honours cost/wallclock/consecutive-failure budgets and refills the queue from the
        active goal when it runs dry.  The parallel path is UNCHANGED.
        """
        import asyncio
        import os
        import time as _time

        from app.core.run_summary import RunSummary, RunSummaryStore, should_stop

        # Recover from stale checkpoint on startup
        self._recover_checkpoint()
        self._ensure_verify_configured()

        try:
            max_iter = int(os.environ.get("HEPHAESTUS_MAX_ITER", "0") or "0")
        except ValueError:
            max_iter = 0
        try:
            max_parallel = int(os.environ.get("HEPHAESTUS_MAX_PARALLEL", "1") or "1")
        except ValueError:
            max_parallel = 1
        max_parallel = max(1, min(max_parallel, 16))

        if max_parallel > 1:
            # Parallel path — NOT modified for Ralph (explicit follow-up, out of scope).
            await self._run_parallel(max_parallel, max_iter)
            return

        # --- C3: Ralph env reads (sequential path only) ---
        run_mode = os.environ.get("HEPHAESTUS_RUN_MODE", "queue")
        try:
            cost_budget = float(os.environ.get("HEPHAESTUS_COST_BUDGET_USD", "0") or 0)
        except (ValueError, TypeError):
            cost_budget = 0.0
        try:
            wallclock_sec = int(os.environ.get("HEPHAESTUS_WALLCLOCK_SEC", "0") or 0)
        except (ValueError, TypeError):
            wallclock_sec = 0
        try:
            max_consec = int(os.environ.get("HEPHAESTUS_MAX_CONSEC_FAIL", "4") or 4)
        except (ValueError, TypeError):
            max_consec = 4

        started_wall_ms = _time.time() * 1000
        deadline_ms: float | None = (
            started_wall_ms + wallclock_sec * 1000 if wallclock_sec > 0 else None
        )

        if run_mode == "ralph" and not cost_budget and deadline_ms is None and max_consec <= 0 and not max_iter:
            log.warning("Ralph mode: ALL budgets disabled (cost/wallclock/consec/max_iter) — "
                        "loop will run until manual stop.")

        summary = RunSummary(run_mode=run_mode, started_at_ms=started_wall_ms)
        summary_store = RunSummaryStore()

        _SUCCESS_STATUSES = {"done", "merged", "in_review"}

        while not self._stop_requested:
            # --- C3: budget/wallclock/consec-fail stops apply to RALPH mode only.
            # Queue mode keeps its original behavior (max_iter + idle-wait), unchanged. ---
            if run_mode == "ralph":
                now_ms = _time.time() * 1000
                stop, reason = should_stop(
                    summary,
                    cost_budget=cost_budget,
                    deadline_ms=deadline_ms,
                    max_consec_fail=max_consec,
                    now_ms=now_ms,
                )
                if stop:
                    summary.stopped_reason = reason
                    summary_store.put(summary)
                    log.info("Ralph stop: %s", reason)
                    break

            item = self._pick_next_item()
            if not item:
                # --- C3: Ralph empty-queue handling ---
                if run_mode == "ralph":
                    from app.core.goals import GoalStore
                    from app.services.opencode_runner import AgentRunner

                    active_goals = GoalStore().active()
                    if active_goals:
                        goal = active_goals[0]
                        runner = AgentRunner(
                            self._pm,
                            engine=getattr(self._ws, "engine", "opencode") if self._ws else "opencode",
                            env=getattr(self._ws, "engine_env", {}) if self._ws else {},
                            profiles=getattr(self._ws, "engine_profiles", []) if self._ws else [],
                        )
                        n = await replenish_goal(self._ws, goal, runner=runner)
                        if n > 0:
                            log.info("Ralph: replenished %d tasks for goal %s", n, goal.id)
                            continue
                        # n == 0: dry round
                        if goal.dry_rounds >= 2:
                            reason = f"goal-complete (dry) goal={goal.id}"
                            summary.stopped_reason = reason
                            summary_store.put(summary)
                            log.info("Ralph stop: %s", reason)
                            break
                        log.info(
                            "Ralph: goal %s dry_rounds=%d — waiting 2s", goal.id, goal.dry_rounds
                        )
                        await asyncio.sleep(2)
                        continue
                    # No active goals in ralph mode — original idle sleep, never exits.
                    log.info("No pending items — sleeping 30s")
                    await asyncio.sleep(30)
                    continue

                # --- Queue mode (auto-driver): EXIT on a confirmed-dry queue so the
                # process ends (it auto-restarts on the next send via reconcile_driver).
                # Yield once, then re-read to close the exit↔send race: if a task became
                # queued/in_progress in the meantime, keep going instead of exiting. ---
                await asyncio.sleep(0)
                from app.core.deps import has_runnable
                from app.core.state import _read_state as _rs_exit

                still_runnable = has_runnable(_rs_exit().get("items", []))
                if still_runnable:
                    continue
                log.info("queue empty — driver exiting")
                break

            # --- process item ---
            item_id = item.get("id")
            try:
                await self._process_item(item)
            except Exception as e:
                log.error("Item %s failed: %s", item_id, e)
                self._mark_failed(item, f"failed:{type(e).__name__}")
            finally:
                # Sequential mode mutates the main checkout; return it to base after each item
                # so a crash/failure never leaves the repo stranded on an auto/ branch.
                self._restore_base_branch()

            # --- C3: determine success and update summary ---
            from app.core.state import _read_state

            reloaded_status = ""
            try:
                state_items = _read_state().get("items", [])
                for it in state_items:
                    if it.get("id") == item_id:
                        reloaded_status = it.get("status", "")
                        break
            except Exception:
                log.error("failed to reload status for item %s after processing", item_id, exc_info=True)

            item_succeeded = reloaded_status in _SUCCESS_STATUSES
            if item_succeeded:
                summary.items_done += 1
                summary.consec_fail = 0
            else:
                summary.items_failed += 1
                summary.consec_fail += 1

            # Accumulate cost from the iter dir
            if self.iter_dir is not None:
                try:
                    from app.core.events import _iter_cost

                    summary.cost_usd += _iter_cost(self.iter_dir).get("cost_usd", 0.0)
                except Exception:
                    log.warning(
                        "failed to accumulate iter cost from %s", self.iter_dir, exc_info=True
                    )

            summary_store.put(summary)

            # max_iter bounds TOTAL processed items (success + fail) — preserves the original
            # cost-control semantics (a run of failing items must still terminate at max_iter).
            processed = summary.items_done + summary.items_failed
            if max_iter and processed >= max_iter:
                log.info(
                    "Reached HEPHAESTUS_MAX_ITER=%d — stopping after %d item(s)", max_iter, processed
                )
                break
            await asyncio.sleep(5)  # inter-iter sleep

        # FEAT-005: archive the finished run for the history view. archive() skips
        # no-op runs (driver cycles that processed nothing) so history isn't spammed.
        try:
            summary.ended_at_ms = _time.time() * 1000
            from app.core.run_summary import RunHistoryStore

            RunHistoryStore().archive(summary)
        except Exception:
            log.warning("failed to archive run summary to history", exc_info=True)

    async def _run_parallel(self, max_parallel: int, max_iter: int) -> None:
        """Scheduler: up to `max_parallel` items run concurrently, each in its own FSM
        worker + isolated git worktree + iter dir (=> its own live stream)."""
        import asyncio

        log.info("parallel scheduler: up to %d concurrent worker(s)", max_parallel)
        done = 0
        active: set[asyncio.Task[None]] = set()
        while not self._stop_requested:
            while len(active) < max_parallel and not (max_iter and (done + len(active)) >= max_iter):
                claimed = self._claim_next_item()
                if claimed is None:
                    break
                active.add(asyncio.create_task(self._run_worker(claimed)))
            if not active:
                if max_iter and done >= max_iter:
                    break
                # Auto-driver: nothing claimable and nothing running. Re-check the claim
                # once to close the exit↔send race; on a confirmed-dry queue, EXIT the
                # scheduler (it auto-restarts on the next send via reconcile_driver) instead
                # of looping forever. Parallel mode is never ralph.
                await asyncio.sleep(0)
                recheck = self._claim_next_item()
                if recheck is not None:
                    active.add(asyncio.create_task(self._run_worker(recheck)))
                    continue
                log.info("queue empty — parallel scheduler exiting")
                break
            finished, active = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
            done += len(finished)
            if max_iter and done >= max_iter:
                self._stop_requested = True
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        log.info("parallel scheduler stopped after %d item(s)", done)

    async def _run_worker(self, item: dict[str, Any]) -> None:
        """Process one claimed item on a fresh FSM instance in an isolated worktree."""
        worker = OrchestratorFSM()
        worker._parallel = True
        try:
            await worker._process_item(item)
        except Exception as e:  # noqa: BLE001 — one worker must not kill the scheduler
            log.error("worker item %s failed: %s", item.get("id"), e)
            worker._mark_failed(item, f"failed:{type(e).__name__}")
        finally:
            worker._drop_worktree()  # ensure isolation dir is gone even on failure

    def _drop_worktree(self) -> None:
        """Remove the worker's worktree dir (registry + on-disk). git's remove can leave the
        folder on Windows when a handle is briefly held, so prune + rmtree as a fallback."""
        if not self._worktree or self._ws is None:
            return
        drop_worktree(self._worktree, self._ws.repo_path)
        self._worktree = None

    def _restore_base_branch(self) -> None:
        """Sequential mode does `git checkout -b auto/...` in the MAIN checkout; after an item
        (done OR failed) force-return the checkout to the base branch so a crashed/failed run
        never strands the repo on an auto/ branch with the agent's partial uncommitted edits.
        No-op in parallel mode (isolated worktrees). The auto/ branch itself is preserved."""
        if self._parallel or self._worktree or self._ws is None:
            return
        restore_base_branch(self._ws.repo_path, self._ws.base_branch)

    def _runnable_statuses(self) -> set[str]:
        """Statuses the loop may pick. The user explicitly SENDS a task to run by flipping
        it to 'queued'; only those are runnable. In ralph mode a goal IS the explicit send,
        and goal replenishment enqueues 'pending' items — so ralph also accepts 'pending'
        (its continuous/replenish behavior is unchanged)."""
        import os

        if os.environ.get("HEPHAESTUS_RUN_MODE", "queue") == "ralph":
            return {"queued", "pending"}
        return {"queued"}

    def _claim_next_item(self) -> dict[str, Any] | None:
        """Atomically take the first READY item -> in_progress so concurrent workers get
        distinct items (and a crash leaves it recoverable via _requeue_stale_in_progress).
        Ready = status runnable AND all dependsOn satisfied; topo order emerges since only
        leaves are ready first. Parallel mode is never ralph, so this only ever claims
        'queued' items."""
        from app.core.deps import deps_satisfied
        from app.core.state import _read_state, _StateLock, _write_state

        runnable = self._runnable_statuses()
        with _StateLock():
            s = _read_state()
            items = s.get("items", [])
            by_id = {it.get("id"): it for it in items}
            for it in items:
                if it.get("status") in runnable and deps_satisfied(it, by_id):
                    it["status"] = "in_progress"
                    _write_state(s)
                    return dict(it)
        return None

    def _pick_next_item(self) -> dict[str, Any] | None:
        """Pick the first READY item (runnable status AND all dependsOn satisfied). For
        queued items this is exactly `ready`; for ralph-mode pending items this makes a
        task with unfinished deps wait until its prerequisites complete."""
        from app.core.deps import deps_satisfied
        from app.core.state import _read_state

        runnable = self._runnable_statuses()
        s = _read_state()
        items = s.get("items", [])
        by_id = {it.get("id"): it for it in items}
        for item in items:
            if item.get("status") in runnable and deps_satisfied(item, by_id):
                picked: dict[str, Any] = item
                return picked
        return None

    async def _process_item(self, item: dict[str, Any], ws: object | None = None) -> None:
        """Run one item through the full FSM pipeline, including the revision loop.

        ``ws`` defaults to the workspace resolved at construction (self._ws); callers
        (and tests) may pass one explicitly (umbrella R14/R15 — ws via self._ws).
        """
        self.current_item = item
        item_id = item.get("id", "?")
        if ws is not None:
            # Runtime accepts duck-typed workspaces (SimpleNamespace in tests); the
            # cast is a no-op that keeps self._ws's declared RepoProfile type.
            self._ws = cast("RepoProfile", ws)
        ws = self._ws

        # PREFLIGHT
        self._set_phase(Phase.PREFLIGHT, item_id)
        if not await self._preflight(item):
            return

        # PROMPT_BUILD
        self._set_phase(Phase.PROMPT_BUILD, item_id)
        prompt = await self._build_prompt(item)
        if not prompt:
            self._mark_failed(item, "failed:prompt-build")
            return

        # OPENCODE — with transient retry (Improvement 5)
        self._set_phase(Phase.OPENCODE, item_id)
        rc = await self._run_opencode_with_retry(item, prompt)
        if rc is None:  # refused
            self._mark_failed(item, "failed:refused")
            return
        if rc != 0:
            self._mark_failed(item, "failed:opencode")
            return

        # VERIFY
        self._set_phase(Phase.VERIFY, item_id)
        outcome = await self._verify(item)
        if not outcome.passed:
            self._mark_failed(item, "failed:verify")
            return
        # Honest gate: only "green" when something actually ran. If nothing did
        # (no verify config AND no test files in the diff) the item is unverified,
        # which the merge preflight surfaces and blocks instead of silently passing.
        self._persist_item_fields(
            item,
            verify_green=not outcome.unverified,
            verify_unverified=outcome.unverified,
            verify_outcome=outcome.model_dump(),
        )

        # REL-003: persist verify result in checkpoint for crash recovery
        self._intermediate_results["verify_green"] = not outcome.unverified
        self._intermediate_results["verify_outcome"] = outcome.model_dump()

        # SCOPE GUARD
        from app.core.scope_guard import check_scope
        from app.models.workspace import ScopeGuardMode
        scope_mode = getattr(self._ws, "scope_guard", ScopeGuardMode.ADVISORY)
        scope_result = check_scope(
            repo_cwd=self._get_repo(),
            base_ref=f"{self._ws.remote}/{self._ws.base_branch}" if self._ws else "origin/main",
            branch=item.get("branch", ""),
            touches=item.get("touches", []),
            mode=scope_mode,
        )
        if scope_result.extra_files:
            self._persist_item_fields(item, scope_extra=scope_result.extra_files)
        if not scope_result.ok:
            self._mark_failed(item, "failed:scope-guard")
            return

        # COMMIT
        self._set_phase(Phase.COMMIT, item_id)
        if not await self._commit(item):
            self._mark_failed(item, "failed:commit")
            return

        # PARSE_RESULT
        self._set_phase(Phase.PARSE_RESULT, item_id)
        await self._parse_result(item)

        # VALIDATE + revision loop (Stage 3, §7)
        self._set_status(item, "in_review")
        attempt = int(item.get("attempts", 0))
        max_rev = int(getattr(getattr(ws, "review", None), "max_revisions", 2))
        last_blocking: list[str] | None = None

        while True:
            if self._stop_requested:
                return  # leave status=in_review; checkpoint persisted
            self._set_phase(Phase.VALIDATE, item_id)
            vr = await self._validate(item, ws, attempt)
            if vr.gate == "pass":
                if attempt > 0 and last_blocking:
                    from app.services.lessons import extract_lesson
                    from app.services.opencode_runner import AgentRunner
                    try:
                        runner = AgentRunner(
                            self._pm,
                            engine=getattr(self._ws, "engine", "opencode"),
                            env=getattr(self._ws, "engine_env", {}),
                            profiles=getattr(self._ws, "engine_profiles", []),
                        )
                        lesson = await extract_lesson(
                            blocking_issues=last_blocking,
                            fix_summary=item.get("result_summary", ""),
                            runner=runner,
                            ws=cast("RepoProfile", ws),
                        )
                        if lesson:
                            from app.services.project_memory import add_lesson
                            added = add_lesson(cast("RepoProfile", ws), lesson=lesson, task_id=item_id)
                            if added:
                                log.info("Lesson learned from %s: %s", item_id, lesson)
                    except Exception:
                        log.warning("lesson extraction failed for %s", item_id, exc_info=True)

                self._set_phase(Phase.CLEANUP, item_id)
                await self._cleanup(item)
                item["validation"] = vr.model_dump(by_alias=True)
                self._mark_done(item)
                return
            last_blocking = vr.blocking
            attempt += 1
            item["attempts"] = attempt
            if attempt > max_rev:
                item["validation"] = vr.model_dump(by_alias=True)
                self._mark_failed(item, "failed:max-revisions")
                return
            # Persist WHY it went back (gate + blocking issues + layer summaries) so the
            # board/drawer can show the review result instead of it vanishing.
            self._persist_item_fields(item, validation=vr.model_dump(by_alias=True), attempts=attempt)
            self._set_status(item, "needs_revision")
            from app.core.validators import build_revision_prompt

            rprompt = build_revision_prompt(item, vr, attempt, cast("RepoProfile", ws))
            if self.iter_dir:
                (self.iter_dir / "prompt.md").write_text(rprompt, encoding="utf-8")
                # Keep the feedback ("what to rework") as a viewable artifact per attempt.
                (self.iter_dir / f"revision-{attempt}.md").write_text(rprompt, encoding="utf-8")
            # Archive the just-finished attempt's conversation before the revision
            # re-run overwrites output.primary.jsonl / validation/ (history viewer §1).
            _snapshot_revision(self.iter_dir, attempt - 1)
            # Revision re-runs on the SAME branch (PREFLIGHT not repeated); diff accumulates.
            self._set_phase(Phase.OPENCODE, item_id)
            rc = await self._run_opencode_with_retry(item, rprompt)
            if rc is None:
                self._mark_failed(item, "failed:refused")
                return
            if rc != 0:
                self._mark_failed(item, "failed:opencode")
                return
            self._set_phase(Phase.VERIFY, item_id)
            outcome = await self._verify(item)
            if not outcome.passed:
                self._mark_failed(item, "failed:verify")
                return
            self._persist_item_fields(
                item,
                verify_green=not outcome.unverified,
                verify_unverified=outcome.unverified,
                verify_outcome=outcome.model_dump(),
            )

            # SCOPE GUARD
            from app.core.scope_guard import check_scope
            from app.models.workspace import ScopeGuardMode
            scope_mode = getattr(self._ws, "scope_guard", ScopeGuardMode.ADVISORY)
            scope_result = check_scope(
                repo_cwd=self._get_repo(),
                base_ref=f"{self._ws.remote}/{self._ws.base_branch}" if self._ws else "origin/main",
                branch=item.get("branch", ""),
                touches=item.get("touches", []),
                mode=scope_mode,
            )
            if scope_result.extra_files:
                self._persist_item_fields(item, scope_extra=scope_result.extra_files)
            if not scope_result.ok:
                self._mark_failed(item, "failed:scope-guard")
                return

            self._set_phase(Phase.COMMIT, item_id)
            if not await self._commit(item):
                self._mark_failed(item, "failed:commit")
                return
            self._set_phase(Phase.PARSE_RESULT, item_id)
            await self._parse_result(item)
            self._set_status(item, "in_review")

    def _set_phase(self, phase: Phase, item_id: str) -> None:
        """Write current phase to current.json and persist checkpoint."""
        # Validate transition
        allowed = _TRANSITIONS.get(self.phase, set())
        if phase not in allowed and self.phase != phase:
            log.warning("invalid FSM transition: %s -> %s (allowed: %s)", self.phase, phase, allowed)
        self.phase = phase

        # Use workspace-aware state dir for checkpoint when available
        if self._ws is not None:
            from app.core.workspaces import registry

            state_dir = registry.state_dir(self._ws)
        else:
            from app.config import STATE_DIR

            state_dir = STATE_DIR
        from app.core.state import _atomic_write

        data = json.dumps(
            {
                "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "itemId": item_id,
                "phase": phase.value,
                "detail": "",
            }
        )
        _atomic_write(state_dir / "current.json", data)

        # Checkpoint persistence — write except when returning to IDLE
        if phase != Phase.IDLE:
            checkpoint = json.dumps(
                {
                    "phase": phase.value,
                    "item_id": item_id,
                    "branch": (self.current_item or {}).get("branch"),
                    "iter_dir": str(self.iter_dir) if self.iter_dir else None,
                    "timestamp": time.time(),
                    "intermediate_results": dict(self._intermediate_results),
                }
            )
            _atomic_write(state_dir / "fsm-checkpoint.json", checkpoint)

    def _set_status(self, item: dict[str, Any], status: str) -> None:
        """Persist a status transition for the current item (no decision log)."""
        from app.core.state import _read_state, _StateLock, _write_state

        item["status"] = status
        with _StateLock():
            s = _read_state()
            for it in s.get("items", []):
                if it.get("id") == item.get("id"):
                    it["status"] = status
            _write_state(s)

    def _persist_item_fields(self, item: dict[str, Any], **fields: Any) -> None:
        """Persist arbitrary fields onto the queued item in work-state.json.

        _set_status/_mark_done only write `status`, so flags like verify_green (read by
        the merge preflight) must be persisted explicitly or they never reach disk."""
        from app.core.state import _read_state, _StateLock, _write_state

        item.update(fields)
        with _StateLock():
            s = _read_state()
            for it in s.get("items", []):
                if it.get("id") == item.get("id"):
                    it.update(fields)
            _write_state(s)

    async def _preflight(self, item: dict[str, Any]) -> bool:
        """Check git status, create branch, set up iter dir."""
        from app.orchestrator.phases.preflight import preflight_phase

        return await preflight_phase(self, item)

    async def _build_prompt(self, item: dict[str, Any]) -> str | None:
        """Build the prompt file for opencode."""
        return build_task_prompt(item, self._ws, self.iter_dir)

    async def _run_opencode(self, item: dict[str, Any], prompt: str) -> int | None:
        """Run opencode with the prompt via AgentRunner. Returns exit code or None if refused."""
        from app.orchestrator.phases.opencode import run_opencode

        return await run_opencode(self, item, prompt)

    async def _run_opencode_with_retry(self, item: dict[str, Any], prompt: str) -> int | None:
        """Run opencode with automatic retry on transient failures."""
        from app.orchestrator.phases.opencode import run_opencode_with_retry

        return await run_opencode_with_retry(self, item, prompt)

    async def _verify(self, item: dict[str, Any]) -> VerifyOutcome:
        """Run configured verify commands AND the diff-test safety net."""
        from app.orchestrator.phases.verify import verify_phase

        return await verify_phase(self, item)

    async def _commit(self, item: dict[str, Any]) -> bool:
        """Commit changes to the auto/ branch."""
        from app.orchestrator.phases.commit import commit_phase

        return await commit_phase(self, item)

    async def _parse_result(self, item: dict[str, Any]) -> bool:
        """Parse opencode result and update state."""
        from app.orchestrator.phases.parse_result import parse_result_phase

        return await parse_result_phase(self, item)

    async def _validate(self, item: dict[str, Any], ws: object, revision: int) -> ValidationResult:
        """Run the map-reduce validation funnel (replaces the legacy tier-review no-op)."""
        from app.orchestrator.phases.validate import validate_phase

        return await validate_phase(self, item, ws, revision)

    def _try_resume_committed(self, cp: dict[str, Any]) -> str | None:
        """REL-003 resume: if the crashed item had a DURABLE commit (the persisted SHA still
        exists in git) and verify had passed, recover it straight to ``in_review`` — its work
        is committed and verified, ready to merge — instead of re-running the whole iteration
        (re-OPENCODE + re-VERIFY + re-COMMIT, minutes of wasted work). Returns the resumed item
        id, or None if anything is uncertain (caller then does the safe clear+requeue).

        Conservative by design: only fires for an item that crashed AT/AFTER COMMIT with a SHA
        that git confirms exists. Items that crashed before a durable commit re-run as before.
        Trade-off: a resumed item skips the AI validation loop (it goes to in_review, mergeable);
        the objective gates (verify) passed and the merge re-verifies the merged tree.
        """
        intermediate = cp.get("intermediate_results") or {}
        commit = str(intermediate.get("commit") or "")
        item_id = str(cp.get("item_id") or "")
        if not commit or not item_id or not intermediate.get("verify_green") or self._ws is None:
            return None
        # Don't trust the checkpoint alone — the commit must actually exist in the repo.
        from app.core.helpers import _run
        try:
            sha = _run(["git", "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}"],
                       cwd=self._ws.repo_path).strip()
        except Exception:
            return None
        if not sha:
            return None
        from app.core.state import _read_state, _StateLock, _write_state
        try:
            with _StateLock():
                s = _read_state()
                found = False
                for it in s.get("items", []):
                    if it.get("id") == item_id and it.get("status") == "in_progress":
                        it["status"] = "in_review"
                        it["verify_green"] = bool(intermediate.get("verify_green"))
                        it["commit"] = commit
                        if intermediate.get("verify_outcome") is not None:
                            it["verify_outcome"] = intermediate["verify_outcome"]
                        found = True
                if found:
                    _write_state(s)
        except Exception:
            log.warning("REL-003 resume: state update failed for %s — falling back to requeue",
                        item_id, exc_info=True)
            return None
        if not found:
            return None
        log.info("REL-003 resume: %s recovered to in_review from durable commit %s "
                 "(skipped re-run)", item_id, commit[:8])
        return item_id

    def _recover_checkpoint(self) -> None:
        """Check for stale checkpoint from a previous crash and recover.

        REL-003: intermediate_results (verify_green, commit hash) are persisted in the
        checkpoint. If the item crashed after a DURABLE commit, _try_resume_committed recovers
        it straight to in_review (skipping the expensive re-run); otherwise we fall back to the
        safe clear+requeue.
        """
        if self._ws is not None:
            from app.core.workspaces import registry

            state_dir = registry.state_dir(self._ws)
        else:
            from app.config import STATE_DIR

            state_dir = STATE_DIR

        cp_path = state_dir / "fsm-checkpoint.json"
        if not cp_path.exists():
            return
        try:
            cp = json.loads(cp_path.read_text(encoding="utf-8"))
            phase_val = cp.get("phase", "idle")
            intermediate = cp.get("intermediate_results", {})
            if phase_val != "idle":
                log.warning(
                    "stale FSM checkpoint found: phase=%s item=%s branch=%s iter_dir=%s ts=%.1f — clearing",
                    phase_val,
                    cp.get("item_id"),
                    cp.get("branch"),
                    cp.get("iter_dir"),
                    cp.get("timestamp", 0),
                )
                if intermediate:
                    log.info(
                        "intermediate results available: verify_green=%s commit=%s",
                        intermediate.get("verify_green"),
                        intermediate.get("commit"),
                    )
            self.phase = Phase.IDLE
            cp_path.unlink(missing_ok=True)
            # REL-003: resume a durably-committed item straight to in_review; the rest
            # (and anything not resumable) fall back to the safe clear+requeue. The resumed
            # item is now in_review (not in_progress), so _requeue_stale_in_progress leaves it.
            self._try_resume_committed(cp)
            self._requeue_stale_in_progress()
        except Exception:
            log.error("failed to read FSM checkpoint at %s — renaming to .corrupt", cp_path, exc_info=True)
            try:
                cp_path.rename(cp_path.with_suffix(".json.corrupt"))
            except Exception:
                log.warning("failed to rename corrupt checkpoint %s", cp_path, exc_info=True)
                with contextlib.suppress(Exception):
                    cp_path.unlink(missing_ok=True)
            self._requeue_stale_in_progress()

    def _requeue_stale_in_progress(self) -> None:
        """After a crash, items left 'in_progress' would otherwise be skipped forever
        (_pick_next_item only takes 'queued'), stalling the loop. Reset them to 'queued'
        (NOT 'pending') so a restarted driver resumes exactly the sent tasks and never
        auto-runs backlog items."""
        from app.core.state import _read_state, _StateLock, _write_state

        with _StateLock():
            s = _read_state()
            changed = False
            for it in s.get("items", []):
                if it.get("status") == "in_progress":
                    it["status"] = "queued"
                    changed = True
            if changed:
                _write_state(s)
                log.info("recovered stale in_progress item(s) -> queued")

    async def _cleanup(self, item: dict[str, Any]) -> None:
        """Clean up after iteration."""
        from app.orchestrator.phases.cleanup import cleanup_phase

        await cleanup_phase(self, item)

    def _get_repo(self) -> str:
        """The working dir for git/agent ops — the worker's worktree if isolated, else the
        workspace repo. All git/agent cwds route through this so parallel workers don't
        fight over a single checkout."""
        return get_working_dir(self._worktree, self._ws.repo_path if self._ws else "")

    def _mark_failed(self, item: dict[str, Any], status: str) -> None:
        """Mark item as failed in state."""
        from app.core.decisions import _append_decision
        from app.core.state import _read_state, _StateLock, _write_state

        with _StateLock():
            s = _read_state()
            for it in s.get("items", []):
                if it.get("id") == item.get("id"):
                    it["status"] = status
            _write_state(s)
        _append_decision(
            "orchestrator", "fail", item.get("branch", "-"), status, item.get("id", "?")
        )
        with contextlib.suppress(Exception):  # FEAT-002 — best-effort, never affects the FSM
            from app.services.notify import notify_task
            notify_task(item.get("id", ""), status)
        self._set_phase(Phase.IDLE, "")

    def _mark_done(self, item: dict[str, Any]) -> None:
        """Mark item as done in state."""
        from app.core.decisions import _append_decision
        from app.core.state import _read_state, _StateLock, _write_state

        with _StateLock():
            s = _read_state()
            for it in s.get("items", []):
                if it.get("id") == item.get("id"):
                    it["status"] = "done"
                    it["verify_green"] = True  # done implies verify passed
                    if item.get("validation") is not None:
                        it["validation"] = item["validation"]
                    if item.get("commit"):
                        it["commit"] = item["commit"]
            _write_state(s)
        _append_decision(
            "orchestrator", "done", item.get("branch", "-"), "ok", item.get("id", "?")
        )
        with contextlib.suppress(Exception):  # FEAT-002 — best-effort, never affects the FSM
            from app.services.notify import notify_task
            notify_task(item.get("id", ""), "done")
        self._set_phase(Phase.IDLE, "")
