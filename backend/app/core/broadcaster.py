"""Background task that polls state and broadcasts changes over WebSocket.

Uses a hash-based diff so unchanged state is never re-sent to connected
clients.  Runs as an ``asyncio.Task`` managed by the FastAPI lifespan.
"""

from __future__ import annotations

import asyncio
import logging

from app.services.ws_manager import manager

log = logging.getLogger("hephaestus.backend.broadcaster")

_DEFAULT_INTERVAL = 1.0  # seconds


async def state_broadcaster(interval: float = _DEFAULT_INTERVAL) -> None:
    """Periodically broadcast state to the ``board`` room subscribers.

    A cheap ``hash(str(...))`` comparison on the items list ensures we only
    send a WebSocket frame when the state has actually changed.
    """
    last_hash: int | None = None
    while True:
        try:
            # Backpressure: skip state building if no clients connected
            n_clients = sum(len(conns) for conns in manager._rooms.values())
            if n_clients == 0:
                log.debug("skipping broadcast, no clients")
                await asyncio.sleep(interval)
                continue

            from app.core.iters import build_state

            state = build_state()
            current_hash = hash(str(state.get("items", [])))
            if current_hash != last_hash:
                await manager.broadcast("board", {"type": "state_update", "data": state})
                last_hash = current_hash
        except asyncio.CancelledError:
            raise
        except Exception:
            # build_state may fail if state dir doesn't exist yet during startup.
            log.error("state_broadcaster tick failed", exc_info=True)
        await asyncio.sleep(interval)
