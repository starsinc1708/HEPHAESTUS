"""Workspace domain model — RepoProfile + agent/review config (umbrella §4.1)."""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class VerifySource(StrEnum):
    AGENT = "agent"      # команды определены Profiler'ом -> .hephaestus/memory/verify.md
    MANUAL = "manual"    # пользователь задал override в настройках


class ScopeGuardMode(StrEnum):
    OFF = "off"
    ADVISORY = "advisory"
    STRICT = "strict"



class EngineProfile(BaseModel):
    """A named agent-engine configuration: a CLI + its env (endpoint/keys).

    Lets a workspace mix CLIs/models per role — e.g. a 'claude' profile (real Anthropic)
    for planning and a 'deepseek' profile (Claude CLI pointed at DeepSeek via env) for
    implementation/verification. Referenced from AgentRef.engine_profile by name.
    """
    model_config = ConfigDict(populate_by_name=True)
    name: str
    engine: str = "opencode"            # "opencode" | "claude"
    env: dict[str, str] = Field(default_factory=dict)


class AgentRef(BaseModel):
    """opencode provider/model/agent triple. 'agent' опционален."""
    model_config = ConfigDict(populate_by_name=True)
    provider: str
    model: str
    agent: str | None = None
    # Optional reference to a named EngineProfile; None/"" -> workspace default engine.
    engine_profile: str | None = Field(None, alias="engineProfile")
    # Optional model parameters (temperature, max_tokens, top_p, etc.) passed as CLI flags.
    model_params: dict[str, float | int | str | bool] = Field(default_factory=dict, alias="modelParams")


class AgentsConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    use_models: bool = Field(False, alias="useModels")
    primary: AgentRef
    fallback: AgentRef
    # Plan / decomposition (scan mappers + reducers); falls back to primary when None.
    planner: AgentRef | None = None
    validators: list[AgentRef] = []
    arbiters: list[AgentRef] = []
    final: AgentRef | None = None
    # Conflict-resolution role (Epic 1). None -> falls back to `primary`.
    merge: AgentRef | None = None


class ReviewConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    enabled: bool = True
    tier1_threshold: int = Field(5, alias="tier1Threshold")
    tier2_threshold: int = Field(2, alias="tier2Threshold")
    max_revisions: int = Field(2, alias="maxRevisions")


class RoleConnections(BaseModel):
    """Per-workspace assignment of agent roles to global connection ids.

    Stored on the RepoProfile; resolved into AgentRef/EngineProfile at registry load.
    """
    model_config = ConfigDict(populate_by_name=True)
    primary: str | None = None
    fallback: str | None = None
    planner: str | None = None
    final: str | None = None
    merge: str | None = None
    validators: list[str] = Field(default_factory=list)
    arbiters: list[str] = Field(default_factory=list)


class RepoProfile(BaseModel):
    """Workspace == RepoProfile + runtime paths."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str
    name: str
    repo_path: str = Field(..., alias="repoPath")
    base_branch: str = Field("main", alias="baseBranch")
    remote: str = "origin"
    branch_prefix: str = Field("auto", alias="branchPrefix")

    agents: AgentsConfig
    strictness: str = "standard"
    review: ReviewConfig = ReviewConfig()

    # Agent engine: "opencode" (default) or "claude" (Claude Code CLI, `claude -p`).
    # engine_env is merged into the agent subprocess env — e.g. to drive Claude CLI
    # against DeepSeek: ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic + ANTHROPIC_API_KEY.
    engine: str = "opencode"
    engine_env: dict[str, str] = Field(default_factory=dict, alias="engineEnv")
    # Named engine profiles a role may reference via AgentRef.engine_profile.
    engine_profiles: list[EngineProfile] = Field(default_factory=list, alias="engineProfiles")
    # Per-role assignment of global connection ids; resolved into agents/engine_profiles
    # at registry load (see app.core.workspaces._resolve_role_connections).
    role_connections: RoleConnections | None = Field(None, alias="roleConnections")

    verify_source: VerifySource = Field(VerifySource.AGENT, alias="verifySource")
    verify_commands_override: list[str] = Field([], alias="verifyCommandsOverride")
    verify_timeout_sec: int = Field(900, alias="verifyTimeoutSec")

    memory_dir: str = Field(".hephaestus/memory", alias="memoryDir")
    autopush: bool = False
    autopush_remote: str = Field("origin", alias="autopushRemote")
    scope_guard: ScopeGuardMode = Field(ScopeGuardMode.ADVISORY, alias="scopeGuard")
    max_transient_retries: int = Field(2, alias="maxTransientRetries")
    transient_backoff_sec: int = Field(10, alias="transientBackoffSec")

    created_at: str | None = Field(None, alias="createdAt")
    onboarded: bool = False