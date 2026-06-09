"""Funnel integration with a scripted fake AgentRunner (no opencode, no bash)."""

from __future__ import annotations

import json
import pathlib

import pytest

from app.core.validators import ValidationFunnel
from tests.conftest import make_repo_profile

pytestmark = pytest.mark.asyncio


def _lens_block(lens: str, verdict: str, conf: float = 0.9) -> str:
    return (
        f"VALIDATION_VERDICT_BEGIN\nlens: {lens}\nverdict: {verdict}\n"
        f"confidence: {conf}\nevidence: hunk 1\ntop_issues: none\n"
        f"reasoning: scripted {verdict}\nVALIDATION_VERDICT_END\n"
    )


def _arbiter_block(verdict: str) -> str:
    return (
        f"ARBITER_VERDICT_BEGIN\nverdict: {verdict}\n"
        f"dedup_findings: - none\nagree_with_lenses: agree\nreasoning: ok\nARBITER_VERDICT_END\n"
    )


def _final_block(gate: str, blocking: str = "none") -> str:
    return f"FINAL_GATE_BEGIN\ngate: {gate}\nblocking: {blocking}\nnotes: scripted\nFINAL_GATE_END\n"


async def test_pass_path(tmp_path, fake_agent_runner):
    iter_dir = tmp_path / "iter-0001"
    iter_dir.mkdir()
    scripts = {ln: _lens_block(ln, "approve") for ln in
               ("correctness", "tests", "security", "conventions", "scope")}
    scripts |= {"arbiter-0": _arbiter_block("approve"), "arbiter-1": _arbiter_block("approve"),
                "final": _final_block("pass")}
    runner = fake_agent_runner(scripts)
    ws = make_repo_profile(str(tmp_path))
    funnel = ValidationFunnel(ws, runner)
    vr = await funnel.run_funnel({"id": "x", "proposal": "p"},
                                 iter_dir=iter_dir, diff_text="diff", revision=0)
    assert vr.gate == "pass"
    assert (iter_dir / "validation" / "layer1" / "tests.json").exists()
    assert (iter_dir / "validation" / "layer3" / "final.json").exists()
    fd = json.loads((iter_dir / "validation" / "layer3" / "final.json").read_text())
    assert fd["gate"] == "pass"


async def test_needs_revision_when_lens_fails(tmp_path, fake_agent_runner):
    iter_dir = tmp_path / "iter-0002"
    iter_dir.mkdir()
    scripts = {ln: _lens_block(ln, "approve") for ln in
               ("correctness", "security", "conventions", "scope")}
    scripts["tests"] = _lens_block("tests", "needs_revision", 0.5)
    scripts |= {"arbiter-0": _arbiter_block("needs_revision"),
                "arbiter-1": _arbiter_block("needs_revision"),
                "final": _final_block("needs_revision", "tests: add a test")}
    runner = fake_agent_runner(scripts)
    ws = make_repo_profile(str(tmp_path))  # standard, t1=5 → 4 approve fails
    vr = await ValidationFunnel(ws, runner).run_funnel(
        {"id": "x", "proposal": "p"}, iter_dir=iter_dir, diff_text="d", revision=0)
    assert vr.gate == "needs_revision"
    assert any("tests" in b for b in vr.blocking)


async def test_disabled_short_circuits(tmp_path, fake_agent_runner):
    iter_dir = tmp_path / "iter-0003"
    iter_dir.mkdir()
    runner = fake_agent_runner({})
    ws = make_repo_profile(str(tmp_path), strictness="disabled")
    vr = await ValidationFunnel(ws, runner).run_funnel(
        {"id": "x"}, iter_dir=iter_dir, diff_text="d", revision=2)
    assert vr.gate == "pass"
    assert vr.revision == 2
    assert runner.calls == []  # AgentRunner never invoked


async def test_validators_fallback_to_primary(tmp_path, fake_agent_runner):
    """R3: empty validators pool falls back to [primary]*N — funnel still runs, not a silent pass."""
    iter_dir = tmp_path / "iter-0004"
    iter_dir.mkdir()
    scripts = {ln: _lens_block(ln, "approve") for ln in
               ("correctness", "tests", "security", "conventions", "scope")}
    scripts |= {"arbiter-0": _arbiter_block("approve"), "arbiter-1": _arbiter_block("approve"),
                "final": _final_block("pass")}
    runner = fake_agent_runner(scripts)
    ws = make_repo_profile(str(tmp_path), n_validators=0)  # validators empty → fallback to primary
    vr = await ValidationFunnel(ws, runner).run_funnel(
        {"id": "x", "proposal": "p"}, iter_dir=iter_dir, diff_text="d", revision=0)
    # all 5 lenses still ran (via primary fallback) and produced artifacts
    assert {ln for ln in runner.calls if ln in
            ("correctness", "tests", "security", "conventions", "scope")} == {
            "correctness", "tests", "security", "conventions", "scope"}
    assert vr.gate == "pass"


async def test_all_arbiters_errored_not_penalized(tmp_path, fake_agent_runner):
    """R20: if every arbiter errored (launch failure), L2 is not penalized — gate rests on L1+L3."""
    iter_dir = tmp_path / "iter-0005"
    iter_dir.mkdir()
    scripts = {ln: _lens_block(ln, "approve") for ln in
               ("correctness", "tests", "security", "conventions", "scope")}
    scripts |= {"final": _final_block("pass")}

    class _ErroringArbiterRunner(fake_agent_runner):  # fake_agent_runner is the class itself
        async def run(self, ref, *, prompt_file, cwd, output_path, timeout_sec):
            if "arbiter" in pathlib.Path(output_path).name:
                raise RuntimeError("arbiter launch failed")
            return await super().run(ref, prompt_file=prompt_file, cwd=cwd,
                                     output_path=output_path, timeout_sec=timeout_sec)

    err_runner = _ErroringArbiterRunner(scripts)
    ws = make_repo_profile(str(tmp_path))
    vr = await ValidationFunnel(ws, err_runner).run_funnel(
        {"id": "x", "proposal": "p"}, iter_dir=iter_dir, diff_text="d", revision=0)
    # L1 all-approve + L3 pass; L2 all-errored must NOT block
    assert vr.gate == "pass"
    assert not any("arbiters:" in b for b in vr.blocking)
