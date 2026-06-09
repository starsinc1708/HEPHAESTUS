"""Contract: RepoProfile round-trips camelCase aliases."""
from __future__ import annotations


def test_repoprofile_round_trip() -> None:
    from app.models.workspace import AgentRef, RepoProfile, VerifySource

    payload = {
        "id": "9f3a1c20e4b57d61",
        "name": "demo",
        "repoPath": "/tmp/demo",
        "baseBranch": "main",
        "branchPrefix": "auto",
        "agents": {
            "useModels": True,
            "primary": {"provider": "anthropic", "model": "claude-opus-4-8"},
            "fallback": {"provider": "openai", "model": "gpt-4.1"},
        },
        "verifySource": "agent",
        "verifyCommandsOverride": [],
    }
    ws = RepoProfile.model_validate(payload)
    assert ws.repo_path == "/tmp/demo"
    assert ws.base_branch == "main"
    assert ws.verify_source is VerifySource.AGENT
    assert ws.agents.use_models is True
    assert isinstance(ws.agents.primary, AgentRef)

    dumped = ws.model_dump(by_alias=True)
    assert dumped["repoPath"] == "/tmp/demo"
    assert dumped["verifySource"] == "agent"
    assert dumped["memoryDir"] == ".hephaestus/memory"


def test_agentsconfig_defaults() -> None:
    from app.models.workspace import AgentRef, AgentsConfig

    cfg = AgentsConfig(
        primary=AgentRef(provider="anthropic", model="claude-opus-4-8"),
        fallback=AgentRef(provider="openai", model="gpt-4.1"),
    )
    assert cfg.use_models is False
    assert cfg.validators == []
    assert cfg.final is None