"""Contract: GET /api/state exposes loop.process and deprecated tmux mirror."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_loopstatus_has_process_field() -> None:
    from app.main import app

    client = TestClient(app)
    r = client.get("/api/state")
    assert r.status_code == 200
    loop = r.json().get("loop") or {}
    assert "process" in loop
    assert set(loop["process"]).issuperset({"state", "pid", "children"})
    assert "tmux" in loop
