def test_clis_endpoint(client, monkeypatch):
    import app.api.v1.clis as mod
    monkeypatch.setattr(mod, "detect_clis", lambda: {
        "claude": {"installed": True, "version": "2.1.140", "auth": {"unknown": True}},
        "opencode": {"installed": True, "version": "1.16.2", "auth": {"providers": ["anthropic"]}},
        "codex": {"installed": False, "version": None, "auth": {}},
    })
    r = client.get("/api/v1/clis")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    clis = data["clis"]
    assert "claude" in clis
    assert "opencode" in clis
    assert "codex" in clis
    assert clis["claude"]["installed"] is True
    assert clis["opencode"]["installed"] is True
    assert clis["codex"]["installed"] is False
