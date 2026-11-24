"""Stop and cancel remain available while serialized work is running."""
import threading
import time
import pytest
pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtTest import QTest
from backend.can.bus_manager import bus_manager
from test_desktop_responsiveness import ui, finish


def test_cancel_yaml_keeps_global_controls_enabled(ui):
    app, window, workspace = ui
    window.yaml.setPlainText('name: Slow\nsteps: [{action: wait, ms: 10000}]')
    window._run_yaml(); app.processEvents()
    assert window._busy and window.centralWidget().isEnabled()
    assert window.cancel_test_button.isEnabled() and window.stop_tx_button.isEnabled()
    assert not window.tabs.isEnabled()
    window.cancel_test_button.click(); finish(app, window)
    assert 'CANCELLED' in window.test_result.toPlainText()
    assert not window.cancel_test_button.isEnabled() and window.tabs.isEnabled()


def test_stop_cancels_queued_sends_and_requires_explicit_resume(ui, monkeypatch):
    app, window, workspace = ui
    bus_manager.connect('virtual', 'desktop-stop')
    entered = threading.Event(); release = threading.Event()
    original = workspace.sender.send_message_signals
    def delayed(*args, **kwargs):
        entered.set(); release.wait(3)
        return original(*args, **kwargs)
    monkeypatch.setattr(workspace.sender, 'send_message_signals', delayed)
    window._submit_send(window.selected, {'MAP_4_BAR': 1})
    assert entered.wait(1)
    window._submit_send(window.selected, {'MAP_4_BAR': 2})
    start = time.monotonic(); window.stop_tx_button.click()
    assert time.monotonic() - start < .5
    assert workspace.sender.transmissions_paused()
    assert window.stop_tx_button.text() == 'Resume TX'
    release.set(); finish(app, window)
    assert window._recent_requests[-1]['status'] == 'Cancelled'
    assert workspace.sender.get_session_signals('default') == []
    window.stop_tx_button.click()
    assert not workspace.sender.transmissions_paused()
    window._submit_send(window.selected, {'MAP_4_BAR': 3}); finish(app, window)
    assert window._recent_requests[-1]['status'] == 'TX accepted'


def test_yaml_uses_workspace_sender_instead_of_global_singleton(ui):
    app, window, workspace = ui
    bus_manager.connect('virtual', 'desktop-yaml-sender')
    window.yaml.setPlainText('''name: Local workspace
steps:
  - action: send_signal
    message: ENGINE_FD_8
    signal: MAP_4_BAR
    value: 17
''')
    window._run_yaml(); finish(app, window)
    assert 'INCOMPLETE' in window.test_result.toPlainText()
    assert next(r['value'] for r in workspace.sender.get_session_signals('default') if r['signal'] == 'MAP_4_BAR') == 17


def test_close_during_blocked_send_keeps_event_loop_responsive(ui, monkeypatch):
    app, window, workspace = ui
    bus_manager.connect('virtual', 'close-during-send')
    entered = threading.Event(); release = threading.Event()
    original = workspace.sender.send_message_signals
    def blocked(*args, **kwargs):
        entered.set(); release.wait(3)
        return original(*args, **kwargs)
    monkeypatch.setattr(workspace.sender, 'send_message_signals', blocked)
    window._submit_send(window.selected, {'MAP_4_BAR': 1})
    assert entered.wait(1)
    started = time.monotonic(); window.close()
    assert time.monotonic() - started < .5
    assert window._closing and not window._shutdown_complete
    app.processEvents(); release.set()
    deadline = time.monotonic() + 5
    while not window._shutdown_complete and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert window._shutdown_complete and not window.isVisible()


