"""GitLab integration for HEPHAESTUS — uses glab CLI for API calls."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from typing import Any

from app.core.helpers import _active_git, _run
from app.services.integrations.base import ProviderCapabilities
from app.services.integrations.creds import effective_host, effective_token

log = logging.getLogger("hephaestus.backend.gitlab_service")

name: str = "gitlab"


class GitLabService:
    """GitLab integration via ``glab`` CLI (subprocess). Mirrors GitHubIssuesService shape."""

    name: str = "gitlab"

    def __init__(self, project: str | None = None) -> None:
        self.project = project or self._detect_project()

    # ------------------------------------------------------------------
    # Project detection
    # ------------------------------------------------------------------

    def _detect_project(self) -> str:
        """Detect *group/project* from ``git remote`` in the active workspace."""
        repo_path = _active_git()[0]
        url = _run(["git", "remote", "get-url", "origin"], cwd=repo_path or None)
        if url and self._is_gitlab_remote(url):
            parsed = self._parse_remote_url(url)
            if parsed:
                return parsed
        log.warning("Could not detect GitLab project from git remote; using empty string")
        return ""

    @staticmethod
    def _is_gitlab_remote(url: str) -> bool:
        """Return True if the remote URL points to a GitLab host."""
        return "gitlab" in url.lower()

    @staticmethod
    def _parse_remote_url(url: str) -> str | None:
        """Parse a git remote URL into *group/project* format."""
        m = re.match(r"(?:git@[^:]+:|https?://[^/]+/)(.+?)(?:\.git)?$", url)
        if m:
            return m.group(1)
        return None

    # ------------------------------------------------------------------
    # glab CLI wrapper
    # ------------------------------------------------------------------

    def _glab(self, args: list[str]) -> dict[str, Any] | list[Any] | None:
        """Run a ``glab`` CLI command, return parsed JSON. Never raises."""
        cmd = ["glab", *args]
        if self.project:
            cmd = cmd + ["--repo", self.project]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
                env=self._subprocess_env(),
            )
            if result.returncode != 0:
                log.error(
                    "glab %s failed (rc=%d): %s",
                    " ".join(args),
                    result.returncode,
                    result.stderr.strip(),
                )
                return None
            stdout = result.stdout.strip()
            if not stdout:
                return None
            try:
                parsed: dict[str, Any] | list[Any] = json.loads(stdout)
                return parsed
            except json.JSONDecodeError:
                log.warning("glab %s returned non-JSON, treating as plain text", " ".join(args))
                return {"url": stdout} if stdout else None
        except subprocess.TimeoutExpired:
            log.error("glab %s timed out", " ".join(args))
            return None
        except FileNotFoundError:
            log.error("glab CLI not found — install GitLab CLI and authenticate")
            return None
        except (TypeError, OSError) as exc:
            log.error("glab %s failed (system error): %s", " ".join(args), exc)
            return None

    # ------------------------------------------------------------------
    # Provider API
    # ------------------------------------------------------------------

    def _subprocess_env(self) -> dict[str, str] | None:
        """Inherit the process env, injecting the stored PAT + host for ``glab``."""
        tok = effective_token("gitlab")
        if not tok:
            return None
        return {**os.environ, "GITLAB_TOKEN": tok, "GITLAB_HOST": effective_host("gitlab")}

    def available(self) -> bool:
        """Return True when a GitLab token has been connected in the UI."""
        return effective_token("gitlab") is not None

    def capabilities(self) -> ProviderCapabilities:
        """GitLab supports issues and pull requests (MRs)."""
        return ProviderCapabilities(issues=True, pull_requests=True)

    def list_issues(
        self,
        *,
        labels: list[str] | None = None,
        state: str = "open",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List issues. Returns list of dicts from glab."""
        args = [
            "issue",
            "list",
            "--state",
            state,
            "--per-page",
            str(limit),
            "--output",
            "json",
        ]
        if labels:
            for lbl in labels:
                args += ["--label", lbl.strip()]
        result = self._glab(args)
        return result if isinstance(result, list) else []

    def import_to_queue(self, *, label: str) -> dict[str, Any]:
        """Import labeled GitLab issues into the HEPHAESTUS work queue.

        Returns ``{added: [...], skipped: [...], errors: [...]}``.
        """
        from app.core.queue import _queue_add

        added: list[dict[str, Any]] = []
        skipped: list[str] = []
        errors: list[str] = []

        issues = self.list_issues(labels=[label])
        for issue in issues:
            iid = issue.get("iid")
            if iid is None:
                continue
            qid = f"gl-{iid}"
            try:
                item: dict[str, Any] = {
                    "id": qid,
                    "title": issue.get("title", f"GitLab Issue !{iid}"),
                    "proposal": issue.get("description", ""),
                    "source_issue": iid,
                    "source_provider": "gitlab",
                    "plan_file": "GITLAB-ISSUE",
                    "wave": "ISSUE",
                }
                result = _queue_add(item)
                if result.get("ok"):
                    added.append(item)
                else:
                    skipped.append(qid)
            except Exception as exc:
                errors.append(f"gl-{iid}: {exc}")
                log.error("Failed to sync GitLab issue #%s: %s", iid, exc)

        return {"added": added, "skipped": skipped, "errors": errors}

    def sync_status(self, item: dict[str, Any]) -> None:
        """Push the current task status back to the GitLab issue. Best-effort; never raises."""
        if item.get("source_provider") != "gitlab":
            return
        issue_iid = item.get("source_issue")
        if not issue_iid:
            return
        status = item.get("status", "pending")
        try:
            label_map: dict[str, str] = {
                "pending": "hephaestus:pending",
                "in_progress": "hephaestus:in-progress",
                "done": "hephaestus:done",
                "merged": "hephaestus:merged",
                "needs_revision": "hephaestus:needs-revision",
            }
            target_label = label_map.get(status, "hephaestus:pending")
            if status.startswith("failed"):
                target_label = "hephaestus:failed"
            self._glab(
                [
                    "issue",
                    "note",
                    str(issue_iid),
                    "--message",
                    f"HEPHAESTUS status: {status}",
                ]
            )
            self._glab(
                [
                    "issue",
                    "update",
                    str(issue_iid),
                    "--label",
                    target_label,
                ]
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("sync_status to GitLab issue %s failed: %s", issue_iid, exc)

    def create_pr(
        self,
        branch: str,
        *,
        title: str,
        body: str,
        base: str,
    ) -> dict[str, Any] | None:
        """Push *branch* and open a merge request. Returns ``{number, url}`` or None."""
        if not self.available():
            return None
        repo_path = _active_git()[0]
        _run(["git", "push", "-u", "origin", branch], cwd=repo_path or None)
        result = self._glab(
            [
                "mr",
                "create",
                "--source-branch",
                branch,
                "--target-branch",
                base,
                "--title",
                title,
                "--description",
                body,
                "--output",
                "json",
            ]
        )
        if isinstance(result, dict):
            iid = result.get("iid")
            web_url = result.get("web_url", "")
            return {"number": iid, "url": web_url}
        return None
