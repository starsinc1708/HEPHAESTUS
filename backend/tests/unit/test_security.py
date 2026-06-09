"""Tests for security features: HMAC, security headers, rate limiting, WS auth."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# 1. Verify hmac.compare_digest is used
# ---------------------------------------------------------------------------


def test_hmac_compare_digest_used():
    """Verify main.py imports hmac and uses compare_digest (not ==)."""
    import inspect

    import app.main as main_mod

    source = inspect.getsource(main_mod)
    assert "hmac" in source, "hmac module should be imported"
    assert "compare_digest" in source, "hmac.compare_digest should be used for constant-time comparison"


# ---------------------------------------------------------------------------
# 2. Security headers are present on responses
# ---------------------------------------------------------------------------


def test_security_headers_present(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """Verify responses include X-Frame-Options, X-Content-Type-Options, etc."""
    monkeypatch.delenv("HEPHAESTUS_DASHBOARD_PASSWORD", raising=False)
    response = client.get("/healthz")
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-XSS-Protection") == "1; mode=block"
    assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


# ---------------------------------------------------------------------------
# 3. Rate limiter blocks after 5 failed login attempts
# ---------------------------------------------------------------------------


def test_rate_limiter_blocks_after_5(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """Make 6 rapid login attempts, verify 429 on 6th.

    The auth middleware blocks unauthorized POSTs, so the rate limiter
    inside the login handler is only reached when requests pass middleware
    auth. We test the rate limiter function directly.
    """
    monkeypatch.setenv("HEPHAESTUS_DASHBOARD_PASSWORD", "test-secret-password")
    # Reset rate limiter state
    import app.main as main_mod

    main_mod._AUTH_RATE_LIMITS.clear()

    # Test the rate limiter directly (the handler is behind auth middleware)
    ip = "1.2.3.4"
    # 5 failures should not be limited yet
    for i in range(5):
        assert not main_mod._check_auth_rate_limit(ip), f"should not be limited at attempt {i+1}"
        main_mod._record_auth_failure(ip)

    # 6th check should be limited
    assert main_mod._check_auth_rate_limit(ip), "should be limited after 5 failures"


# ---------------------------------------------------------------------------
# 4. Rate limiter prunes old timestamps
# ---------------------------------------------------------------------------


def test_rate_limiter_prunes_old(monkeypatch: pytest.MonkeyPatch):
    """Verify old timestamps are cleaned up."""
    import app.main as main_mod

    main_mod._AUTH_RATE_LIMITS.clear()

    # Insert timestamps that are older than the window
    old_time = time.time() - main_mod._AUTH_RATE_WINDOW - 100
    main_mod._AUTH_RATE_LIMITS["test-ip"] = [old_time] * 10

    # Check rate limit should prune old entries and NOT be limited
    is_limited = main_mod._check_auth_rate_limit("test-ip")
    assert not is_limited, "Old timestamps should be pruned, so IP should not be limited"
    # The list should be empty after pruning
    assert len(main_mod._AUTH_RATE_LIMITS.get("test-ip", [])) == 0


# ---------------------------------------------------------------------------
# 5. WS auth rejects invalid tokens
# ---------------------------------------------------------------------------


def test_ws_auth_rejects_invalid(monkeypatch: pytest.MonkeyPatch):
    """Verify WS auth check rejects bad tokens."""
    monkeypatch.setenv("HEPHAESTUS_DASHBOARD_PASSWORD", "correct-password")
    from app.api.ws import _check_ws_auth

    ws = MagicMock()
    ws.query_params = {}
    ws.headers = {}

    # No token provided
    result = asyncio.run(_check_ws_auth(ws))
    assert result is False, "WS auth should reject when no token provided"

    # Wrong token
    ws.headers = {"authorization": "Bearer wrong-token"}
    result = asyncio.run(_check_ws_auth(ws))
    assert result is False, "WS auth should reject wrong token"

    # Correct token
    ws.headers = {"authorization": "Bearer correct-password"}
    result = asyncio.run(_check_ws_auth(ws))
    assert result is True, "WS auth should accept correct token"
