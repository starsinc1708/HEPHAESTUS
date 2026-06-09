"""GitHubProvider — IntegrationProvider adapter wrapping GitHubIssuesService."""

from __future__ import annotations

from typing import Any

from app.services.github_issues import GitHubIssuesService
from app.services.integrations.base import ProviderCapabilities


class GitHubProvider:
    """Thin adapter that makes GitHubIssuesService satisfy IntegrationProvider."""

    name: str = "github"

    def __init__(self, repo_full_name: str | None = None) -> None:
        self._svc = GitHubIssuesService(repo_full_name)

    # ------------------------------------------------------------------
    # IntegrationProvider protocol
    # ------------------------------------------------------------------

    def available(self) -> bool:
        return self._svc.available()

    def capabilities(self) -> ProviderCapabilities:
        return self._svc.capabilities()

    def list_issues(
        self,
        *,
        labels: list[str] | None = None,
        state: str = "open",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self._svc.list_issues(labels=labels, state=state, limit=limit)

    def import_to_queue(self, *, label: str) -> dict[str, Any]:
        """Import issues with *label* into the HEPHAESTUS queue.

        Derives the label_prefix from the part before ':' (if present).
        """
        prefix = label.split(":")[0] if ":" in label else label
        result: dict[str, Any] = self._svc.sync_to_queue(label_prefix=prefix)
        return result

    def sync_status(self, item: dict[str, Any]) -> None:
        self._svc.sync_status_to_issue(item)

    def create_pr(
        self,
        branch: str,
        *,
        title: str,
        body: str,
        base: str,
    ) -> dict[str, Any] | None:
        return self._svc.create_pr(branch, title=title, body=body, base=base)
