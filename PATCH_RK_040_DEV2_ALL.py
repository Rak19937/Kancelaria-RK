#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RK KANCELARIA 0.4.0-dev2: combined audited patch, no user data changes.

Run after ZASTOSUJ_040_DEV2.py. AST identifies the exact original functions.
All changed source files are validated and updated as a single, recoverable batch.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import tempfile
from pathlib import Path

MARKER = 'RK_040_DEV2_AUDIT_PATCH_20261106_R1'
VERSION = 'VERSION = "0.4.0-dev2"'
MANIFEST = ('.rk_audit_patch_040_dev2_manifest.json')


def function_span(text: str, name: str, owner: str | None = None) -> tuple[int, int]:
    tree = ast.parse(text)
    nodes = tree.body
    if owner:
        classes = [n for n in nodes if isinstance(n, ast.ClassDef) and n.name == owner]
        if len(classes) != 1:
            raise ValueError('Brak jednoznacznej klasy ' + owner)
        nodes = classes[0].body
    found = [n for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if len(found) != 1:
        raise ValueError(f'Brak jednoznacznej funkcji {owner or "module"}.{name}')
    node = found[0]
    lines = text.splitlines(keepends=True)
    start = min([node.lineno] + [n.lineno for n in node.decorator_list]) - 1
    return sum(len(x) for x in lines[:start]), sum(len(x) for x in lines[:node.end_lineno])


def replace_function(text: str, name: str, code: str, owner: str | None = None) -> str:
    a, b = function_span(text, name, owner)
    expected_indent = 4 if owner else 0
    start = code.splitlines()[0]
    if len(start) - len(start.lstrip()) != expected_indent:
        raise ValueError('Nieprawidłowe wcięcie nowej funkcji: ' + name)
    return text[:a] + code.rstrip() + '\n' + text[b:]


def replace_once(text: str, old: str, new: str, description: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f'{description}: oczekiwano dokładnie jednej kotwicy, znaleziono {count}. Nie zmieniono plików.')
    return text.replace(old, new, 1)


ATOMIC_RESTORE = r'''def apply_pending_restore_if_any() -> str:
    """Switch DB and attachments as one recoverable operation.

    SQLite and directories cannot be swapped in one filesystem syscall.
    Prepare everything on the same volume, back up both, then journal the
    replacement; on exception the original state is restored. Power loss
    leaves a recovery journal that prevents unsafe startup.
    """
    if not PENDING_RESTORE_MARKER.exists() or not PENDING_RESTORE_DB.exists():
        return ''
    if pending_sync_journal(DATA_DIR):
        raise RuntimeError('Wykryto niedokończoną synchronizację. Przywróć jej kopię przed uruchomieniem RK KANCELARIA.')
    try:
        meta=json.loads(PENDING_RESTORE_MARKER.read_text(encoding='utf-8'))
        if not isinstance(meta,dict):raise ValueError('Nieprawidłowy znacznik przywracania.')
    except Exception as exc:
        raise RuntimeError('Nie można odczytać znacznika przywracania. Dane pozostawiono bez zmian.') from exc
    ok,why=sqlite_integrity(PENDING_RESTORE_DB)
    if not ok:
        raise RuntimeError('Nie przywrócono bazy: uszkodzony przygotowany snapshot: '+str(why))
    kind=meta.get('kind','backup_restore')
    full=kind in {'installed_import','cloud_snapshot','data_snapshot'}
    if full and (not PENDING_IMPORT_DOCS.is_dir() or not PENDING_IMPORT_DRAFTS.is_dir()):
        raise RuntimeError('Niekompletny snapshot: brak przygotowanych dokumentów lub projektów. Dane nietknięte.')
    from rk_core.sync_atomic import commit_staged
    import rk_sync
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.rk_pending_stage_',dir=str(DATA_DIR)))
    try:
        staged_db=stage/'sprawnik.sqlite3'
        _sqlite_backup(PENDING_RESTORE_DB,staged_db)
        if kind=='cloud_snapshot':
            # Set Cloud state IN THE STAGED DB, before committing any files.
            with contextlib.closing(sqlite3.connect(staged_db,timeout=10)) as rawcon:
                with rawcon:
                    rawcon.execute("CREATE TABLE IF NOT EXISTS app_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
                    for key,value in {
                        'cloud_last_version':str(meta.get('cloud_version') or 0),
                        'cloud_last_sync':datetime.now().isoformat(timespec='seconds'),
                    }.items():
                        rawcon.execute("INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP",(key,value))
        managed=('dokumenty','projekty_pism') if full else ()
        if full:
            shutil.copytree(PENDING_IMPORT_DOCS,stage/'dokumenty',copy_function=shutil.copy2)
            shutil.copytree(PENDING_IMPORT_DRAFTS,stage/'projekty_pism',copy_function=shutil.copy2)
        backup=rk_sync.backup_destination(DATA_DIR,'przed_pending_restore')
        commit_staged(DATA_DIR,backup,staged_db,stage,managed,rk_sync._replace_dir,sqlite_integrity)
    except Exception as exc:
        log_event('Bezpieczne przywracanie snapshotu: '+str(exc),'ERROR')
        raise RuntimeError('Nie udało się przywrócić pełnego stanu. Sprawdź dziennik synchronizacji i kopię danych: '+str(exc)) from exc
    finally:
        shutil.rmtree(stage,ignore_errors=True)
    # Only after successful DB+directory commit may the pending data be discarded.
    PENDING_RESTORE_MARKER.unlink()
    PENDING_RESTORE_DB.unlink(missing_ok=True)
    shutil.rmtree(PENDING_IMPORT_DOCS,ignore_errors=True)
    shutil.rmtree(PENDING_IMPORT_DRAFTS,ignore_errors=True)
    if kind=='cloud_snapshot':
        message=f"Pobrano stan Cloud v{meta.get('cloud_version','?')}: {meta.get('source','serwer Cloud')}"
    elif kind=='data_snapshot':
        message=f"Przywrócono pełny snapshot: {meta.get('source','wybrany plik')}"
    elif kind=='installed_import':
        message=f"Zaimportowano dane z Installed: {meta.get('source','stara instalacja')}"
    else:
        message=f"Przywrócono backup: {meta.get('source','wybrana kopia')}"
    log_event(message,'WARNING')
    return message
'''


def patch_app(text: str) -> str:
    if MARKER in text:
        return text
    if text.count(VERSION) != 1:
        raise ValueError('Patch wymaga źródeł 0.4.0-dev2 po oficjalnym migratorze.')
    original_export = text[function_span(text,'create_data_snapshot_zip')[0]:function_span(text,'create_data_snapshot_zip')[1]]
    if "sc.execute(\"DELETE FROM user_sessions\")" not in original_export:
        raise ValueError('Eksport snapshotu został zmieniony; brak znanej kotwicy bezpieczeństwa.')
    insecure = '''        try:
            sc=sqlite3.connect(tmp)
            sc.execute("DELETE FROM user_sessions")
            sc.execute("DELETE FROM app_settings WHERE key IN ('backup_key_dpapi','backup_key_verifier','cloud_token')")
            sc.commit(); sc.close()
        except Exception as exc:
            log_event(f'Nie udało się oczyścić lokalnych sekretów w snapshot: {exc}','WARNING')'''
    secure = '''        # Fail closed: never export a snapshot if secret removal fails.
        # Closing the handle explicitly is essential for Windows file cleanup.
        with contextlib.closing(sqlite3.connect(tmp,timeout=15)) as sc:
            with sc:
                sc.execute("DELETE FROM user_sessions")
                sc.execute("DELETE FROM app_settings WHERE key IN ('backup_key_dpapi','backup_key_verifier','cloud_token')")'''
    changed_export = replace_once(original_export,insecure,secure,'sensitive snapshot sanitization')
    text=replace_function(text,'create_data_snapshot_zip',changed_export)
    old_restore=text[function_span(text,'apply_pending_restore_if_any')[0]:function_span(text,'apply_pending_restore_if_any')[1]]
    if 'os.replace(PENDING_RESTORE_DB,DB_PATH)' not in old_restore or 'shutil.copytree(PENDING_IMPORT_DOCS,FILES_DIR' not in old_restore:
        raise ValueError('Przywracanie snapshotu zmieniło strukturę; patch odmawia nieznanej wersji.')
    text=replace_function(text,'apply_pending_restore_if_any',ATOMIC_RESTORE)
    text=replace_once(text,VERSION,VERSION+'\n'+MARKER+' = True','audit patch version marker')
    compile(text,'app.py','exec')
    return text


def patch_cloud(text: str) -> str:
    if 'class _RKNoCloudRedirect(' in text:
        return text
    if 'def _request(req: urllib.request.Request, timeout: int=45)' not in text:
        raise ValueError('Nieznana wersja klienta Cloud.')
    cls = '''class _RKNoCloudRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward bearer credentials to a redirected URL."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CloudError('Cloud nie akceptuje przekierowań HTTP. Wskaż końcowy adres HTTPS serwera.')


'''
    text=replace_once(text,'def _request(req: urllib.request.Request, timeout: int=45)',cls+'def _request(req: urllib.request.Request, timeout: int=45)','cloud redirect guard')
    text=replace_once(text,'with urllib.request.urlopen(req,timeout=timeout) as r:',
        'with urllib.request.build_opener(_RKNoCloudRedirect()).open(req,timeout=timeout) as r:', 'cloud client request')
    compile(text,'rk_cloud.py','exec')
    return text


def patches(root: Path) -> dict[str, str]:
    changes={}
    for name,fix in [('app.py',patch_app),('rk_cloud.py',patch_cloud)]:
        path=root/name
        if not path.is_file():raise FileNotFoundError('Brak pliku źródłowego: '+name)
        before=path.read_text(encoding='utf-8')
        after=fix(before)
        if before!=after:
            changes[name]=after
    return changes


def apply(root: Path,dry_run=False,verify=False) -> str:
    root=root.resolve()
    if (root/'Data').is_file():raise ValueError('Data musi być katalogiem, nie plikiem.')
    expected=patches(root)
    if verify:
        if expected:
            raise ValueError('Patch nie jest zastosowany: '+', '.join(expected))
        if MARKER not in (root/'app.py').read_text(encoding='utf-8'):
            raise ValueError('Brak znacznika patcha w app.py')
        return 'VERIFIED: audited source patch applied.'
    if dry_run:
        return f'DRY RUN OK: {len(expected)} plików; żadne dane ani źródła nie zostały zmienione.'
    if not expected:
        return 'Patch RK 0.4.0-dev2 już zainstalowany. Bez zmian.'
    # Preserve originals BEFORE writing. No changes to Data, including backups.
    originals={name:(root/name).read_bytes() for name in expected}
    backup=root/'.rk_audit_patch_backup_040_dev2'
    if backup.exists():
        raise FileExistsError('Istnieje kopia poprzedniego patcha; niczego nie nadpisano: '+str(backup))
    backup.mkdir(parents=True,exist_ok=False)
    for name,body in originals.items():
        dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(body)
    (backup/MANIFEST).write_text(json.dumps({n:hashlib.sha256(b).hexdigest() for n,b in originals.items()},indent=2),encoding='utf-8')
    replaced=[]
    try:
        for name,body in expected.items():
            dst=root/name
            fd,tmp=tempfile.mkstemp(prefix='.rk_audit_',dir=str(dst.parent))
            try:
                with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
                    f.write(body);f.flush();os.fsync(f.fileno())
                os.replace(tmp,dst);replaced.append(name)
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
    except BaseException:
        for name in replaced:(root/name).write_bytes(originals[name])
        raise
    return 'PATCH OK: '+', '.join(sorted(replaced))+'; Data pozostaje bez zmian.'


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('repo',nargs='?',default='.')
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--verify',action='store_true')
    a=p.parse_args()
    try:print(apply(Path(a.repo),dry_run=a.dry_run,verify=a.verify))
    except Exception as exc:
        print('BŁĄD PATCH 040 DEV2:',exc)
        raise SystemExit(1)
