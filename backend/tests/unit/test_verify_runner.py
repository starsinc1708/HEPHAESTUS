"""Unit: VerifyRunner resolves commands and runs them cross-platform (no bash)."""
from __future__ import annotations

import os
import pathlib
import sys

import pytest


def _ws(tmp_path: pathlib.Path, **over):
    from app.models.workspace import AgentRef, AgentsConfig, RepoProfile

    base = dict(
        id="abc123",
        name="demo",
        repo_path=str(tmp_path),
        agents=AgentsConfig(
            primary=AgentRef(provider="anthropic", model="claude-opus-4-8"),
            fallback=AgentRef(provider="openai", model="gpt-4.1"),
        ),
    )
    base.update(over)
    return RepoProfile(**base)


def test_resolve_manual(tmp_path: pathlib.Path) -> None:
    from app.core.verify import VerifyRunner
    from app.models.workspace import VerifySource

    ws = _ws(tmp_path, verify_source=VerifySource.MANUAL, verify_commands_override=["echo hi"])
    assert VerifyRunner(ws).resolve_commands() == ["echo hi"]


def test_resolve_agent_from_memory(tmp_path: pathlib.Path) -> None:
    from app.core.verify import VerifyRunner
    from app.services.project_memory import ProjectMemory

    ws = _ws(tmp_path)
    ProjectMemory(ws).write_doc("verify", "## commands\n```sh\necho ok\n```\n", source="profiler")
    assert VerifyRunner(ws).resolve_commands() == ["echo ok"]


@pytest.mark.asyncio
async def test_run_green(tmp_path: pathlib.Path) -> None:
    from app.core.verify import VerifyRunner
    from app.models.workspace import VerifySource

    py = sys.executable.replace("\\", "/")
    ws = _ws(
        tmp_path,
        verify_source=VerifySource.MANUAL,
        verify_commands_override=[f'"{py}" -c "import sys; sys.exit(0)"'],
    )
    res = await VerifyRunner(ws).run(cwd=str(tmp_path), log_path=tmp_path / "verify.log", timeout_sec=30)
    assert res.ok is True
    assert res.failed_command is None
    assert len(res.ran) == 1


@pytest.mark.asyncio
async def test_run_fail(tmp_path: pathlib.Path) -> None:
    from app.core.verify import VerifyRunner
    from app.models.workspace import VerifySource

    py = sys.executable.replace("\\", "/")
    fail = f'"{py}" -c "import sys; sys.exit(1)"'
    ws = _ws(
        tmp_path,
        verify_source=VerifySource.MANUAL,
        verify_commands_override=[fail, f'"{py}" -c "import sys; sys.exit(0)"'],
    )
    res = await VerifyRunner(ws).run(cwd=str(tmp_path), log_path=tmp_path / "verify.log", timeout_sec=30)
    assert res.ok is False
    assert res.failed_command == fail


@pytest.mark.asyncio
async def test_run_empty_is_noop(tmp_path: pathlib.Path) -> None:
    from app.core.verify import VerifyRunner
    from app.models.workspace import VerifySource

    ws = _ws(tmp_path, verify_source=VerifySource.MANUAL, verify_commands_override=[])
    res = await VerifyRunner(ws).run(cwd=str(tmp_path), log_path=tmp_path / "verify.log", timeout_sec=30)
    assert res.ok is True
    assert res.ran == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows .cmd shim resolution (R5)")
@pytest.mark.asyncio
async def test_run_resolves_cmd_shim_on_windows(tmp_path: pathlib.Path, monkeypatch) -> None:
    """A bare 'mytool' must resolve to mytool.cmd via shutil.which (R5)."""
    from app.core.verify import VerifyRunner
    from app.models.workspace import VerifySource

    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    (shim_dir / "mytool.cmd").write_text("@echo verify-ok\r\n@exit /b 0\r\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(shim_dir) + os.pathsep + os.environ["PATH"])

    ws = _ws(tmp_path, verify_source=VerifySource.MANUAL, verify_commands_override=["mytool"])
    res = await VerifyRunner(ws).run(cwd=str(tmp_path), log_path=tmp_path / "verify.log", timeout_sec=30)
    assert res.ok is True
    assert "verify-ok" in (tmp_path / "verify.log").read_text(errors="replace")


def test_argv_for_shell_override(tmp_path: pathlib.Path) -> None:
    """shell:-prefixed commands route through cmd /c (Windows) / sh -c (POSIX) (R5)."""
    from app.core.verify import VerifyRunner
    from app.models.workspace import VerifySource

    ws = _ws(tmp_path, verify_source=VerifySource.MANUAL)
    argv = VerifyRunner(ws)._argv_for("shell:echo a && echo b")
    if sys.platform == "win32":
        assert argv[:2] == ["cmd", "/c"]
    else:
        assert argv[:2] == ["sh", "-c"]
