"""Event parsing — thin facade re-exporting from split modules.

Original module was ported verbatim from dashboard/server.py.
Battle-tested for defensive multi-shape JSONL parsing.
Port verbatim — do NOT simplify or improve.
"""

from __future__ import annotations

from app.core.event_cost import _iter_cost, _sum_usage  # noqa: F401
from app.core.event_parser import (  # noqa: F401
    _current_iter_block,
    _full_item_from_event,
    _pair_tool_results,
    _parse_events,
    _read_event_at_idx,
    parse_full_conversation,
    parse_full_message,
)
from app.core.event_summarizer import _summarize_claude_message, _summarize_event  # noqa: F401
from app.core.event_text import (  # noqa: F401
    EVENT_TAIL,
    EVENT_TEXT_MAX,
    EVENT_TEXT_MAX_RICH,
    MAX_READ_SIZE,
    _extract_ts,
    _key_arg_for_tool,
    _truncate,
    extract_assistant_text,
)

__all__ = [
    "EVENT_TAIL",
    "EVENT_TEXT_MAX",
    "EVENT_TEXT_MAX_RICH",
    "MAX_READ_SIZE",
    "extract_assistant_text",
    "parse_full_conversation",
    "parse_full_message",
    # Private names re-exported for internal use
    "_truncate",
    "_key_arg_for_tool",
    "_extract_ts",
    "_sum_usage",
    "_iter_cost",
    "_summarize_claude_message",
    "_summarize_event",
    "_parse_events",
    "_read_event_at_idx",
    "_full_item_from_event",
    "_pair_tool_results",
    "_current_iter_block",
]
