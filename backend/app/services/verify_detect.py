"""Deterministic verify-command detector — no agent calls (Improvement 2)."""
from __future__ import annotations

import json
import logging
import pathlib

log = logging.getLogger("hephaestus.backend.verify_detect")

# Script keys in package.json that map to verify commands
_NPM_VERIFY_KEYS = ("test", "lint", "typecheck", "check")


def detect_verify_commands(repo_path: pathlib.Path) -> list[str]:
    """Detect verify commands from project config files.
    
    Scans for package.json, pyproject.toml, Makefile, go.mod, Cargo.toml.
    For monorepos, also checks immediate subdirectories.
    Returns a deduplicated list of shell commands.
    """
    cmds: list[str] = []
    
    # Root-level detection
    _detect_at(repo_path, cmds)
    
    # Monorepo: check immediate subdirs that have their own config
    try:
        for child in sorted(repo_path.iterdir()):
            if child.is_dir() and not child.name.startswith(".") and child.name not in (
                "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
            ):
                subdir_cmds: list[str] = []
                _detect_at(child, subdir_cmds)
                if subdir_cmds:
                    rel = child.name
                    for sc in subdir_cmds:
                        cmds.append(f"shell:cd {rel} && {sc}")
    except OSError:
        log.debug("monorepo subdir enumeration failed for %s", repo_path, exc_info=True)
        pass
    
    # Dedup preserving order
    seen: set[str] = set()
    result: list[str] = []
    for c in cmds:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


def partition_by_baseline(
    repo_path: pathlib.Path, cmds: list[str], timeout_sec: int = 600
) -> tuple[list[str], list[str]]:
    """Split detected verify commands into ``(gating, advisory)`` by running each on the
    clean baseline tree.

    A command that already FAILS on the untouched repo — a pre-existing red suite, missing
    infra/services, or a platform-mismatched dependency — can never gate: it would fail
    every task regardless of the agent's change. Such commands are downgraded to *advisory*
    (recorded, not gating); commands that pass become the hard gate. The diff-scoped test net
    (``app.core.diff_tests``) still runs the test files each change touches.

    Synchronous on purpose: this runs once, in the separate orchestrator process, before any
    iteration, so a blocking probe doesn't touch the dashboard API. Best-effort — a command
    that errors, is missing, or times out counts as red. Each command is capped at
    ``timeout_sec`` (never more than 600s) so a hung command can't stall startup."""
    import subprocess

    from app.core.verify import argv_for

    cap = min(timeout_sec, 600) if timeout_sec and timeout_sec > 0 else 600
    gating: list[str] = []
    advisory: list[str] = []
    for cmd in cmds:
        argv = argv_for(cmd)
        if not argv:
            continue
        try:
            rc = subprocess.run(
                argv, cwd=str(repo_path), capture_output=True, timeout=cap
            ).returncode
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            log.debug("baseline probe failed/timed out for %r", cmd, exc_info=True)
            rc = 1
        (gating if rc == 0 else advisory).append(cmd)
    return gating, advisory


def _detect_at(directory: pathlib.Path, cmds: list[str]) -> None:
    """Detect verify commands in a single directory."""
    _detect_npm(directory, cmds)
    _detect_python(directory, cmds)
    _detect_makefile(directory, cmds)
    _detect_go(directory, cmds)
    _detect_cargo(directory, cmds)


def _detect_npm(directory: pathlib.Path, cmds: list[str]) -> None:
    pkg = directory / "package.json"
    if not pkg.exists():
        return
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
        scripts = data.get("scripts", {})
        for key in _NPM_VERIFY_KEYS:
            if key in scripts:
                cmds.append(f"npm run {key}")
    except Exception:
        log.debug("failed to parse package.json in %s", directory, exc_info=True)
        pass


def _detect_python(directory: pathlib.Path, cmds: list[str]) -> None:
    pyproject = directory / "pyproject.toml"
    if not pyproject.exists():
        return
    try:
        content = pyproject.read_text(encoding="utf-8")
        if "[tool.pytest" in content or "pytest" in content.lower():
            cmds.append("python -m pytest -q")
        if "[tool.ruff" in content or "ruff" in content.lower():
            cmds.append("ruff check .")
        if "[tool.mypy" in content or "mypy" in content.lower():
            cmds.append("mypy --strict .")
    except Exception:
        log.debug("failed to parse pyproject.toml in %s", directory, exc_info=True)
        pass


def _detect_makefile(directory: pathlib.Path, cmds: list[str]) -> None:
    makefile = directory / "Makefile"
    if not makefile.exists():
        return
    try:
        content = makefile.read_text(encoding="utf-8")
        for target in ("test", "lint", "check"):
            # Match lines like "test:" or "test: deps"
            import re
            if re.search(rf"^{target}\s*:", content, re.MULTILINE):
                cmds.append(f"make {target}")
    except Exception:
        log.debug("failed to parse Makefile in %s", directory, exc_info=True)
        pass


def _detect_go(directory: pathlib.Path, cmds: list[str]) -> None:
    if (directory / "go.mod").exists():
        cmds.append("go test ./...")
        cmds.append("go vet ./...")


def _detect_cargo(directory: pathlib.Path, cmds: list[str]) -> None:
    if (directory / "Cargo.toml").exists():
        cmds.append("cargo test")
        cmds.append("cargo clippy -- -D warnings")
