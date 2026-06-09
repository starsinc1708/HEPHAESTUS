"""Unit tests for provider-level fallback (MODEL-002)."""
from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest

from app.models.workspace import AgentRef, AgentsConfig


def _result(exit_code: int, label: str = "test"):
    return SimpleNamespace(exit_code=exit_code, refused=False,
                           output_path=pathlib.Path("/tmp/out.jsonl"), agent_label=label)


class TestProviderFallback:
    @pytest.mark.asyncio
    async def test_no_chain_delegates_to_run_with_fallback(self, tmp_path: pathlib.Path) -> None:
        from app.core.process import ProcessManager
        from app.services.opencode_runner import AgentRunner
        runner = AgentRunner(ProcessManager())
        agents = AgentsConfig(
            primary=AgentRef(provider="anthropic", model="m1"),
            fallback=AgentRef(provider="openai", model="m2"))
        calls: list[str] = []
        async def mock_run(ref, **kw):
            calls.append(ref.provider)
            return _result(0, ref.provider)
        runner.run = mock_run  # type: ignore
        res = await runner.run_with_provider_fallback(agents,
            prompt_file=tmp_path / "p.md", cwd=".", iter_dir=tmp_path, timeout_sec=10)
        assert res.exit_code == 0
        assert calls == ["anthropic"]

    @pytest.mark.asyncio
    async def test_cycle_impossible(self, tmp_path: pathlib.Path) -> None:
        from app.core.process import ProcessManager
        from app.services.opencode_runner import AgentRunner
        runner = AgentRunner(ProcessManager())
        agents = AgentsConfig(
            primary=AgentRef(provider="a", model="m1"),
            fallback=AgentRef(provider="b", model="m2"))
        chain = [
            ("a", AgentRef(provider="a", model="m1"), AgentRef(provider="a", model="m1b")),
            ("b", AgentRef(provider="b", model="m2"), AgentRef(provider="b", model="m2b")),
            ("a", AgentRef(provider="a", model="m1"), AgentRef(provider="a", model="m1b")),  # duplicate — skipped
        ]
        calls: list[str] = []
        async def mock_run(ref, **kw):
            calls.append(ref.provider)
            return _result(1, ref.provider)
        runner.run = mock_run  # type: ignore
        await runner.run_with_provider_fallback(agents,
            prompt_file=tmp_path / "p.md", cwd=".", iter_dir=tmp_path, timeout_sec=10,
            provider_chain=chain)
        # Should only try a and b, not a again
        providers_tried = set(calls)
        assert "a" in providers_tried
        assert "b" in providers_tried
        assert len(calls) <= 4  # at most primary+fallback for each of 2 providers
