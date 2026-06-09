import app.services.connections as cs


def test_add_get_list_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "_STORE", tmp_path / "connections.json")
    c = cs.add_connection(provider="deepseek", engine="claude", auth_method="api_key",
                          model="deepseek-chat", key="sk-secret123", label="DS")
    assert c.id.startswith("conn-")
    assert c.status == "untested"
    assert cs.get_connection(c.id).env["ANTHROPIC_AUTH_TOKEN"] == "sk-secret123"  # raw kept server-side
    masked = cs.list_connections_masked()
    assert masked[0]["env"]["ANTHROPIC_AUTH_TOKEN"] != "sk-secret123"
    assert cs.delete_connection(c.id) is True
    assert cs.get_connection(c.id) is None
    assert cs.delete_connection("nope") is False


def test_corrupt_store_is_empty(tmp_path, monkeypatch):
    p = tmp_path / "connections.json"
    p.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(cs, "_STORE", p)
    assert cs.list_connections() == []  # never raises


def test_set_status(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "_STORE", tmp_path / "connections.json")
    c = cs.add_connection(provider="glm", engine="claude", auth_method="api_key",
                          model="glm-4.6", key="zk-1", label="G")
    cs.set_status(c.id, "connected", error=None, tested_at="2026-06-07T00:00:00Z")
    assert cs.get_connection(c.id).status == "connected"
