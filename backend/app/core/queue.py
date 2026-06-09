"""Queue CRUD operations — ported from dashboard/server.py:753-831.

Add, reorder, delete, patch, and requeue items in the work-state queue.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from app.core.decisions import _append_decision
from app.core.helpers import _DEFAULT_ACCEPTANCE_ADHOC
from app.core.state import _read_state, _StateLock, _write_state

log = logging.getLogger("hephaestus.backend.queue")


def _try_broadcast_state() -> None:
    """Try to broadcast state via WS manager. Lazy import to avoid circular deps."""
    try:
        import asyncio

        from app.services.ws_manager import manager

        loop = getattr(asyncio, "_get_running_loop", lambda: None)()
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
        if loop and not loop.is_closed():
            loop.create_task(manager.broadcast_state())
    except Exception:
        pass  # Import fails or manager not initialized — skip silently


def _queue_add(item: dict[str, Any]) -> dict[str, Any]:
    if not item.get("id"):
        item["id"] = f"adhoc-{int(time.time())}-{os.urandom(2).hex()}"
    # Input validation
    if len(item.get("title", "")) > 500:
        raise ValueError("title too long (max 500 characters)")
    if len(item.get("touches", [])) > 50:
        raise ValueError("too many touches (max 50)")
    if len(str(item.get("proposal", ""))) > 50000:
        raise ValueError("proposal too long (max 50000 characters)")
    item.setdefault("title", item["id"])
    item.setdefault("plan_file", "AD-HOC")
    item.setdefault("plan_section", "")
    item.setdefault("wave", "AD-HOC")
    item.setdefault("touches", [])
    # Mandatory acceptance — gives the implementer a concrete success criterion AND
    # gives reviewers something to grade the test_score rubric against. Without this,
    # ad-hoc items succeed-or-fail by `verify` alone, which doesn't catch "you only
    # fixed one of the four callers" or "the test passes without your change".
    if not item.get("acceptance"):
        item["acceptance"] = _DEFAULT_ACCEPTANCE_ADHOC
    item["status"] = "pending"
    item["attempts"] = 0
    item["branch"] = None
    with _StateLock():
        s = _read_state()
        s["items"] = [it for it in s.get("items", []) if it.get("id") != item["id"]]
        max_order = max((int(it.get("orderIndex", 0) or 0) for it in s["items"]), default=-1)
        item.setdefault("orderIndex", max_order + 1)
        s["items"].append(item)
        _write_state(s)
    _try_broadcast_state()
    return {"ok": True, "id": item["id"]}


def _reorder(new_order: list[str]) -> dict[str, Any]:
    """Validate + apply a full reorder. Single source of truth: task_graph.can_reorder."""
    from app.core.task_graph import apply_reorder, can_reorder

    with _StateLock():
        s = _read_state()
        items = s.get("items", [])
        ok, reason = can_reorder(items, new_order)
        if not ok:
            return {"ok": False, "error": reason}
        s["items"] = apply_reorder(items, new_order)
        _write_state(s)
    _try_broadcast_state()
    return {"ok": True, "order": new_order}


def _queue_move_top(qid: str) -> dict[str, Any]:
    """Move-top = reorder with [qid] first; refuses if it breaks a dependency/conflict order."""
    with _StateLock():
        s = _read_state()
        items: list[dict[str, Any]] = s.get("items", [])
        current: list[Any] = [it.get("id") for it in items]
        if qid not in current:
            return {"ok": False, "error": "id not found"}
    new_order: list[str] = [qid] + [i for i in current if i != qid]
    return _reorder(new_order)


def _queue_delete(qid: str) -> dict[str, Any]:
    with _StateLock():
        s = _read_state()
        n_before = len(s.get("items", []))
        s["items"] = [it for it in s.get("items", []) if it.get("id") != qid]
        if len(s["items"]) == n_before:
            return {"ok": False, "error": "id not found"}
        _write_state(s)
    _try_broadcast_state()
    return {"ok": True}


def _queue_patch(qid: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Edit fields of an item. Only pending items can be edited freely."""
    EDITABLE = {"title", "proposal", "why", "touches", "acceptance", "plan_section", "agent_override",
                "modelOverride", "complexity"}
    VALID_STATUSES = {"pending", "in_progress", "done", "merged", "needs_revision", "discarded",
                      "failed:opencode", "failed:verify", "failed:no-changes", "failed:timeout", "failed:refused"}
    # Validate touches is a list if provided
    if "touches" in patch and not isinstance(patch["touches"], list):
        raise ValueError("touches must be a list")
    # Validate status is a valid string if provided
    if "status" in patch and patch["status"] not in VALID_STATUSES:
        raise ValueError(f"invalid status: {patch['status']}")
    with _StateLock():
        s = _read_state()
        for it in s.get("items", []):
            if it.get("id") == qid:
                if it.get("status") not in ("pending", "needs_revision"):
                    return {"ok": False, "error": f"cannot edit item in status {it.get('status')}"}
                for k, v in patch.items():
                    if k in EDITABLE:
                        it[k] = v
                mo = it.get("modelOverride")
                if mo is not None:
                    from app.models.workspace import AgentRef
                    try:
                        AgentRef.model_validate(mo)
                    except Exception as exc:
                        raise ValueError("modelOverride must be {provider, model[, agent]} or null") from exc
                _write_state(s)
                _try_broadcast_state()
                return {"ok": True, "id": qid}
        return {"ok": False, "error": "id not found"}


def add_proposals_to_queue(
    proposals: list[dict[str, Any]],
    *,
    epic_id: str | None = None,
    source: str = "",
) -> None:
    """Append proposals as pending queue items, skipping ids already present.

    Uses the same field mapping as ``_scan_import`` (rationale→why, default
    acceptance/touches, status="pending", epicId=epic_id, dependsOn=[]).
    Idempotent: calling twice with the same ids does not duplicate items.
    """
    with _StateLock():
        s = _read_state()
        existing_ids = {it.get("id") for it in s.get("items", [])}
        for p in proposals:
            pid = p.get("id")
            if not pid or not p.get("title") or not p.get("proposal"):
                continue
            if pid in existing_ids:
                continue
            acceptance = p.get("acceptance") or _DEFAULT_ACCEPTANCE_ADHOC
            item: dict[str, Any] = {
                "id": pid,
                "title": p.get("title", pid),
                "proposal": p.get("proposal", ""),
                "why": p.get("rationale", ""),
                "acceptance": acceptance,
                "touches": p.get("touches", []) or [],
                "status": "pending",
                "attempts": 0,
                "branch": None,
                "source": source,
                "dependsOn": [],
            }
            if epic_id is not None:
                item["epicId"] = epic_id
            s["items"].append(item)
            existing_ids.add(pid)
        _write_state(s)


_RUNNABLE_TARGET_STATUSES = ("pending", "needs_revision")


def _run_task(item_id: str) -> dict[str, Any]:
    """Send a single task to run: queue it AND its whole unfinished prerequisite chain.

    Flips the target plus each of its eligible (pending/needs_revision) unfinished
    ancestors to ``queued`` so the user's send brings the dependency chain along.
    Already-queued/in_progress ancestors are left as-is; done/merged/failed:* ancestors
    are NOT flipped (a failed prereq stays a dead-end until the user requeues it).

    Returns {"ok": True, "id", "status": "queued"} on success.
    Not found -> {"ok": False, "error": "id not found"} (route maps to 404).
    Wrong status -> {"ok": False, "error": ..., "status": <current>} (route maps to 409).
    """
    from app.core.deps import unfinished_ancestors

    with _StateLock():
        s = _read_state()
        items = s.get("items", [])
        by_id = {it.get("id"): it for it in items}
        target = by_id.get(item_id)
        if target is None:
            return {"ok": False, "error": "id not found"}
        cur = target.get("status")
        if cur not in _RUNNABLE_TARGET_STATUSES:
            return {"ok": False, "error": f"cannot run item in status {cur}", "status": cur}
        targets = {item_id} | unfinished_ancestors(item_id, by_id)
        for tid in targets:
            it = by_id.get(tid)
            if it is not None and it.get("status") in _RUNNABLE_TARGET_STATUSES:
                it["status"] = "queued"
        _write_state(s)
        _try_broadcast_state()
        return {"ok": True, "id": item_id, "status": "queued"}


def _run_tasks(ids: list[str]) -> dict[str, Any]:
    """Bulk send-to-run. Queue every eligible id AND its unfinished prerequisite chain.

    Per requested id: missing -> skipped {"id", "status": None}; target ineligible (status
    not pending/needs_revision) -> skipped {"id", "status": <cur>}; else flip the target +
    its eligible unfinished ancestors to queued. Accumulates ALL flipped ids (deduped,
    discovery order preserved) into ``queued``.

    Returns {"ok": True, "queued": [ids...], "skipped": [{"id", "status"}...]}.
    """
    from app.core.deps import unfinished_ancestors

    queued: list[str] = []
    seen: set[str] = set()
    skipped: list[dict[str, Any]] = []
    with _StateLock():
        s = _read_state()
        items = s.get("items", [])
        by_id = {it.get("id"): it for it in items}
        changed = False
        for iid in ids:
            it = by_id.get(iid)
            if it is None:
                skipped.append({"id": iid, "status": None})
                continue
            cur = it.get("status")
            if cur not in _RUNNABLE_TARGET_STATUSES:
                skipped.append({"id": iid, "status": cur})
                continue
            targets = [iid, *sorted(unfinished_ancestors(iid, by_id))]
            for tid in targets:
                tit = by_id.get(tid)
                if tit is not None and tit.get("status") in _RUNNABLE_TARGET_STATUSES:
                    tit["status"] = "queued"
                    changed = True
                    if tid not in seen:
                        seen.add(tid)
                        queued.append(tid)
        if changed:
            _write_state(s)
    if queued:
        _try_broadcast_state()
    return {"ok": True, "queued": queued, "skipped": skipped}


def _unqueue_task(item_id: str) -> dict[str, Any]:
    """Un-send: flip queued -> pending (only before it starts running).

    queued -> pending: {"ok": True, "id", "status": "pending"}.
    in_progress -> {"ok": False, "error": "already in progress"} (route maps to 409).
    Not found -> {"ok": False, "error": "id not found"} (route maps to 404).
    """
    with _StateLock():
        s = _read_state()
        for it in s.get("items", []):
            if it.get("id") == item_id:
                cur = it.get("status")
                if cur == "in_progress":
                    return {"ok": False, "error": "already in progress", "status": cur}
                if cur != "queued":
                    return {"ok": False, "error": f"cannot unqueue item in status {cur}", "status": cur}
                it["status"] = "pending"
                _write_state(s)
                _try_broadcast_state()
                return {"ok": True, "id": item_id, "status": "pending"}
        return {"ok": False, "error": "id not found"}


def _patch_deps(item_id: str, depends_on: list[str]) -> dict[str, Any]:
    """Set an item's ``dependsOn`` list and recompute every item's ``blocks`` inverse.

    Validates: target exists; every dep id exists; no self-reference; no dep that would
    create a cycle. On any failure returns {"ok": False, "error", "offending"} (route maps
    "not found" -> 404, else 400) and leaves state untouched.

    On success: target["dependsOn"] = list(depends_on); recompute_blocks(items); persist.
    Returns {"ok": True, "id", "dependsOn": [...]}.
    """
    from app.core.deps import recompute_blocks, would_create_cycle

    with _StateLock():
        s = _read_state()
        items = s.get("items", [])
        by_id = {it.get("id"): it for it in items}
        target = by_id.get(item_id)
        if target is None:
            return {"ok": False, "error": "id not found"}
        for dep in depends_on:
            if dep == item_id:
                return {"ok": False, "error": "self-dependency not allowed", "offending": item_id}
            if dep not in by_id:
                return {"ok": False, "error": f"unknown dependency: {dep}", "offending": dep}
            if would_create_cycle(item_id, dep, by_id):
                return {"ok": False, "error": f"cycle: {dep}", "offending": dep}
        target["dependsOn"] = list(depends_on)
        recompute_blocks(items)
        _write_state(s)
        _try_broadcast_state()
        return {"ok": True, "id": item_id, "dependsOn": list(depends_on)}


def _queue_requeue(qid: str) -> dict[str, Any]:
    """Flip ANY status back to pending (done/merged/failed/needs_revision/discarded). Preserves branch field."""
    with _StateLock():
        s = _read_state()
        for it in s.get("items", []):
            if it.get("id") == qid:
                old_status = it.get("status")
                old_branch = it.get("branch")
                if old_branch:
                    it.setdefault("previousBranches", []).append(old_branch)
                    it["branch"] = None
                it["status"] = "pending"
                it["requeued_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                _write_state(s)
                _try_broadcast_state()
                _append_decision("human", "requeue-item", qid, "ok", f"was {old_status}")
                return {"ok": True, "id": qid, "was": old_status}
        return {"ok": False, "error": "id not found"}


def _queue_requeue_failed() -> dict[str, Any]:
    """Bulk-requeue ALL items with failed:* status back to pending.

    Returns count of requeued items.
    """
    with _StateLock():
        s = _read_state()
        requeued: list[str] = []
        for it in s.get("items", []):
            status = it.get("status", "")
            if status.startswith("failed"):
                old_branch = it.get("branch")
                if old_branch:
                    it.setdefault("previousBranches", []).append(old_branch)
                    it["branch"] = None
                it["status"] = "pending"
                it["requeued_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                requeued.append(it.get("id", "?"))
                _append_decision("human", "requeue-failed", it.get("id", "?"), "ok", f"was {status}")
        if requeued:
            _write_state(s)
            _try_broadcast_state()
        return {"ok": True, "requeued": requeued, "count": len(requeued)}
