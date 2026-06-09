"""Full (untruncated) conversation parse — block expansion + tool pairing.

Covers parse_full_conversation across Claude-CLI message shapes (one item per content
block, no truncation) and opencode/part shapes (one-to-one), plus empty/malformed input.
"""

from __future__ import annotations

import json

from app.core.events import parse_full_conversation

LONG_THINKING = "T" * 300 + " end-of-thinking"  # >240 chars so truncation would show
LONG_MD = "# Heading\n\n" + ("M" * 300) + " end-of-markdown"  # >240 chars


def _write(tmp_path, name, lines):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(o) for o in lines) + "\n", encoding="utf-8")
    return p


def test_claude_block_expansion_no_truncation(tmp_path):
    """A Claude assistant message expands into thinking + text + tool items, all FULL,
    and the following user tool_result is folded into the tool item by toolUseId."""
    p = _write(
        tmp_path,
        "output.primary.jsonl",
        [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": LONG_THINKING},
                        {"type": "text", "text": LONG_MD},
                        {"type": "tool_use", "id": "tu_1", "name": "Read",
                         "input": {"file_path": "a.py"}},
                    ],
                    "usage": {"input": 10, "output": 20},
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tu_1",
                         "content": "file contents here"},
                    ],
                },
            },
        ],
    )
    items = parse_full_conversation(p)

    kinds = [it["kind"] for it in items]
    assert kinds == ["thinking", "text", "tool"], kinds

    think = items[0]
    assert think["kind"] == "thinking"
    assert think["thinking"] == LONG_THINKING
    assert len(think["thinking"]) > 240
    assert "…" not in think["thinking"]

    text = items[1]
    assert text["kind"] == "text"
    assert text["text"] == LONG_MD
    assert len(text["text"]) > 240
    assert "…" not in text["text"]

    tool = items[2]
    assert tool["kind"] == "tool"
    assert tool["tool"]["name"] == "Read"
    assert tool["tool"]["input"] == {"file_path": "a.py"}
    # tool_result was paired in by toolUseId
    assert tool["tool"]["output"] == "file contents here"

    # the standalone tool_result must have been consumed (no leftover tool_result item)
    assert not any(it["kind"] == "tool_result" for it in items)


def test_opencode_part_one_to_one(tmp_path):
    """opencode/part text + tool parts map one-to-one with full (untruncated) input/output."""
    long_text = "opencode reasoning paragraph. " * 20  # > EVENT_TEXT_MAX (240) chars
    assert len(long_text) > 240
    p = _write(
        tmp_path,
        "output.primary.jsonl",
        [
            {"part": {"type": "text", "text": long_text}},
            {"part": {"type": "tool", "tool": "bash",
                      "state": {"input": {"command": "ls"}, "output": "file listing",
                                "status": "completed"}}},
        ],
    )
    items = parse_full_conversation(p)
    kinds = [it["kind"] for it in items]
    assert kinds == ["text", "tool"], kinds

    # full text preserved — not clipped to the 240-char timeline preview, no ellipsis
    assert items[0]["text"] == long_text
    assert len(items[0]["text"]) > 240
    assert "…" not in items[0]["text"]

    tool = items[1]
    assert tool["kind"] == "tool"
    assert tool["tool"]["input"] == {"command": "ls"}
    assert tool["tool"]["output"] == "file listing"


def test_missing_file_returns_empty(tmp_path):
    assert parse_full_conversation(tmp_path / "nope.jsonl") == []


def test_blank_and_malformed_lines_skipped(tmp_path):
    p = tmp_path / "output.primary.jsonl"
    p.write_text(
        "\n"
        + "{ this is not json\n"
        + json.dumps({"part": {"type": "text", "text": "valid line"}})
        + "\n"
        + "   \n"
        + "[1, 2, 3]\n",  # valid JSON but not a dict → skipped
        encoding="utf-8",
    )
    items = parse_full_conversation(p)
    assert len(items) == 1
    assert items[0]["kind"] == "text"
    assert items[0]["text"] == "valid line"


def test_system_and_hook_events_are_dropped(tmp_path):
    """`type=system` lines (init + hook lifecycle — e.g. a SessionStart hook injecting skill
    context as raw JSON) are control/meta, not conversation. They must NOT leak into the
    transcript; only real assistant/user turns render."""
    p = _write(
        tmp_path,
        "output.primary.jsonl",
        [
            {"type": "system", "subtype": "hook_started", "hook_name": "SessionStart"},
            {"type": "system", "subtype": "hook_response",
             "text": '{"hookSpecificOutput": {"additionalContext": "<EXTREMELY_IMPORTANT> superpowers"}}'},
            {"type": "system", "subtype": "init", "cwd": "/x"},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Implementing now."}]}},
        ],
    )
    items = parse_full_conversation(p)
    assert len(items) == 1
    assert items[0]["kind"] == "text"
    assert items[0]["text"] == "Implementing now."
    assert not any("additionalContext" in (it.get("text") or "") for it in items)
