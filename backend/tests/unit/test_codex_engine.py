from app.models.workspace import AgentRef
from app.services.opencode_runner import AgentRunner


def test_codex_cmd_and_stdin():
    r = AgentRunner(None, engine="codex")  # type: ignore[arg-type]
    cmd = r._build_cmd_codex(AgentRef(provider="openai", model="gpt-5-codex"))
    assert cmd == ["codex", "exec", "--model", "gpt-5-codex", "--skip-git-repo-check"]
    assert r._label(AgentRef(provider="openai", model="gpt-5-codex"), True, "codex") == "codex:gpt-5-codex"
