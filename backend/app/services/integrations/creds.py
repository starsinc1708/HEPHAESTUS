"""Stored integration credentials: ``state/integrations.json``.

Single source of truth for GitHub/GitLab Personal Access Tokens entered in the UI
(no env files). Tokens are stored plaintext on disk — same posture as
``connections.json`` — but **masked in every API response** and never logged.
Never crashes on a corrupt store (→ treated as empty).

Shape::

    { "github": {"token": "...", "status": "connected", "lastError": null,
                 "lastTestedAt": "..."},
      "gitlab": {"token": "...", "host": "https://gitlab.com", "status": "...", ...} }
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import STATE_DIR
from app.core.state import _atomic_write

log = logging.getLogger("hephaestus.backend.integrations.creds")

_STORE = STATE_DIR / "integrations.json"

#: Providers that support a stored credential (UI-connect, v2 #8).
KNOWN_PROVIDERS: tuple[str, ...] = ("github", "gitlab")
DEFAULT_GITLAB_HOST = "https://gitlab.com"


# ---------------------------------------------------------------------------
# Disk I/O (never-crash)
# ---------------------------------------------------------------------------


def _read_all() -> dict[str, dict[str, Any]]:
    """Return the whole store as ``{name: cred}``. Corrupt/missing → ``{}``."""
    if not _STORE.exists():
        return {}
    try:
        data = json.loads(_STORE.read_text(encoding="utf-8"))
    except Exception:
        log.warning("integrations.json unreadable — treating as empty", exc_info=True)
        return {}
    if not isinstance(data, dict):
        return {}
    # Keep only well-formed dict entries; tolerate junk without raising.
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, dict)}


def _write_all(data: dict[str, dict[str, Any]]) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(_STORE, json.dumps(data, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def get_cred(name: str) -> dict[str, Any] | None:
    """Return the raw stored cred for *name* (token plaintext), or ``None``."""
    return _read_all().get(name)


def set_cred(name: str, token: str, host: str | None = None) -> None:
    """Store *token* (and *host* for GitLab); resets status to ``untested``."""
    data = _read_all()
    cred = data.get(name) or {}
    cred["token"] = token
    if name == "gitlab":
        cred["host"] = host or DEFAULT_GITLAB_HOST
    cred["status"] = "untested"
    cred["lastError"] = None
    data[name] = cred
    _write_all(data)


def clear_cred(name: str) -> None:
    """Erase the stored cred for *name* (disconnect). No-op if absent."""
    data = _read_all()
    if name in data:
        del data[name]
        _write_all(data)


def set_status(name: str, status: str, *, error: str | None, tested_at: str | None) -> None:
    """Update the verify result for *name*, preserving the stored token/host."""
    data = _read_all()
    cred = data.get(name)
    if cred is None:
        return
    cred["status"] = status
    cred["lastError"] = error
    cred["lastTestedAt"] = tested_at
    data[name] = cred
    _write_all(data)


# ---------------------------------------------------------------------------
# Accessors used by the provider services
# ---------------------------------------------------------------------------


def effective_token(name: str) -> str | None:
    """Return the token to use for *name* (stored only — the store is the source)."""
    cred = _read_all().get(name)
    if cred and cred.get("token"):
        return str(cred["token"])
    return None


def effective_host(name: str) -> str:
    """Return the API host for *name* (GitLab: stored host or the default)."""
    cred = _read_all().get(name)
    if cred and cred.get("host"):
        return str(cred["host"])
    return DEFAULT_GITLAB_HOST


# ---------------------------------------------------------------------------
# Masking + listing for API responses
# ---------------------------------------------------------------------------


def mask_token(token: str | None) -> str | None:
    """Mask a secret token for API responses; ``None``/empty → ``None``."""
    if not token:
        return None
    return (token[:3] + "***" + token[-2:]) if len(token) > 6 else "***"


def list_masked() -> list[dict[str, Any]]:
    """Return per-provider connection state for the API (token masked).

    Always lists every known provider so the UI can render a connect card even
    when nothing is stored yet.
    """
    data = _read_all()
    out: list[dict[str, Any]] = []
    for name in KNOWN_PROVIDERS:
        cred = data.get(name) or {}
        token = cred.get("token")
        has_token = bool(token)
        status = cred.get("status") or ("disconnected" if not has_token else "untested")
        host = (cred.get("host") or DEFAULT_GITLAB_HOST) if name == "gitlab" else None
        out.append(
            {
                "name": name,
                "available": has_token,
                "connected": status == "connected",
                "status": status,
                "hasToken": has_token,
                "token": mask_token(token),
                "host": host,
                "lastError": cred.get("lastError"),
                "lastTestedAt": cred.get("lastTestedAt"),
            }
        )
    return out
