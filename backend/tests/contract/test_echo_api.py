def test_echo_endpoint(client):
    r = client.get("/api/v1/echo/hello")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["echo"] == "hello"


def test_echo_endpoint_with_url_encoded_chars(client):
    r = client.get("/api/v1/echo/hello%20world")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["echo"] == "hello world"
