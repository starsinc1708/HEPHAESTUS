"""ws_shim builds a RepoProfile from global config (temporary Stage-1 bridge)."""
from __future__ import annotations

from app.core.ws_shim import get_active_profile
from app.models.workspace import RepoProfile


def test_get_active_profile_returns_repo_profile() -> None:
    prof = get_active_profile()
    assert isinstance(prof, RepoProfile)
    assert prof.repo_path is not None
    assert prof.memory_dir == ".hephaestus/memory"
    assert len(prof.id) == 16
    assert prof.agents.primary is not None
