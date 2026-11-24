"""
backend/can/bus_manager.py
Thread-safe CAN bus manager using python-can.
Supports virtual buses and python-can hardware interfaces, including ICS neoVI/ValueCAN.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from typing import Callable, Optional

try:
    import can
    CAN_AVAILABLE = True
except ImportError:
    CAN_AVAILABLE = False


@dataclass
class BusStatus:
    connected: bool = False
    bus_type: str = "virtual"
    channel: Optional[str] = None
    bitrate: int = 500_000
    fd: bool = False
    data_bitrate: Optional[int] = None
    bitrate_switch: bool = False
    serial: Optional[str] = None
    channel_info: Optional[str] = None
    error: Optional[str] = None
    last_tx_error: Optional[str] = None
    tx_count: int = 0
    configure_bitrates: bool = True


class BusManager:
    """Singleton CAN bus manager."""

    def __init__(self) -> None:
        self._bus: Optional[can.BusABC] = None
        self._lock = threading.Lock()
        self._status = BusStatus()
        self._listeners: list[Callable[[can.Message], None]] = []
        self._notifier: Optional[can.Notifier] = None

    # ── Connection ──────────────────────────────────────────────────────────

    def connect(
        self,
        bus_type: str = "virtual",
        channel: Optional[str] = None,
        bitrate: int = 500_000,
        fd: bool = False,
        data_bitrate: Optional[int] = None,
        bitrate_switch: bool = False,
        serial: Optional[str] = None,
        configure_bitrates: bool = True,
    ) -> BusStatus:
        with self._lock:
            if self._bus is not None:
                self._teardown()

            from backend.can.traffic import traffic
            traffic.reset()

            self._status = BusStatus(
                bus_type=bus_type, channel=channel, bitrate=bitrate, fd=fd,
                data_bitrate=(data_bitrate or bitrate) if fd else None,
                bitrate_switch=bitrate_switch, serial=serial,
                configure_bitrates=configure_bitrates,
            )
            if not CAN_AVAILABLE:
                self._status.error = "python-can not installed. Run: pip install python-can"
                return self._status

            try:
                if bitrate <= 0 or (data_bitrate is not None and data_bitrate <= 0):
                    raise ValueError("Bitrates must be positive")
                if bitrate_switch and not fd:
                    raise ValueError("Bitrate switching requires CAN FD")
                if not configure_bitrates and bus_type != 'neovi':
                    raise ValueError('Preserving adapter bitrates is available for ValueCAN / neoVI only')
                kwargs: dict = {"ignore_config": True}
                if configure_bitrates:
                    kwargs['bitrate'] = bitrate
                if fd:
                    kwargs['fd'] = True
                    if configure_bitrates:
                        kwargs['data_bitrate'] = data_bitrate or bitrate

                if bus_type == "virtual":
                    kwargs["interface"] = "virtual"
                    kwargs["channel"] = channel or "canvas_virtual"
                    kwargs["receive_own_messages"] = True
                elif bus_type == "neovi":
                    kwargs["interface"] = "neovi"
                    # ICS network names avoid confusing physical port numbers with net IDs.
                    kwargs["channel"] = channel or "HSCAN"
                    kwargs["receive_own_messages"] = True
                    if serial:
                        kwargs["serial"] = serial
                elif bus_type == "socketcan":
                    kwargs["interface"] = "socketcan"
                    kwargs["channel"] = channel or "vcan0"
                elif bus_type == "pcan":
                    kwargs["interface"] = "pcan"
                    kwargs["channel"] = channel or "PCAN_USBBUS1"
                elif bus_type == "kvaser":
                    kwargs["interface"] = "kvaser"
                    kwargs["channel"] = channel or "0"
                elif bus_type == "serial":
                    kwargs["interface"] = "serial"
                    kwargs["channel"] = channel or "COM3"
                else:
                    kwargs["interface"] = bus_type
                    if channel:
                        kwargs["channel"] = channel

                self._bus = can.Bus(**kwargs)
                self._notifier = can.Notifier(self._bus, self._listeners, timeout=0.05)
                self._status.connected = True
                self._status.channel = str(kwargs.get("channel", ""))
                self._status.channel_info = getattr(self._bus, "channel_info", None)
            except Exception as exc:
                self._teardown()
                self._status.error = str(exc)
                if bus_type == "neovi" and isinstance(exc, ImportError):
                    self._status.error += (
                        " | ValueCAN: install Intrepid Product Drivers and "
                        "pip install 'python-can[neovi]'. Check the device serial and ICS "
                        "network name (HSCAN for CAN1; verify CAN2's name in your device settings)."
                    )

            return self._status

    def disconnect(self) -> None:
        with self._lock:
            self._teardown()
            self._status = BusStatus(connected=False)
            from backend.can.traffic import traffic
            traffic.reset()

    def _teardown(self) -> None:
        if self._notifier:
            self._notifier.stop()
            self._notifier = None
        if self._bus:
            try:
                self._bus.shutdown()
            except Exception:
                pass
            self._bus = None

    # ── Sending ─────────────────────────────────────────────────────────────

    def send_message(
        self,
        arbitration_id: int,
        data: bytes,
        is_extended_id: bool = False,
        is_fd: bool = False,
        dispatch_guard=None,
    ) -> bool:
        """Send a raw CAN frame. Returns True on success."""
        if not CAN_AVAILABLE:
            return False
        with self._lock:
            if self._bus is None:
                self._status.last_tx_error = "CAN bus is not connected"
                return False
            try:
                if is_fd and not self._status.fd:
                    raise ValueError("This DBC message requires CAN FD. Reconnect with CAN FD enabled.")
                msg = can.Message(
                    arbitration_id=arbitration_id,
                    data=data,
                    is_extended_id=is_extended_id,
                    is_fd=is_fd,
                    bitrate_switch=is_fd and self._status.bitrate_switch,
                    check=True,
                )
                if dispatch_guard is not None and not dispatch_guard():
                    raise RuntimeError('Transmission cancelled or paused before adapter dispatch')
                self._bus.send(msg, timeout=0.5)
                self._status.last_tx_error = None
                self._status.tx_count += 1
                return True
            except Exception as exc:
                self._status.last_tx_error = str(exc)
                return False

    # ── Listeners ───────────────────────────────────────────────────────────

    def add_listener(self, callback: Callable[[can.Message], None]) -> None:
        self._listeners.append(callback)
        if self._notifier and CAN_AVAILABLE:
            self._notifier.add_listener(callback)  # type: ignore[arg-type]

    def remove_listener(self, callback: Callable[[can.Message], None]) -> None:
        self._listeners = [l for l in self._listeners if l is not callback]
        if self._notifier and CAN_AVAILABLE:
            self._notifier.remove_listener(callback)

    # ── Status ──────────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        result = asdict(self._status)
        reader_error = getattr(self._notifier, 'exception', None)
        result['reader_error'] = str(reader_error) if isinstance(reader_error, BaseException) else None
        return result


# Module-level singleton
bus_manager = BusManager()
