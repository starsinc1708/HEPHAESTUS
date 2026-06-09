"""Unit tests for `_snapshot_revision` — per-revision history archive (history viewer §1).

HEPHAESTUS reuses ONE iter dir across every revision of a run: each revision overwrites
`output.primary.jsonl` and the whole `validation/` tree, so only the last revision
survives on disk. `_snapshot_revision` copies the just-finished attempt's artifacts to
an attempt-namespaced alias BEFORE the next revision overwrites them, while leaving the
canonical paths in place as the latest revision (additive, non-breaking).
"""

from __future__ import annotations

import json
import pathlib

from app.orchestrator.fsm import _snapshot_revision


def _write_primary(d: pathlib.Path, text: str) -> None:
    """Write a single stream-json text line to canonical output.primary.jsonl."""
    line = json.dumps({"type": "text", "text": text})
    (d / "output.primary.jsonl").write_text(line + "\n", encoding="utf-8")


def _write_validation(d: pathlib.Path, tag: str) -> None:
    """(Re)create a canonical validation/ tree carrying a revision tag."""
    vdir = d / "validation"
    (vdir / "layer1").mkdir(parents=True, exist_ok=True)
    (vdir / "layer3").mkdir(parents=True, exist_ok=True)
    (vdir / "layer1" / "correctness.jsonl").write_text(
        json.dumps({"tag": tag}) + "\n", encoding="utf-8"
    )
    (vdir / "layer3" / "final.json").write_text(
        json.dumps({"tag": tag}), encoding="utf-8"
    )


def _primary_text(p: pathlib.Path) -> str:
    return json.loads(p.read_text(encoding="utf-8").strip())["text"]


def _validation_tag(p: pathlib.Path) -> str:
    return json.loads(p.read_text(encoding="utf-8").strip())["tag"]


def test_r0_preserved_and_canonical_stays_after_revision(tmp_path: pathlib.Path) -> None:
    """r0 archive captures rev0; a simulated revision moves canonical to rev1 but the
    r0 archive still holds rev0 (history preserved while latest stays canonical)."""
    d = tmp_path / "iter-abc"
    d.mkdir()
    _write_primary(d, "rev0 work")
    _write_validation(d, "rev0")

    _snapshot_revision(d, 0)

    # Archive exists with rev0 content.
    r0 = d / "output.primary.r0.jsonl"
    assert r0.exists()
    assert _primary_text(r0) == "rev0 work"
    assert (d / "validation.r0" / "layer1" / "correctness.jsonl").exists()
    assert (d / "validation.r0" / "layer3" / "final.json").exists()
    assert _validation_tag(d / "validation.r0" / "layer3" / "final.json") == "rev0"

    # SIMULATE the revision overwriting canonical paths.
    _write_primary(d, "rev1 work")
    _write_validation(d, "rev1")

    # Canonical now holds rev1 (latest stays canonical).
    assert _primary_text(d / "output.primary.jsonl") == "rev1 work"
    assert _validation_tag(d / "validation" / "layer3" / "final.json") == "rev1"
    # History preserved: r0 archive still holds rev0.
    assert _primary_text(r0) == "rev0 work"
    assert _validation_tag(d / "validation.r0" / "layer3" / "final.json") == "rev0"


def test_latest_stays_canonical_across_two_revisions(tmp_path: pathlib.Path) -> None:
    """Two revisions: r0=rev0, r1=rev1, canonical=rev2; both validation archives exist."""
    d = tmp_path / "iter-xyz"
    d.mkdir()
    _write_primary(d, "rev0 work")
    _write_validation(d, "rev0")

    _snapshot_revision(d, 0)
    _write_primary(d, "rev1 work")
    _write_validation(d, "rev1")

    _snapshot_revision(d, 1)
    _write_primary(d, "rev2 work")
    _write_validation(d, "rev2")

    assert _primary_text(d / "output.primary.r0.jsonl") == "rev0 work"
    assert _primary_text(d / "output.primary.r1.jsonl") == "rev1 work"
    assert _primary_text(d / "output.primary.jsonl") == "rev2 work"

    assert (d / "validation.r0").is_dir()
    assert (d / "validation.r1").is_dir()
    assert _validation_tag(d / "validation.r0" / "layer3" / "final.json") == "rev0"
    assert _validation_tag(d / "validation.r1" / "layer3" / "final.json") == "rev1"
    assert _validation_tag(d / "validation" / "layer3" / "final.json") == "rev2"


def test_never_raises_on_missing_dir_or_files(tmp_path: pathlib.Path) -> None:
    """No-op on None; no-op + no archives when canonical artifacts are absent."""
    # None iter_dir is a silent no-op.
    _snapshot_revision(None, 0)

    empty = tmp_path / "iter-empty"
    empty.mkdir()
    # No output.primary.jsonl and no validation/ — must not raise, must create nothing.
    _snapshot_revision(empty, 0)
    assert not (empty / "output.primary.r0.jsonl").exists()
    assert not (empty / "validation.r0").exists()
    assert list(empty.iterdir()) == []


def test_idempotent_does_not_corrupt_first_archive(tmp_path: pathlib.Path) -> None:
    """A second snapshot for the same attempt is a no-op even if canonical changed —
    the existence guard keeps the original archive intact and never raises."""
    d = tmp_path / "iter-idem"
    d.mkdir()
    _write_primary(d, "rev0 work")
    _write_validation(d, "rev0")

    _snapshot_revision(d, 0)

    # Canonical changes between calls (as it would after a re-run).
    _write_primary(d, "rev1 work")
    _write_validation(d, "rev1")

    # Second call for the SAME attempt must not raise and must not overwrite r0.
    _snapshot_revision(d, 0)

    assert _primary_text(d / "output.primary.r0.jsonl") == "rev0 work"
    assert _validation_tag(d / "validation.r0" / "layer3" / "final.json") == "rev0"
