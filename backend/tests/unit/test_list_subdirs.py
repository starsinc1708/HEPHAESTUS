"""Unit tests for scan_run.list_subdirs — the scan-scope picker backend."""
from __future__ import annotations

import pathlib

from app.core.scan_run import list_subdirs


def _touch(p: pathlib.Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")


def test_lists_immediate_dirs_skips_vendor_and_dotdirs(tmp_path: pathlib.Path) -> None:
    _touch(tmp_path / "src" / "a.py")
    _touch(tmp_path / "src" / "sub" / "b.py")
    _touch(tmp_path / "packages" / "c.ts")
    _touch(tmp_path / "node_modules" / "dep" / "index.js")  # vendor -> hidden
    _touch(tmp_path / ".git" / "HEAD")                      # SKIP_DIRS -> hidden
    _touch(tmp_path / ".github" / "ci.yml")                # dotdir -> hidden

    dirs = list_subdirs(str(tmp_path))
    names = [d["name"] for d in dirs]
    assert names == ["packages", "src"]  # sorted, vendor/dot hidden

    src = next(d for d in dirs if d["name"] == "src")
    assert src["path"] == "src"
    assert src["files"] == 2          # a.py + sub/b.py (recursive)
    assert src["hasChildren"] is True
    assert next(d for d in dirs if d["name"] == "packages")["hasChildren"] is False


def test_file_count_prunes_vendor_dirs(tmp_path: pathlib.Path) -> None:
    _touch(tmp_path / "app" / "real.py")
    _touch(tmp_path / "app" / "node_modules" / "junk.js")
    _touch(tmp_path / "app" / "dist" / "bundle.js")
    app = next(d for d in list_subdirs(str(tmp_path)) if d["name"] == "app")
    assert app["files"] == 1  # node_modules + dist pruned


def test_lists_children_under_subpath(tmp_path: pathlib.Path) -> None:
    _touch(tmp_path / "apps" / "api" / "main.py")
    _touch(tmp_path / "apps" / "web" / "main.ts")
    names = [d["name"] for d in list_subdirs(str(tmp_path), "apps")]
    assert names == ["api", "web"]


def test_traversal_and_missing_return_empty(tmp_path: pathlib.Path) -> None:
    assert list_subdirs(str(tmp_path), "..") == []
    assert list_subdirs(str(tmp_path), "../../etc") == []
    assert list_subdirs(str(tmp_path), "does-not-exist") == []
