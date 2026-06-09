"""_restore_base_branch: sequential mode must return the main checkout to base after an
item, discarding the agent's partial uncommitted edits, without deleting the auto/ branch."""
from __future__ import annotations

import pathlib
import subprocess
from types import SimpleNamespace

from app.orchestrator.fsm import OrchestratorFSM


def _git(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True).stdout.strip()


def _repo(tmp_path: pathlib.Path) -> pathlib.Path:
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "--initial-branch=master")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("base", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "init")
    return r


def test_restore_returns_to_base_and_reverts_tracked_partial(tmp_path: pathlib.Path) -> None:
    r = _repo(tmp_path)
    _git(r, "checkout", "-b", "auto/idea-x-1")              # sequential preflight did this
    (r / "a.txt").write_text("agent partial edit", encoding="utf-8")  # uncommitted tracked edit

    fsm = OrchestratorFSM()
    fsm._parallel = False
    fsm._worktree = None
    fsm._ws = SimpleNamespace(repo_path=str(r), base_branch="master")  # type: ignore[assignment]
    fsm._restore_base_branch()

    assert _git(r, "rev-parse", "--abbrev-ref", "HEAD") == "master"   # back on base
    assert (r / "a.txt").read_text(encoding="utf-8") == "base"        # tracked partial edit reverted
    assert "auto/idea-x-1" in _git(r, "branch")                       # branch preserved (for merge)


def test_restore_noop_in_parallel(tmp_path: pathlib.Path) -> None:
    r = _repo(tmp_path)
    _git(r, "checkout", "-b", "auto/idea-y-1")
    fsm = OrchestratorFSM()
    fsm._parallel = True  # worktree-isolated worker — must NOT touch the main checkout
    fsm._ws = SimpleNamespace(repo_path=str(r), base_branch="master")  # type: ignore[assignment]
    fsm._restore_base_branch()
    assert _git(r, "rev-parse", "--abbrev-ref", "HEAD") == "auto/idea-y-1"  # untouched
