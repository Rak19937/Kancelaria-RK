# -*- coding: utf-8 -*-
"""RK 0.4.0-dev4: non-destructive audit, corrections and vault lifecycle.

No migrations of existing customer records. All additions are idempotent.
"""
from __future__ import annotations
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from rk_core.files import atomic_write_bytes
from rk_dev3_core import encrypt_vault, decrypt_vault


def ensure_dev4_schema(con: sqlite3.Connection) -> None:
    con.executescript('''
        CREATE TABLE IF NOT EXISTS dev4_action_log (
            id INTEGER PRIMARY KEY, case_id INTEGER REFERENCES cases(id) ON DELETE SET NULL,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            action TEXT NOT NULL, details TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_dev4_action_case ON dev4_action_log(case_id, created_at);
        CREATE TABLE IF NOT EXISTS dev4_time_voids (
            entry_id INTEGER PRIMARY KEY REFERENCES dev3_time_entries(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            explanation TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS dev4_time_corrections (
            id INTEGER PRIMARY KEY,
            entry_id INTEGER NOT NULL REFERENCES dev3_time_entries(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            previous_value TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    ''')


def action_log(con, case_id: int | None, user_id: int | None, action: str, details: str='') -> None:
    con.execute('INSERT INTO dev4_action_log(case_id,user_id,action,details) VALUES(?,?,?,?)',
                (case_id, user_id, action[:120], details[:1000]))


def audit_if_available(con, case_id, user_id, action, details=''):
    # Legacy isolated test fixtures may lack dev4 tables. Production always has them.
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dev4_action_log'").fetchone():
        action_log(con,case_id,user_id,action,details)


def void_time(con, entry_id: int, user_id: int, explanation: str='') -> bool:
    entry=con.execute('SELECT case_id FROM dev3_time_entries WHERE id=?', (entry_id,)).fetchone()
    if not entry: raise ValueError('Nie ma wskazanego wpisu czasu')
    if con.execute('SELECT 1 FROM dev4_time_voids WHERE entry_id=?',(entry_id,)).fetchone():
        raise ValueError('Wpis został już anulowany')
    con.execute('INSERT INTO dev4_time_voids(entry_id,user_id,explanation) VALUES(?,?,?)',
                (entry_id, user_id, explanation[:1000]))
    action_log(con, entry[0], user_id, 'Anulowanie wpisu czasu', f'Wpis {entry_id}')
    return True


def update_time(con, entry_id: int, user_id: int, day: str, minutes: int, description: str,
                rate_grosze: int, billable: bool) -> None:
    import json
    from datetime import date
    try: date.fromisoformat(day)
    except (ValueError, TypeError): raise ValueError('Niepoprawna data')
    if not 1 <= minutes <= 1440: raise ValueError('Czas musi wynosić od 1 do 1440 minut')
    if not 0 <= rate_grosze <= 100000000: raise ValueError('Niepoprawna stawka')
    row=con.execute('SELECT * FROM dev3_time_entries WHERE id=?',(entry_id,)).fetchone()
    if not row:raise ValueError('Nie znaleziono wpisu')
    if con.execute('SELECT 1 FROM dev4_time_voids WHERE entry_id=?',(entry_id,)).fetchone():
        raise ValueError('Nie można modyfikować anulowanego wpisu')
    snapshot=json.dumps(dict(row), ensure_ascii=False, default=str)
    con.execute('INSERT INTO dev4_time_corrections(entry_id,user_id,previous_value) VALUES(?,?,?)',
                (entry_id,user_id,snapshot))
    con.execute('''UPDATE dev3_time_entries SET activity_date=?, minutes=?,description=?,
              rate_grosze=?, billable=? WHERE id=?''',
              (day,minutes,description[:2000],rate_grosze,int(bool(billable)),entry_id))
    action_log(con,row['case_id'],user_id,'Korekta czasu',f'Wpis {entry_id}')


def vault_rotate(con, files_dir: Path, file_id: int, owner: int, old_passphrase: str,
                 new_passphrase: str) -> None:
    row=con.execute('SELECT * FROM dev3_vault_files WHERE id=?',(file_id,)).fetchone()
    if not row:raise ValueError('Nie znaleziono pliku sejfu')
    if not owner:raise ValueError('Brak uprawnień')
    path=files_dir/'_vault'/row['stored_name']
    raw=decrypt_vault(path.read_bytes(),old_passphrase)
    import hashlib
    if hashlib.sha256(raw).hexdigest()!=row['digest_sha256']:
        raise ValueError('Nieprawidłowa suma kontrolna dokumentu')
    # Change ciphertext atomically. The original file survives any failed encryption.
    encrypted=encrypt_vault(raw,new_passphrase)
    atomic_write_bytes(path,encrypted)


def vault_delete(con, files_dir: Path, file_id: int, owner: int) -> None:
    """Delete DB row first; on-disk deletion after commit belongs to caller.

    Use `vault_file_path` before calling this and unlink after committing.
    """
    if not owner:raise ValueError('Brak uprawnień')
    if not con.execute('SELECT 1 FROM dev3_vault_files WHERE id=?',(file_id,)).fetchone():
        raise ValueError('Nie znaleziono pliku')
    con.execute('DELETE FROM dev3_vault_files WHERE id=?',(file_id,))


def vault_file_path(files_dir: Path, stored_name: str) -> Path:
    import re
    if not re.fullmatch(r'[0-9a-f]{32}\.rkv',stored_name):
        raise ValueError('Nieprawidłowy identyfikator sejfu')
    return files_dir/'_vault'/stored_name
