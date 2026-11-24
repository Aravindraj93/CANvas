"""Production DBC edge cases must remain browsable without unsafe scaling changes."""
import can
import pytest

from backend.can.bus_manager import bus_manager
from backend.can.signal_sender import SignalSender
from backend.dbc_workspace import DbcWorkspace
from backend.storage import WorkspaceStore
from test_programs_choices import engine_dbc


def zero_scale_dbc():
    return b'''VERSION ""
NS_ :
BS_:
BU_: Bench
BO_ 700 Mixed: 8 Bench
 SG_ Reserved : 0|8@1+ (0,0) [0|0] "" Bench
 SG_ Angle : 8|8@1+ (0.5,-10) [-10|100] "deg" Bench
BA_DEF_ SG_ "GenSigStartValue" INT 0 255;
BA_ "GenSigStartValue" SG_ 700 Reserved 5;
'''


def test_zero_scale_import_restores_and_preserves_raw_bits(tmp_path):
    workspace = DbcWorkspace(WorkspaceStore(tmp_path), SignalSender())
    state = workspace.upload([('reserved.dbc', zero_scale_dbc())])
    dbc_id = state['uploaded_ids'][0]
    reserved = state['messages'][0]['signals'][0]
    assert reserved['read_only'] and reserved['raw_initial'] == 5
    assert 'Zero-scale' in reserved['default_warning']
    restored = DbcWorkspace(WorkspaceStore(tmp_path), SignalSender())
    assert restored.state()['messages'][0]['signals'][0]['read_only']
    try:
        bus_manager.connect('virtual', 'zero-scale')
        with can.Bus(interface='virtual', channel='zero-scale') as receiver:
            assert restored.sender.send_signal('Mixed', 'Angle', 20, dbc_id)
            frame = receiver.recv(.5)
            assert frame.data[0] == 5 and frame.data[1] == 60
            with pytest.raises(ValueError, match='Reserved'):
                restored.sender.send_signal('Mixed', 'Reserved', 1, dbc_id)
            assert receiver.recv(.02) is None
    finally:
        bus_manager.disconnect()


def test_bad_signal_does_not_block_importing_other_messages(tmp_path):
    content = zero_scale_dbc() + b'''BO_ 701 BadRange: 8 Bench
 SG_ Impossible : 0|8@1+ (1,0) [0.1|0.2] "" Bench
'''
    workspace = DbcWorkspace(WorkspaceStore(tmp_path), SignalSender())
    state = workspace.upload([('edge.dbc', content)])
    assert state['message_count'] == 2
    assert state['messages'][1]['signals'][0]['read_only']
    assert 'correction' in state['messages'][1]['signals'][0]['default_warning']


def test_favorites_and_program_switch_reuse_parsed_dbc(tmp_path, monkeypatch):
    workspace = DbcWorkspace(WorkspaceStore(tmp_path), SignalSender())
    calls = []
    parse = SignalSender.parse_dbc
    def counted(content): calls.append(1); return parse(content)
    monkeypatch.setattr(SignalSender, 'parse_dbc', staticmethod(counted))
    state = workspace.upload([('engine.dbc', engine_dbc())])
    dbc_id = state['uploaded_ids'][0]
    workspace.favorite(dbc_id, 'ENGINE_FD_8', 'CmdIgnSts', True)
    workspace.state(); workspace.state(); workspace.create_program('Other'); workspace.select_program('default')
    assert len(calls) == 1


def test_bad_parse_reports_filename_and_keeps_existing_workspace(tmp_path):
    workspace = DbcWorkspace(WorkspaceStore(tmp_path), SignalSender())
    workspace.upload([('engine.dbc', engine_dbc())])
    with pytest.raises(ValueError, match='broken.dbc'):
        workspace.upload([('broken.dbc', b'not a dbc')])
    assert len(workspace.state()['files']) == 1
