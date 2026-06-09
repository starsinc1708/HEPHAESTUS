"""Integration tests for CSRF/CORS and body-limit middleware."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient


def test_csrf_post_without_origin_returns_403(client: TestClient) -> None:
    """POST without Origin header should be rejected by CSRF guard."""
    resp = client.post("/api/state/cleanup", json={"kinds": ["failed"]})
    assert resp.status_code == 403
    assert "CSRF" in resp.json()["error"]


def test_csrf_post_with_matching_origin_succeeds(client: TestClient) -> None:
    """POST with Origin matching Host should pass CSRF check."""
    with patch("app.core.driver._tmux_has", return_value=False):
        resp = client.post(
            "/api/state/cleanup",
            json={"kinds": ["failed"]},
            headers={"Origin": "http://localhost:8766", "Host": "localhost:8766"},
        )
    # 200 or 500 is fine — the CSRF check passed, the handler ran
    assert resp.status_code != 403


def test_csrf_post_with_referer_fallback(client: TestClient) -> None:
    """POST without Origin but with matching Referer should pass CSRF check."""
    with patch("app.core.driver._tmux_has", return_value=False):
        resp = client.post(
            "/api/state/cleanup",
            json={"kinds": ["failed"]},
            headers={
                "Referer": "http://localhost:8766/dashboard",
                "Host": "localhost:8766",
            },
        )
    assert resp.status_code != 403


def test_csrf_post_with_wrong_origin_returns_403(client: TestClient) -> None:
    """POST with non-matching Origin should be rejected."""
    resp = client.post(
        "/api/state/cleanup",
        json={"kinds": ["failed"]},
        headers={"Origin": "http://evil.example.com", "Host": "localhost:8766"},
    )
    assert resp.status_code == 403


def test_csrf_get_always_passes(client: TestClient) -> None:
    """GET requests should never be blocked by CSRF."""
    resp = client.get("/healthz")
    assert resp.status_code == 200


def test_body_limit_rejects_large_payload(client: TestClient) -> None:
    """POST with body > 5MB should be rejected with 413."""
    large_body = "x" * (5_000_001)
    resp = client.post(
        "/api/state/cleanup",
        content=large_body,
        headers={
            "Content-Type": "application/json",
            "Origin": "http://localhost:8766",
            "Host": "localhost:8766",
        },
    )
    assert resp.status_code == 413


def test_cors_header_on_get_with_matching_origin(client: TestClient) -> None:
    """GET with matching Origin should receive Access-Control-Allow-Origin header."""
    resp = client.get("/healthz", headers={"Origin": "http://localhost:8766", "Host": "localhost:8766"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:8766"
