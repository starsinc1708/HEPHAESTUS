from app.models.merge import MergeDecision, MergeJob, MergeJobStatus


def test_mergejob_camelcase_roundtrip():
    job = MergeJob(
        id="merge-0001", branch="auto/x", base_branch="main",
        status=MergeJobStatus.RESOLVED, decision=MergeDecision.AI_MERGED,
        resolved_files=["a.py"], verify_ok=True, worktree_branch="hephaestus/merge/x",
        base_sha="abc123", item_id="x",
    )
    d = job.model_dump(by_alias=True)
    assert d["baseBranch"] == "main"
    assert d["resolvedFiles"] == ["a.py"]
    assert d["verifyOk"] is True
    assert d["worktreeBranch"] == "hephaestus/merge/x"
    assert d["baseSha"] == "abc123"
    assert MergeJob.model_validate(d).status is MergeJobStatus.RESOLVED


def test_agentsconfig_merge_role_optional():
    from app.models.workspace import AgentRef, AgentsConfig
    cfg = AgentsConfig(primary=AgentRef(provider="anthropic", model="m"),
                       fallback=AgentRef(provider="anthropic", model="m"))
    assert cfg.merge is None
    cfg2 = AgentsConfig.model_validate({
        "primary": {"provider": "a", "model": "m"},
        "fallback": {"provider": "a", "model": "m"},
        "merge": {"provider": "a", "model": "haiku"},
    })
    assert cfg2.merge.model == "haiku"


def test_item_merge_resolution_alias():
    from app.models.domain import Item
    it = Item(id="x", title="t", status="pending")
    it.merge_resolution = "ai"
    assert it.model_dump(by_alias=True)["mergeResolution"] == "ai"
