"""#4 — pure dependency-graph helpers in app.core.deps.

Covers deps_satisfied / ready / has_runnable / unfinished_ancestors /
would_create_cycle / recompute_blocks. All operate over plain work-state item dicts.
"""

from __future__ import annotations

from app.core import deps


def _by_id(items: list[dict]) -> dict[str, dict]:
    return {it["id"]: it for it in items}


# ---------- is_done ----------


def test_is_done() -> None:
    assert deps.is_done({"status": "done"}) is True
    assert deps.is_done({"status": "merged"}) is True
    assert deps.is_done({"status": "queued"}) is False
    assert deps.is_done({}) is False


# ---------- deps_satisfied ----------


def test_deps_satisfied_all_done() -> None:
    items = [
        {"id": "a", "status": "done"},
        {"id": "b", "status": "merged"},
        {"id": "c", "status": "queued", "dependsOn": ["a", "b"]},
    ]
    by_id = _by_id(items)
    assert deps.deps_satisfied(by_id["c"], by_id) is True


def test_deps_satisfied_one_pending() -> None:
    items = [
        {"id": "a", "status": "done"},
        {"id": "b", "status": "pending"},
        {"id": "c", "status": "queued", "dependsOn": ["a", "b"]},
    ]
    by_id = _by_id(items)
    assert deps.deps_satisfied(by_id["c"], by_id) is False


def test_deps_satisfied_missing_dep_treated_satisfied() -> None:
    # A dep id absent from by_id (deleted prereq) must NOT deadlock — treated as satisfied.
    items = [{"id": "c", "status": "queued", "dependsOn": ["ghost"]}]
    by_id = _by_id(items)
    assert deps.deps_satisfied(by_id["c"], by_id) is True


def test_deps_satisfied_empty_or_absent() -> None:
    assert deps.deps_satisfied({"id": "c", "status": "queued", "dependsOn": []}, {}) is True
    assert deps.deps_satisfied({"id": "c", "status": "queued"}, {}) is True


# ---------- ready ----------


def test_ready_queued_and_satisfied_true() -> None:
    items = [
        {"id": "a", "status": "done"},
        {"id": "c", "status": "queued", "dependsOn": ["a"]},
    ]
    by_id = _by_id(items)
    assert deps.ready(by_id["c"], by_id) is True


def test_ready_pending_false() -> None:
    items = [{"id": "c", "status": "pending", "dependsOn": []}]
    by_id = _by_id(items)
    assert deps.ready(by_id["c"], by_id) is False


def test_ready_queued_unsatisfied_false() -> None:
    items = [
        {"id": "a", "status": "pending"},
        {"id": "c", "status": "queued", "dependsOn": ["a"]},
    ]
    by_id = _by_id(items)
    assert deps.ready(by_id["c"], by_id) is False


# ---------- has_runnable ----------


def test_has_runnable_in_progress_true() -> None:
    assert deps.has_runnable([{"id": "a", "status": "in_progress"}]) is True


def test_has_runnable_ready_queued_true() -> None:
    items = [
        {"id": "a", "status": "done"},
        {"id": "c", "status": "queued", "dependsOn": ["a"]},
    ]
    assert deps.has_runnable(items) is True


def test_has_runnable_only_pending_false() -> None:
    assert deps.has_runnable([{"id": "a", "status": "pending"}]) is False


def test_has_runnable_queued_with_unfinished_dep_false() -> None:
    # Dead-end: queued but its dep is not done → not ready → not runnable.
    items = [
        {"id": "a", "status": "failed:verify"},
        {"id": "c", "status": "queued", "dependsOn": ["a"]},
    ]
    assert deps.has_runnable(items) is False


def test_has_runnable_empty_false() -> None:
    assert deps.has_runnable([]) is False


# ---------- unfinished_ancestors ----------


def test_unfinished_ancestors_transitive_chain() -> None:
    # C -> B -> A, all unfinished
    items = [
        {"id": "a", "status": "pending"},
        {"id": "b", "status": "pending", "dependsOn": ["a"]},
        {"id": "c", "status": "queued", "dependsOn": ["b"]},
    ]
    by_id = _by_id(items)
    assert deps.unfinished_ancestors("c", by_id) == {"a", "b"}


def test_unfinished_ancestors_skips_done() -> None:
    # B is done — it and its ancestors are not collected (done ancestors pruned).
    items = [
        {"id": "a", "status": "pending"},
        {"id": "b", "status": "done", "dependsOn": ["a"]},
        {"id": "c", "status": "queued", "dependsOn": ["b"]},
    ]
    by_id = _by_id(items)
    assert deps.unfinished_ancestors("c", by_id) == set()


def test_unfinished_ancestors_tolerates_missing() -> None:
    items = [{"id": "c", "status": "queued", "dependsOn": ["ghost"]}]
    by_id = _by_id(items)
    assert deps.unfinished_ancestors("c", by_id) == set()


def test_unfinished_ancestors_terminates_on_cycle() -> None:
    # a <-> b cycle in dependsOn — must not infinite-loop.
    items = [
        {"id": "a", "status": "pending", "dependsOn": ["b"]},
        {"id": "b", "status": "pending", "dependsOn": ["a"]},
        {"id": "c", "status": "queued", "dependsOn": ["a"]},
    ]
    by_id = _by_id(items)
    assert deps.unfinished_ancestors("c", by_id) == {"a", "b"}


def test_unfinished_ancestors_excludes_self() -> None:
    items = [{"id": "a", "status": "pending", "dependsOn": ["a"]}]
    by_id = _by_id(items)
    assert "a" not in deps.unfinished_ancestors("a", by_id)


def test_unfinished_ancestors_diamond() -> None:
    # D depends on B and C; both depend on A (a diamond). A is collected once.
    items = [
        {"id": "a", "status": "pending"},
        {"id": "b", "status": "pending", "dependsOn": ["a"]},
        {"id": "c", "status": "pending", "dependsOn": ["a"]},
        {"id": "d", "status": "queued", "dependsOn": ["b", "c"]},
    ]
    by_id = _by_id(items)
    assert deps.unfinished_ancestors("d", by_id) == {"a", "b", "c"}


# ---------- would_create_cycle ----------


def test_would_create_cycle_direct_self() -> None:
    items = [{"id": "a", "status": "pending"}]
    by_id = _by_id(items)
    assert deps.would_create_cycle("a", "a", by_id) is True


def test_would_create_cycle_direct_2_cycle() -> None:
    # a already dependsOn b; adding b dependsOn a -> 2-cycle.
    items = [
        {"id": "a", "status": "pending", "dependsOn": ["b"]},
        {"id": "b", "status": "pending"},
    ]
    by_id = _by_id(items)
    assert deps.would_create_cycle("b", "a", by_id) is True


def test_would_create_cycle_transitive_3_cycle() -> None:
    # a -> b -> c (dependsOn); adding c dependsOn a -> 3-cycle.
    items = [
        {"id": "a", "status": "pending", "dependsOn": ["b"]},
        {"id": "b", "status": "pending", "dependsOn": ["c"]},
        {"id": "c", "status": "pending"},
    ]
    by_id = _by_id(items)
    assert deps.would_create_cycle("c", "a", by_id) is True


def test_would_create_cycle_no_cycle() -> None:
    items = [
        {"id": "a", "status": "pending"},
        {"id": "b", "status": "pending"},
    ]
    by_id = _by_id(items)
    assert deps.would_create_cycle("a", "b", by_id) is False


def test_would_create_cycle_tolerates_preexisting_cycle() -> None:
    # Pre-existing x<->y cycle must not hang the reachability DFS.
    items = [
        {"id": "x", "status": "pending", "dependsOn": ["y"]},
        {"id": "y", "status": "pending", "dependsOn": ["x"]},
        {"id": "z", "status": "pending"},
    ]
    by_id = _by_id(items)
    # z depends on x: reachable from x? x->y->x (cycle), never reaches z → no new cycle.
    assert deps.would_create_cycle("z", "x", by_id) is False


# ---------- recompute_blocks ----------


def test_recompute_blocks_inverse_correctness() -> None:
    items = [
        {"id": "a", "status": "pending"},
        {"id": "b", "status": "pending", "dependsOn": ["a"]},
        {"id": "c", "status": "pending", "dependsOn": ["a"]},
    ]
    deps.recompute_blocks(items)
    by_id = _by_id(items)
    assert by_id["a"]["blocks"] == ["b", "c"]  # sorted
    assert by_id["b"]["blocks"] == []
    assert by_id["c"]["blocks"] == []


def test_recompute_blocks_clears_stale() -> None:
    items = [
        {"id": "a", "status": "pending", "blocks": ["stale", "b"]},
        {"id": "b", "status": "pending", "dependsOn": []},
    ]
    deps.recompute_blocks(items)
    by_id = _by_id(items)
    assert by_id["a"]["blocks"] == []  # no item dependsOn a anymore
    assert by_id["b"]["blocks"] == []


def test_recompute_blocks_only_existing_ids() -> None:
    # A dependsOn a ghost id must not create a blocks entry on a non-existent item.
    items = [{"id": "b", "status": "pending", "dependsOn": ["ghost"]}]
    deps.recompute_blocks(items)
    assert items[0]["blocks"] == []
