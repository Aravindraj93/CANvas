"""
backend/api/signals.py — FastAPI router for sending CAN signals and bus management.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.can.bus_manager import bus_manager
from backend.can.signal_sender import signal_sender
from backend.can.traffic import traffic

router = APIRouter()


# ── Request Models ───────────────────────────────────────────────────────────

class SendSignalRequest(BaseModel):
    dbc_id: Optional[str] = None
    message_name: str
    signal_name: str
    value: float | str


class SendMessageRequest(BaseModel):
    dbc_id: Optional[str] = None
    message_name: str
    signals: dict[str, float | str]


class CyclicRequest(BaseModel):
    dbc_id: Optional[str] = None
    message_name: str
    signals: dict[str, float | str]
    period_ms: int = Field(default=100, ge=1)


class StopCyclicRequest(BaseModel):
    message_name: str
    dbc_id: Optional[str] = None


class VerifyRequest(BaseModel):
    message_name: str
    dbc_id: Optional[str] = None
    expected: dict[str, float]
    max_age_ms: int = Field(default=1000, ge=1)
    tolerance: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)


class ConnectRequest(BaseModel):
    bus_type: str = "virtual"
    channel: Optional[str] = None
    bitrate: int = Field(default=500_000, gt=0)
    fd: bool = False
    data_bitrate: Optional[int] = Field(default=None, gt=0)
    bitrate_switch: bool = False
    serial: Optional[str] = None
    configure_bitrates: bool = True


# ── Signal Endpoints ─────────────────────────────────────────────────────────

@router.post("/send")
def send_signal(req: SendSignalRequest):
    """Send a single named CAN signal."""
    try:
        ok = signal_sender.send_signal(req.message_name, req.signal_name, req.value, req.dbc_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not ok:
        raise HTTPException(status_code=500, detail=bus_manager.get_status().get("last_tx_error") or "Bus not connected or send failed")

    return {"status": "sent", "message": req.message_name, "signal": req.signal_name, "value": req.value}


@router.post("/send-message")
def send_message(req: SendMessageRequest):
    """Send a full CAN message with multiple signal values."""
    try:
        ok = signal_sender.send_message_signals(req.message_name, req.signals, req.dbc_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not ok:
        raise HTTPException(status_code=500, detail=bus_manager.get_status().get("last_tx_error") or "Bus not connected or send failed")

    return {"status": "sent", "message": req.message_name, "signals": req.signals}


@router.post("/start-cyclic")
def start_cyclic(req: CyclicRequest):
    """Start periodically sending a message at the given rate."""
    try:
        signal_sender.start_cyclic(req.message_name, req.signals, req.period_ms, req.dbc_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"status": "started", "message": req.message_name, "period_ms": req.period_ms}


@router.post("/stop-cyclic")
def stop_cyclic(req: StopCyclicRequest):
    """Stop periodic sending for a message."""
    signal_sender.stop_cyclic(req.message_name, req.dbc_id)
    return {"status": "stopped", "message": req.message_name}


@router.get("/cyclic")
def get_cyclic():
    """List all currently active cyclic messages."""
    return {"cyclic_messages": signal_sender.get_cyclic_messages(), "errors": signal_sender.get_cyclic_errors()}


@router.get('/status')
def message_status(keys: list[str] = Query(default=[]), visible_only: bool = False):
    connected = bus_manager.get_status()['connected']
    selected = set(keys)
    return {
        'messages': {signal_sender.message_key(msg.name, dbc_id): traffic.view(msg, connected)
                     for dbc_id, _, msg in signal_sender.message_entries()
                     if not visible_only or signal_sender.message_key(msg.name, dbc_id) in selected},
        'cyclic_messages': signal_sender.get_cyclic_messages(),
        'errors': signal_sender.get_cyclic_errors(),
    }


@router.post('/verify')
def verify_message(req: VerifyRequest):
    try:
        _, msg = signal_sender.resolve_message(req.message_name, req.dbc_id)
        return traffic.verify(msg, req.expected, bus_manager.get_status()['connected'],
                              req.max_age_ms, req.tolerance)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ── Bus Management Endpoints ─────────────────────────────────────────────────

@router.get("/bus/status")
def bus_status():
    """Get the current CAN bus connection status."""
    return bus_manager.get_status()


@router.post("/bus/connect")
def bus_connect(req: ConnectRequest):
    """Connect to a CAN bus interface."""
    signal_sender.stop_all_cyclic()
    status = bus_manager.connect(
        bus_type=req.bus_type,
        channel=req.channel,
        bitrate=req.bitrate,
        fd=req.fd,
        data_bitrate=req.data_bitrate,
        bitrate_switch=req.bitrate_switch,
        serial=req.serial,
        configure_bitrates=req.configure_bitrates,
    )
    if not status.connected:
        raise HTTPException(status_code=500, detail=status.error or "Connection failed")
    return bus_manager.get_status()


@router.post("/bus/disconnect")
def bus_disconnect():
    """Disconnect from the CAN bus."""
    signal_sender.stop_all_cyclic()
    bus_manager.disconnect()
    return {"status": "disconnected"}
