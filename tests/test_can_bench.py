"""Hardware-independent regressions for the bench connection and send path."""
import asyncio
import statistics
import time
from pathlib import Path
from unittest.mock import MagicMock

import can
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from cantools.database.can import Database, Message, Signal

from backend.can.bus_manager import BusManager, bus_manager
from backend.can.signal_sender import SignalSender, signal_sender
from backend.api.signals import router
from backend.runner.test_runner import _run_step


@pytest.fixture(autouse=True)
def cleanup_singletons():
    signal_sender.unload()
    bus_manager.disconnect()
    yield
    signal_sender.unload()
    bus_manager.disconnect()


@pytest.fixture
def sender():
    instance = SignalSender()
    instance.load_dbc(str(Path(__file__).parent / 'fixtures' / 'sample.dbc'))
    yield instance
    instance.stop_all_cyclic()


def fd_database(length=16):
    return Database(messages=[Message(
        frame_id=0x41B, name='Angles', length=length, is_fd=True,
        signals=[Signal(name='PitchAngle', start=0, length=8, minimum=0, maximum=100)],
    )])


def test_neovi_configuration_and_frame_flags(monkeypatch):
    fake_bus = MagicMock()
    factory = MagicMock(return_value=fake_bus)
    monkeypatch.setattr(can, 'Bus', factory)
    monkeypatch.setattr(can, 'Notifier', MagicMock())
    manager = BusManager()
    status = manager.connect('neovi', 'HSCAN', 500000, fd=True,
                             data_bitrate=2000000, bitrate_switch=True, serial='V2I104')
    assert status.connected
    factory.assert_called_once_with(interface='neovi', channel='HSCAN', bitrate=500000,
                                    fd=True, data_bitrate=2000000,
                                    receive_own_messages=True, serial='V2I104', ignore_config=True)
    assert manager.send_message(0x41B, bytes(16), is_fd=True)
    frame = fake_bus.send.call_args.args[0]
    assert frame.is_fd and frame.bitrate_switch and not frame.is_extended_id
    assert frame.dlc == 16
    assert manager.get_status()['tx_count'] == 1
    manager.disconnect()


def test_neovi_uses_network_name_default(monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr(can, 'Bus', factory)
    monkeypatch.setattr(can, 'Notifier', MagicMock())
    manager = BusManager()
    assert manager.connect('neovi').connected
    assert factory.call_args.kwargs['channel'] == 'HSCAN'
    assert 'serial' not in factory.call_args.kwargs
    manager.disconnect()


def test_hardware_failure_does_not_fall_back_to_virtual(monkeypatch):
    factory = MagicMock(side_effect=RuntimeError('neoVI DLL bad net ID'))
    monkeypatch.setattr(can, 'Bus', factory)
    manager = BusManager()
    status = manager.connect('neovi', 'HSCAN2')
    assert not status.connected and status.bus_type == 'neovi'
    assert 'bad net ID' in status.error
    assert factory.call_count == 1 and manager._bus is None


def test_notifier_failure_closes_opened_adapter(monkeypatch):
    fake_bus = MagicMock()
    monkeypatch.setattr(can, 'Bus', MagicMock(return_value=fake_bus))
    monkeypatch.setattr(can, 'Notifier', MagicMock(side_effect=RuntimeError('reader failed')))
    manager = BusManager()
    assert not manager.connect('neovi').connected
    fake_bus.shutdown.assert_called_once()
    assert manager._bus is None


def test_real_virtual_fd_frame_and_signal_value():
    bus_manager.connect('virtual', 'fd-test', fd=True, data_bitrate=2000000,
                        bitrate_switch=True)
    sender = SignalSender()
    sender._db = fd_database()
    with can.Bus(interface='virtual', channel='fd-test') as receiver:
        assert sender.send_signal('Angles', 'PitchAngle', 42)
        frame = receiver.recv(1)
        assert frame is not None and frame.is_fd and frame.bitrate_switch
        assert frame.arbitration_id == 0x41B and len(frame.data) == 16
        assert sender._db.decode_message(frame.arbitration_id, frame.data)['PitchAngle'] == 42


@pytest.mark.parametrize('length', [8, 16])
def test_fd_rejected_on_classical_connection(length):
    bus_manager.connect('virtual')
    sender = SignalSender()
    sender._db = fd_database(length)
    assert not sender.send_signal('Angles', 'PitchAngle', 42)
    assert 'requires CAN FD' in bus_manager.get_status()['last_tx_error']


def test_classical_frames_stay_classical_on_fd_connection(sender):
    bus_manager.connect('virtual', 'classic-test', fd=True, bitrate_switch=True)
    with can.Bus(interface='virtual', channel='classic-test') as receiver:
        assert sender.send_signal('Powertrain', 'VehicleSpeed', 50)
        frame = receiver.recv(1)
        assert frame is not None and not frame.is_fd and not frame.bitrate_switch


def test_individual_signal_preserves_previous_values(sender):
    bus_manager.connect('virtual', 'preserve-test')
    with can.Bus(interface='virtual', channel='preserve-test') as receiver:
        assert sender.send_signal('Powertrain', 'EngineRPM', 1500)
        receiver.recv(1)
        assert sender.send_signal('Powertrain', 'VehicleSpeed', 40)
        frame = receiver.recv(1)
        decoded = sender._db.decode_message(frame.arbitration_id, frame.data)
        assert decoded['EngineRPM'] == 1500 and decoded['VehicleSpeed'] == 40


def test_default_value_is_within_signal_range(sender):
    bus_manager.connect('virtual')
    assert sender.send_signal('Climate', 'FanSpeed', 3)
    assert sender._last_values['Climate']['SetTemp'] == 16


def test_unknown_signal_fails(sender):
    with pytest.raises(ValueError, match='Unknown signals'):
        sender.send_signal('Powertrain', 'WrongSignal', 1)


def test_cyclic_rejects_disconnected_bus(sender):
    with pytest.raises(RuntimeError, match='not connected'):
        sender.start_cyclic('Powertrain', {'VehicleSpeed': 50}, 20)
    assert sender.get_cyclic_messages() == []


def test_cyclic_values_update_and_stop(sender):
    bus_manager.connect('virtual', 'cyclic-test')
    with can.Bus(interface='virtual', channel='cyclic-test') as receiver:
        sender.start_cyclic('Powertrain', {'VehicleSpeed': 10}, 20)
        assert receiver.recv(1) is not None
        assert sender.send_signal('Powertrain', 'VehicleSpeed', 77)
        deadline = time.monotonic() + 1
        frames = []
        while time.monotonic() < deadline and len(frames) < 3:
            frame = receiver.recv(.1)
            if frame is not None:
                value = sender._db.decode_message(frame.arbitration_id, frame.data)['VehicleSpeed']
                if value == 77:
                    frames.append(frame)
        assert len(frames) == 3
        sender.stop_cyclic('Powertrain')
        while receiver.recv(0) is not None:
            pass
        assert receiver.recv(.08) is None
        assert sender.get_cyclic_messages() == []


def test_cyclic_late_failure_is_reported(sender, monkeypatch):
    bus_manager.connect('virtual')
    sender.start_cyclic('Powertrain', {'VehicleSpeed': 10}, 20)
    monkeypatch.setattr(sender, 'send_message_signals', lambda *a, **kwargs: False)
    deadline = time.monotonic() + 1
    while sender.get_cyclic_messages() and time.monotonic() < deadline:
        time.sleep(.01)
    assert sender.get_cyclic_messages() == []
    assert 'Powertrain' in sender.get_cyclic_errors()


def test_cyclic_cadence_accounts_for_adapter_send_duration(sender, monkeypatch):
    bus_manager.connect('virtual', 'cyclic-cadence')
    starts = []
    real_send = bus_manager.send_message

    def slow_send(*args, **kwargs):
        starts.append(time.monotonic())
        time.sleep(.045)
        return real_send(*args, **kwargs)

    monkeypatch.setattr(bus_manager, 'send_message', slow_send)
    sender.start_cyclic('Powertrain', {'VehicleSpeed': 10}, 80)
    deadline = time.monotonic() + 2
    while len(starts) < 6 and time.monotonic() < deadline:
        time.sleep(.005)
    sender.stop_cyclic('Powertrain')
    assert len(starts) >= 6
    intervals = [b - a for a, b in zip(starts, starts[1:])]
    assert .065 < statistics.median(intervals) < .105


def test_transmission_error_detail_and_recovery(monkeypatch):
    manager = BusManager()
    manager.connect('virtual')
    monkeypatch.setattr(manager._bus, 'send', MagicMock(side_effect=can.CanError('bus off')))
    assert not manager.send_message(0x41B, bytes(8))
    assert 'bus off' in manager.get_status()['last_tx_error']
    monkeypatch.setattr(manager._bus, 'send', MagicMock())
    assert manager.send_message(0x41B, bytes(8))
    assert manager.get_status()['last_tx_error'] is None
    manager.disconnect()


def test_api_validation_errors_and_disconnect_stops_cyclic():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        assert client.post('/bus/connect', json={'bitrate': 0}).status_code == 422
        assert client.post('/start-cyclic', json={'message_name': 'Powertrain', 'signals': {}, 'period_ms': 0}).status_code == 422
        assert client.post('/bus/connect', json={'bus_type': 'virtual'}).status_code == 200
        signal_sender.load_dbc(str(Path(__file__).parent / 'fixtures' / 'sample.dbc'))
        assert client.post('/start-cyclic', json={'message_name': 'Powertrain', 'signals': {'VehicleSpeed': 40}, 'period_ms': 20}).status_code == 200
        assert 'Powertrain' in client.get('/cyclic').json()['cyclic_messages']
        assert client.post('/bus/disconnect').status_code == 200
        assert client.get('/cyclic').json()['cyclic_messages'] == []
        result = client.post('/send', json={'message_name': 'Powertrain', 'signal_name': 'VehicleSpeed', 'value': 45})
        assert result.status_code == 500 and 'not connected' in result.json()['detail']


def test_runner_marks_send_failure():
    fake = MagicMock()
    fake.send_signal.return_value = False
    result = asyncio.run(_run_step(0, {'action': 'send_signal', 'message': 'Angles',
                                     'signal': 'PitchAngle', 'value': 1}, fake))
    assert result['status'] == 'FAIL'


def test_notifier_thread_broadcasts_to_websocket():
    from backend.api import ws
    app = FastAPI()
    app.include_router(ws.router)
    # A real python-can Notifier thread invokes the registered listener.
    bus_manager.connect('virtual', 'monitor-test')
    with TestClient(app) as client:
        with client.websocket_connect('/bus') as socket:
            assert socket.receive_json()['type'] == 'status'
            with can.Bus(interface='virtual', channel='monitor-test') as external:
                external.send(can.Message(arbitration_id=0x41B, data=bytes(8), is_extended_id=False))
                frame = socket.receive_json()
                assert frame['id'] == 0x41B and frame['direction'] == 'RX'
                assert frame['is_fd'] is False
