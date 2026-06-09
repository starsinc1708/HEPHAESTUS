"""Contract tests: integrations API router (Epic 3 + v2 #8 UI connect)."""

from __future__ import annotations

_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


def _patch_creds(tmp_path, monkeypatch):
    """Point the creds store at an isolated temp file (hermetic)."""
    import app.services.integrations.creds as creds

    monkeypatch.setattr(creds, "_STORE", tmp_path / "integrations.json")


# ---------------------------------------------------------------------------
# GET /api/v1/integrations — always lists github + gitlab with connection state
# ---------------------------------------------------------------------------


def test_list_integrations_lists_known_providers(client, tmp_path, monkeypatch):
    _patch_creds(tmp_path, monkeypatch)
    monkeypatch.setattr("app.api.v1.integrations.default_provider", lambda: None)
    r = client.get("/api/v1/integrations")
    assert r.status_code == 200
    body = r.json()
    names = {p["name"] for p in body["providers"]}
    assert names == {"github", "gitlab"}
    gh = next(p for p in body["providers"] if p["name"] == "github")
    assert gh["capabilities"]["pullRequests"] is True
    assert gh["connected"] is False
    assert gh["available"] is False
    assert gh["token"] is None
    assert "linear" not in names


def test_list_integrations_reflects_connection(client, tmp_path, monkeypatch):
    _patch_creds(tmp_path, monkeypatch)
    monkeypatch.setattr("app.api.v1.integrations.default_provider", lambda: None)
    import app.services.integrations.creds as creds

    creds.set_cred("gitlab", "glpat_supersecret9", host="https://gitlab.example.com")
    creds.set_status("gitlab", "connected", error=None, tested_at="2026-06-08T00:00:00Z")
    body = client.get("/api/v1/integrations").json()
    gl = next(p for p in body["providers"] if p["name"] == "gitlab")
    assert gl["connected"] is True
    assert gl["host"] == "https://gitlab.example.com"
    assert gl["token"] is not None and "supersecret" not in gl["token"]
    assert "glpat_supersecret9" not in str(body)  # raw token never leaks


# ---------------------------------------------------------------------------
# connect / verify / disconnect
# ---------------------------------------------------------------------------


def test_connect_github_verified(client, tmp_path, monkeypatch):
    _patch_creds(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "app.api.v1.integrations.verify_credential", lambda name, **kw: ("connected", None)
    )
    r = client.post(
        "/api/v1/integrations/github/connect",
        json={"token": "ghp_realsecret123"},
        headers=_CSRF,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is True
    assert body["status"] == "connected"
    assert body["token"] is not None and "ghp_realsecret123" not in str(body)  # masked


def test_connect_bad_token_failed_message(client, tmp_path, monkeypatch):
    _patch_creds(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "app.api.v1.integrations.verify_credential",
        lambda name, **kw: ("failed", "invalid token"),
    )
    r = client.post(
        "/api/v1/integrations/github/connect",
        json={"token": "bad"},
        headers=_CSRF,
    )
    assert r.status_code == 200  # never 500/4xx for a verify failure
    body = r.json()
    assert body["connected"] is False
    assert body["error"] == "invalid token"


def test_connect_gitlab_with_host(client, tmp_path, monkeypatch):
    _patch_creds(tmp_path, monkeypatch)
    captured: dict[str, object] = {}

    def _verify(name, **kw):
        captured.update({"name": name, **kw})
        return "connected", None

    monkeypatch.setattr("app.api.v1.integrations.verify_credential", _verify)
    r = client.post(
        "/api/v1/integrations/gitlab/connect",
        json={"token": "glpat_x", "host": "https://gitlab.example.com"},
        headers=_CSRF,
    )
    assert r.status_code == 200
    assert r.json()["host"] == "https://gitlab.example.com"
    assert captured["host"] == "https://gitlab.example.com"


def test_connect_gitlab_invalid_host_400(client, tmp_path, monkeypatch):
    _patch_creds(tmp_path, monkeypatch)
    r = client.post(
        "/api/v1/integrations/gitlab/connect",
        json={"token": "glpat_x", "host": "http://insecure"},
        headers=_CSRF,
    )
    assert r.status_code == 400


def test_connect_empty_token_400(client, tmp_path, monkeypatch):
    _patch_creds(tmp_path, monkeypatch)
    r = client.post(
        "/api/v1/integrations/github/connect", json={"token": "  "}, headers=_CSRF
    )
    assert r.status_code == 400


def test_connect_unknown_provider_404(client, tmp_path, monkeypatch):
    _patch_creds(tmp_path, monkeypatch)
    r = client.post(
        "/api/v1/integrations/bitbucket/connect", json={"token": "x"}, headers=_CSRF
    )
    assert r.status_code == 404


def test_verify_uses_stored_token(client, tmp_path, monkeypatch):
    _patch_creds(tmp_path, monkeypatch)
    import app.services.integrations.creds as creds

    creds.set_cred("github", "ghp_stored")
    seen: dict[str, object] = {}

    def _verify(name, **kw):
        seen.update(kw)
        return "connected", None

    monkeypatch.setattr("app.api.v1.integrations.verify_credential", _verify)
    r = client.post("/api/v1/integrations/github/verify", headers=_CSRF)
    assert r.status_code == 200
    assert r.json()["connected"] is True
    assert seen["token"] == "ghp_stored"


def test_verify_not_connected_409(client, tmp_path, monkeypatch):
    _patch_creds(tmp_path, monkeypatch)
    r = client.post("/api/v1/integrations/github/verify", headers=_CSRF)
    assert r.status_code == 409


def test_disconnect_clears(client, tmp_path, monkeypatch):
    _patch_creds(tmp_path, monkeypatch)
    import app.services.integrations.creds as creds

    creds.set_cred("github", "ghp_x")
    r = client.post("/api/v1/integrations/github/disconnect", headers=_CSRF)
    assert r.status_code == 200
    assert creds.get_cred("github") is None


# ---------------------------------------------------------------------------
# Existing kept actions (import / pr / sync) — credential now store-backed
# ---------------------------------------------------------------------------


def test_import_unavailable_409(client, monkeypatch):
    monkeypatch.setattr("app.api.v1.integrations.get_provider", lambda n: None)
    r = client.post(
        "/api/v1/integrations/gitlab/import",
        json={"label": "x"},
        headers=_CSRF,
    )
    assert r.status_code == 409


def test_create_pr(client, monkeypatch):
    from app.services.integrations.base import ProviderCapabilities

    class Fake:
        name = "github"

        def available(self) -> bool:
            return True

        def capabilities(self) -> ProviderCapabilities:
            return ProviderCapabilities(issues=True, pull_requests=True)

        def create_pr(self, branch: str, *, title: str, body: str, base: str) -> dict:
            return {"number": 9, "url": "http://pr/9"}

    monkeypatch.setattr("app.api.v1.integrations.default_provider", lambda: Fake())
    monkeypatch.setattr("app.api.v1.integrations.get_provider", lambda n: Fake())
    r = client.post(
        "/api/v1/integrations/pr",
        json={"branch": "auto/x", "title": "T", "body": "B", "base": "main"},
        headers=_CSRF,
    )
    assert r.status_code == 200 and r.json()["number"] == 9


def test_import_available_provider(client, monkeypatch):
    from app.services.integrations.base import ProviderCapabilities

    class FakeProvider:
        name = "github"

        def available(self) -> bool:
            return True

        def capabilities(self) -> ProviderCapabilities:
            return ProviderCapabilities(issues=True)

        def import_to_queue(self, *, label: str) -> dict:
            return {"added": ["item-1"], "errors": []}

    monkeypatch.setattr("app.api.v1.integrations.get_provider", lambda n: FakeProvider())
    r = client.post(
        "/api/v1/integrations/github/import",
        json={"label": "hephaestus:bug"},
        headers=_CSRF,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "item-1" in body["added"]


def test_create_pr_bad_branch(client, monkeypatch):
    from app.services.integrations.base import ProviderCapabilities

    class Fake:
        name = "github"

        def available(self) -> bool:
            return True

        def capabilities(self) -> ProviderCapabilities:
            return ProviderCapabilities(pull_requests=True)

        def create_pr(self, branch: str, *, title: str, body: str, base: str) -> dict:
            return {"number": 1, "url": "http://pr/1"}

    monkeypatch.setattr("app.api.v1.integrations.default_provider", lambda: Fake())
    monkeypatch.setattr("app.api.v1.integrations.get_provider", lambda n: Fake())
    r = client.post(
        "/api/v1/integrations/pr",
        json={"branch": "../../../etc/passwd", "title": "T", "body": "B", "base": "main"},
        headers=_CSRF,
    )
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_create_pr_no_provider(client, monkeypatch):
    monkeypatch.setattr("app.api.v1.integrations.default_provider", lambda: None)
    monkeypatch.setattr("app.api.v1.integrations.get_provider", lambda n: None)
    r = client.post(
        "/api/v1/integrations/pr",
        json={"branch": "feature/my-branch", "title": "T", "body": "B", "base": "main"},
        headers=_CSRF,
    )
    assert r.status_code == 409
    assert r.json()["ok"] is False
