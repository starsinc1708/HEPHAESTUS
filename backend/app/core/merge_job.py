"""MergeJobStore, MergeJobRunner — Epic 1: AI-powered merge.

Task 3: MergeJobStore + merge-NNNN sequencing.
Task 6: MergeJobRunner.start (worktree → merge → resolve → verify → resolved).
Task 7: accept / reject / reaper.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import time
from typing import Any

from app.core.state import _atomic_write, _state_dir, _StateLock
from app.models.merge import MergeDecision, MergeJob, MergeJobStatus

_REGISTRY = "merge-jobs.json"
_MAX_KEEP = 50
# Terminal states AND awaiting-decision states that unblock a new merge:
# conflict = human must act, accepted/rejected/failed = done.
_TERMINAL = {"accepted", "rejected", "failed", "conflict"}


# ---------------------------------------------------------------------------
# Sequencing
# ---------------------------------------------------------------------------


def _next_merge_seq() -> int:
    """Return the next monotonically-increasing merge sequence number."""
    sd = _state_dir()
    nums: list[int] = []
    for p in sd.glob("merge-*"):
        part = p.name.split("-", 1)[1] if "-" in p.name else ""
        if p.is_dir() and part.isdigit():
            nums.append(int(part))
    return (max(nums) + 1) if nums else 1


# ---------------------------------------------------------------------------
# MergeJobStore
# ---------------------------------------------------------------------------


class MergeJobStore:
    """Persist MergeJob records as a rolling JSON registry in the state dir."""

    def _path(self) -> pathlib.Path:
        return _state_dir() / _REGISTRY

    def list(self) -> list[MergeJob]:
        p = self._path()
        if not p.exists():
            return []
        raw = json.loads(p.read_text(encoding="utf-8") or '{"jobs": []}')
        return [MergeJob.model_validate(j) for j in raw.get("jobs", [])]

    def get(self, job_id: str) -> MergeJob | None:
        return next((j for j in self.list() if j.id == job_id), None)

    def put(self, job: MergeJob) -> None:
        with _StateLock():
            jobs = [j for j in self.list() if j.id != job.id]
            jobs.append(job)
            jobs = jobs[-_MAX_KEEP:]
            payload = json.dumps(
                {"jobs": [j.model_dump(by_alias=True) for j in jobs]},
                indent=2,
                ensure_ascii=False,
            )
            self._path().parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(self._path(), payload)

    def active(self) -> MergeJob | None:
        """Return a job that blocks starting a new merge (non-terminal status).

        Terminal set = {accepted, rejected, failed, conflict}.
        A 'resolved' job is still active — it's awaiting accept/reject.
        """
        return next(
            (j for j in self.list() if j.status.value not in _TERMINAL),
            None,
        )


# ---------------------------------------------------------------------------
# MergeJobRunner
# ---------------------------------------------------------------------------


class MergeJobRunner:
    """Orchestrate a full merge lifecycle for a single auto/* branch."""

    def __init__(self, ws: Any, *, run_agent: object | None = None, verify: object | None = None) -> None:
        self.ws = ws
        self._run_agent = run_agent
        self._verify = verify  # injected or lazily created in start()
        self.store = MergeJobStore()

    def _now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _timeout(self) -> int:
        from app.config import MERGE_TIMEOUT_SEC

        return MERGE_TIMEOUT_SEC or self.ws.verify_timeout_sec

    def _over_limits(self, wt: str, conflicts: list[str]) -> bool:
        from app.config import MERGE_MAX_FILE_BYTES, MERGE_MAX_FILES

        if len(conflicts) > MERGE_MAX_FILES:
            return True
        for f in conflicts:
            p = pathlib.Path(wt) / f
            if p.exists() and p.stat().st_size > MERGE_MAX_FILE_BYTES:
                return True
        return False

    def _get_verify(self) -> Any:
        if self._verify is not None:
            return self._verify
        from app.core.verify import VerifyRunner

        return VerifyRunner(self.ws)

    async def start(
        self,
        *,
        branch: str,
        push: bool,
        ai_resolve: bool,
        auto_accept: bool,
    ) -> MergeJob:
        from app.core.git import (
            _current_sha,
            _worktree_add,
            _worktree_remove,
        )
        from app.core.helpers import _run
        from app.core.merge_resolver import MergeResolver, has_conflict_markers
        from app.core.state import _read_state

        repo: str = self.ws.repo_path
        base: str = self.ws.base_branch
        remote: str = self.ws.remote

        seq = _next_merge_seq()
        job_id = f"merge-{seq:04d}"
        job_dir = _state_dir() / job_id
        item = next(
            (it for it in _read_state().get("items", []) if it.get("branch") == branch),
            None,
        )
        wt = str(pathlib.Path(repo).parent / ".hephaestus-worktrees" / job_id)
        wt_branch = f"hephaestus/merge/{branch.split('/', 1)[-1]}"

        job = MergeJob(
            id=job_id,
            branch=branch,
            base_branch=base,
            status=MergeJobStatus.RUNNING,
            worktree=wt,
            worktree_branch=wt_branch,
            base_sha=_current_sha(repo, base),
            item_id=(item or {}).get("id"),
            push=push,
            auto_accept=auto_accept,
            created_at=self._now(),
            updated_at=self._now(),
        )
        self.store.put(job)

        def _fail(msg: str) -> MergeJob:
            _worktree_remove(repo, wt, wt_branch)
            job.status = MergeJobStatus.FAILED
            job.decision = MergeDecision.FAILED
            job.error = msg
            job.updated_at = self._now()
            self.store.put(job)
            return job

        _run(["git", "fetch", remote, base], cwd=repo)  # best effort
        if not _worktree_add(repo, wt, wt_branch, base):
            return _fail("worktree add failed")

        m = subprocess.run(
            ["git", "merge", "--no-ff", "--no-commit", branch],
            cwd=wt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        conflicts = [
            c
            for c in _run(["git", "diff", "--name-only", "--diff-filter=U"], cwd=wt).splitlines()
            if c
        ]

        if m.returncode == 0 and not conflicts:
            job.decision = MergeDecision.AUTO_MERGED
        else:
            if not ai_resolve or self._over_limits(wt, conflicts):
                subprocess.run(
                    ["git", "merge", "--abort"],
                    cwd=wt,
                    capture_output=True,
                    text=True,
                )
                _worktree_remove(repo, wt, wt_branch)
                job.status = MergeJobStatus.CONFLICT
                job.decision = MergeDecision.NEEDS_HUMAN
                job.conflicts = conflicts
                job.updated_at = self._now()
                self.store.put(job)
                return job

            job.status = MergeJobStatus.RESOLVING
            job.conflicts = conflicts
            self.store.put(job)

            outcome = await MergeResolver(self.ws, run_agent=self._run_agent).resolve(  # type: ignore[arg-type]
                worktree_cwd=wt,
                conflicts=conflicts,
                item=item or {},
                job_dir=job_dir,
                timeout_sec=self._timeout(),
            )
            if not outcome.ok:
                subprocess.run(
                    ["git", "merge", "--abort"],
                    cwd=wt,
                    capture_output=True,
                    text=True,
                )
                return _fail("resolver agent failed")

            # Stage the resolver's output so --diff-filter=U reflects the index correctly.
            _run(["git", "add", "-A"], cwd=wt)
            # §4.6 guard: the resolver may only touch files within the merge scope
            # (files changed by either side since the merge-base). Anything else => abort.
            mb = _run(["git", "merge-base", base, branch], cwd=repo, default="").strip()
            allowed: set[str] = set()
            if mb:
                allowed |= {
                    f for f in _run(
                        ["git", "diff", "--name-only", f"{mb}..{branch}"], cwd=repo
                    ).splitlines() if f
                }
                allowed |= {
                    f for f in _run(
                        ["git", "diff", "--name-only", f"{mb}..{base}"], cwd=repo
                    ).splitlines() if f
                }
            changed = {
                f for f in _run(
                    ["git", "diff", "--cached", "--name-only"], cwd=wt
                ).splitlines() if f
            }
            extra = sorted(changed - allowed) if allowed else []
            if extra:
                subprocess.run(["git", "merge", "--abort"], cwd=wt, capture_output=True, text=True)
                return _fail(f"resolver touched out-of-scope files: {', '.join(extra[:10])}")
            still = [
                c
                for c in _run(
                    ["git", "diff", "--name-only", "--diff-filter=U"], cwd=wt
                ).splitlines()
                if c
            ]
            markers_left = any(
                has_conflict_markers(
                    (pathlib.Path(wt) / f).read_text(encoding="utf-8", errors="replace")
                )
                for f in conflicts
                if (pathlib.Path(wt) / f).exists()
            )
            if still or markers_left:
                subprocess.run(
                    ["git", "merge", "--abort"],
                    cwd=wt,
                    capture_output=True,
                    text=True,
                )
                return _fail("conflict markers remain after resolution")

            job.decision = MergeDecision.AI_MERGED
            job.resolved_files = conflicts

        subj = _run(["git", "log", "-1", "--pretty=%s", branch], cwd=repo) or f"merge {branch}"
        # AUTO_MERGED: `git merge --no-ff --no-commit` above already staged the FULL merge in
        # the index — do NOT `git add -A` here. That would also stage UNTRACKED working-tree
        # files (e.g. a `frontend/node_modules` symlink that `.gitignore`'s dir-pattern
        # `node_modules/` doesn't catch), polluting the merge commit and breaking the later
        # fast-forward checkout. (The AI_MERGED path stages the resolver's edits above, guarded
        # by the out-of-scope check.) Just commit the already-staged merge.
        subprocess.run(
            ["git", "commit", "--no-edit", "-m", f"merge: {subj} (from {branch})"],
            cwd=wt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )

        job.status = MergeJobStatus.VERIFYING
        self.store.put(job)

        verify_runner = self._get_verify()
        vres = await verify_runner.run(
            cwd=wt,
            log_path=job_dir / "verify.log",
            timeout_sec=self._timeout(),
        )
        job.verify_ok = vres.ok
        if not vres.ok:
            return _fail("verify failed on merged tree")

        diff = _run(["git", "diff", f"{base}..{wt_branch}"], cwd=wt, default="")
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "merge.diff").write_text(diff, encoding="utf-8")
        job.diff = diff[:65536]
        job.status = MergeJobStatus.RESOLVED
        job.updated_at = self._now()
        self.store.put(job)

        if (
            auto_accept
            and job.verify_ok
            and job.decision in (MergeDecision.AUTO_MERGED, MergeDecision.AI_MERGED)
        ):
            await self.accept(job_id, push=push)
            refreshed = self.store.get(job_id)
            return refreshed if refreshed is not None else job

        return job

    async def accept(self, job_id: str, *, push: bool) -> dict[str, object]:
        from app.core.git import (
            GitService,
            _current_sha,
            _ff_merge,
            _update_item_by_branch,
            _worktree_remove,
        )
        from app.core.helpers import _run

        job = self.store.get(job_id)
        if job is None or job.status is not MergeJobStatus.RESOLVED:
            return {"ok": False, "error": "job not in resolved state"}

        repo: str = self.ws.repo_path
        base: str = self.ws.base_branch
        remote: str = self.ws.remote

        if GitService(self.ws)._loop_active():
            return {"ok": False, "error": "loop active, stop it before merge"}

        if _current_sha(repo, base) != job.base_sha:
            return {"ok": False, "error": "base moved, reject and re-run merge"}

        if not _ff_merge(repo, job.worktree_branch or "", base):
            return {"ok": False, "error": "fast-forward into base failed"}

        push_note = "not-pushed"
        if push:
            p = subprocess.run(
                ["git", "push", remote, base],
                cwd=repo,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            if p.returncode != 0:
                return {
                    "ok": False,
                    "error": f"merged locally but push failed: {p.stderr.strip()[:300]}",
                }
            push_note = "pushed"

        new_sha = _current_sha(repo, base)
        _worktree_remove(repo, job.worktree or "", job.worktree_branch)
        _run(["git", "branch", "-D", job.branch], cwd=repo)

        resolution = "ai" if job.decision is MergeDecision.AI_MERGED else "auto"
        _update_item_by_branch(
            job.branch,
            "merged",
            {
                "merged_into": base,
                "merge_sha": new_sha,
                "push": push_note,
                "mergeResolution": resolution,
            },
        )
        from app.core.decisions import _append_decision

        _append_decision(
            "human",
            "merge",
            job.branch,
            "ok",
            f"{new_sha[:10]} {push_note} ({resolution})",
        )

        job.status = MergeJobStatus.ACCEPTED
        job.updated_at = self._now()
        self.store.put(job)

        return {
            "ok": True,
            "branch": job.branch,
            "newHead": new_sha[:10],
            "push": push_note,
        }

    async def reject(self, job_id: str) -> dict[str, object]:
        from app.core.decisions import _append_decision
        from app.core.git import _worktree_remove

        job = self.store.get(job_id)
        if job is None:
            return {"ok": False, "error": "job not found"}
        if job.status is not MergeJobStatus.RESOLVED:
            return {"ok": False, "error": "job not in resolved state"}

        _worktree_remove(self.ws.repo_path, job.worktree or "", job.worktree_branch)
        job.status = MergeJobStatus.REJECTED
        job.updated_at = self._now()
        self.store.put(job)
        _append_decision("human", "merge", job.branch, "rejected", "ai-merge discarded")
        return {"ok": True}

    def reap(self) -> None:
        """Mark orphaned in-flight jobs as FAILED and clean up their worktrees.

        Called at startup to recover from a crashed/restarted process.
        Any job still in RUNNING/RESOLVING/VERIFYING was interrupted mid-flight.
        """
        from app.core.git import _worktree_remove

        for job in self.store.list():
            if job.status in (
                MergeJobStatus.RUNNING,
                MergeJobStatus.RESOLVING,
                MergeJobStatus.VERIFYING,
            ):
                if job.worktree:
                    _worktree_remove(self.ws.repo_path, job.worktree, job.worktree_branch)
                job.status = MergeJobStatus.FAILED
                job.error = "orphaned by restart"
                self.store.put(job)
