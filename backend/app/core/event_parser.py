"""Event parsing, full conversation parse, and current iteration state — ported verbatim from events.py.

This module is battle-tested for defensive multi-shape JSONL parsing.
Port verbatim — do NOT simplify or improve.
"""

from __future__ import annotations

import json
import logging
import pathlib
import time
from typing import Any

from app.core.event_summarizer import _summarize_event
from app.core.event_text import EVENT_TAIL, MAX_READ_SIZE, _extract_ts, _truncate

log = logging.getLogger("hephaestus.backend.events")


def _parse_events(
    path: pathlib.Path,
    limit: int = EVENT_TAIL,
    with_idx_offset: int = 0,
) -> list[dict[str, Any]]:
    """Defensive read-from-tail parser. Always passes a stable `idx` to the summarizer
    so the client can request the full event via /api/iter/<dir>/event/<idx>."""
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        size = path.stat().st_size
        if size > MAX_READ_SIZE:
            log.warning("_parse_events: file too large, skipping: %s (%d bytes)", path, size)
            return events
        # If we read just the tail, count lines from the beginning to get true idx.
        if size > 262144:
            with path.open("rb") as f:
                f.seek(0)
                line_count_before_tail = 0
                cursor = 0
                target = max(0, size - 262144)
                while cursor < target:
                    block = f.read(min(65536, target - cursor))
                    if not block:
                        break
                    line_count_before_tail += block.count(b"\n")
                    cursor = f.tell()
                # Drop the first line (likely cut)
                line_count_before_tail += 1
                chunk = f.read().decode(errors="replace")
            lines = chunk.splitlines()
            if lines:
                lines = lines[1:]
            idx_offset = line_count_before_tail
        else:
            chunk = path.read_text(errors="replace")
            lines = chunk.splitlines()
            idx_offset = 0
        # Track the absolute idx for the line we're rendering.
        local_idx = 0
        kept: list[tuple[int, object]] = []
        for line in lines:
            line = line.strip()
            if not line:
                local_idx += 1
                continue
            try:
                obj = json.loads(line)
                kept.append((idx_offset + local_idx, obj))
            except Exception:
                log.debug("failed to parse event line at idx %d", idx_offset + local_idx, exc_info=True)
                kept.append((idx_offset + local_idx, {"_raw_line": line}))
            local_idx += 1
        for abs_idx, obj in kept[-limit:]:
            if isinstance(obj, dict) and "_raw_line" in obj:
                events.append({"idx": abs_idx, "kind": "raw", "icon": "·", "text": _truncate(obj["_raw_line"])})
            else:
                events.append(_summarize_event(obj, idx=abs_idx))
    except Exception as e:
        log.error("_parse_events failed for %s: %s", path, e)
        events.append({"idx": -1, "kind": "raw", "icon": "✗", "text": f"event-parse error: {e}"})
    return events


def _read_event_at_idx(jsonl_path: pathlib.Path, idx: int) -> dict[str, Any] | None:
    """Read a single event at line index `idx` and return its FULL parsed object
    (no truncation). Used by /api/iter/<dir>/event/<idx>."""
    if not jsonl_path.exists() or idx < 0:
        return None
    try:
        with jsonl_path.open("r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i == idx:
                    line = line.strip()
                    if not line:
                        return None
                    try:
                        return {"idx": idx, "raw": json.loads(line)}
                    except Exception:
                        log.debug("failed to parse event at idx %d", idx, exc_info=True)
                        return {"idx": idx, "raw": None, "text": line}
    except Exception:
        log.debug("_read_event_at_idx failed for %s at idx %d", jsonl_path, idx, exc_info=True)
        return None
    return None


# ---------- FULL (untruncated) conversation parse — feeds the conversation viewer ----------
#
# NOTE: these are NEW sibling functions. The verbatim-ported parsers above
# (_summarize_event / _summarize_claude_message / _truncate) COLLAPSE a message into
# one truncated event; here we EXPAND every block into its own untruncated item.


def parse_full_message(
    blocks: list[Any],
    *,
    role: str | None,
    ts_ms: int | None,
    tokens: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Expand a Claude CLI message's content blocks into one FULL (non-truncated)
    conversation item per block: thinking / text / tool (tool_use) / tool_result."""
    items: list[dict[str, Any]] = []
    for b in blocks:
        if isinstance(b, str):
            if b.strip():
                items.append({"role": role or "assistant", "kind": "text", "text": b, "tsMs": ts_ms})
            continue
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt in ("tool_use", "tool_call"):
            items.append({"role": role or "assistant", "kind": "tool",
                          "tool": {"name": b.get("name") or "tool", "input": b.get("input", {}), "output": None},
                          "toolUseId": b.get("id"), "tsMs": ts_ms})
        elif bt == "tool_result":
            c = b.get("content", "")
            out = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
            items.append({"role": role or "user", "kind": "tool_result",
                          "tool": {"name": None, "input": None, "output": out},
                          "toolUseId": b.get("tool_use_id"), "tsMs": ts_ms})
        elif bt == "thinking" and b.get("thinking"):
            items.append({"role": role or "assistant", "kind": "thinking",
                          "thinking": str(b["thinking"]), "tsMs": ts_ms})
        elif bt == "text" and b.get("text"):
            items.append({"role": role or "assistant", "kind": "text", "text": str(b["text"]), "tsMs": ts_ms})
    if tokens and items:
        items[-1]["tokens"] = tokens
    return items


def _full_item_from_event(obj: dict[str, Any]) -> dict[str, Any] | None:
    """For NON-Claude-message (opencode/part) shapes: reuse the battle-tested
    _summarize_event then map its FULL fields (text_full/output_full/args_full) into a
    conversation item. Returns None for boundary/raw events we don't render."""
    ev = _summarize_event(obj, idx=None)
    kind = ev.get("kind")
    role = ev.get("role")
    ts = ev.get("ts_ms")
    if kind == "text":
        body = ev.get("text_full") or ev.get("text") or ""
        return {"role": role or "assistant", "kind": "text", "text": body, "tsMs": ts} if body.strip() else None
    if kind == "reasoning":
        body = ev.get("text_full") or ev.get("text") or ""
        return {"role": role, "kind": "thinking", "thinking": body, "tsMs": ts}
    if kind == "tool_call":
        out = ev.get("output_full")
        out_s = out if isinstance(out, str) else (json.dumps(out, ensure_ascii=False) if out is not None else None)
        return {"role": role, "kind": "tool",
                "tool": {"name": ev.get("tool"), "input": ev.get("args_full"), "output": out_s},
                "toolUseId": ev.get("tool_use_id"), "tsMs": ts}
    if kind == "tool_result":
        out = ev.get("output_full")
        out_s = out if isinstance(out, str) else (json.dumps(out, ensure_ascii=False) if out is not None else None)
        return {"role": role, "kind": "tool_result",
                "tool": {"name": None, "input": None, "output": out_s},
                "toolUseId": ev.get("tool_use_id"), "tsMs": ts}
    return None  # session / finish / raw — not part of the conversation transcript


def parse_full_conversation(path: pathlib.Path) -> list[dict[str, Any]]:
    """Read a whole agent JSONL stream and return the FULL, untruncated conversation as
    an ordered list of items. Claude-message events expand block-by-block; opencode/part
    events map one-to-one. tool_result outputs are paired into their matching tool item
    (by toolUseId) so each tool renders as one OpenCode-style card with input + output."""
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    try:
        if path.stat().st_size > MAX_READ_SIZE:
            log.warning("parse_full_conversation: file too large, skipping: %s", path)
            return items
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(obj, dict):
                continue
            # Drop control/meta events: `type=system` carries init + hook lifecycle
            # (hook_started/hook_response/hook_progress, e.g. a SessionStart hook injecting
            # skill/context text). These are NOT the agent's conversation — rendering them
            # dumps raw hook JSON / injected context into the viewer.
            if obj.get("type") == "system":
                continue
            part = obj.get("part") if isinstance(obj.get("part"), dict) else None
            ts = _extract_ts(obj, part)
            msg = obj.get("message")
            if isinstance(msg, dict) and isinstance(msg.get("content"), list):
                t = obj.get("type")
                role = obj.get("role") or (t if isinstance(t, str) else None)
                tokens = msg.get("usage") if isinstance(msg.get("usage"), dict) else None
                items.extend(parse_full_message(msg["content"], role=role, ts_ms=ts, tokens=tokens))
            else:
                it = _full_item_from_event(obj)
                if it is not None:
                    items.append(it)
    except Exception as e:  # never let a parse error crash the endpoint
        log.error("parse_full_conversation failed for %s: %s", path, e)
        return items
    return _pair_tool_results(items)


def _pair_tool_results(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fold standalone tool_result items into the matching tool item's output (matched by
    toolUseId). Tool items that already carry an output (opencode) are left as-is. Orphan
    tool_results (no matching call) are kept as their own items. Returns a NEW list, order
    preserved."""
    tool_by_id: dict[str, dict[str, Any]] = {}
    for it in items:
        if it.get("kind") == "tool":
            tid = it.get("toolUseId")
            if isinstance(tid, str) and tid:
                tool_by_id.setdefault(tid, it)
    out: list[dict[str, Any]] = []
    for it in items:
        if it.get("kind") == "tool_result":
            tid = it.get("toolUseId")
            target = tool_by_id.get(tid) if isinstance(tid, str) else None
            if target is not None and not (target.get("tool") or {}).get("output"):
                target.setdefault("tool", {})["output"] = (it.get("tool") or {}).get("output")
                continue  # consumed — don't emit the standalone result
        out.append(it)
    return out


def _current_iter_block() -> dict[str, Any]:
    """Return current iteration state for the active iter dir."""
    from app.core.state import _state_dir

    _sd = _state_dir()  # active workspace state dir (legacy fallback)
    its = sorted(_sd.glob("iter-*"), key=lambda p: p.name) if _sd.exists() else []
    d = its[-1] if its else None
    if not d:
        return {
            "dir": None,
            "active_agent": None,
            "events": [],
            "primary_size": 0,
            "fallback_size": 0,
            "events_count": 0,
            "started_at_ms": None,
            "now_ms": int(time.time() * 1000),
        }
    pri = d / "output.primary.jsonl"
    fbk = d / "output.fallback.jsonl"
    pri_sz = pri.stat().st_size if pri.exists() else 0
    fbk_sz = fbk.stat().st_size if fbk.exists() else 0
    if fbk_sz and (not pri_sz or fbk.stat().st_mtime >= pri.stat().st_mtime):
        events = _parse_events(fbk)
        agent = "fallback"
    else:
        events = _parse_events(pri)
        agent = "primary"
    # iteration start = mtime of run-tag (driver writes this when iter starts)
    started_at_ms = None
    rt = d / "run-tag"
    if rt.exists():
        started_at_ms = int(rt.stat().st_mtime * 1000)
    return {
        "dir": d.name,
        "active_agent": agent,
        "primary_size": pri_sz,
        "fallback_size": fbk_sz,
        "events": events,
        "events_count": len(events),
        "started_at_ms": started_at_ms,
        "now_ms": int(time.time() * 1000),
    }
