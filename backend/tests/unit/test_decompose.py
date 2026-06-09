"""Unit tests for decompose — block parsing, epic expansion, fallback. AgentRunner mocked."""
from __future__ import annotations

import pathlib

import pytest


def test_decomposer_prompt_exists_and_templated() -> None:
    p = pathlib.Path(__file__).resolve().parents[3] / "prompts" / "scan-decomposer.md"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "{{proposals_json}}" in text
    assert "{{repo_path}}" in text
    assert "{{memory_excerpt}}" in text
    assert "DECOMPOSE_BEGIN" in text
    assert "DECOMPOSE_END" in text
    for forbidden in ("sisyphus", "atlas", "/home/starsinc", "pnpm"):
        assert forbidden not in text


from app.core.decompose import _parse_decompose_block  # noqa: E402


def test_parse_decompose_block() -> None:
    text = (
        "some reasoning\n"
        "DECOMPOSE_BEGIN\n"
        '{"tasks": [{"id": "scan-a", "epic": false, "subtasks": [], "dependsOn": ["scan-b"], "reason": "x"}]}\n'
        "DECOMPOSE_END\n"
        "trailing"
    )
    parsed = _parse_decompose_block(text)
    assert parsed is not None
    assert parsed["tasks"][0]["id"] == "scan-a"
    assert parsed["tasks"][0]["dependsOn"] == ["scan-b"]


def test_parse_decompose_block_takes_last() -> None:
    text = (
        "DECOMPOSE_BEGIN\n{\"tasks\": []}\nDECOMPOSE_END\n"
        "DECOMPOSE_BEGIN\n{\"tasks\": [{\"id\": \"scan-z\"}]}\nDECOMPOSE_END\n"
    )
    parsed = _parse_decompose_block(text)
    assert parsed["tasks"][0]["id"] == "scan-z"


def test_parse_decompose_block_bad_json() -> None:
    assert _parse_decompose_block("DECOMPOSE_BEGIN\n{not json}\nDECOMPOSE_END") is None
    assert _parse_decompose_block("no block at all") is None


import types  # noqa: E402

from app.core.decompose import decompose_proposals  # noqa: E402


class _FakeRunner:
    """Mock AgentRunner: writes a predetermined final text to output_path, returns it."""
    def __init__(self, final_text: str) -> None:
        self._text = final_text

    async def run(self, ref, *, prompt_file, cwd, output_path: pathlib.Path, timeout_sec):
        output_path.write_text(self._text, encoding="utf-8")
        return types.SimpleNamespace(exit_code=0, refused=False, output_path=output_path, agent_label="mock")


def _ws(tmp_path) -> object:
    from app.models.workspace import AgentRef, AgentsConfig
    agents = AgentsConfig(primary=AgentRef(provider="p", model="m"), fallback=AgentRef(provider="p", model="m"))
    return types.SimpleNamespace(
        id="ws01", repo_path=str(tmp_path), memory_dir=".hephaestus/memory", agents=agents
    )


def _proposals() -> list[dict]:
    return [
        {"id": "scan-a", "title": "A", "proposal": "do a", "touches": ["src/x.py"]},
        {"id": "scan-b", "title": "B", "proposal": "do b", "touches": ["src/y.py"]},
    ]


@pytest.mark.asyncio
async def test_decompose_empty_returns_empty(tmp_path: pathlib.Path) -> None:
    runner = _FakeRunner("")
    out = await decompose_proposals(_ws(tmp_path), [], scan_dir="scan-1", runner=runner)
    assert out == []


@pytest.mark.asyncio
async def test_decompose_fallback_on_bad_json(tmp_path: pathlib.Path) -> None:
    runner = _FakeRunner("garbage with no block")
    out = await decompose_proposals(_ws(tmp_path), _proposals(), scan_dir="scan-1", runner=runner)
    assert {t["id"] for t in out} == {"scan-a", "scan-b"}
    assert all(t["dependsOn"] == [] for t in out)


@pytest.mark.asyncio
async def test_decompose_applies_depends_and_order(tmp_path: pathlib.Path) -> None:
    block = (
        "DECOMPOSE_BEGIN\n"
        '{"tasks": [{"id": "scan-b", "epic": false, "subtasks": [], "dependsOn": ["scan-a"]}]}\n'
        "DECOMPOSE_END"
    )
    runner = _FakeRunner(block)
    out = await decompose_proposals(_ws(tmp_path), _proposals(), scan_dir="scan-1", runner=runner)
    by_id = {t["id"]: t for t in out}
    assert by_id["scan-b"]["dependsOn"] == ["scan-a"]
    assert by_id["scan-a"]["orderIndex"] < by_id["scan-b"]["orderIndex"]


@pytest.mark.asyncio
async def test_dangling_depends_dropped(tmp_path: pathlib.Path) -> None:
    block = (
        "DECOMPOSE_BEGIN\n"
        '{"tasks": [{"id": "scan-a", "dependsOn": ["ghost"]}]}\n'
        "DECOMPOSE_END"
    )
    runner = _FakeRunner(block)
    out = await decompose_proposals(_ws(tmp_path), _proposals(), scan_dir="scan-1", runner=runner)
    by_id = {t["id"]: t for t in out}
    assert by_id["scan-a"]["dependsOn"] == []


@pytest.mark.asyncio
async def test_epic_expansion(tmp_path: pathlib.Path) -> None:
    proposals = [{"id": "scan-epic", "title": "Big", "proposal": "p", "touches": []}]
    block = (
        "DECOMPOSE_BEGIN\n"
        '{"tasks": [{"id": "scan-epic", "epic": true, "subtasks": ['
        '{"id": "1", "title": "part1", "proposal": "p1", "touches": ["a.py"], "dependsOn": []},'
        '{"id": "2", "title": "part2", "proposal": "p2", "touches": ["b.py"], "dependsOn": ["1"]}'
        ']}]}\n'
        "DECOMPOSE_END"
    )
    runner = _FakeRunner(block)
    out = await decompose_proposals(_ws(tmp_path), proposals, scan_dir="scan-1", runner=runner)
    by_id = {t["id"]: t for t in out}
    assert "scan-epic" in by_id
    assert by_id["scan-epic"]["epicId"] is None
    assert "scan-epic-1" in by_id and by_id["scan-epic-1"]["epicId"] == "scan-epic"
    assert by_id["scan-epic-1"]["parent"] == "scan-epic"
    assert by_id["scan-epic-2"]["dependsOn"] == ["scan-epic-1"]


@pytest.mark.asyncio
async def test_llm_cycle_broken(tmp_path: pathlib.Path, caplog) -> None:
    block = (
        "DECOMPOSE_BEGIN\n"
        '{"tasks": [{"id": "scan-a", "dependsOn": ["scan-b"]}, {"id": "scan-b", "dependsOn": ["scan-a"]}]}\n'
        "DECOMPOSE_END"
    )
    runner = _FakeRunner(block)
    out = await decompose_proposals(_ws(tmp_path), _proposals(), scan_dir="scan-1", runner=runner)
    assert {t["id"] for t in out} == {"scan-a", "scan-b"}


# ---------------------------------------------------------------------------
# A3: complexity field propagation (Epic 2, Batch A)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decompose_carries_complexity(tmp_path: pathlib.Path) -> None:
    """Task with complexity in LLM output gets complexity in the returned dict."""
    block = (
        "DECOMPOSE_BEGIN\n"
        '{"tasks": ['
        '{"id": "scan-a", "epic": false, "subtasks": [], "dependsOn": [], "complexity": "complex"},'
        '{"id": "scan-b", "epic": false, "subtasks": [], "dependsOn": []}'
        "]}\n"
        "DECOMPOSE_END"
    )
    runner = _FakeRunner(block)
    out = await decompose_proposals(_ws(tmp_path), _proposals(), scan_dir="scan-1", runner=runner)
    by_id = {t["id"]: t for t in out}
    assert by_id["scan-a"]["complexity"] == "complex"
    assert by_id["scan-b"]["complexity"] is None


@pytest.mark.asyncio
async def test_decompose_complexity_none_when_absent(tmp_path: pathlib.Path) -> None:
    """Task without complexity field in LLM output defaults to None."""
    block = (
        "DECOMPOSE_BEGIN\n"
        '{"tasks": [{"id": "scan-a", "dependsOn": []}, {"id": "scan-b", "dependsOn": []}]}\n'
        "DECOMPOSE_END"
    )
    runner = _FakeRunner(block)
    out = await decompose_proposals(_ws(tmp_path), _proposals(), scan_dir="scan-1", runner=runner)
    by_id = {t["id"]: t for t in out}
    assert by_id["scan-a"].get("complexity") is None
    assert by_id["scan-b"].get("complexity") is None
