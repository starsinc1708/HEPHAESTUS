import json

import app.core.workspaces as wsmod
from app.core.workspaces import WorkspaceRegistry, _resolve_role_connections
from app.models.connections import Connection
from app.models.workspace import AgentRef, AgentsConfig, RepoProfile, RoleConnections


def _ws(role_conns):
    base = AgentRef(provider="x", model="m", engine_profile=None)
    return RepoProfile(id="w", name="w", repoPath="/tmp/x",
                       agents=AgentsConfig(primary=base, fallback=base),
                       role_connections=role_conns)


def test_resolves_role_to_agentref_and_profile(monkeypatch):
    conn = Connection(id="conn-1", label="DS", provider="deepseek", engine="claude",
                      model="deepseek-chat", env={"ANTHROPIC_AUTH_TOKEN": "k"})
    monkeypatch.setattr(wsmod, "get_connection", lambda cid: conn if cid == "conn-1" else None)
    ws = _resolve_role_connections(_ws(RoleConnections(primary="conn-1", validators=["conn-1"])))
    assert ws.agents.primary.model == "deepseek-chat"
    assert ws.agents.primary.engine_profile == "conn-1"
    assert ws.agents.validators[0].engine_profile == "conn-1"
    assert any(p.name == "conn-1" and p.engine == "claude" for p in ws.engine_profiles)


def test_dangling_id_falls_back_and_warns(monkeypatch):
    monkeypatch.setattr(wsmod, "get_connection", lambda cid: None)
    ws = _resolve_role_connections(_ws(RoleConnections(primary="conn-gone")))
    assert ws.agents.primary.model == "m"  # unchanged
    assert "conn-gone" in getattr(ws, "role_warnings", [])


def test_update_does_not_persist_resolved_connection_keys(tmp_path, monkeypatch):
    """Regression: registry.update() on a workspace with roleConnections must merge against
    the RAW on-disk profile.json — never the resolver-injected, key-bearing in-memory profile.
    Otherwise a plain rename would serialize ANTHROPIC_AUTH_TOKEN=sk-SECRET into profile.json."""
    conn = Connection(id="conn-secret", label="DS", provider="deepseek", engine="claude",
                      model="deepseek-chat", env={"ANTHROPIC_AUTH_TOKEN": "sk-SECRET"})
    monkeypatch.setattr(wsmod, "get_connection", lambda cid: conn if cid == "conn-secret" else None)

    repo = tmp_path / "repo"
    pf = repo / ".hephaestus" / "profile.json"
    pf.parent.mkdir(parents=True, exist_ok=True)
    base = AgentRef(provider="x", model="m", engine_profile=None)
    ws = RepoProfile(id="ws-1", name="orig", repoPath=str(repo),
                     agents=AgentsConfig(primary=base, fallback=base),
                     role_connections=RoleConnections(primary="conn-secret"))
    pf.write_text(ws.model_dump_json(by_alias=True, indent=2), encoding="utf-8")

    reg = WorkspaceRegistry(home=tmp_path / "_home")
    reg._write_index({"workspaces": {"ws-1": str(repo)}, "active": None})

    out = reg.update("ws-1", {"name": "renamed"})
    assert out.name == "renamed"

    on_disk_text = pf.read_text(encoding="utf-8")
    assert "sk-SECRET" not in on_disk_text        # raw key never persisted
    assert '"name": "renamed"' in on_disk_text    # the actual patch did land
    # The roleConnections id reference IS persisted (that's correct), but the resolver-injected
    # engineProfile named after the connection must NOT be.
    on_disk = json.loads(on_disk_text)
    assert on_disk["roleConnections"]["primary"] == "conn-secret"
    assert not any(ep["name"] == "conn-secret" for ep in on_disk.get("engineProfiles", []))
