"""WebSocket ConnectionManager with rooms, bounded queues, and drop-oldest policy."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("hephaestus.backend.ws")

# Maximum items per-client send queue. When full, oldest messages are dropped
# so the client always receives the freshest data.
_MAX_QUEUE = 100

# Heartbeat interval in seconds.
HEARTBEAT_INTERVAL = 15


class ConnectionManager:
    """Manages WebSocket connections organised into named rooms.

    Each connected client gets a bounded ``asyncio.Queue``.  ``broadcast``
    pushes a JSON-serialisable dict into every queue in a room; when a queue
    is full the *oldest* item is discarded (drop-tail) so that new data is
    never lost.  A per-room background task drains each client's queue and
    sends the data over the wire.
    """

    MAX_CONNECTIONS = 100

    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = {}
        self._buffers: dict[WebSocket, asyncio.Queue[str]] = {}
        self._sender_tasks: dict[WebSocket, asyncio.Task[None]] = {}

    def _total_connections(self) -> int:
        return sum(len(conns) for conns in self._rooms.values())

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self, ws: WebSocket, room: str = "global") -> None:
        """Accept *ws*, add to *room*, create bounded queue + sender task."""
        if self._total_connections() >= self.MAX_CONNECTIONS:
            await ws.close(code=1013)
            log.warning("ws connection rejected: over limit (%d)", self.MAX_CONNECTIONS)
            return
        await ws.accept()
        self._rooms.setdefault(room, set()).add(ws)
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=_MAX_QUEUE)
        self._buffers[ws] = q
        self._sender_tasks[ws] = asyncio.create_task(self._sender(ws, q))
        log.info("ws connected to room=%s total_in_room=%d", room, len(self._rooms.get(room, set())))

    async def disconnect(self, ws: WebSocket, room: str = "global") -> None:
        """Remove *ws* from *room*, cancel sender, cleanup resources."""
        conns = self._rooms.get(room)
        if conns:
            conns.discard(ws)
            if not conns:
                del self._rooms[room]
        self._buffers.pop(ws, None)
        task = self._sender_tasks.pop(ws, None)
        if task is not None:
            task.cancel()
        log.info("ws disconnected from room=%s", room)

    # ------------------------------------------------------------------
    # Broadcasting
    # ------------------------------------------------------------------

    async def broadcast(self, room: str, message: dict[str, Any]) -> None:
        """Send *message* to **all** connections in *room*.

        If a client's queue is full the oldest queued item is dropped so the
        newest data is never discarded.
        """
        payload = json.dumps(message, default=str)
        for ws in list(self._rooms.get(room, set())):
            q = self._buffers.get(ws)
            if q is None:
                continue
            while q.full():
                # Drop oldest to make room for the new message.
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    break
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(payload)  # extremely unlikely after the drain loop above

    async def broadcast_state(self) -> None:
        """Build and broadcast a full state snapshot to the ``board`` room."""
        try:
            from app.core.iters import build_state

            state = build_state()
            await self.broadcast("board", {"type": "state_update", "data": state})
        except Exception:
            log.exception("broadcast_state failed")

    async def broadcast_iter_event(self, dirname: str, event: dict[str, Any]) -> None:
        """Push a single iteration event to ``iter:<dirname>`` subscribers."""
        room = f"iter:{dirname}"
        await self.broadcast(room, {"type": "iter_event", "data": event})

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def send_heartbeat(self, ws: WebSocket) -> bool:
        """Send a ping frame. Returns ``False`` if the send failed."""
        try:
            await ws.send_json({"type": "ping", "ts": time.time()})
            return True
        except Exception:
            log.debug("send_heartbeat failed", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Internal sender task
    # ------------------------------------------------------------------

    async def _sender(self, ws: WebSocket, q: asyncio.Queue[str]) -> None:
        """Drain *q* and send each payload over *ws*.

        Runs as a per-connection ``asyncio.Task`` so that slow clients never
        block the broadcast loop.
        """
        try:
            while True:
                payload = await q.get()
                try:
                    await ws.send_text(payload)
                except Exception:
                    log.debug("ws send failed — client likely disconnected")
                    break
        except asyncio.CancelledError:
            pass


# Module-level singleton — imported by the WS router and the broadcaster.
manager = ConnectionManager()
