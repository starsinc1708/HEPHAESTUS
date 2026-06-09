"""build_state sorts items by (orderIndex, id); _task_view exposes deps."""
from __future__ import annotations

import json
import pathlib

import pytest


def test_build_state_sorts_by_order_index(tmp_state_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.iters as iters_mod
    import app.core.state as state_mod
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_state_dir, raising=False)
    (tmp_state_dir / "work-state.json").write_text(json.dumps({"items": [
        {"id": "B", "title": "B", "status": "pending", "orderIndex": 2},
        {"id": "A", "title": "A", "status": "pending", "orderIndex": 0},
        {"id": "C", "title": "C", "status": "pending", "orderIndex": 1},
    ]}))
    st = iters_mod.build_state()
    assert [it["id"] for it in st["items"]] == ["A", "C", "B"]
