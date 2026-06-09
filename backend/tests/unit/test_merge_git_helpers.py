import pathlib
import subprocess

from app.core.git import _current_sha, _ff_merge, _worktree_add, _worktree_remove


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _make_repo(tmp_path) -> pathlib.Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "a@b.c")
    _git(r, "config", "user.name", "t")
    (r / "f.txt").write_text("base\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "init")
    return r


def test_worktree_add_remove_and_ff(tmp_path):
    repo = _make_repo(tmp_path)
    base_sha = _current_sha(str(repo), "main")
    assert base_sha and len(base_sha) >= 7
    _git(repo, "checkout", "-b", "auto/x")
    (repo / "g.txt").write_text("new\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add g")
    _git(repo, "checkout", "main")
    wt = tmp_path / "wt"
    assert _worktree_add(str(repo), str(wt), "hephaestus/merge/x", "main") is True
    _git(wt, "merge", "--no-ff", "--no-edit", "auto/x")
    assert _ff_merge(str(repo), "hephaestus/merge/x", "main") is True
    assert (repo / "g.txt").exists()
    _worktree_remove(str(repo), str(wt), "hephaestus/merge/x")
    assert not wt.exists()
