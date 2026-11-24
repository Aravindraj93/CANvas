"""Real desktop events, shared DBC identifiers and recoverable hardware configuration."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from unittest.mock import MagicMock
import can
import pytest
pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox
from backend.can.bus_manager import bus_manager, BusManager
from backend.can.signal_sender import SignalSender
from backend.dbc_workspace import DbcWorkspace
from backend.desktop.app import CanvasWindow, DARK
from backend.storage import WorkspaceStore
from test_desktop_responsiveness import finish
from test_programs_choices import engine_dbc
from test_workspace_status import dbc


@pytest.fixture
def studio(tmp_path):
    app=QApplication.instance() or QApplication([]); app.setStyleSheet(DARK)
    workspace=DbcWorkspace(WorkspaceStore(tmp_path), SignalSender())
    workspace.upload([('engine.dbc',engine_dbc())])
    window=CanvasWindow(workspace); window.show(); app.processEvents()
    yield app, window, workspace
    window.close(); app.processEvents()


def select_popup(app, combo, raw_physical):
    index=combo.findData(raw_physical)
    assert index >= 0
    combo.showPopup(); app.processEvents()
    view=combo.view(); model_index=combo.model().index(index,0)
    view.scrollTo(model_index); app.processEvents()
    QTest.mouseClick(view.viewport(),Qt.MouseButton.LeftButton,pos=view.visualRect(model_index).center())
    app.processEvents()


def test_real_child_typing_enter_and_popup_repeat_after_favorite(studio):
    app, window, ws=studio
    bus_manager.connect('virtual','actual-gestures')
    # Click an actual bordered favorite button; then use newly rendered editors.
    button=window.signals.cellWidget(0,0)
    assert button.text() == '☆ Add' and button.isCheckable()
    QTest.mouseClick(button,Qt.MouseButton.LeftButton); finish(app,window)
    assert window.signals.cellWidget(0,0).text() == '★ Saved'
    editor=window.editors['MAP_4_BAR']
    combo=window.signals.cellWidget(1,2).findChild(QComboBox)
    with can.Bus(interface='virtual',channel='actual-gestures') as receiver:
        for value in range(10,20):
            QTest.mouseClick(editor.lineEdit(),Qt.MouseButton.LeftButton)
            editor.lineEdit().selectAll(); QTest.keyClicks(editor.lineEdit(),str(value))
            QTest.keyClick(editor.lineEdit(),Qt.Key.Key_Return)
        finish(app,window)
        frames=[receiver.recv(.5) for _ in range(10)]
        assert all(frame is not None for frame in frames)
        decoded=[ws.sender._db.decode_message(f.arbitration_id,f.data,decode_choices=False)['MAP_4_BAR'] for f in frames]
        assert decoded == list(range(10,20))
        assert receiver.recv(.02) is None
        for value in [4,2,4,4,2,4]:
            select_popup(app,combo,value); finish(app,window)
            frame=receiver.recv(.5)
            assert frame is not None and frame.data[2] & 7 == value
        assert receiver.recv(.02) is None
    report=window._diagnostic_report()
    assert len(report['recent_requests']) == 16
    assert all(row['status']=='TX accepted' for row in report['recent_requests'])
    assert report['traffic']['last_tx_hex']
    assert 'TX accepted #' in window.signals.item(1,7).text()
    json.dumps(report)


def test_shared_id_encoding_and_monitor_require_explicit_source(tmp_path):
    ws=DbcWorkspace(WorkspaceStore(tmp_path),SignalSender())
    content_a=dbc(0x5B0,'Shared','Value')
    content_b=content_a.replace(b'(1,0)',b'(2,0)')
    state=ws.upload([('PMASAH.dbc',content_a),('PDT7.dbc',content_b)])
    a,b=state['uploaded_ids']
    assert all(f['active'] for f in state['files']) and len(state['messages'])==2
    try:
        bus_manager.connect('virtual','shared-frame')
        with can.Bus(interface='virtual',channel='shared-frame') as receiver:
            with pytest.raises(ValueError,match='multiple DBCs'):
                ws.sender.send_signal('Shared','Value',20)
            assert ws.sender.send_signal('Shared','Value',20,a)
            assert receiver.recv(.5).data[0]==20
            assert ws.sender.send_signal('Shared','Value',20,b)
            frame=receiver.recv(.5)
            assert frame.data[0]==10
            assert ws.sender.decode_frame(frame)['ambiguous']
            assert ws.sender.decode_frame(frame,a)['decoded']['Value']==10
            assert ws.sender.decode_frame(frame,b)['decoded']['Value']==20
            ws.sender.start_cyclic('Shared',{'Value':20},50,a)
            with pytest.raises(ValueError,match='already cyclic'):
                ws.sender.start_cyclic('Shared',{'Value':20},50,b)
            with pytest.raises(ValueError,match='already cyclic'):
                ws.sender.send_signal('Shared','Value',30,b)
            ws.sender.stop_all_cyclic()
            assert ws.sender.send_signal('Shared','Value',30,b)
    finally:
        ws.sender.stop_all_cyclic();bus_manager.disconnect()


def test_multiple_files_can_be_checked_and_favorited_in_ui(studio):
    app,window,ws=studio
    state=ws.upload([('one.dbc',dbc(0x5B0,'One')),('two.dbc',dbc(0x5B0,'Two'))])
    window.refresh_workspace(state); app.processEvents()
    assert window.files.count()==3
    for i in range(3): window.files.item(i).setCheckState(Qt.CheckState.Unchecked); finish(app,window)
    for i in range(3): window.files.item(i).setCheckState(Qt.CheckState.Checked); finish(app,window)
    assert all(f['active'] for f in ws.state()['files']) and window.messages.rowCount()==3
    button=window.messages.cellWidget(1,0)
    assert button.text()=='☆ Add'
    QTest.mouseClick(button,Qt.MouseButton.LeftButton); finish(app,window)
    assert window.messages.cellWidget(1,0).isChecked()
    assert window.shared_hint.isVisible()
    window.files.clearSelection()
    for i in (1,2): window.files.item(i).setSelected(True)
    window._use_selected_dbcs(); finish(app,window)
    assert sum(f['active'] for f in ws.state()['files'])==2
    assert window.messages.rowCount()==2
    window._enable_all_dbcs(); finish(app,window)
    assert all(f['active'] for f in ws.state()['files'])


def test_fd_configuration_is_top_level_and_persisted(studio):
    app,window,ws=studio
    assert window.fd.isVisible() and window.fd.isChecked()
    window.interface.setCurrentIndex(window.interface.findData('virtual')); window.channel.setText('persist-fd')
    window.bitrate.setValue(250000); window.data_bitrate.setValue(1000000); window.brs.setChecked(True)
    window.apply_connection.click(); finish(app,window)
    assert bus_manager.get_status()['fd'] and bus_manager.get_status()['bitrate_switch']
    assert window.fd.isVisible() and not window.connection_panel.isVisible()
    window.close(); app.processEvents()
    restored=CanvasWindow(ws); restored.show(); app.processEvents()
    try:
        assert restored.fd.isChecked() and restored.brs.isChecked()
        assert restored.channel.text()=='persist-fd'
        assert restored.bitrate.value()==250000 and restored.data_bitrate.value()==1000000
        assert not bus_manager.get_status()['connected']  # Never reconnect on startup.
    finally: restored.close(); app.processEvents()


def test_neovi_can_preserve_bitrate_settings_and_report_reader_failure(monkeypatch):
    fake=MagicMock(); factory=MagicMock(return_value=fake)
    notifier=MagicMock(); notifier.exception=None
    monkeypatch.setattr(can,'Bus',factory)
    monkeypatch.setattr(can,'Notifier',MagicMock(return_value=notifier))
    manager=BusManager()
    try:
        assert manager.connect('neovi','HSCAN',fd=True,configure_bitrates=False).connected
        kwargs=factory.call_args.kwargs
        assert kwargs['fd'] and kwargs['ignore_config']
        assert 'bitrate' not in kwargs and 'data_bitrate' not in kwargs
        notifier.exception=RuntimeError('reader stopped')
        assert manager.get_status()['reader_error']=='reader stopped'
    finally: manager.disconnect()


def test_failed_fd_apply_keeps_error_and_saved_working_settings(studio, monkeypatch):
    app,window,ws=studio
    window.interface.setCurrentIndex(window.interface.findData('virtual'));window.channel.setText('last-good')
    window.apply_connection.click();finish(app,window)
    saved=ws.store.connection_settings()
    monkeypatch.setattr(can,'Bus',MagicMock(side_effect=RuntimeError('FD configuration rejected by adapter')))
    window.fd.setChecked(False);window.fd.click();window.apply_connection.click();finish(app,window)
    assert not bus_manager.get_status()['connected']
    assert 'FD configuration rejected' in window.note.text()
    assert ws.store.connection_settings()==saved


def test_neovi_receipt_thread_is_not_blocked_by_ws_decoder(monkeypatch):
    import threading
    from pathlib import Path
    from backend.api import ws
    from backend.can.signal_sender import signal_sender
    queued=[]
    loop=MagicMock();loop.is_running.return_value=True
    loop.call_soon_threadsafe.side_effect=lambda callback: queued.append(callback)
    monkeypatch.setattr(ws,'_broadcast_loop',loop)
    monkeypatch.setattr(ws,'_connections',{object()})
    receipt=threading.Event();threads=[]
    frame=can.Message(arbitration_id=0x41B,is_extended_id=False,data=bytes(8))
    def transmit(msg, timeout):
        def receive():
            ws._on_can_message(frame)
            receipt.set()
        thread=threading.Thread(target=receive,daemon=True);threads.append(thread);thread.start()
        if not receipt.wait(.2): raise can.CanTimeoutError('Receive callback blocked the receipt thread')
    fake=MagicMock();fake.send.side_effect=transmit
    monkeypatch.setattr(can,'Bus',MagicMock(return_value=fake))
    monkeypatch.setattr(can,'Notifier',MagicMock())
    signal_sender.load_dbc(str(Path(__file__).parent/'fixtures'/'sample.dbc'))
    try:
        bus_manager.connect('neovi','HSCAN')
        assert signal_sender.send_signal('Powertrain','VehicleSpeed',20)
        assert receipt.is_set() and len(queued)==1
    finally:
        signal_sender.unload();bus_manager.disconnect()
        for thread in threads: thread.join(1)
