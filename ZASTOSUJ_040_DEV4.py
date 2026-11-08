#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RK 0.4.0-dev4 R1 — non-destructive source migration and functional hotfix.

Run on GitHub sources. Refuses unrecognized versions or mismatched anchors;
never opens or modifies Data. Makes backups and rolls back source writes on error.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

VERSION_OLD='VERSION = "0.4.0-dev3"'
VERSION_NEW='VERSION = "0.4.0-dev4"'
MARKER='RK_040_DEV4_REPAIR_20261108'
TARGETS=('app.py','rk_core/schema_version.py','TEST_ARCHITEKTURA_040.py',
         'TEST_STABILIZACJA_040_DEV2.py','RAPORT_JAKOSCI_040.py','AUDYT_I_TESTY_RK_040_DEV2.py',
         'rk_windows_version.txt')
REQUIRED=('rk_dev4.py','rk_dev4_core.py','rk_dev3.py','rk_dev3_core.py','rk_dev3_calendar.py','TEST_RK_DEV4.py')


def once(src,old,new,label):
    found=src.count(old)
    if found!=1:raise RuntimeError(f'{label}: oczekiwano 1 kotwicy, znaleziono {found}; źródła niezmienione')
    return src.replace(old,new,1)


def build(root:Path):
    for rel in (*TARGETS,*REQUIRED):
        if not (root/rel).is_file():raise RuntimeError('Brak wymaganego pliku '+rel)
    old={rel:(root/rel).read_text(encoding='utf-8') for rel in TARGETS}
    app=old['app.py']
    if VERSION_NEW in app:
        if MARKER not in app:raise RuntimeError('Dev4 bez znacznika aktualizacji; wymagana ręczna kontrola')
        if 'SCHEMA_VERSION = 332' not in old['rk_core/schema_version.py']:
            raise RuntimeError('Niekompletna instalacja schematu dev4')
        return {}
    if app.count(VERSION_OLD)!=1:raise RuntimeError('Wymagana aktualna wersja 0.4.0-dev3 R2')
    app=once(app,VERSION_OLD,VERSION_NEW+'\n'+MARKER+' = True','wersja')
    app=once(app,'from rk_dev3 import Dev3Mixin',
             'from rk_dev3 import Dev3Mixin\nfrom rk_dev4 import Dev4Mixin\nfrom rk_dev4_core import ensure_dev4_schema, action_log, vault_file_path', 'import dev4')
    app=once(app,'        ensure_dev3_schema(con)\n    start_worker(sys.modules[__name__])',
             '        ensure_dev3_schema(con)\n        ensure_dev4_schema(con)\n    start_worker(sys.modules[__name__])','migracja dev4')
    app=once(app,'class Handler(Dev3Mixin, CaseflowMixin,',
             'class Handler(Dev4Mixin, Dev3Mixin, CaseflowMixin,','mixin dev4')
    app=once(app,'            if self.dev3_get(path, qs): return',
             '            if self.dev4_get(path, qs): return\n            if self.dev3_get(path, qs): return','GET dev4')
    app=once(app,'            if self.dev3_post(path, fields, files): return',
             '            if self.dev4_post(path, fields, files): return\n            if self.dev3_post(path, fields, files): return','POST dev4')
    app=once(app,'        date(year,12,25), date(year,12,26),',
             '        date(year,12,24), date(year,12,25), date(year,12,26),','Wigilia dniem wolnym')
    app=once(app,'                            except OSError: pass\n        return out.getvalue()',
             '                            except OSError as exc:\n                                raise RuntimeError(f"Nie można wykonać kompletnej kopii: {fp}") from exc\n        return out.getvalue()', 'fail closed snapshot')
    # Prevent deleting the owner of encrypted files: hand ownership to the administrator
    # performing the deletion, rather than orphaning data or failing on foreign keys.
    app=once(app,'            con.execute("DELETE FROM users WHERE id=?",(uid,))',
             '''            # Vault files remain accessible after deleting their original owner.
            moved=con.execute("UPDATE dev3_vault_files SET owner_id=? WHERE owner_id=?",(me['id'],uid)).rowcount
            if moved:action_log(con,None,me['id'],'Przejęcie sejfu po usunięciu konta',
                                f'Użytkownik {uid}; dokumenty {moved}')
            con.execute("DELETE FROM users WHERE id=?",(uid,))''','transfer vault before user deletion')
    # During case removal a snapshot is created before any deletion. Remove only
    # validated encrypted blobs after DB commit; never erase the complete vault dir.
    app=once(app,"        author=self.current_author(f); folder=FILES_DIR/f\"sprawa_{cid}\"\n        with db() as con:",
             """        author=self.current_author(f); folder=FILES_DIR/f"sprawa_{cid}"
        with db() as con:
            vault_names=[r[0] for r in con.execute(
                'SELECT stored_name FROM dev3_vault_files WHERE case_id=?',(cid,))]""",'vault cleanup before cascade')
    app=once(app,'        if folder.exists():\n            try: shutil.rmtree(folder)',
             '''        for stored in vault_names:
            try:vault_file_path(FILES_DIR,stored).unlink(missing_ok=True)
            except (OSError,ValueError) as exc:log_app_exception(f'/case/{cid}/delete-vault',exc)
        if folder.exists():
            try: shutil.rmtree(folder)''','vault cleanup after commit')
    app=once(app,"                        if expected not in names: missing.append(expected)\n                finally:",
             """                        if expected not in names: missing.append(expected)
                    for v in test_con.execute('SELECT stored_name FROM dev3_vault_files'):
                        expected='dokumenty/_vault/'+v[0]
                        if expected not in names:missing.append(expected)
                finally:""",'restore check vault')
    old['app.py']=app
    for name,prev,new in (
        ('rk_core/schema_version.py','SCHEMA_VERSION = 331','SCHEMA_VERSION = 332'),
        ('TEST_ARCHITEKTURA_040.py',"self.assertIn('VERSION = \"0.4.0-dev3\"',app)","self.assertIn('VERSION = \"0.4.0-dev4\"',app)"),
        ('TEST_STABILIZACJA_040_DEV2.py','self.assertEqual(SCHEMA_VERSION,331)','self.assertEqual(SCHEMA_VERSION,332)'),
        ('RAPORT_JAKOSCI_040.py',"'version':'0.4.0-dev3'","'version':'0.4.0-dev4'"),
        ('AUDYT_I_TESTY_RK_040_DEV2.py',"'version':'0.4.0-dev3'","'version':'0.4.0-dev4'"),
    ):
        old[name]=once(old[name],prev,new,name)
    meta=old['rk_windows_version.txt']
    meta=once(meta,'filevers=(0, 4, 0, 3), prodvers=(0, 4, 0, 3)',
              'filevers=(0, 4, 0, 4), prodvers=(0, 4, 0, 4)','EXE version tuple')
    meta=once(meta,"StringStruct('FileVersion', '0.4.0.3')","StringStruct('FileVersion', '0.4.0.4')",'EXE file version')
    meta=once(meta,"StringStruct('ProductVersion', '0.4.0-dev3')","StringStruct('ProductVersion', '0.4.0-dev4')",'EXE product version')
    old['rk_windows_version.txt']=meta
    for name,src in old.items():
        if name.endswith('.py'):ast.parse(src,filename=name)
    return {rel:src for rel,src in old.items() if src!=(root/rel).read_text(encoding='utf8')}


def apply(root:Path,dry_run=False,verify=False):
    root=root.resolve(); out=build(root)
    if verify:
        if out:raise RuntimeError('Źródła nie zostały zaktualizowane: '+', '.join(out))
        return 'OK: dev4 — poprawka wdrożona'
    if dry_run:return f'DRY RUN: {len(out)} plików do modyfikacji, dane nietknięte'
    if not out:return 'RK dev4 już zastosowana; bez zmian'
    backup=root/'.rk_backup_before_040_dev4'
    if backup.exists():raise RuntimeError('Znaleziono wcześniejszą kopię .rk_backup_before_040_dev4; przerwano')
    backup.mkdir(parents=True,exist_ok=False)
    original={name:(root/name).read_bytes() for name in out}
    for name,blob in original.items():
        p=backup/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(blob)
    (backup/'manifest.json').write_text(json.dumps({n:hashlib.sha256(b).hexdigest() for n,b in original.items()},indent=2),'utf8')
    written=[]
    try:
        for name,source in out.items():
            target=root/name
            fd,temp=tempfile.mkstemp(dir=target.parent,prefix='.rk_dev4_')
            try:
                with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
                    f.write(source);f.flush();os.fsync(f.fileno())
                os.replace(temp,target)
                written.append(name)
            finally:
                if os.path.exists(temp):os.unlink(temp)
    except BaseException:
        for rel in written:(root/rel).write_bytes(original[rel])
        raise
    return f'RK dev4 — źródła zaktualizowane ({len(written)} plików); Data bez zmian'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repo',nargs='?',default='.')
    parser.add_argument('--dry-run',action='store_true');parser.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    try:print(apply(Path(args.repo),args.dry_run,args.verify))
    except Exception as exc:
        print('DEV4 ERROR:',exc);raise SystemExit(1)
