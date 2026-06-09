"""Pure dependency-graph helpers over work-state items (#4).

Work-state items are plain ``dict[str, Any]`` with at least ``id`` and ``status`` and
optionally ``dependsOn``/``blocks`` (camelCase). All helpers are total functions that
never raise on missing keys, tolerate dangling/cyclic data, and are ``mypy --strict`` clean.

A ``by_id`` argument is always ``{item["id"]: item}`` over the full item list.
"""

from __future__ import annotations

from typing import Any

_DONE_STATUSES = frozenset({"done", "merged"})


def is_done(item: dict[str, Any]) -> bool:
    """True when the item is in a terminal-success status (done/merged)."""
    return item.get("status") in _DONE_STATUSES


def deps_satisfied(item: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> bool:
    """True when every dependency of ``item`` is done.

    A dependency id MISSING from ``by_id`` (a deleted prerequisite) is treated as
    SATISFIED so a removed task never deadlocks its dependents. Empty/absent
    ``dependsOn`` → True.
    """
    for dep_id in item.get("dependsOn", []) or []:
        dep = by_id.get(dep_id)
        if dep is not None and not is_done(dep):
            return False
    return True


def ready(item: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> bool:
    """True when the item is ``queued`` AND all its dependencies are satisfied."""
    return item.get("status") == "queued" and deps_satisfied(item, by_id)


def has_runnable(items: list[dict[str, Any]]) -> bool:
    """True if any item is ``in_progress`` OR any item is ``ready``.

    This is the single definition of "is there work the loop can do right now" shared by
    the driver reconciler and the loop's exit check — a dead-end (queued items whose deps
    are not done) is NOT runnable.
    """
    by_id = {it.get("id"): it for it in items}
    for it in items:
        if it.get("status") == "in_progress":
            return True
        if ready(it, by_id):  # type: ignore[arg-type]
            return True
    return False


def unfinished_ancestors(task_id: str, by_id: dict[str, dict[str, Any]]) -> set[str]:
    """Transitive set of ``dependsOn`` ancestor ids of ``task_id`` that are NOT done.

    Walks ``dependsOn`` edges from the task. Done ancestors are pruned (not collected and
    not recursed through). Missing ids are skipped. Cyclic data terminates via a visited
    set. ``task_id`` itself is never included.
    """
    result: set[str] = set()
    visited: set[str] = {task_id}
    start = by_id.get(task_id)
    stack: list[str] = list(start.get("dependsOn", []) or []) if start is not None else []
    while stack:
        dep_id = stack.pop()
        if dep_id in visited:
            continue
        visited.add(dep_id)
        dep = by_id.get(dep_id)
        if dep is None:
            continue  # missing prereq — do not recurse, do not collect
        if is_done(dep):
            continue  # done ancestor — prune it and its parents
        result.add(dep_id)
        stack.extend(dep.get("dependsOn", []) or [])
    return result


def would_create_cycle(
    task_id: str, new_dep_id: str, by_id: dict[str, dict[str, Any]]
) -> bool:
    """True if adding edge ``task_id --dependsOn--> new_dep_id`` would create a cycle.

    A cycle forms iff ``new_dep_id == task_id`` OR ``task_id`` is already reachable from
    ``new_dep_id`` by following existing ``dependsOn`` edges. DFS with a visited set so
    missing ids and pre-existing cycles never cause an infinite loop.
    """
    if new_dep_id == task_id:
        return True
    visited: set[str] = set()
    stack: list[str] = [new_dep_id]
    while stack:
        cur = stack.pop()
        if cur == task_id:
            return True
        if cur in visited:
            continue
        visited.add(cur)
        node = by_id.get(cur)
        if node is None:
            continue
        stack.extend(node.get("dependsOn", []) or [])
    return False


def recompute_blocks(items: list[dict[str, Any]]) -> None:
    """Rebuild every item's ``blocks`` list as the inverse of all ``dependsOn`` edges.

    If X dependsOn Y, then Y["blocks"] contains X. Only ids that exist as items get a
    blocks entry; each list is sorted for determinism; items with no dependents get
    ``blocks = []``. Mutates ``items`` in place.
    """
    by_id = {it.get("id"): it for it in items}
    blocks: dict[Any, list[str]] = {it.get("id"): [] for it in items}
    for it in items:
        dependent = it.get("id")
        if dependent is None:
            continue
        for dep_id in it.get("dependsOn", []) or []:
            if dep_id in by_id:
                blocks[dep_id].append(dependent)
    for it in items:
        it["blocks"] = sorted(blocks.get(it.get("id"), []))
