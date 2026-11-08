#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dev5 full regression tests; synthetic client data, no real network or files."""
from __future__ import annotations
import contextlib
import os
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from rk_dev3_core import ensure_dev3_schema,vault_store,decrypt_vault,encrypt_vault
from rk_dev4_core import ensure_dev4_schema
from rk_dev5_acl import (ensure_dev5_acl_schema,can_access_case,grant_case,revoke_case,
                        case_scoped_document,Dev5AccessMixin)
from rk_dev5_vault import ensure_dev5_vault_schema,vault_change_safe,recover_vault_journal,_backup
from rk_dev5_calendar_reconcile import (ensure_dev5_calendar_schema,linked_event,accept_change,
                                        record_published,mark_missing)


def fixture():
    con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
    con.executescript('''
    PRAGMA foreign_keys=ON;
    CREATE TABLE users(id INTEGER PRIMARY KEY, role TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1,
        username TEXT, author_name TEXT, function TEXT, password_hash TEXT, password_salt TEXT);
    CREATE TABLE cases(id INTEGER PRIMARY KEY, title TEXT, signature TEXT,lead_user_id INTEGER,
        status TEXT DEFAULT 'active', next_date TEXT DEFAULT '',next_step TEXT DEFAULT '',
        subject TEXT DEFAULT '', client TEXT DEFAULT '', court TEXT DEFAULT '');
    CREATE TABLE documents(id INTEGER PRIMARY KEY,case_id INTEGER NOT NULL REFERENCES cases(id),
        title TEXT,original_name TEXT,stored_name TEXT,doc_date TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE tasks(id INTEGER PRIMARY KEY,case_id INTEGER REFERENCES cases(id),title TEXT,
        due_date TEXT DEFAULT '',status TEXT DEFAULT 'open');
    CREATE TABLE case_notes(id INTEGER PRIMARY KEY,case_id INTEGER REFERENCES cases(id),note TEXT,author TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE case_appointments(id INTEGER PRIMARY KEY,case_id INTEGER REFERENCES cases(id),
        title TEXT,appointment_date TEXT,appointment_time TEXT,kind TEXT DEFAULT '',
        notes TEXT DEFAULT '',created_by TEXT DEFAULT '',updated_by TEXT DEFAULT '');
    CREATE TABLE user_sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER REFERENCES users(id),expires_at TEXT);
    INSERT INTO users(id,role,username,author_name) VALUES(1,'admin','root','Administrator'),
       (2,'user','anna','Anna'),(3,'user','jan','Jan');
    INSERT INTO cases(id,title,signature,lead_user_id) VALUES
       (10,'Alimenty','III RC 2/26',2),(11,'Tajny klient','I C 9/26',3);
    INSERT INTO documents(id,case_id,title,original_name,stored_name,doc_date) VALUES
       (20,10,'Pismo do sądu','a.pdf','a.pdf','2026-11-01'),
       (21,11,'TAJNY_DOKUMENT_INNEGO_KLIENTA','secret.pdf','secret.pdf','2026-11-02');
    INSERT INTO tasks(id,case_id,title,status) VALUES
       (30,10,'Sprawdź doręczenie','open'),(31,11,'POUFNE_ZADANIE','open');
    INSERT INTO case_appointments(id,case_id,title,appointment_date,appointment_time) VALUES
       (7,10,'Rozprawa','2026-11-22','10:30'),(8,11,'POUFNY_TERMIN','2026-11-25','11:00');
    ''')
    ensure_dev3_schema(con)
    ensure_dev4_schema(con)
    ensure_dev5_acl_schema(con)
    ensure_dev5_vault_schema(con)
    ensure_dev5_calendar_schema(con)
    return con


class FakeHandler(Dev5AccessMixin):
    def __init__(self,con,uid=2):
        self.con=con;self.uid=uid;self.html='';self.status=None;self.redirect_to='';self.error=None
    def _dev3_app(self):
        return SimpleNamespace(db=lambda:self.con,normalize_username=lambda x:x.strip(),
          valid_username=lambda x:len(x)>2, document_state=lambda x:('missing',None,'missing'))
    def _dev3_me(self):
        return self.con.execute('SELECT * FROM users WHERE id=?',(self.uid,)).fetchone()
    def send_html(self,body,status=200):self.html=body;self.status=status
    def redirect(self,url):self.redirect_to=url
    def send_error(self,code,*args):self.error=code


class CaseACLTests(unittest.TestCase):
    def setUp(self):self.con=fixture()
    def tearDown(self):self.con.close()

    def test_default_denies_other_case_even_if_doc_id_known(self):
        self.assertTrue(can_access_case(self.con,2,10))
        self.assertFalse(can_access_case(self.con,2,11))
        self.assertIsNone(case_scoped_document(self.con,2,11,21))
        self.assertIsNone(case_scoped_document(self.con,2,10,21))
        self.assertIsNotNone(case_scoped_document(self.con,2,10,20))

    def test_admin_grant_revoke_works_without_leaking_to_third_party(self):
        grant_case(self.con,1,11,2,'read')
        self.assertTrue(can_access_case(self.con,2,11))
        self.assertFalse(can_access_case(self.con,2,11,'edit'))
        self.assertTrue(can_access_case(self.con,3,11,'edit'))  # case lead
        with self.assertRaises(PermissionError):grant_case(self.con,2,11,3,'edit')
        grant_case(self.con,1,11,2,'edit')
        self.assertTrue(can_access_case(self.con,2,11,'edit'))
        revoke_case(self.con,1,11,2)
        self.assertFalse(can_access_case(self.con,2,11))

    def test_inactive_user_denied_even_as_case_lead(self):
        self.con.execute('UPDATE users SET is_active=0 WHERE id=2')
        self.assertFalse(can_access_case(self.con,2,10))

    def test_no_unauthorized_case_in_safe_listing(self):
        h=FakeHandler(self.con,2)
        self.assertTrue(h.dev5_access_get('/my-cases',{}))
        self.assertIn('Alimenty',h.html)
        self.assertNotIn('Tajny klient',h.html)
        self.assertNotIn('POUFNE_ZADANIE',h.html)
        h.dev5_access_get('/my-cases/10',{})
        self.assertIn('Pismo do sądu',h.html)
        self.assertNotIn('TAJNY_DOKUMENT_INNEGO_KLIENTA',h.html)
        self.assertNotIn('POUFNY_TERMIN',h.html)

    def test_old_documents_and_search_routes_are_closed_for_users(self):
        h=FakeHandler(self.con,2)
        for path in ('/documents','/search','/document/21/download',
                     '/case/11','/drafts','/calendar','/backup/snapshot'):
            h.status=None
            self.assertTrue(h.dev5_access_get(path,{}))
            self.assertEqual(h.status,403,path)
        h.error=None
        h.dev5_access_get('/my-cases/11',{})
        self.assertEqual(h.error,404)
        h.error=None
        h.dev5_access_get('/my-cases/10/documents/21/file',{})
        self.assertEqual(h.error,404)

    def test_user_cannot_mutate_unrelated_case_or_legacy_task(self):
        h=FakeHandler(self.con,2)
        self.assertTrue(h.dev5_access_post('/case/11/task',{},{}))
        self.assertEqual(h.status,403)
        h.status=None
        self.assertTrue(h.dev5_access_post('/my-cases/11/note',{'note':'attempt'},{}))
        self.assertEqual(h.error,404)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM case_notes WHERE case_id=11').fetchone()[0],0)
        h.error=None
        h.dev5_access_post('/my-cases/10/note',{'note':'Wniosek wysłany'}, {})
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM case_notes WHERE case_id=10').fetchone()[0],1)


class VaultRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.con=fixture();self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.con.close();self.tmp.cleanup()
    def db(self):return self.con
    def seed(self):
        fid=vault_store(self.con,self.root,10,1,'plik.txt',b'POUFNE','moje-stare-haslo')
        name=self.con.execute('SELECT stored_name FROM dev3_vault_files WHERE id=?',(fid,)).fetchone()[0]
        return fid,self.root/'_vault'/name

    def test_rotate_commits_new_password_and_removes_journal(self):
        fid,path=self.seed()
        vault_change_safe(self.db,self.root,fid,1,True,'rotate','moje-stare-haslo','moje-nowe-haslo')
        self.assertEqual(decrypt_vault(path.read_bytes(),'moje-nowe-haslo'),b'POUFNE')
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM dev5_vault_journal').fetchone()[0],0)

    def test_audit_failure_restores_old_cipher_and_db(self):
        fid,path=self.seed();before=path.read_bytes()
        with patch('rk_dev5_vault.action_log',side_effect=RuntimeError('audit failure')):
            with self.assertRaisesRegex(RuntimeError,'audit failure'):
                vault_change_safe(self.db,self.root,fid,1,True,'rotate','moje-stare-haslo','moje-nowe-haslo')
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM dev5_vault_journal').fetchone()[0],0)

    def test_power_loss_prepared_rotation_restores_old_file(self):
        fid,path=self.seed();op=uuid.uuid4().hex;saved=_backup(self.root,op)
        name=path.name;self.con.execute('INSERT INTO dev5_vault_journal VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)',
             (op,name,fid,'rotate','prepared'))
        os.replace(path,saved);path.write_bytes(encrypt_vault(b'POUFNE','moje-nowe-haslo'))
        recover_vault_journal(self.db,self.root)
        self.assertEqual(decrypt_vault(path.read_bytes(),'moje-stare-haslo'),b'POUFNE')
        self.assertFalse(saved.exists())

    def test_power_loss_committed_delete_cleans_backup(self):
        fid,path=self.seed();op=uuid.uuid4().hex;saved=_backup(self.root,op)
        name=path.name;os.replace(path,saved)
        self.con.execute('INSERT INTO dev5_vault_journal VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)',
                         (op,name,fid,'delete','committed'))
        self.con.execute('DELETE FROM dev3_vault_files WHERE id=?',(fid,))
        recover_vault_journal(self.db,self.root)
        self.assertFalse(path.exists());self.assertFalse(saved.exists())
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM dev5_vault_journal').fetchone()[0],0)


class RemoteCalendarRevisionTests(unittest.TestCase):
    def setUp(self):
        self.con=fixture()
        self.con.execute("INSERT INTO dev3_calendar_links(provider,appointment_id,external_id,etag) VALUES('google',7,'g1','v1')")
    def tearDown(self):self.con.close()
    def event(self,hour, status='confirmed'):
        return {'id':'g1','summary':'Termin kancelarii','status':status,
            'start':{'dateTime':f'2026-11-22T{hour:02d}:30:00+01:00'},
            'end':{'dateTime':f'2026-11-22T{hour+1:02d}:30:00+01:00'}}

    def test_external_change_is_proposal_not_auto_update(self):
        record_published(self.con,'google','g1','Termin kancelarii','2026-11-22T10:30','2026-11-22T11:30')
        self.assertTrue(linked_event(self.con,'google','g1',self.event(12)))
        self.assertEqual(self.con.execute('SELECT appointment_time FROM case_appointments WHERE id=7').fetchone()[0],'10:30')
        review=self.con.execute('SELECT * FROM dev5_calendar_changes').fetchone()
        self.assertEqual(review['status'],'pending')
        accept_change(self.con,review['id'],1,accept=True)
        self.assertEqual(self.con.execute('SELECT appointment_time FROM case_appointments WHERE id=7').fetchone()[0],'12:30')

    def test_absent_remote_event_requires_review_but_does_not_delete_local_date(self):
        record_published(self.con,'google','g1','Termin kancelarii','2026-11-22T10:30','2026-11-22T11:30')
        self.assertEqual(mark_missing(self.con,'google',set(),date(2026,11,8),date(2026,12,8)),1)
        proposal=self.con.execute('SELECT id,missing FROM dev5_calendar_changes').fetchone()
        self.assertEqual(proposal['missing'],1)
        accept_change(self.con,proposal['id'],1,True)
        row=self.con.execute('SELECT appointment_date,notes FROM case_appointments WHERE id=7').fetchone()
        self.assertEqual(row['appointment_date'],'2026-11-22')
        self.assertIn('nie odnaleziono',row['notes'])

    def test_cancel_does_not_delete_local_appointment(self):
        record_published(self.con,'google','g1','Termin kancelarii','2026-11-22T10:30','2026-11-22T11:30')
        linked_event(self.con,'google','g1',{'id':'g1','status':'cancelled'})
        review=self.con.execute('SELECT id,cancelled FROM dev5_calendar_changes').fetchone()
        self.assertEqual(review['cancelled'],1)
        accept_change(self.con,review['id'],1,True)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM case_appointments WHERE id=7').fetchone()[0],1)
        self.assertIn('anulowane',self.con.execute('SELECT notes FROM case_appointments WHERE id=7').fetchone()[0])


if __name__=='__main__':unittest.main(verbosity=2)
