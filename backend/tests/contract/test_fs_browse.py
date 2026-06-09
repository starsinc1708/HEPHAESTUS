"""Contract tests for GET /api/v1/fs/browse — the repository-picker directory browser."""
from __future__ import annotations

import pathlib

from fastapi.testclient import TestClient


def _names(entries: list[dict[str, object]]) -> set[str]:
    return {str(e["name"]) for e in entries}


def test_browse_lists_subdirs_and_flags_git_repos(client: TestClient, tmp_path: pathlib.Path) -> None:
    """Immediate child dirs are listed; a dir containing .git is flagged isGitRepo; dot-dirs hidden."""
    (tmp_path / "my-repo" / ".git").mkdir(parents=True)
    (tmp_path / "plain-dir").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "a-file.txt").write_text("x")

    r = client.get("/api/v1/fs/browse", params={"path": str(tmp_path)})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["path"] == tmp_path.as_posix()
    assert data["parent"] == tmp_path.parent.as_posix()

    by_name = {str(e["name"]): e for e in data["entries"]}
    assert _names(data["entries"]) == {"my-repo", "plain-dir"}  # dot-dir + file excluded
    assert by_name["my-repo"]["isGitRepo"] is True
    assert by_name["plain-dir"]["isGitRepo"] is False
    # Paths are absolute POSIX-style and point at the children.
    assert by_name["my-repo"]["path"] == (tmp_path / "my-repo").as_posix()


def test_browse_nonexistent_path_falls_back_gracefully(client: TestClient, tmp_path: pathlib.Path) -> None:
    """A non-existent path never errors: it resolves to the nearest existing ancestor (ok stays True)."""
    missing = tmp_path / "does-not-exist" / "nested"
    r = client.get("/api/v1/fs/browse", params={"path": str(missing)})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    # Falls back to the nearest existing ancestor — here tmp_path.
    assert data["path"] == tmp_path.as_posix()


def test_browse_empty_path_returns_root(client: TestClient) -> None:
    """No path → the filesystem root, which has no parent."""
    r = client.get("/api/v1/fs/browse")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["parent"] is None
    assert isinstance(data["entries"], list)
