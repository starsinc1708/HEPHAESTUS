"""Iteration, task, and state builder services — ported verbatim from dashboard/server.py.

Functions for iter dir summarisation, detailed views, diffs, tool history,
task drilldown, state cleanup, and the main build_state() aggregator that
the legacy UI polls every 3 seconds.
"""

from __future__ import annotations

import contextlib
import json
import logging
import pathlib
import time
from typing import Any, cast

from app.config import _config_effective
from app.core.decisions import _read_decisions
from app.core.driver import _loop_status
from app.core.events import _current_iter_block, _iter_cost, _parse_events, _summarize_event
from app.core.git import _git_branches, _git_recent_commits
from app.core.helpers import _active_git, _all_iter_dirs, _load_json, _log_tail, _run, _summarize
from app.core.state import _read_state, _state_dir, _StateLock, _write_state

log = logging.getLogger("hephaestus.backend.iters")

# ---------- build_state() mtime cache (PERF-002) ----------

_state_cache: dict[str, Any] | None = None
_cache_key: tuple[float, ...] | None = None


def _compute_cache_key() -> tuple[float, ...] | None:
    """Compute an mtime-based cache key from iter dirs and work-state.json."""
    try:
        sd = _state_dir()
        iter_dirs = _all_iter_dirs()
        key_parts: list[float] = []
        for d in sorted(iter_dirs):
            try:
                key_parts.append(d.stat().st_mtime)
            except OSError:
                return None  # dir disappeared → force rebuild
        ws_path = sd / "work-state.json"
        with contextlib.suppress(OSError):
            key_parts.append(ws_path.stat().st_mtime)
        return tuple(key_parts)
    except Exception:
        return None


def _cache_invalidated() -> bool:
    """Check if cached state is stale by comparing mtimes."""
    global _cache_key
    new_key = _compute_cache_key()
    return new_key is None or _cache_key is None or new_key != _cache_key


def invalidate_state_cache() -> None:
    """Force cache invalidation (call after writes)."""
    global _state_cache, _cache_key
    _state_cache = None
    _cache_key = None


# ---------- safe iter dir validation ----------


def _safe_iter_dir(dirname: str) -> pathlib.Path | None:
    """Validate and resolve an iter dir name. Returns the resolved Path or None."""
    if not dirname.startswith("iter-") or ".." in dirname or "/" in dirname:
        return None
    base = _state_dir()  # active workspace's <repo>/.hephaestus/state (legacy fallback)
    d = base / dirname
    try:
        resolved = d.resolve()
        if not str(resolved).startswith(str(base.resolve())):
            return None
    except (ValueError, OSError):
        return None
    if not resolved.exists():
        return None
    return resolved


def _resolve_conversation_stream(iter_dir: pathlib.Path, stream: str) -> pathlib.Path | None:
    """Resolve a conversation stream NAME (a relative path WITHOUT the .jsonl suffix,
    e.g. 'output.primary', 'output.primary.r0', 'validation/layer1/correctness',
    'validation.r0/layer2/arbiter-0', 'validation/layer3/final') to the backing .jsonl
    file, GUARANTEED to live inside iter_dir. Returns None on empty/oversized/unsafe input
    or any path-traversal attempt."""
    # Reject backslashes outright on every platform: a legitimate stream name only uses
    # '/' and '.', while '\' is a Windows path separator (a real traversal vector there)
    # and an illegitimate filename char elsewhere. This keeps the guard OS-independent.
    if not stream or len(stream) > 200 or "\x00" in stream or "\\" in stream:
        return None
    candidate = iter_dir / f"{stream}.jsonl"
    try:
        resolved = candidate.resolve()
        base = iter_dir.resolve()
    except (OSError, ValueError, RuntimeError):
        return None
    if resolved != base and not resolved.is_relative_to(base):
        return None
    return resolved


# ---------- history ----------


def _iter_summary_row(d: pathlib.Path) -> dict[str, Any]:
    """One-line summary of an iter dir for the history list."""
    name = d.name
    mtime = d.stat().st_mtime
    # try to derive item-id + status from the work-state file
    item_id = None
    status = None
    branch = None
    commit = None
    review = None
    s = _read_state()
    for it in s.get("items", []):
        if it.get("lastIter") == name:
            item_id = it.get("id")
            status = it.get("status")
            branch = it.get("branch")
            commit = it.get("commit")
            review = it.get("review")
            break
    # tier-review final decision
    final = None
    fd = d / "reviews" / "final-decision.json"
    if fd.exists():
        final_obj = cast("dict[str, Any]", _load_json(fd) or {})
        final = final_obj.get("final_decision")
    # token totals
    cost = _iter_cost(d)
    return {
        "iter": name,
        "mtime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(mtime)),
        "item_id": item_id,
        "status": status,
        "branch": branch,
        "commit_short": (commit[:10] if commit else None),
        "review": review,
        "final_decision": final,
        "tokens": cost["total"],
    }


# ---------- iter details ----------


def _iter_details(dirname: str) -> dict[str, Any]:
    d = _safe_iter_dir(dirname)
    if d is None:
        return {"ok": False, "error": "not found"}
    info: dict[str, Any] = {"ok": True, "dir": dirname, "files": sorted(p.name for p in d.iterdir())}
    if (d / "commit-msg.txt").exists():
        info["commit_msg"] = (d / "commit-msg.txt").read_text(encoding="utf-8", errors="replace")[:1500]
    if (d / "verify.log").exists():
        vl = (d / "verify.log").read_text(encoding="utf-8", errors="replace")
        lastlines = vl.splitlines()[-20:]
        info["verify_summary"] = "\n".join(lastlines)
        info["verify_lines"] = len(vl.splitlines())
        info["verify_size"] = (d / "verify.log").stat().st_size
    rev_dir = d / "reviews"
    if rev_dir.exists():
        info["has_reviews"] = True
        for t in ("tier1", "tier2"):
            sf = rev_dir / f"{t}-summary.json"
            if sf.exists():
                info[f"{t}_summary"] = _load_json(sf)
        fd = rev_dir / "final-decision.json"
        if fd.exists():
            info["final_decision"] = _load_json(fd)
        info["verdicts"] = []
        for vf in sorted(rev_dir.glob("*.verdict.json")):
            v = cast("dict[str, Any]", _load_json(vf) or {})
            info["verdicts"].append(
                {k: v.get(k) for k in ("reviewer", "tier", "verdict", "confidence", "top_issues", "reasoning")}
            )
    # Stage 3 validation funnel (umbrella §4.4): validation/layer3/final.json + layer1 verdicts
    vdir = d / "validation"
    if vdir.exists():
        fd = vdir / "layer3" / "final.json"
        if fd.exists():
            info["validation"] = _load_json(fd)
        l1dir = vdir / "layer1"
        l1: list[dict[str, Any]] = []
        if l1dir.exists():
            for vf in sorted(l1dir.glob("*.json")):
                v_l1: dict[str, Any] | list[Any] = _load_json(vf) or {}
                if isinstance(v_l1, dict) and "lens" in v_l1:
                    l1.append({k: v_l1.get(k) for k in ("lens", "verdict", "confidence", "reasoning")})
        l2dir = vdir / "layer2"
        l2: list[dict[str, Any]] = []
        if l2dir.exists():
            for vf in sorted(l2dir.glob("*.json")):
                v_l2: dict[str, Any] | list[Any] = _load_json(vf) or {}
                if isinstance(v_l2, dict):
                    l2.append(v_l2)
        if (l1 or l2) and not isinstance(info.get("validation"), dict):
            info["validation"] = {}
        if isinstance(info.get("validation"), dict):
            info["validation"]["layer1"] = l1
            info["validation"].setdefault("layer2Summary", [])
            if l2:
                info["validation"]["layer2Summary"] = l2
    info["cost"] = _iter_cost(d)
    return info


def _iter_raw_events(dirname: str, stream: str = "primary", limit: int = 400) -> list[dict[str, Any]] | None:
    """Return parsed events from a chosen stream (primary|fallback|reviewer name)."""
    d = _safe_iter_dir(dirname)
    if d is None:
        return None
    if stream in ("primary", "fallback"):  # noqa: SIM108
        p = d / f"output.{stream}.jsonl"
    else:
        p = d / "reviews" / f"{stream}.out.jsonl"
    return _parse_events(p, limit=limit) if p.exists() else []


def _iter_diff(dirname: str) -> str | None:
    """Try every reasonable source of the diff:
      1) reviews/diff.patch (cached by tier-review)
      2) branch committed diff (git diff origin/main..branch)
      3) live working tree (if iter is still in_progress and we're on the branch)
      4) recorded commit SHA (if branch was merged/discarded but we kept the sha)
    Returns the first non-empty diff, or a short status note if all empty.
    """
    d = _safe_iter_dir(dirname)
    if d is None:
        return None

    repo, base, remote, _prefix = _active_git()
    # 1) cached
    diff_file = d / "reviews" / "diff.patch"
    if diff_file.exists():
        content = diff_file.read_text(encoding="utf-8", errors="replace")
        if content.strip():
            return content

    s = _read_state()
    item = None
    for it in s.get("items", []):
        if it.get("lastIter") == dirname:
            item = it
            break
    if not item:
        return "(no item references this iter dir — was state reset?)"

    branch = item.get("branch") or item.get("lastBranch")
    status = item.get("status")
    commit = item.get("commit") or item.get("merge_sha")

    if branch:
        # 2) branch committed diff
        committed = _run(["git", "diff", f"{remote}/{base}..{branch}"], cwd=repo, timeout=20)
        if committed and committed.strip():
            return committed
        # 3) in-progress: show working tree against base if we're on the branch
        if status == "in_progress":
            head_now = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
            if head_now == branch:
                wt = _run(["git", "diff", f"{remote}/{base}"], cwd=repo, timeout=20)
                if wt and wt.strip():
                    return wt + "\n\n[NB: working-tree diff — iter still in progress, no commit yet]"
                # Try also untracked-file content
                untracked = _run(["git", "ls-files", "--others", "--exclude-standard"], cwd=repo, timeout=10)
                if untracked:
                    return f"[iter in progress on branch {branch}; no diff yet]\n\nUntracked files:\n{untracked}"
            return (
                f"[iter in progress on branch {branch}; current HEAD is "
                f"'{head_now}'; agent hasn't written changes yet or HEAD drifted]"
            )

    # 4) by commit sha (branch deleted after merge/discard)
    if commit:
        by_sha = _run(["git", "diff", f"{remote}/{base}..{commit}"], cwd=repo, timeout=20)
        if by_sha and by_sha.strip():
            return by_sha
        # commit might also be the merge_sha (already in main)
        return (
            f"[branch was merged into {base} as commit "
            f"{commit[:10]}; no remaining diff vs {remote}/{base}]"
        )

    return f"[no diff available — status={status}, branch={branch or 'none'}, commit={commit or 'none'}]"


def _iter_verify(dirname: str) -> str | None:
    d = _safe_iter_dir(dirname)
    if d is None:
        return None
    p = d / "verify.log"
    return p.read_text(errors="replace") if p.exists() else None


# ---------- per-iter tool history ----------


def _stream_path(d: pathlib.Path, stream: str) -> pathlib.Path:
    if stream in ("primary", "fallback"):
        return d / f"output.{stream}.jsonl"
    return d / "reviews" / f"{stream}.out.jsonl"


def _iter_tool_history(dirname: str, stream: str = "primary") -> list[dict[str, Any]] | None:
    """Return a flat list of tool calls + paired results for ONE stream of an iter.
    Pairs tool_call (with `tool_use_id`) to a later tool_result event with the same id.
    Output: [{name, args_preview, args_full, output_preview, output_full, ts_started_ms,
              ts_completed_ms, duration_ms, status, tool_use_id}].
    Cheap on disk: walks the JSONL file once, indexed by tool_use_id.
    """
    d = _safe_iter_dir(dirname)
    if d is None:
        return None
    p = _stream_path(d, stream)
    if not p.exists():
        return []
    # Pass through _parse_events with NO truncation cap so we get the full args/output.
    # We bump the parser by reading directly to dodge the 80-event tail.
    calls: dict[str, dict[str, Any]] = {}  # tool_use_id -> dict
    order: list[str] = []  # insertion order
    try:
        with p.open("r", encoding="utf-8", errors="replace") as f:
            for idx, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    log.debug("failed to parse JSONL line in _iter_tool_history at idx %d", idx, exc_info=True)
                    continue
                ev = _summarize_event(obj, idx=idx)
                kind = ev.get("kind")
                tid = ev.get("tool_use_id")
                if kind == "tool_call":
                    rec: dict[str, Any] = {
                        "idx": ev.get("idx"),
                        "tool_use_id": tid,
                        "tool": ev.get("tool"),
                        "args_preview": ev.get("args_preview"),
                        "args_full": ev.get("args_full"),
                        "ts_started_ms": ev.get("ts_started_ms") or ev.get("ts_ms"),
                        "ts_completed_ms": ev.get("ts_completed_ms"),
                        "status": ev.get("status"),
                        "output_preview": ev.get("output_preview"),
                        "output_full": ev.get("output_full"),
                    }
                    if tid and tid in calls:
                        # later call with same id replaces the placeholder (rare)
                        order.append(tid)
                    elif tid:
                        order.append(tid)
                    key = tid or f"_anon_{idx}"
                    calls[key] = rec
                elif kind == "tool_result" and tid:
                    existing = calls.get(tid)
                    if not existing:
                        # orphan result — track for visibility
                        order.append(tid)
                        existing = {"idx": ev.get("idx"), "tool_use_id": tid, "tool": "?", "orphan_result": True}
                        calls[tid] = existing
                    existing["output_preview"] = ev.get("output_preview")
                    existing["output_full"] = ev.get("output_full")
                    existing["ts_completed_ms"] = existing.get("ts_completed_ms") or ev.get("ts_ms")
                    existing["status"] = "completed"
        # Build the final flat list in observation order
        seen: set[str] = set()
        flat: list[dict[str, Any]] = []
        for k in order:
            if k in seen:
                continue
            seen.add(k)
            entry = calls.get(k)
            if not entry:
                continue
            ts0 = entry.get("ts_started_ms")
            ts1 = entry.get("ts_completed_ms")
            if isinstance(ts0, (int, float)) and isinstance(ts1, (int, float)) and ts1 >= ts0:
                entry["duration_ms"] = int(ts1 - ts0)
            flat.append(entry)
        return flat
    except Exception as e:
        log.error("_iter_tool_history failed for %s/%s: %s", dirname, stream, e)
        return []


def _iter_streams(dirname: str) -> list[dict[str, Any]]:
    """List all available agent streams in an iter dir, with role tag."""
    d = _safe_iter_dir(dirname)
    if d is None:
        return []
    streams: list[dict[str, Any]] = []
    for nm in ("primary", "fallback"):
        p = d / f"output.{nm}.jsonl"
        if p.exists() and p.stat().st_size > 0:
            from app.services.agent_activity import _detect_implementer_agent

            agent, _which = _detect_implementer_agent(d) if nm == "primary" else (None, None)
            streams.append({"stream": nm, "role": "implementer", "agent": agent, "size": p.stat().st_size})
    rdir = d / "reviews"
    if rdir.exists():
        for vf in sorted(rdir.glob("*.out.jsonl")):
            base = vf.name[: -len(".out.jsonl")]
            verdict_file = rdir / f"{base}.verdict.json"
            tier: Any = None
            verdict = None
            reviewer = base
            v = cast("dict[str, Any]", _load_json(verdict_file) or {})
            tier = v.get("tier")
            verdict = v.get("verdict")
            reviewer = v.get("reviewer") or base
            role = {"tier1": "tier-1 reviewer", "tier2": "tier-2 reviewer", "final": "final reviewer"}.get(
                tier, "reviewer"
            )
            streams.append(
                {
                    "stream": base,
                    "role": role,
                    "agent": reviewer,
                    "tier": tier,
                    "verdict": verdict,
                    "size": vf.stat().st_size,
                }
            )
    return streams


# ---------- per-task view ----------


def _task_view(item_id: str) -> dict[str, Any]:
    """Aggregate everything dashboard needs to render the per-task drilldown:
    item record, list of iters that ran for it, per-iter summary, total cost,
    list of agents that touched it.
    """
    s = _read_state()
    item = next((it for it in s.get("items", []) if it.get("id") == item_id), None)
    if not item:
        return {"ok": False, "error": "task not found"}
    # iters for this item: state files whose lastIter or previousBranches map back
    iters: list[dict[str, Any]] = []
    agents_seen: dict[str, dict[str, Any]] = {}  # agent -> { role -> count }
    cost_total: dict[str, Any] = {
        "input": 0,
        "output": 0,
        "reasoning": 0,
        "cache_read": 0,
        "cache_write": 0,
        "total": 0,
        "cost_usd": 0.0,
    }
    _sd = _state_dir()
    if _sd.exists():
        for d in sorted(_sd.glob("iter-*")):
            # Match iter dir → this item via state lookup
            matches_id = False
            for it in s.get("items", []):
                if it.get("id") == item_id:
                    if it.get("lastIter") == d.name:
                        matches_id = True
                    break
            # Fallback: read the iter's commit-msg and grep for item id
            if not matches_id:
                cm = d / "commit-msg.txt"
                if cm.exists():
                    try:
                        if item_id in cm.read_text(errors="replace"):
                            matches_id = True
                    except Exception:
                        log.debug("failed to read commit-msg.txt in %s", d, exc_info=True)
                        pass
            if not matches_id:
                continue
            row = _iter_summary_row(d)
            row["streams"] = _iter_streams(d.name)
            for s_ in row["streams"]:
                a = s_.get("agent")
                if a:
                    agents_seen.setdefault(a, {"name": a, "roles": {}})
                    r = s_.get("role") or "?"
                    agents_seen[a]["roles"][r] = agents_seen[a]["roles"].get(r, 0) + 1
            c = _iter_cost(d)
            row["cost"] = c
            for k in ("input", "output", "reasoning", "cache_read", "cache_write", "total"):
                cost_total[k] += c.get(k, 0)
            cost_total["cost_usd"] += c.get("cost_usd", 0.0)
            iters.append(row)
    cost_total["cost_usd"] = round(cost_total["cost_usd"], 5)
    # Latest iter is the natural target for "open" actions on the row.
    latest_iter = iters[-1]["iter"] if iters else None
    item_out = dict(item)
    item_out["dependsOn"] = item.get("dependsOn", [])
    item_out["blocks"] = item.get("blocks", [])
    item_out["conflictGroup"] = item.get("conflictGroup")
    return {
        "ok": True,
        "item": item_out,
        "iters": iters,
        "agents": sorted(agents_seen.values(), key=lambda x: x["name"]),
        "cost": cost_total,
        "latest_iter": latest_iter,
    }


# ---------- state cleanup ----------


def _state_cleanup(opts: dict[str, Any]) -> dict[str, Any]:
    """Operator-triggered: clear failed/stale entries to keep the queue actionable.
    kinds: list of status prefixes to drop (e.g. ['failed', 'discarded']).
    reset_orphan_in_progress: re-pend any in_progress items whose driver isn't running.
    """
    from app.core.decisions import _append_decision
    from app.core.process import ProcState, pm

    kinds = opts.get("kinds") or ["failed", "discarded"]
    do_orphan = bool(opts.get("reset_orphan_in_progress"))
    if not isinstance(kinds, list) or not all(isinstance(k, str) for k in kinds):
        return {"ok": False, "error": "kinds must be list[str]"}
    loop_running = pm.status("loop").state == ProcState.RUNNING
    cleared: list[str] = []
    flipped: list[str] = []
    with _StateLock():
        s = _read_state()
        kept: list[dict[str, Any]] = []
        for it in s.get("items", []):
            st = it.get("status") or ""
            if any(st == k or st.startswith(k + ":") for k in kinds):
                cleared.append(it.get("id"))
                continue
            if do_orphan and st == "in_progress" and not loop_running:
                it["status"] = "pending"
                it["recovered_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                flipped.append(it.get("id"))
            kept.append(it)
        s["items"] = kept
        _write_state(s)
    _append_decision(
        "human",
        "state-cleanup",
        "-",
        "ok",
        f"cleared={len(cleared)} flipped_orphans={len(flipped)} kinds={','.join(kinds)}",
    )
    return {"ok": True, "cleared": cleared, "reset_to_pending": flipped}


# ---------- iteration auto-retention (REL-001) ----------

_NON_TERMINAL_STATUSES = frozenset(
    {"pending", "queued", "in_progress", "in_review", "needs_revision"}
)

_MERGE_TERMINAL_STATUSES = frozenset({"accepted", "rejected", "failed", "conflict"})


def _protected_iter_names(
    state: dict[str, Any],
    all_dirs: list[pathlib.Path],
) -> set[str]:
    """Build set of iter dir names that must NOT be deleted.

    Protection rules:
      1. Current (alphabetically last) iter dir is always protected.
      2. For each item with a non-terminal status, protect its lastIter.
      3. For each non-terminal merge job in merge-jobs.json, protect the
         lastIter of the item it references (via itemId).
    """
    protected: set[str] = set()

    if not all_dirs:
        return protected

    # 1. Current iter = alphabetically last
    current_name = all_dirs[-1].name
    protected.add(current_name)

    # 2. Non-terminal tasks
    items = state.get("items") if isinstance(state, dict) else None
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            status = item.get("status")
            last_iter = item.get("lastIter")
            if status in _NON_TERMINAL_STATUSES and isinstance(last_iter, str):
                protected.add(last_iter)

    # 3. Non-terminal merge jobs
    #    Resolve state_dir from the iter dirs we have (they all share a parent).
    state_dir = all_dirs[0].parent
    merge_jobs_path = state_dir / "merge-jobs.json"
    if merge_jobs_path.exists():
        merge_raw = _load_json(merge_jobs_path)
        if isinstance(merge_raw, dict):
            jobs = merge_raw.get("jobs")
            if isinstance(jobs, list):
                # Build item_id -> lastIter lookup from state
                item_lookup: dict[str, str] = {}
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            iid = item.get("id")
                            li = item.get("lastIter")
                            if isinstance(iid, str) and isinstance(li, str):
                                item_lookup[iid] = li
                for job in jobs:
                    if not isinstance(job, dict):
                        continue
                    job_status = job.get("status")
                    if job_status in _MERGE_TERMINAL_STATUSES:
                        continue
                    item_id = job.get("itemId")
                    if isinstance(item_id, str) and item_id in item_lookup:
                        protected.add(item_lookup[item_id])

    return protected


def select_iters_to_prune(
    iter_dirs: list[pathlib.Path],
    *,
    now: float,
    keep_days: int,
    keep_min: int,
    protected_ids: set[str],
) -> list[pathlib.Path]:
    """Pure function: select which iter dirs are safe to delete.

    A dir is prunable if ALL of:
      - older than keep_days (mtime < now - keep_days * 86400)
      - not in protected_ids
      - not among the keep_min most recent dirs (sorted by name, ascending)
    """
    if not iter_dirs:
        return []

    # Sorted by name (alphabetical = chronological for iter-NNNN)
    sorted_dirs = sorted(iter_dirs, key=lambda p: p.name)

    # keep_min most recent = last keep_min entries by name
    kept_by_min: set[str] = set()
    if keep_min > 0:
        kept_by_min = {d.name for d in sorted_dirs[-keep_min:]}

    cutoff = now - keep_days * 86400.0
    prunable: list[pathlib.Path] = []

    for d in sorted_dirs:
        if d.name in protected_ids:
            continue
        if d.name in kept_by_min:
            continue
        try:
            mtime = d.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            prunable.append(d)

    return prunable


def prune_iters(*, state_dir_override: pathlib.Path | None = None) -> dict[str, Any]:
    """Never-crash wrapper: prune old iteration directories.

    Reads config from env (HEPHAESTUS_KEEP_ITERS_DAYS, HEPHAESTUS_KEEP_ITERS_MIN),
    builds protected set, calls select_iters_to_prune, deletes selected dirs.
    """
    try:
        import os
        import shutil

        keep_days = int(os.environ.get("HEPHAESTUS_KEEP_ITERS_DAYS", "30"))
        keep_min = int(os.environ.get("HEPHAESTUS_KEEP_ITERS_MIN", "20"))

        # Resolve state dir
        sd = state_dir_override if state_dir_override is not None else _state_dir()

        if not sd.exists():
            return {"ok": True, "pruned": [], "kept": 0, "protected": 0}

        # Gather iter dirs (sorted by name)
        all_dirs = sorted(
            [p for p in sd.glob("iter-*") if p.is_dir()],
            key=lambda p: p.name,
        )

        if not all_dirs:
            return {"ok": True, "pruned": [], "kept": 0, "protected": 0}

        # Build protected set
        state = _read_state() if state_dir_override is None else _load_state_from(sd)
        protected_ids = _protected_iter_names(state, all_dirs)

        # Select dirs to prune
        to_prune = select_iters_to_prune(
            all_dirs,
            now=time.time(),
            keep_days=keep_days,
            keep_min=keep_min,
            protected_ids=protected_ids,
        )

        # Delete
        pruned_names: list[str] = []
        for d in to_prune:
            shutil.rmtree(d, ignore_errors=True)
            pruned_names.append(d.name)
            log.info("pruned old iter dir: %s", d.name)

        kept = len(all_dirs) - len(pruned_names)
        protected_count = len(protected_ids)

        return {
            "ok": True,
            "pruned": pruned_names,
            "kept": kept,
            "protected": protected_count,
        }
    except Exception as e:
        log.error("prune_iters failed: %s", e)
        return {"ok": False, "error": str(e)}


def _load_state_from(sd: pathlib.Path) -> dict[str, Any]:
    """Load work-state.json from an explicit state dir (used by prune_iters with override)."""
    p = sd / "work-state.json"
    if not p.exists():
        return {"items": []}
    try:
        raw = p.read_text(encoding="utf-8")
        if not raw.strip():
            return {"items": []}
        loaded: dict[str, Any] = json.loads(raw)
        return loaded
    except Exception:
        log.debug("_load_state_from: failed to parse %s", p, exc_info=True)
        return {"items": []}


# ---------- state builder ----------


def _build_state_uncached() -> dict[str, Any]:
    """Build full state snapshot from disk (no caching)."""
    state = _read_state()
    _sd = _state_dir()
    current = _load_json(_sd / "current.json") or {"itemId": None, "phase": "idle", "detail": ""}
    # roll up tokens across all iters (cheap once parsed — JSONL files are small per-iter)
    iter_dirs = _all_iter_dirs()
    total_tokens = 0
    for d in iter_dirs:
        total_tokens += _iter_cost(d)["total"]
    return {
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "current": current,
        "current_iter": _current_iter_block(),
        "summary": _summarize(state),
        "items": sorted(
            state.get("items", []),
            key=lambda it: (int(it.get("orderIndex", 0) or 0), str(it.get("id", ""))),
        ),
        "log_tail": _log_tail(),
        "decisions": _read_decisions(limit=20),
        "totals": {"tokens": total_tokens, "iters": len(iter_dirs)},
        "git": {
            "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=_active_git()[0]),
            "head": _run(["git", "rev-parse", "--short", "HEAD"], cwd=_active_git()[0]),
            "auto_branches": _git_branches(),
            "recent_commits": _git_recent_commits(),
        },
        # Same payload under both keys: legacy "loop" + "loopStatus" (the name the
        # frontend store/types use). Without the alias the dashboard never reflects a
        # running loop, so "Запуск" looks like it did nothing.
        "loop": _loop_status(),
        "loopStatus": _loop_status(),
        "config": _config_effective(),
        "killswitch_present": (_sd / "stop").exists(),
    }


def build_state() -> dict[str, Any]:
    """Build full state snapshot. Cached with mtime-based invalidation."""
    global _state_cache, _cache_key
    if _state_cache is not None and not _cache_invalidated():
        return _state_cache
    state = _build_state_uncached()
    _cache_key = _compute_cache_key()
    _state_cache = state
    return state
