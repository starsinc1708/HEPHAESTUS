"""Unit tests for model parameter tuning (MODEL-003)."""
from __future__ import annotations

from app.models.workspace import AgentRef


def _runner():
    from app.core.process import ProcessManager
    from app.services.opencode_runner import AgentRunner
    return AgentRunner(ProcessManager())


class TestModelParamsAgentRef:
    def test_has_optional_model_params(self):
        ref = AgentRef(provider="openai", model="gpt-4o", model_params={"temperature": 0.7})
        assert ref.model_params == {"temperature": 0.7}

    def test_default_empty_params(self):
        ref = AgentRef(provider="openai", model="gpt-4o")
        assert ref.model_params == {}

    def test_alias_modelParams(self):
        ref = AgentRef(provider="openai", model="gpt-4o", modelParams={"temperature": 0.7})
        assert ref.model_params == {"temperature": 0.7}


class TestModelParamsBuildCmd:
    def test_opencode_temperature(self):
        ar = _runner()
        ref = AgentRef(provider="openai", model="gpt-4o", model_params={"temperature": 0.7})
        cmd = ar._build_cmd(ref, "test", use_models=True)
        assert "--temperature" in cmd
        assert "0.7" in cmd

    def test_opencode_max_tokens(self):
        ar = _runner()
        ref = AgentRef(provider="openai", model="gpt-4o", model_params={"max_tokens": 4096})
        cmd = ar._build_cmd(ref, "test", use_models=True)
        assert "--max-output-tokens" in cmd
        assert "4096" in cmd

    def test_unknown_param_ignored(self):
        ar = _runner()
        ref = AgentRef(provider="openai", model="gpt-4o", model_params={"fantasy_flag": True})
        cmd = ar._build_cmd(ref, "test", use_models=True)
        assert "fantasy_flag" not in " ".join(cmd)

    def test_empty_params_no_extra_flags(self):
        """Regression: empty params = command identical to before."""
        ar = _runner()
        ref_plain = AgentRef(provider="openai", model="gpt-4o")
        ref_empty = AgentRef(provider="openai", model="gpt-4o", model_params={})
        cmd_plain = ar._build_cmd(ref_plain, "test", use_models=True)
        cmd_empty = ar._build_cmd(ref_empty, "test", use_models=True)
        assert cmd_plain == cmd_empty
