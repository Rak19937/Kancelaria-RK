"""Recoverable state replacement for RK Installed <-> Portable sync.

A SQLite DB and two document folders cannot be renamed atomically as one
filesystem operation. We stage all content, record a durable journal, and
restore the original state from a verified backup on any caught error. On a
power loss the journal blocks opening the potentially inconsistent database
until the backup has been restored offline.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

JOURNAL='.rk_sync_incomplete.json'


class SyncRecoveryRequired(RuntimeError):
    pass


def pending_sync_journal(data_dir: Path) -> Path | None:
    p=Path(data_dir)/JOURNAL
    return p if p.exists() else None


def _journal_write(path: Path, data: dict) -> None:
    tmp=path.with_suffix('.tmp')
    try:
        with tmp.open('w',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)


def restore_from_backup(destination: Path, backup: Path, existed: dict, managed_dirs) -> None:
    """Restore original DB and folders; backup is never modified."""
    destination=Path(destination);backup=Path(backup)
    if not backup.is_dir():
        raise SyncRecoveryRequired('Nie znaleziono kopii bezpieczeństwa synchronizacji.')
    db=destination/'sprawnik.sqlite3'
    if existed['db']:
        original=backup/'sprawnik.sqlite3'
        if not original.is_file():
            raise SyncRecoveryRequired('Backup nie zawiera wymaganej poprzedniej bazy SQLite.')
        temp=destination/('.rk_restore_'+uuid.uuid4().hex+'.sqlite3')
        shutil.copy2(original,temp)
        os.replace(temp,db)
    else:
        db.unlink(missing_ok=True)
    for dirname in managed_dirs:
        target=destination/dirname
        if existed[dirname]:
            original=backup/dirname
            if not original.is_dir():
                raise SyncRecoveryRequired('Backup nie zawiera poprzedniego katalogu '+dirname)
            staged=destination/('.rk_rollback_'+uuid.uuid4().hex)
            shutil.copytree(original,staged)
            if target.exists():shutil.rmtree(target)
            os.replace(staged,target)
        elif target.exists():
            shutil.rmtree(target)


def commit_staged(destination: Path, backup: Path, staged_db: Path,
                  stage_root: Path, managed_dirs, replace_dir, verify_db) -> None:
    destination=Path(destination);backup=Path(backup);stage_root=Path(stage_root)
    journal=destination/JOURNAL
    if journal.exists():
        raise SyncRecoveryRequired('Wykryto niedokończoną synchronizację. Najpierw przywróć backup wskazany w dzienniku.')
    present={'db':(destination/'sprawnik.sqlite3').exists()}
    present.update({d:(destination/d).exists() for d in managed_dirs})
    _journal_write(journal,{'format':'rk-sync-0.4-dev2','backup':str(backup.resolve()),
                            'original':present,'managed_dirs':list(managed_dirs)})
    try:
        dbtmp=destination/('.rk_sync_'+uuid.uuid4().hex+'.sqlite3')
        try:
            shutil.copy2(staged_db,dbtmp)
            os.replace(dbtmp,destination/'sprawnik.sqlite3')
        finally:
            dbtmp.unlink(missing_ok=True)
        for dirname in managed_dirs:
            replace_dir(stage_root/dirname,destination/dirname)
        ok,why=verify_db(destination/'sprawnik.sqlite3')
        if not ok:raise SyncRecoveryRequired('Baza po synchronizacji nie przeszła kontroli integralności: '+str(why))
    except Exception as exc:
        try:
            restore_from_backup(destination,backup,present,managed_dirs)
        except Exception as restore_error:
            raise SyncRecoveryRequired('NIE OTWIERAJ RK KANCELARIA. Nie udało się przywrócić stanu po błędzie synchronizacji: '
                                       +str(restore_error)+'; kopia: '+str(backup)) from exc
        journal.unlink(missing_ok=True)
        raise SyncRecoveryRequired('Synchronizacja przerwana; automatycznie przywrócono poprzednie dane. Przyczyna: '+str(exc)) from exc
    else:
        journal.unlink(missing_ok=True)


def recover_interrupted(data_dir: Path) -> str:
    """Offline recovery from the journal left by a process crash. No network."""
    data_dir=Path(data_dir).resolve(); journal=data_dir/JOURNAL
    if not journal.is_file():return 'Brak niedokończonej synchronizacji.'
    meta=json.loads(journal.read_text(encoding='utf-8'))
    if meta.get('format')!='rk-sync-0.4-dev2':
        raise SyncRecoveryRequired('Nieznana wersja dziennika; odtwórz ręcznie z backupu.')
    backup=Path(meta['backup']).resolve()
    allowed=(data_dir/'backup_synchronizacji').resolve()
    if backup==allowed or allowed not in backup.parents:
        raise SyncRecoveryRequired('Dziennik wskazuje backup poza katalogiem synchronizacji.')
    managed=tuple(meta['managed_dirs'])
    if managed != ('dokumenty','projekty_pism'):
        raise SyncRecoveryRequired('Nieznane katalogi w dzienniku synchronizacji.')
    restore_from_backup(data_dir,backup,meta['original'],managed)
    journal.unlink(missing_ok=True)
    return 'Przywrócono poprzedni stan bazy i dokumentów z '+str(backup)
