"""Unit tests for task_graph — DAG, conflict groups, reorder predicate. Cross-platform, no bash."""

from __future__ import annotations

from app.core.task_graph import (
    _norm_touch,
    apply_reorder,
    assign_conflict_groups,
    build_graph,
    can_reorder,
    detect_cycles,
    topo_order,
)


def test_norm_touch_windows() -> None:
    assert _norm_touch("a\\B.py:10") == _norm_touch("a/b.py")
    assert _norm_touch("src/X.py:42") == "src/x.py"
    assert _norm_touch("  ./src/x.py  ") == "src/x.py"


def test_assign_conflict_groups_shared_file() -> None:
    items = [
        {"id": "t1", "touches": ["src/x.py:42"]},
        {"id": "t2", "touches": ["src\\x.py"]},
        {"id": "t3", "touches": ["src/other.py"]},
    ]
    groups = assign_conflict_groups(items)
    assert groups["t1"] is not None
    assert groups["t1"] == groups["t2"]
    assert groups["t1"].startswith("cg-")
    assert groups["t3"] is None


def test_conflict_group_singleton_none() -> None:
    items = [{"id": "solo", "touches": ["a.py"]}]
    assert assign_conflict_groups(items) == {"solo": None}


def test_topo_order_respects_deps() -> None:
    items = [
        {"id": "C", "dependsOn": ["B"], "touches": [], "orderIndex": 2},
        {"id": "A", "dependsOn": [], "touches": [], "orderIndex": 0},
        {"id": "B", "dependsOn": ["A"], "touches": [], "orderIndex": 1},
    ]
    g = build_graph(items)
    assert topo_order(g) == ["A", "B", "C"]


def test_topo_order_stable_tiebreak() -> None:
    items = [
        {"id": "z", "dependsOn": [], "touches": [], "orderIndex": 0},
        {"id": "a", "dependsOn": [], "touches": [], "orderIndex": 0},
        {"id": "m", "dependsOn": [], "touches": [], "orderIndex": 5},
    ]
    g = build_graph(items)
    assert topo_order(g) == ["a", "z", "m"]


def test_detect_cycles() -> None:
    items = [
        {"id": "A", "dependsOn": ["B"], "touches": [], "orderIndex": 0},
        {"id": "B", "dependsOn": ["A"], "touches": [], "orderIndex": 1},
    ]
    g = build_graph(items)
    cycles = detect_cycles(g)
    assert len(cycles) == 1
    assert set(cycles[0]) == {"A", "B"}
    g2 = build_graph([{"id": "X", "dependsOn": [], "touches": [], "orderIndex": 0}])
    assert detect_cycles(g2) == []


def test_topo_order_breaks_llm_cycle() -> None:
    items = [
        {"id": "A", "dependsOn": ["B"], "touches": [], "orderIndex": 0},
        {"id": "B", "dependsOn": ["A"], "touches": [], "orderIndex": 1},
        {"id": "C", "dependsOn": [], "touches": [], "orderIndex": 2},
    ]
    g = build_graph(items)
    order = topo_order(g)
    assert set(order) == {"A", "B", "C"}
    assert order.index("C") < order.index("A") or order.index("C") < order.index("B")


def _items() -> list[dict]:
    return [
        {"id": "A", "dependsOn": [], "touches": ["a.py"], "orderIndex": 0},
        {"id": "B", "dependsOn": ["A"], "touches": ["b.py"], "orderIndex": 1},
        {"id": "C", "dependsOn": [], "touches": ["c.py"], "orderIndex": 2},
    ]


def test_can_reorder_ok() -> None:
    items = _items()
    ok, reason = can_reorder(items, ["A", "C", "B"])
    assert ok is True
    assert reason == ""


def test_can_reorder_breaks_dependency() -> None:
    items = _items()
    ok, reason = can_reorder(items, ["B", "A", "C"])
    assert ok is False
    assert "breaks dependency A before B" in reason


def test_can_reorder_set_mismatch() -> None:
    items = _items()
    ok, reason = can_reorder(items, ["A", "B"])
    assert ok is False
    assert "reorder set mismatch" in reason


def test_can_reorder_dangling_dep_ignored() -> None:
    items = [
        {"id": "A", "dependsOn": ["ghost"], "touches": ["a.py"], "orderIndex": 0},
        {"id": "B", "dependsOn": [], "touches": ["b.py"], "orderIndex": 1},
    ]
    ok, reason = can_reorder(items, ["B", "A"])
    assert ok is True


def test_can_reorder_conflict_order() -> None:
    items = [
        {"id": "A", "dependsOn": [], "touches": ["src/x.py"], "orderIndex": 0},
        {"id": "B", "dependsOn": [], "touches": ["src/x.py:9"], "orderIndex": 1},
    ]
    ok, reason = can_reorder(items, ["B", "A"])
    assert ok is False
    assert "violates conflict order" in reason
    assert "A must stay before B" in reason


def test_can_reorder_conflict_pairwise_not_transitive() -> None:
    items = [
        {"id": "A", "dependsOn": [], "touches": ["src/x.py"], "orderIndex": 0},
        {"id": "B", "dependsOn": [], "touches": ["src/x.py", "src/y.py"], "orderIndex": 1},
        {"id": "C", "dependsOn": [], "touches": ["src/y.py"], "orderIndex": 2},
    ]
    ok, reason = can_reorder(items, ["A", "B", "C"])
    assert ok is True, reason
    ok2, reason2 = can_reorder(items, ["C", "B", "A"])
    assert ok2 is False
    assert "violates conflict order" in reason2


def test_apply_reorder_dense_indices() -> None:
    items = _items()
    out = apply_reorder(items, ["A", "C", "B"])
    by_id = {it["id"]: it for it in out}
    assert by_id["A"]["orderIndex"] == 0
    assert by_id["C"]["orderIndex"] == 1
    assert by_id["B"]["orderIndex"] == 2
    assert items[1]["id"] == "B" and items[1]["orderIndex"] == 1
