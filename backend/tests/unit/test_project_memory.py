"""Unit tests for project_memory — frontmatter, verify commands, atomic write, scan/task updates."""
from __future__ import annotations

import pathlib
import types

import pytest

from app.services import project_memory as pm


def _ws(repo_path: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(id="9f3a1c20e4b57d61", repo_path=repo_path, memory_dir=".hephaestus/memory")


def _ws_real(tmp_path: pathlib.Path):
    """Create a real RepoProfile for backward-compat tests."""
    from app.models.workspace import AgentRef, AgentsConfig, RepoProfile
    return RepoProfile(
        id="abc123", name="demo", repo_path=str(tmp_path),
        agents=AgentsConfig(primary=AgentRef(provider="p", model="m"), fallback=AgentRef(provider="p", model="m")),
    )


# ── Module-level function tests (Stage 2) ──

def test_frontmatter_roundtrip() -> None:
    fm = pm._frontmatter("verify", "9f3a1c20e4b57d61", "scan")
    meta, body = pm._parse_frontmatter(fm + "## commands\nhello\n")
    assert meta["doc"] == "verify"
    assert meta["workspace_id"] == "9f3a1c20e4b57d61"
    assert meta["source"] == "scan"
    assert meta["schema"] == 1
    assert body.strip() == "## commands\nhello"


def test_parse_frontmatter_absent() -> None:
    meta, body = pm._parse_frontmatter("no frontmatter here")
    assert meta == {}
    assert body == "no frontmatter here"


def test_unknown_doc_rejected() -> None:
    ws = _ws("/tmp/repo")
    with pytest.raises(ValueError):
        pm.write_doc(ws, "nope", "x", source="manual")
    assert pm.read_doc(ws, "nope") is None


def test_read_verify_commands(tmp_path: pathlib.Path) -> None:
    ws = _ws(str(tmp_path))
    body = "## commands\n```sh\nuv run pytest -q\n# a comment\n\nuv run ruff check .\n```\n"
    pm.write_doc(ws, "verify", body, source="profiler")
    cmds = pm.read_verify_commands(ws)
    assert cmds == ["uv run pytest -q", "uv run ruff check ."]


def test_read_verify_commands_no_block(tmp_path: pathlib.Path) -> None:
    ws = _ws(str(tmp_path))
    pm.write_doc(ws, "verify", "no commands here\n", source="profiler")
    assert pm.read_verify_commands(ws) == []


def test_write_doc_atomic(tmp_path: pathlib.Path) -> None:
    ws = _ws(str(tmp_path))
    p = pm.write_doc(ws, "architecture", "# Arch\nmodules\n", source="profiler")
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert text.startswith("---\ndoc: architecture\n")
    index = (pm.memory_dir(ws) / "MEMORY.md").read_text(encoding="utf-8")
    assert "[architecture](architecture.md)" in index
    assert "[x]" in index


def test_update_after_scan_appends_tech_debt(tmp_path: pathlib.Path) -> None:
    ws = _ws(str(tmp_path))
    proposals = [
        {"id": "scan-a", "title": "Fix race", "category": "bug", "severity": "high"},
        {"id": "scan-b", "title": "Add CSRF", "category": "security", "severity": "medium"},
        {"id": "scan-c", "title": "Rename var", "category": "quality", "severity": "low"},
    ]
    pm.update_after_scan(ws, scan_dir="scan-20260605-1", proposals=proposals)
    body = pm.read_doc(ws, "tech-debt")
    assert body is not None
    assert "## from scan scan-20260605-1" in body
    assert "Fix race" in body
    assert "Add CSRF" in body
    assert "Rename var" not in body


def test_update_after_scan_dedups_same_dir(tmp_path: pathlib.Path) -> None:
    ws = _ws(str(tmp_path))
    props = [{"id": "scan-a", "title": "Fix race", "category": "bug", "severity": "high"}]
    pm.update_after_scan(ws, scan_dir="scan-1", proposals=props)
    pm.update_after_scan(ws, scan_dir="scan-1", proposals=props)  # re-scan same dir
    body = pm.read_doc(ws, "tech-debt")
    assert body is not None
    assert body.count("## from scan scan-1") == 1  # upsert, not append twice


def test_update_after_scan_caps_length(tmp_path: pathlib.Path) -> None:
    ws = _ws(str(tmp_path))
    for i in range(200):
        pm.update_after_scan(
            ws,
            scan_dir=f"scan-{i}",
            proposals=[{"id": f"s{i}", "title": f"bug {i}", "category": "bug", "severity": "high"}],
        )
    body = pm.read_doc(ws, "tech-debt")
    assert body is not None
    assert len(body.splitlines()) <= 150  # memory stays short (research invariant)


# ── Backward-compatible class tests (Stage 1) ──

def test_class_write_doc_frontmatter(tmp_path: pathlib.Path) -> None:
    pmem = pm.ProjectMemory(_ws_real(tmp_path))
    p = pmem.write_doc("architecture", "## Modules\nfoo", source="profiler")
    assert p.exists()
    fm, body = pmem.read_doc("architecture")
    assert fm["doc"] == "architecture"
    assert fm["workspace_id"] == "abc123"
    assert fm["source"] == "profiler"
    assert fm["schema"] == 1
    assert body.strip() == "## Modules\nfoo"


def test_class_read_verify_commands(tmp_path: pathlib.Path) -> None:
    pmem = pm.ProjectMemory(_ws_real(tmp_path))
    body = "## commands\n```sh\nuv run pytest -q\n# a comment\n\nuv run ruff check .\n```\n"
    pmem.write_doc("verify", body, source="profiler")
    cmds = pmem.read_verify_commands()
    assert cmds == ["uv run pytest -q", "uv run ruff check ."]


def test_class_read_verify_commands_empty(tmp_path: pathlib.Path) -> None:
    pmem = pm.ProjectMemory(_ws_real(tmp_path))
    pmem.write_doc("verify", "no commands fence here", source="manual")
    assert pmem.read_verify_commands() == []


def test_class_read_doc_missing(tmp_path: pathlib.Path) -> None:
    pmem = pm.ProjectMemory(_ws_real(tmp_path))
    fm, body = pmem.read_doc("verify")
    assert fm == {}
    assert body == ""


def test_class_bootstrap_index(tmp_path: pathlib.Path) -> None:
    pmem = pm.ProjectMemory(_ws_real(tmp_path))
    pmem.write_doc("architecture", "x", source="profiler")
    pmem.bootstrap_index()
    fm, body = pmem.read_doc("index")
    assert fm["doc"] == "index"
    assert "architecture.md" in body
