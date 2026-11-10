#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DEV7 regression tests on synthetic databases and generated source fixtures."""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from rk_ux6 import delete_case_dependencies
from rk_dev7_stability import (
    check_case_form, preflight_case_delete, verify_backup_snapshot,
    assert_deleted_case_integrity, Dev7SafetyError)
from ZASTOSUJ_DEV7 import patch_app, patch_ux6, apply, verify, MARKER

ROOT=Path(__file__).resolve().parent


def fixture():
    con=sqlite3.connect(':memory:')
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('CREATE TABLE cases(id INTEGER PRIMARY KEY,title TEXT)')
    con.execute('CREATE TABLE tasks(id INTEGER PRIMARY KEY,case_id INTEGER REFERENCES cases(id) ON DELETE CASCADE)')
    con.execute("INSERT INTO cases(id,title) VALUES(1,'Usun'),(2,'Zachowaj')")
    con.execute('INSERT INTO tasks(id,case_id) VALUES(11,1),(22,2)')
    return con


def sample_zip(payload=b'SQLite format 3\x00testing'):
    contents={'sprawnik.sqlite3':payload,'dokumenty/sprawa_1/pismo.txt':b'Test file'}
    meta={'format':'RK-KANCELARIA-DATA-SNAPSHOT','version':1,
          'file_sha256':{k:hashlib.sha256(v).hexdigest() for k,v in contents.items()}}
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in contents.items():z.writestr(name,data)
        z.writestr('snapshot.json',json.dumps(meta).encode('utf-8'))
    return output.getvalue()


class CaseFormTests(unittest.TestCase):
    statuses={'active':'W toku','closed':'Zakończona'}
    def test_valid_case(self):
        self.assertTrue(check_case_form({'title':'Test','subject':'Zapłata','status':'active',
                                         'next_date':'2026-11-10'},self.statuses,new=True))
    def test_bad_date(self):
        with self.assertRaises(Dev7SafetyError):
            check_case_form({'title':'Test','status':'active','next_date':'2026-02-30'},self.statuses)
    def test_wrong_status(self):
        with self.assertRaises(Dev7SafetyError):
            check_case_form({'title':'Test','status':'closed-means-gone'},self.statuses)
    def test_empty_name(self):
        with self.assertRaises(Dev7SafetyError):
            check_case_form({'title':'  ','status':'active'},self.statuses)
    def test_missing_subject_new_only(self):
        with self.assertRaises(Dev7SafetyError):
            check_case_form({'title':'Test','status':'active'},self.statuses,new=True)
        self.assertTrue(check_case_form({'title':'Test','status':'active'},self.statuses,new=False))
    def test_missing_status_rejected(self):
        with self.assertRaises(Dev7SafetyError):
            check_case_form({'title':'Test','subject':'Zapłata'},self.statuses,new=True)
    def test_long_name(self):
        with self.assertRaises(Dev7SafetyError):
            check_case_form({'title':'x'*501,'status':'active'},self.statuses)


class DeleteSafetyTests(unittest.TestCase):
    def test_preflight_is_reversible(self):
        con=fixture()
        try:
            self.assertTrue(preflight_case_delete(con,1,delete_case_dependencies))
            self.assertEqual(con.execute('SELECT COUNT(*) FROM cases').fetchone()[0],2)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],2)
        finally:con.close()
    def test_restrict_blocks_and_rolls_back(self):
        con=fixture()
        try:
            con.execute('CREATE TABLE unrelated_proof(case_id INTEGER REFERENCES cases(id) ON DELETE RESTRICT)')
            con.execute('INSERT INTO unrelated_proof(case_id) VALUES(1)')
            with self.assertRaises(Dev7SafetyError) as cm:
                preflight_case_delete(con,1,delete_case_dependencies)
            self.assertIn('unrelated_proof',str(cm.exception))
            self.assertIsNotNone(con.execute('SELECT * FROM cases WHERE id=1').fetchone())
            self.assertEqual(con.execute('SELECT COUNT(*) FROM tasks WHERE case_id=1').fetchone()[0],1)
        finally:con.close()
    def test_foreign_keys_must_be_on(self):
        con=fixture()
        con.commit();con.execute('PRAGMA foreign_keys=OFF')
        with self.assertRaises(Dev7SafetyError):preflight_case_delete(con,1,delete_case_dependencies)
        con.close()
    def test_real_delete_integrity(self):
        con=fixture()
        try:
            with con:
                delete_case_dependencies(con,1)
                assert_deleted_case_integrity(con,1)
            self.assertEqual([r[0] for r in con.execute('SELECT id FROM cases')],[2])
            self.assertEqual([r[0] for r in con.execute('SELECT id FROM tasks')],[22])
        finally:con.close()
    def test_undeleted_case_fails(self):
        con=fixture()
        try:
            with self.assertRaises(Dev7SafetyError):assert_deleted_case_integrity(con,1)
        finally:con.close()


class SnapshotTests(unittest.TestCase):
    def test_valid_backup(self):
        with tempfile.TemporaryDirectory() as td:
            data=sample_zip();p=Path(td)/'snapshot.zip';p.write_bytes(data)
            self.assertTrue(verify_backup_snapshot(p,data))
    def test_short_write_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            data=sample_zip();p=Path(td)/'snapshot.zip';p.write_bytes(data[:-1])
            with self.assertRaises(Dev7SafetyError):verify_backup_snapshot(p,data)
    def test_wrong_manifest_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            raw=io.BytesIO()
            with zipfile.ZipFile(raw,'w') as z:
                z.writestr('sprawnik.sqlite3',b'SQLite format 3\x00')
                z.writestr('snapshot.json',json.dumps({'format':'RK-KANCELARIA-DATA-SNAPSHOT','file_sha256':{}}))
            p=Path(td)/'snapshot.zip';p.write_bytes(raw.getvalue())
            with self.assertRaises(Dev7SafetyError):verify_backup_snapshot(p,raw.getvalue())
    def test_content_tampering_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            data=sample_zip();p=Path(td)/'snapshot.zip';p.write_bytes(data)
            fake=data[:-12]+b'XXXXXXXXXXXX'
            with self.assertRaises(Dev7SafetyError):verify_backup_snapshot(p,fake)


def app_fixture():
    """Minimalny poprawny Python z rzeczywistymi kotwicami zmian dev7."""
    return """from rk_ux6 import Ux6Mixin, ensure_ux6_schema, delete_case_dependencies, choice_exists as ux6_choice_exists
APP_NAME = "RK KANCELARIA"
VERSION = "0.4.0-dev5"
RK_UX6_20261108 = True
STATUS_LABELS = {'active':'W toku','closed':'Zakończona'}

class Handler:
    def case_create(self, f):
        pass

    def case_update(self,cid,f):
        pass

    def case_delete(self,cid,f):
        if not self.require_admin(): return
        if (f.get('confirmation','') or '').strip()!='USUŃ' or f.get('acknowledge')!='1':
            return self.case_delete_confirm(cid,'Nie potwierdzono usunięcia. Wpisz dokładnie „USUŃ” i zaznacz pole potwierdzenia.')
        try:
            raw,snapshot_name=create_data_snapshot_zip()
        except (OSError,RuntimeError,sqlite3.Error) as exc:
            log_app_exception(f'/case/{cid}/snapshot',exc)
            return self.case_delete_confirm(cid,str(exc))
        backup_dir=DATA_DIR/'backup_przed_usunieciem_sprawy'
        backup_dir.mkdir(parents=True,exist_ok=True)
        backup_path=backup_dir/f"sprawa_{cid}_{snapshot_name}"
        try:
            atomic_write_bytes(backup_path,raw)
            if not backup_path.is_file() or backup_path.stat().st_size!=len(raw):
                raise RuntimeError('Zapis kopii nie jest kompletny.')
        except (OSError,RuntimeError) as exc:
            return self.case_delete_confirm(cid,str(exc))
        try:
            with db() as con:
                delete_case_dependencies(con,cid)
        except (sqlite3.Error,ValueError) as exc:
            return self.case_delete_confirm(cid,str(exc))

    def case_pin_toggle(self,cid,f):
        pass

    def do_POST(self):
        self.send_html('Nie udało się otworzyć tej części programu. Twoje zapisane dane nie zostały usunięte.')

    def setup_page(self):
        pass
"""


class InstallerTests(unittest.TestCase):
    def test_patch_compiles_real_anchors(self):
        transformed=patch_app(app_fixture())
        self.assertIn(MARKER,transformed)
        self.assertIn('assert_deleted_case_integrity(con,cid)',transformed)
        self.assertEqual(patch_app(transformed),transformed)

    def test_dry_run_and_reapply_never_touch_data(self):
        import shutil
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'app.py').write_text(app_fixture(),encoding='utf8')
            shutil.copy(ROOT/'rk_ux6.py',root/'rk_ux6.py')
            shutil.copy(ROOT/'rk_dev7_stability.py',root/'rk_dev7_stability.py')
            (root/'Data').mkdir()
            (root/'Data'/'client.sqlite3').write_bytes(b'SECRET-DO-NOT-TOUCH')
            before=(root/'app.py').read_bytes()
            self.assertIn('DRY RUN',apply(root,True))
            self.assertEqual((root/'app.py').read_bytes(),before)
            self.assertIn('zweryfikowane',apply(root,False))
            self.assertIn('zainstalowano',apply(root,False))
            self.assertEqual((root/'Data'/'client.sqlite3').read_bytes(),b'SECRET-DO-NOT-TOUCH')
            self.assertTrue((root/'.rk_backup_before_dev7'/'app.py').is_file())

    def test_calendar_filter(self):
        code=(ROOT/'rk_ux6.py').read_text('utf-8')
        patched=patch_ux6(code)
        self.assertIn("WHERE p.appointment_date=? AND p.status='planned'",patched)
        self.assertEqual(patch_ux6(patched),patched)
    def test_bad_app_refuses_change(self):
        with self.assertRaises(RuntimeError):patch_app('def x():pass\n')
    def test_installer_no_data_touch(self):
        script=(ROOT/'ZASTOSUJ_DEV7.py').read_text('utf-8')
        self.assertIn("FILES=('app.py','rk_ux6.py')",script)
        self.assertNotIn("root/'Data'",script)
        self.assertNotIn('shutil.rmtree',script)
    def test_workflow_has_guards(self):
        workflow=(ROOT/'.github/workflows/aktualizacja-dev5.yml').read_text('utf-8')
        if 'ZASTOSUJ_DEV7.py' not in workflow:
            self.skipTest('Workflow DEV7 wgrywany jako ostatni.')
        for item in ('ZASTOSUJ_DEV7.py','TEST_RK_DEV7.py','AUDYT_I_TESTY_RK_040_DEV2.py',
                     'RK_KANCELARIA_PORTABLE.spec'):
            self.assertIn(item,workflow)
        for line in workflow.splitlines():
            if 'git add --' in line:self.assertNotIn('.github/workflows',line)


if __name__=='__main__':unittest.main(verbosity=2)
