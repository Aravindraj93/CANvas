"""
backend/can/signal_sender.py
DBC-aware CAN signal encoding and transmission using cantools + python-can.
"""

from __future__ import annotations

import threading
import math
import time
from pathlib import Path
from typing import Optional

try:
    import cantools
    import cantools.database
    CANTOOLS_AVAILABLE = True
except ImportError:
    CANTOOLS_AVAILABLE = False

from backend.can.bus_manager import bus_manager


def _numeric_signal_value(value, default: float = 0.0) -> float:
    """Convert cantools numeric or NamedSignalValue objects to a number."""
    if value is None:
        return default
    return float(getattr(value, "value", value))


def _signal_bounds(sig):
    if sig.is_float:
        return (float(sig.minimum) if sig.minimum is not None else -1e9,
                float(sig.maximum) if sig.maximum is not None else 1e9)
    raw_min = -(2 ** (sig.length - 1)) if sig.is_signed else 0
    raw_max = 2 ** (sig.length - (1 if sig.is_signed else 0)) - 1
    physical = [raw_min * sig.scale + sig.offset, raw_max * sig.scale + sig.offset]
    return (float(sig.minimum) if sig.minimum is not None else float(min(physical)),
            float(sig.maximum) if sig.maximum is not None else float(max(physical)))


def _signal_value(sig, value):
    if isinstance(value, str):
        matches = [raw for raw, label in (sig.choices or {}).items() if str(label) == value]
        if not matches:
            raise ValueError(f"Unknown choice '{value}' for {sig.name}")
        return float(matches[0] * sig.scale + sig.offset)
    return _numeric_signal_value(value)


def _valid_signal_value(sig, value):
    if not math.isfinite(value):
        return False
    # Some production DBCs define reserved fields with factor 0. They have
    # a constant physical value and cannot be inverted through cantools.
    if sig.scale == 0:
        return value == sig.offset
    raw = sig.conversion.numeric_scaled_to_raw(value)
    if not sig.is_float:
        raw_min = -(2 ** (sig.length - 1)) if sig.is_signed else 0
        raw_max = 2 ** (sig.length - (1 if sig.is_signed else 0)) - 1
        if not raw_min <= raw <= raw_max:
            return False
    if raw in (sig.choices or {}) and abs(raw * sig.scale + sig.offset - value) <= abs(sig.scale) * 1e-6:
        return True
    low, high = _signal_bounds(sig)
    return low <= value <= high


def _dbc_initial(sig):
    raw = getattr(sig, 'raw_initial', None)
    if raw is not None:
        return float(sig.conversion.raw_to_scaled(raw, decode_choices=False))
    if sig.initial is not None:
        return _numeric_signal_value(sig.initial)
    return None


def _default_signal_value(sig):
    if sig.scale == 0:
        return float(sig.offset)
    initial = _dbc_initial(sig)
    if initial is not None and _valid_signal_value(sig, initial):
        return initial
    low, high = _signal_bounds(sig)
    candidate = min(high, max(low, 0.0))
    if not sig.is_float:
        raw = sig.conversion.numeric_scaled_to_raw(candidate)
        candidate = float(sig.conversion.raw_to_scaled(raw, decode_choices=False))
    if _valid_signal_value(sig, candidate):
        return candidate
    if not sig.is_float and sig.scale:
        for bound in (low, high):
            raw_bound = (bound - sig.offset) / sig.scale
            for raw in (math.floor(raw_bound), math.ceil(raw_bound)):
                value = float(raw * sig.scale + sig.offset)
                if _valid_signal_value(sig, value):
                    return value
    for raw in (sig.choices or {}):
        choice = float(raw * sig.scale + sig.offset)
        if _valid_signal_value(sig, choice):
            return choice
    raise ValueError(f'No valid default value for {sig.name}; check the DBC range and scaling')


def _constant_raw_value(sig):
    raw = getattr(sig, 'raw_initial', None)
    raw = 0 if raw is None else raw
    low = -(2 ** (sig.length - 1)) if sig.is_signed else 0
    high = 2 ** (sig.length - (1 if sig.is_signed else 0)) - 1
    if not math.isfinite(raw) or not low <= raw <= high or int(raw) != raw:
        raise ValueError(f'{sig.name}: zero-scale field has an invalid raw initial value {raw}')
    return int(raw)


class SignalSender:
    """Loads a DBC file and sends named signals over the CAN bus."""

    def __init__(self) -> None:
        self._db: Optional[cantools.database.Database] = None
        self._databases: dict[str, tuple[str, cantools.database.Database]] = {}
        self._dbc_path: Optional[str] = None
        self._cyclic_threads: dict[str, threading.Thread] = {}
        self._cyclic_stop: dict[str, threading.Event] = {}
        self._cyclic_errors: dict[str, str] = {}
        self._last_values: dict[str, dict[str, float]] = {}
        self._send_lock = threading.RLock()
        self._cyclic_lock = threading.RLock()
        self._metadata_cache = None
        self._metadata_signature = None
        self._frame_lookup = {}
        self._frame_signature = None
        self._session_scope = None
        self._session_signals = {}
        self._cyclic_periods = {}
        self._tx_paused = threading.Event()
        self._tx_generation = 0

    def _definition_signature(self):
        return (id(self._db), tuple((key, name, id(db))
                for key, (name, db) in self._databases.items()), self._dbc_path)

    def _invalidate_definitions(self):
        self._metadata_signature = None
        self._metadata_cache = None
        self._frame_signature = None
        self._frame_lookup = {}

    # ── DBC Management ──────────────────────────────────────────────────────

    @staticmethod
    def parse_dbc(content: bytes):
        if not CANTOOLS_AVAILABLE:
            raise RuntimeError("cantools not installed. Run: pip install cantools")
        try:
            text = content.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = content.decode('cp1252')
        try:
            db = cantools.database.load_string(text, database_format='dbc')
        except Exception as exc:
            raise ValueError(f'Failed to parse DBC: {exc}') from exc
        if not db.messages:
            raise ValueError('The DBC contains no CAN messages')
        return db

    @staticmethod
    def validate_databases(entries):
        for dbc_id, filename, db in entries:
            names = set()
            seen = set()
            for msg in db.messages:
                if msg.name in names:
                    raise ValueError(f"Duplicate message name '{msg.name}' in {filename}")
                names.add(msg.name)
                # A problematic field must not prevent browsing every other
                # message in an otherwise parseable DBC. Send validation stays strict.
                key = (msg.frame_id, msg.is_extended_frame)
                if key in seen:
                    raise ValueError(f'Duplicate CAN ID {hex(msg.frame_id)} within {filename}')
                seen.add(key)

    def use_databases(self, entries, session_scope=None):
        self.validate_databases(entries)
        with self._cyclic_lock:
            self.stop_all_cyclic()
            with self._send_lock:
                self._session_scope = session_scope
                self._databases = {dbc_id: (filename, db) for dbc_id, filename, db in entries}
                self._db = entries[0][2] if entries else None
                self._dbc_path = None
                self._last_values.clear()
                self._invalidate_definitions()
            from backend.can.traffic import traffic
            traffic.reset()

    @staticmethod
    def message_key(message_name, dbc_id=None):
        return f'{dbc_id}::{message_name}' if dbc_id else message_name

    def resolve_message(self, message_name, dbc_id=None):
        if self._databases:
            if dbc_id and dbc_id not in self._databases:
                raise ValueError('This DBC is not active. Enable it in Saved DBCs.')
            matches = []
            for source_id, (_, db) in self._databases.items():
                if dbc_id and source_id != dbc_id:
                    continue
                try:
                    matches.append((source_id, db.get_message_by_name(message_name)))
                except KeyError:
                    pass
            if len(matches) > 1:
                raise ValueError(f"Message '{message_name}' exists in multiple DBCs; supply dbc_id")
            if matches:
                return matches[0]
        elif self._db and not dbc_id:
            try:
                return None, self._db.get_message_by_name(message_name)
            except KeyError:
                pass
        elif not self._db:
            raise RuntimeError('No DBC active. Add or enable a saved DBC first.')
        raise ValueError(f"Message '{message_name}' not found in active DBCs")

    def message_entries(self):
        with self._send_lock:
            if self._databases:
                return [(dbc_id, filename, msg)
                        for dbc_id, (filename, db) in self._databases.items() for msg in db.messages]
            return [(None, self._dbc_path, msg) for msg in self._db.messages] if self._db else []

    def decode_frame(self, frame, dbc_id=None):
        signature = self._definition_signature()
        if signature != self._frame_signature:
            self._frame_lookup = {}
            for source_id, filename, msg in self.message_entries():
                self._frame_lookup.setdefault((msg.frame_id, msg.is_extended_frame), []).append((source_id, filename, msg))
            self._frame_signature = signature
        entries = self._frame_lookup.get((frame.arbitration_id, frame.is_extended_id), [])
        if dbc_id:
            entries = [entry for entry in entries if entry[0] == dbc_id]
        if len(entries) > 1:
            return {'message_name': 'Shared CAN ID — choose DBC', 'decoded': {},
                    'ambiguous': True, 'candidates': [{'dbc_id': d, 'dbc_filename': f, 'message_name': m.name}
                                                    for d, f, m in entries]}
        if entries:
            dbc_id, filename, msg = entries[0]
            if frame.is_fd != bool(msg.is_fd or msg.length > 8) or len(frame.data) != msg.length:
                raise ValueError('Received frame format or payload length differs from the DBC')
            decoded = {k: float(v) for k, v in msg.decode(frame.data, decode_choices=False).items()}
            if any(not math.isfinite(v) for v in decoded.values()):
                raise ValueError('Received a non-finite signal value')
            return {'message_name': msg.name, 'dbc_id': dbc_id, 'dbc_filename': filename,
                    'decoded': {k: float(v) for k, v in decoded.items()}}
        return {'message_name': None, 'decoded': {}}

    def load_dbc(self, path: str) -> dict:
        """Load a DBC file. Returns parsed messages/signals as dict."""
        if not CANTOOLS_AVAILABLE:
            raise RuntimeError("cantools not installed. Run: pip install cantools")

        db = cantools.database.load_file(path)
        self.stop_all_cyclic()
        with self._send_lock:
            self._db = db
            self._databases.clear()
            self._dbc_path = path
            self._last_values.clear()
            self._invalidate_definitions()
        return self._db_to_dict()

    def load_dbc_bytes(self, content: bytes, filename: str = "upload.dbc") -> dict:
        """Load DBC from raw bytes (for file upload)."""
        if not CANTOOLS_AVAILABLE:
            raise RuntimeError("cantools not installed.")

        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".dbc", delete=False) as f:
            f.write(content)
            tmp_path = f.name

        try:
            db = cantools.database.load_file(tmp_path)
            self.stop_all_cyclic()
            with self._send_lock:
                self._db = db
                self._databases.clear()
                self._dbc_path = filename
                self._last_values.clear()
                self._invalidate_definitions()
            return self._db_to_dict()
        finally:
            os.unlink(tmp_path)

    def unload(self) -> None:
        self.stop_all_cyclic()
        self._db = None
        self._databases.clear()
        self._dbc_path = None
        self._last_values.clear()
        self._invalidate_definitions()

    def _db_to_dict(self) -> dict:
        """Convert loaded DB to JSON-serializable dict."""
        if not self._db:
            return {"messages": []}
        messages = []
        entries = self.message_entries()
        sources = {}
        for source_id, filename, msg in entries:
            sources.setdefault((msg.frame_id, msg.is_extended_frame), []).append(filename)
        for dbc_id, filename, msg in entries:
            signals = []
            for sig in msg.signals:
                warning = None
                read_only = False
                raw_initial = None
                try:
                    initial = _default_signal_value(sig)
                    if sig.scale == 0:
                        raw_initial = _constant_raw_value(sig)
                        read_only = True
                        warning = f'Zero-scale field: fixed at {sig.offset:g}; preserves raw {raw_initial}. Read only.'
                    elif _dbc_initial(sig) is not None and not _valid_signal_value(sig, _dbc_initial(sig)):
                        warning = f'DBC initial value {_dbc_initial(sig):g} is invalid; using {initial:g}'
                except (ValueError, ArithmeticError, OverflowError) as exc:
                    initial = 0.0
                    read_only = True
                    warning = f'DBC definition needs correction: {sig.name}: {exc}'
                signals.append({
                    "name": sig.name,
                    "start_bit": sig.start,
                    "length": sig.length,
                    "min_value": _signal_bounds(sig)[0],
                    "max_value": _signal_bounds(sig)[1],
                    "unit": sig.unit or "",
                    "initial_value": initial,
                    "read_only": read_only,
                    "raw_initial": raw_initial,
                    "comment": sig.comment or "",
                    "scale": sig.scale,
                    "offset": sig.offset,
                    "choices": [{'raw_value': raw, 'value': float(raw * sig.scale + sig.offset), 'label': str(label)}
                                for raw, label in (sig.choices or {}).items()],
                    "default_warning": warning,
                })
            messages.append({
                "name": msg.name,
                "key": self.message_key(msg.name, dbc_id),
                "dbc_id": dbc_id,
                "dbc_filename": filename,
                "shared_sources": sources[(msg.frame_id, msg.is_extended_frame)] if len(sources[(msg.frame_id, msg.is_extended_frame)]) > 1 else [],
                "is_extended_id": msg.is_extended_frame,
                "arbitration_id": msg.frame_id,
                "arbitration_id_hex": hex(msg.frame_id),
                "length": msg.length,
                "is_fd": bool(msg.is_fd or msg.length > 8),
                "cycle_time": msg.cycle_time,
                "comment": msg.comment or "",
                "signals": signals,
            })
        return {"messages": messages, "message_count": len(messages)}

    def get_all_messages(self) -> dict:
        with self._send_lock:
            signature = self._definition_signature()
            if signature != self._metadata_signature:
                self._metadata_cache = self._db_to_dict() if self._db else {"messages": [], "message_count": 0}
                self._metadata_signature = signature
            return self._metadata_cache

    # ── Signal Sending ───────────────────────────────────────────────────────

    def send_signal(self, message_name: str, signal_name: str, value: float, dbc_id=None) -> bool:
        """Update one signal, retaining values last sent for other signals."""
        return self.send_message_signals(message_name, {signal_name: value}, dbc_id)

    def send_message_signals(self, message_name: str, signal_values: dict[str, float], dbc_id=None,
                             *, request_id=None, cyclic=False) -> bool:
        """Encode and send a full CAN message with given signal values."""
        generation = self._tx_generation
        with self._send_lock:
            if generation != self._tx_generation:
                raise RuntimeError('Transmission cancelled by Stop TX')
            return self._send_message_signals(message_name, signal_values, dbc_id, request_id, cyclic, generation)

    def _send_message_signals(self, message_name: str, signal_values: dict[str, float],
                              dbc_id, request_id, cyclic, generation) -> bool:
        if self._tx_paused.is_set():
            raise RuntimeError('Transmission paused. Use Resume TX before sending.')
        if not self._db:
            raise RuntimeError("No DBC loaded. Upload a .dbc file first.")

        dbc_id, msg = self.resolve_message(message_name, dbc_id)
        key = self.message_key(message_name, dbc_id)
        for other_key, thread in list(self._cyclic_threads.items()):
            if other_key != key and thread.is_alive():
                source, name = other_key.split('::', 1) if '::' in other_key else (None, other_key)
                _, other = self.resolve_message(name, source)
                if (other.frame_id, other.is_extended_frame) == (msg.frame_id, msg.is_extended_frame):
                    raise ValueError(f'CAN ID {hex(msg.frame_id)} is already cyclic from another DBC/message. Stop that cyclic stream first.')

        data, all_values = self._prepare_payload(msg, signal_values, self._last_values.get(key, {}))

        is_fd = bool(msg.is_fd or msg.length > 8)
        status = bus_manager.get_status()
        started_at = time.time()
        started = time.monotonic()
        ok = bus_manager.send_message(
            arbitration_id=msg.frame_id,
            data=data,
            is_extended_id=getattr(msg, 'is_extended_frame', False),
            is_fd=is_fd,
            dispatch_guard=lambda: not self._tx_paused.is_set() and generation == self._tx_generation,
        )
        duration_ms = round((time.monotonic() - started) * 1000, 3)
        from backend.can.traffic import traffic
        traffic.record_tx(msg.frame_id, msg.is_extended_frame,
                          None if ok else bus_manager.get_status().get('last_tx_error') or 'CAN send failed',
                          data=data, details={
                              'message': message_name, 'dbc_id': dbc_id, 'request_id': request_id,
                              'cyclic': cyclic, 'channel': status['channel'], 'is_fd': is_fd,
                              'bitrate_switch': is_fd and status['bitrate_switch'],
                              'started_at_unix_s': started_at, 'send_duration_ms': duration_ms,
                          })
        if ok:
            self._last_values[key] = all_values
            # Decode the actual encoded payload: quantization and multiplexing
            # must not make the session display claim values never transmitted.
            decoded = msg.decode(data, decode_choices=False)
            filename = self._databases[dbc_id][0] if dbc_id in self._databases else self._dbc_path
            for name, value in decoded.items():
                session_key = (self._session_scope, key, name)
                previous_record = self._session_signals.get(session_key, {})
                self._session_signals[session_key] = dict(
                    message_key=key, message=message_name, dbc_id=dbc_id,
                    dbc_filename=filename, can_id=hex(msg.frame_id), signal=name,
                    value=float(value), sent_at=started_at,
                    count=previous_record.get('count', 0) + 1,
                    explicit=previous_record.get('explicit', False) or name in signal_values,
                )
        return ok

    def validate_sequence(self, steps):
        """Dry-run encodings with retained values, without modifying sender state."""
        with self._send_lock:
            retained = {key: dict(values) for key, values in self._last_values.items()}
            for index, step in enumerate(steps):
                if step['action'] not in ('send_signal', 'send_message'): continue
                try:
                    dbc_id, msg = self.resolve_message(step['message'], step.get('dbc_id'))
                    key = self.message_key(msg.name, dbc_id)
                    values = step['signals'] if step['action'] == 'send_message' else {step['signal']: step['value']}
                    _, retained[key] = self._prepare_payload(msg, values, retained.get(key, {}))
                except Exception as exc:
                    raise ValueError(f'Step {index + 1}: {exc}') from exc

    @classmethod
    def _prepare_payload(cls, msg, signal_values, previous):
        unknown = set(signal_values) - {sig.name for sig in msg.signals}
        if unknown:
            raise ValueError(f"Unknown signals in '{msg.name}': {', '.join(sorted(unknown))}")
        all_values = {}
        for sig in msg.signals:
            all_values[sig.name] = (_signal_value(sig, signal_values[sig.name]) if sig.name in signal_values
                                    else previous[sig.name] if sig.name in previous else _default_signal_value(sig))
        try:
            if any(sig.scale == 0 for sig in msg.signals):
                raw_values = {}
                for sig in msg.signals:
                    value = all_values[sig.name]
                    if not _valid_signal_value(sig, value):
                        raise ValueError(f'{sig.name}: invalid physical value {value:g}')
                    raw_values[sig.name] = (_constant_raw_value(sig) if sig.scale == 0
                                            else sig.conversion.numeric_scaled_to_raw(value))
                data = msg.encode(msg.gather_signals(raw_values), scaling=False, strict=True)
            else:
                data = cls._encode_physical(msg, all_values)
        except Exception as exc:
            raise ValueError(f"Failed to encode message '{msg.name}': {exc}") from exc
        return data, all_values

    def get_session_signals(self, scope=None):
        """Snapshot of accepted payload fields for this process, never failed attempts."""
        with self._send_lock:
            return [dict(record) for (program, _, _), record in self._session_signals.items()
                    if program == scope]

    def get_cyclic_periods(self):
        with self._cyclic_lock:
            return dict(self._cyclic_periods)

    @staticmethod
    def _encode_physical(msg, all_values):
        encoding_values = msg.gather_signals(all_values)
        for sig in msg.signals:
            if sig.name not in encoding_values:
                continue
            value = encoding_values[sig.name]
            if not _valid_signal_value(sig, value):
                low, high = _signal_bounds(sig)
                raise ValueError(f'{sig.name} = {value:g} is outside [{low:g}, {high:g}] and is not a defined DBC choice')
            raw = sig.conversion.numeric_scaled_to_raw(value)
            if raw in (sig.choices or {}):
                encoding_values[sig.name] = str(sig.choices[raw])
        return msg.encode(encoding_values)


    # ── Cyclic Sending ───────────────────────────────────────────────────────

    def start_cyclic(
        self,
        message_name: str,
        signal_values: dict[str, float],
        period_ms: int = 100,
        dbc_id=None,
    ) -> None:
        """Start periodically sending a message."""
        if period_ms < 1:
            raise ValueError("Cycle time must be at least 1 ms")
        with self._cyclic_lock:
            dbc_id, _ = self.resolve_message(message_name, dbc_id)
            key = self.message_key(message_name, dbc_id)
            self.stop_cyclic(message_name, dbc_id)
            # Validate the DBC, encoding and initial transmission before reporting success.
            period = period_ms / 1000.0
            first_deadline = time.monotonic() + period
            if not self.send_message_signals(message_name, signal_values, dbc_id, cyclic=True):
                raise RuntimeError(bus_manager.get_status().get("last_tx_error") or "CAN send failed")
            self._cyclic_errors.pop(key, None)
            stop_event = threading.Event()
            self._cyclic_stop[key] = stop_event
            self._cyclic_periods[key] = period_ms

            def _worker():
                deadline = first_deadline
                while not stop_event.is_set():
                    now = time.monotonic()
                    # Preserve the requested cadence and skip slots the adapter missed.
                    if now > deadline:
                        deadline += math.ceil((now - deadline) / period) * period
                    if stop_event.wait(max(0, deadline - now)):
                        return
                    try:
                        with self._send_lock:
                            if stop_event.is_set():
                                return
                            # Read the latest successfully transmitted values after taking the lock.
                            if not self.send_message_signals(message_name, {}, dbc_id, cyclic=True):
                                raise RuntimeError(bus_manager.get_status().get("last_tx_error") or "CAN send failed")
                    except Exception as exc:
                        self._cyclic_errors[key] = str(exc)
                        stop_event.set()
                    deadline += period

            t = threading.Thread(target=_worker, daemon=True, name=f"canvas-cyclic-{message_name}")
            self._cyclic_threads[key] = t
            t.start()

    def stop_cyclic(self, message_name: str, dbc_id=None) -> None:
        key = self.message_key(message_name, dbc_id)
        with self._cyclic_lock:
            event = self._cyclic_stop.pop(key, None)
            self._cyclic_periods.pop(key, None)
            if event:
                event.set()
            thread = self._cyclic_threads.pop(key, None)
            if thread and thread is not threading.current_thread():
                thread.join(timeout=1.0)

    def pause_transmissions(self):
        """Latch immediately, without waiting for a blocked adapter or cyclic lock."""
        self._tx_paused.set()
        self._tx_generation += 1
        for event in list(self._cyclic_stop.values()): event.set()

    def resume_transmissions(self):
        self._tx_paused.clear()

    def transmissions_paused(self):
        return self._tx_paused.is_set()

    def stop_all_cyclic(self) -> None:
        with self._cyclic_lock:
            for event in list(self._cyclic_stop.values()): event.set()
            for name in list(self._cyclic_stop.keys()):
                self.stop_cyclic(name)
            self._cyclic_errors.clear()

    def get_cyclic_messages(self) -> list[str]:
        with self._cyclic_lock:
            return [name for name, thread in self._cyclic_threads.items() if thread.is_alive()]

    def get_cyclic_errors(self) -> dict[str, str]:
        return dict(self._cyclic_errors)


# Module-level singleton
signal_sender = SignalSender()
