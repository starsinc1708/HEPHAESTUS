"""HEPHAESTUS_REVISION_MAX allowed; thresholds present in effective config defaults."""

from __future__ import annotations

from app.config import ALLOWED_CONFIG_KEYS, _config_effective


def test_revision_max_allowed():
    assert "HEPHAESTUS_REVISION_MAX" in ALLOWED_CONFIG_KEYS


def test_effective_has_threshold_defaults():
    eff = _config_effective()
    assert "HEPHAESTUS_TIER1_APPROVE_THRESHOLD" in eff
    assert "HEPHAESTUS_TIER2_APPROVE_THRESHOLD" in eff
    assert int(eff["HEPHAESTUS_TIER1_APPROVE_THRESHOLD"]) >= 1


def test_effective_has_revision_max_default():
    eff = _config_effective()
    assert "HEPHAESTUS_REVISION_MAX" in eff
    assert int(eff["HEPHAESTUS_REVISION_MAX"]) >= 0
