"""Connection + provider catalog for the agent-settings redesign (global model connections)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Connection(BaseModel):
    """A globally-stored, reusable model endpoint (provider + engine + model + env)."""
    model_config = ConfigDict(populate_by_name=True)
    id: str
    label: str
    provider: str                      # "anthropic" | "deepseek" | "glm" | "openai" | ...
    engine: str                        # "claude" | "opencode" | "codex"
    model: str
    auth_method: str = Field("api_key", alias="authMethod")
    env: dict[str, str] = Field(default_factory=dict)
    status: str = "untested"           # untested | connected | failed
    last_tested_at: str | None = Field(None, alias="lastTestedAt")
    last_error: str | None = Field(None, alias="lastError")


class Combo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    engine: str                                   # claude | opencode | codex
    auth_method: str = Field(alias="authMethod")  # subscription | api_key
    models: list[str]
    base_url: str | None = Field(None, alias="baseUrl")
    key_env: str | None = Field(None, alias="keyEnv")
    login_cmd: str | None = Field(None, alias="loginCmd")


class ProviderCatalogEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    provider: str
    label: str
    blurb: str
    combos: list[Combo]


PROVIDER_CATALOG: list[ProviderCatalogEntry] = [
    ProviderCatalogEntry(provider="anthropic", label="Claude (Anthropic)",
        blurb="Claude Max/Pro subscription via `claude` login (no key). Or an ANTHROPIC API key.",
        combos=[
            Combo(engine="claude", auth_method="subscription",
                  models=["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-3-5"],
                  login_cmd="claude   (then /login)"),
            Combo(engine="claude", auth_method="api_key", key_env="ANTHROPIC_API_KEY",
                  models=["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-3-5"]),
            Combo(engine="opencode", auth_method="api_key", key_env="ANTHROPIC_API_KEY",
                  models=["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-3-5"]),
        ]),
    ProviderCatalogEntry(provider="glm", label="GLM (z.ai coding plan)",
        blurb="z.ai coding plan — subscription token (ANTHROPIC-compatible endpoint).",
        combos=[Combo(engine="claude", auth_method="api_key", key_env="ANTHROPIC_AUTH_TOKEN",
                      base_url="https://api.z.ai/api/anthropic", models=["glm-4.6", "glm-4.5"])]),
    ProviderCatalogEntry(provider="deepseek", label="DeepSeek",
        blurb="DeepSeek API key (ANTHROPIC-compatible endpoint), or via opencode.",
        combos=[
            Combo(engine="claude", auth_method="api_key", key_env="ANTHROPIC_AUTH_TOKEN",
                  base_url="https://api.deepseek.com/anthropic",
                  models=["deepseek-chat", "deepseek-reasoner"]),
            Combo(engine="opencode", auth_method="api_key", key_env="DEEPSEEK_API_KEY",
                  models=["deepseek-chat", "deepseek-reasoner"]),
        ]),
    ProviderCatalogEntry(provider="openai", label="OpenAI / GPT",
        blurb="ChatGPT subscription via `codex` login, or an OpenAI API key (codex/opencode).",
        combos=[
            # codex+subscription = ChatGPT-account auth: it rejects gpt-5-codex/o4-mini/gpt-4o
            # ("model not supported when using Codex with a ChatGPT account", verified live
            # 2026-06-07). gpt-5.5 is codex's current default and works on the ChatGPT plan.
            Combo(engine="codex", auth_method="subscription",
                  models=["gpt-5.5", "gpt-5-codex", "o4-mini"], login_cmd="codex login"),
            # codex+api_key = OpenAI API key auth: the gpt-5-codex/o4-mini/gpt-4o ids apply here.
            Combo(engine="codex", auth_method="api_key", key_env="OPENAI_API_KEY",
                  models=["gpt-5-codex", "o4-mini", "gpt-4o"]),
            Combo(engine="opencode", auth_method="api_key", key_env="OPENAI_API_KEY",
                  models=["gpt-4o", "o4-mini"]),
        ]),
    ProviderCatalogEntry(provider="gemini", label="Google Gemini",
        blurb="Gemini via opencode — `opencode auth login` or a Google API key.",
        combos=[
            Combo(engine="opencode", auth_method="subscription",
                  models=["gemini-2.5-pro", "gemini-2.5-flash"], login_cmd="opencode auth login"),
            Combo(engine="opencode", auth_method="api_key", key_env="GEMINI_API_KEY",
                  models=["gemini-2.5-pro", "gemini-2.5-flash"]),
        ]),
    ProviderCatalogEntry(provider="openrouter", label="OpenRouter (gateway)",
        blurb="OpenRouter API key — access to many models; model as `vendor/model`.",
        combos=[Combo(engine="opencode", auth_method="api_key", key_env="OPENROUTER_API_KEY",
                      models=["anthropic/claude-sonnet-4-5", "openai/gpt-4o", "google/gemini-2.5-pro"])]),
    ProviderCatalogEntry(provider="copilot", label="GitHub Copilot",
        blurb="GitHub Copilot subscription via `opencode auth login` (OAuth).",
        combos=[Combo(engine="opencode", auth_method="subscription",
                      models=["gpt-4o", "claude-sonnet-4-5"], login_cmd="opencode auth login")]),
    ProviderCatalogEntry(provider="ollama", label="Ollama (local)",
        blurb="Self-hosted models via Ollama (OpenAI-compatible local endpoint). No API key needed for local use.",
        combos=[Combo(engine="opencode", auth_method="api_key", key_env="OPENAI_API_KEY",
                      base_url="http://localhost:11434/v1",
                      models=["llama3.1", "qwen2.5", "mistral", "gemma2"])]),
]


def find_combo(provider: str, engine: str, auth_method: str) -> Combo | None:
    for e in PROVIDER_CATALOG:
        if e.provider == provider:
            for c in e.combos:
                if c.engine == engine and c.auth_method == auth_method:
                    return c
    return None


def build_env(provider: str, engine: str, auth_method: str, model: str, key: str) -> dict[str, str]:
    """Subprocess env for a connection. Subscription → no secret. Raises ValueError on bad combo."""
    combo = find_combo(provider, engine, auth_method)
    if combo is None:
        raise ValueError(f"unsupported combo: {provider}/{engine}/{auth_method}")
    if auth_method == "subscription":
        return {"ANTHROPIC_MODEL": model} if engine == "claude" else {}
    # api_key
    if engine == "claude":
        env: dict[str, str] = {"ANTHROPIC_AUTH_TOKEN": key, "ANTHROPIC_MODEL": model}
        if combo.base_url:
            env["ANTHROPIC_BASE_URL"] = combo.base_url
        return env
    if engine == "codex":
        return {"OPENAI_API_KEY": key}
    # opencode engine
    oc_env: dict[str, str] = {}
    if combo.base_url:
        oc_env["OPENAI_BASE_URL"] = combo.base_url
    if key:  # skip key env when empty (Ollama local = no auth)
        oc_env[combo.key_env or "API_KEY"] = key
    return oc_env


_SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def mask_env(env: dict[str, str]) -> dict[str, str]:
    """Mask secret-looking values (…KEY/…TOKEN) for API responses; keep URLs/models visible."""
    out: dict[str, str] = {}
    for k, v in env.items():
        if any(h in k.upper() for h in _SECRET_HINTS) and v:
            out[k] = (v[:3] + "***" + v[-2:]) if len(v) > 6 else "***"
        else:
            out[k] = v
    return out
