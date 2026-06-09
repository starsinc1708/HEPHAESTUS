"""Contract: Ollama provider connection flow."""
_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


def _patch_store(tmp_path, monkeypatch):
    import app.services.connections as cs
    monkeypatch.setattr(cs, "_STORE", tmp_path / "connections.json")


def test_ollama_in_catalog(client):
    r = client.get("/api/v1/connection-presets")
    assert r.status_code == 200
    provs = {e["provider"] for e in r.json()["catalog"]}
    assert "ollama" in provs


def test_create_ollama_connection_no_key(client, tmp_path, monkeypatch):
    _patch_store(tmp_path, monkeypatch)
    r = client.post("/api/v1/connections", headers=_CSRF, json={
        "provider": "ollama", "engine": "opencode", "authMethod": "api_key",
        "model": "llama3.1", "key": ""})
    assert r.status_code == 200
    c = r.json()["connection"]
    assert c["provider"] == "ollama"
    assert c["env"].get("OPENAI_BASE_URL") == "http://localhost:11434/v1"
    assert "ANTHROPIC_BASE_URL" not in c["env"]


def test_create_ollama_connection_with_key_masks(client, tmp_path, monkeypatch):
    _patch_store(tmp_path, monkeypatch)
    r = client.post("/api/v1/connections", headers=_CSRF, json={
        "provider": "ollama", "engine": "opencode", "authMethod": "api_key",
        "model": "llama3.1", "key": "sk-testkey123"})
    assert r.status_code == 200
    env = r.json()["connection"]["env"]
    assert "sk-testkey123" not in str(env)


def test_existing_connections_still_work(client, tmp_path, monkeypatch):
    _patch_store(tmp_path, monkeypatch)
    r = client.post("/api/v1/connections", headers=_CSRF, json={
        "provider": "deepseek", "engine": "claude", "authMethod": "api_key",
        "model": "deepseek-chat", "key": "sk-ds"})
    assert r.status_code == 200
    c = r.json()["connection"]
    assert c["env"].get("ANTHROPIC_BASE_URL") == "https://api.deepseek.com/anthropic"
    assert "OPENAI_BASE_URL" not in c["env"]
