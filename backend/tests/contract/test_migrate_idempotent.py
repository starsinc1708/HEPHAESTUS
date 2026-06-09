"""Contract: migrate_legacy_state is idempotent and sets workspaceId."""
from __future__ import annotations

import json
import pathlib
import subprocess

import pytest


def test_migrate_once_and_idempotent(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, timeout=30, check=True)

    legacy = tmp_path / "legacy-state"
    legacy.mkdir()
    (legacy / "work-state.json").write_text(json.dumps({"items": [{"id": "a", "title": "A", "status": "pending"}]}))
    (legacy / "decisions.log").write_text("x\n")

    home = tmp_path / "home"

    import app.core.migrate as migrate_mod
    monkeypatch.setattr(migrate_mod, "_LEGACY_STATE_DIR", legacy, raising=False)
    monkeypatch.setattr(migrate_mod, "_LEGACY_REPO", str(repo), raising=False)
    monkeypatch.setattr(migrate_mod, "_HOME", home, raising=False)

    res1 = migrate_mod.migrate_legacy_state()
    assert res1["migrated"] is True
    ws_id = res1["workspaceId"]
    # State is migrated INTO the working repo's .hephaestus/state (not the registry root).
    moved = repo / ".hephaestus" / "state" / "work-state.json"
    assert moved.exists()
    items = json.loads(moved.read_text())["items"]
    assert items[0]["workspaceId"] == ws_id
    assert (home / ".migrated").exists()

    res2 = migrate_mod.migrate_legacy_state()
    assert res2["migrated"] is False
