"""Regression guards for the goal-planner / scan-decomposer prompt guidance.

These lock in the anti-over-decomposition + dependency-assignment instructions so a
future prompt edit cannot silently drop them and reintroduce the failure modes:
  - the planner splitting one coherent change into micro-tasks (incl. setup-only
    fragments, separate test-only tasks, and "run the gates" pseudo-tasks);
  - the decomposer leaving `dependsOn` empty even when one task needs another's code,
    which breaks under branch isolation.
"""
from __future__ import annotations

import pathlib

_PROMPTS = pathlib.Path(__file__).resolve().parents[3] / "prompts"


def test_goal_planner_prompt_discourages_over_decomposition() -> None:
    text = (_PROMPTS / "goal-planner.md").read_text(encoding="utf-8")
    # Still templated + protocol intact.
    for token in ("{{goal_title}}", "{{goal_description}}", "PLAN_BEGIN", "PLAN_END"):
        assert token in text
    # Bias toward the fewest, self-contained tasks.
    assert "FEWEST" in text
    assert "independently-mergeable" in text or "independently mergeable" in text
    # Each task carries its own test.
    assert "own test" in text.lower()
    # No process/gate pseudo-tasks; no setup-only / test-only fragment tasks.
    assert "gate tasks" in text.lower()
    assert "setup-only" in text.lower()
    assert "test-only" in text.lower()


def test_scan_decomposer_prompt_requires_real_dependencies() -> None:
    text = (_PROMPTS / "scan-decomposer.md").read_text(encoding="utf-8")
    for token in ("{{proposals_json}}", "DECOMPOSE_BEGIN", "DECOMPOSE_END"):
        assert token in text
    # Branch-isolation rationale + the "set every real prerequisite" mandate must survive.
    assert "isolation" in text.lower() or "branch-isolated" in text.lower()
    assert "every real prerequisite" in text.lower()
    # Must still warn against inventing edges from mere shared files.
    assert "same file" in text.lower()
