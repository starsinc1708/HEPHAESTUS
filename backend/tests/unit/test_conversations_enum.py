"""Unit tests for _task_conversations — enumeration of iterations × stages × agent-runs.

Builds the tree the conversation viewer needs: per iteration, the implement stage
(implementer runs across revisions) and the validate stage (layer1 lenses / layer2
arbiters / layer3 final across revisions). Every agent's `stream` round-trips into the
B2 conversation endpoint (stream + ".jsonl" is the real file under the iter dir).
"""

from __future__ import annotations

import json
import pathlib

import app.core.state as state_mod
from app.core.conversations import _task_conversations


def _claude_line(model: str = "claude-x", text: str = "hi") -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {"model": model, "content": [{"type": "text", "text": text}]},
        }
    )


def _seed_full_history(tmp_path: pathlib.Path) -> pathlib.Path:
    """One iter dir with 3 implementer revisions + archived (r0) and canonical validation."""
    d = tmp_path / "iter-0001"
    d.mkdir(parents=True)
    # Implementer: two archived revisions + canonical (latest)
    (d / "output.primary.r0.jsonl").write_text(_claude_line() + "\n", encoding="utf-8")
    (d / "output.primary.r1.jsonl").write_text(_claude_line() + "\n", encoding="utf-8")
    (d / "output.primary.jsonl").write_text(_claude_line() + "\n" + _claude_line() + "\n", encoding="utf-8")

    # Archived validation (revision 0 — sent back)
    (d / "validation.r0" / "layer1").mkdir(parents=True)
    (d / "validation.r0" / "layer1" / "correctness.jsonl").write_text(_claude_line() + "\n", encoding="utf-8")
    (d / "validation.r0" / "layer1" / "correctness.json").write_text(
        json.dumps({"lens": "correctness", "verdict": "needs_revision"}), encoding="utf-8"
    )
    (d / "validation.r0" / "layer3").mkdir(parents=True)
    (d / "validation.r0" / "layer3" / "final.jsonl").write_text(_claude_line() + "\n", encoding="utf-8")
    (d / "validation.r0" / "layer3" / "final.json").write_text(
        json.dumps({"gate": "needs_revision"}), encoding="utf-8"
    )

    # Canonical validation (latest — passed)
    (d / "validation" / "layer1").mkdir(parents=True)
    (d / "validation" / "layer1" / "correctness.jsonl").write_text(_claude_line() + "\n", encoding="utf-8")
    (d / "validation" / "layer1" / "correctness.json").write_text(
        json.dumps({"lens": "correctness", "verdict": "approve"}), encoding="utf-8"
    )
    (d / "validation" / "layer2").mkdir(parents=True)
    (d / "validation" / "layer2" / "arbiter-0.jsonl").write_text(_claude_line() + "\n", encoding="utf-8")
    (d / "validation" / "layer2" / "arbiter-0.json").write_text(
        json.dumps({"arbiter": 0, "verdict": "approve"}), encoding="utf-8"
    )
    # noise that must be skipped (prompt + parsed-verdict siblings are not streams)
    (d / "validation" / "layer2" / "arbiter-0.prompt.md").write_text("prompt", encoding="utf-8")
    (d / "validation" / "layer3").mkdir(parents=True)
    (d / "validation" / "layer3" / "final.jsonl").write_text(_claude_line() + "\n", encoding="utf-8")
    (d / "validation" / "layer3" / "final.json").write_text(json.dumps({"gate": "pass"}), encoding="utf-8")
    return d


def _seed_state(tmp_path: pathlib.Path, items: list[dict]) -> None:
    (tmp_path / "work-state.json").write_text(json.dumps({"items": items}), encoding="utf-8")


def _find_agent(stage: dict, stream: str) -> dict | None:
    return next((a for a in stage["agents"] if a["stream"] == stream), None)


def test_full_enumeration_with_history(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path, raising=False)
    d = _seed_full_history(tmp_path)
    _seed_state(tmp_path, [{"id": "task-1", "title": "t", "status": "done", "lastIter": "iter-0001"}])

    res = _task_conversations("task-1")
    assert res["ok"] is True
    assert res["itemId"] == "task-1"
    assert len(res["iterations"]) == 1
    it = res["iterations"][0]
    assert it["dir"] == "iter-0001"
    assert it["attempts"] == 3

    stages = {st["stage"]: st for st in it["stages"]}
    impl = stages["implement"]
    assert len(impl["agents"]) == 3
    r0 = _find_agent(impl, "output.primary.r0")
    r1 = _find_agent(impl, "output.primary.r1")
    can = _find_agent(impl, "output.primary")
    assert r0 is not None and r1 is not None and can is not None
    assert r0["revision"] == 0 and r0["current"] is False and r0["status"] == "needs_revision"
    assert r1["revision"] == 1 and r1["current"] is False
    assert can["revision"] == 2 and can["current"] is True and can["status"] == "done"
    for a in impl["agents"]:
        assert a["role"] == "implementer"
        assert a["model"] == "claude-x"
        assert a["messages"] >= 1

    val = stages["validate"]
    a_r0_corr = _find_agent(val, "validation.r0/layer1/correctness")
    a_r0_final = _find_agent(val, "validation.r0/layer3/final")
    a_corr = _find_agent(val, "validation/layer1/correctness")
    a_arb = _find_agent(val, "validation/layer2/arbiter-0")
    a_final = _find_agent(val, "validation/layer3/final")
    assert a_r0_corr is not None
    assert a_r0_corr["role"] == "validator:correctness"
    assert a_r0_corr["revision"] == 0 and a_r0_corr["status"] == "needs_revision"
    assert a_r0_final is not None
    assert a_r0_final["role"] == "final" and a_r0_final["status"] == "needs_revision"
    assert a_corr is not None
    assert a_corr["revision"] == 1 and a_corr["current"] is True and a_corr["status"] == "approve"
    assert a_arb is not None
    assert a_arb["role"] == "arbiter" and a_arb["status"] == "approve"
    assert a_final is not None
    assert a_final["role"] == "final" and a_final["status"] == "pass"

    # No prompt/json files leaked in as streams.
    streams = {a["stream"] for a in val["agents"]}
    assert not any(s.endswith(".prompt") or s.endswith(".json") for s in streams)

    # Round-trip guarantee: every stream + ".jsonl" is a real file under the iter dir.
    for st in it["stages"]:
        for a in st["agents"]:
            fp = d / f"{a['stream']}.jsonl"
            assert fp.exists(), f"stream {a['stream']} does not round-trip to a file"


def test_unknown_task_returns_not_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path, raising=False)
    _seed_state(tmp_path, [])
    res = _task_conversations("nope")
    assert res["ok"] is False
    assert "error" in res


def test_canonical_only_no_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", tmp_path, raising=False)
    d = tmp_path / "iter-0002"
    d.mkdir(parents=True)
    (d / "output.primary.jsonl").write_text(_claude_line() + "\n", encoding="utf-8")
    _seed_state(tmp_path, [{"id": "task-9", "title": "t", "status": "in_progress", "lastIter": "iter-0002"}])

    res = _task_conversations("task-9")
    assert res["ok"] is True
    assert len(res["iterations"]) == 1
    it = res["iterations"][0]
    stages = {st["stage"]: st for st in it["stages"]}
    impl = stages["implement"]
    assert len(impl["agents"]) == 1
    a = impl["agents"][0]
    assert a["stream"] == "output.primary"
    assert a["revision"] == 0 and a["current"] is True
    # No validate stage (zero agents → omitted).
    assert "validate" not in stages
