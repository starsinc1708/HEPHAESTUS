"""Contract tests for GET /api/v1/tasks/{item_id}/conversations.

Enumerates a task's iterations and, per iteration, the stages × agent-runs so the
frontend can build the iteration → stage → agent tree, then open each stream via the
B2 conversation endpoint. 404 for unknown tasks.
"""

from __future__ import annotations

import json
import pathlib

import app.core.state as state_mod


def _claude_line(model: str = "claude-x", text: str = "hi") -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {"model": model, "content": [{"type": "text", "text": text}]},
        }
    )


def _seed(tmp_path: pathlib.Path) -> None:
    d = tmp_path / "iter-0001"
    d.mkdir(parents=True)
    (d / "output.primary.r0.jsonl").write_text(_claude_line() + "\n", encoding="utf-8")
    (d / "output.primary.jsonl").write_text(_claude_line() + "\n", encoding="utf-8")
    (d / "validation" / "layer1").mkdir(parents=True)
    (d / "validation" / "layer1" / "correctness.jsonl").write_text(_claude_line() + "\n", encoding="utf-8")
    (d / "validation" / "layer1" / "correctness.json").write_text(
        json.dumps({"lens": "correctness", "verdict": "approve"}), encoding="utf-8"
    )
    (d / "validation" / "layer3").mkdir(parents=True)
    (d / "validation" / "layer3" / "final.jsonl").write_text(_claude_line() + "\n", encoding="utf-8")
    (d / "validation" / "layer3" / "final.json").write_text(json.dumps({"gate": "pass"}), encoding="utf-8")
    (tmp_path / "work-state.json").write_text(
        json.dumps({"items": [{"id": "task-1", "title": "t", "status": "done", "lastIter": "iter-0001"}]}),
        encoding="utf-8",
    )


def test_conversations_endpoint_returns_tree(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path, raising=False)
    _seed(tmp_path)

    r = client.get("/api/v1/tasks/task-1/conversations")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["itemId"] == "task-1"
    assert data["iterations"], "iterations should be non-empty"
    it = data["iterations"][0]
    assert it["dir"] == "iter-0001"
    assert "createdAt" in it
    assert "attempts" in it
    stages = {st["stage"]: st for st in it["stages"]}
    assert "implement" in stages
    assert "validate" in stages
    impl_streams = {a["stream"] for a in stages["implement"]["agents"]}
    assert {"output.primary.r0", "output.primary"} <= impl_streams
    val_streams = {a["stream"] for a in stages["validate"]["agents"]}
    assert "validation/layer1/correctness" in val_streams
    assert "validation/layer3/final" in val_streams


def test_conversations_endpoint_unknown_task_404(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path, raising=False)
    (tmp_path / "work-state.json").write_text(json.dumps({"items": []}), encoding="utf-8")

    r = client.get("/api/v1/tasks/does-not-exist/conversations")
    assert r.status_code == 404
    assert r.json()["ok"] is False
