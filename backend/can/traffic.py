"""Live traffic evidence. TX acceptance and TX echo never count as received frames."""
from __future__ import annotations

import copy
import math
import threading
import time
from collections import deque

from backend.can.bus_manager import bus_manager


class TrafficTracker:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._lock = threading.RLock()
        self._records = {}
        self._recent_tx = deque(maxlen=200)
        self._recent_cyclic_tx = deque(maxlen=300)

    def reset(self):
        with self._lock:
            self._records.clear()
            self._recent_tx.clear()
            self._recent_cyclic_tx.clear()

    def _record(self, frame_id, extended):
        return self._records.setdefault((frame_id, extended), {
            'tx_count': 0, 'rx_count': 0, 'tx_echo_count': 0, 'error_count': 0,
            'last_tx_error': None, 'last_rx': None, 'last_tx': None, 'last_echo': None,
            'rx_data': None, 'rx_is_fd': None,
            'tx_data': None, 'echo_data': None,
        })

    def record_tx(self, frame_id, extended, error=None, data=None, *, details=None):
        with self._lock:
            record = self._record(frame_id, extended)
            record['last_tx_error'] = error
            if error:
                record['error_count'] += 1
            else:
                record['tx_count'] += 1
                record['last_tx'] = self.clock()
                record['tx_data'] = bytes(data) if data is not None else None
            if details is not None:
                history = self._recent_cyclic_tx if details['cyclic'] else self._recent_tx
                history.append({
                    **details, 'can_id': hex(frame_id), 'is_extended_id': extended,
                    'payload_hex': bytes(data).hex(' ') if data is not None else None,
                    'accepted': error is None, 'error': error,
                })

    def recent_transmissions(self):
        with self._lock:
            entries = [entry.copy() for entry in (*self._recent_tx, *self._recent_cyclic_tx)]
        return sorted(entries, key=lambda entry: entry['started_at_unix_s'])

    def on_frame(self, frame):
        with self._lock:
            record = self._record(frame.arbitration_id, frame.is_extended_id)
            if frame.is_error_frame or frame.is_remote_frame:
                record['error_count'] += 1
                return
            if frame.is_rx:
                record['rx_count'] += 1
                record['last_rx'] = self.clock()
                record['rx_data'] = bytes(frame.data)
                record['rx_is_fd'] = frame.is_fd
            else:
                record['tx_echo_count'] += 1
                record['last_echo'] = self.clock()
                record['echo_data'] = bytes(frame.data)

    def view(self, message, connected=True, max_age_ms=None, include_decoded=True):
        with self._lock:
            record = copy.copy(self._record(message.frame_id, message.is_extended_frame))
        now = self.clock()
        threshold = max_age_ms if max_age_ms is not None else max(1000, (message.cycle_time or 0) * 3)
        def age(value):
            return round(max(0, (now - value) * 1000), 1) if value is not None else None
        result = {k: record[k] for k in ('tx_count', 'rx_count', 'tx_echo_count', 'error_count', 'last_tx_error')}
        result.update(rx_age_ms=age(record['last_rx']), tx_age_ms=age(record['last_tx']),
                      echo_age_ms=age(record['last_echo']), stale_after_ms=threshold,
                      decoded={}, decode_error=None)
        result.update(last_tx_hex=record['tx_data'].hex(' ') if record['tx_data'] is not None else None,
                      last_rx_hex=record['rx_data'].hex(' ') if record['rx_data'] is not None else None,
                      last_echo_hex=record['echo_data'].hex(' ') if record['echo_data'] is not None else None)
        if record['rx_data'] is not None:
            try:
                if record['rx_is_fd'] != bool(message.is_fd or message.length > 8):
                    raise ValueError('Received CAN / CAN FD format differs from the DBC')
                if len(record['rx_data']) != message.length:
                    raise ValueError(f"Received {len(record['rx_data'])} bytes; DBC expects {message.length}")
                if include_decoded:
                    decoded = {k: float(v) for k, v in message.decode(record['rx_data'], decode_choices=False).items()}
                    if any(not math.isfinite(v) for v in decoded.values()):
                        raise ValueError('Received a non-finite signal value')
                    result['decoded'] = decoded
            except Exception as exc:
                result['decode_error'] = str(exc)
        if not connected:
            result['state'] = 'disconnected'
        elif result['last_tx_error']:
            result['state'] = 'tx_error'
        elif result['rx_age_ms'] is not None:
            result['state'] = ('stale' if result['rx_age_ms'] > threshold else
                               'decode_error' if result['decode_error'] else 'receiving')
        elif result['tx_echo_count']:
            result['state'] = 'tx_echo'
        elif result['tx_count']:
            result['state'] = 'tx_only'
        else:
            result['state'] = 'not_seen'
        return result

    def verify(self, message, expected, connected=True, max_age_ms=1000, tolerance=None):
        if not expected:
            raise ValueError('Choose at least one signal to verify')
        signals = {s.name: s for s in message.signals}
        unknown = set(expected) - set(signals)
        if unknown:
            raise ValueError(f"Unknown signals: {', '.join(sorted(unknown))}")
        if tolerance is not None and (not math.isfinite(tolerance) or tolerance < 0):
            raise ValueError('Tolerance must be a finite nonnegative number')
        if any(not math.isfinite(float(v)) for v in expected.values()):
            raise ValueError('Expected values must be finite')
        status = self.view(message, connected, max_age_ms)
        reason = None
        if not connected:
            reason = 'Bus disconnected; reconnect and receive a new frame'
        elif status['rx_age_ms'] is None:
            reason = 'No RX frame received. A successful send or TX echo is not RX evidence.'
        elif status['rx_age_ms'] > max_age_ms:
            reason = f"Latest RX is stale ({status['rx_age_ms']} ms old)"
        elif status['decode_error']:
            reason = status['decode_error']
        comparisons = []
        if reason is None:
            for name, value in expected.items():
                actual = status['decoded'].get(name)
                allowed = tolerance if tolerance is not None else abs(float(signals[name].scale)) / 2 + 1e-9
                match = actual is not None and math.isfinite(actual) and abs(actual - value) <= allowed
                comparisons.append({'signal': name, 'expected': value, 'actual': actual,
                                    'tolerance': allowed, 'match': match})
            if not all(c['match'] for c in comparisons):
                reason = 'Latest received signal values differ from the expected values'
        return {'status': 'FAIL' if reason else 'PASS', 'reason': reason or 'Latest fresh RX matches',
                'rx_age_ms': status['rx_age_ms'], 'comparisons': comparisons,
                'evidence': 'received_bus_frame'}


traffic = TrafficTracker()
bus_manager.add_listener(traffic.on_frame)
