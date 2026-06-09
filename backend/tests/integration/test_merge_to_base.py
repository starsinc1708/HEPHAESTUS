"""GitService merge_preflight / merge_to_base on a temp git repo (no bash)."""

from __future__ import annotations

import subprocess

from app.core.git import GitService
from tests.conftest import make_repo_profile


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _make_auto_branch(repo, name="auto/x-1", content="patch\n"):
    _git(["checkout", "-b", name], repo)
    (repo / "feature.txt").write_text(content)
    _git(["add", "-A"], repo)
    _git(["commit", "-m", "feat"], repo)
    _git(["checkout", "main"], repo)


def test_preflight_blocks_when_dirty(tmp_git_repo, monkeypatch):
    _make_auto_branch(tmp_git_repo)
    (tmp_git_repo / "dirty.txt").write_text("uncommitted\n")
    ws = make_repo_profile(str(tmp_git_repo))
    gs = GitService(ws)
    monkeypatch.setattr(gs, "_find_item_by_branch", lambda b: {"branch": b})
    monkeypatch.setattr(gs, "_loop_active", lambda: False)
    pf = gs.merge_preflight("auto/x-1")
    assert pf.clean_tree is False
    assert pf.ok is False


def test_preflight_ok_when_clean_and_validated(tmp_git_repo, monkeypatch):
    _make_auto_branch(tmp_git_repo)
    ws = make_repo_profile(str(tmp_git_repo))
    gs = GitService(ws)
    # R11: persistent flags on the Task drive preflight (not status-prefix heuristics).
    monkeypatch.setattr(gs, "_find_item_by_branch",
                        lambda b: {"branch": b, "verify_green": True,
                                   "validation": {"gate": "pass"}})
    monkeypatch.setattr(gs, "_loop_active", lambda: False)
    pf = gs.merge_preflight("auto/x-1")
    assert pf.clean_tree is True
    assert pf.verify_green is True
    assert pf.validation_passed is True
    assert pf.loop_active is False
    assert pf.ok is True


def test_preflight_blocks_when_validation_failed(tmp_git_repo, monkeypatch):
    _make_auto_branch(tmp_git_repo)
    ws = make_repo_profile(str(tmp_git_repo))
    gs = GitService(ws)
    monkeypatch.setattr(gs, "_find_item_by_branch",
                        lambda b: {"branch": b, "verify_green": True,
                                   "validation": {"gate": "needs_revision"}})
    monkeypatch.setattr(gs, "_loop_active", lambda: False)
    pf = gs.merge_preflight("auto/x-1")
    assert pf.validation_passed is False
    assert pf.ok is False


def test_preflight_blocks_when_loop_running(tmp_git_repo, monkeypatch):
    """R11: merge forbidden while loop RUNNING even when everything else is green."""
    _make_auto_branch(tmp_git_repo)
    ws = make_repo_profile(str(tmp_git_repo))
    gs = GitService(ws)
    monkeypatch.setattr(gs, "_find_item_by_branch",
                        lambda b: {"branch": b, "verify_green": True,
                                   "validation": {"gate": "pass"}})
    monkeypatch.setattr(gs, "_loop_active", lambda: True)
    pf = gs.merge_preflight("auto/x-1")
    assert pf.loop_active is True
    assert pf.ok is False


def _green_item(gs, monkeypatch, branch):
    """R11: a persistent green Task for `branch`, loop not active."""
    monkeypatch.setattr(gs, "_find_item_by_branch",
                        lambda b: {"branch": b, "verify_green": True,
                                   "validation": {"gate": "pass"}})
    monkeypatch.setattr(gs, "_loop_active", lambda: False)


async def test_merge_clean_fast_forward(tmp_git_repo, monkeypatch):
    _make_auto_branch(tmp_git_repo)
    ws = make_repo_profile(str(tmp_git_repo))
    gs = GitService(ws)
    _green_item(gs, monkeypatch, "auto/x-1")
    # no remote → pull/push skipped; merge stays local
    res = await gs.merge_to_base("auto/x-1", push=False)
    assert res["ok"] is True
    assert res["action"] == "merge"
    log = subprocess.run(["git", "log", "--oneline", "main"], cwd=str(tmp_git_repo),
                         capture_output=True, text=True).stdout
    assert "feat" in log
    branches = subprocess.run(["git", "branch"], cwd=str(tmp_git_repo),
                              capture_output=True, text=True).stdout
    assert "auto/x-1" not in branches  # branch deleted after merge


async def test_merge_conflict_aborts(tmp_git_repo, monkeypatch):
    # base and branch both touch README.md differently → conflict
    _git(["checkout", "-b", "auto/x-2"], tmp_git_repo)
    (tmp_git_repo / "README.md").write_text("branch change\n")
    _git(["add", "-A"], tmp_git_repo)
    _git(["commit", "-m", "branch"], tmp_git_repo)
    _git(["checkout", "main"], tmp_git_repo)
    (tmp_git_repo / "README.md").write_text("base change\n")
    _git(["add", "-A"], tmp_git_repo)
    _git(["commit", "-m", "base"], tmp_git_repo)
    ws = make_repo_profile(str(tmp_git_repo))
    gs = GitService(ws)
    _green_item(gs, monkeypatch, "auto/x-2")
    res = await gs.merge_to_base("auto/x-2", push=False)
    assert res["ok"] is False
    assert "README.md" in res["conflicts"]
    porcelain = subprocess.run(["git", "status", "--porcelain"], cwd=str(tmp_git_repo),
                               capture_output=True, text=True).stdout
    assert porcelain.strip() == ""  # abort restored clean tree


async def test_merge_blocked_when_loop_running(tmp_git_repo, monkeypatch):
    """R11: loop RUNNING → merge_to_base returns ok:False 'loop active...' before touching git."""
    _make_auto_branch(tmp_git_repo)
    ws = make_repo_profile(str(tmp_git_repo))
    gs = GitService(ws)
    monkeypatch.setattr(gs, "_find_item_by_branch",
                        lambda b: {"branch": b, "verify_green": True,
                                   "validation": {"gate": "pass"}})
    monkeypatch.setattr(gs, "_loop_active", lambda: True)
    res = await gs.merge_to_base("auto/x-1", push=False)
    assert res["ok"] is False
    assert "loop active" in res["error"]


async def test_merge_unknown_branch_returns_error(tmp_git_repo, monkeypatch):
    """R11: no Task for branch → explicit error (router maps to 409), not a silent pass."""
    _make_auto_branch(tmp_git_repo)
    ws = make_repo_profile(str(tmp_git_repo))
    gs = GitService(ws)
    monkeypatch.setattr(gs, "_loop_active", lambda: False)
    monkeypatch.setattr(gs, "_find_item_by_branch", lambda b: None)
    res = await gs.merge_to_base("auto/x-1", push=False)
    assert res["ok"] is False
    assert "no task found" in res["error"]
