"""Persistence, multiple-DBC routing, favorites and independent RX evidence."""
import asyncio
from pathlib import Path
import time

import can
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.storage import WorkspaceStore
from backend.dbc_workspace import DbcWorkspace
from backend.can.signal_sender import SignalSender, signal_sender
from backend.can.bus_manager import bus_manager
from backend.can.traffic import TrafficTracker, traffic
from backend.api import dbc as dbc_api, signals as signals_api
from backend.runner.test_runner import _run_step


def dbc(frame_id=0x100, name='Angles', signal='PitchAngle'):
    return f'''VERSION ""
NS_ :
BS_:
BU_: Bench
BO_ {frame_id} {name}: 8 Bench
 SG_ {signal} : 0|8@1+ (1,0) [0|100] "deg" Bench
'''.encode()


@pytest.fixture
def workspace(tmp_path):
    sender = SignalSender()
    value = DbcWorkspace(WorkspaceStore(tmp_path), sender)
    yield value
    sender.stop_all_cyclic()
    bus_manager.disconnect()


@pytest.fixture
def client(workspace, monkeypatch):
    monkeypatch.setattr(dbc_api, 'workspace', workspace)
    monkeypatch.setattr(signals_api, 'signal_sender', workspace.sender)
    app = FastAPI()
    app.include_router(dbc_api.router, prefix='/dbc')
    app.include_router(signals_api.router, prefix='/signals')
    with TestClient(app) as value:
        yield value


def test_multiple_files_restore_selection_and_favorites(workspace):
    result = workspace.upload([('one.dbc', dbc()), ('two.dbc', dbc(0x200, 'Body', 'RollAngle'))])
    first, second = result['uploaded_ids']
    assert len(result['messages']) == 2 and all(f['active'] for f in result['files'])
    workspace.favorite(first, 'Angles', None, True)
    workspace.favorite(second, 'Body', 'RollAngle', True)
    restored = DbcWorkspace(WorkspaceStore(workspace.store.directory), SignalSender())
    state = restored.state()
    assert len(state['files']) == len(state['messages']) == 2
    assert len(state['favorites']) == 2
    assert restored.sender.get_cyclic_messages() == []  # Never auto-replay transmissions.
    restored.activate([first])
    again = DbcWorkspace(WorkspaceStore(workspace.store.directory), SignalSender())
    assert len(again.state()['messages']) == 1 and len(again.state()['files']) == 2
    assert len(again.state()['favorites']) == 2


def test_identical_reupload_keeps_id_and_favorites(workspace):
    first = workspace.upload([('one.dbc', dbc())])['uploaded_ids'][0]
    workspace.favorite(first, 'Angles', 'PitchAngle', True)
    state = workspace.upload([('renamed.dbc', dbc())])
    assert state['uploaded_ids'] == [first]
    assert len(state['files']) == 1 and len(state['favorites']) == 1


def test_shared_ids_can_be_active_and_restore_with_sources(workspace):
    first = workspace.upload([('one.dbc', dbc())])['uploaded_ids'][0]
    state = workspace.upload([('conflict.dbc', dbc(name='Other'))])
    assert len(state['files']) == 2 and len(state['messages']) == 2
    assert state['messages'][0]['dbc_id'] == first
    assert all(f['active'] for f in state['files'])
    assert state['messages'][0]['shared_sources'] == ['one.dbc', 'conflict.dbc']
    conflict = state['uploaded_ids'][0]
    workspace.activate([first, conflict])
    assert workspace.state()['messages'][0]['dbc_id'] == first
    workspace.activate([conflict])
    assert workspace.state()['messages'][0]['name'] == 'Other'
    workspace.activate([first, conflict])
    restored = DbcWorkspace(WorkspaceStore(workspace.store.directory), SignalSender())
    assert len(restored.state()['messages']) == 2


def test_invalid_batch_does_not_save_partial_files(workspace):
    with pytest.raises(ValueError):
        workspace.upload([('good.dbc', dbc()), ('broken.dbc', b'invalid dbc data')])
    assert workspace.state()['files'] == []


def test_duplicate_names_route_by_dbc_id(workspace):
    state = workspace.upload([('first.dbc', dbc()), ('second.dbc', dbc(0x200))])
    a, b = state['uploaded_ids']
    bus_manager.connect('virtual', 'multiple-routing')
    with can.Bus(interface='virtual', channel='multiple-routing') as receiver:
        with pytest.raises(ValueError, match='multiple DBCs'):
            workspace.sender.send_signal('Angles', 'PitchAngle', 10)
        assert workspace.sender.send_signal('Angles', 'PitchAngle', 12, a)
        assert receiver.recv(1).arbitration_id == 0x100
        assert workspace.sender.send_signal('Angles', 'PitchAngle', 34, b)
        frame = receiver.recv(1)
        assert frame.arbitration_id == 0x200 and frame.data[0] == 34


def test_multi_dbc_cyclic_keys_and_stopping(workspace):
    state = workspace.upload([('first.dbc', dbc()), ('second.dbc', dbc(0x200))])
    a, b = state['uploaded_ids']
    bus_manager.connect('virtual')
    workspace.sender.start_cyclic('Angles', {'PitchAngle': 10}, 30, a)
    workspace.sender.start_cyclic('Angles', {'PitchAngle': 20}, 30, b)
    assert len(workspace.sender.get_cyclic_messages()) == 2
    workspace.sender.stop_cyclic('Angles', a)
    assert workspace.sender.get_cyclic_messages() == [f'{b}::Angles']
    workspace.activate([a])
    assert workspace.sender.get_cyclic_messages() == []


def test_favorites_are_scoped_and_delete_cascades(workspace):
    state = workspace.upload([('first.dbc', dbc()), ('second.dbc', dbc(0x200))])
    a, b = state['uploaded_ids']
    workspace.favorite(a, 'Angles', 'PitchAngle', True)
    assert workspace.state()['favorites'] == [{'dbc_id': a, 'message_name': 'Angles', 'signal_name': 'PitchAngle'}]
    with pytest.raises(ValueError, match='Signal not found'):
        workspace.favorite(a, 'Angles', 'WrongSignal', True)
    state = workspace.delete(a)
    assert state['favorites'] == [] and len(state['messages']) == 1
    assert state['messages'][0]['dbc_id'] == b


def test_upload_filename_cannot_escape_data_directory(workspace):
    state = workspace.upload([('C:\\private\\..\\bench.dbc', dbc())])
    assert state['files'][0]['filename'] == 'bench.dbc'
    assert sorted(p.name for p in workspace.store.directory.iterdir()) == ['workspace.sqlite3']


def message():
    return SignalSender.parse_dbc(dbc()).messages[0]


def test_tx_acceptance_and_echo_do_not_pass_rx_verification():
    tracker = TrafficTracker()
    msg = message()
    tracker.record_tx(msg.frame_id, False)
    assert tracker.view(msg)['state'] == 'tx_only'
    frame = can.Message(arbitration_id=msg.frame_id, is_extended_id=False,
                        data=msg.encode({'PitchAngle': 25}), is_rx=False)
    tracker.on_frame(frame)
    state = tracker.view(msg)
    assert state['state'] == 'tx_echo' and state['tx_echo_count'] == 1 and state['rx_count'] == 0
    assert tracker.verify(msg, {'PitchAngle': 25})['status'] == 'FAIL'


def test_rx_match_mismatch_staleness_and_disconnect():
    now = [100.0]
    tracker = TrafficTracker(clock=lambda: now[0])
    msg = message()
    tracker.on_frame(can.Message(arbitration_id=msg.frame_id, is_extended_id=False,
                                data=msg.encode({'PitchAngle': 25}), is_rx=True, timestamp=0))
    assert tracker.view(msg)['state'] == 'receiving'
    assert tracker.verify(msg, {'PitchAngle': 25})['status'] == 'PASS'
    assert tracker.verify(msg, {'PitchAngle': 30})['status'] == 'FAIL'
    now[0] += 2
    assert tracker.view(msg)['state'] == 'stale'
    assert tracker.verify(msg, {'PitchAngle': 25})['status'] == 'FAIL'
    assert tracker.verify(msg, {'PitchAngle': 25}, connected=False)['status'] == 'FAIL'
    tracker.reset()
    assert tracker.view(msg)['state'] == 'not_seen'


@pytest.mark.parametrize('frame', [
    can.Message(arbitration_id=0x100, is_extended_id=False, data=b'\x19'),
    can.Message(arbitration_id=0x100, is_extended_id=False, data=bytes(8), is_fd=True),
])
def test_invalid_rx_format_never_verifies(frame):
    tracker = TrafficTracker()
    tracker.on_frame(frame)
    assert tracker.view(message())['state'] == 'decode_error'
    assert tracker.verify(message(), {'PitchAngle': 25})['status'] == 'FAIL'


def test_extended_id_does_not_match_standard_definition():
    tracker = TrafficTracker()
    tracker.on_frame(can.Message(arbitration_id=0x100, is_extended_id=True, data=bytes(8)))
    assert tracker.view(message())['rx_count'] == 0


def test_api_multi_upload_favorites_and_rx_evidence(client, workspace):
    state = client.post('/dbc/upload-many', files=[
        ('files', ('a.dbc', dbc(), 'text/plain')),
        ('files', ('b.dbc', dbc(0x200, 'Body', 'RollAngle'), 'text/plain')),
    ]).json()
    assert state['message_count'] == 2
    dbc_id = state['uploaded_ids'][0]
    result = client.post('/dbc/favorites', json={'dbc_id': dbc_id, 'message_name': 'Angles', 'favorite': True})
    assert result.status_code == 200 and len(result.json()['favorites']) == 1
    assert client.get('/dbc/state').json()['favorites'] == result.json()['favorites']
    assert client.post('/signals/bus/connect', json={'bus_type': 'virtual', 'channel': 'api-rx-test'}).status_code == 200
    request = {'dbc_id': dbc_id, 'message_name': 'Angles', 'expected': {'PitchAngle': 42}}
    assert client.post('/signals/verify', json=request).json()['status'] == 'FAIL'
    with can.Bus(interface='virtual', channel='api-rx-test') as external:
        external.send(can.Message(arbitration_id=0x100, is_extended_id=False,
                                  data=message().encode({'PitchAngle': 42})))
        deadline = time.monotonic() + 1
        while traffic.view(message())['rx_count'] == 0 and time.monotonic() < deadline:
            time.sleep(.01)
    result = client.post('/signals/verify', json=request)
    assert result.status_code == 200 and result.json()['status'] == 'PASS'
    status = client.get('/signals/status', params=[('visible_only', 'true'), ('keys', f'{dbc_id}::Angles')]).json()
    assert len(status['messages']) == 1
    assert status['messages'][f'{dbc_id}::Angles']['rx_count'] == 1
    assert client.post('/signals/bus/disconnect').status_code == 200
    assert client.post('/signals/verify', json=request).json()['status'] == 'FAIL'
    assert len(client.get('/dbc/state').json()['files']) == 2


def test_yaml_assert_signal_uses_actual_rx(workspace):
    dbc_id = workspace.upload([('a.dbc', dbc())])['uploaded_ids'][0]
    bus_manager.connect('virtual')
    step = {'action': 'assert_signal', 'message': 'Angles', 'dbc_id': dbc_id,
            'signal': 'PitchAngle', 'expected': 42}
    assert asyncio.run(_run_step(0, step, workspace.sender))['status'] == 'FAIL'
    traffic.on_frame(can.Message(arbitration_id=0x100, is_extended_id=False,
                                data=message().encode({'PitchAngle': 42})))
    assert asyncio.run(_run_step(0, step, workspace.sender))['status'] == 'PASS'
