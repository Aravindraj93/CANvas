"""User gestures, ordered asynchronous transmission, FD setup and large DBCs."""
import os
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import can
import pytest
pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QPushButton

from backend.can.bus_manager import bus_manager
from backend.can.signal_sender import SignalSender
from backend.dbc_workspace import DbcWorkspace
from backend.desktop.app import CanvasWindow, DARK
from backend.storage import WorkspaceStore
from test_can_bench import fd_database
from test_programs_choices import engine_dbc


def finish(app, window):
    deadline = time.monotonic() + 8
    while (window._busy or window._pending_sends) and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.005)
    app.processEvents()
    assert not window._busy and not window._pending_sends


@pytest.fixture
def ui(tmp_path):
    app = QApplication.instance() or QApplication([]); app.setStyleSheet(DARK)
    workspace = DbcWorkspace(WorkspaceStore(tmp_path), SignalSender())
    workspace.upload([('engine.dbc', engine_dbc())])
    window = CanvasWindow(workspace); window.show(); app.processEvents()
    yield app, window, workspace
    window.close(); app.processEvents()


def test_enter_sends_once_and_typing_does_not_send(ui):
    app, window, workspace = ui
    bus_manager.connect('virtual', 'enter-send')
    editor = window.editors['MAP_4_BAR']
    assert editor.lineEdit().width() >= editor.width() - 20
    with can.Bus(interface='virtual', channel='enter-send') as receiver:
        editor.setFocus(); editor.selectAll(); QTest.keyClicks(editor, '23')
        app.processEvents(); assert receiver.recv(.02) is None
        QTest.keyClick(editor.lineEdit(), Qt.Key.Key_Return); finish(app, window)
        frame = receiver.recv(.5)
        assert frame is not None
        assert workspace.sender._db.decode_message(frame.arbitration_id, frame.data, decode_choices=False)['MAP_4_BAR'] == 23
        assert receiver.recv(.02) is None
        # Even unchanged Enter is an explicit send; widget rebuilds are not sends.
        QTest.keyClick(editor, Qt.Key.Key_Return); finish(app, window)
        assert receiver.recv(.5) is not None
        window._fill_messages(); app.processEvents()
        assert receiver.recv(.02) is None


def test_rapid_steps_send_every_value_in_order_without_disabling_ui(ui, monkeypatch):
    app, window, workspace = ui
    bus_manager.connect('virtual', 'step-send')
    original = workspace.sender.send_message_signals
    def delayed(*args, **kwargs):
        time.sleep(.025)
        return original(*args, **kwargs)
    monkeypatch.setattr(workspace.sender, 'send_message_signals', delayed)
    editor = window.editors['MAP_4_BAR']
    with can.Bus(interface='virtual', channel='step-send') as receiver:
        plus = window.findChild(QPushButton, 'increase_MAP_4_BAR')
        minus = window.findChild(QPushButton, 'decrease_MAP_4_BAR')
        plus.click(); plus.click(); plus.click(); minus.click()
        assert window.centralWidget().isEnabled() and window._pending_sends == 4
        finish(app, window)
        frames = [receiver.recv(.5) for _ in range(4)]
        assert all(frame is not None for frame in frames)
        decoded = [workspace.sender._db.decode_message(f.arbitration_id, f.data, decode_choices=False)['MAP_4_BAR'] for f in frames]
        assert decoded == [1, 2, 3, 2]
        assert receiver.recv(.02) is None


def test_user_choice_activation_sends_but_programmatic_selection_does_not(ui):
    app, window, workspace = ui
    bus_manager.connect('virtual', 'choice-commit')
    combo = window.signals.cellWidget(1, 2).findChild(QComboBox)
    with can.Bus(interface='virtual', channel='choice-commit') as receiver:
        index = combo.findData(4); combo.setCurrentIndex(index); app.processEvents()
        assert receiver.recv(.02) is None
        combo.activated.emit(index); finish(app, window)
        assert receiver.recv(.5).data[2] & 7 == 4
        assert receiver.recv(.02) is None


def test_switching_signals_keeps_cyclic_values_and_records_each_payload(ui):
    app, window, workspace = ui
    bus_manager.connect('virtual', 'alternate-signals')
    window.period.setValue(75)
    window.cyclic.click()
    finish(app, window)

    for search, value in [('MAP_4_BAR', 23), ('CmdIgnSts', 4), ('MAP_4_BAR', 9)]:
        window.search.setText(search)
        window._apply_filter()
        assert window.period.value() == 75
        assert window.cyclic_label.text() == '1 cyclic active'
        editor = window.editors[search]
        if search == 'CmdIgnSts':
            combo = window.signals.cellWidget(0, 2).findChild(QComboBox)
            combo.activated.emit(combo.findData(value))
        else:
            editor.setValue(value)
            QTest.keyClick(editor.lineEdit(), Qt.Key.Key_Return)
        finish(app, window)

    def decode(frame):
        return workspace.sender._db.decode_message(int(frame['can_id'], 16),
                                                    bytes.fromhex(frame['payload_hex']), decode_choices=False)

    report = window._diagnostic_report()
    edits = [frame for frame in report['recent_tx_frames'] if frame['request_id'] is not None]
    assert [frame['request_id'] for frame in edits] == [1, 2, 3]
    assert all(frame['accepted'] and frame['channel'] == 'alternate-signals' for frame in edits)
    assert [(decode(f)['MAP_4_BAR'], decode(f)['CmdIgnSts']) for f in edits] == [(23, 0), (23, 4), (9, 4)]
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        frames = window._diagnostic_report()['recent_tx_frames']
        repeated = [f for f in frames if f['cyclic'] and f['started_at_unix_s'] > edits[-1]['started_at_unix_s']]
        if repeated:
            break
        QTest.qWait(20)
    assert repeated and decode(repeated[-1]) == decode(edits[-1])


def test_fd_hint_guides_reconnect_and_never_sends_classical_fallback(ui):
    app, window, workspace = ui
    workspace.sender._db = fd_database(); workspace.sender._databases.clear()
    window.refresh_workspace(workspace.state())
    window.interface.setCurrentIndex(window.interface.findData('virtual')); window.channel.setText('fd-repair')
    bus_manager.connect('virtual', 'fd-repair'); window.refresh_status()
    window.fd.setChecked(False)
    with can.Bus(interface='virtual', channel='fd-repair') as receiver:
        assert window.fd.isVisible() and 'Classical CAN' in window.fd_hint.text()
        window._submit_send(window.selected, {'PitchAngle': 42})
        assert window._pending_sends == 0 and receiver.recv(.02) is None
        window.fd.click(); finish(app, window)
        assert bus_manager.get_status()['connected'] and not bus_manager.get_status()['fd'] and window.fd.isChecked()
        assert window.connection_panel.isVisible()
        window.apply_connection.click(); finish(app, window)
        assert bus_manager.get_status()['fd']
        window._submit_send(window.selected, {'PitchAngle': 42}); finish(app, window)
        frame = receiver.recv(.5)
        assert frame.is_fd and len(frame.data) == 16 and frame.data[0] == 42
        assert window.fd.isVisible()


def test_search_debounces_and_shows_matching_signals(ui, monkeypatch):
    app, window, workspace = ui
    calls = []
    original = window._fill_messages
    def render(): calls.append(1); original()
    monkeypatch.setattr(window, '_fill_messages', render)
    QTest.keyClicks(window.search, 'MAP_4')
    assert calls == []
    QTest.qWait(200); app.processEvents()
    assert len(calls) == 1 and window.messages.rowCount() == 1
    assert [s['name'] for s in window.visible_signals] == ['MAP_4_BAR']
    assert window.signals.rowCount() == 1


def test_hidden_monitor_does_not_decode_incoming_traffic(ui, monkeypatch):
    app, window, workspace = ui
    calls = []
    original = workspace.sender.decode_frame
    def decode(frame): calls.append(1); return original(frame)
    monkeypatch.setattr(workspace.sender, 'decode_frame', decode)
    frame = can.Message(arbitration_id=1040, is_extended_id=False, data=bytes(8))
    for _ in range(1000): window._queue_frame(frame)
    window.refresh_status()
    assert window.frames.empty() and calls == []
    window.tabs.setCurrentIndex(1)
    window._queue_frame(frame); window.refresh_status()
    assert len(calls) == 1 and window.monitor.rowCount() == 1


def test_empty_search_and_program_switch_do_not_reuse_old_edits(ui):
    app, window, workspace = ui
    window.editors['MAP_4_BAR'].setValue(33)
    window.search.setText('not-a-signal'); window._apply_filter()
    assert window.messages.rowCount() == window.signals.rowCount() == 0
    state = workspace.create_program('Other'); window.refresh_workspace(state)
    window.search.clear(); window._apply_filter()
    assert window.editors['MAP_4_BAR'].value() == 0
