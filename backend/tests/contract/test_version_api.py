def test_version_endpoint(client):
    r = client.get("/api/v1/version")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "version" in data
    assert "commit" in data
    assert "serverTime" in data
    assert isinstance(data["version"], str) and len(data["version"]) > 0
    assert data["commit"] is None or isinstance(data["commit"], str)
    # serverTime is ISO 8601 UTC
    assert data["serverTime"].endswith("Z")
    assert len(data["serverTime"]) == 20  # "2026-06-08T12:00:00Z"
