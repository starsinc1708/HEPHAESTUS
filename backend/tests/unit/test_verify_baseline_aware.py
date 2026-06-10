"""SMART-VERIFY: baseline-aware verify auto-detection.

A verify command that already FAILS on the clean baseline (a pre-existing red suite,
missing infra, or a platform-mismatched dependency) can never gate — it would block
every task regardless of the agent's change. The detector runs each candidate on the
baseline and keeps only the GREEN ones as the hard gate (`## commands`); red ones are
recorded under `## advisory` (visible, non-gating).
"""
from __future__ import annotations

import pathlib
import types

from app.services import project_memory as pm
from app.services.verify_detect import partition_by_baseline


def test_partition_splits_green_and_red(tmp_path: pathlib.Path) -> None:
    green, red = partition_by_baseline(tmp_path, ["shell:exit 0", "shell:exit 1"], timeout_sec=30)
    assert green == ["shell:exit 0"]
    assert red == ["shell:exit 1"]


def test_partition_missing_command_counts_as_red(tmp_path: pathlib.Path) -> None:
    # A non-existent program must be treated as red, never raise.
    green, red = partition_by_baseline(tmp_path, ["definitely-not-a-real-cmd-xyz"], timeout_sec=5)
    assert green == []
    assert red == ["definitely-not-a-real-cmd-xyz"]


def _ws(tmp_path: pathlib.Path) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id="9f3a1c20e4b57d61", repo_path=str(tmp_path),
        memory_dir=".hephaestus/memory", verify_timeout_sec=30,
    )


def test_init_verify_writes_only_green_as_gating(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.verify_detect.detect_verify_commands",
        lambda _p: ["shell:exit 0", "shell:exit 1"],
    )
    assert pm.init_verify_if_empty(_ws(tmp_path)) is True
    # Only the green command gates.
    assert pm.read_verify_commands(_ws(tmp_path)) == ["shell:exit 0"]
    # The red one is recorded as advisory (visible) but not gating.
    body = pm.read_doc(_ws(tmp_path), "verify") or ""
    assert "## advisory" in body
    assert "shell:exit 1" in body


def test_init_verify_all_red_leaves_no_gate(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.verify_detect.detect_verify_commands",
        lambda _p: ["shell:exit 1"],
    )
    assert pm.init_verify_if_empty(_ws(tmp_path)) is True
    # No gating commands → the permanently-red suite no longer blocks every task;
    # the diff-scoped test net still runs the files each change touches.
    assert pm.read_verify_commands(_ws(tmp_path)) == []
    assert "shell:exit 1" in (pm.read_doc(_ws(tmp_path), "verify") or "")


def test_init_verify_all_green_has_no_advisory(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.verify_detect.detect_verify_commands",
        lambda _p: ["shell:exit 0"],
    )
    assert pm.init_verify_if_empty(_ws(tmp_path)) is True
    assert pm.read_verify_commands(_ws(tmp_path)) == ["shell:exit 0"]
    assert "## advisory" not in (pm.read_doc(_ws(tmp_path), "verify") or "")
