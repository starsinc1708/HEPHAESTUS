"""Unit: config has no vendor agent defaults and no hardcoded Linux repo path."""
from __future__ import annotations


def test_no_vendor_agent_defaults() -> None:
    import importlib

    import app.config as cfg
    importlib.reload(cfg)
    eff = cfg._config_effective()
    blob = " ".join(str(v) for v in eff.values())
    for vendor in (
        "sisyphus", "atlas", "oracle", "librarian",
        "prometheus", "metis", "momus", "multimodal-looker", "sisyphus-junior",
    ):
        assert vendor not in blob, f"vendor default {vendor} still present"


def test_repo_default_not_hardcoded_linux(monkeypatch) -> None:
    import importlib
    monkeypatch.delenv("HEPHAESTUS_REPO", raising=False)
    import app.config as cfg
    importlib.reload(cfg)
    assert cfg.REPO != "/home/starsinc/hephaestus-repo"


def test_tier_presets_preserved() -> None:
    import app.config as cfg
    assert set(cfg.TIER_PRESETS) == {"strict", "standard", "permissive", "disabled"}
    assert cfg.TIER_PRESETS["standard"]["HEPHAESTUS_TIER1_APPROVE_THRESHOLD"] == "5"


def test_verify_and_agent_keys_whitelisted() -> None:
    import app.config as cfg
    for k in ("HEPHAESTUS_AGENT_PROVIDER", "HEPHAESTUS_AGENT_MODEL", "HEPHAESTUS_VERIFY_COMMANDS"):
        assert k in cfg.ALLOWED_CONFIG_KEYS
