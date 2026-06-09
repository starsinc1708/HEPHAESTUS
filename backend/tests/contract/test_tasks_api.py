"""Contract tests for the tasks checks API (Improvement 3)."""
from __future__ import annotations


def test_task_checks_not_found(client, tmp_path, monkeypatch) -> None:
    import app.core.state as state_mod

    sd = tmp_path / "st"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.get("/api/v1/tasks/nonexistent/checks")
    assert r.status_code == 404
    assert r.json()["ok"] is False


def test_task_checks_found_no_outcome(client, tmp_path, monkeypatch) -> None:
    import app.core.state as state_mod
    from app.core.state import _write_state

    sd = tmp_path / "st"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    # Pre-seed task
    state_data = {
        "items": [
            {
                "id": "task-123",
                "status": "pending",
                "title": "A task",
            }
        ]
    }
    _write_state(state_data)

    r = client.get("/api/v1/tasks/task-123/checks")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["verifyOutcome"] is None
    assert data["scopeExtra"] == []
    assert "verify_outcome" not in data  # camelCase contract only


def test_task_checks_found_with_outcome(client, tmp_path, monkeypatch) -> None:
    import app.core.state as state_mod
    from app.core.state import _write_state

    sd = tmp_path / "st"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    # Pre-seed task with verify_outcome
    verify_outcome = {
        "passed": True,
        "checks_ran": 3,
        "unverified": False,
        "detail": "3 checks ran",
    }
    state_data = {
        "items": [
            {
                "id": "task-123",
                "status": "done",
                "title": "A task",
                "verify_outcome": verify_outcome,
                "scope_extra": ["rogue.txt"],
            }
        ]
    }
    _write_state(state_data)

    r = client.get("/api/v1/tasks/task-123/checks")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["verifyOutcome"] == verify_outcome
    assert data["scopeExtra"] == ["rogue.txt"]
