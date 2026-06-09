"""Integration test for ideas generator + store + import (Epic 4 B1)."""
from __future__ import annotations

import asyncio
import pathlib
import types

import app.core.state as state
from app.services import ideas as ideas_mod


def _make_ws(repo_path: str) -> types.SimpleNamespace:
    """Minimal RepoProfile-shaped namespace sufficient for generate_ideas."""
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
    )


def test_generate_and_import(tmp_path, monkeypatch):
    sd = tmp_path / "st"
    sd.mkdir()
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)
    ws = _make_ws(str(tmp_path / "repo"))

    class Stub:
        async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec, use_models=False):
            pathlib.Path(output_path).write_text(
                'IDEAS_BEGIN{"ideas":[{"title":"Add index","proposal":"p","rationale":"r",'
                '"category":"performance","severity":"medium","touches":["db.py"]}]}IDEAS_END'
            )

            class R:
                exit_code = 0
                refused = False

            return R()

    out = asyncio.run(ideas_mod.generate_ideas(ws, categories=None, runner=Stub()))
    assert out[0].title == "Add index"
    res = ideas_mod.import_ideas([out[0].id])
    assert res["added"]
    from app.core.state import _read_state

    assert any(i.get("source") == "ideas" for i in _read_state()["items"])


def test_generate_returns_empty_on_bad_block(tmp_path, monkeypatch):
    """No valid IDEAS block → generate_ideas returns []."""
    sd = tmp_path / "st2"
    sd.mkdir()
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)
    ws = _make_ws(str(tmp_path / "repo2"))

    class BadStub:
        async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec, use_models=False):
            pathlib.Path(output_path).write_text("no ideas here")

            class R:
                exit_code = 0
                refused = False

            return R()

    out = asyncio.run(ideas_mod.generate_ideas(ws, categories=None, runner=BadStub()))
    assert out == []


def test_parse_ideas_block_last_match():
    """_parse_ideas_block picks the LAST match when multiple blocks are present."""
    text = (
        'IDEAS_BEGIN{"ideas":[{"title":"first"}]}IDEAS_END'
        " noise "
        'IDEAS_BEGIN{"ideas":[{"title":"last"}]}IDEAS_END'
    )
    result = ideas_mod._parse_ideas_block(text)
    assert result[0]["title"] == "last"


def test_import_ideas_marks_imported(tmp_path, monkeypatch):
    """import_ideas sets imported=True on the stored ideas."""
    sd = tmp_path / "st3"
    sd.mkdir()
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)
    ws = _make_ws(str(tmp_path / "repo3"))

    class Stub:
        async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec, use_models=False):
            pathlib.Path(output_path).write_text(
                'IDEAS_BEGIN{"ideas":[{"title":"Opt cache","proposal":"p","rationale":"r",'
                '"category":"performance","severity":"low","touches":[]}]}IDEAS_END'
            )

            class R:
                exit_code = 0
                refused = False

            return R()

    ideas = asyncio.run(ideas_mod.generate_ideas(ws, categories=None, runner=Stub()))
    assert not ideas[0].imported
    ideas_mod.import_ideas([ideas[0].id])
    store = ideas_mod.IdeaStore()
    refreshed = store.get(ideas[0].id)
    assert refreshed is not None
    assert refreshed.imported is True


def test_idea_store_list_get_put(tmp_path, monkeypatch):
    """Basic store round-trip."""
    sd = tmp_path / "st4"
    sd.mkdir()
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)

    store = ideas_mod.IdeaStore()
    idea = ideas_mod.Idea(id="idea-abc", title="Test idea", proposal="p")
    store.put(idea)
    assert store.get("idea-abc") is not None
    assert store.get("idea-abc").title == "Test idea"
    assert store.get("nonexistent") is None


def test_generate_with_categories(tmp_path, monkeypatch):
    """categories list is rendered into the prompt."""
    sd = tmp_path / "st5"
    sd.mkdir()
    monkeypatch.setattr(state, "_STATE_DIR_OVERRIDE", sd)
    ws = _make_ws(str(tmp_path / "repo5"))
    prompt_texts: list[str] = []

    class CapStub:
        async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec, use_models=False):
            prompt_texts.append(pathlib.Path(prompt_file).read_text())
            pathlib.Path(output_path).write_text(
                'IDEAS_BEGIN{"ideas":[{"title":"X","proposal":"p","rationale":"r",'
                '"category":"security","severity":"high","touches":[]}]}IDEAS_END'
            )

            class R:
                exit_code = 0
                refused = False

            return R()

    asyncio.run(ideas_mod.generate_ideas(ws, categories=["security", "perf"], runner=CapStub()))
    assert "security" in prompt_texts[0]
    assert "perf" in prompt_texts[0]
