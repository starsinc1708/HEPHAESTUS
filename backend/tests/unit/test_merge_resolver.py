import asyncio
import pathlib
import subprocess

from app.core.merge_resolver import (
    MergeResolver,
    ResolveOutcome,
    build_resolver_prompt,
    has_conflict_markers,
)


def _make_ws(repo_path: str):
    from app.models.workspace import AgentRef, AgentsConfig, RepoProfile

    repo = pathlib.Path(repo_path)
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(repo)], capture_output=True, timeout=30, check=True)
    return RepoProfile(
        id="test",
        name="repo",
        repo_path=str(repo),
        agents=AgentsConfig(
            primary=AgentRef(provider="anthropic", model="claude-opus-4-8"),
            fallback=AgentRef(provider="openai", model="gpt-4.1"),
        ),
    )


def test_has_conflict_markers_positive():
    text = "a\n<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> auto/x\nb\n"
    assert has_conflict_markers(text) is True


def test_has_conflict_markers_negative():
    assert has_conflict_markers("clean code\nno markers\n") is False
    assert has_conflict_markers("x = '======='  # decoration\n") is False


def test_build_resolver_prompt_includes_intent_and_files():
    item = {"proposal": "add retry", "why": "flaky net", "acceptance": "tests green"}
    prompt = build_resolver_prompt(item=item, conflicts=["src/a.py", "src/b.py"])
    assert "add retry" in prompt
    assert "src/a.py" in prompt and "src/b.py" in prompt
    assert "conflict" in prompt.lower()


def test_resolver_runs_injected_agent(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    conflicted = wt / "a.py"
    conflicted.write_text("<<<<<<< HEAD\nx=1\n=======\nx=2\n>>>>>>> auto/x\n")

    async def fake_agent(prompt_file, cwd, output_path):
        conflicted.write_text("x = 1\nx = 2\n")
        pathlib.Path(output_path).write_text('{"type":"finish"}\n')
        from app.services.opencode_runner import AgentResult

        return AgentResult(
            exit_code=0,
            refused=False,
            output_path=pathlib.Path(output_path),
            agent_label="stub",
        )

    ws = _make_ws(str(tmp_path / "repo"))
    res = asyncio.run(
        MergeResolver(ws, run_agent=fake_agent).resolve(
            worktree_cwd=str(wt),
            conflicts=["a.py"],
            item={"proposal": "p"},
            job_dir=tmp_path,
            timeout_sec=60,
        )
    )
    assert isinstance(res, ResolveOutcome) and res.ok is True
    assert "<<<<<<<" not in conflicted.read_text()
