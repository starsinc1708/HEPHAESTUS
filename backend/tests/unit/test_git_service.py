"""Unit: GitService is workspace-scoped (Stage-3 merge implemented)."""
from __future__ import annotations

import pathlib
import subprocess

import pytest


def _ws(tmp_path: pathlib.Path):
    from app.models.workspace import AgentRef, AgentsConfig, RepoProfile

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, timeout=30, check=True)
    return RepoProfile(
        id="abc",
        name="repo",
        repo_path=str(repo),
        agents=AgentsConfig(
            primary=AgentRef(provider="anthropic", model="claude-opus-4-8"),
            fallback=AgentRef(provider="openai", model="gpt-4.1"),
        ),
    )


def test_branches_empty(tmp_path: pathlib.Path) -> None:
    from app.core.git import GitService
    assert GitService(_ws(tmp_path)).branches() == []


def test_merge_preflight_shape(tmp_path: pathlib.Path) -> None:
    from app.core.git import GitService, MergePreflight
    pf = GitService(_ws(tmp_path)).merge_preflight("auto/x")
    assert isinstance(pf, MergePreflight)
    assert pf.base_branch == "main"
    assert pf.ok is False


@pytest.mark.asyncio
async def test_merge_to_base_no_task(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Stage 3 implemented merge_to_base: with no Task referencing the branch it
    # returns an explicit, surfaceable error (router maps to 409) — not a silent pass.
    # Isolate the loop-active check (like every other merge test): otherwise, when this
    # suite runs under a LIVE orchestrator (HEPHAESTUS verifying its own repo), `_loop_active`
    # recovers the real running loop from process.json and we'd get "loop active" instead.
    from app.core.git import GitService

    monkeypatch.setattr("app.core.git.GitService._loop_active", lambda self: False)
    res = await GitService(_ws(tmp_path)).merge_to_base("auto/x", push=False)
    assert res["ok"] is False
    assert "no task found" in res["error"]
