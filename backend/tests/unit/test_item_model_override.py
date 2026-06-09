"""Item.modelOverride + complexity fields (Epic 2, Batch A, Task A1)."""
from __future__ import annotations

from app.models.domain import Item
from app.models.workspace import AgentRef


def test_item_model_override_and_complexity_aliases():
    it = Item(id="x", title="t", status="pending")
    it.model_override = AgentRef(provider="anthropic", model="claude-opus-4-8")
    it.complexity = "complex"
    d = it.model_dump(by_alias=True)
    assert d["modelOverride"]["model"] == "claude-opus-4-8"
    assert d["complexity"] == "complex"
    back = Item.model_validate(d)
    assert back.model_override is not None
    assert back.model_override.provider == "anthropic"


def test_item_model_override_defaults_none():
    it = Item(id="y", title="t2", status="pending")
    assert it.model_override is None
    assert it.complexity is None
    d = it.model_dump(by_alias=True)
    assert d["modelOverride"] is None
    assert d["complexity"] is None


def test_item_model_override_camel_case_roundtrip():
    """Validate from camelCase dict (as the frontend would send)."""
    data = {
        "id": "z",
        "title": "task z",
        "status": "pending",
        "modelOverride": {"provider": "openai", "model": "gpt-4o"},
        "complexity": "simple",
    }
    it = Item.model_validate(data)
    assert it.model_override is not None
    assert it.model_override.provider == "openai"
    assert it.model_override.model == "gpt-4o"
    assert it.complexity == "simple"


def test_patch_allowlist_includes_model_override_and_complexity():
    """_queue_patch must not strip modelOverride or complexity."""
    from app.core.queue import _queue_patch
    from app.core.state import _read_state, _StateLock, _write_state

    # Inject a pending item directly into state
    item_id = "test-patch-mo"
    with _StateLock():
        s = _read_state()
        s.setdefault("items", []).append({
            "id": item_id,
            "title": "patch test",
            "status": "pending",
            "attempts": 0,
        })
        _write_state(s)

    try:
        result = _queue_patch(item_id, {
            "modelOverride": {"provider": "anthropic", "model": "claude-opus-4-8"},
            "complexity": "complex",
        })
        assert result.get("ok") is True

        with _StateLock():
            s = _read_state()
        found = next((it for it in s["items"] if it["id"] == item_id), None)
        assert found is not None
        assert found.get("modelOverride") == {"provider": "anthropic", "model": "claude-opus-4-8"}
        assert found.get("complexity") == "complex"
    finally:
        # Clean up test item
        with _StateLock():
            s = _read_state()
            s["items"] = [it for it in s.get("items", []) if it["id"] != item_id]
            _write_state(s)
