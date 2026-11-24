"""Coordinate persisted DBCs with the active message definitions."""
from __future__ import annotations

from pathlib import Path
import threading
import hashlib
import re

from backend.storage import WorkspaceStore
from backend.can.signal_sender import SignalSender, signal_sender


class DbcWorkspace:
    FAVORITES_FORMAT = 'canvas-favorites-v1'
    NOTE_LIMIT = 2000
    def __init__(self, store=None, sender=None):
        self.store = store or WorkspaceStore()
        self.sender = sender or signal_sender
        self._lock = threading.RLock()
        self._parsed = {}
        self.restore_error = None
        self.restore_errors = []
        self.reload(reparse=False)

    def reload(self, reparse=True):
        """Restore each enabled file independently, preserving selection and bytes."""
        with self._lock:
            entries = []
            errors = []
            for row in self.store.list_dbcs():
                if not row['active']:
                    continue
                try:
                    # Retry from saved bytes, rather than reusing a stale parse.
                    if reparse:
                        self._parsed.pop(row['id'], None)
                    entries.extend(self._databases([row['id']]))
                except Exception as exc:
                    errors.append(dict(dbc_id=row['id'], filename=row['filename'], error=str(exc)))
            self.sender.use_databases(entries, session_scope=self.store.active_program())
            self.restore_errors = errors
            self.restore_error = ('DBC loading failed: ' + '; '.join(
                f"{e['filename']}: {e['error']}" for e in errors)) if errors else None
            return self.state()

    def state(self):
        with self._lock:
            loaded = set(self.sender._databases)
            errors = {e['dbc_id']: e['error'] for e in self.restore_errors}
            files = [{**row, 'loaded': row['id'] in loaded, 'load_error': errors.get(row['id'])}
                     for row in self.store.list_dbcs()]
            return {**self.sender.get_all_messages(), 'files': files,
                    'favorites': self.store.favorites(), 'signal_notes': self.store.signal_notes(),
                    'restore_error': self.restore_error,
                    'restore_errors': list(self.restore_errors),
                    'programs': self.store.programs(), 'active_program_id': self.store.active_program()}

    def select_program(self, program_id):
        with self._lock:
            self.store.program_dbc_ids(program_id)  # Validate before changing selection.
            self.store.select_program(program_id)
            return self.reload(reparse=False)

    def create_program(self, name):
        with self._lock:
            program_id = self.store.create_program(name)
            return self.select_program(program_id)

    def _databases(self, ids):
        entries = []
        for dbc_id in dict.fromkeys(ids):
            row = self.store.get(dbc_id)
            if dbc_id not in self._parsed:
                self._parsed[dbc_id] = SignalSender.parse_dbc(row['content'])
            entries.append((dbc_id, row['filename'], self._parsed[dbc_id]))
        SignalSender.validate_databases(entries)
        return entries

    def _activate(self, ids):
        entries = self._databases(ids)
        self.store.set_active(ids)
        current_ids = set(self.sender._databases)
        if current_ids != set(ids) or (not entries and self.sender._db is not None):
            self.sender.use_databases(entries, session_scope=self.store.active_program())
        self.restore_error = None
        self.restore_errors = []

    def activate(self, ids):
        with self._lock:
            self._activate(ids)
            return self.state()

    def upload(self, uploads):
        entries = []
        parsed = {}
        for filename, content in uploads:
            filename = Path(filename.replace('\\', '/')).name
            if not filename.lower().endswith('.dbc'):
                raise ValueError('Only .dbc files are supported')
            try:
                db = SignalSender.parse_dbc(content)
            except ValueError as exc:
                raise ValueError(f'{filename}: {exc}') from exc
            SignalSender.validate_databases([('upload', filename, db)])
            parsed[hashlib.sha256(content).hexdigest()] = db
            entries.append((filename, content, len(db.messages)))
        with self._lock:
            old_ids = [r['id'] for r in self.store.list_dbcs() if r['active']]
            new_ids = self.store.save_many(entries)
            self._parsed.update(parsed)
            notice = None
            try:
                self._activate(list(dict.fromkeys(old_ids + new_ids)))
            except ValueError as exc:
                # Valid files are saved even when they conflict with the active set.
                notice = f'Files saved. Active selection unchanged: {exc}'
            return {**self.state(), 'notice': notice, 'uploaded_ids': new_ids}

    def delete(self, dbc_id):
        with self._lock:
            self.store.get(dbc_id)
            was_active = any(r['id'] == dbc_id and r['active'] for r in self.store.list_dbcs())
            active = [r['id'] for r in self.store.list_dbcs() if r['active'] and r['id'] != dbc_id]
            entries = self._databases(active)
            self.store.delete(dbc_id)
            self._parsed.pop(dbc_id, None)
            if was_active:
                self.sender.use_databases(entries, session_scope=self.store.active_program())
            self.restore_errors = []
            self.restore_error = None
            return self.state()

    def _favorite_target(self, dbc_id, message_name, signal_name):
        if dbc_id not in self._parsed:
            self._parsed[dbc_id] = SignalSender.parse_dbc(self.store.get(dbc_id)['content'])
        try:
            msg = self._parsed[dbc_id].get_message_by_name(message_name)
        except KeyError:
            raise ValueError(f'Message not found in this DBC: {message_name}') from None
        if signal_name and signal_name not in {s.name for s in msg.signals}:
            raise ValueError(f'Signal not found in {message_name}: {signal_name}')

    def favorite(self, dbc_id, message_name, signal_name, favorite):
        with self._lock:
            self._favorite_target(dbc_id, message_name, signal_name)
            self.store.set_favorite(dbc_id, message_name, signal_name, favorite)
            return {'favorites': self.store.favorites()}

    @classmethod
    def _clean_note(cls, note):
        if not isinstance(note, str) or len(note) > cls.NOTE_LIMIT:
            raise ValueError(f'Use up to {cls.NOTE_LIMIT} characters per signal note')
        return note.strip()

    def set_signal_note(self, dbc_id, message_name, signal_name, note):
        with self._lock:
            if not signal_name:
                raise ValueError('Select a signal first')
            self._favorite_target(dbc_id, message_name, signal_name)
            self.store.set_signal_note(dbc_id, message_name, signal_name, self._clean_note(note))
            return self.store.signal_notes()

    def export_favorites(self):
        with self._lock:
            program_id = self.store.active_program()
            program = next(p['name'] for p in self.store.programs() if p['id'] == program_id)
            filenames = {f['id']: f['filename'] for f in self.store.list_dbcs()}
            favorites = {(f['dbc_id'], f['message_name'], f['signal_name']) for f in self.store.favorites()}
            notes = {(n['dbc_id'], n['message_name'], n['signal_name']): n['note']
                     for n in self.store.signal_notes()}
            keys = favorites | {key for key in notes if (*key[:2], '') in favorites}
            entries = [
                {'dbc_id': dbc_id, 'dbc_filename': filenames[dbc_id], 'message_name': message,
                 'signal_name': signal, 'favorite': (dbc_id, message, signal) in favorites,
                 'note': notes.get((dbc_id, message, signal), '')}
                for dbc_id, message, signal in sorted(keys)
            ]
            return {'format': self.FAVORITES_FORMAT, 'program': program, 'entries': entries}

    def import_favorites(self, package):
        if not isinstance(package, dict) or package.get('format') != self.FAVORITES_FORMAT:
            raise ValueError('Select a CANvas favorites JSON export')
        entries = package.get('entries')
        if not isinstance(entries, list) or not entries:
            raise ValueError('The favorites file contains no entries')
        with self._lock:
            files = {f['id']: f for f in self.store.list_dbcs()}
            seen, missing, inactive = set(), set(), set()
            validated = []
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError('Invalid favorites entry')
                dbc_id, message, signal, filename = (entry.get(k) for k in
                    ('dbc_id', 'message_name', 'signal_name', 'dbc_filename'))
                if not all(isinstance(v, str) for v in (dbc_id, message, signal, filename)):
                    raise ValueError('Invalid DBC, message, or signal in favorites file')
                if not re.fullmatch(r'[0-9a-f]{64}', dbc_id) or not message or not filename:
                    raise ValueError('Invalid DBC or message reference in favorites file')
                favorite = entry.get('favorite')
                note = self._clean_note(entry.get('note'))
                key = (dbc_id, message, signal)
                if (type(favorite) is not bool or (not favorite and not note)
                        or (note and not signal) or key in seen):
                    raise ValueError('Invalid or duplicate favorites entry')
                seen.add(key)
                if dbc_id not in files:
                    missing.add(filename)
                    continue
                self._favorite_target(*key)
                if not files[dbc_id]['active']:
                    inactive.add(files[dbc_id]['filename'])
                validated.append({**entry, 'note': note})
            if missing:
                raise ValueError('Add the matching DBC version(s) and retry: ' + ', '.join(sorted(missing)))
            return {**self.store.merge_favorites(validated), 'inactive_dbcs': sorted(inactive)}


workspace = DbcWorkspace()
