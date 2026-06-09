"""Cost aggregation API: roll up token usage and cost across all iteration dirs.

Follows the codebase convention (see connections.py): return a plain dict on success
with `response_model=None` so the return type type-checks.
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter

from app.core.event_cost import _iter_cost
from app.core.helpers import _all_iter_dirs
from app.core.state import _read_state

router = APIRouter()


def _aggregate_cost() -> dict[str, Any]:
    """Roll up cost/token data across all iteration dirs.

    Returns:
        dict with keys: totalCostUsd, totalTokens, topTasks, budgetUsd
    """
    total_cost = 0.0
    total_tokens = 0

    try:
        for d in _all_iter_dirs():
            try:
                result = _iter_cost(d)
                total_cost += result.get("cost_usd", 0.0)
                total_tokens += result.get("total", 0)
            except Exception:
                continue
    except Exception:
        pass

    # Read per-task cost from state items (top 10 by cost)
    top_tasks: list[dict[str, Any]] = []
    try:
        state = _read_state()
        items = state.get("items", []) if isinstance(state, dict) else []
        # Sort items by cost_usd descending, take top 10
        with_cost = [
            {
                "id": it.get("id", ""),
                "title": it.get("title", ""),
                "status": it.get("status", ""),
                "costUsd": float(it.get("cost_usd", 0) or 0),
            }
            for it in items
            if it.get("cost_usd")
        ]
        with_cost.sort(key=lambda x: x["costUsd"], reverse=True)
        top_tasks = with_cost[:10]
    except Exception:
        pass

    # Read budget from env var (null when 0/unset)
    budget_raw = os.environ.get("HEPHAESTUS_COST_BUDGET_USD", "")
    budget_usd: float | None = None
    try:
        val = float(budget_raw)
        if val > 0:
            budget_usd = val
    except (ValueError, TypeError):
        pass

    return {
        "totalCostUsd": round(total_cost, 5),
        "totalTokens": total_tokens,
        "topTasks": top_tasks,
        "budgetUsd": budget_usd,
    }


@router.get("/api/v1/costs", response_model=None)
def get_costs() -> dict[str, Any]:
    """Return aggregated cost data across all iteration dirs.

    Never returns 500 — all exceptions are caught inside _aggregate_cost().
    """
    try:
        data = _aggregate_cost()
        return {"ok": True, **data}
    except Exception:
        return {
            "ok": True,
            "totalCostUsd": 0.0,
            "totalTokens": 0,
            "topTasks": [],
            "budgetUsd": None,
        }
