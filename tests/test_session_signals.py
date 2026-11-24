"""Full choice text and accepted session payload monitoring/control."""
import asyncio
import os

import can
import pytest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox

from backend.can.bus_manager import bus_manager
from backend.runner.test_runner import _run_step
from test_desktop_responsiveness import ui, finish
from test_programs_choices import engine_dbc


def open_session(app, window):
    window.tabs.setCurrentWidget(window.session_page)
    window.refresh_status(); app.processEvents()


def row_for(window, name):
    return next(row for row in range(window.session_table.rowCount())
                if window.session_table.item(row, 0).text() == name)


def test_choice_text_fits_closed_control_and_popup(ui):
    app, window, workspace = ui
    label = 'Ignition running with accessory power and all vehicle systems enabled'
    content = engine_dbc().replace(b'"RUN"', f'"{label}"'.encode())
    workspace.activate([])
    workspace.upload([('long-choice.dbc', content)])
    window.refresh_workspace(workspace.state()); app.processEvents()
    combo = window.signals.cellWidget(1, 2).findChild(QComboBox)
    combo.setCurrentIndex(combo.findData(4)); app.processEvents()
    required = combo.fontMetrics().horizontalAdvance(combo.currentText())
    assert label in combo.currentText()
    assert combo.width() >= required + 30
    assert combo.view().minimumWidth() >= required + 30
    assert combo.view().textElideMode() == Qt.TextElideMode.ElideNone
    assert window.signals.rowHeight(1) >= 78


def test_session_records_payload_and_controls_send_once(ui):
    app, window, workspace = ui
    bus_manager.connect('virtual', 'session-control')
    key = window.selected['key']
    with can.Bus(interface='virtual', channel='session-control') as receiver:
        window._submit_send(window.selected, {'MAP_4_BAR': 23}); finish(app, window)
        assert receiver.recv(.5) is not None
        open_session(app, window)
        assert window.session_table.rowCount() == 2
        row = row_for(window, 'MAP_4_BAR')
        assert window.session_table.item(row, 2).text() == '23'
        assert window.session_table.item(row, 9).text() == 'Selected'
        assert window.session_table.item(row_for(window, 'CmdIgnSts'), 9).text() == 'Payload field'
        editor = window._session_editors[(key, 'MAP_4_BAR')]
        editor.setValue(24); app.processEvents()
        assert receiver.recv(.02) is None
        assert window.editors['MAP_4_BAR'].value() == 24
        QTest.keyClick(editor.lineEdit(), Qt.Key.Key_Return); finish(app, window)
        assert receiver.recv(.5) is not None and receiver.recv(.02) is None
        assert window.session_table.item(row, 2).text() == '24'
        combo = window.session_table.cellWidget(row_for(window, 'CmdIgnSts'), 3).findChild(QComboBox)
        combo.activated.emit(combo.findData(4)); finish(app, window)
        assert receiver.recv(.5).data[2] & 7 == 4
        assert receiver.recv(.02) is None
        assert len(workspace.sender.get_session_signals('default')) == 2


def test_session_cycle_controls_and_polling_preserve_editor(ui):
    app, window, workspace = ui
    bus_manager.connect('virtual', 'session-cycle')
    msg = window.selected
    workspace.sender.start_cyclic(msg['name'], {'MAP_4_BAR': 7}, 40, msg['dbc_id'])
    open_session(app, window)
    row = row_for(window, 'MAP_4_BAR'); editor = window._session_editors[(msg['key'], 'MAP_4_BAR')]
    assert window.session_table.item(row, 5).text() == 'Cyclic'
    assert window.session_table.cellWidget(row, 6).value() == 40
    QTest.qWait(100); window.refresh_status()
    assert window._session_editors[(msg['key'], 'MAP_4_BAR')] is editor
    editor.setValue(12); QTest.keyClick(editor.lineEdit(), Qt.Key.Key_Return); finish(app, window)
    QTest.qWait(80)
    snapshot = workspace.sender.get_session_signals('default')
    assert next(r['value'] for r in snapshot if r['signal'] == 'MAP_4_BAR') == 12
    window.session_table.cellWidget(row, 7).click(); finish(app, window)
    assert not workspace.sender.get_cyclic_messages()
    assert window.session_table.item(row, 5).text() == 'Not cyclic'
    window.session_table.cellWidget(row, 6).setValue(60)
    window.session_table.cellWidget(row, 7).click(); finish(app, window)
    assert workspace.sender.get_cyclic_periods()[msg['key']] == 60
    workspace.sender.stop_all_cyclic(); window.refresh_status()
    window.session_cycles_only.setChecked(True)
    assert window.session_table.rowCount() == 0


def test_session_history_excludes_failures_and_survives_reconnect_program_and_dbc_changes(ui, monkeypatch):
    app, window, workspace = ui
    bus_manager.connect('virtual', 'session-history')
    msg = window.selected
    sender = workspace.sender
    with monkeypatch.context() as patch:
        patch.setattr(bus_manager, 'send_message', lambda **kwargs: False)
        assert not sender.send_signal(msg['name'], 'MAP_4_BAR', 5, msg['dbc_id'])
    assert sender.get_session_signals('default') == []
    assert sender.send_signal(msg['name'], 'MAP_4_BAR', 5, msg['dbc_id'])
    with pytest.raises(ValueError): sender.send_signal(msg['name'], 'MAP_4_BAR', 999, msg['dbc_id'])
    snapshot = sender.get_session_signals('default')
    assert snapshot[0]['value'] == 5 and snapshot[0]['count'] == 1
    snapshot[0]['value'] = 999
    assert sender.get_session_signals('default')[0]['value'] == 5
    bus_manager.disconnect(); bus_manager.connect('virtual', 'session-history')
    state = workspace.create_program('Other'); window.refresh_workspace(state)
    open_session(app, window)
    assert window.session_table.rowCount() == 0
    sender.send_signal(msg['name'], 'MAP_4_BAR', 9, msg['dbc_id'])
    window.refresh_status()
    assert window.session_table.item(row_for(window, 'MAP_4_BAR'), 2).text() == '9'
    window.refresh_workspace(workspace.select_program('default')); window.refresh_status()
    assert window.session_table.item(row_for(window, 'MAP_4_BAR'), 2).text() == '5'
    window.refresh_workspace(workspace.activate([])); window.refresh_status()
    row = row_for(window, 'MAP_4_BAR')
    assert window.session_table.item(row, 5).text() == 'DBC inactive / removed'
    assert window.session_table.cellWidget(row, 3) is None
    assert window.session_table.cellWidget(row, 7) is None


def test_yaml_sends_are_tracked_without_studio_requests(ui):
    app, window, workspace = ui
    bus_manager.connect('virtual', 'session-yaml')
    result = asyncio.run(_run_step(0, {'action': 'send_signal', 'message': window.selected['name'],
                                      'signal': 'CmdIgnSts', 'value': 'RUN', 'dbc_id': window.selected['dbc_id']},
                                   workspace.sender))
    assert result['status'] == 'PASS'
    assert not window._recent_requests
    open_session(app, window)
    assert window.session_table.item(row_for(window, 'CmdIgnSts'), 2).text() == '4'
    assert window.session_table.item(row_for(window, 'CmdIgnSts'), 9).text() == 'Selected'


def test_filter_preserves_drafts_and_restarting_cycle_preserves_hidden_payload(ui):
    app, window, workspace = ui
    bus_manager.connect('virtual', 'session-filter')
    msg = window.selected
    workspace.sender.send_message_signals(msg['name'], {'MAP_4_BAR': 23, 'CmdIgnSts': 4}, msg['dbc_id'])
    open_session(app, window)
    window._session_editors[(msg['key'], 'MAP_4_BAR')].setValue(24)
    window.session_search.setText('CmdIgnSts')
    window.session_search.clear()
    assert window._session_editors[(msg['key'], 'MAP_4_BAR')].value() == 24
    assert window.session_table.item(row_for(window, 'MAP_4_BAR'), 2).text() == '23'
    # Definition reload clears sender payload state, but session history remains.
    window.refresh_workspace(workspace.reload())
    window.session_search.setText('MAP_4_BAR'); window.refresh_status()
    assert window.session_table.rowCount() == 1
    window.session_table.cellWidget(0, 7).click(); finish(app, window)
    values = {r['signal']: r['value'] for r in workspace.sender.get_session_signals('default')}
    assert values == {'MAP_4_BAR': 24, 'CmdIgnSts': 4}


def test_shared_dbc_ids_keep_separate_session_values(ui):
    app, window, workspace = ui
    state = workspace.upload([('second.dbc', engine_dbc().replace(b'"RUN"', b'"Running"'))])
    window.refresh_workspace(state)
    first, second = state['messages']
    bus_manager.connect('virtual', 'session-shared')
    workspace.sender.send_signal(first['name'], 'MAP_4_BAR', 3, first['dbc_id'])
    workspace.sender.send_signal(second['name'], 'MAP_4_BAR', 9, second['dbc_id'])
    open_session(app, window)
    assert window.session_table.rowCount() == 4
    assert window._session_editors[(first['key'], 'MAP_4_BAR')].value() == 3
    assert window._session_editors[(second['key'], 'MAP_4_BAR')].value() == 9


def test_multiplexed_fields_not_in_current_payload_are_not_shown_as_active_cyclic(ui):
    app, window, workspace = ui
    content = b'''VERSION ""
NS_ :
BS_:
BU_: Bench
BO_ 1050 MuxMessage: 3 Bench
 SG_ Selector M : 0|8@1+ (1,0) [0|1] "" Bench
 SG_ BranchA m0 : 8|8@1+ (1,0) [0|255] "" Bench
 SG_ BranchB m1 : 8|8@1+ (1,0) [0|255] "" Bench
'''
    workspace.activate([])
    state = workspace.upload([('mux.dbc', content)]); window.refresh_workspace(state)
    msg = state['messages'][0]
    bus_manager.connect('virtual', 'session-mux')
    workspace.sender.send_message_signals(msg['name'], {'Selector': 0, 'BranchA': 3, 'BranchB': 9}, msg['dbc_id'])
    assert {r['signal'] for r in workspace.sender.get_session_signals('default')} == {'Selector', 'BranchA'}
    workspace.sender.start_cyclic(msg['name'], {'Selector': 1, 'BranchB': 9}, 40, msg['dbc_id'])
    open_session(app, window)
    assert window.session_table.item(row_for(window, 'BranchA'), 5).text() == 'Cyclic · field inactive'
    assert window.session_table.item(row_for(window, 'BranchB'), 5).text() == 'Cyclic'


