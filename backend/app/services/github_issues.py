"""GitHub Issues integration for HEPHAESTUS — uses gh CLI for API calls."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from typing import Any, cast

from app.core.helpers import _active_git, _run
from app.services.integrations.base import ProviderCapabilities
from app.services.integrations.creds import effective_token

log = logging.getLogger("hephaestus.backend.github_issues")

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubIssuesService:
    """GitHub Issues integration via ``gh`` CLI (subprocess). No PyGithub dependency."""

    def __init__(self, repo_full_name: str | None = None) -> None:
        self.repo = repo_full_name or self._detect_repo()

    # ------------------------------------------------------------------
    # Repo detection
    # ------------------------------------------------------------------

    def _detect_repo(self) -> str:
        """Detect *owner/repo* from ``git remote`` in the ACTIVE workspace. Falls back to dir name."""
        repo_path = _active_git()[0]
        url = _run(["git", "remote", "get-url", "origin"], cwd=repo_path or None)
        if url:
            parsed = self._parse_remote_url(url)
            if parsed:
                return parsed
        log.warning("Could not detect repo from git remote; using workspace dir name")
        return repo_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if repo_path else ""

    @staticmethod
    def _parse_remote_url(url: str) -> str | None:
        """Parse a git remote URL into *owner/repo* format."""
        # SSH: git@github.com:owner/repo.git
        m = re.match(r"(?:git@[^:]+:|https?://[^/]+/)([^/]+/[^/]+?)(?:\.git)?$", url)
        if m:
            return m.group(1)
        return None

    # ------------------------------------------------------------------
    # gh CLI wrapper with retry
    # ------------------------------------------------------------------

    def _gh(self, args: list[str], input_data: str | None = None) -> dict[str, Any] | list[Any] | None:
        """Run a ``gh`` CLI command, return parsed JSON. Raises on failure."""
        cmd = ["gh", *args, "--repo", self.repo]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                input=input_data,
                check=False,
                env=self._subprocess_env(),
            )
            if result.returncode != 0:
                log.error("gh %s failed (rc=%d): %s", " ".join(args), result.returncode, result.stderr.strip())
                return None
            stdout = result.stdout.strip()
            if not stdout:
                return None
            import json

            try:
                parsed: dict[str, Any] | list[Any] = json.loads(stdout)
                return parsed
            except json.JSONDecodeError:
                # Some gh commands (e.g. issue create without --json) return plain text.
                # If we expected JSON but got text, return a generic dict with the raw output.
                log.warning("gh %s returned non-JSON, treating as plain text", " ".join(args))
                return {"url": stdout} if stdout else None
        except subprocess.TimeoutExpired:
            log.error("gh %s timed out", " ".join(args))
            return None
        except FileNotFoundError:
            log.error("gh CLI not found — install GitHub CLI and authenticate")
            return None
        except (TypeError, OSError) as exc:
            log.error("gh %s failed (system error): %s", " ".join(args), exc)
            return None

    def _gh_with_retry(self, args: list[str], max_retries: int = 3) -> dict[str, Any] | list[Any] | None:
        """Run ``gh`` with exponential backoff retry on failure."""
        for attempt in range(max_retries):
            result = self._gh(args)
            if result is not None:
                return result
            if attempt < max_retries - 1:
                backoff = 2 ** attempt  # 1s, 2s
                log.warning("gh retry %d/%d (waiting %ds): %s", attempt + 1, max_retries, backoff, args)
                time.sleep(backoff)
        return self._gh(args)  # final attempt

    # ------------------------------------------------------------------
    # Provider API
    # ------------------------------------------------------------------

    def _subprocess_env(self) -> dict[str, str] | None:
        """Inherit the process env, injecting the stored PAT as ``GH_TOKEN``.

        The ``gh`` CLI authenticates with ``GH_TOKEN`` over any logged-in
        account, so import/PR actions use the UI-connected credential.
        """
        tok = effective_token("github")
        if not tok:
            return None
        return {**os.environ, "GH_TOKEN": tok}

    def available(self) -> bool:
        """Return True when a GitHub token has been connected in the UI."""
        return effective_token("github") is not None

    def capabilities(self) -> ProviderCapabilities:
        """GitHub supports issues and pull requests."""
        return ProviderCapabilities(issues=True, pull_requests=True)

    def create_pr(
        self,
        branch: str,
        *,
        title: str,
        body: str,
        base: str,
    ) -> dict[str, Any] | None:
        """Push *branch* and open a pull request. Returns ``{number, url}`` or None."""
        if not self.available():
            return None
        repo_path = _active_git()[0]
        _run(["git", "push", "-u", "origin", branch], cwd=repo_path or None)
        result = self._gh(
            [
                "pr",
                "create",
                "--head",
                branch,
                "--base",
                base,
                "--title",
                title,
                "--body",
                body,
                "--json",
                "number,url",
            ]
        )
        if isinstance(result, dict):
            return result
        return None

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def list_issues(
        self,
        labels: list[str] | str | None = None,
        state: str | None = "open",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List issues. Returns ``[{number, title, state, labels, body, created_at, updated_at}]``."""
        args = [
            "issue",
            "list",
            "--state",
            state or "open",
            "--limit",
            str(limit),
            "--json",
            "number,title,state,labels,body,createdAt,updatedAt",
        ]
        if labels:
            label_list: list[str] = labels.split(",") if isinstance(labels, str) else labels
            for lbl in label_list:
                args += ["--label", lbl.strip()]
        result = self._gh_with_retry(args)
        return result if isinstance(result, list) else []

    def get_issue(self, number: int) -> dict[str, Any] | None:
        """Get single issue details with comments."""
        return cast(
            "dict[str, Any] | None",
            self._gh(
                [
                    "issue",
                    "view",
                    str(number),
                    "--json",
                    "number,title,body,state,labels,comments",
                ]
            ),
        )

    def create_issue(self, title: str, body: str, labels: list[str] | None = None) -> dict[str, Any] | None:
        """Create an issue. Returns ``{number, url}``."""
        args = ["issue", "create", "--title", title, "--body", body, "--json", "number,url"]
        if labels:
            for lbl in labels:
                args += ["--label", lbl]
        return cast("dict[str, Any] | None", self._gh(args))

    def update_issue(
        self,
        number: int,
        *,
        add_labels: list[str] | None = None,
        remove_labels: list[str] | None = None,
        state: str | None = None,
        title: str | None = None,
        body: str | None = None,
    ) -> dict[str, Any] | None:
        """Update issue labels/state/title/body."""
        # Handle state change via close/reopen
        if state in ("closed",):
            self._gh(["issue", "close", str(number)])
        elif state in ("open",):
            self._gh(["issue", "reopen", str(number)])

        args = ["issue", "edit", str(number)]
        if title:
            args += ["--title", title]
        if body:
            args += ["--body", body]
        if add_labels:
            for lbl in add_labels:
                args += ["--add-label", lbl]
        if remove_labels:
            for lbl in remove_labels:
                args += ["--remove-label", lbl]
        if len(args) > 3:  # more than just "issue edit NUMBER"
            return cast("dict[str, Any] | None", self._gh(args))
        return {"ok": True, "number": number}

    def add_comment(self, number: int, body: str) -> dict[str, Any] | None:
        """Add comment to issue."""
        return cast(
            "dict[str, Any] | None",
            self._gh(
                [
                    "issue",
                    "comment",
                    str(number),
                    "--body",
                    body,
                ]
            ),
        )

    def get_comments(self, number: int) -> list[dict[str, Any]]:
        """Get issue comments."""
        data = self._gh(
            [
                "issue",
                "view",
                str(number),
                "--json",
                "comments",
            ]
        )
        if isinstance(data, dict):
            comments: list[dict[str, Any]] = data.get("comments", [])
            return comments
        return []

    # ------------------------------------------------------------------
    # HEPHAESTUS integration
    # ------------------------------------------------------------------

    def sync_to_queue(self, label_prefix: str = "hephaestus") -> dict[str, Any]:
        """Import open issues with ``hephaestus:pending`` label as tasks into work queue.

        Returns ``{added: [ids], skipped: [ids], errors: [msgs]}``.
        """
        from app.core.queue import _queue_add

        added: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []

        issues = self.list_issues(labels=[f"{label_prefix}:pending"], state="open")
        for issue in issues:
            number = issue.get("number")
            if number is None:
                continue
            qid = f"gh-{number}"
            try:
                result = _queue_add(
                    {
                        "id": qid,
                        "title": issue.get("title", f"GitHub Issue #{number}"),
                        "proposal": issue.get("body", ""),
                        "plan_file": "GITHUB-ISSUE",
                        "wave": "ISSUE",
                        "source_issue": number,
                    }
                )
                if result.get("ok"):
                    # Relabel: queued, remove pending
                    self.update_issue(
                        number,
                        add_labels=[f"{label_prefix}:queued"],
                        remove_labels=[f"{label_prefix}:pending"],
                    )
                    added.append(qid)
                else:
                    skipped.append(qid)
            except Exception as exc:
                errors.append(f"gh-{number}: {exc}")
                log.error("Failed to sync issue #%d: %s", number, exc)

        return {"added": added, "skipped": skipped, "errors": errors}

    def sync_status_to_issue(self, item: dict[str, Any]) -> None:
        """Update issue labels and add comment based on task status."""
        issue_number = item.get("source_issue")
        if not issue_number:
            return

        status = item.get("status", "pending")
        label_map: dict[str, str] = {
            "pending": "hephaestus:pending",
            "in_progress": "hephaestus:in-progress",
            "done": "hephaestus:done",
            "merged": "hephaestus:merged",
            "needs_revision": "hephaestus:needs-revision",
        }
        target_label = label_map.get(status)
        if status.startswith("failed"):
            target_label = "hephaestus:failed"

        if target_label:
            self.update_issue(
                int(issue_number),
                add_labels=[target_label],
            )

        # Close issue on merge
        if status == "merged":
            self.update_issue(int(issue_number), state="closed")
            self.add_comment(int(issue_number), f"✅ HEPHAESTUS: Task merged — branch `{item.get('branch', '?')}`")

        # Comment on failure
        if status.startswith("failed"):
            self.add_comment(
                int(issue_number),
                f"⚠️ HEPHAESTUS: Task failed — `{status}`",
            )

        # Comment on progress
        if status == "in_progress":
            branch = item.get("branch")
            msg = "🔄 HEPHAESTUS: Task in progress"
            if branch:
                msg += f" on branch `{branch}`"
            self.add_comment(int(issue_number), msg)

    def create_from_task(self, item: dict[str, Any]) -> dict[str, Any] | None:
        """Create a GitHub issue from a task item. Returns ``{number, url}`` or ``None``."""
        title = item.get("title", "Untitled HEPHAESTUS task")
        parts: list[str] = []
        if item.get("proposal"):
            parts.append(f"## Proposal\n\n{item['proposal']}")
        if item.get("why"):
            parts.append(f"## Why\n\n{item['why']}")
        if item.get("acceptance"):
            parts.append(f"## Acceptance Criteria\n\n{item['acceptance']}")
        if item.get("touches"):
            parts.append("## Files to Touch\n\n" + "\n".join(f"- `{t}`" for t in item["touches"]))
        body = "\n\n---\n\n".join(parts) if parts else "Auto-created by HEPHAESTUS"

        result = self.create_issue(title, body, labels=["hephaestus:pending"])
        if result and result.get("number"):
            return {"number": result["number"], "url": result.get("url", "")}
        return None

    def get_memory(self, issue_number: int) -> list[dict[str, Any]]:
        """Get issue comments as memory/context for the agent.

        Returns ``[{author, created_at, body}]``.
        """
        comments = self.get_comments(issue_number)
        memory: list[dict[str, Any]] = []
        for c in comments:
            memory.append(
                {
                    "author": c.get("author", {}).get("login", "unknown"),
                    "created_at": c.get("createdAt", ""),
                    "body": c.get("body", ""),
                }
            )
        return memory
