"""Decisions log — ported from dashboard/server.py:341-363.

TSV append and read for the human/machine decision trail stored in
state/decisions.log.
"""

from __future__ import annotations

import time
from typing import Any

from app.core.state import _state_dir


def _append_decision(actor: str, action: str, branch: str, result: str, extra: str | None = None) -> None:
    sd = _state_dir()  # active workspace state dir (legacy fallback)
    sd.mkdir(parents=True, exist_ok=True)
    line = "\t".join(
        [
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            actor,
            action,
            branch,
            result,
            extra or "",
        ]
    )
    with (sd / "decisions.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _read_decisions(limit: int = 40) -> list[dict[str, Any]]:
    p = _state_dir() / "decisions.log"
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
        for ln in lines:
            parts = ln.split("\t")
            if len(parts) >= 5:
                out.append(
                    {
                        "ts": parts[0],
                        "actor": parts[1],
                        "action": parts[2],
                        "branch": parts[3],
                        "result": parts[4],
                        "extra": (parts[5] if len(parts) > 5 else ""),
                    }
                )
    except Exception:
        pass
    return out
