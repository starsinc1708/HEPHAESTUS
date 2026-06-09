_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


def _patch_store(tmp_path, monkeypatch):
    import app.services.connections as cs
    monkeypatch.setattr(cs, "_STORE", tmp_path / "connections.json")


def test_catalog(client):
    r = client.get("/api/v1/connection-presets")
    assert r.status_code == 200
    provs = {e["provider"] for e in r.json()["catalog"]}
    assert {"anthropic", "openai", "glm", "copilot"} <= provs


def test_create_subscription_no_key(client, tmp_path, monkeypatch):
    import app.services.connections as cs
    monkeypatch.setattr(cs, "_STORE", tmp_path / "connections.json")
    r = client.post("/api/v1/connections", headers=_CSRF, json={
        "provider": "anthropic", "engine": "claude", "authMethod": "subscription",
        "model": "claude-opus-4-5"})
    assert r.status_code == 200
    c = r.json()["connection"]
    assert c["authMethod"] == "subscription"
    assert "ANTHROPIC_AUTH_TOKEN" not in c["env"]  # no secret for subscription


def test_create_list_masks_key_then_delete(client, tmp_path, monkeypatch):
    _patch_store(tmp_path, monkeypatch)
    r = client.post("/api/v1/connections", headers=_CSRF, json={
        "provider": "deepseek", "engine": "claude", "authMethod": "api_key",
        "model": "deepseek-chat", "key": "sk-supersecret9"})
    assert r.status_code == 200
    cid = r.json()["connection"]["id"]
    lst = client.get("/api/v1/connections").json()["connections"]
    assert lst[0]["env"]["ANTHROPIC_AUTH_TOKEN"] != "sk-supersecret9"  # masked
    assert client.delete(f"/api/v1/connections/{cid}", headers=_CSRF).status_code == 200


def test_create_response_masks_key(client, tmp_path, monkeypatch):
    """Regression: POST /connections must not echo the raw key back in the create response."""
    _patch_store(tmp_path, monkeypatch)
    r = client.post("/api/v1/connections", headers=_CSRF, json={
        "provider": "deepseek", "engine": "claude", "authMethod": "api_key",
        "model": "deepseek-chat", "key": "sk-supersecret9"})
    assert r.status_code == 200
    env = r.json()["connection"]["env"]
    assert env["ANTHROPIC_AUTH_TOKEN"] != "sk-supersecret9"  # masked
    assert "***" in env["ANTHROPIC_AUTH_TOKEN"]
    assert "sk-supersecret9" not in str(r.json())


def test_create_bad_combo_400(client, tmp_path, monkeypatch):
    _patch_store(tmp_path, monkeypatch)
    r = client.post("/api/v1/connections", headers=_CSRF, json={
        "provider": "glm", "engine": "opencode", "authMethod": "api_key",
        "model": "glm-4.6", "key": "k"})
    assert r.status_code == 400


def test_test_endpoint(client, tmp_path, monkeypatch):
    _patch_store(tmp_path, monkeypatch)
    cid = client.post("/api/v1/connections", headers=_CSRF, json={
        "provider": "deepseek", "engine": "claude", "authMethod": "api_key",
        "model": "deepseek-chat", "key": "k"}).json()["connection"]["id"]
    import app.api.v1.connections as mod
    async def _fake(conn):
        return "connected", None
    monkeypatch.setattr(mod, "test_connection", _fake)
    r = client.post(f"/api/v1/connections/{cid}/test", headers=_CSRF)
    assert r.status_code == 200 and r.json()["status"] == "connected"
