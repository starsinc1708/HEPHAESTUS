"""Unit: list_worktrees() — branch→task linkage, changedFiles, pairwise overlap, never-crash."""

import json
import subprocess

import pytest

from app.models.workspace import AgentRef, AgentsConfig, RepoProfile


def _git(repo, *a):
    subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, text=True)


def _ws(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "base.txt").write_text("base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    # simulate a remote-tracking base: the diff uses origin/main — create it as a local ref
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo, RepoProfile(
        id="w", name="repo", repo_path=str(repo),
        agents=AgentsConfig(
            primary=AgentRef(provider="anthropic", model="claude-opus-4-8"),
            fallback=AgentRef(provider="openai", model="gpt-4.1"),
        ),
    )


def _branch(repo, name, edits):
    """Create an auto/* branch off main with `edits` (path->content), commit, return to main."""
    _git(repo, "checkout", "-b", name, "main")
    for path, content in edits.items():
        (repo / path).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"work on {name}")
    _git(repo, "checkout", "main")


@pytest.fixture
def _reset_state_override():
    import app.core.state as state_mod
    yield
    state_mod._STATE_DIR_OVERRIDE = None


def _seed_state(tmp_path, monkeypatch, items):
    import app.core.state as state_mod
    sd = tmp_path / "state"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "work-state.json").write_text(json.dumps({"items": items}))
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)


def test_branch_task_linkage(tmp_path, monkeypatch, _reset_state_override):
    from app.core.worktrees import list_worktrees

    repo, ws = _ws(tmp_path)
    _branch(repo, "auto/linked", {"a.txt": "x\n"})
    _branch(repo, "auto/orphan", {"b.txt": "y\n"})
    _seed_state(tmp_path, monkeypatch, [
        {"id": "t1", "title": "T1", "status": "done", "branch": "auto/linked"},
    ])

    wts = {w.branch: w for w in list_worktrees(ws)}
    assert "auto/linked" in wts
    assert "auto/orphan" in wts
    assert wts["auto/linked"].task is not None
    assert wts["auto/linked"].task.id == "t1"
    assert wts["auto/linked"].task.title == "T1"
    assert wts["auto/linked"].task.status == "done"
    assert wts["auto/orphan"].task is None


def test_changed_files(tmp_path, monkeypatch, _reset_state_override):
    from app.core.worktrees import list_worktrees

    repo, ws = _ws(tmp_path)
    _branch(repo, "auto/x", {"shared.txt": "from-x\n", "only-x.txt": "x\n"})
    _branch(repo, "auto/y", {"shared.txt": "from-y\n", "only-y.txt": "y\n"})
    _seed_state(tmp_path, monkeypatch, [])

    wts = {w.branch: w for w in list_worktrees(ws)}
    assert set(wts["auto/x"].changed_files) == {"shared.txt", "only-x.txt"}
    assert wts["auto/x"].changed_count == 2
    assert set(wts["auto/y"].changed_files) == {"shared.txt", "only-y.txt"}


def test_overlap(tmp_path, monkeypatch, _reset_state_override):
    from app.core.worktrees import list_worktrees

    repo, ws = _ws(tmp_path)
    _branch(repo, "auto/x", {"shared.txt": "from-x\n", "only-x.txt": "x\n"})
    _branch(repo, "auto/y", {"shared.txt": "from-y\n", "only-y.txt": "y\n"})
    _branch(repo, "auto/z", {"only-z.txt": "z\n"})
    _seed_state(tmp_path, monkeypatch, [
        {"id": "ty", "title": "TY", "status": "done", "branch": "auto/y"},
    ])

    wts = {w.branch: w for w in list_worktrees(ws)}

    x_conflicts = {c.branch: c for c in wts["auto/x"].conflicts_with}
    assert "auto/y" in x_conflicts
    assert x_conflicts["auto/y"].files == ["shared.txt"]
    assert x_conflicts["auto/y"].task is not None
    assert x_conflicts["auto/y"].task.id == "ty"
    assert "auto/z" not in x_conflicts

    y_conflicts = {c.branch: c for c in wts["auto/y"].conflicts_with}
    assert "auto/x" in y_conflicts
    assert y_conflicts["auto/x"].files == ["shared.txt"]
    # auto/x has no task → conflict ref task is None
    assert y_conflicts["auto/x"].task is None

    assert wts["auto/z"].conflicts_with == []


def test_never_crashes_on_bad_base_ref(tmp_path, monkeypatch, _reset_state_override):
    from app.core.worktrees import list_worktrees

    repo, ws = _ws(tmp_path)
    _branch(repo, "auto/x", {"shared.txt": "from-x\n"})
    _seed_state(tmp_path, monkeypatch, [])
    # Break the base ref the diff relies on (origin/nope does not exist).
    ws.base_branch = "nope"

    wts = list_worktrees(ws)
    # Must not raise; affected branch lists [] changed files.
    assert [w.branch for w in wts] == ["auto/x"]
    assert wts[0].changed_files == []
    assert wts[0].changed_count == 0
    assert wts[0].conflicts_with == []
