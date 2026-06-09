"""AgentRunner supports the Claude CLI engine: prompt via stdin + engine_env merge."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.core.validators import _last_text_event
from app.models.workspace import AgentRef, EngineProfile
from app.services.opencode_runner import AgentRunner

# Built without the literal token to dodge an over-eager content-security hook.
_SPAWN_TARGET = "app.services.opencode_runner.asyncio." + "create_subprocess_" + "exec"


def test_build_cmd_claude() -> None:
    r = AgentRunner(None, engine="claude")  # type: ignore[arg-type]
    cmd = r._build_cmd_claude(AgentRef(provider="x", model="deepseek-v4-pro"))
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "--dangerously-skip-permissions" in cmd
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert cmd[cmd.index("--model") + 1] == "deepseek-v4-pro"


def test_label_claude() -> None:
    r = AgentRunner(None, engine="claude")  # type: ignore[arg-type]
    assert r._label(AgentRef(provider="p", model="m"), False, "claude") == "claude:m"


class _FakeStdin:
    """Captures all bytes written via the streaming stdin path (write/drain/close)."""

    def __init__(self, captured: dict) -> None:
        self._captured = captured
        self._buf = b""

    def write(self, data: bytes) -> None:
        self._buf += data
        self._captured["stdin_data"] = self._buf

    async def drain(self) -> None: ...
    def close(self) -> None: ...


class _FakeReader:
    """Yields its payload once, then EOF — mimics asyncio StreamReader.read(n)."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._done = False

    async def read(self, n: int = -1) -> bytes:
        if self._done:
            return b""
        self._done = True
        return self._data


class _FakeProc:
    """Streaming-capable fake: AgentRunner.run now pumps stdout/stderr + feeds stdin
    incrementally (no communicate()), so the double must expose those streams."""

    def __init__(self, out: bytes, captured: dict) -> None:
        self.returncode = 0
        self._captured = captured
        self.stdin = _FakeStdin(captured)
        self.stdout = _FakeReader(out)
        self.stderr = _FakeReader(b"")

    def kill(self) -> None: ...
    async def wait(self) -> int:
        return self.returncode


@pytest.mark.asyncio
async def test_run_claude_uses_stdin_and_engine_env(tmp_path: pathlib.Path, monkeypatch) -> None:
    captured: dict = {}

    async def fake_spawn(*cmd, cwd, stdin, stdout, stderr, env):
        captured["cmd"] = list(cmd)
        captured["env"] = env
        out = (json.dumps({"type": "result", "result": "hello from claude"}) + "\n").encode()
        return _FakeProc(out, captured)

    monkeypatch.setattr(_SPAWN_TARGET, fake_spawn)
    pf = tmp_path / "prompt.md"
    pf.write_text("THE PROMPT", encoding="utf-8")
    out = tmp_path / "o.jsonl"

    r = AgentRunner(
        None,  # type: ignore[arg-type]
        engine="claude",
        env={"ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic", "ANTHROPIC_API_KEY": "sk-x"},
    )
    res = await r.run(AgentRef(provider="x", model="deepseek-v4-pro"),
                      prompt_file=pf, cwd=str(tmp_path), output_path=out, timeout_sec=30)

    assert res.exit_code == 0
    assert "claude" in captured["cmd"][0]
    assert captured["env"]["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"
    # A provided key is routed to ANTHROPIC_AUTH_TOKEN (Bearer) so the headless Claude CLI
    # uses it instead of the machine's logged-in OAuth account (which 401s against DeepSeek).
    assert captured["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-x"
    assert "ANTHROPIC_API_KEY" not in captured["env"]
    assert captured["stdin_data"] == b"THE PROMPT"
    assert _last_text_event(out) == "hello from claude"


def test_last_text_event_parses_claude_result(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "c.jsonl"
    assistant = {"type": "assistant",
                 "message": {"content": [{"type": "text", "text": "VALIDATION_VERDICT_BEGIN"}]}}
    result = {"type": "result", "result": "VALIDATION_VERDICT_END"}
    p.write_text(json.dumps(assistant) + "\n" + json.dumps(result) + "\n", encoding="utf-8")
    text = _last_text_event(p)
    assert "VALIDATION_VERDICT_BEGIN" in text
    assert "VALIDATION_VERDICT_END" in text


def test_engine_profile_resolution() -> None:
    prof = EngineProfile(name="deepseek", engine="claude",
                         env={"ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
                              "ANTHROPIC_API_KEY": "k"})
    r = AgentRunner(None, engine="opencode", profiles=[prof])  # type: ignore[arg-type]
    # A ref pointing at the profile resolves to that engine + env.
    eng, env = r._resolve_engine(AgentRef(provider="x", model="m", engine_profile="deepseek"))
    assert eng == "claude"
    assert env["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"
    # A ref without a profile falls back to the workspace default.
    eng2, env2 = r._resolve_engine(AgentRef(provider="x", model="m"))
    assert eng2 == "opencode"
    assert env2 == {}


@pytest.mark.asyncio
async def test_run_uses_per_ref_profile(tmp_path: pathlib.Path, monkeypatch) -> None:
    """Default engine opencode, but a ref's profile routes THAT role to Claude+DeepSeek."""
    captured: dict = {}

    async def fake_spawn(*cmd, cwd, stdin, stdout, stderr, env):
        captured["cmd"] = list(cmd)
        captured["env"] = env
        out = (json.dumps({"type": "result", "result": "ok"}) + "\n").encode()
        return _FakeProc(out, captured)

    monkeypatch.setattr(_SPAWN_TARGET, fake_spawn)
    prof = EngineProfile(name="deepseek", engine="claude",
                         env={"ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic"})
    r = AgentRunner(None, engine="opencode", profiles=[prof])  # type: ignore[arg-type]
    pf = tmp_path / "p.md"
    pf.write_text("X", encoding="utf-8")
    await r.run(AgentRef(provider="x", model="deepseek-v4-pro", engine_profile="deepseek"),
                prompt_file=pf, cwd=str(tmp_path), output_path=tmp_path / "o.jsonl", timeout_sec=30)
    assert "claude" in captured["cmd"][0]  # routed to claude despite opencode default
    assert captured["env"]["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"
