from app.models.validation import MergeRequest


def test_merge_request_defaults_and_aliases():
    r = MergeRequest.model_validate({"push": True, "aiResolve": False, "autoAccept": True})
    assert r.push is True and r.ai_resolve is False and r.auto_accept is True
    assert MergeRequest().ai_resolve is True  # default ON
