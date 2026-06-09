"""Tests: optional output_path parameter for build_map, generate_ideas."""
from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace

import pytest

import app.core.state as state_mod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_runner(output_text: str = ""):
    """Returns an object with an async run() that writes output_text to output_path."""

    class _Runner:
        async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec, use_models=True):
            pathlib.Path(output_path).write_text(output_text, encoding="utf-8")
            return SimpleNamespace(
                exit_code=0,
                refused=False,
                output_path=output_path,
                agent_label="fake",
            )

    return _Runner()


def _make_ws(tmp_path: pathlib.Path):
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / ".hephaestus" / "state").mkdir(parents=True, exist_ok=True)
    (repo / ".hephaestus" / "memory").mkdir(parents=True, exist_ok=True)
    (repo / ".git").mkdir(exist_ok=True)
    agents = SimpleNamespace(
        primary=SimpleNamespace(provider="p", model="m", agent="primary"),
        planner=None,
    )
    return SimpleNamespace(
        id="ws-test",
        repo_path=str(repo),
        agents=agents,
        engine="opencode",
        engine_env={},
        engine_profiles=[],
    )


# ---------------------------------------------------------------------------
# build_map output_path
# ---------------------------------------------------------------------------


async def test_build_map_with_output_path(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    map_block = 'MAP_BEGIN{"map":{"a.py":"entry"}}MAP_END'
    map_json = json.dumps({"type": "text", "text": map_block})
    runner = _fake_runner(map_json + "\n")

    custom_output = tmp_path / "custom_map.jsonl"

    from app.services.codebase_map import build_map

    ws = _make_ws(tmp_path)
    result = await build_map(ws, runner=runner, output_path=custom_output)

    assert isinstance(result, dict)
    # The custom output path must exist (runner wrote to it)
    assert custom_output.exists()


async def test_build_map_without_output_path_still_works(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Backward-compat: no output_path → uses the default internal path."""
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    runner = _fake_runner("")
    from app.services.codebase_map import build_map

    ws = _make_ws(tmp_path)
    result = await build_map(ws, runner=runner)
    # Returns {} on empty output — that's fine; just must not raise
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# generate_ideas output_path
# ---------------------------------------------------------------------------


async def test_generate_ideas_with_output_path(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    idea_block = (
        'IDEAS_BEGIN{"ideas":[{"title":"T","proposal":"p","rationale":"r",'
        '"category":"quality","severity":"low","touches":[]}]}IDEAS_END'
    )
    idea_json = json.dumps({"type": "text", "text": idea_block})
    runner = _fake_runner(idea_json + "\n")

    custom_output = tmp_path / "custom_ideas.jsonl"

    from app.services.ideas import generate_ideas

    ws = _make_ws(tmp_path)
    # Stub project_memory and codebase_map to avoid FS side-effects
    monkeypatch.setattr("app.services.project_memory.read_doc", lambda ws, k: "")
    monkeypatch.setattr("app.services.codebase_map.read_map", lambda ws: {})
    monkeypatch.setattr(
        "app.services.prompt_manager.PromptManager.render_prompt",
        lambda self, name, ctx: "prompt text",
    )

    result = await generate_ideas(ws, categories=None, runner=runner, output_path=custom_output)

    assert isinstance(result, list)
    assert custom_output.exists()


async def test_generate_ideas_without_output_path_still_works(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path)

    runner = _fake_runner("")
    monkeypatch.setattr("app.services.project_memory.read_doc", lambda ws, k: "")
    monkeypatch.setattr("app.services.codebase_map.read_map", lambda ws: {})
    monkeypatch.setattr(
        "app.services.prompt_manager.PromptManager.render_prompt",
        lambda self, name, ctx: "prompt text",
    )

    from app.services.ideas import generate_ideas

    ws = _make_ws(tmp_path)
    result = await generate_ideas(ws, categories=None, runner=runner)
    assert isinstance(result, list)
