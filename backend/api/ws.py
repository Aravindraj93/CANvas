"""
backend/api/ws.py — WebSocket endpoint for real-time CAN bus monitoring.
Broadcasts received CAN frames to all connected browser clients.
"""

from __future__ import annotations

import asyncio
import json
import time
import threading
from collections import deque
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.can.bus_manager import bus_manager
from backend.can.signal_sender import signal_sender

router = APIRouter()

# Set of active WebSocket connections
_connections: set[WebSocket] = set()
_admitted: set[WebSocket] = set()
_broadcast_loop: Optional[asyncio.AbstractEventLoop] = None
_pending_frames = deque(maxlen=500)
_pending_lock = threading.Lock()
_draining = False


def _can_message_to_dict(msg) -> dict:
    """Convert a python-can Message to a JSON-serializable dict."""
    try:
        info = signal_sender.decode_frame(msg)
    except Exception as exc:
        info = {"message_name": None, "decoded": {}, "decode_error": str(exc)}

    return {
        "id": msg.arbitration_id,
        "id_hex": f"0x{msg.arbitration_id:03X}",
        "data_hex": msg.data.hex().upper(),
        "data_bytes": list(msg.data),
        "dlc": msg.dlc,
        "is_extended_id": msg.is_extended_id,
        "is_fd": msg.is_fd,
        "bitrate_switch": msg.bitrate_switch,
        "direction": "RX" if msg.is_rx else "TX",
        **info,
        "timestamp": msg.timestamp or time.time(),
    }


async def _broadcast(frame_dict: dict) -> None:
    """Broadcast a frame to all connected WebSocket clients."""
    if not _connections:
        return
    payload = json.dumps(frame_dict)
    async def deliver(ws):
        try:
            await asyncio.wait_for(ws.send_text(payload), timeout=.5)
        except Exception:
            _connections.discard(ws)
            try: await asyncio.wait_for(ws.close(code=1013), timeout=.1)
            except Exception: pass
    await asyncio.gather(*(deliver(ws) for ws in list(_connections)))


async def _drain_pending():
    global _draining
    try:
        while True:
            with _pending_lock:
                if not _pending_frames: break
                msg = _pending_frames.popleft()
            if _connections: await _broadcast(_can_message_to_dict(msg))
    finally:
        with _pending_lock:
            _draining = False
            if _pending_frames and _connections:
                _draining = True
                asyncio.create_task(_drain_pending())


def _on_can_message(msg) -> None:
    """Called by python-can Notifier on every received frame."""
    global _draining
    loop = _broadcast_loop
    if _connections and loop and loop.is_running():
        with _pending_lock:
            _pending_frames.append(msg)
            if _draining: return
            _draining = True
        try:
            loop.call_soon_threadsafe(lambda: asyncio.create_task(_drain_pending()))
        except RuntimeError:
            with _pending_lock: _draining = False


# Register the listener once at module load
bus_manager.add_listener(_on_can_message)


@router.websocket("/bus")
async def ws_bus(websocket: WebSocket):
    """WebSocket endpoint — streams live CAN frames to the browser."""
    global _broadcast_loop
    if len(_admitted) >= 16:
        await websocket.close(code=1013)
        return
    _admitted.add(websocket)
    _broadcast_loop = asyncio.get_running_loop()
    try:
        await websocket.accept()
        await asyncio.wait_for(websocket.send_text(json.dumps({
            'type': 'status', 'bus': bus_manager.get_status(),
        })), timeout=.5)
        _connections.add(websocket)
        while True:
            # Keep connection alive — client can send pings
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await asyncio.wait_for(websocket.send_text(json.dumps({"type": "pong"})), timeout=.5)
            except asyncio.TimeoutError:
                # Send keepalive
                await asyncio.wait_for(websocket.send_text(json.dumps({"type": "keepalive"})), timeout=.5)
    except (WebSocketDisconnect, RuntimeError, OSError, asyncio.TimeoutError):
        pass
    finally:
        _connections.discard(websocket)
        _admitted.discard(websocket)
