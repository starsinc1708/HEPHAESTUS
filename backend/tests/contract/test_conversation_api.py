"""Contract tests for GET /api/iter/{dirname}/conversation?stream=X.

Returns the FULL untruncated conversation for one agent stream, resolves nested stream
names path-safely inside the iter dir, and rejects traversal with 400 (never a file read).
"""

from __future__ import annotations

import json

import app.core.state as state_mod


def _seed_iter(tmp_path):
    d = tmp_path / "iter-9999"
    d.mkdir(parents=True)
    p = d / "output.primary.jsonl"
    p.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [
                                {"type": "text", "text": "doing the work"},
                                {"type": "tool_use", "id": "tu_1", "name": "Read",
                                 "input": {"file_path": "x.py"}},
                            ]
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "content": [
                                {"type": "tool_result", "tool_use_id": "tu_1",
                                 "content": "x.py body"},
                            ]
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return d


def test_conversation_endpoint_returns_full_messages(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    _seed_iter(tmp_path)

    r = client.get("/api/iter/iter-9999/conversation?stream=output.primary")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["stream"] == "output.primary"
    msgs = data["messages"]
    assert msgs, "messages should be non-empty"
    kinds = [m["kind"] for m in msgs]
    assert kinds == ["text", "tool"], kinds
    tool = msgs[1]
    assert tool["tool"]["name"] == "Read"
    assert tool["tool"]["output"] == "x.py body"


def test_conversation_endpoint_rejects_traversal(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    _seed_iter(tmp_path)

    r = client.get("/api/iter/iter-9999/conversation?stream=../../etc/passwd")
    assert r.status_code == 400
    assert r.json()["error"] == "invalid stream"


def test_conversation_endpoint_missing_stream_404(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)
    _seed_iter(tmp_path)

    r = client.get("/api/iter/iter-9999/conversation?stream=output.nonexistent")
    assert r.status_code == 404
