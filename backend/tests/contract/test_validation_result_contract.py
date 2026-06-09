"""Contract: ValidationResult / MergePreflightResponse camelCase serialization."""

from __future__ import annotations

from app.models.validation import (
    LensVerdict,
    MergePreflightResponse,
    MergeRequest,
    ValidationResult,
)


def test_validation_result_dumps_camelcase():
    vr = ValidationResult(
        layer1=[LensVerdict(lens="correctness", verdict="approve", confidence=0.9, reasoning="ok")],
        layer2_summary=[{"arbiter": "a1", "verdict": "approve"}],
        gate="pass",
        blocking=[],
        revision=0,
    )
    d = vr.model_dump(by_alias=True)
    assert set(d.keys()) == {"layer1", "layer2Summary", "gate", "blocking", "revision"}
    assert d["layer1"][0]["lens"] == "correctness"


def test_validation_result_roundtrip_from_final_decision():
    fixture = {
        "layer1": [{"lens": "tests", "verdict": "needs_revision", "confidence": 0.4, "reasoning": "no test"}],
        "layer2Summary": [],
        "gate": "needs_revision",
        "blocking": ["tests: no test"],
        "revision": 1,
    }
    vr = ValidationResult.model_validate(fixture)
    assert vr.gate == "needs_revision"
    assert vr.revision == 1
    assert vr.layer1[0].lens == "tests"


def test_merge_preflight_response_camelcase():
    pf = MergePreflightResponse(
        clean_tree=True, verify_green=True, validation_passed=False,
        loop_active=False, base_branch="main", conflicts=[], ok=False,
    )
    d = pf.model_dump(by_alias=True)
    assert d["cleanTree"] is True
    assert d["verifyGreen"] is True
    assert d["validationPassed"] is False
    assert d["loopActive"] is False
    assert d["baseBranch"] == "main"
    assert d["ok"] is False


def test_merge_preflight_response_loop_active_defaults_false():
    # loop_active is optional with a False default (R11); omitting it must not error.
    pf = MergePreflightResponse(
        clean_tree=True, verify_green=True, validation_passed=True,
        base_branch="main", conflicts=[], ok=True,
    )
    assert pf.loop_active is False
    assert pf.model_dump(by_alias=True)["loopActive"] is False


def test_merge_request_default_push_false():
    assert MergeRequest().push is False
    assert MergeRequest(push=True).push is True
