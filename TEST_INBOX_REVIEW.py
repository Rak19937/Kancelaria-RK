# -*- coding: utf-8 -*-
"""Offline regression tests for Inbox (no network, no external OCR engine)."""
import contextlib
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rk_inbox import InboxMixin, analyze_letter, ensure_inbox_schema, valid_date, escape


class InboxLogicTests(unittest.TestCase):
    def test_explicit_deadline_remains_undated(self):
        result = analyze_letter('Sygn. I C 104/26. Sąd zobowiązuje stronę do złożenia dokumentów w terminie 14 dni od doręczenia.')
        self.assertIn('I C 104/26', result['signatures'])
        self.assertTrue(any(p['kind'] == 'Termin procesowy' and '14 dni' in p['title'] for p in result['suggestions']))
        self.assertTrue(all(not p['due_date'] for p in result['suggestions']))

    def test_no_guessed_deadline(self):
        result = analyze_letter('Postanowienie w sprawie I Ns 231/26. Dokument doręczono stronie.')
        self.assertTrue(all(p['kind'] != 'Termin procesowy' for p in result['suggestions']))
        self.assertTrue(any('postanowienie' in p['title'].lower() for p in result['suggestions']))

    def test_reminder_is_only_proposed(self):
        result = analyze_letter('Prosimy o odpowiedź na nasze pismo.')
        self.assertTrue(any(p['kind'] == 'Monit' for p in result['suggestions']))

    def test_no_ocr_text(self):
        result = analyze_letter('')
        self.assertEqual(len(result['suggestions']), 1)
        self.assertIn('Brak odczytanego tekstu', result['suggestions'][0]['source'])

    def test_date_validations_and_html(self):
        self.assertEqual(valid_date('2026-11-03'), '2026-11-03')
        self.assertEqual(valid_date(''), '')
        for wrong in ('2026-02-31', '03.11.2026', '2026-1-1'):
            with self.assertRaises(ValueError):
                valid_date(wrong)
        self.assertEqual(escape('<script>'), '&lt;script&gt;')

    def test_schema_idempotent(self):
        con = sqlite3.connect(':memory:')
        con.execute('CREATE TABLE documents(id INTEGER PRIMARY KEY)')
        ensure_inbox_schema(con)
        ensure_inbox_schema(con)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='inbox_items'").fetchone()[0], 1)
        con.close()


class _AppStub:
    def __init__(self, root):
        self.FILES_DIR = root / 'dokumenty'
        self.FILES_DIR.mkdir()
        self.con = sqlite3.connect(':memory:', isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self.con.executescript('''
            CREATE TABLE cases(id INTEGER PRIMARY KEY, title TEXT, signature TEXT DEFAULT '', internal_signature TEXT DEFAULT '', status TEXT DEFAULT 'active');
            CREATE TABLE documents(id INTEGER PRIMARY KEY, case_id INTEGER,doc_date TEXT,
              received_date TEXT, delivered_date TEXT, doc_type TEXT, doc_status TEXT,title TEXT,
              description TEXT, stored_name TEXT, original_name TEXT,created_by TEXT,
              updated_by TEXT,file_hash TEXT,extracted_text TEXT,ocr_used INTEGER,
              ocr_status TEXT,ocr_language TEXT,indexed_at TEXT);
            CREATE TABLE tasks(id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT,due_date TEXT,
              status TEXT, priority TEXT, depends_on TEXT,notes TEXT,task_type TEXT,
              created_by TEXT,updated_by TEXT);
            CREATE TABLE document_fts(document_id INTEGER,case_id INTEGER,title TEXT,filename TEXT,body TEXT);
            INSERT INTO cases(id,title) VALUES(5,'Sprawa testowa');
        ''')
        ensure_inbox_schema(self.con)
        raw = b'dokument testowy'
        (self.FILES_DIR / '_inbox').mkdir()
        (self.FILES_DIR / '_inbox' / 'a.txt').write_bytes(raw)
        self.con.execute('''INSERT INTO inbox_items
          (original_name,stored_name,file_hash,extracted_text,ocr_status,ocr_used,ocr_language,suggestions_json)
          VALUES(?,?,?,?,?,?,?,?)''',
          ('pismo.txt', 'a.txt', hashlib.sha256(raw).hexdigest(), 'w terminie 7 dni',
           'tekst', 0, '', json.dumps(analyze_letter('w terminie 7 dni'))))

    @contextlib.contextmanager
    def db(self):
        try:
            yield self.con
            self.con.commit()
        except Exception:
            self.con.rollback()
            raise

    @staticmethod
    def atomic_write_bytes(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    @staticmethod
    def safe_filename(value):
        return Path(value).name

    @staticmethod
    def extract_document_text(filename, data):
        return ('Sąd zobowiązuje w terminie 14 dni', 0, 'tekst', '')

    @staticmethod
    def audit(*args):
        pass

    @staticmethod
    def sync_task_alert(*args):
        pass

    @staticmethod
    def log_app_exception(*args):
        pass

    @staticmethod
    def layout(title, body, active=''):
        return body


class _HandlerStub(InboxMixin):
    def __init__(self, app):
        self.app = app
        self.last_url = None
        self.last_error = None

    def _app(self):
        return self.app

    def current_author(self, fields=None):
        return 'Weryfikujący'

    def redirect(self, url):
        self.last_url = url
        return url

    def send_html(self, body, status=200):
        self.last_error = (status, body)
        return status

    def send_error(self, status):
        return status


class InboxApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = _AppStub(Path(self.tmp.name))
        self.handler = _HandlerStub(self.app)

    def tearDown(self):
        self.app.con.close()
        self.tmp.cleanup()

    def test_no_save_without_verification(self):
        self.handler.inbox_approve(1, {'case_id': '5', 'title': 'Pismo'})
        self.assertEqual(self.app.con.execute('SELECT COUNT(*) FROM documents').fetchone()[0], 0)

    def test_atomic_approve_and_idempotency(self):
        form = {
            'verified': 'yes', 'case_id': '5', 'title': 'Pismo testowe',
            'act_0_selected': '1', 'act_0_kind': 'Termin procesowy',
            'act_0_title': 'Sprawdzić termin 7 dni', 'act_0_due': '',
            'act_0_priority': 'high',
        }
        self.handler.inbox_approve(1, form)
        d = self.app.con.execute('SELECT * FROM documents').fetchone()
        t = self.app.con.execute('SELECT * FROM tasks').fetchone()
        self.assertIsNotNone(d)
        self.assertIsNotNone(t)
        self.assertEqual(t['due_date'], '')
        self.assertEqual(t['priority'], 'high')
        self.assertTrue((self.app.FILES_DIR / 'sprawa_5' / d['stored_name']).is_file())
        self.assertEqual(self.app.con.execute('SELECT status FROM inbox_items WHERE id=1').fetchone()[0], 'approved')
        self.assertEqual(self.app.con.execute('SELECT extracted_text FROM inbox_items WHERE id=1').fetchone()[0], '')
        self.handler.inbox_approve(1, form)
        self.assertEqual(self.app.con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 1)
        self.assertEqual(self.app.con.execute('SELECT COUNT(*) FROM documents').fetchone()[0], 1)


    def test_review_requires_case_selection_and_verification(self):
        self.handler.inbox_review(1)
        status, markup = self.handler.last_error
        self.assertEqual(status, 200)
        self.assertIn('name=\'case_id\' required', markup)
        self.assertIn('name=\'verified\'', markup)
        self.assertIn('Data (tylko po ręcznej kontroli)', markup)
        self.assertIn("name='act_0_selected'", markup)

    def test_inbox_upload_is_staged_only(self):
        self.handler.inbox_upload({}, {'file': ('Nowe.pdf', b'%PDF-1.4 fake')})
        self.assertEqual(self.app.con.execute('SELECT COUNT(*) FROM inbox_items').fetchone()[0], 2)
        self.assertEqual(self.app.con.execute('SELECT COUNT(*) FROM documents').fetchone()[0], 0)
        self.assertTrue(self.handler.last_url.startswith('/inbox/'))

    def test_discard_does_not_create_document(self):
        self.handler.inbox_discard(1, {})
        self.assertEqual(self.app.con.execute('SELECT COUNT(*) FROM documents').fetchone()[0], 0)
        self.assertEqual(self.app.con.execute('SELECT status FROM inbox_items WHERE id=1').fetchone()[0], 'discarded')
        self.assertFalse((self.app.FILES_DIR / '_inbox' / 'a.txt').exists())
        self.assertEqual(self.app.con.execute('SELECT extracted_text FROM inbox_items WHERE id=1').fetchone()[0], '')

    def test_bad_date_prevents_partial_save(self):
        self.handler.inbox_approve(1, {
            'verified': 'yes', 'case_id': '5', 'title': 'Pismo',
            'act_0_selected': '1', 'act_0_kind': 'Termin procesowy',
            'act_0_title': 'Kontrola', 'act_0_due': '2026-11-31',
        })
        self.assertEqual(self.app.con.execute('SELECT COUNT(*) FROM documents').fetchone()[0], 0)
        self.assertEqual(self.app.con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 0)

    def test_no_actions_when_unchecked(self):
        self.handler.inbox_approve(1, {'verified': 'yes', 'case_id': '5', 'title': 'Pismo'})
        self.assertEqual(self.app.con.execute('SELECT COUNT(*) FROM documents').fetchone()[0], 1)
        self.assertEqual(self.app.con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
