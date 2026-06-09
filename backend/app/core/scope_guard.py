"""Scope-guard: prevent agents from committing files outside item.touches (Improvement 1).

Reuses the subset-guard pattern from merge_job.py §4.6."""
from __future__ import annotations

import fnmatch
import logging
import subprocess
from dataclasses import dataclass, field

from app.models.workspace import ScopeGuardMode

log = logging.getLogger("hephaestus.core.scope_guard")

# Lock/generated files auto-excluded from scope violations
_AUTO_EXCLUDE = frozenset({
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "uv.lock", "poetry.lock", "Cargo.lock", "go.sum",
    "Pipfile.lock", "composer.lock",
})


@dataclass
class ScopeCheckResult:
    ok: bool
    extra_files: list[str] = field(default_factory=list)
    detail: str = ""


def _changed_files(repo_cwd: str, base_ref: str, branch: str) -> set[str]:
    """All files the agent touched: committed-since-base UNION the working tree.

    A committed-only ``git diff base..branch`` misses everything when the agent leaves
    its changes for the FSM to commit (the common path) — making the guard a silent
    no-op exactly when it should bite. So we also read the working tree via
    ``git status --porcelain -uall`` (staged/unstaged + NEW untracked files). Paths are
    normalised to forward slashes (git already emits POSIX paths; defensive on Windows)."""
    changed: set[str] = set()
    committed = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}..{branch}"],
        cwd=repo_cwd, capture_output=True, text=True, timeout=30,
    )
    for ln in committed.stdout.splitlines():
        if ln.strip():
            changed.add(ln.strip().replace("\\", "/"))
    status = subprocess.run(
        ["git", "status", "--porcelain", "-uall"],
        cwd=repo_cwd, capture_output=True, text=True, timeout=30,
    )
    for ln in status.stdout.splitlines():
        if len(ln) < 4:
            continue
        p = ln[3:].strip()
        if " -> " in p:                       # rename: "old -> new"
            p = p.split(" -> ", 1)[1]
        p = p.strip().strip('"')
        if p:
            changed.add(p.replace("\\", "/"))
    return changed


def check_scope(
    repo_cwd: str,
    base_ref: str,
    branch: str,
    touches: list[str],
    mode: ScopeGuardMode,
) -> ScopeCheckResult:
    """Compare git changed files against item.touches.

    - OFF: always ok=True, no analysis
    - ADVISORY: ok=True but extra_files populated
    - STRICT: ok=False when extra_files non-empty
    
    When touches is empty, always passes (no restriction declared).
    Lock/generated files are auto-excluded.
    """
    if mode is ScopeGuardMode.OFF:
        return ScopeCheckResult(ok=True, detail="scope-guard off")
    
    if not touches:
        return ScopeCheckResult(ok=True, detail="no touches declared; skipping scope check")
    
    # Get changed files (committed + working tree, incl. untracked)
    try:
        changed = _changed_files(repo_cwd, base_ref, branch)
    except Exception as exc:
        log.warning("scope-guard: git inspection failed: %s", exc)
        return ScopeCheckResult(ok=True, detail=f"git inspection failed: {exc}")

    if not changed:
        return ScopeCheckResult(ok=True, detail="no changed files")

    # Build allowed set from touches (support globs). Normalise backslashes so a
    # Windows-authored touch like `src\foo.py` matches git's forward-slash output.
    allowed: set[str] = set()
    for raw in touches:
        pattern = raw.replace("\\", "/")
        if any(c in pattern for c in "*?["):
            # Glob pattern: match against changed files
            for f in changed:
                if fnmatch.fnmatch(f, pattern):
                    allowed.add(f)
        else:
            allowed.add(pattern)
    
    # Auto-exclude lock files
    extra = sorted(
        f for f in (changed - allowed)
        if f.split("/")[-1] not in _AUTO_EXCLUDE
    )
    
    if not extra:
        return ScopeCheckResult(ok=True, detail=f"{len(changed)} file(s), all in scope")
    
    detail = f"{len(extra)} file(s) outside touches: {', '.join(extra[:10])}"
    if mode is ScopeGuardMode.STRICT:
        return ScopeCheckResult(ok=False, extra_files=extra, detail=detail)
    # ADVISORY
    return ScopeCheckResult(ok=True, extra_files=extra, detail=detail)
