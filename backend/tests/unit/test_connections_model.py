import pytest

from app.models.connections import PROVIDER_CATALOG, build_env, find_combo, mask_env


def test_catalog_has_expected_providers():
    provs = {e.provider for e in PROVIDER_CATALOG}
    assert {"anthropic", "glm", "deepseek", "openai", "gemini", "openrouter", "copilot"} <= provs


def test_find_combo_and_bad_combo():
    assert find_combo("anthropic", "claude", "subscription") is not None
    assert find_combo("glm", "opencode", "api_key") is None  # glm is claude-only


def test_build_env_subscription_stores_no_secret():
    env = build_env("anthropic", "claude", "subscription", "claude-opus-4-5", key="")
    assert env == {"ANTHROPIC_MODEL": "claude-opus-4-5"}           # no token at all
    assert build_env("openai", "codex", "subscription", "gpt-5-codex", key="") == {}
    assert build_env("copilot", "opencode", "subscription", "gpt-4o", key="") == {}


def test_build_env_api_key_per_engine():
    assert build_env("deepseek", "claude", "api_key", "deepseek-chat", "sk-K") == {
        "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
        "ANTHROPIC_AUTH_TOKEN": "sk-K", "ANTHROPIC_MODEL": "deepseek-chat"}
    assert build_env("openai", "codex", "api_key", "gpt-5-codex", "sk-K") == {"OPENAI_API_KEY": "sk-K"}
    assert build_env("openrouter", "opencode", "api_key", "x/y", "sk-K") == {"OPENROUTER_API_KEY": "sk-K"}


def test_build_env_anthropic_api_key_omits_empty_base_url():
    assert build_env("anthropic", "claude", "api_key", "claude-sonnet-4-5", "sk-ant-K") == {
        "ANTHROPIC_AUTH_TOKEN": "sk-ant-K", "ANTHROPIC_MODEL": "claude-sonnet-4-5"}


def test_build_env_rejects_bad_combo():
    with pytest.raises(ValueError):
        build_env("glm", "opencode", "api_key", "glm-4.6", "k")


def test_mask_env_hides_secrets_keeps_url():
    masked = mask_env({"ANTHROPIC_BASE_URL": "https://x", "ANTHROPIC_AUTH_TOKEN": "sk-abcdef1234"})
    assert masked["ANTHROPIC_BASE_URL"] == "https://x"
    assert masked["ANTHROPIC_AUTH_TOKEN"].startswith("sk-") and "***" in masked["ANTHROPIC_AUTH_TOKEN"]
    assert "abcdef" not in masked["ANTHROPIC_AUTH_TOKEN"]
