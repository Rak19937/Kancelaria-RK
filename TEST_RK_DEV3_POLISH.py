#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for dev3 R2: real UI methods against synthetic SQLite data.

No real user database, no court portal account, no network calls. Node test simulates
navigation interactions and verifies pin/unpin while mouse focus remains inside.
"""
from __future__ import annotations
import contextlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from TEST_RK_DEV3 import fixture_db
from rk_dev3 import Dev3Mixin
from rk_dev3_core import vault_store, vault_can_view, import_portal_csv


class Handler(Dev3Mixin):
    def __init__(self, con, user_id=1, role='admin', files_dir=None):
        self.con = con
        self.user={'id':user_id, 'role':role}
        self.html=''
        self.last_redirect=None
        self.errors=[]
        self.files_dir=files_dir or Path(tempfile.gettempdir())

    def _dev3_app(self):
        @contextlib.contextmanager
        def db():
            with self.con:
                yield self.con
        return SimpleNamespace(db=db, FILES_DIR=self.files_dir,
                               case_read_only=lambda con,case_id:False,
                               layout=lambda title,body,active='':body)
    def _dev3_me(self):return self.user
    def _dev3_admin(self):
        if self.user['role']=='admin':return True
        self._dev3_error('Administrator required',403);return False
    def _dev3_html(self,title,body,active=''):
        self.html=body
    def _dev3_error(self,exc,code=400):
        self.errors.append((str(exc),code))
    def send_error(self,code):
        self.errors.append(('HTTP',code))
    def redirect(self,url):self.last_redirect=url


class PolishTests(unittest.TestCase):
    def setUp(self):self.con=fixture_db()
    def tearDown(self):self.con.close()

    def test_timer_can_cancel_without_writing_time_and_shows_live_counter(self):
        h=Handler(self.con)
        h.dev3_start({'case_id':'10','description':'Analiza'})
        h.dev3_worktime_page()
        self.assertIn('data-rk-dev3-timer-start=',h.html)
        self.assertIn('/worktime/cancel',h.html)
        self.assertIn('Zatrzymaj i zapisz',h.html)
        h.dev3_cancel()
        self.assertEqual(h.last_redirect,'/worktime')
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM dev3_time_running').fetchone()[0],0)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM dev3_time_entries').fetchone()[0],0)
        with self.assertRaisesRegex(ValueError,'aktywnego stopera'):
            h.dev3_cancel()

    def test_vault_revoke_access_without_deleting_encrypted_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_id=vault_store(self.con,Path(tmp),10,1,'private.txt',b'SEKRET\x00','longstrongpassword!')
            self.con.execute('INSERT INTO dev3_vault_grants(file_id,user_id) VALUES(?,2)',(file_id,))
            owner=Handler(self.con,1,'user',Path(tmp))
            owner.dev3_vault_page()
            self.assertIn('/vault/%d/revoke'%file_id,owner.html)
            self.assertIn('Cofnij dostęp:',owner.html)
            other=Handler(self.con,2,'user',Path(tmp))
            other.dev3_vault_revoke(file_id,{'user_id':'2'})
            self.assertIn(('Brak uprawnień',403),other.errors)
            self.assertTrue(vault_can_view(self.con,file_id,2))
            owner.dev3_vault_revoke(file_id,{'user_id':'2'})
            self.assertFalse(vault_can_view(self.con,file_id,2))
            self.assertEqual(self.con.execute('SELECT COUNT(*) FROM dev3_vault_files').fetchone()[0],1)
            with self.assertRaisesRegex(ValueError,'właściciela'):
                owner.dev3_vault_revoke(file_id,{'user_id':'1'})

    def test_calendar_can_dismiss_pending_event_and_not_delete_appointments(self):
        self.con.execute('''INSERT INTO dev3_calendar_pending(provider,external_id,title,start_at,end_at,payload_hash)
                      VALUES('google','z1','Propozycja','2026-11-28T11:00:00+01:00','2026-11-28T12:00:00+01:00','hash')''')
        id_=self.con.execute('SELECT id FROM dev3_calendar_pending').fetchone()[0]
        h=Handler(self.con)
        h.dev3_calendar_page()
        self.assertIn('/calendar-sync/dismiss',h.html)
        h.dev3_calendar_dismiss({'pending_id':str(id_)})
        self.assertEqual(self.con.execute('SELECT status FROM dev3_calendar_pending').fetchone()[0],'dismissed')
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM case_appointments').fetchone()[0],1)
        with self.assertRaisesRegex(ValueError,'oczekującej'):
            h.dev3_calendar_dismiss({'pending_id':str(id_)})
        not_admin=Handler(self.con,2,'user')
        not_admin.dev3_calendar_dismiss({'pending_id':str(id_)})
        self.assertIn(('Administrator required',403),not_admin.errors)

    def test_portal_assignment_correction_and_undo(self):
        import_portal_csv(self.con,b'identyfikator;sygnatura;data;tytul\nr1;I C 10/26;2026-11-07;Postanowienie',1)
        id_=self.con.execute('SELECT id FROM dev3_portal_items').fetchone()[0]
        h=Handler(self.con)
        h.dev3_court_page();self.assertIn('Zatwierdź kontrolę',h.html)
        with self.assertRaisesRegex(ValueError,'Wybierz sprawę'):
            h.dev3_court_review(id_,{})
        h.dev3_court_review(id_,{'case_id':'10'})
        self.assertEqual(tuple(self.con.execute('SELECT reviewed,case_id FROM dev3_portal_items').fetchone()),(1,10))
        h.dev3_court_page();self.assertIn('Zmień przypisanie',h.html)
        h.dev3_court_review(id_,{'case_id':'11'})
        self.assertEqual(tuple(self.con.execute('SELECT reviewed,case_id FROM dev3_portal_items').fetchone()),(1,11))
        h.dev3_court_review(id_,{'action':'undo'})
        self.assertEqual(tuple(self.con.execute('SELECT reviewed,case_id FROM dev3_portal_items').fetchone()),(0,None))

    def test_production_files_have_valid_syntax_and_clean_nav_selectors(self):
        import ast
        root=Path(__file__).parent
        for file in ('rk_dev3.py','rk_dev3_core.py','rk_dev3_calendar.py'):
            ast.parse((root/file).read_text(encoding='utf-8'),filename=file)
        css=(root/'assets/rk_dev3_nav.css').read_text(encoding='utf-8')
        self.assertIn('.app > .sidebar.dev3-open',css)
        self.assertNotIn('.app > .sidebar:focus-within',css)
        self.assertNotIn('.app > .sidebar:hover',css)
        self.assertIn('@media (min-width:821px)',css)

    @unittest.skipUnless(shutil.which('node'),'Node.js unavailable')
    def test_navigation_clicks_in_node(self):
        root=Path(__file__).parent
        run=subprocess.run(['node',str(root/'TEST_NAV_DEV3_NODE.cjs')],cwd=root,timeout=20,
                           capture_output=True,text=True,encoding='utf8',errors='replace')
        self.assertEqual(run.returncode,0,run.stderr+'\n'+run.stdout)
        self.assertIn('OK: menu',run.stdout)


if __name__=='__main__':unittest.main(verbosity=2)
