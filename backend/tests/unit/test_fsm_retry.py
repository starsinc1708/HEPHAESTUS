"""Tests for FSM transient retry logic."""
from __future__ import annotations

import asyncio
import pathlib
import types
from typing import Any
from unittest.mock import MagicMock

from app.orchestrator.fsm import OrchestratorFSM


def _make_ws(tmp: pathlib.Path, **overrides: Any) -> types.SimpleNamespace:
    """Minimal duck-typed workspace."""
    defaults = dict(
        id="ws-test",
        name="test",
        repo_path=str(tmp),
        base_branch="main",
        remote="origin",
        branch_prefix="auto",
        engine="opencode",
        engine_env={},
        engine_profiles=[],
        verify_source="agent",
        verify_timeout_sec=60,
        memory_dir=".hephaestus/memory",
        autopush=False,
        strictness="disabled",
        agents=types.SimpleNamespace(
            primary=types.SimpleNamespace(provider="test", model="test", agent=None, engine_profile=None),
            fallback=types.SimpleNamespace(provider="test", model="test", agent=None, engine_profile=None),
            use_models=False,
            validators=[], arbiters=[], final=None, planner=None, merge=None,
        ),
        review=types.SimpleNamespace(max_revisions=2),
        scope_guard="off",
        max_transient_retries=2,
        transient_backoff_sec=0,  # no wait in tests
    )
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


def test_retry_on_transient_success(tmp_path: pathlib.Path) -> None:
    fsm = OrchestratorFSM()
    fsm._ws = _make_ws(tmp_path)  # type: ignore[assignment]
    fsm.iter_dir = tmp_path / "iter-0001"
    fsm.iter_dir.mkdir()

    # Stub FSM._persist_item_fields
    fsm._persist_item_fields = MagicMock()

    # Mock _run_opencode: first call returns 1 (transient), second returns 0 (success)
    call_count = 0
    async def mock_run_opencode(item: dict[str, Any], prompt: str) -> int | None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return 1  # transient error (output file empty by default)
        return 0

    fsm._run_opencode = mock_run_opencode  # type: ignore[assignment]

    rc = asyncio.run(fsm._run_opencode_with_retry({"id": "test"}, "prompt"))
    assert rc == 0
    assert call_count == 2
    fsm._persist_item_fields.assert_called_once()


def test_no_retry_on_non_transient(tmp_path: pathlib.Path) -> None:
    fsm = OrchestratorFSM()
    fsm._ws = _make_ws(tmp_path)  # type: ignore[assignment]
    fsm.iter_dir = tmp_path / "iter-0001"
    fsm.iter_dir.mkdir()

    # Stub FSM._persist_item_fields
    fsm._persist_item_fields = MagicMock()

    # Mock _run_opencode: returns 1 but we will simulate substantial output (non-transient)
    async def mock_run_opencode(item: dict[str, Any], prompt: str) -> int | None:
        # Create output file with some content to make it non-transient
        out_file = fsm.iter_dir / "output.primary.jsonl"
        out_file.write_text("x" * 1000, encoding="utf-8")
        return 1

    fsm._run_opencode = mock_run_opencode  # type: ignore[assignment]

    rc = asyncio.run(fsm._run_opencode_with_retry({"id": "test"}, "prompt"))
    assert rc == 1
    # Should not retry because output is > 500 bytes (non-transient)
    fsm._persist_item_fields.assert_not_called()


def test_max_retries_respected(tmp_path: pathlib.Path) -> None:
    fsm = OrchestratorFSM()
    fsm._ws = _make_ws(tmp_path, max_transient_retries=1)  # type: ignore[assignment]
    fsm.iter_dir = tmp_path / "iter-0001"
    fsm.iter_dir.mkdir()

    # Stub FSM._persist_item_fields
    fsm._persist_item_fields = MagicMock()

    call_count = 0
    async def mock_run_opencode(item: dict[str, Any], prompt: str) -> int | None:
        nonlocal call_count
        call_count += 1
        return 1  # always transient fail

    fsm._run_opencode = mock_run_opencode  # type: ignore[assignment]

    rc = asyncio.run(fsm._run_opencode_with_retry({"id": "test"}, "prompt"))
    assert rc == 1
    # 1 initial attempt + 1 retry = 2 total runs
    assert call_count == 2
