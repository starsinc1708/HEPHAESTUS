"""Unit tests for Ollama catalog entry and env routing."""
from app.models.connections import PROVIDER_CATALOG, build_env, find_combo


class TestOllamaCatalog:
    def test_ollama_in_catalog(self):
        provs = {e.provider for e in PROVIDER_CATALOG}
        assert "ollama" in provs

    def test_ollama_has_opencode_combo(self):
        combo = find_combo("ollama", "opencode", "api_key")
        assert combo is not None
        assert combo.base_url == "http://localhost:11434/v1"

    def test_ollama_build_env_sets_openai_base_url(self):
        env = build_env("ollama", "opencode", "api_key", "llama3", "ollama")
        assert env.get("OPENAI_BASE_URL") == "http://localhost:11434/v1"
        assert "ANTHROPIC_BASE_URL" not in env

    def test_ollama_build_env_empty_key_no_key_env(self):
        """Ollama without key: no API key env var set."""
        env = build_env("ollama", "opencode", "api_key", "llama3", "")
        assert env.get("OPENAI_BASE_URL") == "http://localhost:11434/v1"
        # Should NOT set OPENAI_API_KEY="" — empty key means no auth
        assert "OPENAI_API_KEY" not in env

    def test_ollama_models_include_examples(self):
        combo = find_combo("ollama", "opencode", "api_key")
        assert combo is not None
        assert len(combo.models) > 0

    def test_existing_providers_unchanged(self):
        """Regression: existing provider combos and build_env still work identically."""
        # anthropic subscription
        assert find_combo("anthropic", "claude", "subscription") is not None
        # deepseek via claude engine
        env = build_env("deepseek", "claude", "api_key", "deepseek-chat", "sk-K")
        assert env.get("ANTHROPIC_BASE_URL") == "https://api.deepseek.com/anthropic"
        assert "OPENAI_BASE_URL" not in env
        # openai via codex
        env = build_env("openai", "codex", "api_key", "gpt-5-codex", "sk-K")
        assert env == {"OPENAI_API_KEY": "sk-K"}
        # openrouter via opencode (has NO base_url, so no OPENAI_BASE_URL either)
        env = build_env("openrouter", "opencode", "api_key", "x/y", "sk-K")
        assert env == {"OPENROUTER_API_KEY": "sk-K"}
