"""build_revision_prompt renders blocking + lens findings + attempt/max."""

from __future__ import annotations

from types import SimpleNamespace

from app.core.validators import build_revision_prompt
from app.models.validation import LensVerdict, ValidationResult


def test_revision_prompt_contains_blocking():
    vr = ValidationResult(
        layer1=[
            LensVerdict(lens="tests", verdict="needs_revision", confidence=0.4, reasoning="no test for empty input"),
            LensVerdict(lens="scope", verdict="approve", confidence=0.9, reasoning="ok"),
        ],
        layer2_summary=[],
        gate="needs_revision",
        blocking=["tests: no test for empty input"],
        revision=1,
    )
    item = {"id": "item-9", "proposal": "Add retry", "acceptance": "Has a test"}
    ws = SimpleNamespace(review=SimpleNamespace(max_revisions=2))
    text = build_revision_prompt(item, vr, attempt=1, ws=ws)
    assert "no test for empty input" in text
    assert "tests:" in text
    assert "1 of 2" in text or "attempt 1" in text.lower()
    assert "Add retry" in text
    assert "Has a test" in text
    # approved lens must NOT appear in the lens-findings digest
    assert "scope: ok" not in text
