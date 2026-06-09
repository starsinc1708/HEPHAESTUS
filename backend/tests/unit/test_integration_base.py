"""Unit tests for IntegrationProvider protocol and ProviderCapabilities."""

from __future__ import annotations

from app.services.integrations.base import ProviderCapabilities


def test_capabilities_defaults_and_roundtrip() -> None:
    c = ProviderCapabilities()
    assert c.issues is False and c.pull_requests is False
    c2 = ProviderCapabilities(issues=True, pull_requests=True)
    d = c2.model_dump(by_alias=True)
    assert d["pullRequests"] is True
