"""Tests for scope-guard: prevent out-of-scope commits."""
from __future__ import annotations

import pathlib
import subprocess

import pytest


@pytest.fixture()
def git_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a tiny git repo with a base branch and a feature branch."""
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(tmp_path), capture_output=True)
    # Initial commit on main
    (tmp_path / "README.md").write_text("init", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
    # Create feature branch
    subprocess.run(["git", "checkout", "-b", "feat/test"], cwd=str(tmp_path), capture_output=True)
    return tmp_path


def test_off_mode_always_passes(git_repo: pathlib.Path) -> None:
    from app.core.scope_guard import ScopeGuardMode, check_scope
    # Add out-of-scope file
    (git_repo / "top.txt").write_text("oops", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(git_repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "add top"], cwd=str(git_repo), capture_output=True)
    r = check_scope(str(git_repo), "main", "feat/test", ["src/foo.py"], ScopeGuardMode.OFF)
    assert r.ok is True


def test_advisory_reports_extra(git_repo: pathlib.Path) -> None:
    from app.core.scope_guard import ScopeGuardMode, check_scope
    (git_repo / "top.txt").write_text("oops", encoding="utf-8")
    (git_repo / "src").mkdir(exist_ok=True)
    (git_repo / "src" / "foo.py").write_text("ok", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(git_repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "changes"], cwd=str(git_repo), capture_output=True)
    r = check_scope(str(git_repo), "main", "feat/test", ["src/foo.py"], ScopeGuardMode.ADVISORY)
    assert r.ok is True
    assert "top.txt" in r.extra_files


def test_strict_blocks_extra(git_repo: pathlib.Path) -> None:
    from app.core.scope_guard import ScopeGuardMode, check_scope
    (git_repo / "top.txt").write_text("oops", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(git_repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "add top"], cwd=str(git_repo), capture_output=True)
    r = check_scope(str(git_repo), "main", "feat/test", ["src/foo.py"], ScopeGuardMode.STRICT)
    assert r.ok is False
    assert "top.txt" in r.extra_files


def test_no_extra_passes(git_repo: pathlib.Path) -> None:
    from app.core.scope_guard import ScopeGuardMode, check_scope
    (git_repo / "src").mkdir(exist_ok=True)
    (git_repo / "src" / "foo.py").write_text("ok", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(git_repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "ok"], cwd=str(git_repo), capture_output=True)
    r = check_scope(str(git_repo), "main", "feat/test", ["src/foo.py"], ScopeGuardMode.STRICT)
    assert r.ok is True
    assert r.extra_files == []


def test_lock_files_excluded(git_repo: pathlib.Path) -> None:
    from app.core.scope_guard import ScopeGuardMode, check_scope
    (git_repo / "package-lock.json").write_text("{}", encoding="utf-8")
    (git_repo / "src").mkdir(exist_ok=True)
    (git_repo / "src" / "foo.py").write_text("ok", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(git_repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "with lock"], cwd=str(git_repo), capture_output=True)
    r = check_scope(str(git_repo), "main", "feat/test", ["src/foo.py"], ScopeGuardMode.STRICT)
    assert r.ok is True  # lock file auto-excluded
    assert "package-lock.json" not in r.extra_files


def test_strict_catches_uncommitted_out_of_scope(git_repo: pathlib.Path) -> None:
    """The common FSM path: the agent leaves its changes UNCOMMITTED for the FSM to
    commit later. A committed-only diff would see nothing here and silently pass — the
    guard must inspect the working tree (incl. untracked) too."""
    from app.core.scope_guard import ScopeGuardMode, check_scope
    (git_repo / "src").mkdir(exist_ok=True)
    (git_repo / "src" / "foo.py").write_text("ok", encoding="utf-8")   # in scope, untracked
    (git_repo / "rogue.txt").write_text("oops", encoding="utf-8")       # out of scope, untracked
    # Nothing committed on feat/test — base..branch diff is empty.
    r = check_scope(str(git_repo), "main", "feat/test", ["src/foo.py"], ScopeGuardMode.STRICT)
    assert r.ok is False
    assert "rogue.txt" in r.extra_files
    assert "src/foo.py" not in r.extra_files


def test_glob_touch_matches_nested(git_repo: pathlib.Path) -> None:
    """A `src/**`-style touch must cover nested files (fnmatch '*' spans '/')."""
    from app.core.scope_guard import ScopeGuardMode, check_scope
    (git_repo / "src" / "deep").mkdir(parents=True, exist_ok=True)
    (git_repo / "src" / "deep" / "x.py").write_text("ok", encoding="utf-8")
    r = check_scope(str(git_repo), "main", "feat/test", ["src/**"], ScopeGuardMode.STRICT)
    assert r.ok is True
    assert r.extra_files == []


def test_empty_touches_advisory(git_repo: pathlib.Path) -> None:
    """When touches is empty, treat as advisory (everything allowed)."""
    from app.core.scope_guard import ScopeGuardMode, check_scope
    (git_repo / "anything.py").write_text("new", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(git_repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "ok"], cwd=str(git_repo), capture_output=True)
    r = check_scope(str(git_repo), "main", "feat/test", [], ScopeGuardMode.STRICT)
    assert r.ok is True  # empty touches = no restriction
