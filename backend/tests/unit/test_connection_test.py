import asyncio
import pathlib

import app.services.connection_test as ct
from app.models.connections import Connection


class _FakeRunner:
    def __init__(self, rc, text):
        self._rc, self._text = rc, text

    async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec, use_models=False):
        pathlib.Path(output_path).write_text(self._text, encoding="utf-8")
        from app.services.opencode_runner import AgentResult
        return AgentResult(exit_code=self._rc, refused=False, output_path=output_path, agent_label="x")


def _conn():
    return Connection(id="c1", label="DS", provider="deepseek", engine="claude",
                      model="deepseek-chat", env={"ANTHROPIC_AUTH_TOKEN": "k"})


def test_success_is_connected(monkeypatch):
    monkeypatch.setattr(ct, "_make_runner", lambda conn: _FakeRunner(0, "HEPHAESTUS_CONN_OK"))
    status, err = asyncio.run(ct.test_connection(_conn()))
    assert status == "connected" and err is None


def test_nonzero_is_failed(monkeypatch):
    monkeypatch.setattr(ct, "_make_runner", lambda conn: _FakeRunner(1, ""))
    status, err = asyncio.run(ct.test_connection(_conn()))
    assert status == "failed" and err


def test_runner_minus_one_is_failed_cli_missing(monkeypatch):
    monkeypatch.setattr(ct, "_make_runner", lambda conn: _FakeRunner(-1, ""))
    status, err = asyncio.run(ct.test_connection(_conn()))
    assert status == "failed"


def test_subscription_failure_shows_login(monkeypatch):
    monkeypatch.setattr(ct, "_make_runner", lambda conn: _FakeRunner(1, ""))  # not logged in
    conn = Connection(id="c", label="Claude", provider="anthropic", engine="claude",
                      model="claude-opus-4-5", auth_method="subscription",
                      env={"ANTHROPIC_MODEL": "claude-opus-4-5"})
    status, err = asyncio.run(ct.test_connection(conn))
    assert status == "failed" and err is not None and "claude" in err.lower()  # login hint mentions the cli
