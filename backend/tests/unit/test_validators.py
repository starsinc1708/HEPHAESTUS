"""Unit tests for ValidationFunnel pure logic (no agent calls)."""

from __future__ import annotations

from types import SimpleNamespace

from app.core.validators import LENS_FOCUS, LENSES, ValidationFunnel


def _ws(strictness="standard", t1=5, t2=2, n_arbiters=2):
    review = SimpleNamespace(enabled=True, tier1_threshold=t1, tier2_threshold=t2, max_revisions=2)
    agents = SimpleNamespace(
        validators=[SimpleNamespace(provider="p", model="m", agent=f"v{i}") for i in range(5)],
        arbiters=[SimpleNamespace(provider="p", model="m", agent=f"a{i}") for i in range(n_arbiters)],
        final=SimpleNamespace(provider="p", model="m", agent="f"),
    )
    return SimpleNamespace(strictness=strictness, review=review, agents=agents)


def test_lenses_constant():
    assert LENSES == ("correctness", "tests", "security", "conventions", "scope")
    assert set(LENS_FOCUS) == set(LENSES)


def test_layer_sizes_standard(monkeypatch):
    monkeypatch.setattr(
        "app.core.validators._effective",
        lambda: {"HEPHAESTUS_TIER1_APPROVE_THRESHOLD": "5", "HEPHAESTUS_TIER2_APPROVE_THRESHOLD": "2"},
    )
    f = ValidationFunnel(_ws("standard"), runner=SimpleNamespace())
    lenses, m, t1, t2 = f._layer_sizes_for()
    assert lenses == ["correctness", "tests", "security", "conventions", "scope"]
    assert m == 2 and t1 == 5 and t2 == 2


def test_layer_sizes_permissive(monkeypatch):
    monkeypatch.setattr(
        "app.core.validators._effective",
        lambda: {"HEPHAESTUS_TIER1_APPROVE_THRESHOLD": "3", "HEPHAESTUS_TIER2_APPROVE_THRESHOLD": "1"},
    )
    f = ValidationFunnel(_ws("permissive", t1=3, t2=1, n_arbiters=1), runner=SimpleNamespace())
    lenses, m, t1, t2 = f._layer_sizes_for()
    assert lenses == ["correctness", "tests", "scope"]
    assert m == 1 and t1 == 3 and t2 == 1


def test_layer_sizes_for_clamps_threshold(monkeypatch):
    # strict preset says threshold 6, but only 5 lenses → clamp to 5
    monkeypatch.setattr(
        "app.core.validators._effective",
        lambda: {"HEPHAESTUS_TIER1_APPROVE_THRESHOLD": "6", "HEPHAESTUS_TIER2_APPROVE_THRESHOLD": "2"},
    )
    f = ValidationFunnel(_ws("strict"), runner=SimpleNamespace())
    lenses, m, t1, t2 = f._layer_sizes_for()
    assert len(lenses) == 5
    assert t1 == 5  # clamped from 6 to len(lenses)


def test_layer_sizes_disabled(monkeypatch):
    monkeypatch.setattr("app.core.validators._effective", lambda: {})
    f = ValidationFunnel(_ws("disabled"), runner=SimpleNamespace())
    lenses, m, t1, t2 = f._layer_sizes_for()
    assert lenses == [] and m == 0


from app.core.validators import _aggregate_layer1, _parse_lens_block  # noqa: E402
from app.models.validation import LensVerdict  # noqa: E402


def test_parse_lens_block_defensive_no_block():
    v = _parse_lens_block("the agent rambled and emitted no block", "tests")
    assert v.verdict == "needs_revision"
    assert v.confidence == 0.0
    assert v.lens == "tests"


def test_parse_lens_block_confidence_0_to_10_form():
    text = (
        "VALIDATION_VERDICT_BEGIN\n"
        "lens: correctness\nverdict: approve\nconfidence: 8\n"
        "evidence: hunk 1\ntop_issues: none\nreasoning: looks correct\n"
        "VALIDATION_VERDICT_END\n"
    )
    v = _parse_lens_block(text, "correctness")
    assert v.verdict == "approve"
    assert abs(v.confidence - 0.8) < 1e-9


def test_parse_lens_block_garbage_verdict_normalizes():
    text = (
        "VALIDATION_VERDICT_BEGIN\nlens: scope\nverdict: maybe-ok\nconfidence: 0.5\n"
        "reasoning: unclear\nVALIDATION_VERDICT_END\n"
    )
    v = _parse_lens_block(text, "scope")
    assert v.verdict == "needs_revision"


def test_aggregate_layer1_threshold():
    verdicts = [
        LensVerdict(lens=lens, verdict="approve", confidence=0.9, reasoning="ok")
        for lens in ("correctness", "tests", "security", "conventions")
    ] + [LensVerdict(lens="scope", verdict="needs_revision", confidence=0.6, reasoning="scope creep")]
    passed5, blocking5 = _aggregate_layer1(verdicts, threshold=5)
    assert passed5 is False
    passed4, _ = _aggregate_layer1(verdicts, threshold=4)
    assert passed4 is True
    assert any("scope" in b for b in blocking5)


def test_aggregate_layer1_high_conf_reject_blocks():
    verdicts = [
        LensVerdict(lens=lens, verdict="approve", confidence=0.9, reasoning="ok")
        for lens in ("correctness", "tests", "security", "conventions")
    ] + [LensVerdict(lens="scope", verdict="reject", confidence=0.8, reasoning="broke API")]
    passed, blocking = _aggregate_layer1(verdicts, threshold=4)
    assert passed is False  # high-conf reject overrides count
    assert any("scope" in b for b in blocking)
