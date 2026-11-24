"""Responsive native CANvas signal studio; hardware work never blocks the UI."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from collections import deque
import json
import importlib.metadata
from html import escape
from pathlib import Path
import queue
import re
import sys
import threading
import time

from PySide6.QtCore import Qt, QTimer, QObject, Signal, QEvent, QLocale
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QCheckBox, QLineEdit, QSpinBox, QDoubleSpinBox,
    QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QTabWidget, QFileDialog, QInputDialog, QMessageBox, QPlainTextEdit,
    QAbstractItemView, QAbstractSpinBox, QFrame, QSizePolicy, QStyle, QStyleOptionButton,
    QStyledItemDelegate, QStyleOptionViewItem,
)

from backend.dbc_workspace import workspace as default_workspace
from backend.can.bus_manager import bus_manager
from backend.can.traffic import traffic
from backend.desktop.search import SearchQuery, normalize

DARK = '''
QWidget { background: #101720; color: #dbe5ee; font-family: "Segoe UI"; font-size: 13px; }
QMainWindow, QTabWidget::pane { background: #101720; border: 0; }
QLabel { background: transparent; }
QWidget#connectionPanel { background: transparent; }
QLabel#muted { color: #8fa3b5; }
QLabel#brand { color: #59dbb4; font-size: 24px; font-weight: 700; }
QLabel#heading { font-size: 16px; font-weight: 600; }
QFrame#card { background: #16212c; border: 1px solid #2c3b49; border-radius: 8px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
    background: #172430; border: 1px solid #364958; border-radius: 5px; padding: 5px; }
QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #59dbb4; }
QPushButton { background: #213443; border: 1px solid #3b5161; border-radius: 5px; padding: 6px 12px; }
QPushButton:hover { background: #2a4455; border-color: #68c8b0; }
QPushButton:disabled { color: #657b8b; border-color: #2a3945; }
QPushButton#primary { background: #24735e; border-color: #3c967d; color: white; }
QPushButton#favorite { color: #c9d9e5; background: #253b4b; border: 1px solid #5b7b90; padding: 4px; }
QPushButton#favorite:checked { color: #ffdc7a; background: #494126; border-color: #d5b350; }
QPushButton#favoriteFilter { background: #253b4b; border: 2px solid #68889e; font-weight: 600; }
QPushButton#favoriteFilter:checked { background: #285d49; border-color: #70dfb6; color: #dcfff0; }
QPushButton#libraryToggle:checked { background: #244759; border-color: #6c8b9d; }
QPushButton#sendSignal { padding: 6px 5px; }
QCheckBox#fdToggle { background: transparent; border: 0; padding: 4px 6px; spacing: 5px; }
QCheckBox#fdToggle::indicator { width: 14px; height: 14px; border: 1px solid #9db9c9; border-radius: 3px; background: #142530; }
QCheckBox#fdToggle::indicator:checked { background: #63dbaf; border-color: #9ae9cb; }
QHeaderView::section { background: #1c2b38; color: #9fb2c3; padding: 8px; border: 0; border-bottom: 1px solid #334755; }
QTableWidget, QListWidget { background: #131f2a; border: 1px solid #2d3f4e; border-radius: 5px;
    alternate-background-color: #172530; gridline-color: #253744; }
QTableWidget::item { padding: 5px; }
QTableWidget::item:selected, QListWidget::item:selected { background: #244759; color: #f3fbff; }
QTabBar::tab { background: transparent; color: #8fa5b7; padding: 12px 20px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #66dfba; border-bottom-color: #66dfba; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator { width: 16px; height: 16px; }
QSplitter::handle { background: #233543; }
QSplitter::handle:hover { background: #527489; }
'''


class SubtitleDelegate(QStyledItemDelegate):
    """Draw a second line while preserving the table's selection and focus style."""

    def __init__(self, parent, color):
        super().__init__(parent)
        self.color = QColor(color)

    def paint(self, painter, option, index):
        subtitle = index.data(Qt.ItemDataRole.UserRole)
        if not subtitle:
            super().paint(painter, option, index)
            return

        style_option = QStyleOptionViewItem(option)
        self.initStyleOption(style_option, index)
        title, style_option.text = style_option.text, ''
        widget = style_option.widget
        style = widget.style() if widget else QApplication.style()
        painter.save()
        painter.setClipRect(style_option.rect)
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, style_option, painter, widget)
        painter.setFont(style_option.font)
        metrics = style_option.fontMetrics
        width = max(0, style_option.rect.width() - 16)
        x = style_option.rect.left() + 8
        y = style_option.rect.center().y() - metrics.height() + metrics.ascent()
        selected = bool(style_option.state & QStyle.StateFlag.State_Selected)
        palette = style_option.palette
        painter.setPen(palette.highlightedText().color() if selected else palette.text().color())
        painter.drawText(x, y, metrics.elidedText(title, Qt.TextElideMode.ElideRight, width))
        painter.setPen(self.color)
        painter.drawText(x, y + metrics.height() + 2,
                         metrics.elidedText(subtitle, Qt.TextElideMode.ElideRight, width))
        painter.restore()


class SignalTable(QTableWidget):
    """Use spare width for notes and keep signal names readable in narrow panes."""

    def fit_signal_column(self):
        reserved = sum(self.columnWidth(column) for column in range(self.columnCount()) if column != 1)
        width = max(140, self.viewport().width() - reserved)
        if self.columnWidth(1) != width:
            self.setColumnWidth(1, width)

    def viewportEvent(self, event):
        result = super().viewportEvent(event)
        if event.type() == QEvent.Type.Resize:
            self.fit_signal_column()
        return result


class FdCheckBox(QCheckBox):
    """A high-contrast checkbox whose tick remains visible with dark Qt styles."""
    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.isChecked(): return
        option = QStyleOptionButton(); self.initStyleOption(option)
        rect = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor('#103b2c'), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        path = QPainterPath(); path.moveTo(rect.left() + rect.width() * .20, rect.top() + rect.height() * .50)
        path.lineTo(rect.left() + rect.width() * .42, rect.top() + rect.height() * .72)
        path.lineTo(rect.left() + rect.width() * .82, rect.top() + rect.height() * .22)
        painter.drawPath(path)


class CommitSpinBox(QDoubleSpinBox):
    """Typing is local; Enter or one step is one explicit transmission."""
    committed = Signal(float)
    rejected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setKeyboardTracking(False)
        self.setAccelerated(False)
        self.setLocale(QLocale.c())
        self.commit_source = 'enter'
        self.lineEdit().installEventFilter(self)
        self.lineEdit().setStyleSheet('background: transparent; border: 0; padding: 0;')

    def _commit_typed(self):
        if not self.hasAcceptableInput():
            self.rejected.emit(self.text())
            return
        self.interpretText()
        self.commit_source = 'enter'
        self.committed.emit(self.value())

    def eventFilter(self, watched, event):
        if watched is self.lineEdit() and event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.type() == QEvent.Type.KeyPress:
                    self._commit_typed()
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Some Qt styles collapse the internal editor when NoButtons is used
        # on a styled subclass. Keep the text field inside our own frame.
        self.lineEdit().setGeometry(7, 2, max(1, self.width() - 14), max(1, self.height() - 4))

    def stepBy(self, steps):
        before = self.value()
        super().stepBy(steps)
        if self.value() != before:
            self.commit_source = 'step'
            self.committed.emit(self.value())

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._commit_typed()
            event.accept()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        # Scrolling the table must not accidentally alter or transmit a value.
        event.ignore()


class Results(QObject):
    ready = Signal(object, object)
    sent = Signal(object, object)
    shutdown_ready = Signal()


def label(text, name='muted'):
    value = QLabel(text); value.setObjectName(name)
    return value


def table(headers, widths, widget_type=QTableWidget):
    value = widget_type(0, len(headers))
    value.setHorizontalHeaderLabels(headers)
    value.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    value.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    value.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    value.setAlternatingRowColors(True)
    value.setShowGrid(False)
    value.verticalHeader().hide()
    value.verticalHeader().setDefaultSectionSize(34)
    value.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    for col, width in enumerate(widths): value.setColumnWidth(col, width)
    value.horizontalHeader().setStretchLastSection(True)
    return value


class CanvasWindow(QMainWindow):
    PAGE_SIZE = 100
    SIGNAL_PAGE_SIZE = 80

    def __init__(self, workspace=None):
        super().__init__()
        self.workspace = workspace or default_workspace
        self.sender = self.workspace.sender
        self.state = self.workspace.state()
        self.selected = None
        self.values = {}; self.editors = {}; self.visible_signals = []; self.displayed = []
        self._cycle_periods = {}
        self._refreshing = False; self._busy = False; self._closing = False
        self._pending_sends = 0; self._monitor_visible = False; self._monitor_dropped = 0
        self._request_seq = 0; self._recent_requests = deque(maxlen=200); self._row_feedback = {}
        self._session_editors = {}; self._session_rows = []; self._session_signature = None
        self._session_seen_values = {}
        self._session_limit = self.SIGNAL_PAGE_SIZE
        self._test_cancel = None; self._send_generation = 0
        self._shutdown_complete = False
        self.limit = self.PAGE_SIZE; self.signal_limit = self.SIGNAL_PAGE_SIZE
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='canvas-ui')
        self.results = Results(); self.results.ready.connect(self._completed); self.results.sent.connect(self._sent)
        self.results.shutdown_ready.connect(self._finish_close)
        self.frames = queue.Queue(maxsize=500)
        self._frame_listener = self._queue_frame; bus_manager.add_listener(self._frame_listener)
        self.setWindowTitle('CANvas · Signal Studio')
        self.resize(1440, 900); self.setMinimumSize(1000, 700)
        root = QWidget(); self.setCentralWidget(root)
        layout = QVBoxLayout(root); layout.setContentsMargins(18, 12, 18, 10); layout.setSpacing(10)
        top = QHBoxLayout(); top.addWidget(label('CANvas', 'brand')); top.addWidget(label('SIGNAL STUDIO'))
        top.addStretch(); top.addWidget(label('Program'))
        self.programs = QComboBox(); self.programs.setMinimumWidth(200); self.programs.currentIndexChanged.connect(self._select_program)
        top.addWidget(self.programs)
        new = QPushButton('+ New program'); new.clicked.connect(self._new_program); top.addWidget(new); layout.addLayout(top)
        self.export_favorites_button = QPushButton('Export favorites')
        self.export_favorites_button.setToolTip('Save the selected program’s favorites and their signal notes as a shareable JSON file.')
        self.export_favorites_button.clicked.connect(self._export_favorites)
        top.addWidget(self.export_favorites_button)
        self.import_favorites_button = QPushButton('Import favorites')
        self.import_favorites_button.setToolTip('Merge a CANvas favorites file into the selected program.')
        self.import_favorites_button.clicked.connect(self._import_favorites)
        top.addWidget(self.import_favorites_button)
        self._build_connection(layout)
        self.tabs = QTabWidget(); layout.addWidget(self.tabs, 1)
        self._build_studio(); self._build_monitor(); self._build_tests(); self._build_session()
        self.tabs.currentChanged.connect(self._tab_changed)
        footer = QHBoxLayout()
        self.note = QLabel('Ready. Add DBC files, then connect to your bench.'); self.note.setWordWrap(True)
        footer.addWidget(self.note, 1)
        self.cyclic_label = label('')
        footer.addWidget(self.cyclic_label)
        self.cancel_test_button = QPushButton('Cancel test'); self.cancel_test_button.setEnabled(False)
        self.cancel_test_button.clicked.connect(self._cancel_test); footer.addWidget(self.cancel_test_button)
        self.stop_tx_button = QPushButton('Stop TX'); self.stop_tx_button.setCheckable(True)
        self.stop_tx_button.setToolTip('Pause all transmission, cancel the test and queued sends. An adapter call already in progress may finish. Resume never restarts cycles.')
        self.stop_tx_button.toggled.connect(self._stop_tx); footer.addWidget(self.stop_tx_button)
        self.stop_tx_button.setChecked(self.sender.transmissions_paused())
        self.queue_label = label(''); footer.addWidget(self.queue_label); layout.addLayout(footer)
        self.search_timer = QTimer(self); self.search_timer.setSingleShot(True); self.search_timer.setInterval(140)
        self.search_timer.timeout.connect(self._apply_filter)
        self.refresh_workspace(self.state)
        self.timer = QTimer(self); self.timer.timeout.connect(self.refresh_status); self.timer.start(500)

    def _set_note(self, text, error=False):
        self.note.setText(text); self.note.setStyleSheet('color: #ffad91;' if error else 'color: #aebfce;')

    def _run(self, action, callback=None):
        if self._busy or self._closing: return
        self._busy = True; self._set_operation_enabled(False); self._set_note('Working…')
        future = self.executor.submit(action)
        def done(f):
            try: self.results.ready.emit((callback, f.result()), None)
            except Exception as exc: self.results.ready.emit(None, str(exc))
        future.add_done_callback(done)

    def _set_operation_enabled(self, enabled):
        for widget in self.centralWidget().findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
            if widget not in (self.stop_tx_button, self.cancel_test_button): widget.setEnabled(enabled)
        self.cancel_test_button.setEnabled(self._test_cancel is not None)

    def _cancel_test(self):
        if self._test_cancel is not None:
            self._test_cancel.set()
            self._set_note('Cancellation requested. An adapter call already in progress may finish.')

    def _stop_tx(self, paused):
        self.stop_tx_button.setText('Resume TX' if paused else 'Stop TX')
        if paused:
            self._send_generation += 1; self._cancel_test(); self.sender.pause_transmissions()
            # Do not wait on adapter locks in the GUI thread.
            self.executor.submit(self.sender.stop_all_cyclic)
            self._set_note('TX paused. Queued sends cancelled; cyclic streams stopping. An in-progress driver call may finish.')
        else:
            self.sender.resume_transmissions()
            self._set_note('TX enabled. Cyclic streams and cancelled tests are not restarted.')

    def _completed(self, payload, error):
        self._busy = False
        if self._closing: return
        self._test_cancel = None; self._set_operation_enabled(True)
        if error:
            self.refresh_workspace(self.workspace.state())
            self._set_note(error, True)
        else:
            self._set_note('Ready')
            callback, result = payload
            if callback: callback(result)
        self.refresh_status()

    def _submit_send(self, msg, values, source='button'):
        if self._closing: return
        self._request_seq += 1
        entry = dict(request_id=self._request_seq, message_key=msg['key'], message=msg['name'],
                     dbc_id=msg['dbc_id'], dbc_filename=msg.get('dbc_filename'), can_id=msg['arbitration_id_hex'],
                     values=dict(values), source=source, status='Queued', requested_at=datetime.now().astimezone().isoformat())
        self._recent_requests.append(entry)
        for name in values: self._row_feedback[(msg['key'], name)] = entry
        status = bus_manager.get_status()
        reason = None
        if self.sender.transmissions_paused(): reason = 'TX is paused. Click Resume TX before sending.'
        elif self._busy: reason = 'Workspace operation is in progress. Retry when it finishes.'
        elif not status['connected']: reason = 'Connect to the bench before sending.'
        elif status.get('reader_error'): reason = 'Adapter receiver stopped: ' + status['reader_error'] + '. Reconnect the adapter.'
        elif msg['is_fd'] and not status['fd']: reason = 'Message requires CAN FD. Check CAN FD beside Connect, then Apply & reconnect.'
        elif self._pending_sends >= 200: reason = 'Send queue is full. Wait for the adapter.'
        if reason:
            entry.update(status='Blocked', error=reason); self._refresh_feedback(); self._set_note(reason, True)
            self._update_fd_hint(status); return
        self._pending_sends += 1; self.queue_label.setText(f'{self._pending_sends} sending')
        self._refresh_feedback()
        generation = self._send_generation
        def send():
            if generation != self._send_generation:
                entry['cancelled'] = True
                raise RuntimeError('Queued transmission cancelled by Stop TX')
            if not self.sender.send_message_signals(entry['message'], entry['values'], entry['dbc_id'],
                                                    request_id=entry['request_id']):
                raise RuntimeError(bus_manager.get_status()['last_tx_error'] or 'CAN send failed')
            return entry
        future = self.executor.submit(send)
        def done(f):
            try: self.results.sent.emit(f.result(), None)
            except Exception as exc: self.results.sent.emit(entry, str(exc))
        future.add_done_callback(done)

    def _sent(self, entry, error):
        self._pending_sends = max(0, self._pending_sends - 1)
        entry.update(status='Error' if error else 'TX accepted', completed_at=datetime.now().astimezone().isoformat())
        if entry.get('cancelled'): entry['status'] = 'Cancelled'
        if error: entry['error'] = error
        if self._closing: return
        self.queue_label.setText(f'{self._pending_sends} sending' if self._pending_sends else '')
        values = ', '.join(f'{k} = {v:g}' for k, v in entry['values'].items())
        self._set_note(error or f"TX accepted #{entry['request_id']} · {entry['message']} · {values}", bool(error))
        self._refresh_feedback()
        self.refresh_status()

    def _reject_numeric(self, msg, sig, text):
        self._request_seq += 1
        reason = f"{sig['name']}: '{text}' is outside the editor range or incomplete. Nothing sent."
        entry = dict(request_id=self._request_seq, message_key=msg['key'], message=msg['name'],
                     dbc_id=msg['dbc_id'], values={sig['name']: text}, source='enter', status='Blocked', error=reason,
                     requested_at=datetime.now().astimezone().isoformat())
        self._recent_requests.append(entry); self._row_feedback[(msg['key'], sig['name'])] = entry
        self._refresh_feedback(); self._set_note(reason, True)

    def _refresh_feedback(self):
        if not self.selected: return
        for row, sig in enumerate(self.visible_signals):
            item = self.signals.item(row, 7)
            if item is None: continue
            entry = self._row_feedback.get((self.selected['key'], sig['name']))
            if not entry: item.setText('Not sent'); continue
            item.setText(f"{entry['status']} #{entry['request_id']}")
            item.setToolTip(entry.get('error') or f"{sig['name']} = {entry['values'][sig['name']]:g} · {entry['source']}")
            item.setForeground(QColor('#ffb092' if entry['status'] in ('Error', 'Blocked') else '#72dfbb'))

    def _diagnostic_report(self):
        versions = {}
        for name in ('python-can', 'python-ics', 'cantools', 'PySide6-Essentials'):
            try: versions[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError: versions[name] = 'not installed'
        selected = self.selected
        evidence = traffic.view(self._definitions[selected['key']], bus_manager.get_status()['connected']) if selected else None
        workspace = dict(active_program_id=self.state['active_program_id'], programs=self.state['programs'],
                         files=self.state['files'], message_count=len(self.state['messages']),
                         restore_error=self.state.get('restore_error'), restore_errors=self.state.get('restore_errors', []),
                         search=self.search.text(), favorites_only=self.favorites.isChecked(),
                         matching_message_count=len(self.displayed))
        return dict(version='0.4.6', captured_at=datetime.now().astimezone().isoformat(), platform=sys.platform,
                    packages=versions, bus=bus_manager.get_status(), selected_message=selected,
                    workspace=workspace, traffic=evidence, recent_requests=list(self._recent_requests),
                    recent_tx_frames=traffic.recent_transmissions(), active_cyclic=self.sender.get_cyclic_messages(),
                    cyclic_errors=self.sender.get_cyclic_errors(),
                    session_signals=self.sender.get_session_signals(self.state['active_program_id']))

    def _save_diagnostics(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save bench diagnostics', 'CANvas-diagnostics.json', 'JSON (*.json)')
        if path:
            try:
                Path(path).write_text(json.dumps(self._diagnostic_report(), indent=2), encoding='utf-8')
                self._set_note('Saved diagnostics: ' + path)
            except OSError as exc: self._set_note(str(exc), True)

    def _build_connection(self, layout):
        card = QFrame(); card.setObjectName('card'); box = QVBoxLayout(card)
        summary = QHBoxLayout()
        self.bus_label = QLabel('● Disconnected'); summary.addWidget(self.bus_label, 1)
        self.bus_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.connection_toggle = QPushButton('Connection settings'); self.connection_toggle.setCheckable(True)
        self.connection_toggle.setChecked(True); summary.addWidget(self.connection_toggle)
        self.fd = FdCheckBox('CAN FD'); self.fd.setObjectName('fdToggle'); self.fd.setChecked(True)
        self.fd.setToolTip('Checked by default. Changes take effect with Apply & connect / reconnect. BRS and data bitrate must match the bench.')
        self.fd.clicked.connect(self._fd_clicked); summary.addWidget(self.fd, 0, Qt.AlignmentFlag.AlignVCenter)
        self.connect_button = QPushButton('Connect'); self.connect_button.setObjectName('primary')
        self.connect_button.clicked.connect(self._toggle_connection); summary.addWidget(self.connect_button); box.addLayout(summary)
        diagnostics = QPushButton('Save diagnostics'); diagnostics.clicked.connect(self._save_diagnostics); summary.addWidget(diagnostics)
        self.connection_panel = QWidget(); self.connection_panel.setObjectName('connectionPanel')
        grid = QGridLayout(self.connection_panel); grid.setContentsMargins(0, 6, 0, 2)
        self.interface = QComboBox(); self.interface.addItem('Intrepid ValueCAN / neoVI', 'neovi'); self.interface.addItem('Virtual simulation', 'virtual')
        self.channel = QLineEdit('HSCAN'); self.channel.setPlaceholderText('ICS network')
        self.bitrate = QSpinBox(); self.bitrate.setRange(1000, 1000000); self.bitrate.setValue(500000)
        self.data_bitrate = QSpinBox(); self.data_bitrate.setRange(1000, 20000000); self.data_bitrate.setValue(2000000)
        self.brs = QCheckBox('BRS')
        self.serial = QLineEdit(); self.serial.setPlaceholderText('Optional')
        fields = [('Interface', self.interface), ('Network / channel', self.channel), ('Nominal bit/s', self.bitrate),
                  ('FD data bit/s', self.data_bitrate), ('Bitrate switch', self.brs), ('Device serial', self.serial)]
        for col, (title, widget) in enumerate(fields):
            grid.addWidget(label(title), 0, col); grid.addWidget(widget, 1, col)
        self.keep_bitrates = QCheckBox("Use adapter's saved bitrates (ValueCAN)")
        self.keep_bitrates.setToolTip('Skip nominal/data bitrate writes. Configure the adapter first in neoVI Explorer; CAN FD and BRS frame flags still follow these controls.')
        grid.addWidget(self.keep_bitrates, 2, 0, 1, 4)
        self.apply_connection = QPushButton('Apply & connect'); self.apply_connection.setObjectName('primary')
        self.apply_connection.clicked.connect(self._apply_connection); grid.addWidget(self.apply_connection, 2, 4, 1, 2)
        grid.addWidget(label('Settings take effect when you click Apply & connect / reconnect.'), 3, 0, 1, 6)
        box.addWidget(self.connection_panel); layout.addWidget(card)
        self.connection_toggle.toggled.connect(self.connection_panel.setVisible)
        self.fd.toggled.connect(self._connection_fields)
        self.keep_bitrates.toggled.connect(self._connection_fields)
        self.interface.currentIndexChanged.connect(self._connection_fields)
        connected = bus_manager.get_status()['connected']
        saved = bus_manager.get_status() if connected else self.workspace.store.connection_settings()
        self.interface.setCurrentIndex(max(0, self.interface.findData(saved.get('bus_type', 'neovi'))))
        self.channel.setText(saved.get('channel') or 'HSCAN'); self.bitrate.setValue(saved.get('bitrate') or 500000)
        self.fd.setChecked(saved.get('fd', True) if connected or saved.get('fd_default_v1') else True)
        self.data_bitrate.setValue(saved.get('data_bitrate') or 2000000)
        self.brs.setChecked(saved.get('bitrate_switch', False)); self.serial.setText(saved.get('serial') or '')
        self.keep_bitrates.setChecked(not saved.get('configure_bitrates', True))
        self._connection_fields()

    def _connection_fields(self):
        use_saved = self.keep_bitrates.isChecked() and self.interface.currentData() == 'neovi'
        self.keep_bitrates.setEnabled(self.interface.currentData() == 'neovi')
        self.bitrate.setEnabled(not use_saved)
        self.data_bitrate.setEnabled(not use_saved and self.fd.isChecked())
        self.brs.setEnabled(self.fd.isChecked())
        self.apply_connection.setText('Apply & reconnect' if bus_manager.get_status()['connected'] else 'Apply & connect')

    def _toggle_connection(self):
        if bus_manager.get_status()['connected']:
            def disconnect(): self.sender.stop_all_cyclic(); bus_manager.disconnect()
            self._run(disconnect, lambda _: self.connection_toggle.setChecked(True)); return
        self._apply_connection()

    def _apply_connection(self):
        options = dict(bus_type=self.interface.currentData(), channel=self.channel.text().strip() or None,
                       bitrate=self.bitrate.value(), fd=self.fd.isChecked(),
                       data_bitrate=self.data_bitrate.value() if self.fd.isChecked() else None,
                       bitrate_switch=self.fd.isChecked() and self.brs.isChecked(), serial=self.serial.text().strip() or None,
                       configure_bitrates=not (self.keep_bitrates.isChecked() and self.interface.currentData() == 'neovi'))
        def connect():
            self.sender.stop_all_cyclic()
            status = bus_manager.connect(**options)
            if not status.connected: raise RuntimeError(status.error)
            self.workspace.store.save_connection_settings({**options, 'fd_default_v1': True})
        self._run(connect, lambda _: self.connection_toggle.setChecked(False))

    def _fd_clicked(self, checked):
        self.connection_toggle.setChecked(True); self._connection_fields()
        self._set_note(('CAN FD enabled in settings. ' if checked else 'Classical CAN selected in settings. ')
                       + 'Check the bench bitrates and click ' + self.apply_connection.text() + ' to apply.')

    def _build_studio(self):
        page = QWidget(); row = QHBoxLayout(page); row.setContentsMargins(0, 10, 0, 0); row.setSpacing(14)
        sidebar = QWidget(); side = QVBoxLayout(sidebar); side.setContentsMargins(0, 0, 0, 0)
        side.addWidget(label('DBC Library', 'heading'))
        add = QPushButton('+ Add DBC files'); add.clicked.connect(self._add_dbcs); side.addWidget(add)
        self.files = QListWidget(); self.files.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.files.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.files.itemChanged.connect(self._activate_files); side.addWidget(self.files, 1)
        self.file_count = label(''); side.addWidget(self.file_count)
        file_actions = QHBoxLayout()
        enable_all = QPushButton('Enable all'); enable_all.clicked.connect(self._enable_all_dbcs)
        use_selected = QPushButton('Use selected'); use_selected.clicked.connect(self._use_selected_dbcs)
        file_actions.addWidget(enable_all); file_actions.addWidget(use_selected); side.addLayout(file_actions)
        self.reload_dbcs = QPushButton('Reload DBCs')
        self.reload_dbcs.setToolTip('Retry the enabled DBCs from saved data. Stops cyclic sending; does not reconnect the adapter.')
        self.reload_dbcs.clicked.connect(lambda: self._run(self.workspace.reload, self.refresh_workspace))
        side.addWidget(self.reload_dbcs)
        remove = QPushButton('Remove selected'); remove.clicked.connect(self._delete_dbc); side.addWidget(remove)
        tip = label('Ctrl / Shift selects multiple files.\nUse selected activates those files.\nFiles and favorites save automatically.'); tip.setWordWrap(True); side.addWidget(tip)
        main = QWidget(); main_layout = QVBoxLayout(main); main_layout.setContentsMargins(0, 0, 0, 0); main_layout.setSpacing(8)
        filters = QHBoxLayout()
        self.show_library = QPushButton('DBC Library')
        self.show_library.setObjectName('libraryToggle')
        self.show_library.setCheckable(True)
        self.show_library.setChecked(True)
        self.show_library.setToolTip('Show or hide the DBC Library to make room for the tables.')
        self.show_library.toggled.connect(sidebar.setVisible)
        filters.addWidget(self.show_library)
        self.search = QLineEdit(); self.search.setPlaceholderText('Search signal, message or CAN ID — spaces and small typos are OK'); self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter_changed)
        self.favorites = QPushButton('☆ Favorites only'); self.favorites.setObjectName('favoriteFilter')
        self.favorites.setCheckable(True); self.favorites.setAutoDefault(False)
        self.favorites.setAccessibleName('Show favorites only')
        self.favorites.setToolTip('Click to show this program’s favorite messages/signals. Click again to show all.')
        self.favorites.toggled.connect(lambda checked: self.favorites.setText('★ Favorites only' if checked else '☆ Favorites only'))
        self.favorites.toggled.connect(self._apply_filter)
        self.more = QPushButton('More messages'); self.more.clicked.connect(self._more)
        filters.addWidget(self.search, 1); filters.addWidget(self.favorites); filters.addWidget(self.more); main_layout.addLayout(filters)
        self.dbc_error = QLabel(); self.dbc_error.setWordWrap(True)
        self.dbc_error.setTextFormat(Qt.TextFormat.PlainText)
        self.dbc_error.setStyleSheet('color: #ffb092; background: #35251f; border: 1px solid #96624b; padding: 8px;')
        main_layout.addWidget(self.dbc_error)
        message_pane = QWidget()
        message_layout = QVBoxLayout(message_pane)
        message_layout.setContentsMargins(0, 0, 0, 0)
        message_header = QHBoxLayout()
        message_header.addWidget(label('Messages', 'heading'), 1)
        message_details = QCheckBox('Details')
        message_details.setToolTip('Show DBC, traffic status and TX / echo / RX counts in the message list.')
        message_header.addWidget(message_details)
        message_layout.addLayout(message_header)
        self.message_count = label('')
        self.message_count.setWordWrap(True)
        self.messages = table(['★', 'Message', 'DBC', 'ID / format', 'Status', 'TX / echo / RX'], [76, 160, 145, 94, 114, 105])
        self.messages.verticalHeader().setDefaultSectionSize(44)
        self.messages.setItemDelegateForColumn(1, SubtitleDelegate(self.messages, '#a8bdce'))
        self.messages.horizontalHeader().setStretchLastSection(False)
        self.messages.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.messages.itemSelectionChanged.connect(self._select_message)
        message_details.toggled.connect(self._show_message_details)
        self._show_message_details(False)
        message_layout.addWidget(self.messages, 1)
        message_layout.addWidget(self.message_count)
        detail = QWidget(); detail_layout = QVBoxLayout(detail); detail_layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout(); self.selected_title = label('Select a message', 'heading')
        self.selected_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        header.addWidget(self.selected_title, 1)
        self.signal_count = label(''); header.addWidget(self.signal_count)
        self.edit_signal_note = QPushButton('Signal note…')
        self.edit_signal_note.setToolTip('Select a signal row to add or edit its note for this program.')
        self.edit_signal_note.setEnabled(False)
        self.edit_signal_note.clicked.connect(self._edit_signal_note)
        header.addWidget(self.edit_signal_note)
        self.details = QCheckBox('Details'); self.details.toggled.connect(self._show_details); header.addWidget(self.details)
        self.more_signals = QPushButton('More signals'); self.more_signals.clicked.connect(self._more_signals); header.addWidget(self.more_signals)
        detail_layout.addLayout(header)
        fd_row = QHBoxLayout(); self.fd_hint = label(''); self.fd_hint.setWordWrap(True)
        self.fd_hint.setStyleSheet('color: #f0c879;')
        fd_row.addWidget(self.fd_hint, 1); detail_layout.addLayout(fd_row)
        self.shared_hint = label(''); self.shared_hint.setWordWrap(True); detail_layout.addWidget(self.shared_hint)
        self.signals = table(['★', 'Signal / note', 'Value', 'Raw', 'Latest RX', 'DBC range / notes', '', 'Last action'],
                             [76, 190, 244, 65, 85, 220, 58, 114], widget_type=SignalTable)
        self.signals.setItemDelegateForColumn(1, SubtitleDelegate(self.signals, '#89e2ce'))
        self.signals.itemSelectionChanged.connect(self._update_note_button)
        self.signals.horizontalHeader().setStretchLastSection(False)
        self.signals.horizontalHeader().moveSection(6, 3)
        self._show_details(False)
        detail_layout.addWidget(self.signals, 1)
        self.definition_note = label(''); self.definition_note.setStyleSheet('color: #f0c879;')
        self.definition_note.setWordWrap(True); detail_layout.addWidget(self.definition_note)
        detail_layout.addWidget(label('Enter sends the edited signal.  − / + and text-choice selections send immediately.'))
        actions = QHBoxLayout()
        self.send_selected = QPushButton('Send selected'); self.send_selected.clicked.connect(self._send_selected)
        self.send_all = QPushButton('Send visible'); self.send_all.clicked.connect(self._send_all)
        self.period = QSpinBox(); self.period.setRange(1, 600000); self.period.setValue(100); self.period.setSuffix(' ms'); self.period.setMaximumWidth(120)
        self.period.valueChanged.connect(self._remember_cycle_period)
        self.cyclic = QPushButton('Start cyclic'); self.cyclic.clicked.connect(self._toggle_cyclic)
        self.cyclic.setToolTip('Repeat the selected CAN message at the specified interval. Signal edits update the repeated payload.')
        stop = QPushButton('Stop all'); stop.clicked.connect(lambda: self._run(self.sender.stop_all_cyclic))
        for widget in [self.send_selected, self.send_all]: actions.addWidget(widget)
        actions.addStretch(); actions.addWidget(label('Cycle')); actions.addWidget(self.period); actions.addWidget(self.cyclic); actions.addWidget(stop)
        detail_layout.addLayout(actions)
        verify_row = QHBoxLayout()
        self.max_age = QSpinBox(); self.max_age.setRange(1, 600000); self.max_age.setValue(1000); self.max_age.setSuffix(' ms'); self.max_age.setMaximumWidth(125)
        verify = QPushButton('Verify latest RX'); verify.clicked.connect(self._verify)
        verify.setToolTip('Compare visible expected values with the latest fresh received CAN frame. TX echo does not count as RX; this does not verify the HMI screen.')
        verify_row.addWidget(verify); verify_row.addWidget(label('Max age')); verify_row.addWidget(self.max_age)
        verify_row.addStretch(); detail_layout.addLayout(verify_row)
        self.studio_split = QSplitter(Qt.Orientation.Horizontal)
        self.studio_split.setHandleWidth(7)
        self.studio_split.setChildrenCollapsible(False)
        self.studio_split.addWidget(message_pane)
        self.studio_split.addWidget(detail)
        message_pane.setMinimumWidth(205)
        self.studio_split.setSizes([265, 930])
        self.studio_split.setStretchFactor(1, 1)
        main_layout.addWidget(self.studio_split, 1)
        outer = QSplitter(); outer.addWidget(sidebar); outer.addWidget(main); outer.setSizes([215, 1240]); outer.setStretchFactor(1, 1)
        outer.setChildrenCollapsible(False)
        row.addWidget(outer); self.tabs.addTab(page, 'Signal Studio')

    def _build_monitor(self):
        page = QWidget(); layout = QVBoxLayout(page)
        self.monitor_page = page
        row = QHBoxLayout(); self.monitor_filter = QLineEdit(); self.monitor_filter.setPlaceholderText('Filter CAN ID or message name')
        self.paused = QCheckBox('Pause')
        clear = QPushButton('Clear'); clear.clicked.connect(lambda: self.monitor.setRowCount(0))
        self.monitor_source = QComboBox(); self.monitor_source.addItem('Auto DBC (flag shared IDs)', None)
        row.addWidget(self.monitor_filter, 1); row.addWidget(self.monitor_source); row.addWidget(self.paused); row.addWidget(clear); layout.addLayout(row)
        self.monitor = table(['Time', 'Direction', 'CAN ID', 'Format', 'Message', 'Data', 'Decoded signals'], [110, 75, 85, 85, 170, 250, 300])
        layout.addWidget(self.monitor); self.monitor_note = label('Monitor captures while this tab is open.'); layout.addWidget(self.monitor_note)
        self.tabs.addTab(page, 'Bus Monitor')
        self.tabs.setTabToolTip(self.tabs.count()-1, 'RX = received frames. TX echo = the adapter’s transmitted-frame copy. Neither alone proves HMI display behavior.')

    def _build_tests(self):
        page = QWidget(); layout = QVBoxLayout(page); row = QHBoxLayout()
        load = QPushButton('Open YAML'); load.clicked.connect(self._load_yaml)
        run = QPushButton('Run test'); run.clicked.connect(self._run_yaml)
        row.addWidget(load); row.addWidget(run); row.addStretch(); layout.addLayout(row)
        self.yaml = QPlainTextEdit('name: "Bench check"\nsteps:\n  - action: log\n    message: "Add send / assert_signal steps for your DBC"\n')
        self.test_result = QPlainTextEdit(); self.test_result.setReadOnly(True)
        layout.addWidget(self.yaml, 2); layout.addWidget(self.test_result, 1); self.tabs.addTab(page, 'YAML Tests')
        self.tabs.setTabToolTip(self.tabs.count()-1, 'Run scripted send, wait and check steps. Test-runner verdict limitations are documented in UI_SEARCH_AND_RX.md.')

    def _tab_changed(self, index):
        self._monitor_visible = self.tabs.widget(index) is self.monitor_page
        if self.tabs.widget(index) is self.session_page:
            self._refresh_session()
        if not self._monitor_visible:
            while not self.frames.empty():
                try: self.frames.get_nowait()
                except queue.Empty: break

    def _build_session(self):
        self.session_page = QWidget(); layout = QVBoxLayout(self.session_page)
        description = label('Signals successfully sent in this session for the selected program. '
                            'Selected = explicitly submitted; Payload field = carried in the same CAN frame. '
                            'Cycles repeat whole messages, not individual signals. History survives reconnects, but is not saved on exit.')
        description.setWordWrap(True); layout.addWidget(description)
        filters = QHBoxLayout()
        self.session_search = QLineEdit(); self.session_search.setPlaceholderText('Filter signal, message, DBC or CAN ID')
        self.session_cycles_only = QCheckBox('Cyclic only')
        self.session_more = QPushButton('More signals')
        self.session_more.clicked.connect(self._more_session)
        stop = QPushButton('Stop all cyclic'); stop.clicked.connect(lambda: self._run(self.sender.stop_all_cyclic))
        for widget in (self.session_search, self.session_cycles_only, self.session_more, stop): filters.addWidget(widget)
        layout.addLayout(filters)
        self.session_table = table(['Signal', 'Message / DBC / ID', 'Last TX value', 'Edit value',
                                    'Send', 'Cycle status', 'Interval', 'Cycle control', 'TX count / last time', 'Included as', 'Last action'],
                                   [180, 250, 110, 244, 65, 160, 110, 120, 170, 120, 160])
        self.session_table.horizontalHeader().setStretchLastSection(False)
        layout.addWidget(self.session_table, 1)
        self.session_summary = label('No signals sent yet. Send from Signal Studio or run a YAML test.'); layout.addWidget(self.session_summary)
        layout.addWidget(label('Enter, choices and − / + send immediately. Editing a cyclic signal updates its repeated message payload.'))
        self.session_search.textChanged.connect(self._reset_session_filter)
        self.session_cycles_only.toggled.connect(self._reset_session_filter)
        self.tabs.addTab(self.session_page, 'Session Signals')

    def _reset_session_filter(self, *_):
        self._session_limit = self.SIGNAL_PAGE_SIZE; self._session_signature = None
        self._refresh_session()

    def _more_session(self):
        self._session_limit += self.SIGNAL_PAGE_SIZE; self._session_signature = None
        self._refresh_session()

    def _session_cycle(self, msg, period):
        if msg['key'] in self.sender.get_cyclic_messages():
            self._run(lambda: self.sender.stop_cyclic(msg['name'], msg['dbc_id']))
        else:
            records = [r for r in self.sender.get_session_signals(self.state['active_program_id'])
                       if r['message_key'] == msg['key']]
            latest = max((r['sent_at'] for r in records), default=0)
            writable = {s['name'] for s in msg['signals'] if not s.get('read_only')}
            values = {r['signal']: r['value'] for r in records
                      if r['sent_at'] == latest and r['signal'] in writable}
            values.update({name: editor.value() for (key, name), editor in self._session_editors.items()
                           if key == msg['key'] and name in writable})
            self._cycle_periods[msg['key']] = period
            self._run(lambda: self.sender.start_cyclic(msg['name'], values, period, msg['dbc_id']))

    def _refresh_session(self):
        if self._busy or self._closing: return
        records = self.sender.get_session_signals(self.state['active_program_id'])
        cyclic = set(self.sender.get_cyclic_messages()); periods = self.sender.get_cyclic_periods()
        errors = self.sender.get_cyclic_errors()
        latest = {}
        for record in records:
            key = record['message_key']; latest[key] = max(latest.get(key, 0), record['sent_at'])
        term = self.session_search.text().casefold().strip()
        matches = [r for r in records if (not self.session_cycles_only.isChecked() or r['message_key'] in cyclic)
                   and (not term or term in ' '.join(str(r.get(k) or '') for k in
                        ('signal', 'message', 'dbc_filename', 'can_id')).casefold())]
        visible = matches[:self._session_limit]
        messages = {m['key']: m for m in self.state['messages']}
        signature = (self.state['active_program_id'], tuple((r['message_key'], r['signal']) for r in visible))
        if signature != self._session_signature:
            self._session_signature = signature; self._session_editors = {}; self._session_rows = []
            self.session_table.setRowCount(0); self.session_table.setRowCount(len(visible))
            value_width = 244
            for row, entry in enumerate(visible):
                msg = messages.get(entry['message_key'])
                sig = next((s for s in msg['signals'] if s['name'] == entry['signal']), None) if msg else None
                for col, text in enumerate([entry['signal'], f"{entry['message']} · {entry['dbc_filename'] or 'DBC'} · {entry['can_id']}"]):
                    item = QTableWidgetItem(text); item.setToolTip(text); self.session_table.setItem(row, col, item)
                for col in (2, 5, 8, 9, 10): self.session_table.setItem(row, col, QTableWidgetItem())
                if sig:
                    values = self.values.setdefault(msg['key'], {s['name']: s['initial_value'] for s in msg['signals']})
                    record_key = (msg['key'], sig['name'])
                    if self._session_seen_values.get(record_key) != entry['value'] and not self._pending_sends:
                        values[sig['name']] = entry['value']
                        self._session_seen_values[record_key] = entry['value']
                    cell, spin, width = self._value_editor(msg, sig)
                    self._session_editors[(msg['key'], sig['name'])] = spin
                    self.session_table.setCellWidget(row, 3, cell); value_width = max(value_width, width)
                    self.session_table.setRowHeight(row, 78 if sig.get('choices') else 42)
                    send = QPushButton('Send'); send.setEnabled(not sig.get('read_only'))
                    send.clicked.connect(lambda checked=False, m=msg, s=sig, editor=spin: self._submit_send(m, {s['name']: editor.value()}, 'session button'))
                    self.session_table.setCellWidget(row, 4, send)
                    period = QSpinBox(); period.setRange(1, 600000); period.setSuffix(' ms')
                    period.setValue(periods.get(msg['key'], self._cycle_periods.get(msg['key'], msg.get('cycle_time') or 100)))
                    self.session_table.setCellWidget(row, 6, period)
                    control = QPushButton('Start cyclic')
                    control.clicked.connect(lambda checked=False, m=msg, p=period: self._session_cycle(m, p.value()))
                    self.session_table.setCellWidget(row, 7, control)
                self._session_rows.append((self._session_seen_values.get((entry['message_key'], entry['signal'])), msg, sig))
            self.session_table.setColumnWidth(3, value_width)
        for row, entry in enumerate(visible):
            old_value, msg, sig = self._session_rows[row]
            self._set_cell(self.session_table, row, 2, f"{entry['value']:g}")
            key = entry['message_key']; active = key in cyclic
            state = ('Cyclic' if entry['sent_at'] == latest[key] else 'Cyclic · field inactive') if active else 'Not cyclic'
            if not sig: state = 'DBC inactive / removed'
            if errors.get(key): state = 'Cycle error'
            self._set_cell(self.session_table, row, 5, state)
            self.session_table.item(row, 5).setToolTip(errors.get(key) or state)
            self._set_cell(self.session_table, row, 8, f"{entry['count']} · {datetime.fromtimestamp(entry['sent_at']).strftime('%H:%M:%S.%f')[:-3]}")
            self._set_cell(self.session_table, row, 9, 'Selected' if entry['explicit'] else 'Payload field')
            feedback = self._row_feedback.get((key, entry['signal']))
            self._set_cell(self.session_table, row, 10, f"{feedback['status']} #{feedback['request_id']}" if feedback else 'TX accepted')
            self.session_table.item(row, 10).setToolTip((feedback or {}).get('error', ''))
            if sig:
                editor = self._session_editors[(key, sig['name'])]
                # Keep focused drafts and queued rapid edits intact during polling.
                focused = editor.parentWidget().isAncestorOf(QApplication.focusWidget()) if QApplication.focusWidget() else False
                if old_value != entry['value'] and not focused and not self._pending_sends:
                    editor.setValue(entry['value']); self._session_rows[row] = (entry['value'], msg, sig)
                    self._session_seen_values[(key, sig['name'])] = entry['value']
                period = self.session_table.cellWidget(row, 6)
                if isinstance(period, QSpinBox):
                    period.setEnabled(not active)
                    if active: period.setValue(periods.get(key, period.value()))
                control = self.session_table.cellWidget(row, 7)
                if isinstance(control, QPushButton): control.setText('Stop cyclic' if active else 'Start cyclic')
        self.session_more.setVisible(len(matches) > len(visible))
        self.session_summary.setText(f'{len(records)} session signals · {len(cyclic)} cyclic messages · showing {len(visible)} / {len(matches)} matches'
                                     if records else 'No signals sent yet. Send from Signal Studio or run a YAML test.')

    def _value_editor(self, msg, sig, on_update=None):
        cell = QWidget(); outer = QVBoxLayout(cell); outer.setContentsMargins(2, 2, 2, 2); outer.setSpacing(3)
        choices = sig.get('choices') or []; combo = QComboBox(cell); width = 244
        if choices and not sig.get('read_only'):
            combo.addItem('Numeric', None)
            for choice in choices: combo.addItem(f"{choice['label']} ({choice['raw_value']})", choice['value'])
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            combo.ensurePolished()
            width = max(width, max(combo.fontMetrics().horizontalAdvance(combo.itemText(i)) for i in range(combo.count())) + 60)
            combo.setMinimumWidth(width - 4); combo.view().setMinimumWidth(width)
            combo.view().setTextElideMode(Qt.TextElideMode.ElideNone)
            combo.currentTextChanged.connect(combo.setToolTip); outer.addWidget(combo)
        else: combo.hide()
        line = QHBoxLayout(); line.setSpacing(5); outer.addLayout(line)
        spin = CommitSpinBox(cell); spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        decimals = max(-Decimal(str(v)).as_tuple().exponent for v in (sig.get('scale') or 1, sig.get('offset') or 0))
        spin.setDecimals(min(9, max(2, decimals)))
        limits = [sig['min_value'], sig['max_value'], sig['initial_value'], *[c['value'] for c in choices]]
        spin.setRange(min(limits), max(limits)); spin.setSingleStep(abs(sig.get('scale') or 1))
        values = self.values.setdefault(msg['key'], {s['name']: s['initial_value'] for s in msg['signals']})
        spin.setValue(values[sig['name']]); spin.setEnabled(not sig.get('read_only'))
        minus = QPushButton('−'); plus = QPushButton('+')
        minus.setObjectName('decrease_' + sig['name']); plus.setObjectName('increase_' + sig['name'])
        for button in (minus, plus):
            button.setFixedWidth(28); button.setAutoRepeat(True); button.setAutoRepeatDelay(400); button.setAutoRepeatInterval(100)
            button.setEnabled(not sig.get('read_only')); button.setStyleSheet('padding: 5px 0;')
        minus.clicked.connect(spin.stepDown); plus.clicked.connect(spin.stepUp)
        line.addWidget(minus); spin.setMinimumWidth(68); line.addWidget(spin, 1); line.addWidget(plus)
        def update(value):
            self.values[msg['key']][sig['name']] = value
            combo.blockSignals(True); combo.setCurrentIndex(max(0, combo.findData(value))); combo.blockSignals(False)
            combo.setToolTip(combo.currentText())
            peers = [self._session_editors.get((msg['key'], sig['name']))]
            if self.selected and self.selected['key'] == msg['key']: peers.append(self.editors.get(sig['name']))
            for peer in peers:
                if peer is not None and peer is not spin and peer.value() != value: peer.setValue(value)
            if on_update: on_update(value)
        spin.valueChanged.connect(update)
        spin.committed.connect(lambda value: self._submit_send(msg, {sig['name']: value}, spin.commit_source))
        spin.rejected.connect(lambda text: self._reject_numeric(msg, sig, text))
        combo.currentIndexChanged.connect(lambda i: spin.setValue(combo.itemData(i)) if combo.itemData(i) is not None else None)
        combo.activated.connect(lambda i: self._submit_send(msg, {sig['name']: combo.itemData(i)}, 'text choice') if combo.itemData(i) is not None else None)
        update(spin.value())
        return cell, spin, width

    def _show_details(self, enabled):
        self.signals.setColumnHidden(3, not enabled)
        self.signals.setColumnHidden(5, not enabled)
        self.signals.fit_signal_column()

    def _show_message_details(self, enabled):
        for column in (2, 3, 4, 5):
            self.messages.setColumnHidden(column, not enabled)
        self.messages.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Interactive if enabled else QHeaderView.ResizeMode.Stretch)
        if enabled:
            self.messages.setColumnWidth(1, 160)

    def _new_program(self):
        name, accepted = QInputDialog.getText(self, 'New program', 'Program / app name:')
        if accepted: self._run(lambda: self.workspace.create_program(name), self.refresh_workspace)

    def _select_program(self):
        if not self._refreshing and self.programs.currentData():
            program_id = self.programs.currentData()
            self._run(lambda: self.workspace.select_program(program_id), self.refresh_workspace)

    def _add_dbcs(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Add DBC files', '', 'DBC files (*.dbc)')
        if paths:
            def upload(): return self.workspace.upload([(Path(p).name, Path(p).read_bytes()) for p in paths])
            self._run(upload, self.refresh_workspace)

    def _activate_files(self):
        if self._refreshing: return
        ids = [self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count())
               if self.files.item(i).checkState() == Qt.CheckState.Checked]
        self._run(lambda: self.workspace.activate(ids), self.refresh_workspace)

    def _enable_all_dbcs(self):
        ids = [file['id'] for file in self.state['files']]
        self._run(lambda: self.workspace.activate(ids), self.refresh_workspace)

    def _use_selected_dbcs(self):
        ids = [item.data(Qt.ItemDataRole.UserRole) for item in self.files.selectedItems()]
        if not ids:
            self._set_note('Select DBC files with Ctrl / Shift, then click Use selected.'); return
        self._run(lambda: self.workspace.activate(ids), self.refresh_workspace)

    def _delete_dbc(self):
        item = self.files.currentItem()
        if item and QMessageBox.question(self, 'Remove DBC', 'Remove this saved DBC, its favorites, and its signal notes from every program?') == QMessageBox.StandardButton.Yes:
            dbc_id = item.data(Qt.ItemDataRole.UserRole); self._run(lambda: self.workspace.delete(dbc_id), self.refresh_workspace)

    def refresh_workspace(self, state):
        if state['active_program_id'] != self.state.get('active_program_id'):
            self.values.clear(); self.selected = None
            self._session_seen_values.clear()
            self._cycle_periods.clear()
        self.state = state; self._refreshing = True
        self.programs.clear()
        for program in state['programs']: self.programs.addItem(program['name'], program['id'])
        self.programs.setCurrentIndex(self.programs.findData(state['active_program_id']))
        self.files.clear()
        for file in state['files']:
            item = QListWidgetItem(file['filename']); item.setData(Qt.ItemDataRole.UserRole, file['id'])
            load_status = ('Failed to load: ' + file['load_error'] if file.get('load_error') else
                           'Loaded' if file.get('loaded') else 'Disabled')
            item.setToolTip(f"{file['filename']}\n{file['message_count']} messages · {load_status}\n{file['id']}")
            if file.get('load_error'): item.setForeground(QColor('#ffb092'))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if file['active'] else Qt.CheckState.Unchecked); self.files.addItem(item)
        self.file_count.setText(f"{sum(f['active'] for f in state['files'])} enabled · {sum(f.get('loaded', False) for f in state['files'])} loaded · {len(state['files'])} saved")
        errors = state.get('restore_errors', [])
        self.dbc_error.setVisible(bool(state.get('restore_error')))
        summary = '; '.join(f"{e['filename']}: {e['error']}" for e in errors)
        self.dbc_error.setText((f"{len(errors)} DBC(s) could not load. " + summary[:600] +
                               ('…' if len(summary) > 600 else '') + '\nOther loaded DBCs remain available. Retry with Reload DBCs, or uncheck a failed file.')
                              if errors else (state.get('restore_error') or ''))
        self.dbc_error.setToolTip(state.get('restore_error') or '')
        source = self.monitor_source.currentData()
        self.monitor_source.clear(); self.monitor_source.addItem('Auto DBC (flag shared IDs)', None)
        for file in state['files']:
            if file['active']: self.monitor_source.addItem(file['filename'], file['id'])
        self.monitor_source.setCurrentIndex(max(0, self.monitor_source.findData(source)))
        self._favorite_keys = {(f['dbc_id'], f['message_name'], f['signal_name']) for f in state['favorites']}
        self._favorite_messages = {(f['dbc_id'], f['message_name']) for f in state['favorites']}
        self._cache_signal_notes(state.get('signal_notes', []))
        # Search text is prepared once per workspace update, not on every keypress.
        self._message_search_fields = {m['key']: (normalize(m['name']), normalize(m['arbitration_id_hex'])) for m in state['messages']}
        self._signal_search_fields = {m['key']: {s['name']: normalize(s['name']) for s in m['signals']} for m in state['messages']}
        self._search_index = {m['key']: self._message_search_fields[m['key']] + tuple(self._signal_search_fields[m['key']].values()) for m in state['messages']}
        self._favorite_search_index = {m['key']: self._message_search_fields[m['key']] + tuple(
            self._signal_search_fields[m['key']][s['name']] for s in m['signals'] if self._starred(m) or self._starred(m, s['name']))
            for m in state['messages']}
        self._definitions = {self.sender.message_key(m.name, d): m for d, _, m in self.sender.message_entries()}
        self._session_signature = None; self._session_editors = {}
        self._refreshing = False; self._apply_filter()
        if state.get('notice') or state.get('restore_error'): self._set_note(state.get('notice') or state['restore_error'], True)

    def _starred(self, msg, signal=''):
        return (msg['dbc_id'], msg['name'], signal) in self._favorite_keys

    def _cache_signal_notes(self, notes):
        self._signal_notes = {(n['dbc_id'], n['message_name'], n['signal_name']): n['note'] for n in notes}

    def _signal_note(self, msg, signal):
        return self._signal_notes.get((msg['dbc_id'], msg['name'], signal), '')

    def _show_signal_note(self, row, msg, sig):
        item = self.signals.item(row, 1)
        note = self._signal_note(msg, sig['name'])
        preview = ' '.join(note.split())
        subtitle = f'Note: {preview}' if preview else None
        item.setText(sig['name'])
        item.setData(Qt.ItemDataRole.UserRole, subtitle)
        item.setData(Qt.ItemDataRole.AccessibleTextRole, f"{sig['name']}. {subtitle}" if subtitle else sig['name'])
        parts = [sig['name'], f'Note: {note}' if note else '', sig.get('comment'),
                 sig.get('default_warning'), f"Range: {sig['min_value']:g} … {sig['max_value']:g} {sig['unit']}"]
        item.setToolTip('<qt>' + '<br><br>'.join(escape(part).replace('\n', '<br>') for part in parts if part) + '</qt>')
        height = 78 if sig.get('choices') and not sig.get('read_only') else (50 if note else 42)
        self.signals.setRowHeight(row, height)

    def _update_note_button(self):
        self.edit_signal_note.setEnabled(
            bool(self.selected and self.selected['dbc_id'] and self.signals.selectedItems()
                 and 0 <= self.signals.currentRow() < len(self.visible_signals))
        )

    def _edit_signal_note(self):
        row = self.signals.currentRow()
        if not self.selected or not 0 <= row < len(self.visible_signals):
            return
        msg, sig = self.selected, self.visible_signals[row]
        name = sig['name']
        note, accepted = QInputDialog.getMultiLineText(
            self, 'Signal note', f"{self.programs.currentText()} · {msg['name']}.{name}\n"
            'Describe when or why to send this signal. Clear the text to remove the note.',
            self._signal_note(msg, name),
        )
        if not accepted:
            return

        def saved(notes):
            self.state['signal_notes'] = notes
            self._cache_signal_notes(notes)
            self._show_signal_note(row, msg, sig)
            self._set_note('Signal note saved.' if note.strip() else 'Signal note removed.')

        self._run(lambda: self.workspace.set_signal_note(msg['dbc_id'], msg['name'], name, note), saved)

    def _export_favorites(self):
        program = self.programs.currentText()
        filename = re.sub(r'[^\w.-]+', '_', program).strip('._') or 'program'
        path, _ = QFileDialog.getSaveFileName(
            self, f'Export favorites from {program}', f'CANvas_{filename}_favorites.json', 'JSON files (*.json)')
        if not path:
            return

        def export():
            package = self.workspace.export_favorites()
            if not package['entries']:
                raise ValueError(f'No favorites in {package["program"]}. Star a signal or message first.')
            Path(path).write_text(json.dumps(package, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
            return sum(entry['favorite'] for entry in package['entries'])

        self._run(export, lambda count: self._set_note(f'Exported {count} favorites from {program}.'))

    def _import_favorites(self):
        program = self.programs.currentText()
        path, _ = QFileDialog.getOpenFileName(self, f'Import favorites into {program}', '', 'JSON files (*.json)')
        if not path:
            return

        def import_file():
            try:
                package = json.loads(Path(path).read_text(encoding='utf-8-sig'))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError('Select a valid CANvas favorites JSON export') from exc
            result = self.workspace.import_favorites(package)
            return self.workspace.state(), result

        def imported(payload):
            state, result = payload
            self.refresh_workspace(state)
            message = (f"Imported into {program}. {result['favorites_added']} new favorites, "
                       f"{result['notes_added']} new notes.")
            if result['notes_kept']:
                message += f" Kept {result['notes_kept']} existing notes that differed."
            if result['inactive_dbcs']:
                message += ' Enable these DBCs to see their signals: ' + ', '.join(result['inactive_dbcs'])
            self._set_note(message)

        self._run(import_file, imported)

    def _favorite(self, msg, signal=''):
        favorite = not self._starred(msg, signal)
        def action():
            self.workspace.favorite(msg['dbc_id'], msg['name'], signal, favorite)
            return self.workspace.state()
        self._run(action, self.refresh_workspace)

    def _favorite_button(self, msg, signal=''):
        selected = self._starred(msg, signal)
        button = QPushButton('★ Saved' if selected else '☆ Add')
        button.setObjectName('favorite'); button.setCheckable(True); button.setChecked(selected)
        target = signal or msg['name']
        button.setAccessibleName(('Remove favorite ' if selected else 'Add favorite ') + target)
        button.setToolTip(('Remove ' if selected else 'Add ') + target + ' from this program’s favorites')
        button.clicked.connect(lambda checked=False, m=msg, s=signal: self._favorite(m, s))
        return button

    def _message_clicked(self, row, col):
        if col == 0 and row < len(self.displayed): self._favorite(self.displayed[row])

    def _filter_changed(self):
        self.search_timer.start()

    def _apply_filter(self):
        self.search_timer.stop(); self.limit = self.PAGE_SIZE; self.signal_limit = self.SIGNAL_PAGE_SIZE; self._fill_messages()

    def _more(self): self.limit += self.PAGE_SIZE; self._fill_messages()

    def _more_signals(self): self.signal_limit += self.SIGNAL_PAGE_SIZE; self._select_message()

    def _fill_messages(self):
        # Selecting a result and constructing its editors can move Qt focus.
        # Preserve the active search edit through the entire synchronous refresh.
        editing_search = self.search.hasFocus()
        cursor = self.search.cursorPosition()
        start = self.search.selectionStart()
        length = len(self.search.selectedText())
        try:
            self._render_messages()
        finally:
            if editing_search:
                self.search.setFocus(Qt.FocusReason.OtherFocusReason)
                if start >= 0:
                    self.search.setSelection(start + length, -length) if cursor == start else self.search.setSelection(start, length)
                else:
                    self.search.setCursorPosition(cursor)

    def _render_messages(self):
        previous = self.selected['key'] if self.selected else None
        query = SearchQuery(self.search.text())
        index = self._favorite_search_index if self.favorites.isChecked() else self._search_index
        eligible = [m for m in self.state['messages'] if not self.favorites.isChecked() or (m['dbc_id'], m['name']) in self._favorite_messages]
        matches = [m for m in eligible if query.matches(index[m['key']])]
        self._search_fuzzy = not matches and query.allow_fuzzy
        if self._search_fuzzy:
            matches = [m for m in eligible if query.matches(index[m['key']], fuzzy=True)]
            matches.sort(key=lambda m: query.rank(index[m['key']]))
        self._search_query = query
        self.displayed = matches[:self.limit]
        self._refreshing = True; self.messages.setUpdatesEnabled(False); self.messages.setRowCount(0)
        self.messages.setRowCount(len(self.displayed))
        for row, msg in enumerate(self.displayed):
            self.messages.setCellWidget(row, 0, self._favorite_button(msg))
            values = ['★' if self._starred(msg) else '☆', msg['name'], msg.get('dbc_filename') or '',
                      f"{msg['arbitration_id_hex']} · {'FD' if msg['is_fd'] else 'CAN'}", 'Not seen', '0 / 0 / 0']
            for col, value in enumerate(values):
                item = QTableWidgetItem(value); item.setToolTip(value)
                if col == 0: item.setForeground(QColor('#edc569'))
                if col == 1:
                    subtitle = f"{msg['arbitration_id_hex']} {'FD' if msg['is_fd'] else 'CAN'}"
                    if msg.get('dbc_filename'):
                        subtitle += f" · {msg['dbc_filename']}"
                    item.setData(Qt.ItemDataRole.UserRole, subtitle)
                self.messages.setItem(row, col, item)
        match_type = 'approximate matches' if self._search_fuzzy and matches else 'matching messages'
        self.message_count.setText(f"{len(matches)} {match_type} · showing {len(self.displayed)} · {len(self.state['messages'])} loaded")
        self.more.setVisible(len(matches) > len(self.displayed))
        index = next((i for i, m in enumerate(self.displayed) if m['key'] == previous), 0)
        if self.displayed: self.messages.selectRow(index)
        self.messages.setUpdatesEnabled(True); self._refreshing = False
        if self.displayed: self._select_message()
        else:
            self.selected = None; self.signals.setRowCount(0); self.editors = {}; self.visible_signals = []
            if not self.state['messages']:
                empty = ('DBC loading failed — see the error above' if self.state.get('restore_error') else
                         'Enable a DBC file to show messages' if self.state['files'] else 'Add DBC files to show messages')
            elif self.favorites.isChecked():
                empty = 'No matching favorites — turn off Favorites only to search all messages'
            else:
                empty = 'No matching messages — clear or shorten the search'
            self.selected_title.setText(empty); self.signal_count.setText(''); self.more_signals.hide()
            self.definition_note.hide()
            self.fd_hint.hide(); self.shared_hint.hide()

    def _select_message(self):
        if self._refreshing: return
        row = self.messages.currentRow()
        if row < 0 or row >= len(self.displayed): return
        msg = self.displayed[row]
        if not self.selected or self.selected['key'] != msg['key']: self.signal_limit = self.SIGNAL_PAGE_SIZE
        self.selected = msg
        self.period.setValue(self._cycle_periods.get(msg['key'], msg.get('cycle_time') or 100))
        eligible = [s for s in msg['signals'] if not self.favorites.isChecked() or self._starred(msg) or self._starred(msg, s['name'])]
        # A signal search shows the matching fields, keeping large messages light.
        query = self._search_query
        if not query.matches(self._message_search_fields[msg['key']], fuzzy=self._search_fuzzy):
            eligible = [s for s in eligible if query.matches((self._signal_search_fields[msg['key']][s['name']],), fuzzy=self._search_fuzzy)]
        self.visible_signals = eligible[:self.signal_limit]
        self.selected_title.setText(f"{msg['name']}   ·   {msg['arbitration_id_hex']}   ·   {'CAN FD' if msg['is_fd'] else 'CAN'} / {msg['length']} bytes")
        self.selected_title.setToolTip(self.selected_title.text())
        self.shared_hint.setVisible(bool(msg.get('shared_sources')))
        self.shared_hint.setText(f"Shared CAN ID · source: {msg.get('dbc_filename')} · TX uses this selected definition; traffic counts are shared by ID.")
        self.signal_count.setText(f'{len(self.visible_signals)} / {len(eligible)} signals')
        warnings = [s['default_warning'] for s in self.visible_signals if s.get('default_warning')]
        self.definition_note.setVisible(bool(warnings))
        self.definition_note.setText((warnings[0] + (f'  (+{len(warnings)-1} more; see Details)' if len(warnings) > 1 else '')) if warnings else '')
        self.more_signals.setVisible(len(eligible) > len(self.visible_signals))
        self.signals.setUpdatesEnabled(False); self.signals.setRowCount(0); self.signals.setRowCount(len(self.visible_signals)); self.editors = {}
        values = self.values.setdefault(msg['key'], {s['name']: s['initial_value'] for s in msg['signals']})
        value_width = 244
        for row, sig in enumerate(self.visible_signals):
            self.signals.setCellWidget(row, 0, self._favorite_button(msg, sig['name']))
            self.signals.setItem(row, 1, QTableWidgetItem())
            self._show_signal_note(row, msg, sig)
            self.signals.setItem(row, 3, QTableWidgetItem('')); self.signals.setItem(row, 4, QTableWidgetItem('—'))
            def update(value, s=sig, r=row):
                raw = s.get('raw_initial') if s.get('scale') == 0 else (value - s.get('offset', 0)) / (s.get('scale') or 1)
                self.signals.item(r, 3).setText(f'{raw:g}' if raw is not None else '—')
            cell, spin, width = self._value_editor(msg, sig, update)
            value_width = max(value_width, width); self.signals.setCellWidget(row, 2, cell)
            if sig.get('choices') and not sig.get('read_only'): self.signals.setRowHeight(row, 78)
            notes = sig.get('default_warning') or f"{sig['min_value']:g} … {sig['max_value']:g} {sig['unit']}"
            note_item = QTableWidgetItem(notes); note_item.setToolTip(notes); self.signals.setItem(row, 5, note_item)
            send = QPushButton('Send'); send.setObjectName('sendSignal'); send.setEnabled(not sig.get('read_only'))
            send.clicked.connect(lambda checked=False, m=msg, s=sig, editor=spin: self._submit_send(m, {s['name']: editor.value()}))
            self.signals.setCellWidget(row, 6, send)
            self.signals.setItem(row, 7, QTableWidgetItem('Not sent'))
            self.editors[sig['name']] = spin
        self.signals.setColumnWidth(2, value_width); self.signals.fit_signal_column()
        self.signals.setUpdatesEnabled(True); self._update_note_button(); self._refresh_feedback(); self.refresh_status()

    def _current_values(self):
        if not self.selected: raise ValueError('Select a message first')
        return {s['name']: self.editors[s['name']].value() for s in self.visible_signals if not s.get('read_only')}

    def _send_selected(self):
        row = self.signals.currentRow()
        if self.selected and 0 <= row < len(self.visible_signals):
            sig = self.visible_signals[row]
            if not sig.get('read_only'): self._submit_send(self.selected, {sig['name']: self.editors[sig['name']].value()})
        else: self._set_note('Select a signal row first.')

    def _send_all(self):
        if self.selected: self._submit_send(self.selected, self._current_values())

    def _remember_cycle_period(self, period):
        if self.selected:
            self._cycle_periods[self.selected['key']] = period

    def _toggle_cyclic(self):
        if not self.selected: return
        msg = self.selected.copy(); values = self._current_values(); period = self.period.value()
        if msg['key'] in self.sender.get_cyclic_messages(): self._run(lambda: self.sender.stop_cyclic(msg['name'], msg['dbc_id']))
        elif msg['is_fd'] and not bus_manager.get_status()['fd']:
            self._set_note('Configure CAN FD and connect before starting this message.', True)
        else: self._run(lambda: self.sender.start_cyclic(msg['name'], values, period, msg['dbc_id']))

    def _verify(self):
        if not self.selected: return
        try:
            msg = self._definitions[self.selected['key']]
            result = traffic.verify(msg, self._current_values(), bus_manager.get_status()['connected'], self.max_age.value())
            mismatches = [f"{r['signal']}: expected {r['expected']:g}, RX {r['actual']}" for r in result['comparisons'] if not r['match']]
            self._set_note(f"RX snapshot {result['status']}: {result['reason']} " + '; '.join(mismatches), result['status'] != 'PASS')
        except ValueError as exc: self._set_note(str(exc), True)

    def _queue_frame(self, frame):
        if not self._monitor_visible: return
        try: self.frames.put_nowait(frame)
        except queue.Full: self._monitor_dropped += 1

    def _update_fd_hint(self, status):
        mismatch = bool(self.selected and self.selected['is_fd'] and (not status['connected'] or not status['fd']))
        self.fd_hint.setVisible(mismatch)
        if mismatch:
            mode = 'Adapter is connected in Classical CAN mode.' if status['connected'] else 'CAN FD connection needed.'
            self.fd_hint.setText(f"{mode} Check CAN FD beside Connect, then Apply & reconnect.")

    def refresh_status(self):
        if self._busy or self._closing: return
        status = bus_manager.get_status(); connected = status['connected']
        self.connect_button.setText('Disconnect' if connected else 'Connect')
        mode = f"CAN FD · {status['bitrate']} / {status['data_bitrate']} bit/s" if status['fd'] else f"Classical CAN · {status['bitrate']} bit/s"
        if not status.get('configure_bitrates', True):
            mode = ('CAN FD' if status['fd'] else 'Classical CAN') + ' · adapter saved bitrates (not read back)'
        device = ('SIMULATION' if status['bus_type'] == 'virtual' else status.get('channel_info') or status['bus_type'])
        self.bus_label.setText(f'● {device}   ·   {mode}' if connected else '○ Disconnected')
        self.bus_label.setToolTip(self.bus_label.text())
        if status.get('reader_error'): self._set_note('Adapter receiver stopped: ' + status['reader_error'] + '. Reconnect.', True)
        self._connection_fields(); self._update_fd_hint(status)
        cyclic = self.sender.get_cyclic_messages()
        self.cyclic_label.setText(f'{len(cyclic)} cyclic active' if cyclic else '')
        if self.tabs.currentIndex() == 0:
            errors = self.sender.get_cyclic_errors()
            # Only rows actually in the viewport need traffic updates.
            top = max(0, self.messages.rowAt(0)); bottom = self.messages.rowAt(self.messages.viewport().height() - 1)
            if bottom < 0: bottom = len(self.displayed) - 1
            rows = set(range(top, min(bottom + 1, len(self.displayed))))
            if self.selected:
                rows.update(i for i, m in enumerate(self.displayed) if m['key'] == self.selected['key'])
            for row in rows:
                msg = self.displayed[row]; definition = self._definitions[msg['key']]
                selected = bool(self.selected and self.selected['key'] == msg['key'])
                record = traffic.view(definition, connected, include_decoded=selected)
                text = record['state'].replace('_', ' ')
                if record['rx_age_ms'] is not None: text += f" · {record['rx_age_ms']:.0f} ms"
                self._set_cell(self.messages, row, 4, text)
                counts = f"{record['tx_count']} / {record['tx_echo_count']} / {record['rx_count']}"
                self._set_cell(self.messages, row, 5, counts)
                item = self.messages.item(row, 1)
                tooltip = f"{msg['name']}\n{msg.get('dbc_filename') or 'DBC'}\n{text}\nTX / echo / RX: {counts}"
                if item.toolTip() != tooltip:
                    item.setToolTip(tooltip)
                if selected:
                    self.cyclic.setText('Stop cyclic' if msg['key'] in cyclic else 'Start cyclic'); self.period.setEnabled(msg['key'] not in cyclic)
                    for i, sig in enumerate(self.visible_signals):
                        value = record['decoded'].get(sig['name']); self._set_cell(self.signals, i, 4, f'{value:g}' if value is not None else '—')
                    error = errors.get(msg['key'])
                    if error: self._set_note(error, True)
        if self._monitor_visible: self._drain_frames()
        if self.tabs.currentWidget() is self.session_page: self._refresh_session()

    @staticmethod
    def _set_cell(widget, row, col, text):
        item = widget.item(row, col)
        if item is not None and item.text() != text: item.setText(text)

    def _drain_frames(self):
        # Bound work by both frame count and time. No table autosizing per frame.
        deadline = time.perf_counter() + .012; count = 0; term = self.monitor_filter.text().casefold()
        self.monitor.setUpdatesEnabled(False)
        try:
            while count < 40 and time.perf_counter() < deadline:
                try: frame = self.frames.get_nowait()
                except queue.Empty: break
                count += 1
                if self.paused.isChecked(): continue
                try:
                    source = self.monitor_source.currentData()
                    info = self.sender.decode_frame(frame, source) if source else self.sender.decode_frame(frame)
                except Exception as exc: info = {'message_name': 'Decode error', 'decoded': {'error': str(exc)}}
                name = info.get('message_name') or ''; frame_id = f'0x{frame.arbitration_id:X}'
                if term and term not in (frame_id + ' ' + name).casefold(): continue
                if self.monitor.rowCount() >= 300: self.monitor.removeRow(0)
                row = self.monitor.rowCount(); self.monitor.insertRow(row)
                values = [datetime.fromtimestamp(frame.timestamp).strftime('%H:%M:%S.%f')[:-3] if frame.timestamp else '—',
                          'RX' if frame.is_rx else 'TX echo', frame_id, ('FD' if frame.is_fd else 'CAN') + (' ext' if frame.is_extended_id else ''), name,
                          frame.data.hex(' ').upper(), ' · '.join(f'{k}={v}' for k, v in info['decoded'].items())]
                for col, value in enumerate(values): self.monitor.setItem(row, col, QTableWidgetItem(value))
        finally: self.monitor.setUpdatesEnabled(True)
        self.monitor_note.setText(f'Live display · latest 300 frames · {self._monitor_dropped} omitted under load. RX status tracks traffic independently.')

    def _load_yaml(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open test', '', 'YAML (*.yaml *.yml)')
        if path: self.yaml.setPlainText(Path(path).read_text(encoding='utf-8'))

    def _run_yaml(self):
        if self._busy or self._closing: return
        content = self.yaml.toPlainText()
        self._test_cancel = threading.Event()
        cancel = self._test_cancel
        def run():
            from backend.runner.test_runner import run_test_from_yaml
            return asyncio.run(run_test_from_yaml(content, sender=self.sender, cancel_event=cancel))
        def show(result): self.test_result.setPlainText(result['status'] + '\n' + result.get('reason', '') + '\n' + '\n'.join(f"{s['status']}: {s['message']}" for s in result['steps']))
        self._run(run, show)

    def closeEvent(self, event):
        if self._shutdown_complete:
            event.accept(); return
        if self._closing:
            event.ignore(); return
        self._closing = True; self.timer.stop(); self.search_timer.stop()
        self._send_generation += 1
        if self._test_cancel is not None: self._test_cancel.set()
        self.sender.pause_transmissions()
        bus_manager.remove_listener(self._frame_listener)
        if self._busy or self._pending_sends:
            event.ignore(); self.centralWidget().setEnabled(False)
            self._set_note('Closing: cancellation requested; waiting for the current adapter call to finish…')
            def cleanup():
                try: self._shutdown_resources()
                finally: self.results.shutdown_ready.emit()
            threading.Thread(target=cleanup, name='canvas-shutdown', daemon=True).start()
            return
        self._shutdown_resources(); self._shutdown_complete = True; event.accept()

    def _shutdown_resources(self):
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.sender.stop_all_cyclic(); bus_manager.disconnect()
        self.sender.resume_transmissions()

    def _finish_close(self):
        self._shutdown_complete = True; self.close()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName('CANvas'); app.setOrganizationName('CANvas'); app.setStyleSheet(DARK)
    window = CanvasWindow(); window.show(); return app.exec()


if __name__ == '__main__': raise SystemExit(main())
