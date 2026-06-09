"""Unit: hephaestus_home() resolves registry root cross-platform."""
from __future__ import annotations

import pathlib

import pytest


def test_hephaestus_home_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEPHAESTUS_HOME", raising=False)
    from app.services.hephaestus_home import hephaestus_home

    h = hephaestus_home()
    assert isinstance(h, pathlib.Path)
    assert h.name == ".hephaestus"
    assert h == pathlib.Path.home() / ".hephaestus"


def test_hephaestus_home_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    monkeypatch.setenv("HEPHAESTUS_HOME", str(tmp_path / "reg"))
    from app.services.hephaestus_home import hephaestus_home

    assert hephaestus_home() == (tmp_path / "reg")