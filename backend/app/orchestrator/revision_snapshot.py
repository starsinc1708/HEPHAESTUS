"""Revision snapshot helper — archive the current iteration output before a revision overwrites it."""

from __future__ import annotations

import logging
import pathlib
import shutil

log = logging.getLogger("hephaestus.orchestrator")


def _snapshot_revision(iter_dir: pathlib.Path | None, prev_attempt: int) -> None:
    """Archive the current implementer output + validation funnel artifacts under an
    attempt-namespaced alias BEFORE the next revision overwrites them. The canonical
    output.primary.jsonl / validation/ stay in place as the latest revision (additive,
    non-breaking). Best-effort: never raises, so a copy failure can't crash a run."""
    if iter_dir is None:
        return
    try:
        primary = iter_dir / "output.primary.jsonl"
        if primary.exists():
            dest = iter_dir / f"output.primary.r{prev_attempt}.jsonl"
            if not dest.exists():
                shutil.copy2(primary, dest)
        vdir = iter_dir / "validation"
        if vdir.is_dir():
            vdest = iter_dir / f"validation.r{prev_attempt}"
            if not vdest.exists():
                shutil.copytree(vdir, vdest)
    except Exception:
        log.warning("revision snapshot failed for %s r%d", iter_dir, prev_attempt, exc_info=True)
