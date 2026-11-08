#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for dev4: synthetic SQLite + temporary files; no user data/network."""
from __future__ import annotations
import contextlib
import shutil
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from TEST_RK_DEV3 import fixture_db
from rk_dev3_core import start_timer,stop_timer,add_manual_time,time_csv,import_portal_csv,vault_store,decrypt_vault
from rk_dev3_calendar import publish_appointment,pull_proposals,CalendarSyncError
from rk_dev4_core import ensure_dev4_schema,void_time,update_time,vault_rotate,vault_delete,vault_file_path
from ZASTOSUJ_040_DEV4 import apply
from rk_dev4 import Dev4Mixin
from TEST_RK_DEV3_POLISH import Handler as MockDev3Handler

TZ=ZoneInfo('Europe/Warsaw')


class Dev4CoreTests(unittest.TestCase):
    def setUp(self):self.con=fixture_db();ensure_dev4_schema(self.con)
    def tearDown(self):self.con.close()

    def test_time_after_polish_midnight_not_previous_utc_date(self):
        now=datetime(2026,11,8,0,30,tzinfo=TZ)
        start_timer(self.con,1,10,'Nocny dyżur',now.astimezone(timezone.utc)-timedelta(minutes=10))
        stop_timer(self.con,1,10000,True,now.astimezone(timezone.utc))
        row=self.con.execute('SELECT activity_date,minutes FROM dev3_time_entries').fetchone()
        self.assertEqual(tuple(row),('2026-11-08',10))

    def test_timer_over_24h_saves_all_minutes_in_bounded_rows(self):
        start=datetime(2026,11,5,10,30,tzinfo=TZ)
        end=start+timedelta(hours=27,minutes=5)
        start_timer(self.con,1,10,'Długi dyżur',start)
        stop_timer(self.con,1,10000,True,end)
        entries=self.con.execute('SELECT activity_date,minutes FROM dev3_time_entries ORDER BY id').fetchall()
        self.assertGreaterEqual(len(entries),2)
        self.assertEqual(sum(r['minutes'] for r in entries),1625)
        self.assertTrue(all(1<=r['minutes']<=1440 for r in entries))
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM dev3_time_running').fetchone()[0],0)

    def test_bad_clock_does_not_discard_timer(self):
        start=datetime(2026,11,8,10,tzinfo=TZ)
        start_timer(self.con,1,10,'Test',start)
        with self.assertRaises(ValueError):stop_timer(self.con,1,0,True,start-timedelta(minutes=1))
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM dev3_time_running').fetchone()[0],1)

    def test_time_correction_history_and_void_csv(self):
        eid=add_manual_time(self.con,10,1,'2026-11-08',80,'Opis',25000,True)
        update_time(self.con,eid,1,'2026-11-09',42,'Zmiana',10000,False)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM dev4_time_corrections').fetchone()[0],1)
        self.assertIn('Zmiana',time_csv(self.con).decode('utf8'))
        void_time(self.con,eid,1)
        self.assertNotIn('Zmiana',time_csv(self.con).decode('utf8'))
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM dev3_time_entries').fetchone()[0],1)
        with self.assertRaises(ValueError):update_time(self.con,eid,1,'2026-11-08',60,'',0,False)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM dev4_action_log').fetchone()[0],2)

    def test_vault_rotation_fail_safe_and_deletion(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);fid=vault_store(self.con,root,10,1,'priv.txt',b'Sekret', 'previous-password-1')
            name=self.con.execute('SELECT stored_name FROM dev3_vault_files WHERE id=?',(fid,)).fetchone()[0]
            target=vault_file_path(root,name)
            old=target.read_bytes()
            with self.assertRaises(ValueError):vault_rotate(self.con,root,fid,True,'wrong-password','new-secret-password')
            self.assertEqual(target.read_bytes(),old)
            vault_rotate(self.con,root,fid,True,'previous-password-1','new-secret-password')
            self.assertNotEqual(target.read_bytes(),old)
            self.assertEqual(decrypt_vault(target.read_bytes(),'new-secret-password'),b'Sekret')
            vault_delete(self.con,root,fid,True)
            self.assertEqual(self.con.execute('SELECT COUNT(*) FROM dev3_vault_files').fetchone()[0],0)
            target.unlink()

    def test_portal_second_import_updates_pending_but_not_reviewed(self):
        raw=lambda title:('identyfikator;sygnatura;data;tytul\nr;I C 10/26;2026-11-08;'+title).encode()
        self.assertEqual(import_portal_csv(self.con,raw('Start'),1),(1,0))
        self.assertEqual(import_portal_csv(self.con,raw('Poprawione'),1),(0,1))
        self.assertEqual(self.con.execute('SELECT document_title FROM dev3_portal_items').fetchone()[0],'Poprawione')
        self.con.execute('UPDATE dev3_portal_items SET reviewed=1')
        self.assertEqual(import_portal_csv(self.con,raw('Zmienione po zatwierdzeniu'),1),(0,1))
        self.assertEqual(self.con.execute('SELECT document_title FROM dev3_portal_items').fetchone()[0],'Poprawione')

    def test_calendar_explicit_duration_and_overflow_error(self):
        calls=[]
        def fake(url,token,method='GET',body=None,etag=None):calls.append(body);return {'id':'x-1','etag':'e'}
        with patch('rk_dev3_calendar._api',side_effect=fake):
            publish_appointment(self.con,'google',7,'fake',False,105)
        self.assertEqual(calls[0]['end']['dateTime'],'2026-11-22T12:15:00')
        with self.assertRaises(CalendarSyncError):publish_appointment(self.con,'google',7,'fake',False,1800)

    def test_schema_twice(self):
        ensure_dev4_schema(self.con)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM dev4_time_voids').fetchone()[0],0)


class Dev4UiTests(unittest.TestCase):
    def setUp(self):self.con=fixture_db();ensure_dev4_schema(self.con)
    def tearDown(self):self.con.close()

    def handler(self,user_id=1,role='admin',folder=None):
        class DemoHandler(Dev4Mixin,MockDev3Handler):pass
        return DemoHandler(self.con,user_id,role,folder)

    def test_edit_and_void_endpoints_keep_history(self):
        ident=add_manual_time(self.con,10,1,'2026-11-08',30,'Czynność',6000,True)
        h=self.handler()
        h.dev4_time_edit_page(ident)
        self.assertIn('Korekta czasu',h.html)
        h.dev4_time_change(ident,'update',{'day':'2026-11-09','minutes':'50',
            'description':'Po korekcie','rate':'100,00','billable':'1'})
        self.assertEqual(h.last_redirect,'/worktime')
        self.assertEqual(self.con.execute('SELECT minutes FROM dev3_time_entries').fetchone()[0],50)
        h.dev4_time_change(ident,'delete',{})
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM dev4_time_voids').fetchone()[0],1)
        other=self.handler(user_id=2,role='user')
        with self.assertRaises(ValueError):other.dev4_time_change(ident,'update',{'minutes':'42'})

    def test_vault_remove_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as td:
            ident=vault_store(self.con,Path(td),10,1,'file.pdf',b'Encrypted','a-super-long-passphrase')
            self.con.commit()
            h=self.handler(folder=Path(td))
            with self.assertRaises(ValueError):h.dev4_vault_change(ident,'delete',{'confirmation':'X'})
            self.assertEqual(self.con.execute('SELECT COUNT(*) FROM dev3_vault_files').fetchone()[0],1)
            h.dev4_vault_change(ident,'delete',{'confirmation':'USUŃ'})
            self.assertEqual(self.con.execute('SELECT COUNT(*) FROM dev3_vault_files').fetchone()[0],0)
            self.assertEqual(list((Path(td)/'_vault').iterdir()),[])


class InstallerTests(unittest.TestCase):
    def make_fixture(self,root):
        app='''from rk_dev3 import Dev3Mixin
from rk_dev3_core import ensure_dev3_schema
VERSION = "0.4.0-dev3"

class CaseflowMixin:pass
class Handler(Dev3Mixin, CaseflowMixin,object):
    def do_GET(self):
        if True:
            if self.dev3_get(path, qs): return
    def do_POST(self):
        if True:
            if self.dev3_post(path, fields, files): return

def init_db():
    with db() as con:
        ensure_dev3_schema(con)
    start_worker(sys.modules[__name__])

def holidays(year):
    return {
        date(year,12,25), date(year,12,26),
    }

def snap():
        for fp in files:
                            try: z.write(fp,'f')
                            except OSError: pass
        return out.getvalue()

def user_delete():
    with db() as con:
            con.execute("DELETE FROM users WHERE id=?",(uid,))

def case_delete():
        author=self.current_author(f); folder=FILES_DIR/f"sprawa_{cid}"
        with db() as con:
            immutable_audit(con,None,'case',cid,'Trwale usunięto sprawę','test',author)
            con.execute("DELETE FROM cases WHERE id=?",(cid,))
        if folder.exists():
            try: shutil.rmtree(folder)
            except Exception: pass

def recovery_test_restore():
                try:
                    for d in test_con.execute("SELECT case_id,stored_name FROM documents WHERE stored_name<>''"):
                        expected=f"dokumenty/sprawa_{d['case_id']}/{d['stored_name']}"
                        if expected not in names: missing.append(expected)
                finally:
                    test_con.close()
'''
        spec={
            'app.py':app,
            'rk_core/schema_version.py':'SCHEMA_VERSION = 331\n',
            'TEST_ARCHITEKTURA_040.py':"def t(self, app):\n    self.assertIn('VERSION = \"0.4.0-dev3\"',app)\n",
            'TEST_STABILIZACJA_040_DEV2.py':'def t(self):\n    self.assertEqual(SCHEMA_VERSION,331)\n',
            'RAPORT_JAKOSCI_040.py':"report={'version':'0.4.0-dev3'}\n",
            'AUDYT_I_TESTY_RK_040_DEV2.py':"report={'version':'0.4.0-dev3'}\n",
            'rk_windows_version.txt':"filevers=(0, 4, 0, 3), prodvers=(0, 4, 0, 3)\nStringStruct('FileVersion', '0.4.0.3')\nStringStruct('ProductVersion', '0.4.0-dev3')\n",
        }
        for name,s in spec.items():
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(s,'utf8')
        for name in ('rk_dev4.py','rk_dev4_core.py','rk_dev3.py','rk_dev3_core.py','rk_dev3_calendar.py','TEST_RK_DEV4.py'):
            shutil.copy2(Path(__file__).parent/name,root/name)
        (root/'Data').mkdir();(root/'Data'/'sprawnik.sqlite3').write_bytes(b'PROTECTED')

    def test_installer_is_idempotent_and_never_touches_data(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.make_fixture(root)
            self.assertIn('DRY RUN',apply(root,dry_run=True))
            self.assertIn('źródła zaktualizowane',apply(root))
            self.assertIn('już zastosowana',apply(root))
            self.assertIn('wdrożona',apply(root,verify=True))
            self.assertEqual((root/'Data'/'sprawnik.sqlite3').read_bytes(),b'PROTECTED')
            src=(root/'app.py').read_text()
            for fragment in ('Dev4Mixin','date(year,12,24)','ensure_dev4_schema(con)','vault_names','dev4_post','Nie można wykonać kompletnej kopii'):
                self.assertIn(fragment,src)
            self.assertTrue((root/'.rk_backup_before_040_dev4/app.py').is_file())

    def test_unrecognized_version_is_rejected_without_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.make_fixture(root)
            app=root/'app.py';app.write_text(app.read_text().replace('0.4.0-dev3','0.4.0-dev7'),'utf8')
            with self.assertRaises(RuntimeError):apply(root)
            self.assertFalse((root/'.rk_backup_before_040_dev4').exists())
            self.assertEqual((root/'Data'/'sprawnik.sqlite3').read_bytes(),b'PROTECTED')

if __name__=='__main__':unittest.main(verbosity=2)
