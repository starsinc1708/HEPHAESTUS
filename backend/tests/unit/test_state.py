"""Unit tests for core state module: _atomic_write, _read_state, _write_state."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.core.state import _atomic_write, _read_state, _write_state


def test_atomic_write_creates_file(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "test.json"
    _atomic_write(target, '{"hello": "world"}')
    assert target.exists()
    assert json.loads(target.read_text()) == {"hello": "world"}


def test_atomic_write_is_atomic(tmp_path: pathlib.Path) -> None:
    """No .tmp file should remain after successful write."""
    target = tmp_path / "test.json"
    _atomic_write(target, '{"ok": true}')
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0


def test_read_state_missing_file(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path)
    result = _read_state()
    assert result == {"items": []}


def test_read_state_valid_file(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path)
    state_file = tmp_path / "work-state.json"
    state_file.write_text('{"items": [{"id": "x", "status": "pending"}]}')
    result = _read_state()
    assert len(result["items"]) == 1
    assert result["items"][0]["id"] == "x"


def test_read_state_corrupt_returns_lkg(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path)
    state_file = tmp_path / "work-state.json"
    state_file.write_text('{"items": [{"id": "cached"}]}')
    _read_state()  # populates LKG
    state_file.write_text("NOT VALID JSON {{{")
    result = _read_state()
    assert result["items"][0]["id"] == "cached"


def test_write_state_adds_updated_at(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path)
    _write_state({"items": []})
    state_file = tmp_path / "work-state.json"
    data = json.loads(state_file.read_text())
    assert "updatedAt" in data


def test_write_state_validates_json(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_write_state should refuse to write invalid JSON (guard rail test)."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path)
    _write_state({"items": [{"id": "t"}]})
    state_file = tmp_path / "work-state.json"
    data = json.loads(state_file.read_text())
    assert data["items"][0]["id"] == "t"


# ---------- backup rotation tests ----------


def test_backup_rotation_creates_bak1(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After 2 writes, work-state.json.bak.1 must exist with the previous state."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path)
    monkeypatch.setenv("HEPHAESTUS_BACKUP_KEEP", "5")

    _write_state({"items": [{"id": "first"}]})
    _write_state({"items": [{"id": "second"}]})

    bak1 = tmp_path / "work-state.json.bak.1"
    assert bak1.exists()
    data = json.loads(bak1.read_text())
    assert data["items"][0]["id"] == "first"


def test_backup_rotation_keeps_n_backups(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After K writes, there are min(K-1, keep) backup files."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path)
    keep = 3
    monkeypatch.setenv("HEPHAESTUS_BACKUP_KEEP", str(keep))

    for i in range(5):
        _write_state({"items": [{"id": f"item-{i}"}]})

    # 5 writes → 4 previous states, but capped at keep=3 → 3 backups
    backups = sorted(tmp_path.glob("work-state.json.bak.*"))
    assert len(backups) == 3
    # .bak.1 = most recent previous = item-3 (write #4, current is write #5)
    data1 = json.loads((tmp_path / "work-state.json.bak.1").read_text())
    assert data1["items"][0]["id"] == "item-3"


def test_backup_rotation_oldest_dropped(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After keep+1 writes, the oldest backup beyond keep is removed."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path)
    keep = 3
    monkeypatch.setenv("HEPHAESTUS_BACKUP_KEEP", str(keep))

    for i in range(6):
        _write_state({"items": [{"id": f"item-{i}"}]})

    # keep=3, so only .bak.1, .bak.2, .bak.3 should exist
    for n in range(1, keep + 1):
        assert (tmp_path / f"work-state.json.bak.{n}").exists()
    # .bak.4 should NOT exist (dropped)
    assert not (tmp_path / "work-state.json.bak.4").exists()


def test_backup_failure_does_not_crash_write(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If shutil.copy2 raises, _write_state must still succeed."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path)
    monkeypatch.setenv("HEPHAESTUS_BACKUP_KEEP", "5")

    # First write to create the state file
    _write_state({"items": [{"id": "first"}]})

    # Make copy2 raise on subsequent calls
    monkeypatch.setattr(state_mod.shutil, "copy2", lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")))

    # Second write must NOT raise despite backup failure
    _write_state({"items": [{"id": "second"}]})

    # The state file should still be written correctly
    state_file = tmp_path / "work-state.json"
    data = json.loads(state_file.read_text())
    assert data["items"][0]["id"] == "second"


def test_backup_rotation_content_correct(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each .bak.N contains the N-th previous state content."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path)
    keep = 5
    monkeypatch.setenv("HEPHAESTUS_BACKUP_KEEP", str(keep))

    for i in range(5):
        _write_state({"items": [{"id": f"v{i}"}]})

    # After 5 writes: current=v4, .bak.1=v3, .bak.2=v2, .bak.3=v1, .bak.4=v0
    assert json.loads((tmp_path / "work-state.json.bak.1").read_text())["items"][0]["id"] == "v3"
    assert json.loads((tmp_path / "work-state.json.bak.2").read_text())["items"][0]["id"] == "v2"
    assert json.loads((tmp_path / "work-state.json.bak.3").read_text())["items"][0]["id"] == "v1"
    assert json.loads((tmp_path / "work-state.json.bak.4").read_text())["items"][0]["id"] == "v0"


def test_write_state_raises_on_invalid_json(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_write_state should raise RuntimeError when json.dumps produces invalid JSON."""
    import app.core.state as state_mod

    monkeypatch.setattr(state_mod, "STATE_DIR", tmp_path)

    # Patch json.dumps to return invalid JSON so json.loads validation fails
    def _bad_dumps(obj: object, **kwargs: object) -> str:
        return "NOT VALID JSON {{{"

    monkeypatch.setattr(json, "dumps", _bad_dumps)

    with pytest.raises(RuntimeError, match="_write_state produced invalid JSON"):
        _write_state({"items": [{"id": "bad"}]})
