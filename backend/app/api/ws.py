"""WebSocket endpoints for real-time live updates.

Three rooms:
  ``/ws/board``  – full state snapshots (dashboard)
  ``/ws/iter/{dirname}`` – per-iteration JSONL event stream
  ``/ws/loop``   – loop phase transitions

Each endpoint keeps the connection alive with a periodic heartbeat ping.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.ws_manager import HEARTBEAT_INTERVAL, manager

log = logging.getLogger("hephaestus.backend.ws")

router = APIRouter()


async def _check_ws_auth(ws: WebSocket) -> bool:
    """Validate WebSocket auth if HEPHAESTUS_DASHBOARD_PASSWORD is set.
    Returns True if auth passes (or is disabled), False otherwise.
    """
    password = os.environ.get("HEPHAESTUS_DASHBOARD_PASSWORD", "")
    if not password:
        return True
    token = ws.query_params.get("token", "") or ws.headers.get("authorization", "")
    if token.startswith("Bearer "):
        token = token[len("Bearer "):]
    return bool(hmac.compare_digest(token, password))


async def _heartbeat_loop(ws: WebSocket) -> None:
    """Periodically send ``{"type":"ping"}`` and expect ``{"type":"pong"}``."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        if not await manager.send_heartbeat(ws):
            break


async def _recv_loop(ws: WebSocket) -> None:
    """Read client messages. Handles ``ping`` → ``pong`` and ignores unknown types."""
    while True:
        raw = await ws.receive_text()
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        msg_type = msg.get("type")
        if msg_type == "pong":
            # Client responded to our heartbeat — nothing to do.
            pass
        elif msg_type == "ping":
            await ws.send_json({"type": "pong"})
        # Unknown types are silently ignored.


# ------------------------------------------------------------------
# Board room — full state updates
# ------------------------------------------------------------------


@router.websocket("/ws/board")
async def ws_board(ws: WebSocket) -> None:
    """Board room — receives full state update broadcasts."""
    if not await _check_ws_auth(ws):
        await ws.close(code=4001)
        return
    await manager.connect(ws, "board")
    hb = asyncio.create_task(_heartbeat_loop(ws))
    try:
        await _recv_loop(ws)
    except WebSocketDisconnect:
        log.debug("ws_board client disconnected", exc_info=True)
    except Exception:
        log.debug("ws_board connection error", exc_info=True)
    finally:
        hb.cancel()
        await manager.disconnect(ws, "board")


# ------------------------------------------------------------------
# Iter room — per-iteration events
# ------------------------------------------------------------------


@router.websocket("/ws/iter/{dirname}")
async def ws_iter(ws: WebSocket, dirname: str) -> None:
    """Iter room — receives new JSONL events as they are written."""
    if not await _check_ws_auth(ws):
        await ws.close(code=4001)
        return
    room = f"iter:{dirname}"
    await manager.connect(ws, room)
    hb = asyncio.create_task(_heartbeat_loop(ws))
    try:
        await _recv_loop(ws)
    except WebSocketDisconnect:
        log.debug("ws_iter client disconnected for room %s", room, exc_info=True)
    except Exception:
        log.debug("ws_iter connection error", exc_info=True)
    finally:
        hb.cancel()
        await manager.disconnect(ws, room)


# ------------------------------------------------------------------
# Loop room — phase transitions
# ------------------------------------------------------------------


@router.websocket("/ws/loop")
async def ws_loop(ws: WebSocket) -> None:
    """Loop status room — receives phase transitions."""
    if not await _check_ws_auth(ws):
        await ws.close(code=4001)
        return
    await manager.connect(ws, "loop")
    hb = asyncio.create_task(_heartbeat_loop(ws))
    try:
        await _recv_loop(ws)
    except WebSocketDisconnect:
        log.debug("ws_loop client disconnected", exc_info=True)
    except Exception:
        log.debug("ws_loop connection error", exc_info=True)
    finally:
        hb.cancel()
        await manager.disconnect(ws, "loop")
