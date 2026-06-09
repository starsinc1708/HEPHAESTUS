"""Integration test for insights service (Epic 4 C1) — stub runner, no real agent CLI."""

from __future__ import annotations

import asyncio
import json
import pathlib
import types

import app.core.state as state
from app.services import insights as ins


def _make_ws(repo_path: str) -> types.SimpleNamespace:
    """Minimal RepoProfile-shaped namespace sufficient for ask()."""
    agents = types.SimpleNamespace(
        primary=types.SimpleNamespace(provider="p", model="m", agent="primary"),
        planner=None,
    )
    return types.SimpleNamespace(
        id="ws-test",
        name="test",
        repo_path=repo_path,
        base_branch="main",
        remote="origin",
        branch_prefix="auto",
        agents=agents,
        memory_dir=".hephaestus/memory",
        verify_timeout_sec=120,
    )


def test_ask_appends_turns(tmp_path: pathlib.Path, monkeypatch: object) -> None:
    sd = tmp_path / "st"
    sd.mkdir()
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)  # type: ignore[attr-defined]
    repo = tmp_path / "repo"
    (repo / ".hephaestus" / "memory").mkdir(parents=True)
    monkeypatch.setattr("app.services.insights._run", lambda cmd, **kw: "")  # type: ignore[attr-defined]
    ws = _make_ws(str(repo))

    class Stub:
        async def run(
            self,
            ref: object,
            *,
            prompt_file: pathlib.Path,
            cwd: str,
            output_path: pathlib.Path,
            timeout_sec: int,
            use_models: bool = False,
        ) -> object:
            pathlib.Path(output_path).write_text(
                json.dumps({"type": "text", "text": "It uses FastAPI in app/main.py"}) + "\n"
                + json.dumps({"type": "finish"}) + "\n"
            )

            class R:
                exit_code = 0
                refused = False

            return R()

    res = asyncio.run(ins.ask(ws, "What web framework?", session_id=None, runner=Stub()))
    assert "FastAPI" in res["answer"]
    sess = ins.InsightsStore().get(res["sessionId"])
    assert sess is not None
    assert len(sess.turns) == 2
    assert sess.turns[0].role == "user"
    assert sess.turns[1].role == "assistant"
    assert sess.turns[1].iter_dir is not None


def test_ask_continues_session(tmp_path: pathlib.Path, monkeypatch: object) -> None:
    """Second ask with the same session_id appends more turns."""
    sd = tmp_path / "st2"
    sd.mkdir()
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)  # type: ignore[attr-defined]
    repo = tmp_path / "repo2"
    (repo / ".hephaestus" / "memory").mkdir(parents=True)
    monkeypatch.setattr("app.services.insights._run", lambda cmd, **kw: "")  # type: ignore[attr-defined]
    ws = _make_ws(str(repo))

    call_count = 0

    class Stub:
        async def run(
            self,
            ref: object,
            *,
            prompt_file: pathlib.Path,
            cwd: str,
            output_path: pathlib.Path,
            timeout_sec: int,
            use_models: bool = False,
        ) -> object:
            nonlocal call_count
            call_count += 1
            pathlib.Path(output_path).write_text(
                json.dumps({"type": "text", "text": f"Answer {call_count}"}) + "\n"
            )

            class R:
                exit_code = 0
                refused = False

            return R()

    res1 = asyncio.run(ins.ask(ws, "First question?", session_id=None, runner=Stub()))
    sid = res1["sessionId"]
    res2 = asyncio.run(ins.ask(ws, "Follow-up question?", session_id=sid, runner=Stub()))

    assert res2["sessionId"] == sid
    sess = ins.InsightsStore().get(sid)
    assert sess is not None
    assert len(sess.turns) == 4  # user, assistant, user, assistant


def test_ask_returns_no_response_on_empty_output(
    tmp_path: pathlib.Path, monkeypatch: object
) -> None:
    """Empty agent output → answer is '(no response)'."""
    sd = tmp_path / "st3"
    sd.mkdir()
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)  # type: ignore[attr-defined]
    repo = tmp_path / "repo3"
    (repo / ".hephaestus" / "memory").mkdir(parents=True)
    monkeypatch.setattr("app.services.insights._run", lambda cmd, **kw: "")  # type: ignore[attr-defined]
    ws = _make_ws(str(repo))

    class EmptyStub:
        async def run(
            self,
            ref: object,
            *,
            prompt_file: pathlib.Path,
            cwd: str,
            output_path: pathlib.Path,
            timeout_sec: int,
            use_models: bool = False,
        ) -> object:
            pathlib.Path(output_path).write_text("")

            class R:
                exit_code = 0
                refused = False

            return R()

    res = asyncio.run(ins.ask(ws, "Silent question?", session_id=None, runner=EmptyStub()))
    assert res["answer"] == "(no response)"


def test_next_insights_seq_increments(tmp_path: pathlib.Path, monkeypatch: object) -> None:
    """_next_insights_seq returns 1 on empty dir, then increments."""
    sd = tmp_path / "st4"
    sd.mkdir()
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)  # type: ignore[attr-defined]

    assert ins._next_insights_seq() == 1
    (sd / "insights-0001").mkdir()
    assert ins._next_insights_seq() == 2
    (sd / "insights-0005").mkdir()
    assert ins._next_insights_seq() == 6


def test_extract_answer_claude_cli_shape(tmp_path: pathlib.Path) -> None:
    """_extract_answer handles Claude CLI stream-json message shape."""
    p = tmp_path / "out.jsonl"
    msg = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "Detailed answer here"}]},
    }
    p.write_text(json.dumps(msg) + "\n")
    assert "Detailed answer here" in ins._extract_answer(p)
