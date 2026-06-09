"""Integration test for codebase_map (Epic 4 A1) — stub runner, no real agent CLI."""
from __future__ import annotations

import asyncio
import pathlib
import types

from app.services import codebase_map as cm


def _make_ws(repo_path: str) -> types.SimpleNamespace:
    """Minimal RepoProfile-shaped namespace sufficient for build_map/read_map."""
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


def test_build_and_read_map(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / ".hephaestus" / "memory").mkdir(parents=True)
    monkeypatch.setattr("app.services.codebase_map._run", lambda cmd, **kw: "a.py\nb.py")
    ws = _make_ws(str(repo))

    class Stub:
        async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec, use_models=False):
            pathlib.Path(output_path).write_text(
                'MAP_BEGIN{"map":{"a.py":"entry","b.py":"util"}}MAP_END'
            )

            class R:
                exit_code = 0
                refused = False

            return R()

    m = asyncio.run(cm.build_map(ws, runner=Stub()))
    assert m["a.py"] == "entry"
    assert cm.read_map(ws)["b.py"] == "util"


def test_read_map_absent(tmp_path):
    ws = _make_ws(str(tmp_path / "norepo"))
    assert cm.read_map(ws) == {}


def test_parse_map_block_last_match(tmp_path):
    """_parse_map_block picks the LAST match when there are multiple blocks."""
    text = (
        'MAP_BEGIN{"map":{"x.py":"first"}}MAP_END'
        " some noise "
        'MAP_BEGIN{"map":{"y.py":"last"}}MAP_END'
    )
    result = cm._parse_map_block(text)
    assert result == {"y.py": "last"}


def test_parse_map_block_empty_on_bad_json(tmp_path):
    assert cm._parse_map_block("MAP_BEGIN{broken}MAP_END") == {}


def test_build_map_filters_excludes(tmp_path, monkeypatch):
    """Files containing excluded fragments are stripped before sending to the agent."""
    repo = tmp_path / "repo2"
    (repo / ".hephaestus" / "memory").mkdir(parents=True)
    seen_files: list[str] = []

    raw_ls = "app.py\nnode_modules/pkg.js\n.venv/lib.py\ndist/bundle.js\n.git/config"
    monkeypatch.setattr("app.services.codebase_map._run", lambda cmd, **kw: raw_ls)

    ws = _make_ws(str(repo))

    class CapturingStub:
        async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec, use_models=False):
            seen_files.extend(pathlib.Path(prompt_file).read_text().splitlines())
            pathlib.Path(output_path).write_text('MAP_BEGIN{"map":{"app.py":"main"}}MAP_END')

            class R:
                exit_code = 0
                refused = False

            return R()

    asyncio.run(cm.build_map(ws, runner=CapturingStub()))
    full_prompt = "\n".join(seen_files)
    assert "node_modules" not in full_prompt
    assert ".venv" not in full_prompt
