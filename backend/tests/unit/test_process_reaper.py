"""Unit tests for ProcessManager.reap_orphans() — zombie/orphan subprocess reaping."""
from __future__ import annotations

import json
import sys

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_process_json(tmp_path, data: dict) -> None:
    (tmp_path / "process.json").write_text(json.dumps(data), encoding="utf-8")


def _read_process_json(tmp_path) -> dict:
    p = tmp_path / "process.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReapOrphans:
    """REL-002: reap_orphans kills orphaned children and cleans tracking."""

    def test_reap_noop_under_pytest(self, tmp_path, monkeypatch):
        """When pytest is in sys.modules, reap_orphans returns [] without touching anything."""
        from app.core.process import ProcessManager

        pm = ProcessManager(state_dir=tmp_path)
        _write_process_json(tmp_path, {"loop": {"pid": 99999, "children": [88888]}})

        # Even if all PIDs are "dead", pytest guard must return early.
        monkeypatch.setattr("app.core.process._pid_alive", lambda pid: False)
        killed: list[int] = []
        monkeypatch.setattr("app.core.process._kill_tree", lambda pid: killed.append(pid))

        # pytest is already in sys.modules because we're running under pytest.
        reaped = pm.reap_orphans()
        assert reaped == []
        assert killed == []

    def test_reap_dead_root_with_live_children(self, tmp_path, monkeypatch):
        """Dead root PID + live child PIDs → children killed, entry cleaned up."""
        from app.core.process import ProcessManager

        pm = ProcessManager(state_dir=tmp_path)
        _write_process_json(tmp_path, {
            "loop": {"pid": 99999, "children": [88888, 77777]},
        })

        # Root 99999 is dead, child 88888 is alive, child 77777 is also alive.
        alive_pids = {88888, 77777}
        monkeypatch.setattr("app.core.process._pid_alive", lambda pid: pid in alive_pids)

        killed: list[int] = []
        monkeypatch.setattr("app.core.process._kill_tree", lambda pid: killed.append(pid))

        # Temporarily remove pytest from sys.modules to bypass safety guard.
        pytest_mod = sys.modules.pop("pytest", None)
        try:
            reaped = pm.reap_orphans()
        finally:
            if pytest_mod is not None:
                sys.modules["pytest"] = pytest_mod

        assert reaped == ["loop"]
        assert 88888 in killed
        assert 77777 in killed
        # Entry should be removed from process.json.
        assert "loop" not in _read_process_json(tmp_path)

    def test_reap_alive_root_not_touched(self, tmp_path, monkeypatch):
        """Alive root PID → nothing killed, entry stays in process.json."""
        from app.core.process import ProcessManager

        pm = ProcessManager(state_dir=tmp_path)
        _write_process_json(tmp_path, {
            "scan": {"pid": 55555, "children": [44444]},
        })

        # Root 55555 is alive.
        alive_pids = {55555, 44444}
        monkeypatch.setattr("app.core.process._pid_alive", lambda pid: pid in alive_pids)

        killed: list[int] = []
        monkeypatch.setattr("app.core.process._kill_tree", lambda pid: killed.append(pid))

        pytest_mod = sys.modules.pop("pytest", None)
        try:
            reaped = pm.reap_orphans()
        finally:
            if pytest_mod is not None:
                sys.modules["pytest"] = pytest_mod

        assert reaped == []
        assert killed == []
        data = _read_process_json(tmp_path)
        assert "scan" in data
        assert data["scan"]["pid"] == 55555

    def test_reap_empty_process_json(self, tmp_path, monkeypatch):
        """No process.json → returns [] without error."""
        from app.core.process import ProcessManager

        pm = ProcessManager(state_dir=tmp_path)
        # Ensure no process.json exists.
        assert not (tmp_path / "process.json").exists()

        killed: list[int] = []
        monkeypatch.setattr("app.core.process._kill_tree", lambda pid: killed.append(pid))

        pytest_mod = sys.modules.pop("pytest", None)
        try:
            reaped = pm.reap_orphans()
        finally:
            if pytest_mod is not None:
                sys.modules["pytest"] = pytest_mod

        assert reaped == []
        assert killed == []

    def test_reap_corrupt_process_json(self, tmp_path, monkeypatch):
        """Corrupt JSON → returns [] without crashing."""
        from app.core.process import ProcessManager

        pm = ProcessManager(state_dir=tmp_path)
        (tmp_path / "process.json").write_text("{{{{not json!!", encoding="utf-8")

        killed: list[int] = []
        monkeypatch.setattr("app.core.process._kill_tree", lambda pid: killed.append(pid))

        pytest_mod = sys.modules.pop("pytest", None)
        try:
            reaped = pm.reap_orphans()
        finally:
            if pytest_mod is not None:
                sys.modules["pytest"] = pytest_mod

        assert reaped == []
        assert killed == []

    def test_reap_removes_dead_entries(self, tmp_path, monkeypatch):
        """Dead root, no children → entry removed from process.json, no kills needed."""
        from app.core.process import ProcessManager

        pm = ProcessManager(state_dir=tmp_path)
        _write_process_json(tmp_path, {
            "merge-agent": {"pid": 12345, "children": []},
        })

        # Root 12345 is dead, no children.
        monkeypatch.setattr("app.core.process._pid_alive", lambda pid: False)

        killed: list[int] = []
        monkeypatch.setattr("app.core.process._kill_tree", lambda pid: killed.append(pid))

        pytest_mod = sys.modules.pop("pytest", None)
        try:
            reaped = pm.reap_orphans()
        finally:
            if pytest_mod is not None:
                sys.modules["pytest"] = pytest_mod

        assert reaped == ["merge-agent"]
        assert killed == []
        assert "merge-agent" not in _read_process_json(tmp_path)

    def test_reap_mixed_entries(self, tmp_path, monkeypatch):
        """Multiple entries: some alive roots, some dead — only dead get reaped."""
        from app.core.process import ProcessManager

        pm = ProcessManager(state_dir=tmp_path)
        _write_process_json(tmp_path, {
            "loop": {"pid": 100, "children": [101]},
            "scan": {"pid": 200, "children": [201, 202]},
            "merge-agent": {"pid": 300, "children": []},
        })

        # loop root (100) alive, scan root (200) dead, merge-agent root (300) dead.
        alive_pids = {100, 101, 201, 202}
        monkeypatch.setattr("app.core.process._pid_alive", lambda pid: pid in alive_pids)

        killed: list[int] = []
        monkeypatch.setattr("app.core.process._kill_tree", lambda pid: killed.append(pid))

        pytest_mod = sys.modules.pop("pytest", None)
        try:
            reaped = pm.reap_orphans()
        finally:
            if pytest_mod is not None:
                sys.modules["pytest"] = pytest_mod

        assert sorted(reaped) == ["merge-agent", "scan"]
        # scan children 201, 202 should be killed.
        assert 201 in killed
        assert 202 in killed
        # loop should remain untouched.
        data = _read_process_json(tmp_path)
        assert "loop" in data
        assert "scan" not in data
        assert "merge-agent" not in data

    def test_reap_dead_child_not_killed(self, tmp_path, monkeypatch):
        """Dead root with dead children → entry cleaned but _kill_tree NOT called."""
        from app.core.process import ProcessManager

        pm = ProcessManager(state_dir=tmp_path)
        _write_process_json(tmp_path, {
            "loop": {"pid": 99999, "children": [88888]},
        })

        # Everything is dead.
        monkeypatch.setattr("app.core.process._pid_alive", lambda pid: False)

        killed: list[int] = []
        monkeypatch.setattr("app.core.process._kill_tree", lambda pid: killed.append(pid))

        pytest_mod = sys.modules.pop("pytest", None)
        try:
            reaped = pm.reap_orphans()
        finally:
            if pytest_mod is not None:
                sys.modules["pytest"] = pytest_mod

        assert reaped == ["loop"]
        # _kill_tree should NOT be called because the child is already dead.
        assert killed == []
