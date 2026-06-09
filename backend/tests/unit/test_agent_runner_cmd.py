"""Unit: AgentRunner._build_cmd — opencode 1.16.0 flags (--format json, --agent/--model,
positional message). Verified against `opencode run --help`."""
from __future__ import annotations

import pathlib


def _runner():
    from app.core.process import ProcessManager
    from app.services.opencode_runner import AgentRunner

    return AgentRunner(ProcessManager())


def test_build_cmd_model_mode() -> None:
    from app.models.workspace import AgentRef

    ar = _runner()
    ref = AgentRef(provider="anthropic", model="claude-opus-4-8")
    cmd = ar._build_cmd(ref, "do the task", use_models=True)
    assert cmd[:4] == ["opencode", "run", "--format", "json"]
    assert "--model" in cmd and "anthropic/claude-opus-4-8" in cmd
    assert "--model-output-format" not in cmd and "--output" not in cmd and "--prompt" not in cmd
    assert cmd[-1] == "do the task"  # prompt is the positional message


def test_build_cmd_agent_mode() -> None:
    from app.models.workspace import AgentRef

    ar = _runner()
    ref = AgentRef(provider="anthropic", model="claude-opus-4-8", agent="sisyphus")
    cmd = ar._build_cmd(ref, "do the task", use_models=False)
    assert "--agent" in cmd and "sisyphus" in cmd
    assert "--model" not in cmd
    assert "--format" in cmd and "json" in cmd


def test_build_cmd_agent_none_falls_back_to_model() -> None:
    from app.models.workspace import AgentRef

    ar = _runner()
    ref = AgentRef(provider="openai", model="gpt-4.1", agent=None)
    cmd = ar._build_cmd(ref, "do the task", use_models=False)
    assert "--model" in cmd and "openai/gpt-4.1" in cmd
    assert "--agent" not in cmd


def test_build_cmd_oversize_prompt_attaches_file(tmp_path: pathlib.Path) -> None:
    from app.models.workspace import AgentRef

    ar = _runner()
    ref = AgentRef(provider="openai", model="gpt-4.1")
    big = tmp_path / "p.md"
    cmd = ar._build_cmd(ref, "x" * 40000, use_models=True, attach_file=big)
    assert "-f" in cmd and str(big) in cmd
    assert ("x" * 40000) not in cmd  # huge text not inlined as a positional arg
