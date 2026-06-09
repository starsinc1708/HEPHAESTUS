"""Tests for deterministic verify-command detector."""
from __future__ import annotations

import json
import pathlib

from app.services.verify_detect import detect_verify_commands


def test_detects_from_package_json(tmp_path: pathlib.Path) -> None:
    """Vue repo with test/lint/build scripts."""
    (tmp_path / "package.json").write_text(
        json.dumps({
            "scripts": {
                "test": "vitest run",
                "lint": "eslint .",
                "typecheck": "vue-tsc --noEmit",
                "build": "vite build",
            }
        }),
        encoding="utf-8",
    )
    cmds = detect_verify_commands(tmp_path)
    assert any("vitest" in c or "test" in c for c in cmds)
    assert any("eslint" in c or "lint" in c for c in cmds)
    assert any("vue-tsc" in c or "typecheck" in c for c in cmds)


def test_detects_from_pyproject(tmp_path: pathlib.Path) -> None:
    """Python repo with pytest/ruff/mypy in pyproject.toml."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n[tool.ruff]\n[tool.mypy]\n",
        encoding="utf-8",
    )
    cmds = detect_verify_commands(tmp_path)
    assert any("pytest" in c for c in cmds)
    assert any("ruff" in c for c in cmds)
    assert any("mypy" in c for c in cmds)


def test_detects_from_makefile(tmp_path: pathlib.Path) -> None:
    (tmp_path / "Makefile").write_text(
        "test:\n\tpytest\nlint:\n\truff check .\n", encoding="utf-8"
    )
    cmds = detect_verify_commands(tmp_path)
    assert any("make" in c for c in cmds)


def test_detects_go(tmp_path: pathlib.Path) -> None:
    (tmp_path / "go.mod").write_text(
        "module example.com/foo\ngo 1.21\n", encoding="utf-8"
    )
    cmds = detect_verify_commands(tmp_path)
    assert any("go test" in c for c in cmds)
    assert any("go vet" in c for c in cmds)


def test_detects_cargo(tmp_path: pathlib.Path) -> None:
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "foo"\n', encoding="utf-8"
    )
    cmds = detect_verify_commands(tmp_path)
    assert any("cargo test" in c for c in cmds)
    assert any("cargo clippy" in c or "cargo check" in c for c in cmds)


def test_empty_repo(tmp_path: pathlib.Path) -> None:
    assert detect_verify_commands(tmp_path) == []


def test_dedup(tmp_path: pathlib.Path) -> None:
    """Same command from two sources should not appear twice."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n", encoding="utf-8"
    )
    (tmp_path / "Makefile").write_text(
        "test:\n\tpytest\n", encoding="utf-8"
    )
    cmds = detect_verify_commands(tmp_path)
    # Should have no exact duplicates
    assert len(cmds) == len(set(cmds))


def test_monorepo_subdirs(tmp_path: pathlib.Path) -> None:
    fe = tmp_path / "frontend"
    fe.mkdir()
    (fe / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run", "lint": "eslint ."}}),
        encoding="utf-8",
    )
    be = tmp_path / "backend"
    be.mkdir()
    (be / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n[tool.ruff]\n", encoding="utf-8"
    )
    cmds = detect_verify_commands(tmp_path)
    assert any("frontend" in c for c in cmds)
    assert any("backend" in c for c in cmds)


def test_init_verify_if_empty(tmp_path: pathlib.Path) -> None:
    from app.models.workspace import AgentsConfig, RepoProfile
    from app.services.project_memory import init_verify_if_empty, read_verify_commands
    
    ws = RepoProfile(
        id="test-ws",
        name="test-ws",
        repo_path=str(tmp_path),
        base_branch="main",
        remote="origin",
        branch_prefix="auto",
        agents=AgentsConfig(
            primary={"provider": "openai", "model": "gpt-4"},
            fallback={"provider": "openai", "model": "gpt-4"},
        ),
        memory_dir=".hephaestus/memory"
    )
    
    # Write package.json so detection finds something
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run"}}),
        encoding="utf-8"
    )
    
    # Initially verify.md does not exist
    assert init_verify_if_empty(ws) is True
    
    # Now it exists, commands should match
    cmds = read_verify_commands(ws)
    assert cmds == ["npm run test"]
    
    # Calling it again should return False (idempotent)
    assert init_verify_if_empty(ws) is False

