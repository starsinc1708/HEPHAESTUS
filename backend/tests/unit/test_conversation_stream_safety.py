"""Path-safe conversation-stream resolver — accepts nested relative stream names,
rejects every traversal / unsafe input. Guards against escaping the iter dir."""

from __future__ import annotations

from app.core.iters import _resolve_conversation_stream


def test_resolves_nested_stream_names(tmp_path):
    d = tmp_path / "iter-0001"
    d.mkdir()

    assert _resolve_conversation_stream(d, "output.primary") == (
        d / "output.primary.jsonl"
    ).resolve()

    assert _resolve_conversation_stream(d, "output.primary.r0") == (
        d / "output.primary.r0.jsonl"
    ).resolve()

    assert _resolve_conversation_stream(d, "validation/layer1/correctness") == (
        d / "validation" / "layer1" / "correctness.jsonl"
    ).resolve()

    assert _resolve_conversation_stream(d, "validation.r0/layer3/final") == (
        d / "validation.r0" / "layer3" / "final.jsonl"
    ).resolve()


def test_rejects_traversal_and_unsafe_input(tmp_path):
    d = tmp_path / "iter-0001"
    d.mkdir()

    assert _resolve_conversation_stream(d, "../../etc/passwd") is None
    assert _resolve_conversation_stream(d, "../secret") is None
    assert _resolve_conversation_stream(d, "../../../../../../etc/hosts") is None
    assert _resolve_conversation_stream(d, "") is None
    assert _resolve_conversation_stream(d, "a" * 300) is None
    assert _resolve_conversation_stream(d, "a\x00b") is None
    # Windows backslash separators must be rejected too (this app runs on Windows;
    # pathlib treats `\` as a separator there, so `..\\` is a real traversal vector).
    assert _resolve_conversation_stream(d, "..\\secret") is None
    assert _resolve_conversation_stream(d, "..\\..\\etc\\passwd") is None
