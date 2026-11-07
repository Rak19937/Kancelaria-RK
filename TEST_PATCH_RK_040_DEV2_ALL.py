#!/usr/bin/env python3
"""Independent regression tests for the consolidated 0.4.0-dev2 patch.

All database tests use new temporary SQLite files, never a user's Data.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace, ModuleType
from unittest.mock import patch
import uuid
import ast

import PATCH_RK_040_DEV2_ALL as fix

ROOT=Path(__file__).resolve().parent

BASE_APP = '''from __future__ import annotations
VERSION = "0.4.0-dev2"

def apply_pending_restore_if_any() -> str:
    if not PENDING_RESTORE_MARKER.exists():return ''
    os.replace(PENDING_RESTORE_DB,DB_PATH)
    if True:
        shutil.copytree(PENDING_IMPORT_DOCS,FILES_DIR)
    return ''

def create_data_snapshot_zip() -> tuple[bytes,str]:
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    tmp=DATA_DIR/f'.snapshot_{uuid.uuid4().hex}.sqlite3'
    try:
        _sqlite_backup(DB_PATH,tmp)
        # Full snapshot sanitizes local secrets before upload.
        try:
            sc=sqlite3.connect(tmp)
            sc.execute("DELETE FROM user_sessions")
            sc.execute("DELETE FROM app_settings WHERE key IN ('backup_key_dpapi','backup_key_verifier','cloud_token')")
            sc.commit(); sc.close()
        except Exception as exc:
            log_event(f'Nie udało się oczyścić lokalnych sekretów w snapshot: {exc}','WARNING')
        ok,why=sqlite_integrity(tmp)
        if not ok:
            raise RuntimeError(f'Kopia bazy nie przeszła quick_check: {why}')
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            z.write(tmp,'sprawnik.sqlite3')
            meta={
                'format':'RK-KANCELARIA-DATA-SNAPSHOT','version':1,'app_version':VERSION,
                'schema_version':SCHEMA_VERSION,'created_at':datetime.now().isoformat(timespec='seconds')
            }
            z.writestr('snapshot.json',json.dumps(meta,ensure_ascii=False,indent=2))
            for root,prefix in ((FILES_DIR,'dokumenty'),(DRAFTS_DIR,'projekty_pism')):
                if root.exists():
                    for fp in root.rglob('*'):
                        if fp.is_file():
                            try: z.write(fp,f"{prefix}/{fp.relative_to(root).as_posix()}")
                            except OSError: pass
        return out.getvalue(),f'RK_KANCELARIA_snapshot_{stamp}.zip'
    finally:
        try: tmp.unlink(missing_ok=True)
        except OSError: pass
'''

BASE_CLOUD='''import urllib.error
import urllib.parse
import urllib.request
class CloudError(RuntimeError):pass
def _request(req: urllib.request.Request, timeout: int=45) -> tuple[bytes,dict[str,str],int]:
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:
            return r.read(),dict(r.headers.items()),int(r.status)
    except urllib.error.HTTPError as exc:
        raise CloudError(str(exc))
'''


def sqlite_backup(src:Path,dst:Path):
    dst.parent.mkdir(parents=True,exist_ok=True)
    with contextlib.closing(sqlite3.connect(src)) as a,contextlib.closing(sqlite3.connect(dst)) as b:
        a.backup(b)


def integrity(db:Path):
    try:
        with contextlib.closing(sqlite3.connect(db)) as con:
            return (con.execute('PRAGMA quick_check').fetchone()[0]=='ok','')
    except Exception as exc:return False,str(exc)


class CoreTests(unittest.TestCase):
    def test_installer_patch_is_idempotent_and_unexpected_source_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'app.py').write_text(BASE_APP,encoding='utf-8')
            (root/'rk_cloud.py').write_text(BASE_CLOUD,encoding='utf-8')
            data=root/'Data';data.mkdir();(data/'private.dat').write_bytes(b'ALWAYS-PRESERVE')
            self.assertIn('DRY RUN OK',fix.apply(root,dry_run=True))
            self.assertEqual((root/'app.py').read_text(),BASE_APP)
            self.assertIn('PATCH OK',fix.apply(root))
            self.assertIn('VERIFIED',fix.apply(root,verify=True))
            self.assertIn('już zainstalowany',fix.apply(root))
            self.assertEqual((data/'private.dat').read_bytes(),b'ALWAYS-PRESERVE')
            self.assertIn(fix.MARKER,(root/'app.py').read_text())
            self.assertTrue((root/'.rk_audit_patch_backup_040_dev2/app.py').is_file())
            (root/'app.py').write_text('VERSION = "wrong"\n',encoding='utf-8')
            with self.assertRaises(ValueError):fix.apply(root,dry_run=True)

    def test_cloud_rejects_cross_site_redirect_without_network(self):
        module=ModuleType('cloud_test')
        exec(fix.patch_cloud(BASE_CLOUD),module.__dict__)
        obj=module._RKNoCloudRedirect()
        req=module.urllib.request.Request('https://office.example/api',headers={'Authorization':'Bearer private'})
        with self.assertRaisesRegex(module.CloudError,'przekierowań'):
            obj.redirect_request(req,None,302,'Redirect',{},'https://evil.example/')

    def test_snapshot_never_exports_cloud_tokens_or_sessions(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);db=root/'sprawnik.sqlite3'
            with contextlib.closing(sqlite3.connect(db)) as con:
                con.executescript('''CREATE TABLE user_sessions(token TEXT);
                  CREATE TABLE app_settings(key TEXT PRIMARY KEY,value TEXT,updated_at TEXT);
                  INSERT INTO user_sessions VALUES('session-private');
                  INSERT INTO app_settings(key,value) VALUES('cloud_token','bearer-private'),('some-setting','safe');''')
                con.commit()
            env=dict(DATA_DIR=root,DB_PATH=db,FILES_DIR=root/'dokumenty',DRAFTS_DIR=root/'projekty_pism',
                     _sqlite_backup=sqlite_backup,sqlite_integrity=integrity,VERSION='0.4.0-dev2',SCHEMA_VERSION=330,
                     datetime=datetime,uuid=uuid,sqlite3=sqlite3,contextlib=contextlib,io=io,zipfile=zipfile,
                     json=json,os=os,log_event=lambda *args:None)
            changed=fix.patch_app(BASE_APP)
            _,span_end=fix.function_span(changed,'create_data_snapshot_zip')
            span_start,_=fix.function_span(changed,'create_data_snapshot_zip')
            exec(changed[span_start:span_end],env)
            zipped,_=env['create_data_snapshot_zip']()
            with zipfile.ZipFile(io.BytesIO(zipped)) as z:
                restored=root/'exported.sqlite3';restored.write_bytes(z.read('sprawnik.sqlite3'))
            with contextlib.closing(sqlite3.connect(restored)) as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM user_sessions').fetchone()[0],0)
                self.assertEqual(con.execute("SELECT COUNT(*) FROM app_settings WHERE key='cloud_token'").fetchone()[0],0)
                self.assertEqual(con.execute("SELECT value FROM app_settings WHERE key='some-setting'").fetchone()[0],'safe')
            # Missing secret tables must ABORT, not create a potentially unsafe backup.
            bad=root/'bad.sqlite3'
            with contextlib.closing(sqlite3.connect(bad)) as con:
                con.execute('CREATE TABLE irrelevant(id INT)');con.commit()
            env['DB_PATH']=bad
            with self.assertRaises(sqlite3.OperationalError):env['create_data_snapshot_zip']()


class RestoreTests(unittest.TestCase):
    def test_full_restore_commits_database_and_directories_together(self):
        self.restore_case(False)

    def test_interrupted_restore_rolls_back_database_and_directories(self):
        self.restore_case(True)

    def restore_case(self,inject_error:bool):
        # Exercising the real journal + restore function against synthetic SQLite.
        from rk_core.sync_atomic import pending_sync_journal
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);data=root/'Data';data.mkdir();pending=data/'pending';pending.mkdir()
            live=data/'sprawnik.sqlite3';newdb=pending/'sprawnik_restore.sqlite3'
            for db,val in [(live,'OLD'),(newdb,'NEW')]:
                with contextlib.closing(sqlite3.connect(db)) as con:
                    con.execute('CREATE TABLE content(value TEXT)')
                    con.execute('INSERT INTO content VALUES (?)',(val,));con.commit()
            doc=data/'dokumenty';draft=data/'projekty_pism';doc.mkdir();draft.mkdir()
            (doc/'old.txt').write_text('old doc');(draft/'old.txt').write_text('old draft')
            ndoc=pending/'import_dokumenty';ndraft=pending/'import_projekty_pism'
            ndoc.mkdir();ndraft.mkdir()
            (ndoc/'new.txt').write_text('new doc');(ndraft/'new.txt').write_text('new draft')
            marker=pending/'restore.json';marker.write_text(json.dumps({'kind':'data_snapshot','source':'synthetic'}),encoding='utf-8')
            # rk_sync dummy delegates backup and swap to real source operations,
            # with optional crash injection after the first directory mutation.
            def backup_destination(dest,label):
                b=dest/'backup_synchronizacji'/'snapshot';b.mkdir(parents=True)
                sqlite_backup(dest/'sprawnik.sqlite3',b/'sprawnik.sqlite3')
                for name in ['dokumenty','projekty_pism']:
                    if (dest/name).is_dir():shutil.copytree(dest/name,b/name)
                return b
            count=[0]
            def replace_dir(src,dst):
                count[0]+=1
                if inject_error and count[0]==2:
                    raise OSError('Testowa awaria po skopiowaniu dokumentów')
                if dst.exists():shutil.rmtree(dst)
                os.replace(src,dst)
            dummy=ModuleType('rk_sync');dummy.backup_destination=backup_destination;dummy._replace_dir=replace_dir
            ns=dict(DATA_DIR=data,DB_PATH=live,FILES_DIR=doc,DRAFTS_DIR=draft,
                    PENDING_RESTORE_DIR=pending,PENDING_RESTORE_MARKER=marker,PENDING_RESTORE_DB=newdb,
                    PENDING_IMPORT_DOCS=ndoc,PENDING_IMPORT_DRAFTS=ndraft,RECOVERY_DIR=data/'backup_recovery',
                    sqlite_integrity=integrity,_sqlite_backup=sqlite_backup,pending_sync_journal=pending_sync_journal,
                    log_event=lambda *args:None,shutil=shutil,Path=Path,tempfile=tempfile,sqlite3=sqlite3,
                    contextlib=contextlib,json=json,datetime=datetime,os=os)
            src=fix.patch_app(BASE_APP)
            a,b=fix.function_span(src,'apply_pending_restore_if_any')
            exec(src[a:b],ns)
            with patch.dict(sys.modules,{'rk_sync':dummy}):
                if inject_error:
                    with self.assertRaisesRegex(RuntimeError,'Nie udało się przywrócić'):
                        ns['apply_pending_restore_if_any']()
                else:
                    output=ns['apply_pending_restore_if_any']()
                    self.assertIn('Przywrócono',output)
            with contextlib.closing(sqlite3.connect(live)) as con:
                value=con.execute('SELECT value FROM content').fetchone()[0]
                self.assertEqual(value,'OLD' if inject_error else 'NEW')
            self.assertTrue(((doc/'old.txt') if inject_error else (doc/'new.txt')).is_file())
            self.assertTrue(((draft/'old.txt') if inject_error else (draft/'new.txt')).is_file())
            self.assertEqual(marker.exists(),inject_error)
            self.assertIsNone(pending_sync_journal(data))


if __name__=='__main__':unittest.main(verbosity=2)
