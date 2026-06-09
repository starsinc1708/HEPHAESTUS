"""SEC-003: _config_overrides() filters unknown keys against ALLOWED_CONFIG_KEYS."""
from __future__ import annotations

import json
import pathlib

import app.config as cfg


def _write_config(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ── 1. Only known keys → all preserved ────────────────────────────────────


def test_known_keys_preserved(tmp_path: pathlib.Path, monkeypatch) -> None:
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_OVERRIDE", config_file)

    _write_config(config_file, {"HEPHAESTUS_REPO": "x", "HEPHAESTUS_MAX_ITER": "42"})

    result = cfg._config_overrides()
    assert result == {"HEPHAESTUS_REPO": "x", "HEPHAESTUS_MAX_ITER": "42"}


# ── 2. Known + unknown keys → unknowns silently dropped ───────────────────


def test_unknown_keys_dropped(tmp_path: pathlib.Path, monkeypatch) -> None:
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_OVERRIDE", config_file)

    _write_config(
        config_file,
        {"HEPHAESTUS_REPO": "x", "EVIL_INJECTION": "pwned", "__dunder__": "nope"},
    )

    result = cfg._config_overrides()
    assert result == {"HEPHAESTUS_REPO": "x"}
    assert "EVIL_INJECTION" not in result
    assert "__dunder__" not in result


# ── 3. Only unknown keys → empty dict returned ────────────────────────────


def test_only_unknown_keys_returns_empty(tmp_path: pathlib.Path, monkeypatch) -> None:
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_OVERRIDE", config_file)

    _write_config(config_file, {"HACKED": "1", "BAD_KEY": "2"})

    result = cfg._config_overrides()
    assert result == {}


# ── 4. Config file doesn't exist → empty dict ─────────────────────────────


def test_missing_config_file(tmp_path: pathlib.Path, monkeypatch) -> None:
    config_file = tmp_path / "nonexistent" / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_OVERRIDE", config_file)

    result = cfg._config_overrides()
    assert result == {}


# ── 5. Malformed JSON → empty dict (exception swallowed) ──────────────────


def test_malformed_json(tmp_path: pathlib.Path, monkeypatch) -> None:
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_OVERRIDE", config_file)

    config_file.write_text("{invalid json!!", encoding="utf-8")

    result = cfg._config_overrides()
    assert result == {}


# ── 6. Empty config {} → empty dict ──────────────────────────────────────


def test_empty_config(tmp_path: pathlib.Path, monkeypatch) -> None:
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_OVERRIDE", config_file)

    _write_config(config_file, {})

    result = cfg._config_overrides()
    assert result == {}
