"""Unit tests for native map-reduce scan_run. AgentRunner + finding parsers mocked."""
from __future__ import annotations

import pathlib
import types

import pytest

from app.core import scan_run


def test_chunk_files_round_robin(tmp_path: pathlib.Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    for i in range(5):
        (src / f"f{i}.py").write_text("x\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "ignored.py").write_text("nope\n")
    chunks = scan_run.chunk_files(str(tmp_path), "src", n=2)
    flat = sorted(f for c in chunks for f in c)
    assert flat == ["src/f0.py", "src/f1.py", "src/f2.py", "src/f3.py", "src/f4.py"]
    assert all(".git" not in f for f in flat)
    assert 1 <= len(chunks) <= 2


def test_dedup_findings_merges_and_counts() -> None:
    items = [
        {"title": "Fix race", "touches": ["src/x.py:10"]},
        {"title": "fix race", "touches": ["src\\x.py"]},
        {"title": "Other", "touches": ["src/y.py"]},
    ]
    out = scan_run.dedup_findings(items)
    assert len(out) == 2
    merged = [it for it in out if it["title"].lower() == "fix race"][0]
    assert merged["agreement_count"] == 2


@pytest.mark.asyncio
async def test_run_mappers_aggregates(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(
        scan_run, "parse_findings_block",
        lambda text: [{"title": text.strip(), "touches": ["a.py"]}],
        raising=False,
    )

    class _Runner:
        async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec):
            output_path.write_text(f"finding-from-{output_path.stem}", encoding="utf-8")
            return types.SimpleNamespace(exit_code=0)

    class _PM:
        def render_prompt(self, name, vars):
            return "PROMPT"

    ws = types.SimpleNamespace(
        repo_path=str(tmp_path),
        agents=types.SimpleNamespace(primary=types.SimpleNamespace(provider="p", model="m")),
    )
    scan_dir = tmp_path / "scan-1"
    scan_dir.mkdir()
    findings = await scan_run.run_mappers(
        ws, _Runner(), scan_dir, [["a.py"], ["b.py"]], prompt_mgr=_PM(), timeout_sec=10
    )
    assert len(findings) == 2


@pytest.mark.asyncio
async def test_run_reducers_shards(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(
        scan_run, "parse_proposals_block",
        lambda text: [{"id": "scan-x", "title": "X", "touches": ["a.py"]}],
        raising=False,
    )

    class _Runner:
        async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec):
            output_path.write_text("blob", encoding="utf-8")
            return types.SimpleNamespace(exit_code=0)

    class _PM:
        def render_prompt(self, name, vars):
            return "PROMPT"

    ws = types.SimpleNamespace(
        repo_path=str(tmp_path),
        agents=types.SimpleNamespace(primary=types.SimpleNamespace(provider="p", model="m")),
    )
    scan_dir = tmp_path / "scan-1"
    scan_dir.mkdir()
    proposals = await scan_run.run_reducers(
        ws, _Runner(), scan_dir, [{"title": "f1"}, {"title": "f2"}],
        reducers=2, prompt_mgr=_PM(), timeout_sec=10
    )
    assert len(proposals) >= 1
