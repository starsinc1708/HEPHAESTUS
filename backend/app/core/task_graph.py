"""DAG construction + conflict groups + reorder predicate — pure stdlib, cross-platform.

Single source of truth for the reorder predicate (umbrella §10.5).
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("hephaestus.backend.task_graph")


@dataclass
class GraphNode:
    id: str
    depends_on: list[str]
    touches: list[str]
    order_index: int
    conflict_group: str | None = None
    blocks: list[str] = field(default_factory=list)


@dataclass
class Graph:
    nodes: dict[str, GraphNode]
    forward: dict[str, list[str]]
    reverse: dict[str, list[str]]


def _norm_touch(t: str) -> str:
    """Normalize a touch path: strip ':LINE', backslash→slash, posix-normalize, casefold."""
    path = t.split(":", 1)[0].strip().replace("\\", "/")
    return os.path.normpath(path).replace("\\", "/").casefold()


class _UnionFind:
    def __init__(self, ids: list[str]) -> None:
        self._parent: dict[str, str] = {i: i for i in ids}

    def find(self, x: str) -> str:
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra


def assign_conflict_groups(items: list[dict[str, Any]]) -> dict[str, str | None]:
    """id -> conflict_group. Group = connected component by shared touches file.
    Key = 'cg-' + sha1(','.join(sorted(member_ids)))[:8]. Singleton → None."""
    all_ids = [it["id"] for it in items]
    file_to_ids: dict[str, list[str]] = {}
    for it in items:
        for t in it.get("touches", []) or []:
            file_to_ids.setdefault(_norm_touch(t), []).append(it["id"])
    uf = _UnionFind(all_ids)
    for ids in file_to_ids.values():
        for j in range(1, len(ids)):
            uf.union(ids[0], ids[j])
    buckets: dict[str, list[str]] = {}
    for i in all_ids:
        buckets.setdefault(uf.find(i), []).append(i)
    result: dict[str, str | None] = {}
    for members in buckets.values():
        if len(members) <= 1:
            result[members[0]] = None
        else:
            key = "cg-" + hashlib.sha1(",".join(sorted(members)).encode()).hexdigest()[:8]
            for m in members:
                result[m] = key
    return result


def build_graph(items: list[dict[str, Any]]) -> Graph:
    """Build DAG. Edges from depends_on; dangling deps (id not in items) dropped."""
    ids = {it["id"] for it in items}
    nodes: dict[str, GraphNode] = {}
    forward: dict[str, list[str]] = {}
    reverse: dict[str, list[str]] = {}
    groups = assign_conflict_groups(items)
    for it in items:
        nid = it["id"]
        deps = [d for d in (it.get("dependsOn") or []) if d in ids and d != nid]
        nodes[nid] = GraphNode(
            id=nid,
            depends_on=deps,
            touches=list(it.get("touches", []) or []),
            order_index=int(it.get("orderIndex", 0) or 0),
            conflict_group=groups.get(nid),
        )
        forward.setdefault(nid, []).extend(deps)
        for d in deps:
            reverse.setdefault(d, []).append(nid)
    for nid, node in nodes.items():
        node.blocks = sorted(reverse.get(nid, []))
    return Graph(nodes=nodes, forward=forward, reverse=reverse)


def detect_cycles(g: Graph) -> list[list[str]]:
    """Return list of cycles (each a list of ids). Empty = acyclic. DFS with colours."""
    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in g.nodes}
    cycles: list[list[str]] = []
    stack: list[str] = []

    def visit(n: str) -> None:
        color[n] = GREY
        stack.append(n)
        for dep in g.nodes[n].depends_on:
            if color.get(dep, BLACK) == GREY:
                i = stack.index(dep)
                cycles.append(stack[i:])
            elif color.get(dep, BLACK) == WHITE:
                visit(dep)
        stack.pop()
        color[n] = BLACK

    for n in sorted(g.nodes):
        if color[n] == WHITE:
            visit(n)
    return cycles


def topo_order(g: Graph) -> list[str]:
    """Stable Kahn topo-sort: tie-break by (order_index, id). On cycle, broken edges
    logged; cycle nodes appended at the end in id order."""
    indeg: dict[str, int] = {n: 0 for n in g.nodes}
    for n in g.nodes:
        for _dep in g.nodes[n].depends_on:
            indeg[n] += 1
    ready = sorted(
        (n for n in g.nodes if indeg[n] == 0),
        key=lambda n: (g.nodes[n].order_index, n),
    )
    out: list[str] = []
    while ready:
        n = ready.pop(0)
        out.append(n)
        for dependent in sorted(g.reverse.get(n, [])):
            indeg[dependent] -= 1
            if indeg[dependent] == 0:
                ready.append(dependent)
        ready.sort(key=lambda x: (g.nodes[x].order_index, x))
    if len(out) < len(g.nodes):
        leftover = sorted(n for n in g.nodes if n not in out)
        log.warning("topo_order: cycle detected, appending unresolved nodes: %s", leftover)
        out.extend(leftover)
    return out


def can_reorder(items: list[dict[str, Any]], new_order: list[str]) -> tuple[bool, str]:
    """Single source of truth for reorder validity (umbrella §10.5, D5).

    File conflict is checked PAIRWISE, NOT transitively (R6): only pairs of tasks that
    share a real file (touches ∩ != empty) constrain relative order.
    conflict_group / assign_conflict_groups is a cosmetic UI label only — never used here.
    """
    by_id = {it["id"]: it for it in items}
    if set(new_order) != set(by_id):
        return (False, "reorder set mismatch: ids added or dropped")
    pos = {id_: i for i, id_ in enumerate(new_order)}
    for it in items:
        x = it["id"]
        for dep in it.get("dependsOn", []) or []:
            if dep not in by_id:
                continue
            if pos[dep] > pos[x]:
                return (False, f"reorder breaks dependency {dep} before {x}")
    norm = {it["id"]: {_norm_touch(t) for t in (it.get("touches") or [])} for it in items}

    def _orig_rank(i: str) -> tuple[int, str]:
        return (int(by_id[i].get("orderIndex", 0) or 0), i)

    ids = sorted(by_id)  # deterministic pair enumeration → stable error messages
    for ai in range(len(ids)):
        for bi in range(ai + 1, len(ids)):
            a, b = ids[ai], ids[bi]
            if not (norm[a] & norm[b]):
                continue
            first, second = (a, b) if _orig_rank(a) < _orig_rank(b) else (b, a)
            if pos[first] > pos[second]:
                return (
                    False,
                    f"reorder violates conflict order: {first} must stay before "
                    f"{second} (shared files)",
                )
    return (True, "")


def apply_reorder(items: list[dict[str, Any]], new_order: list[str]) -> list[dict[str, Any]]:
    """Return a copy of items with order_index rewritten to match new_order (dense 0..n-1)."""
    pos = {id_: i for i, id_ in enumerate(new_order)}
    tail_base = len(new_order)
    out: list[dict[str, Any]] = []
    tail_seen = 0
    for it in items:
        copy = dict(it)
        if it["id"] in pos:
            copy["orderIndex"] = pos[it["id"]]
        else:
            copy["orderIndex"] = tail_base + tail_seen
            tail_seen += 1
        out.append(copy)
    out.sort(key=lambda c: c["orderIndex"])
    return out
