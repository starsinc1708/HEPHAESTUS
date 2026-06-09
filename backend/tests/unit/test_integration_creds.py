"""Unit tests for the integration credential store (creds.py)."""

from __future__ import annotations

import pathlib

import pytest

import app.services.integrations.creds as creds


@pytest.fixture(autouse=True)
def _store(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(creds, "_STORE", tmp_path / "integrations.json")


def test_set_get_clear_github() -> None:
    assert creds.get_cred("github") is None
    creds.set_cred("github", "ghp_secrettoken123")
    cred = creds.get_cred("github")
    assert cred is not None
    assert cred["token"] == "ghp_secrettoken123"  # raw kept server-side
    assert cred["status"] == "untested"
    creds.clear_cred("github")
    assert creds.get_cred("github") is None


def test_set_gitlab_defaults_host() -> None:
    creds.set_cred("gitlab", "glpat_x")
    assert creds.get_cred("gitlab")["host"] == "https://gitlab.com"  # type: ignore[index]
    creds.set_cred("gitlab", "glpat_y", host="https://gitlab.example.com")
    assert creds.get_cred("gitlab")["host"] == "https://gitlab.example.com"  # type: ignore[index]


def test_set_status_preserves_token() -> None:
    creds.set_cred("github", "ghp_keepme")
    creds.set_status("github", "connected", error=None, tested_at="2026-06-08T00:00:00Z")
    cred = creds.get_cred("github")
    assert cred is not None
    assert cred["token"] == "ghp_keepme"
    assert cred["status"] == "connected"
    assert cred["lastTestedAt"] == "2026-06-08T00:00:00Z"
    assert cred["lastError"] is None


def test_effective_token_store_only() -> None:
    assert creds.effective_token("github") is None
    creds.set_cred("github", "ghp_eff")
    assert creds.effective_token("github") == "ghp_eff"


def test_mask_token() -> None:
    assert creds.mask_token(None) is None
    assert creds.mask_token("") is None
    assert creds.mask_token("short") == "***"
    masked = creds.mask_token("ghp_supersecretvalue")
    assert masked is not None
    assert "supersecret" not in masked
    assert masked.startswith("ghp") and masked.endswith("ue")


def test_list_masked_shape() -> None:
    creds.set_cred("github", "ghp_supersecretvalue")
    creds.set_status("github", "connected", error=None, tested_at="2026-06-08T00:00:00Z")
    rows = {r["name"]: r for r in creds.list_masked()}
    assert set(rows) == {"github", "gitlab"}
    gh = rows["github"]
    assert gh["connected"] is True
    assert gh["available"] is True
    assert gh["token"] is not None and "supersecretvalue" not in gh["token"]
    # gitlab not connected → masked token None, default host present, available False
    gl = rows["gitlab"]
    assert gl["connected"] is False
    assert gl["available"] is False
    assert gl["token"] is None
    assert gl["host"] == "https://gitlab.com"


def test_list_masked_never_leaks_raw_token() -> None:
    creds.set_cred("github", "ghp_rawsecret999")
    blob = str(creds.list_masked())
    assert "ghp_rawsecret999" not in blob


def test_corrupt_store_is_empty(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "integrations.json"
    p.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(creds, "_STORE", p)
    assert creds.get_cred("github") is None  # never raises
    rows = {r["name"]: r for r in creds.list_masked()}
    assert rows["github"]["connected"] is False


def test_non_dict_entries_ignored(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "integrations.json"
    p.write_text('{"github": "not-a-dict", "gitlab": {"token": "t"}}', encoding="utf-8")
    monkeypatch.setattr(creds, "_STORE", p)
    assert creds.get_cred("github") is None
    assert creds.get_cred("gitlab") == {"token": "t"}
