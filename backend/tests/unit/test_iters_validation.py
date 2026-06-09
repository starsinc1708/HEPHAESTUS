"""_iter_details surfaces validation/layer3/final.json as 'validation' (umbrella §4.4)."""

from __future__ import annotations

import json

import app.core.state as state_mod
from app.core.iters import _iter_details


def test_iter_details_includes_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path, raising=False)
    d = tmp_path / "iter-0001"
    (d / "validation" / "layer3").mkdir(parents=True)
    (d / "validation" / "layer3" / "final.json").write_text(
        json.dumps({"gate": "pass", "blocking": [], "revision": 0}))
    (d / "validation" / "layer1").mkdir(parents=True)
    (d / "validation" / "layer1" / "tests.json").write_text(
        json.dumps({"lens": "tests", "verdict": "approve", "confidence": 0.9, "reasoning": "ok"}))
    info = _iter_details("iter-0001")
    assert info["ok"] is True
    assert info["validation"]["gate"] == "pass"
    assert info["validation"]["layer1"][0]["lens"] == "tests"


def test_iter_details_without_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path, raising=False)
    d = tmp_path / "iter-0002"
    d.mkdir(parents=True)
    info = _iter_details("iter-0002")
    assert info["ok"] is True
    assert "validation" not in info
