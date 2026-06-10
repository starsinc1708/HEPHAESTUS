"""Integration tests for MergeJobRunner (Tasks 6 + 7).

Uses real git worktrees in tmp dirs — no mocking of git commands.
"""

from __future__ import annotations

import asyncio
import pathlib
import subprocess

import app.core.state as state
from app.core.merge_job import MergeJobRunner, MergeJobStore
from app.models.merge import MergeDecision, MergeJobStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(cwd, *a):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True)


def _make_ws(repo_path: str):
    """Build a minimal RepoProfile-shaped object for merge tests."""
    from app.models.workspace import AgentRef, AgentsConfig, RepoProfile

    return RepoProfile(
        id="test-ws",
        name="test",
        repo_path=repo_path,
        base_branch="main",
        remote="origin",
        agents=AgentsConfig(
            primary=AgentRef(provider="anthropic", model="claude-opus-4-8"),
            fallback=AgentRef(provider="openai", model="gpt-4.1"),
        ),
        engine="opencode",
        engine_env={},
        engine_profiles=[],
        verify_timeout_sec=30,
    )


def _conflict_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a repo with a conflicting branch (both sides touch f.txt differently)."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "a@b.c")
    _git(r, "config", "user.name", "t")
    (r / "f.txt").write_text("base\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "init")
    _git(r, "checkout", "-b", "auto/x")
    (r / "f.txt").write_text("branch-change\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "x")
    _git(r, "checkout", "main")
    (r / "f.txt").write_text("base-change\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "base")
    return r


def _clean_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """A repo whose branch merges into main with NO conflict (→ AUTO_MERGED path).

    base touches only f.txt; auto/x only ADDS feature.txt; main stays at base."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "a@b.c")
    _git(r, "config", "user.name", "t")
    (r / ".gitignore").write_text("node_modules/\n")
    (r / "f.txt").write_text("base\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "init")
    _git(r, "checkout", "-b", "auto/x")
    (r / "feature.txt").write_text("feat\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "feat")
    _git(r, "checkout", "main")
    return r


# ---------------------------------------------------------------------------
# Fake verify + fake resolve agent
# ---------------------------------------------------------------------------


class _FakeVerify:
    def __init__(self, ok: bool) -> None:
        self._ok = ok

    async def run(self, *, cwd: str, log_path: pathlib.Path, timeout_sec: int) -> object:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("verify\n")

        class _R:
            ok = self._ok

        return _R()


async def _resolve_ok(
    prompt_file: pathlib.Path, cwd: str, output_path: pathlib.Path
) -> object:
    """Resolve by writing a clean merged file (no conflict markers)."""
    (pathlib.Path(cwd) / "f.txt").write_text("base-change\nbranch-change\n")
    output_path.write_text('{"type":"finish"}\n')
    from app.services.opencode_runner import AgentResult

    return AgentResult(
        exit_code=0,
        refused=False,
        output_path=output_path,
        agent_label="stub",
    )


# ---------------------------------------------------------------------------
# Fixture: workspace with state dir
# ---------------------------------------------------------------------------


def _ws_for(
    repo: pathlib.Path,
    monkeypatch: object,
    tmp_path: pathlib.Path,
) -> object:
    sd = tmp_path / "hephaestusstate"
    sd.mkdir()
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)
    from app.core.state import _write_state

    _write_state(
        {
            "items": [
                {
                    "id": "x",
                    "branch": "auto/x",
                    "verify_green": True,
                    "validation": {"gate": "pass"},
                    "status": "done",
                    "proposal": "p",
                }
            ]
        }
    )
    return _make_ws(str(repo))


# ---------------------------------------------------------------------------
# Task 6 tests
# ---------------------------------------------------------------------------


def test_ai_merge_resolved(tmp_path, monkeypatch):
    """AI resolver produces a clean merged file → job ends RESOLVED with AI_MERGED."""
    repo = _conflict_repo(tmp_path)
    ws = _ws_for(repo, monkeypatch, tmp_path)
    runner = MergeJobRunner(ws, run_agent=_resolve_ok, verify=_FakeVerify(ok=True))
    job = asyncio.run(
        runner.start(branch="auto/x", push=False, ai_resolve=True, auto_accept=False)
    )
    assert job.status is MergeJobStatus.RESOLVED
    assert job.decision is MergeDecision.AI_MERGED
    assert job.verify_ok is True
    assert "f.txt" in job.resolved_files
    # base repo should be UNTOUCHED (merge happened in isolated worktree)
    assert (repo / "f.txt").read_text() == "base-change\n"


def test_ai_merge_failed_when_markers_remain(tmp_path, monkeypatch):
    """If resolver does NOT remove conflict markers → job fails."""
    repo = _conflict_repo(tmp_path)
    ws = _ws_for(repo, monkeypatch, tmp_path)

    async def _bad(
        pf: pathlib.Path, cwd: str, op: pathlib.Path
    ) -> object:
        # Does NOT fix f.txt — conflict markers remain
        op.write_text("{}\n")
        from app.services.opencode_runner import AgentResult

        return AgentResult(
            exit_code=0,
            refused=False,
            output_path=op,
            agent_label="stub",
        )

    runner = MergeJobRunner(ws, run_agent=_bad, verify=_FakeVerify(ok=True))
    job = asyncio.run(
        runner.start(branch="auto/x", push=False, ai_resolve=True, auto_accept=False)
    )
    assert job.status is MergeJobStatus.FAILED
    # base repo must remain untouched
    assert (repo / "f.txt").read_text() == "base-change\n"


def test_verify_red_fails(tmp_path, monkeypatch):
    """Verify returning ok=False → job fails even if resolution was clean."""
    repo = _conflict_repo(tmp_path)
    ws = _ws_for(repo, monkeypatch, tmp_path)
    runner = MergeJobRunner(ws, run_agent=_resolve_ok, verify=_FakeVerify(ok=False))
    job = asyncio.run(
        runner.start(branch="auto/x", push=False, ai_resolve=True, auto_accept=False)
    )
    assert job.status is MergeJobStatus.FAILED


# ---------------------------------------------------------------------------
# Task 7 tests
# ---------------------------------------------------------------------------


def test_accept_ff_into_base_and_cleanup(tmp_path, monkeypatch):
    """accept() fast-forwards main, cleans up worktree + branch, marks item merged."""
    repo = _conflict_repo(tmp_path)
    ws = _ws_for(repo, monkeypatch, tmp_path)
    runner = MergeJobRunner(ws, run_agent=_resolve_ok, verify=_FakeVerify(ok=True))
    job = asyncio.run(
        runner.start(branch="auto/x", push=False, ai_resolve=True, auto_accept=False)
    )
    assert job.status is MergeJobStatus.RESOLVED

    res = asyncio.run(runner.accept(job.id, push=False))
    assert res["ok"] is True
    # main now has the resolved content
    assert (repo / "f.txt").read_text() == "base-change\nbranch-change\n"
    # state item must be marked merged with the right resolution key
    from app.core.state import _read_state

    it = next(i for i in _read_state()["items"] if i["id"] == "x")
    assert it["status"] == "merged" and it.get("mergeResolution") == "ai"
    assert MergeJobStore().get(job.id).status.value == "accepted"


def test_auto_merge_does_not_commit_untracked_worktree_files(tmp_path, monkeypatch):
    """Regression: a clean AUTO_MERGED merge must commit ONLY the merge — never untracked
    files present in the worktree. Real-world trigger: a `frontend/node_modules` SYMLINK that
    `.gitignore`'s dir-pattern `node_modules/` doesn't match; the old `git add -A` staged it,
    polluting the merge commit and breaking the later fast-forward checkout."""
    repo = _clean_repo(tmp_path)
    ws = _ws_for(repo, monkeypatch, tmp_path)

    # Drop an UNTRACKED file into the merge worktree right after it's created — mirrors the
    # stray node_modules symlink that appeared in the real repo's worktree.
    import app.core.git as gitmod

    real_add = gitmod._worktree_add

    def _add_then_pollute(r: str, wt: str, wt_branch: str, base: str) -> bool:
        ok = real_add(r, wt, wt_branch, base)
        if ok:
            (pathlib.Path(wt) / "stray.txt").write_text("untracked junk\n")
        return ok

    monkeypatch.setattr(gitmod, "_worktree_add", _add_then_pollute)

    runner = MergeJobRunner(ws, run_agent=_resolve_ok, verify=_FakeVerify(ok=True))
    job = asyncio.run(
        runner.start(branch="auto/x", push=False, ai_resolve=False, auto_accept=False)
    )
    assert job.status is MergeJobStatus.RESOLVED
    assert job.decision is MergeDecision.AUTO_MERGED

    tracked = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", job.worktree_branch or ""],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    assert "feature.txt" in tracked          # the real merged change IS committed
    assert "stray.txt" not in tracked        # the untracked worktree file is NOT


def test_reject_discards_worktree_base_untouched(tmp_path, monkeypatch):
    """reject() removes the worktree without touching main."""
    repo = _conflict_repo(tmp_path)
    ws = _ws_for(repo, monkeypatch, tmp_path)
    runner = MergeJobRunner(ws, run_agent=_resolve_ok, verify=_FakeVerify(ok=True))
    job = asyncio.run(
        runner.start(branch="auto/x", push=False, ai_resolve=True, auto_accept=False)
    )
    assert job.status is MergeJobStatus.RESOLVED

    res = asyncio.run(runner.reject(job.id))
    assert res["ok"] is True
    assert (repo / "f.txt").read_text() == "base-change\n"
    assert not pathlib.Path(job.worktree).exists()
    assert MergeJobStore().get(job.id).status.value == "rejected"


def test_reaper_fails_orphaned_job(tmp_path, monkeypatch):
    """reap() transitions RESOLVING jobs with a gone worktree → FAILED."""
    repo = _conflict_repo(tmp_path)
    ws = _ws_for(repo, monkeypatch, tmp_path)
    from app.models.merge import MergeJob

    store = MergeJobStore()
    store.put(
        MergeJob(
            id="merge-0009",
            branch="auto/x",
            base_branch="main",
            status=MergeJobStatus.RESOLVING,
            worktree=str(tmp_path / "gone"),
        )
    )
    MergeJobRunner(ws).reap()
    assert store.get("merge-0009").status is MergeJobStatus.FAILED


def test_reject_running_job_is_guarded(tmp_path, monkeypatch):
    """reject() must be a no-op when the job is still RESOLVING (not awaiting decision)."""
    repo = _conflict_repo(tmp_path)
    ws = _ws_for(repo, monkeypatch, tmp_path)
    from app.models.merge import MergeJob, MergeJobStatus

    store = MergeJobStore()
    wt_marker = tmp_path / "live-wt"
    wt_marker.mkdir()
    store.put(
        MergeJob(
            id="merge-0050",
            branch="auto/x",
            base_branch="main",
            status=MergeJobStatus.RESOLVING,
            worktree=str(wt_marker),
        )
    )
    res = asyncio.run(MergeJobRunner(ws).reject("merge-0050"))
    assert res["ok"] is False
    assert wt_marker.exists()  # worktree NOT removed
    assert store.get("merge-0050").status is MergeJobStatus.RESOLVING  # unchanged


def test_resolver_touching_out_of_scope_file_fails(tmp_path, monkeypatch):
    """§4.6 guard: if resolver writes files outside the merge scope, the job fails."""
    repo = _conflict_repo(tmp_path)
    ws = _ws_for(repo, monkeypatch, tmp_path)

    async def _rogue(prompt_file: pathlib.Path, cwd: str, output_path: pathlib.Path) -> object:
        import pathlib as _p
        (_p.Path(cwd) / "f.txt").write_text("base-change\nbranch-change\n")  # resolve the real conflict
        (_p.Path(cwd) / "ROGUE.txt").write_text("the agent invented this\n")  # out of scope!
        _p.Path(output_path).write_text('{"type":"finish"}\n')
        from app.services.opencode_runner import AgentResult
        return AgentResult(exit_code=0, refused=False, output_path=_p.Path(output_path), agent_label="stub")

    runner = MergeJobRunner(ws, run_agent=_rogue, verify=_FakeVerify(ok=True))
    job = asyncio.run(runner.start(branch="auto/x", push=False, ai_resolve=True, auto_accept=False))
    assert job.status is MergeJobStatus.FAILED
    assert (repo / "f.txt").read_text() == "base-change\n"  # base untouched
