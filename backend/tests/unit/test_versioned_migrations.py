"""ARCH-005: Versioned migration system tests."""
from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

import app.core.migrate as mod

# ---------------------------------------------------------------------------
# Helpers — lightweight migration stubs
# ---------------------------------------------------------------------------


class _OkMigration:
    """A migration that succeeds and records its run."""

    def __init__(self, mid: str, desc: str = "") -> None:
        self.id = mid
        self.description = desc or f"migration {mid}"
        self.calls: list[pathlib.Path] = []

    def run(self, state_dir: pathlib.Path) -> dict[str, Any]:
        self.calls.append(state_dir)
        return {"ok": True}


class _FailMigration:
    """A migration that raises."""

    id = "999_fail"
    description = "always fails"

    def run(self, state_dir: pathlib.Path) -> dict[str, Any]:
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReadApplied:
    def test_missing_file_returns_empty(self, tmp_path: pathlib.Path) -> None:
        assert mod._read_applied(tmp_path) == set()

    def test_valid_file(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / ".migrations.json"
        f.write_text(json.dumps({"applied": ["001_a", "002_b"]}))
        assert mod._read_applied(tmp_path) == {"001_a", "002_b"}

    def test_corrupt_file_returns_empty(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / ".migrations.json"
        f.write_text("NOT JSON{{{")
        assert mod._read_applied(tmp_path) == set()

    def test_empty_applied_list(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / ".migrations.json"
        f.write_text(json.dumps({"applied": []}))
        assert mod._read_applied(tmp_path) == set()


class TestWriteApplied:
    def test_roundtrip(self, tmp_path: pathlib.Path) -> None:
        ids = {"003_c", "001_a", "002_b"}
        mod._write_applied(tmp_path, ids)
        result = mod._read_applied(tmp_path)
        assert result == ids

    def test_version_field(self, tmp_path: pathlib.Path) -> None:
        mod._write_applied(tmp_path, {"001_a", "002_b"})
        data = json.loads((tmp_path / ".migrations.json").read_text())
        assert data["version"] == 2

    def test_sorted_order(self, tmp_path: pathlib.Path) -> None:
        mod._write_applied(tmp_path, {"003_c", "001_a"})
        data = json.loads((tmp_path / ".migrations.json").read_text())
        assert data["applied"] == ["001_a", "003_c"]


class TestRunMigrations:
    def test_empty_registry(self, tmp_path: pathlib.Path) -> None:
        result = mod.run_migrations(tmp_path)
        assert result["applied"] == []
        assert result["skipped"] == []
        assert result["total"] == 0

    def test_apply_two_in_order(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        m1 = _OkMigration("001_a")
        m2 = _OkMigration("002_b")
        monkeypatch.setattr(mod, "_ALL_MIGRATIONS", [m1, m2])

        result = mod.run_migrations(tmp_path)
        assert result["applied"] == ["001_a", "002_b"]
        assert result["skipped"] == []
        assert result["total"] == 2

        # File on disk
        data = json.loads((tmp_path / ".migrations.json").read_text())
        assert data["applied"] == ["001_a", "002_b"]

    def test_rerun_is_noop(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        m1 = _OkMigration("001_a")
        m2 = _OkMigration("002_b")
        monkeypatch.setattr(mod, "_ALL_MIGRATIONS", [m1, m2])

        mod.run_migrations(tmp_path)
        assert len(m1.calls) == 1
        assert len(m2.calls) == 1

        result = mod.run_migrations(tmp_path)
        assert result["applied"] == []
        assert result["skipped"] == ["001_a", "002_b"]
        # Not called again
        assert len(m1.calls) == 1
        assert len(m2.calls) == 1

    def test_failure_stops_chain(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        m1 = _OkMigration("001_a")
        m_fail: _OkMigration | _FailMigration = _FailMigration()
        m3 = _OkMigration("003_c")
        monkeypatch.setattr(mod, "_ALL_MIGRATIONS", [m1, m_fail, m3])

        result = mod.run_migrations(tmp_path)
        assert result["applied"] == ["001_a"]
        # m3 was never reached
        assert len(m3.calls) == 0
        # Only 001_a tracked on disk
        data = json.loads((tmp_path / ".migrations.json").read_text())
        assert data["applied"] == ["001_a"]

    def test_corrupt_file_reruns_all(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        m1 = _OkMigration("001_a")
        monkeypatch.setattr(mod, "_ALL_MIGRATIONS", [m1])

        # Write corrupt file
        (tmp_path / ".migrations.json").write_text("BAD")

        result = mod.run_migrations(tmp_path)
        assert result["applied"] == ["001_a"]
        assert len(m1.calls) == 1

    def test_version_written_correctly(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        m1 = _OkMigration("001_a")
        m2 = _OkMigration("002_b")
        monkeypatch.setattr(mod, "_ALL_MIGRATIONS", [m1, m2])

        mod.run_migrations(tmp_path)
        data = json.loads((tmp_path / ".migrations.json").read_text())
        assert data["version"] == 2

    def test_no_file_written_when_nothing_applied(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        m1 = _OkMigration("001_a")
        monkeypatch.setattr(mod, "_ALL_MIGRATIONS", [m1])

        # Pre-apply via file so everything is skipped
        mod._write_applied(tmp_path, {"001_a"})
        (tmp_path / ".migrations.json").unlink()

        # No migrations list, so nothing applies, no file written
        monkeypatch.setattr(mod, "_ALL_MIGRATIONS", [])
        mod.run_migrations(tmp_path)
        assert not (tmp_path / ".migrations.json").exists()
