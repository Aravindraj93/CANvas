"""Native Qt interactions; skipped when the optional desktop extra is absent."""
import os
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import can
import pytest
pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtWidgets import QApplication, QComboBox

from backend.desktop.app import CanvasWindow, DARK
from backend.dbc_workspace import DbcWorkspace
from backend.storage import WorkspaceStore
from backend.can.signal_sender import SignalSender
from backend.can.bus_manager import bus_manager
from backend.can.traffic import traffic
from test_programs_choices import engine_dbc


def wait(app, window):
    deadline = time.monotonic() + 5
    while window._busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    app.processEvents()
    assert not window._busy, 'Desktop action did not finish'


def test_native_choice_send_favorite_and_program_switch(tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(DARK)
    workspace = DbcWorkspace(WorkspaceStore(tmp_path), SignalSender())
    state = workspace.upload([('engine.dbc', engine_dbc())])
    dbc_id = state['uploaded_ids'][0]
    window = CanvasWindow(workspace); window.show(); app.processEvents()
    try:
        assert window.messages.rowCount() == 1 and window.signals.rowCount() == 2
        assert window.editors['MAP_4_BAR'].value() == 0
        assert '511' in window.signals.item(0,5).text()
        combo = window.signals.cellWidget(1,2).findChild(QComboBox)
        combo.setCurrentIndex(combo.findData(4))
        assert window.editors['CmdIgnSts'].value() == 4
        window.interface.setCurrentIndex(window.interface.findData('virtual'))
        window.channel.setText('native-qt-test')
        window.connect_button.click(); wait(app,window)
        assert bus_manager.get_status()['connected']
        with can.Bus(interface='virtual',channel='native-qt-test') as receiver:
            window.signals.selectRow(1); window.send_selected.click(); wait(app,window)
            frame = receiver.recv(1)
            assert frame is not None and frame.data[2] & 7 == 4
            assert frame.data[0] == 0
        window.signals.cellWidget(1,0).click(); wait(app,window)
        window.favorites.setChecked(True); app.processEvents()
        assert window.signals.rowCount() == 1 and window.visible_signals[0]['name'] == 'CmdIgnSts'
        _, definition = workspace.sender.resolve_message('ENGINE_FD_8',dbc_id)
        traffic.on_frame(can.Message(arbitration_id=definition.frame_id,is_extended_id=False,
                                    data=definition.encode({'MAP_4_BAR':0,'CmdIgnSts':'RUN'})))
        window._verify()
        assert 'PASS' in window.note.text()
        second = workspace.create_program('HVAC')
        window.refresh_workspace(second)
        assert window.messages.rowCount() == 0  # New program has no favorites.
        window.programs.setCurrentIndex(window.programs.findData('default')); wait(app,window)
        assert window.messages.rowCount() == 1 and window.signals.rowCount() == 1
    finally:
        window.close(); app.processEvents()
