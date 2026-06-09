"""Text extraction helpers for opencode JSONL streams — ported verbatim from events.py.

This module is battle-tested for defensive multi-shape JSONL parsing.
Port verbatim — do NOT simplify or improve.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("hephaestus.backend.events")

EVENT_TAIL = 80
EVENT_TEXT_MAX = 240
EVENT_TEXT_MAX_RICH = 8000
MAX_READ_SIZE = 50_000_000  # 50 MB


# ---------- helpers ----------


def extract_assistant_text(raw: str) -> str:
    """Concatenate the assistant's plain text from a JSONL agent stream.

    The agent CLIs (claude `--output-format stream-json`, opencode `--format json`)
    wrap the model's output in JSONL events; the assistant text lives inside event
    fields and is therefore UN-escaped here. A machine block embedded in that text
    (e.g. ``IDEAS_BEGIN{...}IDEAS_END``) comes out as plain JSON the block parsers
    can ``json.loads``. Reading the raw JSONL file instead leaves the block
    JSON-escaped (``\\"``/``\\n``) and the parsers fail.

    Handles three shapes: ``{"type":"text","text":..}`` (opencode/simple),
    ``{"type":"assistant","message":{"content":[{"type":"text","text":..}]}}``
    (claude stream-json), ``{"part":{"type":"text","text":..}}`` (opencode part).
    If the input is not JSONL (e.g. a raw block from a test stub), it is returned
    unchanged so callers stay backward-compatible.
    """
    texts: list[str] = []
    recognized = False  # matched a KNOWN event shape (not just any JSON line)
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        otype = obj.get("type") or obj.get("event") or ""
        if otype == "text":
            recognized = True
            if obj.get("text"):
                texts.append(str(obj["text"]))
            continue
        msg = obj.get("message")
        if isinstance(msg, dict) and isinstance(msg.get("content"), list):
            recognized = True
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                    texts.append(str(block["text"]))
            continue
        part = obj.get("part") if isinstance(obj.get("part"), dict) else None
        if part and part.get("type") == "text":
            recognized = True
            if part.get("text"):
                texts.append(str(part["text"]))
    if texts:
        return "\n".join(texts)
    # Recognized real agent events but no text → non-text answer → "".
    # Never recognized an event shape → input is a raw (non-JSONL) block (e.g. a
    # bare ``BLOCK_BEGIN{...}END`` possibly spanning lines) → pass through verbatim.
    return "" if recognized else raw


def _truncate(s: object, n: int = EVENT_TEXT_MAX) -> str:
    s = str(s).replace("\n", " ⏎ ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _key_arg_for_tool(name: str | None, args: object) -> str:
    """Pick the ONE most-readable arg to put in the step header for known tools."""
    if not isinstance(args, dict):
        return _truncate(str(args), 100)
    name = (name or "").lower()
    if name in ("read", "view"):
        return f"file_path={args.get('filePath') or args.get('file_path') or args.get('path') or '?'}"
    if name in ("edit", "write", "multiedit"):
        return f"file_path={args.get('filePath') or args.get('file_path') or args.get('path') or '?'}"
    if name == "grep":
        return f"pattern={args.get('pattern') or '?'}"
    if name == "glob":
        return f"pattern={args.get('pattern') or '?'}"
    if name == "bash":
        return f"command={_truncate(args.get('command') or '?', 80)}"
    if name == "webfetch":
        return f"url={args.get('url') or '?'}"
    if name == "task":
        return (
            f"subagent={args.get('subagent_type') or '?'}  description={_truncate(args.get('description') or '?', 60)}"
        )
    return _truncate(json.dumps(args, ensure_ascii=False), 100)


def _extract_ts(obj: dict[str, Any], part: dict[str, Any] | None) -> int | None:
    """opencode 1.x emits `timestamp` (ms-since-epoch) at the top level on every event.
    Also sometimes on the part. Return int ms or None."""
    for src in (obj, part):
        if isinstance(src, dict):
            ts = src.get("timestamp") or src.get("ts") or src.get("time")
            if isinstance(ts, (int, float)) and ts > 0:
                return int(ts)
    return None
