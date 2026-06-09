"""Integration: VerifyRunner reads verify.md from memory."""
from __future__ import annotations

import pathlib
import sys

import pytest


@pytest.mark.asyncio
async def test_verify_runner_from_memory(tmp_path: pathlib.Path) -> None:
    from app.core.verify import VerifyRunner
    from app.models.workspace import AgentRef, AgentsConfig, RepoProfile
    from app.services.project_memory import ProjectMemory

    ws = RepoProfile(
        id="abc123",
        name="demo",
        repo_path=str(tmp_path),
        agents=AgentsConfig(
            primary=AgentRef(provider="anthropic", model="claude-opus-4-8"),
            fallback=AgentRef(provider="openai", model="gpt-4.1"),
        ),
    )
    py = sys.executable.replace("\\", "/")
    ProjectMemory(ws).write_doc(
        "verify", f"## commands\n```sh\n\"{py}\" -c \"print('ok')\"\n```\n", source="profiler"
    )
    res = await VerifyRunner(ws).run(cwd=str(tmp_path), log_path=tmp_path / "verify.log", timeout_sec=30)
    assert res.ok is True
    assert "ok" in (tmp_path / "verify.log").read_text()
