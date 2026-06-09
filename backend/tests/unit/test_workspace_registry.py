"""Unit: WorkspaceRegistry CRUD, idempotent create, path resolution."""
from __future__ import annotations

import pathlib
import subprocess

import pytest


def _git_init(p: pathlib.Path) -> None:
    p.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(p)], capture_output=True, timeout=30, check=True)


def _reg(home: pathlib.Path):
    from app.core.workspaces import WorkspaceRegistry
    return WorkspaceRegistry(home=home)


def test_create_idempotent(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "repo"
    _git_init(repo)
    reg = _reg(tmp_path / "home")
    a = reg.create(str(repo), name="repo")
    b = reg.create(str(repo))
    assert a.id == b.id
    assert len(reg.list()) == 1


def test_id_case_insensitive(tmp_path: pathlib.Path) -> None:
    from app.core.workspaces import WorkspaceRegistry

    repo = tmp_path / "Repo"
    _git_init(repo)
    id1 = WorkspaceRegistry.ws_id_for(str(repo))
    id2 = WorkspaceRegistry.ws_id_for(str(repo).upper())
    assert id1 == id2
    assert len(id1) == 16


def test_create_rejects_non_git(tmp_path: pathlib.Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    reg = _reg(tmp_path / "home")
    with pytest.raises(ValueError, match="not a git repository"):
        reg.create(str(plain))


def test_activate_and_active(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "repo"
    _git_init(repo)
    reg = _reg(tmp_path / "home")
    ws = reg.create(str(repo))
    assert reg.active() is None
    reg.activate(ws.id)
    assert reg.active().id == ws.id


def test_state_and_memory_dir(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "repo"
    _git_init(repo)
    home = tmp_path / "home"
    reg = _reg(home)
    ws = reg.create(str(repo))
    sd = reg.state_dir(ws)
    md = reg.memory_dir(ws)
    # All per-workspace data lives inside the working repo's .hephaestus/ dir.
    assert sd == pathlib.Path(ws.repo_path) / ".hephaestus" / "state"
    assert md == pathlib.Path(ws.repo_path) / ".hephaestus" / "memory"
    # profile.json is written into the repo, not the global registry root.
    assert (pathlib.Path(ws.repo_path) / ".hephaestus" / "profile.json").exists()
    # the global index only records id -> repoPath + active.
    assert (home / "registry.json").exists()


def test_update_persists(tmp_path: pathlib.Path) -> None:
    repo = tmp_path / "repo"
    _git_init(repo)
    home = tmp_path / "home"
    reg = _reg(home)
    ws = reg.create(str(repo))
    reg.update(ws.id, {"onboarded": True, "strictness": "strict"})
    reg2 = _reg(home)
    got = reg2.get(ws.id)
    assert got.onboarded is True
    assert got.strictness == "strict"
