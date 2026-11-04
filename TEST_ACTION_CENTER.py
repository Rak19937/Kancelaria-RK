# -*- coding: utf-8 -*-
"""Testy bez prawdziwej bazy użytkownika; obsługa decyzji i bezpieczeństwo terminów."""
import contextlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rk_action_center import (ActionCenterMixin, ensure_action_center_schema,
                              suggest_actions, source_fingerprint, valid_iso_date)
from ZASTOSUJ_OBIEG import apply_app


class AppStub:
    def __init__(self, root):
        self.DRAFTS_DIR = root/'projekty_pism'
        self.FILES_DIR = root/'dokumenty'
        self.DRAFTS_DIR.mkdir()
        self.FILES_DIR.mkdir()
        self.con = sqlite3.connect(':memory:', isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self.con.executescript('''
        PRAGMA foreign_keys=ON;
        CREATE TABLE cases(id INTEGER PRIMARY KEY,title TEXT,signature TEXT);
        CREATE TABLE documents(id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT,stored_name TEXT,
          original_name TEXT,file_hash TEXT DEFAULT '',extracted_text TEXT DEFAULT '',
          indexed_at TEXT DEFAULT '',ocr_used INTEGER DEFAULT 0,ocr_status TEXT DEFAULT '',ocr_language TEXT DEFAULT '');
        CREATE TABLE writing_projects(id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT,
          stored_name TEXT DEFAULT '',original_name TEXT DEFAULT '',updated_at TEXT DEFAULT '',content TEXT DEFAULT '');
        CREATE TABLE inbox_items(id INTEGER PRIMARY KEY,original_name TEXT,ocr_status TEXT,created_at TEXT,status TEXT);
        CREATE TABLE tasks(id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT,due_date TEXT,status TEXT,
          priority TEXT,depends_on TEXT,notes TEXT,task_type TEXT,created_by TEXT,updated_by TEXT,
          deadline_base_date TEXT,deadline_rule TEXT,deadline_source TEXT,deadline_manual INTEGER);
        INSERT INTO cases(id,title,signature) VALUES(3,'Sprawa testowa','I C 12/26');
        INSERT INTO documents(id,case_id,title,stored_name,original_name,file_hash,extracted_text)
          VALUES(11,3,'Postanowienie','postanowienie.docx','postanowienie.docx','hash123',
          'Sąd zobowiązuje do przedłożenia dokumentów w terminie 14 dni od doręczenia postanowienia.');
        INSERT INTO writing_projects(id,case_id,title,stored_name,original_name,updated_at,content)
          VALUES(12,3,'Projekt odpowiedzi','','','2026-11-04','Przygotować odpowiedź na wezwanie do zapłaty.');
        ''')
        ensure_action_center_schema(self.con)
        ensure_action_center_schema(self.con)
        self.audits=[]
        self.synced=[]

    @contextlib.contextmanager
    def db(self):
        try:
            yield self.con
            self.con.commit()
        except Exception:
            self.con.rollback()
            raise

    @staticmethod
    def layout(title, body, active=''):
        return body

    @staticmethod
    def case_read_only(con, cid):
        return False

    def audit(self, con, cid, category, ident, action, details, author):
        self.audits.append((cid,action,details))

    def sync_task_alert(self, con, tid, author):
        self.synced.append(tid)

    @staticmethod
    def extract_document_text(name,data,force_ocr=False):
        return ('',0,'brak','')


class HandlerStub(ActionCenterMixin):
    def __init__(self, app):
        self.app=app
        self.last_url=None
        self.last_error=None
        self.last_page=None

    def _center_app(self):
        return self.app

    def current_author(self, fields=None):
        return 'Prawnik testowy'

    def redirect(self, url):
        self.last_url=url
        return url

    def send_html(self, body, status=200):
        self.last_page=body
        self.last_error=(status,body)
        return status

    def send_error(self,status):
        self.last_error=(status,'')
        return status


class ActionCenterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=AppStub(Path(self.temp.name))
        self.h=HandlerStub(self.app)

    def tearDown(self):
        self.app.con.close()
        self.temp.cleanup()

    def test_no_deadline_guessing(self):
        props=suggest_actions('Postanowienie. W terminie 14 dni od doręczenia należy przedłożyć dokumenty.')
        self.assertTrue(any('terminu' in p['title'] for p in props))
        self.assertTrue(all(p['kind']!='Termin procesowy' for p in props))
        self.assertTrue(all('due_date' not in p for p in props))

    def test_no_external_injection(self):
        props=suggest_actions('<script>alert(1)</script> wezwano do przedłożenia dokumentów')
        self.assertTrue(props)
        self.assertIn('&lt;script&gt;', self._html_escape(props[0]['source_excerpt']))

    @staticmethod
    def _html_escape(s):
        import html
        return html.escape(s)

    def test_idempotent_migration(self):
        ensure_action_center_schema(self.app.con)
        ensure_action_center_schema(self.app.con)
        self.assertEqual(self.app.con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='workflow_proposals'").fetchone()[0],1)

    def test_analysis_no_task_created_and_repeated_no_duplicate(self):
        self.h.action_center_analyze('document',11,{})
        first=self.h.last_url
        self.assertTrue(first.startswith('/workflow/review/'))
        self.assertEqual(self.app.con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],0)
        self.h.action_center_analyze('document',11,{})
        self.assertEqual(self.h.last_url,first)
        self.assertEqual(self.app.con.execute('SELECT COUNT(*) FROM workflow_reviews').fetchone()[0],1)

    def test_select_empty_rejected(self):
        self.h.action_center_analyze('document',11,{})
        self.h.action_center_decide(1,{'decision':'approve','review_confirm':'yes'})
        self.assertEqual(self.h.last_error[0],400)
        self.assertEqual(self.app.con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],0)

    def test_manual_deadline_requires_all_fields(self):
        self.h.action_center_analyze('document',11,{})
        pid=self.app.con.execute('SELECT id FROM workflow_proposals ORDER BY id LIMIT 1').fetchone()[0]
        base={f'p_{pid}_selected':'1',f'p_{pid}_title':'Sprawdzić termin',
              f'p_{pid}_kind':'Termin procesowy',f'p_{pid}_priority':'high',
              'decision':'approve','review_confirm':'yes'}
        self.h.action_center_decide(1,base)
        self.assertEqual(self.h.last_error[0],400)
        self.assertEqual(self.app.con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],0)
        form={**base,'deadline_verified':'yes',f'p_{pid}_base_date':'2026-11-04',
              f'p_{pid}_due_date':'2026-11-18',f'p_{pid}_basis':'Zarządzenie — ręcznie sprawdzono',
              f'p_{pid}_calculation':'Po zweryfikowaniu reguł doręczenia i terminów'}
        self.h.action_center_decide(1,form)
        self.assertEqual(self.app.con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],1)
        task=self.app.con.execute('SELECT * FROM tasks').fetchone()
        self.assertEqual(task['due_date'],'2026-11-18')
        self.assertEqual(task['deadline_base_date'],'2026-11-04')
        self.assertEqual(task['deadline_manual'],1)
        self.assertEqual(len(self.app.synced),1)
        self.h.action_center_decide(1,form)
        self.assertEqual(self.app.con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],1)

    def test_rejection_creates_no_task(self):
        self.h.action_center_analyze('document',11,{})
        pid=self.app.con.execute('SELECT id FROM workflow_proposals ORDER BY id LIMIT 1').fetchone()[0]
        f={f'p_{pid}_selected':'1', f'p_{pid}_title':'Nie dotyczy', f'p_{pid}_kind':'Zadanie',
           'decision':'reject','review_confirm':'yes'}
        self.h.action_center_decide(1,f)
        self.assertEqual(self.app.con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],0)
        self.assertEqual(self.app.con.execute('SELECT status FROM workflow_proposals WHERE id=?',(pid,)).fetchone()[0],'rejected')

    def test_stale_source_blocks_approval(self):
        self.h.action_center_analyze('document',11,{})
        self.app.con.execute("UPDATE documents SET extracted_text='Zmieniono' WHERE id=11")
        pid=self.app.con.execute('SELECT id FROM workflow_proposals ORDER BY id LIMIT 1').fetchone()[0]
        form={f'p_{pid}_selected':'1',f'p_{pid}_title':'Czynność',f'p_{pid}_kind':'Zadanie',
              'decision':'approve','review_confirm':'yes'}
        self.h.action_center_decide(1,form)
        self.assertEqual(self.h.last_error[0],409)
        self.assertEqual(self.app.con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],0)

    def test_date_rejected(self):
        with self.assertRaises(ValueError):valid_iso_date('2026-11-31')
        self.assertEqual(valid_iso_date('2026-11-04'),'2026-11-04')

    def test_draft_without_case_cannot_write(self):
        self.app.con.execute('UPDATE writing_projects SET case_id=NULL WHERE id=12')
        self.h.action_center_analyze('draft',12,{})
        pid=self.app.con.execute('SELECT id FROM workflow_proposals LIMIT 1').fetchone()[0]
        self.h.action_center_decide(1,{f'p_{pid}_selected':'1',f'p_{pid}_title':'Działanie',
          f'p_{pid}_kind':'Zadanie','decision':'approve','review_confirm':'yes'})
        self.assertEqual(self.h.last_error[0],409)
        self.assertEqual(self.app.con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],0)

    def test_user_adds_proposal_without_creating_task(self):
        self.h.action_center_analyze('document',11,{})
        self.h.action_center_add(1,{'title':'Wezwać klienta do dokumentów','kind':'Monit'})
        self.assertEqual(self.app.con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],0)
        self.assertEqual(self.app.con.execute("SELECT COUNT(*) FROM workflow_proposals WHERE title='Wezwać klienta do dokumentów'").fetchone()[0],1)

    def test_form_has_unchecked_suggestions_and_review_fields(self):
        self.h.action_center_analyze('document',11,{})
        self.h.action_center_review_page(1)
        body=self.h.last_page
        self.assertIn('deadline_verified',body)
        self.assertIn("_base_date' type='date'",body)
        self.assertIn('name=\'review_confirm\'',body)
        self.assertIn('Zatwierdź zaznaczone',body)
        self.assertNotIn('checked',body.split('Wybierz propozycję')[0])

    def test_patcher_partial_version_refused(self):
        with self.assertRaises(RuntimeError):apply_app('VERSION = "0.3.1-dev1"')


if __name__=='__main__':
    unittest.main(verbosity=2)
