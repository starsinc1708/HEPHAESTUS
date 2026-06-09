"""Credential verification for UI-connected integrations.

A connect/verify makes a real, short-timeout API call and maps the result to
``(status, error)``. Never raises — a network failure or bad token becomes a
``failed`` status with a friendly Russian message (the UI surfaces it verbatim).
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from app.services.integrations.creds import DEFAULT_GITLAB_HOST

log = logging.getLogger("hephaestus.backend.integrations.verify")

_TIMEOUT_SEC = 10.0

_ERR_BAD_TOKEN = "invalid token"
_ERR_UNAVAILABLE = "service unavailable"
_ERR_UNKNOWN = "unknown provider"


def normalize_gitlab_host(host: str | None) -> str | None:
    """Validate + normalize a GitLab base URL. Returns ``None`` when unsafe.

    Rules: default to ``https://gitlab.com`` when empty; require an ``https``
    scheme and a netloc; reject path traversal, embedded whitespace, and any
    non-root path/query/fragment (prevents building a poisoned API URL).
    """
    if host is None or not host.strip():
        return DEFAULT_GITLAB_HOST
    h = host.strip().rstrip("/")
    if ".." in h or any(c in h for c in " \t\r\n\x00"):
        return None
    parsed = urlparse(h)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    # Reject userinfo (user:pass@host) — it would send the PAT to an attacker
    # host and persist into GITLAB_HOST. Reject non-root path/query/fragment.
    if parsed.username is not None or parsed.password is not None:
        return None
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return None
    # Rebuild from hostname (+ port) only — drops any userinfo / case / IDN noise.
    hostname = parsed.hostname
    if not hostname:
        return None
    netloc = f"{hostname}:{parsed.port}" if parsed.port else hostname
    return f"https://{netloc}"


def _classify(status_code: int) -> tuple[str, str | None]:
    if 200 <= status_code < 300:
        return "connected", None
    if status_code in (401, 403):
        return "failed", _ERR_BAD_TOKEN
    return "failed", f"verification error (HTTP {status_code})"


def verify_credential(
    name: str, *, token: str, host: str | None = None
) -> tuple[str, str | None]:
    """Verify *token* against the provider. Returns ``(status, error)``.

    GitHub → ``GET https://api.github.com/user`` (``Authorization: Bearer``).
    GitLab → ``GET {host}/api/v4/user`` (``PRIVATE-TOKEN``).
    """
    if name == "github":
        url = "https://api.github.com/user"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }
    elif name == "gitlab":
        base = normalize_gitlab_host(host)
        if base is None:
            return "failed", "invalid GitLab URL (https required)"
        url = f"{base}/api/v4/user"
        headers = {"PRIVATE-TOKEN": token}
    else:
        return "failed", _ERR_UNKNOWN

    try:
        resp = httpx.get(url, headers=headers, timeout=_TIMEOUT_SEC)
    except httpx.HTTPError as exc:
        log.warning("verify %s failed (network): %s", name, type(exc).__name__)
        return "failed", _ERR_UNAVAILABLE
    except Exception as exc:  # noqa: BLE001 — never crash the endpoint
        log.warning("verify %s failed (unexpected): %s", name, type(exc).__name__)
        return "failed", _ERR_UNAVAILABLE
    return _classify(resp.status_code)
