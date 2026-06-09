"""Unit tests for app.core.diff_tests — the deterministic test-running safety net.

detect_kind / _js_runner are pure. changed_test_files + run_diff_tests are exercised
against a REAL temp git repo and the REAL pytest runner (available in this venv), so
the Python path is verified end-to-end with no mocking.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import subprocess

import pytest

from app.core.diff_tests import (
    _js_runner,
    changed_test_files,
    detect_kind,
    run_diff_tests,
)


# ---------------------------------------------------------------- detect_kind
@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/useCamera.test.js", "js"),
        ("src/useCamera.spec.ts", "js"),
        ("a/b/Widget.test.tsx", "js"),
        ("a/b/Widget.spec.jsx", "js"),
        ("pkg/feature.test.mjs", "js"),
        ("tests/test_thing.py", "py"),
        ("tests/thing_test.py", "py"),
        ("pkg/handler_test.go", "go"),
        # negatives
        ("src/useCamera.js", None),          # impl, not a test
        ("src/testing.ts", None),            # 'test' substring, not *.test
        ("README.md", None),
        ("tests/conftest.py", None),
        ("pkg/handler.go", None),
        ("noextension", None),
    ],
)
def test_detect_kind(path, expected):
    assert detect_kind(path) == expected


# ----------------------------------------------------------------- _js_runner
def _write_pkg(d: pathlib.Path, dev: dict[str, str]) -> None:
    (d / "package.json").write_text(json.dumps({"devDependencies": dev}), encoding="utf-8")


def test_js_runner_prefers_vitest(tmp_path):
    _write_pkg(tmp_path, {"vitest": "^1.0", "jest": "^29"})
    assert _js_runner(str(tmp_path)) == "vitest"


def test_js_runner_detects_jest(tmp_path):
    _write_pkg(tmp_path, {"jest": "^29"})
    assert _js_runner(str(tmp_path)) == "jest"


def test_js_runner_none_when_absent(tmp_path):
    _write_pkg(tmp_path, {"eslint": "^9"})
    assert _js_runner(str(tmp_path)) is None


def test_js_runner_none_when_no_package_json(tmp_path):
    assert _js_runner(str(tmp_path)) is None


# ---------------------------------------------- changed_test_files (real git)
def _git(repo: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _init_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    return repo


def test_changed_test_files_picks_up_untracked(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "thing_test.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    (repo / "notes.md").write_text("hi\n", encoding="utf-8")          # not a test
    found = changed_test_files(str(repo), "origin/main")              # base_ref absent → '' (no crash)
    assert found == [("thing_test.py", "py")]


# ------------------------------------------------- run_diff_tests (real pytest)
def test_run_diff_tests_no_tests_is_ok(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "readme.md").write_text("x\n", encoding="utf-8")
    res = asyncio.run(run_diff_tests(
        str(repo), "origin/main", log_path=repo / "dt.log", timeout_sec=120
    ))
    assert res.ok is True
    assert res.ran == [] and res.failed == [] and res.unrun == []


def test_run_diff_tests_green_pytest_passes(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "test_green.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    res = asyncio.run(run_diff_tests(
        str(repo), "origin/main", log_path=repo / "dt.log", timeout_sec=120
    ))
    assert res.ok is True
    assert res.ran == ["test_green.py"]
    assert res.failed == []


def test_run_diff_tests_red_pytest_fails(tmp_path):
    repo = _init_repo(tmp_path)
    # Mirrors the camera regression: a committed test that does not match reality.
    (repo / "test_red.py").write_text("def test_broken():\n    assert 1 + 1 == 3\n", encoding="utf-8")
    res = asyncio.run(run_diff_tests(
        str(repo), "origin/main", log_path=repo / "dt.log", timeout_sec=120
    ))
    assert res.ok is False
    assert res.failed == ["test_red.py"]
    assert res.ran == []
    # the runner's output was captured for the drawer
    assert (repo / "dt.log").read_text(encoding="utf-8", errors="replace").strip() != ""


def test_run_diff_tests_js_without_runner_is_unrun_not_failed(tmp_path):
    """A JS test file with no resolvable runner (no package.json) is surfaced as
    `unrun`, never a failure — we don't fail a task because we couldn't run it."""
    repo = _init_repo(tmp_path)
    (repo / "widget.test.js").write_text("it('x', () => { expect(1).toBe(2) })\n", encoding="utf-8")
    res = asyncio.run(run_diff_tests(
        str(repo), "origin/main", log_path=repo / "dt.log", timeout_sec=120
    ))
    assert res.ok is True                       # unrun ≠ failed
    assert res.unrun == ["widget.test.js"]
    assert res.failed == []
