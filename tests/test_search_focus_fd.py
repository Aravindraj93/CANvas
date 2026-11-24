"""Search focus must survive the same refreshes that occur during real typing."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtWidgets import QApplication,QPushButton,QCheckBox
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from backend.desktop.app import CanvasWindow,DARK
from backend.can.signal_sender import SignalSender
from backend.can.bus_manager import bus_manager
from backend.dbc_workspace import DbcWorkspace
from backend.storage import WorkspaceStore
from test_programs_choices import engine_dbc
from test_desktop_responsiveness import finish


@pytest.fixture
def editor_ui(tmp_path):
    app=QApplication.instance() or QApplication([]);app.setStyleSheet(DARK)
    ws=DbcWorkspace(WorkspaceStore(tmp_path),SignalSender())
    ws.upload([('engine.dbc',engine_dbc())])
    window=CanvasWindow(ws);window.show();window.activateWindow();app.processEvents()
    yield app,window,ws
    window.close();app.processEvents()


def test_slow_real_typing_retains_search_focus_across_every_refresh(editor_ui):
    app,window,ws=editor_ui
    QTest.mouseClick(window.search,Qt.MouseButton.LeftButton)
    for letter in 'MAP_4_BAR':
        assert app.focusWidget() is window.search
        QTest.keyClicks(app.focusWidget(),letter)
        QTest.qWait(190)
        assert app.focusWidget() is window.search
    assert window.search.text()=='MAP_4_BAR'
    assert len(window.visible_signals)==1 and window.visible_signals[0]['name']=='MAP_4_BAR'


def test_search_caret_selection_zero_results_and_backspace_survive_refresh(editor_ui):
    app,window,ws=editor_ui
    window.search.setText('MAP_4');window.search.setFocus();window.search.setCursorPosition(3)
    window._apply_filter()
    assert window.search.hasFocus() and window.search.cursorPosition()==3
    window.search.setSelection(4,-4);window._fill_messages()
    assert window.search.hasFocus() and window.search.selectedText()=='MAP_' and window.search.cursorPosition()==0
    window.search.selectAll();QTest.keyClicks(app.focusWidget(),'no-matches');QTest.qWait(190)
    assert window.search.hasFocus() and window.messages.rowCount()==0
    window.search.selectAll();QTest.keyClicks(app.focusWidget(),'MAP_4');QTest.qWait(190)
    QTest.keyClick(app.focusWidget(),Qt.Key.Key_Backspace);QTest.qWait(190)
    assert window.search.hasFocus() and window.search.text()=='MAP_'


def test_favorites_filter_is_a_visible_checkable_button(editor_ui):
    app,window,ws=editor_ui
    assert isinstance(window.favorites,QPushButton) and window.favorites.isCheckable()
    assert window.favorites.objectName()=='favoriteFilter'
    QTest.mouseClick(window.favorites,Qt.MouseButton.LeftButton);app.processEvents()
    assert window.favorites.isChecked() and window.messages.rowCount()==0
    QTest.mouseClick(window.favorites,Qt.MouseButton.LeftButton);app.processEvents()
    assert not window.favorites.isChecked() and window.messages.rowCount()==1
    assert isinstance(window.messages.cellWidget(0,0),QPushButton)
    assert isinstance(window.signals.cellWidget(0,0),QPushButton)


def test_fd_checkbox_is_top_level_checked_default_without_auto_connect(editor_ui):
    app,window,ws=editor_ui
    assert isinstance(window.fd,QCheckBox) and window.fd.isChecked() and window.fd.isEnabled()
    window.connection_toggle.setChecked(False);app.processEvents()
    assert window.fd.isVisible() and not bus_manager.get_status()['connected']
    QTest.mouseClick(window.fd,Qt.MouseButton.LeftButton);app.processEvents()
    assert not window.fd.isChecked() and window.connection_panel.isVisible()
    assert not bus_manager.get_status()['connected']
    window.interface.setCurrentIndex(window.interface.findData('virtual'));window.channel.setText('remember-fd-off')
    window.apply_connection.click();finish(app,window)
    assert not bus_manager.get_status()['fd']
    window.close();app.processEvents()
    restored=CanvasWindow(ws);restored.show();app.processEvents()
    try:
        assert not restored.fd.isChecked() and not bus_manager.get_status()['connected']
    finally:restored.close();app.processEvents()


def test_old_saved_fd_off_settings_migrate_to_enabled_default(tmp_path):
    app=QApplication.instance() or QApplication([])
    store=WorkspaceStore(tmp_path);store.save_connection_settings({'bus_type':'virtual','fd':False,'channel':'old-profile'})
    ws=DbcWorkspace(store,SignalSender());window=CanvasWindow(ws);window.show();app.processEvents()
    try:
        assert window.fd.isChecked() and window.channel.text()=='old-profile'
        assert not bus_manager.get_status()['connected']
    finally:window.close();app.processEvents()


@pytest.mark.parametrize('query,expected,fuzzy',[
    ('map 4 bar','MAP_4_BAR',False),
    ('MAP-4-BAR','MAP_4_BAR',False),
    ('mpa4bar','MAP_4_BAR',True),
    ('cmd ign sts','CmdIgnSts',False),
    ('cmdignstz','CmdIgnSts',True),
    ('engin fd 8',None,True),
    ('0X 410',None,False),
])
def test_tolerant_search_matches_names_and_limits_visible_signals(editor_ui,query,expected,fuzzy):
    app,window,ws=editor_ui
    window.search.setText(query);window.search.setFocus();window._apply_filter()
    assert window.messages.rowCount()==1
    assert window.search.hasFocus()
    if expected:
        assert expected in [s['name'] for s in window.visible_signals]
    else:
        assert len(window.visible_signals)==2
    assert ('approximate matches' in window.message_count.text()) == fuzzy


def test_fuzzy_search_respects_program_favorites(editor_ui):
    app,window,ws=editor_ui
    msg=window.selected
    ws.favorite(msg['dbc_id'],msg['name'],'CmdIgnSts',True)
    window.refresh_workspace(ws.state());window.favorites.setChecked(True)
    window.search.setText('mpa4bar');window._apply_filter()
    assert window.messages.rowCount()==0
    window.search.setText('cmdignstz');window._apply_filter()
    assert window.messages.rowCount()==1
    assert [s['name'] for s in window.visible_signals]==['CmdIgnSts']


def test_fuzzy_results_put_closest_spelling_first(editor_ui):
    from test_workspace_status import dbc
    app,window,ws=editor_ui
    state=ws.upload([('long.dbc',dbc(100,'Long','PitchAngles')),('best.dbc',dbc(101,'Best','PitchAngle'))])
    window.refresh_workspace(state);window.search.setText('pithangle');window._apply_filter()
    assert window.displayed[0]['name']=='Best'
    assert window.visible_signals[0]['name']=='PitchAngle'
