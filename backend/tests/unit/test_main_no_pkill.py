"""main.py must not pkill on shutdown nor require tmux on startup (D1)."""

from __future__ import annotations

import pathlib


def _main_src() -> str:
    here = pathlib.Path(__file__).resolve()
    return (here.parent.parent.parent / "app" / "main.py").read_text(encoding="utf-8")


def test_main_has_no_pkill():
    src = _main_src()
    assert "pkill" not in src
    assert '"tmux"' not in src


def test_main_cancels_via_process_manager():
    # Stage 1 already replaced pkill-shutdown with the cross-platform ProcessManager.
    assert "cancel_all" in _main_src()
