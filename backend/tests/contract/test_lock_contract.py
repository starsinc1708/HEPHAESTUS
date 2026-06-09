"""Contract: _StateLock serializes in-process writes (cross-platform, no bash)."""
from __future__ import annotations

import pathlib

import pytest


def test_concurrent_writes_no_corruption(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path, raising=False)
    (tmp_path / "work-state.json").write_text('{"items": []}')

    for i in range(100):
        with state_mod._StateLock():
            s = state_mod._read_state()
            s["items"].append({"id": f"item-{i}", "title": f"Item {i}", "status": "pending"})
            state_mod._write_state(s)

    final = state_mod._read_state()
    assert len(final["items"]) == 100
    assert {it["id"] for it in final["items"]} == {f"item-{i}" for i in range(100)}


def test_lock_reentrant_safe(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path, raising=False)
    (tmp_path / "work-state.json").write_text('{"items": []}')
    with state_mod._StateLock():
        state_mod._write_state({"items": [{"id": "x", "title": "x", "status": "pending"}]})
    assert len(state_mod._read_state()["items"]) == 1
