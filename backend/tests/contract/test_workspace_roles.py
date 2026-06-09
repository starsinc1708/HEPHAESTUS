_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


def _setup_ws_with_connection(tmp_path, monkeypatch):
    """Onboard one workspace whose roleConnections point at a key-bearing connection, and
    wire both the API's registry and the role resolver to it. Returns (ws_id, registry)."""
    import app.api.v1.workspaces as w
    import app.core.workspaces as wsmod
    from app.core.workspaces import WorkspaceRegistry
    from app.models.connections import Connection
    from app.models.workspace import AgentRef, AgentsConfig, RepoProfile, RoleConnections

    conn = Connection(id="conn-secret", label="DS", provider="deepseek", engine="claude",
                      model="deepseek-chat", env={"ANTHROPIC_AUTH_TOKEN": "sk-SECRET9"})
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
    monkeypatch.setattr(w, "registry", reg)
    return "ws-1", reg


def test_get_workspace_masks_resolved_keys(client, tmp_path, monkeypatch):
    """Regression: GET /workspaces/{id} must mask keys injected into the resolved profile's
    engineProfiles[].env by the role-connection resolver."""
    ws_id, _ = _setup_ws_with_connection(tmp_path, monkeypatch)
    r = client.get(f"/api/v1/workspaces/{ws_id}")
    assert r.status_code == 200
    eps = r.json()["workspace"]["engineProfiles"]
    secret_ep = next(ep for ep in eps if ep["name"] == "conn-secret")
    assert secret_ep["env"]["ANTHROPIC_AUTH_TOKEN"] != "sk-SECRET9"  # masked
    assert "sk-SECRET9" not in str(r.json())


def test_list_workspaces_masks_resolved_keys(client, tmp_path, monkeypatch):
    """Regression: GET /workspaces (list) must mask resolved engineProfiles[].env keys too."""
    _setup_ws_with_connection(tmp_path, monkeypatch)
    r = client.get("/api/v1/workspaces")
    assert r.status_code == 200
    assert "sk-SECRET9" not in str(r.json())


def test_patch_rejects_unknown_connection_id(client, monkeypatch):
    import app.api.v1.workspaces as w
    import app.services.connections as cs
    monkeypatch.setattr(cs, "get_connection", lambda cid: None)
    monkeypatch.setattr(w.registry, "get", lambda i: object())  # ws exists
    r = client.patch("/api/v1/workspaces/ws1", headers=_CSRF,
                     json={"roleConnections": {"primary": "conn-nope"}})
    assert r.status_code == 400
    assert "conn-nope" in r.json()["error"]
