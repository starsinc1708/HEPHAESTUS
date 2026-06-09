"""_verify must not shell out to bash/verify.sh (Stage 3 cross-platform)."""

from __future__ import annotations

import pathlib
import re


def _fsm_src() -> str:
    here = pathlib.Path(__file__).resolve()
    fsm = here.parent.parent.parent / "app" / "orchestrator" / "fsm.py"
    return fsm.read_text(encoding="utf-8")


def test_fsm_has_no_bash_verify():
    src = _fsm_src()
    assert "verify.sh" not in src
    assert not re.search(r'"bash"', src)


def test_fsm_has_no_forbidden_tokens():
    src = _fsm_src()
    assert not re.findall(r"tmux|pgrep|pkill|tier-review\.sh|bash ", src)
