"""Event summarization for opencode JSONL streams — ported verbatim from events.py.

This module is battle-tested for defensive multi-shape JSONL parsing.
Port verbatim — do NOT simplify or improve.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.event_text import EVENT_TEXT_MAX, _extract_ts, _key_arg_for_tool, _truncate

log = logging.getLogger("hephaestus.backend.events")

# ---------- event summarization ----------


def _summarize_claude_message(blocks: list[Any], *, idx: int | None, role: str | None,
                              ts_ms: int | None) -> dict[str, Any]:
    """Render a Claude CLI assistant/user message (a list of content blocks) into ONE
    readable event. Prefers the salient block: tool call > tool result > text > thinking."""
    texts: list[str] = []
    thinks: list[str] = []
    tool: str | None = None
    tool_input: Any = None
    tool_result: str | None = None
    for b in blocks:
        if isinstance(b, str):
            texts.append(b)
            continue
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt in ("tool_use", "tool_call"):
            tool = b.get("name") or "tool"
            tool_input = b.get("input", {})
        elif bt == "tool_result":
            c = b.get("content", "")
            tool_result = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
        elif bt == "thinking" and b.get("thinking"):
            thinks.append(str(b["thinking"]))
        elif bt == "text" and b.get("text"):
            texts.append(str(b["text"]))
    if tool:
        return {"idx": idx, "kind": "tool_call", "icon": "🔧", "role": role, "ts_ms": ts_ms,
                "tool": tool, "args_preview": _key_arg_for_tool(tool, tool_input),
                "args_full": tool_input, "text": f"{tool}({_key_arg_for_tool(tool, tool_input)})"}
    if tool_result is not None:
        return {"idx": idx, "kind": "tool_result", "icon": "↩", "role": role, "ts_ms": ts_ms,
                "text": _truncate(tool_result), "output_preview": _truncate(tool_result),
                "output_full": tool_result}
    if texts:
        body = "\n".join(texts).strip()
        return {"idx": idx, "kind": "text", "icon": "✎", "role": role or "assistant",
                "ts_ms": ts_ms, "text": _truncate(body), "text_full": body}
    body = "\n".join(thinks).strip()
    return {"idx": idx, "kind": "reasoning", "icon": "💭", "role": role, "ts_ms": ts_ms,
            "text": _truncate(body or "(empty)"), "text_full": body}


def _summarize_event(obj: object, idx: int | None = None) -> dict[str, Any]:
    """Defensive event parsing. Returns rich dict that preserves both preview AND full
    data for the dashboard chat-style renderer to handle expansion on demand."""
    if not isinstance(obj, dict):
        return {"idx": idx, "kind": "raw", "icon": "·", "text": _truncate(json.dumps(obj))}
    t = obj.get("type") or obj.get("event") or obj.get("kind") or ""
    role = obj.get("role")
    part = obj.get("part") if isinstance(obj.get("part"), dict) else None
    pt = (part or {}).get("type") if part else None
    ts_ms = _extract_ts(obj, part)

    # Claude CLI stream-json: {"type":"assistant"|"user","message":{"content":[blocks]}}.
    # Without this the whole JSON falls through to the raw branch (ugly dump in the UI).
    msg = obj.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("content"), list):
        return _summarize_claude_message(msg["content"], idx=idx,
                                         role=role or (t if isinstance(t, str) else None), ts_ms=ts_ms)

    # opencode tool events have callID / id on the part — used to pair tool_call ↔ tool_result.
    tool_use_id: str | None = None
    if part:
        tool_use_id = part.get("callID") or part.get("id") or part.get("toolUseID")
    if not tool_use_id:
        tool_use_id = obj.get("callID") or obj.get("tool_use_id") or obj.get("id")

    # text payload extraction (defensive across opencode/anthropic/openai shapes)
    text_payload: str | None = None
    if part:
        text_payload = part.get("text") or part.get("content") or part.get("output")
    if not text_payload:
        text_payload = obj.get("text") or obj.get("content") or obj.get("output") or obj.get("delta")
    if isinstance(text_payload, list):
        flat: list[str] = []
        for el in text_payload:
            if isinstance(el, dict):
                if el.get("type") == "text" and el.get("text"):
                    flat.append(el["text"])
                elif el.get("type") in ("tool_use", "tool_call") and el.get("name"):
                    flat.append(f"→ {el['name']}({_truncate(json.dumps(el.get('input', {})), 60)})")
                elif el.get("type") == "tool_result":
                    flat.append(f"← {_truncate(json.dumps(el.get('content', '')), 80)}")
            elif isinstance(el, str):
                flat.append(el)
        text_payload = " · ".join(flat) if flat else None

    # ---- tool call ----
    if pt == "tool" or t in ("tool_use", "tool_call") or ("tool" in t.lower() and "result" not in t.lower()):
        name = (part or {}).get("tool") or (part or {}).get("name") if part else None
        name = name or obj.get("name") or obj.get("tool") or "tool"
        args = (part or {}).get("state", {}).get("input") if part else None
        if not args:
            args = (part or {}).get("input") if part else None
        if not args:
            args = obj.get("input") or obj.get("args") or {}
        # opencode also stores output INSIDE the tool_use part once result comes back
        state = (part or {}).get("state", {}) if isinstance((part or {}).get("state"), dict) else {}
        output = state.get("output")
        # opencode 1.x tracks call lifecycle on the state: started/completed timestamps.
        ts_started = state.get("startedAt") or state.get("started")
        ts_completed = state.get("completedAt") or state.get("completed")
        status = state.get("status")  # "pending" | "running" | "completed" | "failed"
        return {
            "idx": idx,
            "kind": "tool_call",
            "icon": "🔧",
            "role": role,
            "tool": name,
            "tool_use_id": tool_use_id,
            "ts_ms": ts_ms,
            "ts_started_ms": (int(ts_started) if isinstance(ts_started, (int, float)) and ts_started > 0 else ts_ms),
            "ts_completed_ms": (
                int(ts_completed) if isinstance(ts_completed, (int, float)) and ts_completed > 0 else None
            ),
            "status": status,
            "args_preview": _key_arg_for_tool(name, args),
            "args_full": args,
            "output_preview": (
                _truncate(
                    json.dumps(output, ensure_ascii=False) if not isinstance(output, str) else (output or ""),
                    EVENT_TEXT_MAX,
                )
                if output is not None
                else None
            ),
            "output_full": output,
            "text": f"{name}({_key_arg_for_tool(name, args)})",
        }

    # ---- tool result (separate event in some shapes) ----
    if pt == "tool_result" or t in ("tool_result", "tool-result"):
        out = (part or {}).get("output") if part else None
        out = out or obj.get("output") or obj.get("result") or ""
        out_str = json.dumps(out, ensure_ascii=False) if not isinstance(out, str) else out
        return {
            "idx": idx,
            "kind": "tool_result",
            "icon": "↩",
            "role": role,
            "tool_use_id": tool_use_id,
            "ts_ms": ts_ms,
            "text": _truncate(out_str, EVENT_TEXT_MAX),
            "output_preview": _truncate(out_str, EVENT_TEXT_MAX),
            "output_full": out,
        }

    # ---- reasoning / thinking ----
    if pt in ("reasoning", "thinking") or "reasoning" in t.lower() or "thinking" in t.lower():
        full = text_payload or ""
        return {
            "idx": idx,
            "kind": "reasoning",
            "icon": "💭",
            "role": role,
            "ts_ms": ts_ms,
            "text": _truncate(full or "(empty)"),
            "text_full": full,
        }

    # ---- assistant text ----
    if pt == "text" or (text_payload and not part):
        full = text_payload or ""
        return {
            "idx": idx,
            "kind": "text",
            "icon": "✎",
            "role": role or "assistant",
            "ts_ms": ts_ms,
            "text": _truncate(full),
            "text_full": full,
        }

    # ---- step/session/finish boundary events (used by client for grouping) ----
    if "session" in t.lower():
        return {
            "idx": idx,
            "kind": "session",
            "icon": "▷",
            "role": role,
            "ts_ms": ts_ms,
            "text": _truncate(
                t + " " + json.dumps({k: v for k, v in obj.items() if k != "type"}, ensure_ascii=False),
                120,
            ),
            "boundary": "session",
        }
    if "step" in t.lower() and ("start" in t.lower() or "begin" in t.lower()):
        return {
            "idx": idx,
            "kind": "session",
            "icon": "▷",
            "role": role,
            "ts_ms": ts_ms,
            "text": t,
            "boundary": "step_start",
        }
    if "step" in t.lower() or "finish" in t.lower() or "stop" in t.lower():
        tokens = None
        if part and isinstance(part.get("tokens"), dict):
            tokens = part["tokens"]
        cost = None
        if part:
            cost = part.get("cost")
        return {
            "idx": idx,
            "kind": "finish",
            "icon": "■",
            "role": role,
            "ts_ms": ts_ms,
            "text": _truncate(t),
            "boundary": "step_finish",
            "tokens": tokens,
            "cost": cost,
        }

    return {
        "idx": idx,
        "kind": "raw",
        "icon": "·",
        "ts_ms": ts_ms,
        "text": _truncate(
            f"{t} {json.dumps({k: v for k, v in obj.items() if k != 'type'}, ensure_ascii=False)}",
            200,
        ),
    }
