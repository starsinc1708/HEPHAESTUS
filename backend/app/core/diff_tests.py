"""diff_tests — actually RUN the test files an iteration touched.

The validation funnel (LLM review) is fallible: it once approved a camera feature
whose committed test file tested a *different API* than the implementation (17/18
red) because nothing ever ran the tests. This module is the deterministic safety
net — if the agent created/changed a ``*.test`` / ``*.spec`` / ``test_*`` file, we
run it with an auto-detected runner. Red tests flip the verify gate to *fail*, so a
broken test goes to revision instead of merge.

Design rules:
- **Auto-detect runner by file type** (vitest/jest for JS·TS, pytest for Python,
  ``go test`` for Go). The runner is resolved from the project, never assumed.
- **Never-crash, never false-fail.** A missing/undetectable runner yields ``unrun``
  (surfaced, not a failure). We never fail a task just because we could not find a
  runner, and runner *startup* errors are ``unrun`` — only a runner that ran and
  reported failing tests is a ``failed``.
- **Cross-platform.** ``shutil.which`` resolves ``npx.cmd``/``go.exe`` shims on
  Windows; child processes use argv lists, no shell.
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import logging
import os
import pathlib
import shutil
import subprocess
import sys
from typing import IO, NamedTuple

from pydantic import BaseModel

log = logging.getLogger("hephaestus.backend.diff_tests")

# JS/TS test-file extensions (the part after the final dot).
_JS_EXTS = frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"})


class DiffTestResult(BaseModel):
    ok: bool                      # False iff a runner ran and reported failing tests
    ran: list[str]                # test files executed green
    failed: list[str]             # test files in a runner group that reported failures
    unrun: list[str]              # detected test files with no available/usable runner
    log_path: pathlib.Path


class _RunGroup(NamedTuple):
    argv: list[str]
    cwd: str
    files: list[str]
    kind: str                     # "js" | "py" | "go"


def detect_kind(path: str) -> str | None:
    """Return ``'js' | 'py' | 'go'`` if *path* is a test file, else ``None``.

    JS·TS: ``*.test.<ext>`` / ``*.spec.<ext>``. Python: ``test_*.py`` / ``*_test.py``.
    Go: ``*_test.go``.
    """
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    stem, _, ext = name.rpartition(".")
    if not ext:
        return None
    ext = "." + ext
    if ext in _JS_EXTS and (stem.endswith(".test") or stem.endswith(".spec")):
        return "js"
    if ext == ".py" and (name.startswith("test_") or stem.endswith("_test")):
        return "py"
    if ext == ".go" and stem.endswith("_test"):
        return "go"
    return None


def _git(repo: str, *args: str) -> str:
    """Run a read-only git command, returning stdout ('' on any error)."""
    try:
        completed = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout or ""


def changed_test_files(repo: str, base_ref: str) -> list[tuple[str, str]]:
    """Test files touched this iteration → ``[(repo_relative_path, kind), …]``.

    Union of the working tree (``git status --porcelain -uall`` — picks up *new
    untracked* test files the agent just wrote) and commits since *base_ref*
    (``git diff --name-only base..HEAD`` — picks up files the agent self-committed).
    """
    paths: set[str] = set()
    for line in _git(repo, "status", "--porcelain", "-uall").splitlines():
        if len(line) < 4:
            continue
        p = line[3:].strip()
        if " -> " in p:            # rename: "old -> new"
            p = p.split(" -> ", 1)[1]
        p = p.strip().strip('"')
        if p:
            paths.add(p.replace("\\", "/"))
    for line in _git(repo, "diff", "--name-only", f"{base_ref}..HEAD").splitlines():
        p = line.strip()
        if p:
            paths.add(p.replace("\\", "/"))
    out: list[tuple[str, str]] = []
    for p in sorted(paths):
        kind = detect_kind(p)
        if kind:
            out.append((p, kind))
    return out


def _read_pkg_deps(pkg_dir: str) -> set[str]:
    try:
        data = json.loads((pathlib.Path(pkg_dir) / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    deps: set[str] = set()
    for key in ("devDependencies", "dependencies", "peerDependencies"):
        d = data.get(key)
        if isinstance(d, dict):
            deps.update(d.keys())
    return deps


def _nearest_pkg_dir(repo: str, file_rel: str) -> str | None:
    """Closest ancestor directory of *file_rel* (within *repo*) holding a package.json."""
    repo_p = pathlib.Path(repo).resolve()
    cur = (repo_p / file_rel).resolve().parent
    while True:
        if (cur / "package.json").is_file():
            return str(cur)
        if cur == repo_p:
            return None
        parent = cur.parent
        if parent == cur:          # filesystem root — stop
            return None
        cur = parent


def _js_runner(pkg_dir: str) -> str | None:
    deps = _read_pkg_deps(pkg_dir)
    if "vitest" in deps:
        return "vitest"
    if "jest" in deps:
        return "jest"
    return None


def _plan_runs(repo: str, tests: list[tuple[str, str]]) -> tuple[list[_RunGroup], list[str]]:
    """Group detected test files into one child process per runner.

    Returns ``(run_groups, unrun_files)``. A file lands in *unrun* when its runner
    can't be detected or resolved on PATH.
    """
    runs: list[_RunGroup] = []
    unrun: list[str] = []
    repo_p = pathlib.Path(repo).resolve()

    # ---- JS·TS: group by (nearest package.json dir, runner) ----------------
    npx = shutil.which("npx")
    js_groups: dict[tuple[str, str], list[str]] = {}
    for f, k in tests:
        if k != "js":
            continue
        pkg = _nearest_pkg_dir(repo, f)
        runner = _js_runner(pkg) if pkg else None
        if not pkg or not runner or not npx:
            unrun.append(f)
            continue
        js_groups.setdefault((pkg, runner), []).append(f)
    for (pkg, runner), files in js_groups.items():
        assert npx is not None  # js_groups is only populated when npx resolved on PATH
        rel = [os.path.relpath((repo_p / f).resolve(), pkg).replace("\\", "/") for f in files]
        argv = [npx, "--no-install", "vitest", "run", *rel] if runner == "vitest" \
            else [npx, "--no-install", "jest", *rel]
        runs.append(_RunGroup(argv=argv, cwd=pkg, files=files, kind="js"))

    # ---- Python: one pytest invocation from repo root ----------------------
    py = [f for f, k in tests if k == "py"]
    if py:
        if importlib.util.find_spec("pytest") is not None:
            runs.append(_RunGroup(
                argv=[sys.executable, "-m", "pytest", *py, "-q", "-p", "no:cacheprovider"],
                cwd=repo, files=py, kind="py",
            ))
        else:
            unrun.extend(py)

    # ---- Go: one `go test` per package dir ---------------------------------
    go = [f for f, k in tests if k == "go"]
    if go:
        go_bin = shutil.which("go")
        if not go_bin:
            unrun.extend(go)
        else:
            go_dirs: dict[str, list[str]] = {}
            for f in go:
                d = (str(pathlib.PurePosixPath(f).parent) or ".")
                go_dirs.setdefault(d, []).append(f)
            for d, files in go_dirs.items():
                runs.append(_RunGroup(
                    argv=[go_bin, "test", "./" + d if d != "." else "./..."],
                    cwd=repo, files=files, kind="go",
                ))
    return runs, unrun


async def _exec(argv: list[str], cwd: str, logf: IO[bytes], timeout_sec: int) -> int | None:
    """Run a runner group. Returns exit code, ``None`` if it couldn't start, ``-1`` on timeout."""
    logf.write(f"\n[diff-tests] $ {' '.join(argv)}  (cwd={cwd})\n".encode())
    logf.flush()
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=cwd, stdout=logf, stderr=asyncio.subprocess.STDOUT, env=os.environ,
        )
    except (FileNotFoundError, OSError) as exc:
        logf.write(f"[diff-tests] runner could not start: {exc}\n".encode())
        return None
    try:
        return await asyncio.wait_for(proc.wait(), timeout=timeout_sec)
    except TimeoutError:
        with contextlib.suppress(Exception):
            proc.kill()
            await proc.wait()
        logf.write(b"[diff-tests] timeout - killed runner\n")
        return -1


def _classify(kind: str, rc: int | None) -> str:
    """Map a runner exit code to ``'ran' | 'failed' | 'unrun'``.

    pytest exit codes: 0=all pass, 1=tests failed, 5=no tests collected, 2/3/4=usage/
    internal — only ``1`` is a real test failure; the rest mean "couldn't run" → unrun,
    which avoids false-failing a task on an env/collection error.
    """
    if rc is None:
        return "unrun"
    if rc == -1:                   # timeout / killed — a hung test is broken
        return "failed"
    if kind == "py":
        return {0: "ran", 1: "failed"}.get(rc, "unrun")
    return "ran" if rc == 0 else "failed"


async def run_diff_tests(
    repo: str, base_ref: str, *, log_path: pathlib.Path, timeout_sec: int
) -> DiffTestResult:
    """Detect and run the test files this iteration touched. Output appended to *log_path*."""
    tests = changed_test_files(repo, base_ref)
    if not tests:
        return DiffTestResult(ok=True, ran=[], failed=[], unrun=[], log_path=log_path)
    runs, unrun = _plan_runs(repo, tests)
    ran: list[str] = []
    failed: list[str] = []
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as logf:
        for g in runs:
            verdict = _classify(g.kind, await _exec(g.argv, g.cwd, logf, timeout_sec))
            if verdict == "ran":
                ran.extend(g.files)
            elif verdict == "failed":
                failed.extend(g.files)
            else:
                unrun.extend(g.files)
    return DiffTestResult(ok=not failed, ran=ran, failed=failed, unrun=unrun, log_path=log_path)
