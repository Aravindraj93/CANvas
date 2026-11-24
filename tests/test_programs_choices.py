import sqlite3

import can
import pytest

from backend.storage import WorkspaceStore
from backend.dbc_workspace import DbcWorkspace
from backend.can.signal_sender import SignalSender
from backend.can.bus_manager import bus_manager


def engine_dbc(with_sna=False):
    text = '''VERSION ""
NS_ :
BS_:
BU_: Bench
BO_ 1040 ENGINE_FD_8: 8 Bench
 SG_ MAP_4_BAR : 0|9@1+ (1,0) [0|408] "kPa" Bench
 SG_ CmdIgnSts : 16|3@1+ (1,0) [0|7] "" Bench
BA_DEF_ SG_ "GenSigStartValue" INT 0 511;
BA_ "GenSigStartValue" SG_ 1040 MAP_4_BAR 511;
VAL_ 1040 CmdIgnSts 0 "Initialization" 1 "IGN_LK" 2 "ACC" 4 "RUN" 5 "START" 7 "SNA";
'''
    if with_sna:
        text += 'VAL_ 1040 MAP_4_BAR 511 "SNA";\n'
    return text.encode()


@pytest.fixture
def workspace(tmp_path):
    value = DbcWorkspace(WorkspaceStore(tmp_path), SignalSender())
    yield value
    value.sender.stop_all_cyclic()
    bus_manager.disconnect()


def test_program_favorites_and_dbc_selection_are_independent(workspace):
    state = workspace.upload([('engine.dbc', engine_dbc())]); dbc_id = state['uploaded_ids'][0]
    workspace.favorite(dbc_id, 'ENGINE_FD_8', 'CmdIgnSts', True)
    state = workspace.create_program('Trailer Tow'); second = state['active_program_id']
    assert state['favorites'] == [] and len(state['messages']) == 1
    workspace.favorite(dbc_id, 'ENGINE_FD_8', None, True)
    workspace.activate([])
    state = workspace.select_program('default')
    assert len(state['messages']) == 1 and state['favorites'][0]['signal_name'] == 'CmdIgnSts'
    state = workspace.select_program(second)
    assert state['messages'] == [] and state['favorites'][0]['signal_name'] == ''
    restored = DbcWorkspace(WorkspaceStore(workspace.store.directory), SignalSender()).state()
    assert restored['active_program_id'] == second and restored['messages'] == []


def test_program_names_validate_and_switch_stops_cyclic(workspace):
    state = workspace.upload([('engine.dbc', engine_dbc())]); dbc_id = state['uploaded_ids'][0]
    with pytest.raises(ValueError): workspace.create_program('  ')
    with pytest.raises(ValueError): workspace.create_program('DEFAULT')
    with pytest.raises(ValueError): workspace.select_program('missing')
    bus_manager.connect('virtual')
    workspace.sender.start_cyclic('ENGINE_FD_8', {'CmdIgnSts': 'RUN'}, 20, dbc_id)
    workspace.create_program('HVAC')
    assert workspace.sender.get_cyclic_messages() == []


def test_legacy_workspace_migrates_existing_favorites(tmp_path):
    path = tmp_path / 'workspace.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript('''CREATE TABLE dbcs (id TEXT PRIMARY KEY, filename TEXT, content BLOB, message_count INTEGER, active INTEGER, created_at REAL);
        CREATE TABLE favorites (dbc_id TEXT, message_name TEXT, signal_name TEXT, PRIMARY KEY(dbc_id,message_name,signal_name));''')
        db.execute('INSERT INTO dbcs VALUES (?, ?, ?, 1, 1, 0)', ('abc','engine.dbc',engine_dbc()))
        db.execute("INSERT INTO favorites VALUES ('abc','ENGINE_FD_8','CmdIgnSts')")
    store = WorkspaceStore(tmp_path)
    assert store.active_program() == 'default'
    assert store.program_dbc_ids('default') == ['abc']
    assert store.favorites()[0]['signal_name'] == 'CmdIgnSts'
    # Opening it again must not reset the migrated program or favorites.
    assert WorkspaceStore(tmp_path).favorites() == store.favorites()


def test_invalid_dbc_default_does_not_break_another_signal(workspace):
    state = workspace.upload([('engine.dbc', engine_dbc())]); dbc_id = state['uploaded_ids'][0]
    sig = state['messages'][0]['signals'][0]
    assert sig['initial_value'] == 0 and '511' in sig['default_warning']
    bus_manager.connect('virtual', 'map-regression')
    with can.Bus(interface='virtual', channel='map-regression') as receiver:
        assert workspace.sender.send_signal('ENGINE_FD_8', 'CmdIgnSts', 'RUN', dbc_id)
        frame = receiver.recv(1)
        _, msg = workspace.sender.resolve_message('ENGINE_FD_8', dbc_id)
        decoded = msg.decode(frame.data, decode_choices=False)
        assert decoded['MAP_4_BAR'] == 0 and decoded['CmdIgnSts'] == 4
        with pytest.raises(ValueError, match='outside'):
            workspace.sender.send_signal('ENGINE_FD_8', 'MAP_4_BAR', 511, dbc_id)
        with pytest.raises(ValueError, match='Unknown choice'):
            workspace.sender.send_signal('ENGINE_FD_8', 'CmdIgnSts', 'NotDefined', dbc_id)


def test_defined_sna_outside_numeric_range_is_selectable(workspace):
    state = workspace.upload([('engine.dbc', engine_dbc(True))]); dbc_id = state['uploaded_ids'][0]
    sig = state['messages'][0]['signals'][0]
    assert sig['initial_value'] == 511 and sig['default_warning'] is None
    assert sig['choices'] == [{'raw_value': 511, 'value': 511.0, 'label': 'SNA'}]
    bus_manager.connect('virtual')
    assert workspace.sender.send_signal('ENGINE_FD_8', 'MAP_4_BAR', 'SNA', dbc_id)


def test_choice_raw_codes_use_physical_scaling(workspace):
    content = engine_dbc().replace(b'(1,0) [0|7]', b'(0.5,10) [10|13]')
    state = workspace.upload([('scaled.dbc', content)]); dbc_id = state['uploaded_ids'][0]
    sig = state['messages'][0]['signals'][1]
    assert next(c for c in sig['choices'] if c['label'] == 'RUN')['value'] == 12
    bus_manager.connect('virtual','scaled-choice')
    with can.Bus(interface='virtual',channel='scaled-choice') as receiver:
        assert workspace.sender.send_signal('ENGINE_FD_8','CmdIgnSts','RUN',dbc_id)
        assert receiver.recv(1).data[2] & 7 == 4


def test_fractional_minimum_default_is_representable(workspace):
    content = engine_dbc().replace(b'(1,0) [0|408]', b'(1,0) [0.1|408]')
    state = workspace.upload([('fractional.dbc',content)])
    assert state['messages'][0]['signals'][0]['initial_value'] == 1


def test_api_programs_and_named_choices(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import dbc as dbc_api, signals as signals_api
    local = DbcWorkspace(WorkspaceStore(tmp_path), SignalSender())
    monkeypatch.setattr(dbc_api,'workspace',local)
    monkeypatch.setattr(signals_api,'signal_sender',local.sender)
    app=FastAPI(); app.include_router(dbc_api.router,prefix='/dbc'); app.include_router(signals_api.router,prefix='/signals')
    try:
        with TestClient(app) as client:
            response=client.post('/dbc/programs',json={'name':'Off-road'})
            assert response.status_code==200
            program_id=response.json()['active_program_id']
            state=client.post('/dbc/upload',files={'file':('engine.dbc',engine_dbc())}).json()
            dbc_id=state['uploaded_ids'][0]
            assert client.post('/signals/bus/connect',json={'bus_type':'virtual'}).status_code==200
            response=client.post('/signals/send',json={'dbc_id':dbc_id,'message_name':'ENGINE_FD_8','signal_name':'CmdIgnSts','value':'RUN'})
            assert response.status_code==200,response.text
            assert client.post('/dbc/programs/select',json={'program_id':'default'}).json()['messages']==[]
            assert client.post('/dbc/programs/select',json={'program_id':program_id}).json()['message_count']==1
    finally:
        local.sender.stop_all_cyclic(); bus_manager.disconnect()


def test_scaled_sna_initial_uses_physical_value_not_raw_code(workspace):
    content = engine_dbc(True).replace(b'(1,0) [0|408]', b'(0.8,0) [0|408]')
    state = workspace.upload([('scaled-sna.dbc',content)])
    dbc_id = state['uploaded_ids'][0]
    assert state['messages'][0]['signals'][0]['initial_value'] == pytest.approx(408.8)
    bus_manager.connect('virtual','scaled-sna')
    with can.Bus(interface='virtual',channel='scaled-sna') as receiver:
        assert workspace.sender.send_signal('ENGINE_FD_8','CmdIgnSts','RUN',dbc_id)
        frame=receiver.recv(1)
        assert (frame.data[0] | ((frame.data[1] & 1) << 8)) == 511
