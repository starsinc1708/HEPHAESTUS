"""WorkspaceRegistry — registry of onboarded repos + active selection (D9).

Storage layout: ALL per-workspace data (profile, tasks/state, memory and other
auxiliary files) lives inside the working repository under ``<repo>/.hephaestus/``:

    <repo>/.hephaestus/profile.json     # this RepoProfile
    <repo>/.hephaestus/state/           # work-state.json, iter-*, scans, decisions.log ...
    <repo>/.hephaestus/memory/          # project memory (D6)

The only thing kept OUTSIDE the repos is a thin global index
``<hephaestus_home>/registry.json`` = {"workspaces": {id: repoPath}, "active": id} so the
tool knows which repos are onboarded and which is active.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import pathlib
import time
from typing import Any

from app.models.workspace import AgentRef, AgentsConfig, EngineProfile, RepoProfile
from app.services.connections import get_connection
from app.services.hephaestus_home import hephaestus_home

log = logging.getLogger("hephaestus.backend.workspaces")

def _neutral_agents() -> AgentsConfig:
    """Base defaults: a working funnel out of the box (validators per lens, 2 arbiters,
    final) all pointing at the primary model. The user refines per role in the UI."""
    primary = AgentRef(provider="anthropic", model="claude-opus-4-8")
    fallback = AgentRef(provider="openai", model="gpt-4.1")
    return AgentsConfig(
        primary=primary,
        fallback=fallback,
        validators=[primary.model_copy(deep=True) for _ in range(5)],
        arbiters=[primary.model_copy(deep=True) for _ in range(2)],
        final=primary.model_copy(deep=True),
    )


_HEPHAESTUS_DIR = ".hephaestus"

# Single-valued agent roles on AgentsConfig (each is an AgentRef | None).
_SINGLE_ROLES = ("primary", "fallback", "planner", "final", "merge")
# List-valued agent roles on AgentsConfig (each is a list[AgentRef]).
_LIST_ROLES = ("validators", "arbiters")


def _resolve_role_connections(ws: RepoProfile) -> RepoProfile:
    """Resolve ws.role_connections (role -> connection id) into the in-memory profile.

    For each assigned role, look up the global Connection and:
      * set ws.agents.<role> to AgentRef(provider, model, engineProfile=conn.id), and
      * register an EngineProfile(name=conn.id, engine, env) so the runner can find it.
    A dangling id (no such connection) keeps the existing ref and is recorded on the
    extra `role_warnings` field (RepoProfile is extra="allow"). Mutates in memory only;
    nothing is written back to profile.json.
    """
    rc = ws.role_connections
    if rc is None:
        return ws

    warnings: list[str] = []
    profiles_by_name: dict[str, EngineProfile] = {p.name: p for p in ws.engine_profiles}

    def _ref_for(conn_id: str) -> AgentRef | None:
        conn = get_connection(conn_id)
        if conn is None:
            warnings.append(conn_id)
            return None
        profiles_by_name[conn.id] = EngineProfile(name=conn.id, engine=conn.engine, env=conn.env)
        return AgentRef(provider=conn.provider, model=conn.model, engine_profile=conn.id)

    for role in _SINGLE_ROLES:
        conn_id = getattr(rc, role)
        if not conn_id:
            continue
        ref = _ref_for(conn_id)
        if ref is not None:
            setattr(ws.agents, role, ref)

    for role in _LIST_ROLES:
        ids: list[str] = getattr(rc, role) or []
        if not ids:
            continue
        refs: list[AgentRef] = []
        for conn_id in ids:
            ref = _ref_for(conn_id)
            if ref is not None:
                refs.append(ref)
        if refs:
            setattr(ws.agents, role, refs)

    ws.engine_profiles = list(profiles_by_name.values())
    if warnings:
        ws.role_warnings = warnings  # type: ignore[attr-defined]  # extra="allow" field
    return ws


class WorkspaceRegistry:
    def __init__(self, home: pathlib.Path | None = None) -> None:
        self._home = home or hephaestus_home()

    @staticmethod
    def ws_id_for(repo_path: str) -> str:
        norm = os.path.realpath(repo_path).casefold().encode()
        return hashlib.sha256(norm).hexdigest()[:16]

    # ---------- thin global index (which repos are onboarded + active) ----------

    def _index_path(self) -> pathlib.Path:
        return self._home / "registry.json"

    def _read_index(self) -> dict[str, Any]:
        p = self._index_path()
        if not p.exists():
            return {"workspaces": {}, "active": None}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            log.debug("_read_index: failed to parse %s", p, exc_info=True)
            return {"workspaces": {}, "active": None}
        if not isinstance(data, dict):
            return {"workspaces": {}, "active": None}
        data.setdefault("workspaces", {})
        data.setdefault("active", None)
        return data

    def _write_index(self, idx: dict[str, Any]) -> None:
        from app.core.state import _atomic_write

        self._home.mkdir(parents=True, exist_ok=True)
        _atomic_write(self._index_path(), json.dumps(idx, indent=2, ensure_ascii=False))

    # ---------- per-repo profile (<repo>/.hephaestus/profile.json) ----------

    @staticmethod
    def _profile_path_for(repo_path: str) -> pathlib.Path:
        return pathlib.Path(repo_path) / _HEPHAESTUS_DIR / "profile.json"

    def _load_profile(self, repo_path: str) -> RepoProfile | None:
        pf = self._profile_path_for(repo_path)
        if not pf.exists():
            return None
        try:
            ws = RepoProfile.model_validate_json(pf.read_text(encoding="utf-8"))
        except Exception:
            log.warning("skipping invalid profile.json at %s", pf)
            return None
        if ws.role_connections:
            ws = _resolve_role_connections(ws)
        return ws

    def list(self) -> list[RepoProfile]:
        idx = self._read_index()
        workspaces: dict[str, Any] = idx.get("workspaces", {})
        out: list[RepoProfile] = []
        for repo_path in workspaces.values():
            ws = self._load_profile(str(repo_path))
            if ws is not None:
                out.append(ws)
        return out

    def get(self, ws_id: str) -> RepoProfile | None:
        idx = self._read_index()
        workspaces: dict[str, Any] = idx.get("workspaces", {})
        repo_path = workspaces.get(ws_id)
        if not repo_path:
            return None
        return self._load_profile(str(repo_path))

    def create(self, repo_path: str, *, name: str | None = None) -> RepoProfile:
        rp = pathlib.Path(repo_path)
        if not (rp / ".git").exists():
            raise ValueError("not a git repository")
        ws_id = self.ws_id_for(repo_path)
        existing = self.get(ws_id)
        if existing is not None:
            return existing
        ws = RepoProfile(
            id=ws_id,
            name=name or rp.name,
            repo_path=os.path.realpath(repo_path),
            agents=_neutral_agents(),
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            onboarded=False,
        )
        self._write(ws)
        return ws

    def _write(self, ws: RepoProfile) -> None:
        from app.core.state import _atomic_write

        pf = self._profile_path_for(ws.repo_path)
        pf.parent.mkdir(parents=True, exist_ok=True)
        # Self-ignore: keep HEPHAESTUS's own working data (state/scans/iters/memory) out of the
        # user's repo so `git add -A` during a task never commits it. git reads this file
        # even though `*` also ignores it.
        gi = pf.parent / ".gitignore"
        if not gi.exists():
            with contextlib.suppress(OSError):
                gi.write_text("*\n", encoding="utf-8")
        _atomic_write(pf, ws.model_dump_json(by_alias=True, indent=2))
        idx = self._read_index()
        workspaces: dict[str, Any] = idx.setdefault("workspaces", {})
        workspaces[ws.id] = ws.repo_path
        self._write_index(idx)

    def update(self, ws_id: str, patch: dict[str, Any]) -> RepoProfile:
        pf_ws = self.get(ws_id)
        if pf_ws is None:
            raise ValueError(f"unknown workspace {ws_id}")
        # Merge against the RAW on-disk profile.json (NOT the resolver-injected, in-memory
        # profile from get()). Otherwise resolved key-bearing engineProfiles would be
        # serialized back into profile.json on any patch — invariant: no keys in profile.json.
        raw = json.loads(self._profile_path_for(pf_ws.repo_path).read_text(encoding="utf-8"))
        merged = {**raw, **patch}
        new_ws = RepoProfile.model_validate(merged)
        self._write(new_ws)
        return self._load_profile(pf_ws.repo_path) or new_ws

    def activate(self, ws_id: str) -> None:
        idx = self._read_index()
        idx["active"] = ws_id
        self._write_index(idx)

    def active(self) -> RepoProfile | None:
        idx = self._read_index()
        ws_id = idx.get("active")
        return self.get(str(ws_id)) if ws_id else None

    def state_dir(self, ws: RepoProfile) -> pathlib.Path:
        return pathlib.Path(ws.repo_path) / _HEPHAESTUS_DIR / "state"

    def memory_dir(self, ws: RepoProfile) -> pathlib.Path:
        return pathlib.Path(ws.repo_path) / ws.memory_dir


registry = WorkspaceRegistry()


def active_workspace() -> RepoProfile | None:
    return registry.active()
