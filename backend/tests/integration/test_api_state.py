"""Integration tests for /api/state endpoint."""

from __future__ import annotations

import json
from unittest.mock import patch

from fastapi.testclient import TestClient


def test_get_state_returns_200_with_expected_keys(client: TestClient) -> None:
    """GET /api/state returns 200 with the expected top-level JSON keys."""
    with (
        patch("app.core.iters._git_branches", return_value=[]),
        patch("app.core.iters._git_recent_commits", return_value=[]),
        patch("app.core.iters._run", return_value=""),
        patch("app.core.driver._tmux_has", return_value=False),
    ):
        resp = client.get("/api/state")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("items", "summary", "current", "git", "loop", "updatedAt", "totals", "config"):
        assert key in data, f"missing key: {key}"


def test_get_state_items_is_list(client: TestClient) -> None:
    """GET /api/state items field should be a list."""
    with (
        patch("app.core.iters._git_branches", return_value=[]),
        patch("app.core.iters._git_recent_commits", return_value=[]),
        patch("app.core.iters._run", return_value=""),
        patch("app.core.driver._tmux_has", return_value=False),
    ):
        data = client.get("/api/state").json()
    assert isinstance(data["items"], list)


def test_get_state_summary_has_bucket_counts(client: TestClient) -> None:
    """Summary should contain status bucket counts."""
    with (
        patch("app.core.iters._git_branches", return_value=[]),
        patch("app.core.iters._git_recent_commits", return_value=[]),
        patch("app.core.iters._run", return_value=""),
        patch("app.core.driver._tmux_has", return_value=False),
    ):
        data = client.get("/api/state").json()
    summary = data["summary"]
    for bucket in ("pending", "in_progress", "done", "merged", "failed_total", "total"):
        assert bucket in summary, f"missing summary bucket: {bucket}"


def test_get_state_loop_status(client: TestClient) -> None:
    """Loop status should contain tmux key."""
    with (
        patch("app.core.iters._git_branches", return_value=[]),
        patch("app.core.iters._git_recent_commits", return_value=[]),
        patch("app.core.iters._run", return_value=""),
        patch("app.core.driver._tmux_has", return_value=False),
    ):
        data = client.get("/api/state").json()
    assert "tmux" in data["loop"]
    assert data["loop"]["tmux"] is False


def test_state_cleanup_post_returns_ok(client: TestClient, tmp_state_dir, monkeypatch) -> None:
    """POST /api/state/cleanup should return ok with valid body."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_state_dir)
    with patch("app.core.driver._tmux_has", return_value=False):
        resp = client.post(
            "/api/state/cleanup",
            json={"kinds": ["failed", "discarded"]},
            headers={"Origin": "http://localhost:8766", "Host": "localhost:8766"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "cleared" in data


def test_state_cleanup_resets_orphans(client: TestClient, tmp_state_dir, monkeypatch) -> None:
    """POST /api/state/cleanup with reset_orphan_in_progress flips orphans to pending."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_state_dir)
    # Write state with an in_progress item
    state_file = tmp_state_dir / "work-state.json"
    state_file.write_text(
        json.dumps(
            {
                "items": [
                    {"id": "orphan-1", "title": "Orphan", "status": "in_progress", "attempts": 1},
                    {"id": "ok-1", "title": "OK", "status": "pending", "attempts": 0},
                ]
            }
        )
    )
    with patch("app.core.driver._tmux_has", return_value=False):
        resp = client.post(
            "/api/state/cleanup",
            json={"kinds": ["failed"], "reset_orphan_in_progress": True},
            headers={"Origin": "http://localhost:8766", "Host": "localhost:8766"},
        )
    data = resp.json()
    assert data["ok"] is True
    assert "orphan-1" in data.get("reset_to_pending", [])
