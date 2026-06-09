"""Git branch introspection and branch actions — ported from dashboard/server.py:633-656, 1435-1565.

Read-only git queries (branches, commits), safety validation, and
the merge / requeue / discard actions that operate on auto/* branches.
"""

from __future__ import annotations

import logging
import os
import pathlib
import re
import subprocess
import sys
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from app.core.decisions import _append_decision
from app.core.helpers import _active_git, _load_json, _run
from app.core.state import _read_state, _state_dir, _StateLock, _write_state

if TYPE_CHECKING:
    from app.models.workspace import RepoProfile

log = logging.getLogger("hephaestus.backend.git")

_BRANCH_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,200}$")


# ---------- git introspection ----------


def _git_branches() -> list[dict[str, Any]]:
    repo, base, remote, prefix = _active_git()
    raw = _run(
        [
            "git",
            "for-each-ref",
            "--sort=-committerdate",
            "--format=%(refname:short)|%(committerdate:iso8601)|%(subject)|%(objectname:short)",
            f"refs/heads/{prefix}/",
        ],
        cwd=repo,
    )
    branches: list[dict[str, Any]] = []
    if raw:
        for line in raw.splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4:
                name, ts, subj, sha = parts
                ahead = _run(
                    ["git", "rev-list", "--count", f"{remote}/{base}..{name}"],
                    cwd=repo,
                    default="?",
                )
                branches.append({"name": name, "lastCommitAt": ts, "subject": subj, "sha": sha, "ahead": ahead})
    return branches


def _git_recent_commits() -> list[dict[str, Any]]:
    repo, _base, _remote, _prefix = _active_git()
    raw = _run(
        ["git", "log", "--all", "-n", "20", "--pretty=format:%h|%an|%ad|%s", "--date=iso8601"],
        cwd=repo,
    )
    commits: list[dict[str, Any]] = []
    for line in raw.splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4:
            sha, author, ts, msg = parts
            commits.append({"sha": sha, "author": author, "ts": ts, "subject": msg})
    return commits


# ---------- branch actions ----------


def _is_safe_auto_branch(name: str) -> bool:
    """Strict: only auto/<safe-chars> branches. Rejects --flag-like, traversal,
    whitespace, control chars, NUL. Length capped."""
    if not name or not isinstance(name, str):
        return False
    if ".." in name or "//" in name:
        return False
    if name.startswith("-"):
        return False
    if any(c in name for c in "\n\r\t \x00\\"):
        return False
    prefix = _active_git()[3]
    if not name.startswith(prefix + "/"):
        return False
    rest = name[len(prefix) + 1 :]
    if not rest or rest.startswith("-"):
        return False
    return bool(_BRANCH_NAME_RE.match(name))


def _branch_exists(name: str) -> bool:
    return bool(_run(["git", "rev-parse", "--verify", "refs/heads/" + name], cwd=_active_git()[0]))


def _driver_busy_on(branch: str) -> bool:
    cur = cast("dict[str, Any]", _load_json(_state_dir() / "current.json") or {})
    if cur.get("phase") in (None, "idle"):
        return False
    item_id = cur.get("itemId")
    if not item_id:
        return False
    return any(it.get("id") == item_id and it.get("branch") == branch for it in _read_state().get("items", []))


def _update_item_by_branch(branch: str, status: str, extra: dict[str, Any] | None = None) -> None:
    with _StateLock():
        s = _read_state()
        for it in s.get("items", []):
            if it.get("branch") == branch:
                it["status"] = status
                if extra:
                    it.update(extra)
        _write_state(s)


def _action_merge(name: str) -> dict[str, Any]:
    if not _is_safe_auto_branch(name):
        _append_decision("human", "merge", name, "rejected", "not an auto/ branch")
        return {"ok": False, "error": "not an auto/ branch"}
    if not _branch_exists(name):
        _append_decision("human", "merge", name, "rejected", "branch not found")
        return {"ok": False, "error": "branch not found"}
    if _driver_busy_on(name):
        _append_decision("human", "merge", name, "rejected", "driver busy")
        return {"ok": False, "error": "driver is mid-iter on this item — wait"}
    repo, base, remote, _prefix = _active_git()
    msg = _run(["git", "log", "-1", "--pretty=%s", name], cwd=repo) or f"merge {name}"
    try:
        co = subprocess.run(
            ["git", "checkout", base], cwd=repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"checkout {base} timed out"}
    if co.returncode != 0:
        _append_decision("human", "merge", name, "failed", co.stderr.strip()[:200])
        return {"ok": False, "error": f"checkout {base}: {co.stderr.strip()}"}
    try:
        subprocess.run(
            ["git", "pull", "--ff-only", remote, base], cwd=repo, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "pull timed out"}
    try:
        m = subprocess.run(
            ["git", "merge", "--no-ff", "--no-edit", "-m", f"merge: {msg} (from {name})", name],
            cwd=repo,
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "merge timed out"}
    if m.returncode != 0:
        subprocess.run(
            ["git", "merge", "--abort"], cwd=repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60,
        )
        _append_decision("human", "merge", name, "failed", m.stderr.strip()[:200])
        return {"ok": False, "error": f"merge failed (likely conflict): {m.stderr.strip()[:400]}"}
    new_sha = _run(["git", "rev-parse", "HEAD"], cwd=repo)
    # Push to remote BEFORE deleting the local branch — without this, a subsequent driver
    # `ensure_clean_base` ( `git reset --hard $REMOTE/$BASE_BRANCH` ) wipes our local merge,
    # because origin/main is still behind. Branch deletion + state-update only happen if
    # the push succeeds; on push failure the operator can retry without re-merging.
    try:
        push_result = subprocess.run(
            ["git", "push", remote, base],
            cwd=repo,
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"push to {remote}/{base} timed out"}
    push_note = "pushed"
    if push_result.returncode != 0:
        push_note = "push-failed"
        # Don't delete the branch — leave the merge commit reachable so operator can retry.
        _append_decision(
            "human",
            "merge",
            name,
            "merged-not-pushed",
            f"{new_sha[:10]} push_err={push_result.stderr.strip()[:200]}",
        )
        return {
            "ok": False,
            "action": "merge",
            "branch": name,
            "new_head": new_sha[:10],
            "error": (
                f"merged locally but push to {remote}/{base} failed — "
                f"driver may wipe it on next ensure_clean_base. "
                f"stderr: {push_result.stderr.strip()[:300]}"
            ),
        }
    subprocess.run(
        ["git", "branch", "-D", name], cwd=repo, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60,
    )
    _update_item_by_branch(name, "merged", {"merged_into": base, "merge_sha": new_sha, "push": push_note})
    _append_decision("human", "merge", name, "ok", f"{new_sha[:10]} {push_note}")
    return {"ok": True, "action": "merge", "branch": name, "new_head": new_sha[:10], "push": push_note}


def _action_requeue(name: str) -> dict[str, Any]:
    if not _is_safe_auto_branch(name):
        _append_decision("human", "requeue", name, "rejected", "not an auto/ branch")
        return {"ok": False, "error": "not an auto/ branch"}
    if _driver_busy_on(name):
        _append_decision("human", "requeue", name, "rejected", "driver busy")
        return {"ok": False, "error": "driver is mid-iter on this item — wait"}
    with _StateLock():
        s = _read_state()
        touched = False
        for it in s.get("items", []):
            if it.get("branch") == name:
                it["status"] = "pending"
                it.setdefault("previousBranches", []).append(name)
                it["branch"] = None
                it["requeued_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                touched = True
        _write_state(s)
    if not touched:
        _append_decision("human", "requeue", name, "rejected", "no matching item")
        return {"ok": False, "error": "no item references this branch in state"}
    _append_decision("human", "requeue", name, "ok", "branch retained")
    return {"ok": True, "action": "requeue", "branch": name}


def _action_discard(name: str) -> dict[str, Any]:
    if not _is_safe_auto_branch(name):
        _append_decision("human", "discard", name, "rejected", "not an auto/ branch")
        return {"ok": False, "error": "not an auto/ branch"}
    if _driver_busy_on(name):
        _append_decision("human", "discard", name, "rejected", "driver busy")
        return {"ok": False, "error": "driver is mid-iter on this item — wait"}
    if not _branch_exists(name):
        _append_decision("human", "discard", name, "rejected", "branch not found")
        return {"ok": False, "error": "branch not found"}
    repo, base, _remote, _prefix = _active_git()
    head = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    if head == name:
        co = subprocess.run(
            ["git", "checkout", base], cwd=repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60,
        )
        if co.returncode != 0:
            _append_decision("human", "discard", name, "failed", co.stderr.strip()[:200])
            return {"ok": False, "error": f"could not leave {name}: {co.stderr.strip()}"}
    d = subprocess.run(
        ["git", "branch", "-D", name], cwd=repo, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60,
    )
    if d.returncode != 0:
        _append_decision("human", "discard", name, "failed", d.stderr.strip()[:200])
        return {"ok": False, "error": f"branch -D failed: {d.stderr.strip()}"}
    _update_item_by_branch(name, "discarded")
    _append_decision("human", "discard", name, "ok", "")
    return {"ok": True, "action": "discard", "branch": name}


# ---------- worktree / ff-merge helpers (Epic 1: AI-powered merge) ----------


def _current_sha(repo: str, ref: str) -> str:
    return _run(["git", "rev-parse", ref], cwd=repo, default="")


# Gitignored dependency dirs that live ONLY in the main checkout but are needed by verify,
# which runs with cwd=<worktree>. A merge worktree has none of these, so verify there fails
# ("cannot find .venv\\Scripts\\python.exe" / npx can't resolve node_modules). We link them in.
_WORKTREE_DEP_DIRS = ("backend/.venv", "frontend/node_modules")


def _link_worktree_deps(repo: str, wt: str) -> None:
    """Junction (Windows) / symlink (POSIX) the gitignored dep dirs from the main checkout into
    the worktree so verify can run there. Best-effort: a missing source is skipped, and a failure
    just leaves verify to surface the missing dep as before."""
    for rel in _WORKTREE_DEP_DIRS:
        src = pathlib.Path(repo) / rel
        dst = pathlib.Path(wt) / rel
        if not src.is_dir() or dst.exists():
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if sys.platform.startswith("win"):
                # Directory junction — no admin needed, transparent to tools, and removable
                # with rmdir without following into the target.
                subprocess.run(["cmd", "/c", "mklink", "/J", str(dst), str(src)],
                               capture_output=True, text=True, timeout=30)
            else:
                os.symlink(src, dst, target_is_directory=True)
        except Exception:
            log.debug("link worktree dep failed: %s", rel, exc_info=True)


def _unlink_worktree_deps(wt: str) -> None:
    """Remove the dep links BEFORE git removes the worktree, so neither git nor any rmtree can
    follow a link into the real .venv / node_modules and delete it. Removing the link never
    touches the target: POSIX symlink → os.unlink; Windows junction (not a symlink) → os.rmdir
    removes the reparse point regardless of target contents."""
    for rel in _WORKTREE_DEP_DIRS:
        dst = pathlib.Path(wt) / rel
        try:
            if os.path.islink(dst):
                os.unlink(dst)
            elif dst.exists():
                os.rmdir(dst)
        except OSError:
            log.debug("unlink worktree dep failed: %s", rel, exc_info=True)


def _worktree_add(repo: str, wt: str, branch: str, start_ref: str) -> bool:
    subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=repo,
                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    r = subprocess.run(["git", "worktree", "add", "-b", branch, wt, start_ref], cwd=repo,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if r.returncode == 0:
        _link_worktree_deps(repo, wt)
    return r.returncode == 0


def _worktree_remove(repo: str, wt: str, branch: str | None = None) -> None:
    _unlink_worktree_deps(wt)
    subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=repo,
                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    subprocess.run(["git", "worktree", "prune"], cwd=repo,
                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if branch:
        subprocess.run(["git", "branch", "-D", branch], cwd=repo,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)


def _ff_merge(repo: str, branch: str, base: str) -> bool:
    co = subprocess.run(["git", "checkout", base], cwd=repo, capture_output=True,
                        text=True, encoding="utf-8", errors="replace", timeout=60)
    if co.returncode != 0:
        return False
    m = subprocess.run(["git", "merge", "--ff-only", branch], cwd=repo, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=60)
    return m.returncode == 0


BRANCH_ACTIONS: dict[str, Callable[[str], dict[str, Any]]] = {
    "merge": _action_merge,
    "requeue": _action_requeue,
    "discard": _action_discard,
}

# GitService + MergePreflight (E402 acceptable: must come after BRANCH_ACTIONS).
# R11: the single source of truth for the preflight shape is the validation model,
# which carries loop_active + camelCase aliases. Re-export under the legacy name.
from app.models.validation import MergePreflightResponse as MergePreflight  # noqa: E402


class GitService:
    """Workspace-scoped git ops (umbrella §5.4). Merge bodies land in Stage 3."""

    def __init__(self, ws: RepoProfile) -> None:
        self.ws = ws

    def branches(self) -> list[dict[str, Any]]:
        raw = _run(
            [
                "git",
                "for-each-ref",
                "--sort=-committerdate",
                "--format=%(refname:short)|%(committerdate:iso8601)|%(subject)|%(objectname:short)",
                f"refs/heads/{self.ws.branch_prefix}/",
            ],
            cwd=self.ws.repo_path,
        )
        out: list[dict[str, Any]] = []
        for line in (raw or "").splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4:
                name, ts, subj, sha = parts
                ahead = _run(
                    ["git", "rev-list", "--count", f"{self.ws.remote}/{self.ws.base_branch}..{name}"],
                    cwd=self.ws.repo_path,
                    default="?",
                )
                out.append({"name": name, "lastCommitAt": ts, "subject": subj, "sha": sha, "ahead": ahead})
        return out

    def create_branch(self, name: str) -> bool:
        return bool(
            _run(
                ["git", "checkout", "-b", name, f"{self.ws.remote}/{self.ws.base_branch}"],
                cwd=self.ws.repo_path,
            )
        )

    def commit(self, msg: str) -> str | None:
        _run(["git", "add", "-A"], cwd=self.ws.repo_path)
        if not _run(["git", "diff", "--cached", "--stat"], cwd=self.ws.repo_path):
            return None
        _run(["git", "commit", "-m", msg], cwd=self.ws.repo_path)
        return _run(["git", "rev-parse", "--short", "HEAD"], cwd=self.ws.repo_path) or None

    def diff(self, branch: str) -> str:
        return _run(
            ["git", "diff", f"{self.ws.remote}/{self.ws.base_branch}..{branch}"],
            cwd=self.ws.repo_path,
            default="",
        )

    # ---- Stage 3 merge-preflight helpers (R11: persistent flags, no status heuristics) ----

    def _clean_tree(self) -> bool:
        return _run(["git", "status", "--porcelain"], cwd=self.ws.repo_path, default="\x00") == ""

    def _find_item_by_branch(self, branch: str) -> dict[str, Any] | None:
        for it in _read_state().get("items", []):
            if it.get("branch") == branch:
                item: dict[str, Any] = it
                return item
        return None

    def _last_verify_green(self, branch: str) -> bool:
        """R11: read the PERSISTENT item.verify_green flag (written by the FSM after a
        green verify). NOT a status-prefix heuristic. Missing item → False."""
        item = self._find_item_by_branch(branch)
        if item is None:
            return False
        return bool(item.get("verify_green") or item.get("verifyGreen"))

    def _verify_unverified(self, branch: str) -> bool:
        """Honest gate: True when verify ran NOTHING (no config + no test files in the
        diff), so verify_green is False not because a check failed but because none ran."""
        item = self._find_item_by_branch(branch)
        if item is None:
            return False
        return bool(item.get("verify_unverified") or item.get("verifyUnverified"))

    def _validation_passed(self, branch: str) -> bool:
        """R11: PERSISTENT item.validation.gate == 'pass'. Fallback: layer3/final.json."""
        item = self._find_item_by_branch(branch)
        if item is None:
            return False
        val = item.get("validation")
        if isinstance(val, dict):
            return val.get("gate") == "pass"
        last_iter = item.get("lastIter")
        if last_iter:
            fd = _state_dir() / last_iter / "validation" / "layer3" / "final.json"
            obj = _load_json(fd) or {}
            return isinstance(obj, dict) and obj.get("gate") == "pass"
        return False

    def _loop_active(self) -> bool:
        """R11: merge forbidden while the loop process is RUNNING (concurrent base writes)."""
        try:
            from app.core.process import ProcState, pm
        except ImportError:
            return False
        try:
            return pm.status("loop").state == ProcState.RUNNING
        except Exception:
            log.debug("_loop_active: failed to check loop status", exc_info=True)
            return False

    def merge_preflight(self, branch: str) -> MergePreflight:
        item = self._find_item_by_branch(branch)
        clean = self._clean_tree()
        verify = self._last_verify_green(branch)
        unverified = self._verify_unverified(branch)
        validation = self._validation_passed(branch)
        loop_active = self._loop_active()
        ok = (clean and verify and validation and not loop_active
              and item is not None and _is_safe_auto_branch(branch))
        return MergePreflight(
            clean_tree=clean, verify_green=verify, verify_unverified=unverified,
            validation_passed=validation, loop_active=loop_active,
            base_branch=self.ws.base_branch, conflicts=[], ok=ok,
        )

    async def merge_to_base(self, branch: str, *, push: bool) -> dict[str, Any]:
        repo = self.ws.repo_path
        base = self.ws.base_branch
        remote = self.ws.remote
        # R11: merge forbidden while the loop process is RUNNING (avoid concurrent base writes).
        if self._loop_active():
            return {"ok": False, "error": "loop active, stop it before merge"}
        # R11: Task not found by branch → explicit, surfaceable condition (router → 409), not silent.
        if self._find_item_by_branch(branch) is None:
            return {"ok": False, "error": f"no task found for branch {branch}"}
        pf = self.merge_preflight(branch)
        if not pf.ok:
            if not pf.clean_tree:
                return {"ok": False, "error": "working tree not clean",
                        "preflight": pf.model_dump(by_alias=True)}
            return {"ok": False, "error": "preflight failed",
                    "preflight": pf.model_dump(by_alias=True)}
        if _driver_busy_on(branch):
            return {"ok": False, "error": "driver is mid-iter on this item — wait"}
        msg = _run(["git", "log", "-1", "--pretty=%s", branch], cwd=repo) or f"merge {branch}"
        co = subprocess.run(["git", "checkout", base], cwd=repo,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        if co.returncode != 0:
            return {"ok": False, "error": f"checkout {base}: {co.stderr.strip()}"}
        # pull --ff-only is best-effort: a missing remote must not abort a local merge
        subprocess.run(["git", "pull", "--ff-only", remote, base], cwd=repo,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        m = subprocess.run(
            ["git", "merge", "--no-ff", "--no-edit", "-m", f"merge: {msg} (from {branch})", branch],
            cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        if m.returncode != 0:
            conflicts = _run(["git", "diff", "--name-only", "--diff-filter=U"],
                             cwd=repo).splitlines()
            subprocess.run(["git", "merge", "--abort"], cwd=repo,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            _append_decision("human", "merge", branch, "failed", "conflict")
            return {"ok": False, "conflicts": conflicts, "error": "merge conflict"}
        new_sha = _run(["git", "rev-parse", "HEAD"], cwd=repo)
        push_note = "not-pushed"
        if push:
            p = subprocess.run(["git", "push", remote, base], cwd=repo,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            if p.returncode != 0:
                _append_decision("human", "merge", branch, "merged-not-pushed",
                                 f"{new_sha[:10]} push_err={p.stderr.strip()[:200]}")
                return {"ok": False, "action": "merge", "branch": branch, "newHead": new_sha[:10],
                        "error": f"merged locally but push failed: {p.stderr.strip()[:300]}"}
            push_note = "pushed"
        subprocess.run(["git", "branch", "-D", branch], cwd=repo,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        _update_item_by_branch(branch, "merged",
                               {"merged_into": base, "merge_sha": new_sha, "push": push_note})
        _append_decision("human", "merge", branch, "ok", f"{new_sha[:10]} {push_note}")
        return {"ok": True, "action": "merge", "branch": branch, "newHead": new_sha[:10], "push": push_note}
