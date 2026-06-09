"""Unit tests for integration credential verification (verify.py)."""

from __future__ import annotations

from typing import Any

import pytest

import app.services.integrations.verify as verify


class _Resp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def _patch_get(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any], resp: Any) -> None:
    def fake_get(url: str, **kw: Any) -> Any:
        captured["url"] = url
        captured["headers"] = kw.get("headers", {})
        if isinstance(resp, Exception):
            raise resp
        return resp

    monkeypatch.setattr("httpx.get", fake_get)


# ---------------------------------------------------------------------------
# Host normalization
# ---------------------------------------------------------------------------


def test_normalize_host_default() -> None:
    assert verify.normalize_gitlab_host(None) == "https://gitlab.com"
    assert verify.normalize_gitlab_host("") == "https://gitlab.com"
    assert verify.normalize_gitlab_host("   ") == "https://gitlab.com"


def test_normalize_host_strips_trailing_slash() -> None:
    assert verify.normalize_gitlab_host("https://gitlab.example.com/") == "https://gitlab.example.com"


def test_normalize_host_rejects_non_https() -> None:
    assert verify.normalize_gitlab_host("http://gitlab.example.com") is None
    assert verify.normalize_gitlab_host("ftp://x") is None
    assert verify.normalize_gitlab_host("gitlab.example.com") is None  # no scheme


def test_normalize_host_rejects_traversal_and_paths() -> None:
    assert verify.normalize_gitlab_host("https://x/../y") is None
    assert verify.normalize_gitlab_host("https://x/api/v4") is None  # non-root path
    assert verify.normalize_gitlab_host("https://x y") is None  # space


def test_normalize_host_rejects_userinfo() -> None:
    # user:pass@host would exfiltrate the PAT to an attacker host (SSRF/leak).
    assert verify.normalize_gitlab_host("https://attacker:cred@10.0.0.1") is None
    assert verify.normalize_gitlab_host("https://user@gitlab.example.com") is None


def test_normalize_host_keeps_port() -> None:
    assert verify.normalize_gitlab_host("https://gitlab.example.com:8443") == "https://gitlab.example.com:8443"


# ---------------------------------------------------------------------------
# GitHub verify
# ---------------------------------------------------------------------------


def test_github_200_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    cap: dict[str, Any] = {}
    _patch_get(monkeypatch, cap, _Resp(200))
    status, err = verify.verify_credential("github", token="ghp_x")
    assert status == "connected"
    assert err is None
    assert cap["url"] == "https://api.github.com/user"
    assert cap["headers"]["Authorization"] == "Bearer ghp_x"


def test_github_401_failed_message(monkeypatch: pytest.MonkeyPatch) -> None:
    cap: dict[str, Any] = {}
    _patch_get(monkeypatch, cap, _Resp(401))
    status, err = verify.verify_credential("github", token="bad")
    assert status == "failed"
    assert err is not None and "invalid" in err.lower()


def test_github_network_error_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    cap: dict[str, Any] = {}
    _patch_get(monkeypatch, cap, httpx.ConnectError("boom"))
    status, err = verify.verify_credential("github", token="x")
    assert status == "failed"
    assert err is not None  # friendly, never raises


# ---------------------------------------------------------------------------
# GitLab verify (uses host + PRIVATE-TOKEN)
# ---------------------------------------------------------------------------


def test_gitlab_uses_host_and_private_token(monkeypatch: pytest.MonkeyPatch) -> None:
    cap: dict[str, Any] = {}
    _patch_get(monkeypatch, cap, _Resp(200))
    status, err = verify.verify_credential(
        "gitlab", token="glpat_x", host="https://gitlab.example.com"
    )
    assert status == "connected"
    assert cap["url"] == "https://gitlab.example.com/api/v4/user"
    assert cap["headers"]["PRIVATE-TOKEN"] == "glpat_x"


def test_gitlab_defaults_host(monkeypatch: pytest.MonkeyPatch) -> None:
    cap: dict[str, Any] = {}
    _patch_get(monkeypatch, cap, _Resp(200))
    verify.verify_credential("gitlab", token="glpat_x")
    assert cap["url"] == "https://gitlab.com/api/v4/user"


def test_unknown_provider_failed() -> None:
    status, err = verify.verify_credential("bitbucket", token="x")
    assert status == "failed"
    assert err is not None
