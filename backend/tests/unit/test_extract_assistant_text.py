"""extract_assistant_text: un-escape agent text from stream-json JSONL so embedded
machine blocks (IDEAS_BEGIN/PLAN_BEGIN/MAP_BEGIN/...) become parseable. Regression
for the bug where block parsers ran on the raw JSONL (block was JSON-escaped)."""

from __future__ import annotations

import json

from app.core.events import extract_assistant_text


def test_claude_stream_json_unescapes_embedded_block():
    # Real claude --output-format stream-json: the assistant text (with the block)
    # lives JSON-escaped inside an event's message.content[].text.
    block = 'IDEAS_BEGIN{"ideas":[{"title":"X","category":"perf"}]}IDEAS_END'
    line = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": block}]}})
    out = extract_assistant_text(line + "\n" + json.dumps({"type": "result"}))
    assert "IDEAS_BEGIN" in out
    # The recovered text is un-escaped → the inner JSON parses.
    import re

    m = re.search(r"IDEAS_BEGIN\s*(\{.*?\})\s*IDEAS_END", out, re.DOTALL)
    assert m is not None
    assert json.loads(m.group(1))["ideas"][0]["title"] == "X"


def test_simple_text_event_shape():
    line = json.dumps({"type": "text", "text": "hello world"})
    assert extract_assistant_text(line) == "hello world"


def test_opencode_part_shape():
    line = json.dumps({"part": {"type": "text", "text": "from opencode"}})
    assert extract_assistant_text(line) == "from opencode"


def test_raw_block_passthrough():
    # A test stub writes the raw block (not JSONL) — must be returned unchanged.
    raw = 'PLAN_BEGIN{"tasks":[]}PLAN_END'
    assert extract_assistant_text(raw) == raw


def test_concatenates_multiple_text_parts():
    lines = "\n".join(
        json.dumps({"type": "text", "text": t}) for t in ("a", "b", "c")
    )
    assert extract_assistant_text(lines) == "a\nb\nc"
