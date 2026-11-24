"""A failed saved DBC must not hide every other message after a real restart."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from backend.can.bus_manager import bus_manager
from backend.can.signal_sender import SignalSender
from backend.dbc_workspace import DbcWorkspace
from backend.storage import WorkspaceStore
from test_workspace_status import dbc


def saved_workspace(tmp_path, bad_content=b'not a valid DBC'):
    store = WorkspaceStore(tmp_path)
    ws = DbcWorkspace(store, SignalSender())
    state = ws.upload([('pitch.dbc', dbc()), ('roll.dbc', dbc(0x200, 'Body', 'RollAngle'))])
    good = state['uploaded_ids']
    ws.favorite(good[0], 'Angles', 'PitchAngle', True)
    program = ws.create_program('ORP')['active_program_id']
    ws.favorite(good[1], 'Body', 'RollAngle', True)
    bad = store.save_many([('failed.dbc', bad_content, 1)])[0]
    store.set_active(good + [bad])
    return store, good, bad, program


@pytest.mark.parametrize('bad_content', [b'not a valid DBC',
    dbc() + b'BO_ 256 DuplicateID: 8 Bench\n SG_ Other : 0|8@1+ (1,0) [0|100] "" Bench\n'])
def test_startup_isolates_parse_and_validation_errors_without_changing_saved_data(tmp_path, bad_content):
    store, good, bad, program = saved_workspace(tmp_path, bad_content)
    before = store.list_dbcs(), store.program_dbc_ids(program), store.favorites()
    restored = DbcWorkspace(WorkspaceStore(tmp_path), SignalSender())
    state = restored.state()
    assert {m['name'] for m in state['messages']} == {'Angles', 'Body'}
    assert all(f['active'] for f in state['files'])
    assert {f['id'] for f in state['files'] if f['loaded']} == set(good)
    assert state['restore_errors'][0]['dbc_id'] == bad
    assert 'failed.dbc' in state['restore_error']
    assert before == (store.list_dbcs(), store.program_dbc_ids(program), store.favorites())
    assert store.get(bad)['content'] == bad_content
    assert restored.sender.get_cyclic_messages() == []


def test_switching_to_program_with_failed_file_keeps_its_good_messages(tmp_path):
    store, good, bad, program = saved_workspace(tmp_path)
    restored = DbcWorkspace(store, SignalSender())
    default = restored.select_program('default')
    assert len(default['messages']) == 2 and default['restore_error'] is None
    state = restored.select_program(program)
    assert len(state['messages']) == 2 and 'failed.dbc' in state['restore_error']
    assert state['active_program_id'] == program
    assert state['favorites'][0]['signal_name'] == 'RollAngle'


def test_reload_recovers_transient_failure_and_keeps_program_favorites(tmp_path, monkeypatch):
    store = WorkspaceStore(tmp_path)
    ws = DbcWorkspace(store, SignalSender())
    state = ws.upload([('pitch.dbc', dbc()), ('roll.dbc', dbc(0x200, 'Body', 'RollAngle'))])
    first, second = state['uploaded_ids']
    ws.favorite(first, 'Angles', 'PitchAngle', True)
    parse = SignalSender.parse_dbc
    def fail_one(content):
        if b'RollAngle' in content:
            raise ValueError('temporary parser failure')
        return parse(content)
    with monkeypatch.context() as patch:
        patch.setattr(SignalSender, 'parse_dbc', staticmethod(fail_one))
        restored = DbcWorkspace(WorkspaceStore(tmp_path), SignalSender())
        assert len(restored.state()['messages']) == 1
    state = restored.reload()
    assert len(state['messages']) == 2 and state['restore_error'] is None
    assert state['restore_errors'] == [] and all(f['loaded'] for f in state['files'])
    assert state['favorites'] == store.favorites()
    assert not bus_manager.get_status()['connected']


def test_fresh_process_restores_good_files_beside_failed_file(tmp_path):
    store, good, bad, program = saved_workspace(tmp_path)
    result = subprocess.run([sys.executable, '-c', '''
import json
from backend.dbc_workspace import workspace
state = workspace.state()
print(json.dumps({'messages': [m['name'] for m in state['messages']],
                  'error': state['restore_error'], 'program': state['active_program_id']}))
'''], cwd=Path(__file__).resolve().parents[1], env={**os.environ, 'CANVAS_DATA_DIR': str(tmp_path)},
        capture_output=True, text=True, check=True)
    state = json.loads(result.stdout)
    assert set(state['messages']) == {'Angles', 'Body'}
    assert state['program'] == program and 'failed.dbc' in state['error']


def test_desktop_search_and_persistent_error_survive_connection_and_retry(tmp_path):
    pytest.importorskip('PySide6.QtWidgets')
    from PySide6.QtWidgets import QApplication
    from backend.desktop.app import CanvasWindow
    from test_desktop_responsiveness import finish
    store, good, bad, program = saved_workspace(tmp_path)
    app = QApplication.instance() or QApplication([])
    ws = DbcWorkspace(WorkspaceStore(tmp_path), SignalSender())
    window = CanvasWindow(ws); window.show(); app.processEvents()
    try:
        assert window.messages.rowCount() == 2 and window.signals.rowCount() == 1
        assert window.dbc_error.isVisible() and 'failed.dbc' in window.dbc_error.text()
        assert '3 enabled · 2 loaded' in window.file_count.text()
        window.search.setText('roll angle'); window.search.setFocus(); window._apply_filter()
        assert window.search.hasFocus() and window.visible_signals[0]['name'] == 'RollAngle'
        window.interface.setCurrentIndex(window.interface.findData('virtual'))
        window.channel.setText('restore-ui'); window.apply_connection.click(); finish(app, window)
        assert bus_manager.get_status()['connected'] and window.dbc_error.isVisible()
        report = window._diagnostic_report()
        assert report['workspace']['message_count'] == 2
        assert report['workspace']['restore_errors'][0]['filename'] == 'failed.dbc'
        json.dumps(report)
        window.reload_dbcs.click(); finish(app, window)
        assert window.messages.rowCount() == 1 and window.search.text() == 'roll angle'
        assert window.dbc_error.isVisible() and bus_manager.get_status()['connected']
        window.refresh_workspace(ws.activate(good))
        assert not window.dbc_error.isVisible()
    finally:
        window.close(); app.processEvents()


def test_all_failed_empty_state_names_loading_problem_and_diagnostics_work(tmp_path):
    pytest.importorskip('PySide6.QtWidgets')
    from PySide6.QtWidgets import QApplication
    from backend.desktop.app import CanvasWindow
    store = WorkspaceStore(tmp_path)
    ids = store.save_many([('failed.dbc', b'broken', 1)]); store.set_active(ids)
    app = QApplication.instance() or QApplication([])
    window = CanvasWindow(DbcWorkspace(store, SignalSender())); window.show(); app.processEvents()
    try:
        assert window.messages.rowCount() == window.signals.rowCount() == 0
        assert 'DBC loading failed' in window.selected_title.text()
        assert 'failed.dbc' in window.dbc_error.text()
        window._set_note('Ready')
        assert window.dbc_error.isVisible()
        report = window._diagnostic_report()
        assert report['selected_message'] is None
        assert report['workspace']['files'][0]['load_error']
    finally:
        window.close(); app.processEvents()
