"""Provider registry — discovers and returns available integration providers."""

from __future__ import annotations

import logging

from app.services.integrations.base import IntegrationProvider

log = logging.getLogger("hephaestus.backend.integrations.registry")


def provider_registry() -> dict[str, IntegrationProvider]:
    """Return a dict of name -> provider for every available provider.

    Provider construction is guarded with try/except so a missing or broken
    module never prevents other providers from loading.
    """
    providers: dict[str, IntegrationProvider] = {}

    # GitHub — available once a PAT has been connected in the UI
    try:
        from app.services.integrations.github_provider import GitHubProvider

        gh = GitHubProvider()
        if gh.available():
            providers["github"] = gh
    except Exception:  # noqa: BLE001
        log.debug("GitHub provider unavailable", exc_info=True)

    # GitLab — available once a PAT has been connected in the UI
    try:
        from app.services.integrations.gitlab_service import GitLabService

        gl = GitLabService()
        if gl.available():
            providers["gitlab"] = gl
    except ImportError:
        log.debug("GitLab provider module not available", exc_info=True)
        pass
    except Exception:  # noqa: BLE001
        log.debug("GitLab provider unavailable", exc_info=True)

    return providers


def get_provider(name: str) -> IntegrationProvider | None:
    """Return the named provider if available, else None."""
    return provider_registry().get(name)


def default_provider() -> IntegrationProvider | None:
    """Return the best default provider.

    Preference order:
    1. Provider whose host matches the active repo's git remote.
    2. First available provider.
    3. None.
    """
    registry = provider_registry()
    if not registry:
        return None

    # Try to match active repo remote host to a provider name
    try:
        from app.core.helpers import _active_git, _run

        repo_path = _active_git()[0]
        remote_url = _run(["git", "remote", "get-url", "origin"], cwd=repo_path or None)
        if remote_url:
            rl = remote_url.lower()
            for name, provider in registry.items():
                if name in rl:
                    return provider
    except Exception:  # noqa: BLE001
        log.debug("default_provider: failed to match repo remote host", exc_info=True)
        pass

    # Fall back to first available
    return next(iter(registry.values()))
