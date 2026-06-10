"""Regression: prompt directories must resolve under LOOP_HOME/prompts.

Bug: validators.py and profiler.py derived the prompts dir from ``__file__`` assuming the
repo layout (``backend/app/...`` → repo root → ``/prompts``). When the backend is installed
as a wheel (the Docker image: ``site-packages/app/...``) the relative depth differs, so the
path overshot to ``<python_prefix>/prompts`` (e.g. ``/usr/local/lib/python3.12/prompts``),
which doesn't exist — crashing the tier-review validate phase with FileNotFoundError. The
canonical base is ``LOOP_HOME / "prompts"`` (== repo root in dev, ``/app/prompts`` in Docker).
"""
from __future__ import annotations

from app.config import LOOP_HOME


def test_validators_prompts_dir_is_loop_home_prompts() -> None:
    from app.core import validators

    assert validators._PROMPTS_DIR == LOOP_HOME / "prompts"
    # The exact file whose absence crashed the run must exist under the canonical base.
    assert (validators._PROMPTS_DIR / "validate-final.md").exists()


def test_canonical_prompts_present_under_loop_home() -> None:
    base = LOOP_HOME / "prompts"
    # Files loaded by validators.py (tier review) and profiler.py — all must live here so
    # they're found in an installed/Docker deployment, not just the repo checkout.
    for name in ("validate-final.md", "validate-lens.md", "validate-arbiter.md", "profiler.md"):
        assert (base / name).exists(), f"missing prompt under LOOP_HOME/prompts: {name}"
