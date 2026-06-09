"""Unit tests for the provider registry and new config keys."""

from __future__ import annotations

import pytest


def test_registry_includes_connected(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.integrations.creds as creds
    import app.services.integrations.registry as reg

    monkeypatch.setattr(creds, "_STORE", tmp_path / "integrations.json")

    # Nothing connected → empty registry.
    assert reg.provider_registry() == {}

    # Connecting a GitHub PAT makes it available; Linear no longer exists.
    creds.set_cred("github", "ghp_token")
    r = reg.provider_registry()
    assert "github" in r
    assert "linear" not in r
    assert reg.get_provider("github") is not None


def test_config_provider_key_in_allowed() -> None:
    from app.config import ALLOWED_CONFIG_KEYS

    assert "HEPHAESTUS_DEFAULT_PROVIDER" in ALLOWED_CONFIG_KEYS
