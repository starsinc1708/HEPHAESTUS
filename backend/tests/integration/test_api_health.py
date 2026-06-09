"""Integration tests for health and static file endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_returns_200_ok(client: TestClient) -> None:
    """GET /healthz returns 200 with plain text 'ok'."""
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_healthz_has_no_store_cache(client: TestClient) -> None:
    """Healthz endpoint should have no-store cache header."""
    resp = client.get("/healthz")
    assert resp.headers.get("cache-control") == "no-store, no-cache, must-revalidate"


def test_root_returns_200_or_404(client: TestClient) -> None:
    """GET / returns 200 if index.html exists, 404 otherwise."""
    resp = client.get("/")
    assert resp.status_code in (200, 404)


def test_index_html_returns_200_or_404(client: TestClient) -> None:
    """GET /index.html mirrors GET / behavior."""
    resp = client.get("/index.html")
    assert resp.status_code in (200, 404)


def test_nonexistent_api_returns_404(client: TestClient) -> None:
    """GET /api/nonexistent should return 404 or 405."""
    resp = client.get("/api/nonexistent")
    assert resp.status_code == 404


def test_nonexistent_path_returns_404(client: TestClient) -> None:
    """Unknown non-API path falls through to the SPA shell (client-side routing)."""
    resp = client.get("/some/random/path")
    # 200 when dist/index.html is present (SPA history fallback), 404 when absent.
    assert resp.status_code in (200, 404)


def test_static_path_traversal_blocked(client: TestClient) -> None:
    """A traversal attempt must never leak filesystem contents."""
    resp = client.get("/static/../../etc/passwd")
    # httpx normalizes the URL, so this lands on the SPA shell or a 404 — never the file.
    assert resp.status_code in (200, 404)
    assert "root:" not in resp.text  # /etc/passwd content must not leak
