#!/usr/bin/env python3
"""Entry point for the orchestrator process."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys

# Ensure we're in the right directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.orchestrator.fsm import OrchestratorFSM  # noqa: E402

log = logging.getLogger("hephaestus.orchestrator")


async def main() -> None:
    fsm = OrchestratorFSM()

    # Handle SIGTERM / SIGINT gracefully
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):  # Windows
            loop.add_signal_handler(sig, fsm.request_stop)

    log.info("Orchestrator starting")
    await fsm.run()
    log.info("Orchestrator stopped")


if __name__ == "__main__":
    # Robust loop logging: write directly to <workspace-state>/loop.log via a FileHandler
    # (the parent's stdout redirect to the same file is unreliable for a detached child on
    # Windows, which left loop.log empty and made failures un-diagnosable).
    _handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        from app.core.state import _state_dir

        _lp = _state_dir() / "loop.log"
        _lp.parent.mkdir(parents=True, exist_ok=True)
        _handlers.append(logging.FileHandler(_lp, encoding="utf-8"))
    except Exception:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=_handlers,
    )
    asyncio.run(main())
