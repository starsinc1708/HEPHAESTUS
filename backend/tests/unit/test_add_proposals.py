"""Unit tests for add_proposals_to_queue helper (B1)."""
from __future__ import annotations

import app.core.state as state
from app.core.queue import add_proposals_to_queue


def test_add_proposals_to_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    from app.core.state import _read_state

    props = [{"id": "g1-a", "title": "A", "proposal": "do A", "rationale": "why",
              "acceptance": "tests", "touches": ["x.py"]}]
    add_proposals_to_queue(props, epic_id="goal-1", source="goal:goal-1")
    items = _read_state()["items"]
    it = next(i for i in items if i["id"] == "g1-a")
    assert it["status"] == "pending" and it["epicId"] == "goal-1" and it["proposal"] == "do A"
    # idempotent: adding the same id again does not duplicate
    add_proposals_to_queue(props, epic_id="goal-1", source="goal:goal-1")
    assert sum(1 for i in _read_state()["items"] if i["id"] == "g1-a") == 1


def test_add_proposals_maps_rationale_to_why(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    from app.core.state import _read_state

    props = [{"id": "x1", "title": "T", "proposal": "do X", "rationale": "the reason",
              "touches": ["a.py"]}]
    add_proposals_to_queue(props, source="test")
    it = next(i for i in _read_state()["items"] if i["id"] == "x1")
    assert it["why"] == "the reason"
    assert it["dependsOn"] == []


def test_add_proposals_skips_missing_required_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    from app.core.state import _read_state

    props = [
        {"id": "bad1", "title": "", "proposal": "p"},   # empty title
        {"id": "bad2", "title": "T", "proposal": ""},   # empty proposal
        {"id": "", "title": "T", "proposal": "p"},      # empty id
        {"id": "good", "title": "G", "proposal": "do G"},
    ]
    add_proposals_to_queue(props)
    ids = {i["id"] for i in _read_state()["items"]}
    assert "good" in ids
    assert "bad1" not in ids
    assert "bad2" not in ids
    assert "" not in ids


def test_add_proposals_no_epic_id(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", tmp_path)
    from app.core.state import _read_state

    props = [{"id": "z1", "title": "Z", "proposal": "do Z"}]
    add_proposals_to_queue(props)
    it = next(i for i in _read_state()["items"] if i["id"] == "z1")
    assert "epicId" not in it
