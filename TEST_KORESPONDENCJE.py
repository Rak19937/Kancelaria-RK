# -*- coding: utf-8 -*-
"""Testy niezależne od danych kancelarii, bez kontaktu z siecią."""
from __future__ import annotations

import contextlib
import io
import sqlite3
import unittest
from datetime import date

from rk_correspondence import (CorrespondenceMixin, ensure_correspondence_schema,
                               needs_followup, iso_date, esc)
from ZASTOSUJ_KORESPONDENCJE import apply_app


class AppStub:
    def __init__(self):
        self.con=sqlite3.connect(':memory:',isolation_level=None)
        self.con.row_factory=sqlite3.Row
        self.con.execute('PRAGMA foreign_keys=ON')
        self.con.executescript('''
          CREATE TABLE cases(id INTEGER PRIMARY KEY,title TEXT,signature TEXT DEFAULT '',internal_signature TEXT DEFAULT '');
          CREATE TABLE documents(id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT,original_name TEXT);
          CREATE TABLE document_case_links(document_id INTEGER,case_id INTEGER,PRIMARY KEY(document_id,case_id));
          CREATE TABLE writing_projects(id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT);
          CREATE TABLE tasks(id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT,due_date TEXT,status TEXT,
              priority TEXT,depends_on TEXT,notes TEXT,task_type TEXT,created_by TEXT,updated_by TEXT);
          INSERT INTO cases(id,title) VALUES (1,'Sprawa A'),(2,'Sprawa B');
          INSERT INTO documents(id,case_id,title,original_name) VALUES
            (10,1,'Pismo A','a.docx'),(20,2,'Pismo B','b.pdf');
          INSERT INTO writing_projects(id,case_id,title) VALUES (11,1,'Projekt A'),(21,2,'Projekt B');
        ''')
        ensure_correspondence_schema(self.con)
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
    def layout(title,body,active=''):
        return body

    def audit(self,*args):
        self.audits.append(args)

    def sync_task_alert(self,*args):
        self.synced.append(args)


class HandlerStub(CorrespondenceMixin):
    def __init__(self,app):
        self.app=app
        self.last_url=None
        self.last_html=''
        self.last_status=None

    def _corr_app(self):return self.app
    def current_author(self,fields=None):return 'Prawnik testowy'
    def redirect(self,url):self.last_url=url;return url
    def send_html(self,body,status=200):self.last_html=body;self.last_status=status;return status
    def send_error(self,status):self.last_status=status;return status


class CorrespondenceTests(unittest.TestCase):
    def setUp(self):
        self.a=AppStub()
        self.h=HandlerStub(self.a)
    def tearDown(self):self.a.con.close()
    def default(self,**kw):
        data={'case_id':'1','direction':'outgoing','status':'sent','channel':'email',
              'subject':'Pismo do Sądu','counterparty':'Sąd Rejonowy',
              'sent_on':'2026-11-01','response_expected':'1',
              'expected_reply_on':'2026-11-03',
              'document_id':'10','draft_id':'11'}
        data.update(kw)
        return data
    def create(self,**kwargs):
        result=self.h.correspondence_save(self.default(**kwargs))
        self.assertTrue(str(result).startswith('/correspondence/'),self.h.last_html)
        return int(result.rsplit('/',1)[-1])

    def test_schema_idempotent(self):
        ensure_correspondence_schema(self.a.con)
        ensure_correspondence_schema(self.a.con)
        self.assertEqual(self.a.con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='correspondence_records'").fetchone()[0],1)

    def test_create_outgoing_does_not_send_or_create_tasks(self):
        rid=self.create()
        record=self.a.con.execute('SELECT * FROM correspondence_records WHERE id=?',(rid,)).fetchone()
        self.assertEqual(record['status'],'sent')
        self.assertEqual(record['expected_reply_on'],'2026-11-03')
        self.assertEqual(self.a.con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],0)
        self.assertEqual(self.a.con.execute('SELECT COUNT(*) FROM correspondence_events').fetchone()[0],1)

    def test_invalid_date_rejected(self):
        self.h.correspondence_save(self.default(sent_on='2026-02-30'))
        self.assertEqual(self.h.last_status,400)
        self.assertEqual(self.a.con.execute('SELECT COUNT(*) FROM correspondence_records').fetchone()[0],0)
        with self.assertRaises(ValueError):iso_date('04.11.2026')

    def test_delivery_before_dispatch_rejected(self):
        self.h.correspondence_save(self.default(delivered_on='2026-10-30'))
        self.assertEqual(self.h.last_status,400)

    def test_sent_requires_dispatch_date(self):
        self.h.correspondence_save(self.default(sent_on=''))
        self.assertEqual(self.h.last_status,400)
        self.h.correspondence_save(self.default(status='delivered',delivered_on=''))
        self.assertEqual(self.h.last_status,400)

    def test_other_case_document_rejected(self):
        self.h.correspondence_save(self.default(document_id='20'))
        self.assertEqual(self.h.last_status,409)
        self.assertEqual(self.a.con.execute('SELECT COUNT(*) FROM correspondence_records').fetchone()[0],0)

    def test_other_case_draft_rejected(self):
        self.h.correspondence_save(self.default(draft_id='21'))
        self.assertEqual(self.h.last_status,409)

    def test_shared_document_allowed(self):
        self.a.con.execute('INSERT INTO document_case_links(document_id,case_id) VALUES(20,1)')
        self.create(document_id='20')
        self.assertEqual(self.a.con.execute('SELECT document_id FROM correspondence_records').fetchone()[0],20)

    def test_overdue_only_manual_dates(self):
        rid=self.create()
        r=self.a.con.execute('SELECT * FROM correspondence_records WHERE id=?',(rid,)).fetchone()
        self.assertTrue(needs_followup(r,date(2026,11,4)))
        self.assertFalse(needs_followup(r,date(2026,11,3)))
        self.assertFalse(needs_followup(r,date(2026,11,5),reply_count=1))

    def test_explicit_confirm_creates_single_reminder(self):
        rid=self.create()
        self.h.correspondence_followup(rid,{'title':'Monitorować odpowiedź'})
        self.assertEqual(self.h.last_status,400)
        self.assertEqual(self.a.con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],0)
        self.h.correspondence_followup(rid,{'confirmed':'yes','title':'Monit do sprawy','due_date':'2026-11-10'})
        t=self.a.con.execute('SELECT * FROM tasks').fetchone()
        self.assertEqual((t['title'],t['task_type'],t['due_date']),('Monit do sprawy','Monit','2026-11-10'))
        self.assertEqual(len(self.a.synced),1)
        self.h.correspondence_followup(rid,{'confirmed':'yes','title':'Monit do sprawy'})
        self.assertEqual(self.h.last_status,409)
        self.assertEqual(self.a.con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],1)

    def test_followup_only_for_expected_response(self):
        rid=self.create(response_expected='0',expected_reply_on='')
        self.h.correspondence_followup(rid,{'confirmed':'yes','title':'Monit'})
        self.assertEqual(self.h.last_status,409)
        self.assertEqual(self.a.con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],0)

    def test_incoming_reply_prevents_followup(self):
        rid=self.create()
        self.h.correspondence_save({'case_id':'1','direction':'incoming','status':'received',
                        'channel':'postal','subject':'Odpowiedź','received_on':'2026-11-04',
                        'reply_to_id':str(rid)})
        self.assertTrue(str(self.h.last_url).startswith('/correspondence/'))
        self.h.correspondence_followup(rid,{'confirmed':'yes','title':'Monit'})
        self.assertEqual(self.h.last_status,409)
        self.assertEqual(self.a.con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],0)

    def test_reply_must_be_same_case(self):
        rid=self.create()
        self.h.correspondence_save({'case_id':'2','direction':'incoming','status':'received',
                             'channel':'email','subject':'Odpowiedź obca','reply_to_id':str(rid)})
        self.assertEqual(self.h.last_status,409)

    def test_update_keeps_history_and_no_duplicate_on_noop(self):
        rid=self.create()
        self.h.correspondence_save(self.default(subject='Zmieniony temat'),rid)
        self.assertEqual(self.a.con.execute('SELECT COUNT(*) FROM correspondence_events').fetchone()[0],2)
        self.h.correspondence_save(self.default(subject='Zmieniony temat'),rid)
        self.assertEqual(self.a.con.execute('SELECT COUNT(*) FROM correspondence_events').fetchone()[0],2)

    def test_views_escape_html(self):
        rid=self.create(subject='<script>alert(1)</script>')
        self.h.correspondence_page({})
        self.assertIn('&lt;script&gt;',self.h.last_html)
        self.assertNotIn('<script>alert(1)</script>',self.h.last_html)
        self.h.correspondence_detail(rid)
        self.assertIn('&lt;script&gt;',self.h.last_html)

    def test_form_has_evidence_and_manual_monitoring(self):
        self.h.correspondence_form({'case_id':['1']})
        self.assertEqual(self.h.last_status,200)
        for name in ('dispatch_receipt_id','delivery_receipt_id','expected_reply_on','reply_to_id','draft_id'):
            self.assertIn(name,self.h.last_html)
        self.assertIn('nie wylicza terminów',self.h.last_html)

    def test_app_integration_idempotent(self):
        mock='''from rk_action_center import ActionCenterMixin, ensure_action_center_schema
VERSION = "0.3.4-dev1"
SCHEMA_VERSION = 325
class Handler(ActionCenterMixin, DocumentHubMixin, InboxMixin, BaseHTTPRequestHandler):
    pass

def start():
        ensure_action_center_schema(con)
        if True:
            ("/workflow", "☑", "Centrum decyzji", "workflow"),
            if path == "/workflow": return self.action_center_page()
            if path == "/inbox/upload": return self.inbox_upload(fields, files)
        max_chars=160_000; bodytxt,status=self._preview_text_now(d,p,ext)
        to_doc=f"<form method='post' action='/draft/{did}/to-document' style='display:inline'><button class='btn primary'>Dodaj do dokumentów sprawy</button></form>" if d['case_id'] else ''
        return f"{center_action} {to_doc}"
'''
        patched=apply_app(mock)
        self.assertIn('SCHEMA_VERSION = 326',patched)
        self.assertIn('self.correspondence_followup(',patched)
        self.assertEqual(patched,apply_app(patched))
        with self.assertRaises(RuntimeError):apply_app('VERSION = "0.3.2-dev1"')


if __name__=='__main__':
    unittest.main(verbosity=2)
