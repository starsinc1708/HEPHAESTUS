"""Base abstractions for HEPHAESTUS integration providers."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ProviderCapabilities(BaseModel):
    """Declares what operations a provider supports."""

    model_config = {"populate_by_name": True}

    issues: bool = False
    pull_requests: bool = Field(False, alias="pullRequests")


@runtime_checkable
class IntegrationProvider(Protocol):
    """Structural protocol every integration adapter must satisfy."""

    name: str

    def available(self) -> bool:
        """Return True when this provider's tooling/credentials are present."""
        ...

    def capabilities(self) -> ProviderCapabilities:
        """Return the set of capabilities this provider supports."""
        ...

    def list_issues(
        self,
        *,
        labels: list[str] | None = None,
        state: str = "open",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List issues from the provider."""
        ...

    def import_to_queue(self, *, label: str) -> dict[str, Any]:
        """Import issues matching *label* into the HEPHAESTUS work queue."""
        ...

    def sync_status(self, item: dict[str, Any]) -> None:
        """Push the current task status back to the provider issue."""
        ...

    def create_pr(
        self,
        branch: str,
        *,
        title: str,
        body: str,
        base: str,
    ) -> dict[str, Any] | None:
        """Create a pull request for *branch*. Returns ``{number, url}`` or None."""
        ...
