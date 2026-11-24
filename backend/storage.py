"""Persistent DBC files, selection and favorites on the CANvas host."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid
import json


class WorkspaceStore:
    def __init__(self, directory: str | Path | None = None):
        self.directory = Path(directory or os.environ.get('CANVAS_DATA_DIR') or Path.home() / '.canvas')
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'workspace.sqlite3'
        self._lock = threading.RLock()
        with self.connection() as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS dbcs (
                    id TEXT PRIMARY KEY, filename TEXT NOT NULL, content BLOB NOT NULL,
                    message_count INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS favorites (
                    dbc_id TEXT NOT NULL REFERENCES dbcs(id) ON DELETE CASCADE,
                    message_name TEXT NOT NULL, signal_name TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (dbc_id, message_name, signal_name)
                );
            ''')
        self._migrate_programs()

    def _migrate_programs(self):
        with self._lock, self.connection() as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS programs (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS program_dbcs (
                    program_id TEXT NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
                    dbc_id TEXT NOT NULL REFERENCES dbcs(id) ON DELETE CASCADE,
                    PRIMARY KEY(program_id, dbc_id)
                );
                CREATE TABLE IF NOT EXISTS signal_notes (
                    program_id TEXT NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
                    dbc_id TEXT NOT NULL REFERENCES dbcs(id) ON DELETE CASCADE,
                    message_name TEXT NOT NULL,
                    signal_name TEXT NOT NULL,
                    note TEXT NOT NULL,
                    PRIMARY KEY (program_id, dbc_id, message_name, signal_name)
                );
            ''')
            db.execute("INSERT OR IGNORE INTO programs VALUES ('default', 'Default', ?)", (time.time(),))
            columns = {row['name'] for row in db.execute('PRAGMA table_info(favorites)')}
            if 'program_id' not in columns:
                db.execute('ALTER TABLE favorites RENAME TO favorites_legacy')
                db.execute('CREATE TABLE favorites ('
                           'program_id TEXT NOT NULL REFERENCES programs(id) ON DELETE CASCADE, '
                           'dbc_id TEXT NOT NULL REFERENCES dbcs(id) ON DELETE CASCADE, '
                           "message_name TEXT NOT NULL, signal_name TEXT NOT NULL DEFAULT '', "
                           'PRIMARY KEY (program_id, dbc_id, message_name, signal_name))')
                db.execute("INSERT INTO favorites SELECT 'default', dbc_id, message_name, signal_name FROM favorites_legacy")
                db.execute('DROP TABLE favorites_legacy')
            if db.execute("SELECT 1 FROM settings WHERE key = 'active_program'").fetchone() is None:
                db.execute("INSERT INTO settings VALUES ('active_program', 'default')")
                db.execute("INSERT OR IGNORE INTO program_dbcs SELECT 'default', id FROM dbcs WHERE active = 1")

    def active_program(self):
        with self.connection() as db:
            return db.execute("SELECT value FROM settings WHERE key = 'active_program'").fetchone()[0]

    def connection_settings(self):
        with self.connection() as db:
            row = db.execute("SELECT value FROM settings WHERE key = 'connection'").fetchone()
        try:
            return json.loads(row[0]) if row else {}
        except (TypeError, ValueError):
            return {}

    def save_connection_settings(self, settings):
        with self._lock, self.connection() as db, db:
            db.execute("INSERT OR REPLACE INTO settings VALUES ('connection', ?)", (json.dumps(settings),))

    def programs(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM programs ORDER BY created_at, id')]

    def create_program(self, name):
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError('Use a program name between 1 and 80 characters')
        with self._lock, self.connection() as db, db:
            if any(row['name'].casefold() == name.casefold() for row in db.execute('SELECT name FROM programs')):
                raise ValueError('A program with this name already exists')
            program_id = uuid.uuid4().hex
            db.execute('INSERT INTO programs VALUES (?, ?, ?)', (program_id, name, time.time()))
            db.execute('INSERT INTO program_dbcs SELECT ?, id FROM dbcs WHERE active = 1', (program_id,))
        return program_id

    def program_dbc_ids(self, program_id):
        with self.connection() as db:
            if db.execute('SELECT id FROM programs WHERE id = ?', (program_id,)).fetchone() is None:
                raise ValueError('Program not found')
            return [row[0] for row in db.execute('SELECT dbc_id FROM program_dbcs WHERE program_id = ?', (program_id,))]

    def select_program(self, program_id):
        with self._lock, self.connection() as db, db:
            if db.execute('SELECT id FROM programs WHERE id = ?', (program_id,)).fetchone() is None:
                raise ValueError('Program not found')
            db.execute("UPDATE settings SET value = ? WHERE key = 'active_program'", (program_id,))
            db.execute('UPDATE dbcs SET active = 0')
            db.execute('UPDATE dbcs SET active = 1 WHERE id IN (SELECT dbc_id FROM program_dbcs WHERE program_id = ?)', (program_id,))

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        try:
            yield db
        finally:
            db.close()

    def list_dbcs(self):
        with self.connection() as db:
            return [{**dict(row), 'active': bool(row['active'])} for row in db.execute(
                'SELECT id, filename, message_count, active, created_at FROM dbcs ORDER BY created_at, id')]

    def get(self, dbc_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM dbcs WHERE id = ?', (dbc_id,)).fetchone()
        if row is None:
            raise ValueError('Saved DBC not found')
        return dict(row)

    def save_many(self, entries):
        ids = []
        with self._lock, self.connection() as db, db:
            for filename, content, message_count in entries:
                dbc_id = hashlib.sha256(content).hexdigest()
                # Re-uploading identical content preserves selection and favorites.
                db.execute('INSERT OR IGNORE INTO dbcs '
                           '(id, filename, content, message_count, created_at) VALUES (?, ?, ?, ?, ?)',
                           (dbc_id, filename, content, message_count, time.time()))
                ids.append(dbc_id)
        return ids

    def set_active(self, ids):
        with self._lock, self.connection() as db, db:
            known = {r[0] for r in db.execute('SELECT id FROM dbcs')}
            if set(ids) - known:
                raise ValueError('Saved DBC not found')
            db.execute('UPDATE dbcs SET active = 0')
            db.executemany('UPDATE dbcs SET active = 1 WHERE id = ?', [(i,) for i in ids])
            program_id = db.execute("SELECT value FROM settings WHERE key = 'active_program'").fetchone()[0]
            db.execute('DELETE FROM program_dbcs WHERE program_id = ?', (program_id,))
            db.executemany('INSERT INTO program_dbcs VALUES (?, ?)', [(program_id, i) for i in set(ids)])

    def delete(self, dbc_id):
        with self._lock, self.connection() as db, db:
            db.execute('DELETE FROM dbcs WHERE id = ?', (dbc_id,))

    def favorites(self):
        with self.connection() as db:
            return [dict(r) for r in db.execute(
                'SELECT dbc_id, message_name, signal_name FROM favorites WHERE program_id = ? '
                'ORDER BY dbc_id, message_name, signal_name', (self.active_program(),))]

    def set_favorite(self, dbc_id, message_name, signal_name, favorite):
        with self._lock, self.connection() as db, db:
            program_id = self.active_program()
            if favorite:
                db.execute('INSERT OR IGNORE INTO favorites VALUES (?, ?, ?, ?)',
                           (program_id, dbc_id, message_name, signal_name or ''))
            else:
                db.execute('DELETE FROM favorites WHERE program_id = ? AND dbc_id = ? AND message_name = ? AND signal_name = ?',
                           (program_id, dbc_id, message_name, signal_name or ''))

    def signal_notes(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                'SELECT dbc_id, message_name, signal_name, note FROM signal_notes '
                'WHERE program_id = ? ORDER BY dbc_id, message_name, signal_name',
                (self.active_program(),))]

    def set_signal_note(self, dbc_id, message_name, signal_name, note):
        with self._lock, self.connection() as db, db:
            key = (self.active_program(), dbc_id, message_name, signal_name)
            if note:
                db.execute('INSERT OR REPLACE INTO signal_notes VALUES (?, ?, ?, ?, ?)', (*key, note))
            else:
                db.execute('DELETE FROM signal_notes WHERE program_id = ? AND dbc_id = ? '
                           'AND message_name = ? AND signal_name = ?', key)

    def merge_favorites(self, entries):
        with self._lock, self.connection() as db, db:
            program = self.active_program()
            added = notes_added = conflicts = 0
            for entry in entries:
                key = (program, entry['dbc_id'], entry['message_name'], entry['signal_name'])
                if entry['favorite']:
                    added += db.execute('INSERT OR IGNORE INTO favorites VALUES (?, ?, ?, ?)', key).rowcount
                if entry['note']:
                    old = db.execute('SELECT note FROM signal_notes WHERE program_id = ? AND dbc_id = ? '
                                     'AND message_name = ? AND signal_name = ?', key).fetchone()
                    if old is None:
                        db.execute('INSERT INTO signal_notes VALUES (?, ?, ?, ?, ?)', (*key, entry['note']))
                        notes_added += 1
                    elif old['note'] != entry['note']:
                        conflicts += 1
        return {'favorites_added': added, 'notes_added': notes_added, 'notes_kept': conflicts}
