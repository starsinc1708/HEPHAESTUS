"""Temporary active-workspace accessor — removed when Stage 1 registry lands (spec §6)."""
from __future__ import annotations

import hashlib
import os

from app.config import BASE_BRANCH, BRANCH_PREFIX, REMOTE, REPO, _config_effective
from app.models.workspace import AgentRef, AgentsConfig, RepoProfile


def _ws_id(repo_path: str) -> str:
    return hashlib.sha256(os.path.realpath(repo_path).casefold().encode()).hexdigest()[:16]


def get_active_profile() -> RepoProfile:
    """The registry's ACTIVE workspace if there is one; otherwise a RepoProfile built from
    the legacy global config (kept for tests / no-workspace fallback)."""
    try:
        from app.core.workspaces import registry

        ws = registry.active()
        if ws is not None:
            return ws
    except Exception:  # noqa: BLE001 — registry optional; fall back to the config-built profile
        pass
    eff = _config_effective()
    primary = AgentRef(
        provider=eff.get("HEPHAESTUS_AGENT_PROVIDER", "opencode"),
        model=eff.get("HEPHAESTUS_PRIMARY_MODEL", "default"),
        agent=eff.get("HEPHAESTUS_PRIMARY_AGENT") or None,
    )
    fallback = AgentRef(
        provider=eff.get("HEPHAESTUS_AGENT_PROVIDER", "opencode"),
        model=eff.get("HEPHAESTUS_FALLBACK_MODEL", "default"),
        agent=eff.get("HEPHAESTUS_FALLBACK_AGENT") or None,
    )
    return RepoProfile(
        id=_ws_id(REPO),
        name=os.path.basename(os.path.normpath(REPO)) or "workspace",
        repo_path=REPO,
        base_branch=BASE_BRANCH,
        remote=REMOTE,
        branch_prefix=BRANCH_PREFIX,
        agents=AgentsConfig(primary=primary, fallback=fallback),
    )
