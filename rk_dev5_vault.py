# -*- coding: utf-8 -*-
"""Recovery journal for file/SQLite vault operations (power-loss tolerant).

A durable 'prepared' journal entry is committed BEFORE changing a cipher file.
A 'committed' entry is committed with DB audit/deletion. Startup recovery then
knows whether to restore the old ciphertext or finish a committed operation.
"""
from __future__ import annotations
import hashlib
import os
import threading
import uuid
from pathlib import Path

from rk_dev3_core import encrypt_vault, decrypt_vault
from rk_core.files import atomic_write_bytes
from rk_dev4_core import vault_file_path, action_log

_LOCK=threading.RLock()


def ensure_dev5_vault_schema(con):
    con.executescript('''
      CREATE TABLE IF NOT EXISTS dev5_vault_journal (
       op_id TEXT PRIMARY KEY, stored_name TEXT NOT NULL,
       file_id INTEGER NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('rotate','delete')),
       state TEXT NOT NULL CHECK(state IN ('prepared','committed')),
       created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      );
    ''')


def _backup(root:Path,op_id:str) -> Path:
    if len(op_id)!=32 or any(c not in '0123456789abcdef' for c in op_id):
        raise ValueError('Nieprawidłowy identyfikator dziennika')
    return root/'_vault'/('.rk_recovery_'+op_id+'.rkv')


def _recover_one(db,files_dir:Path, row):
    op=row['op_id']; name=row['stored_name']; status=row['state']; kind=row['kind']
    target=vault_file_path(files_dir,name)
    saved=_backup(files_dir,op)
    if status=='prepared':
        if saved.exists():
            os.replace(saved,target)   # prior ciphertext takes precedence
        elif not target.is_file():
            raise RuntimeError('Brak pliku starego sejfu i jego kopii awaryjnej: '+op)
    elif status=='committed':
        if kind=='rotate' and not target.is_file():
            raise RuntimeError('Brak nowego szyfrogramu po zatwierdzeniu zmiany: '+op)
        if kind=='delete' and target.exists():
            raise RuntimeError('Wykryto niezgodność: zatwierdzono usuwanie, ale plik wciąż istnieje: '+op)
        saved.unlink(missing_ok=True)
    else:raise RuntimeError('Nieznany stan journalu sejfu: '+op)
    with db() as con:
        con.execute('DELETE FROM dev5_vault_journal WHERE op_id=?',(op,))


def recover_vault_journal(db,files_dir:Path):
    """Must run at app init before serving HTTP or starting OCR worker."""
    with _LOCK:
        with db() as con:
            rows=con.execute('SELECT * FROM dev5_vault_journal ORDER BY created_at,op_id').fetchall()
        for row in rows:_recover_one(db,files_dir,row)


def vault_change_safe(db,files_dir:Path,file_id:int,user_id:int,is_admin:bool,kind:str,
                      old_password:str='',new_password:str=''):
    if kind not in ('rotate','delete'):raise ValueError('Nieznana operacja sejfu')
    with _LOCK:
        with db() as con:
            row=con.execute('SELECT * FROM dev3_vault_files WHERE id=?',(file_id,)).fetchone()
            if not row:raise ValueError('Nie znaleziono pliku sejfu')
            if not (is_admin or row['owner_id']==user_id):raise PermissionError('Brak praw do sejfu')
            name=row['stored_name']; cid=row['case_id']; path=vault_file_path(files_dir,name)
            if not path.is_file():raise ValueError('Brak pliku sejfu na dysku')
            if con.execute('SELECT 1 FROM dev5_vault_journal WHERE stored_name=?',(name,)).fetchone():
                raise RuntimeError('Niedokończona operacja na pliku sejfu; uruchom odzyskiwanie')
            before=path.read_bytes()
            if kind=='rotate':
                plain=decrypt_vault(before,old_password)
                if hashlib.sha256(plain).hexdigest()!=row['digest_sha256']:
                    raise ValueError('Plik sejfu nie zgadza się z sumą SHA-256')
                after=encrypt_vault(plain,new_password)
            else:after=b''
        op=uuid.uuid4().hex
        saved=_backup(files_dir,op)
        # First persist journal entry. The existing encrypted file is still intact.
        with db() as con:
            con.execute('INSERT INTO dev5_vault_journal(op_id,stored_name,file_id,kind,state) VALUES(?,?,?,?,?)',
                        (op,name,file_id,kind,'prepared'))
        try:
            # For rotate, retain the old ciphertext as a durable backup until
            # the SQLite action log and 'committed' state are committed.
            os.replace(path,saved)
            if kind=='rotate':atomic_write_bytes(path,after)
            with db() as con:
                current=con.execute('SELECT stored_name FROM dev3_vault_files WHERE id=?',(file_id,)).fetchone()
                if not current or current[0]!=name:
                    raise RuntimeError('Plik sejfu zmienił się podczas operacji')
                if kind=='delete':con.execute('DELETE FROM dev3_vault_files WHERE id=?',(file_id,))
                action_log(con,cid,user_id,'Usunięcie pliku sejfu' if kind=='delete' else 'Zmiana hasła sejfu',f'Plik {file_id}')
                con.execute('UPDATE dev5_vault_journal SET state=? WHERE op_id=?',('committed',op))
        except Exception:
            # If process stays alive, recover now. If power is lost, init_db
            # will find the prepared row and recover before serving requests.
            _recover_one(db,files_dir,{'op_id':op,'stored_name':name,'state':'prepared','kind':kind})
            raise
        # Deleting the recovery ciphertext may fail; committed journal tells
        # startup recovery to finish cleanup. Never undo committed SQLite work.
        try:_recover_one(db,files_dir,{'op_id':op,'stored_name':name,'state':'committed','kind':kind})
        except OSError:
            # Preserve journal for retry, but do not claim cleanup succeeded.
            raise RuntimeError('Operacja została zapisana, ale wymaga usunięcia pliku technicznego przy ponownym uruchomieniu')
