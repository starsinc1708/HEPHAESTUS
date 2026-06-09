"""Cost / token usage rollup for opencode JSONL streams — ported verbatim from events.py.

This module is battle-tested for defensive multi-shape JSONL parsing.
Port verbatim — do NOT simplify or improve.
"""

from __future__ import annotations

import json
import logging
import pathlib
from typing import Any

from app.core.event_text import MAX_READ_SIZE

log = logging.getLogger("hephaestus.backend.events")

# ---------- cost / token usage rollup ----------


def _sum_usage(path: pathlib.Path) -> dict[str, Any]:
    """Sum input/output tokens + cost across all events in an opencode JSONL stream."""
    if not path.exists():
        return {
            "input": 0,
            "output": 0,
            "reasoning": 0,
            "cache_read": 0,
            "cache_write": 0,
            "total": 0,
            "cost_usd": 0.0,
            "events_seen": 0,
        }
    inp = out = rsn = cr = cw = seen = 0
    cost = 0.0
    try:
        if path.stat().st_size > MAX_READ_SIZE:
            log.warning("_sum_usage: file too large, skipping: %s (%d bytes)", path, path.stat().st_size)
            return {
                "input": 0,
                "output": 0,
                "reasoning": 0,
                "cache_read": 0,
                "cache_write": 0,
                "total": 0,
                "cost_usd": 0.0,
                "events_seen": 0,
            }
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                log.debug("failed to parse JSONL line in _sum_usage", exc_info=True)
                continue
            seen += 1
            tokens_objs: list[dict[str, Any]] = []
            cost_vals: list[float] = []
            if isinstance(obj.get("usage"), dict):
                tokens_objs.append(obj["usage"])
            if isinstance(obj.get("tokens"), dict):
                tokens_objs.append(obj["tokens"])
            if isinstance(obj.get("cost"), (int, float)):
                cost_vals.append(obj["cost"])
            part = obj.get("part") if isinstance(obj.get("part"), dict) else None
            if part:
                if isinstance(part.get("tokens"), dict):
                    tokens_objs.append(part["tokens"])
                if isinstance(part.get("usage"), dict):
                    tokens_objs.append(part["usage"])
                if isinstance(part.get("cost"), (int, float)):
                    cost_vals.append(part["cost"])
            msg = obj.get("message") if isinstance(obj.get("message"), dict) else None
            if msg:
                if isinstance(msg.get("tokens"), dict):
                    tokens_objs.append(msg["tokens"])
                if isinstance(msg.get("usage"), dict):
                    tokens_objs.append(msg["usage"])
                if isinstance(msg.get("cost"), (int, float)):
                    cost_vals.append(msg["cost"])
            for u in tokens_objs:
                inp += int(u.get("input") or u.get("input_tokens") or u.get("prompt_tokens") or u.get("prompt") or 0)
                out += int(
                    u.get("output") or u.get("output_tokens") or u.get("completion_tokens") or u.get("completion") or 0
                )
                rsn += int(u.get("reasoning") or 0)
                cache = u.get("cache") if isinstance(u.get("cache"), dict) else None
                if cache:
                    cr += int(cache.get("read") or 0)
                    cw += int(cache.get("write") or 0)
            for c in cost_vals:
                cost += float(c or 0)
    except Exception:
        log.debug("_sum_usage failed for %s", path, exc_info=True)
        pass
    return {
        "input": inp,
        "output": out,
        "reasoning": rsn,
        "cache_read": cr,
        "cache_write": cw,
        "total": inp + out + rsn,
        "cost_usd": round(cost, 5),
        "events_seen": seen,
    }


def _iter_cost(d: pathlib.Path) -> dict[str, Any]:
    """Roll up all the *.jsonl streams in an iter dir into a single token + cost total."""
    total: dict[str, Any] = {
        "input": 0,
        "output": 0,
        "reasoning": 0,
        "cache_read": 0,
        "cache_write": 0,
        "total": 0,
        "cost_usd": 0.0,
        "streams": {},
    }
    if not d.exists():
        return total

    def acc(s: dict[str, Any]) -> None:
        for k in ("input", "output", "reasoning", "cache_read", "cache_write", "total"):
            total[k] += s.get(k, 0)
        total["cost_usd"] += s.get("cost_usd", 0.0)

    for f in d.glob("*.jsonl"):
        if f.stat().st_size > MAX_READ_SIZE:
            log.warning("_iter_cost: skipping large file %s (%d bytes)", f.name, f.stat().st_size)
            continue
        s = _sum_usage(f)
        total["streams"][f.name] = s
        acc(s)
    rdir = d / "reviews"
    if rdir.exists():
        for f in rdir.glob("*.out.jsonl"):
            if f.stat().st_size > MAX_READ_SIZE:
                log.warning("_iter_cost: skipping large file reviews/%s (%d bytes)", f.name, f.stat().st_size)
                continue
            s = _sum_usage(f)
            total["streams"][f"reviews/{f.name}"] = s
            acc(s)
    total["cost_usd"] = round(total["cost_usd"], 5)
    return total
