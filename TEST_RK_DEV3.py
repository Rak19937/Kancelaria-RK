#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RK KANCELARIA dev3 regression tests; all synthetic data, no external network."""
from __future__ import annotations
import contextlib
import io
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rk_dev3_core import (ensure_dev3_schema,STAGES,set_stage,rate_grosze,start_timer,
    stop_timer,add_manual_time,time_csv,encrypt_vault,decrypt_vault,vault_store,vault_can_view,
    import_portal_csv)
from rk_dev3_calendar import (pull_proposals,publish_appointment,accept_proposal,
    CalendarSyncError)
from ZASTOSUJ_040_DEV3 import once,apply


def fixture_db():
    con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
    con.executescript('''
      PRAGMA foreign_keys=ON;
      CREATE TABLE users(id INTEGER PRIMARY KEY,author_name TEXT,is_active INTEGER DEFAULT 1);
      CREATE TABLE cases(id INTEGER PRIMARY KEY,title TEXT,signature TEXT,status TEXT DEFAULT 'active');
      CREATE TABLE case_appointments(
          id INTEGER PRIMARY KEY,case_id INTEGER REFERENCES cases(id),title TEXT NOT NULL,
          appointment_date TEXT NOT NULL,appointment_time TEXT DEFAULT '',kind TEXT DEFAULT '',
          notes TEXT DEFAULT '',created_by TEXT DEFAULT '',updated_by TEXT DEFAULT '');
      INSERT INTO users(id,author_name) VALUES(1,'Admin'),(2,'Inny');
      INSERT INTO cases(id,title,signature) VALUES(10,'Prywatna sprawa','I C 10/26'),(11,'Inna sprawa','I C 11/26');
      INSERT INTO case_appointments(id,case_id,title,appointment_date,appointment_time)
           VALUES(7,10,'Poufna rozprawa','2026-11-22','10:30');
    ''')
    ensure_dev3_schema(con)
    return con


class CoreTests(unittest.TestCase):
    def test_schema_idempotent_existing_cases_unchanged(self):
        with contextlib.closing(fixture_db()) as con:
            ensure_dev3_schema(con)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM cases').fetchone()[0],2)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM dev3_vault_files').fetchone()[0],0)

    def test_stages_are_independent_from_closing_status(self):
        with contextlib.closing(fixture_db()) as con:
            set_stage(con,10,'court',1,'Pismo z sądu')
            set_stage(con,10,'appeal',1,'Apelacja')
            self.assertEqual(con.execute('SELECT stage FROM dev3_case_stage WHERE case_id=10').fetchone()[0],'appeal')
            self.assertEqual(con.execute('SELECT COUNT(*) FROM dev3_stage_log').fetchone()[0],2)
            self.assertEqual(con.execute('SELECT status FROM cases WHERE id=10').fetchone()[0],'active')
            with self.assertRaises(ValueError):set_stage(con,10,'nonexistent',1)

    def test_timer_and_manual_invoices(self):
        with contextlib.closing(fixture_db()) as con:
            now=datetime(2026,11,7,11,30,tzinfo=timezone.utc)
            start_timer(con,1,10,'Analiza',now)
            with self.assertRaises(ValueError):start_timer(con,1,11,'Duplikat',now)
            ident=stop_timer(con,1,rate_grosze('125,50'),True,now+timedelta(minutes=45,seconds=2))
            row=con.execute('SELECT * FROM dev3_time_entries WHERE id=?',(ident,)).fetchone()
            self.assertEqual(row['minutes'],46)
            self.assertEqual(row['rate_grosze'],12550)
            add_manual_time(con,10,1,'2026-11-07',30,'Telefon',8000,False)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM dev3_time_entries').fetchone()[0],2)
            report=time_csv(con)
            self.assertIn('Analiza',report.decode('utf8'))
            self.assertIn('Telefon',report.decode('utf8'))
            with self.assertRaises(ValueError):rate_grosze('-1')
            with self.assertRaises(ValueError):add_manual_time(con,10,1,'nonsense',10,'',0,True)

    def test_vault_ciphertext_and_permissions(self):
        with tempfile.TemporaryDirectory() as tmp,contextlib.closing(fixture_db()) as con:
            blob=b'confidential-case-data-vault\x00\xff'
            pwd='BeZpiEczN3Hasl0_!'
            ident=vault_store(con,Path(tmp),10,1,'sekret.txt',blob,pwd)
            info=con.execute('SELECT * FROM dev3_vault_files WHERE id=?',(ident,)).fetchone()
            ciphertext=(Path(tmp)/'_vault'/info['stored_name']).read_bytes()
            self.assertNotIn(blob,ciphertext)
            self.assertEqual(decrypt_vault(ciphertext,pwd),blob)
            with self.assertRaises(ValueError):decrypt_vault(ciphertext,'BadPassword123')
            tampered=bytearray(ciphertext);tampered[-1]^=3
            with self.assertRaises(ValueError):decrypt_vault(bytes(tampered),pwd)
            self.assertTrue(vault_can_view(con,ident,1))
            self.assertFalse(vault_can_view(con,ident,2))
            con.execute('INSERT INTO dev3_vault_grants(file_id,user_id) VALUES(?,2)',(ident,))
            self.assertTrue(vault_can_view(con,ident,2))
            with self.assertRaises(ValueError):encrypt_vault(b'A','tiny')

    def test_csv_formula_injection_prevention(self):
        with contextlib.closing(fixture_db()) as con:
            con.execute("UPDATE cases SET title='=HYPERLINK(\"https://unsafe.invalid\")' WHERE id=10")
            add_manual_time(con,10,1,'2026-11-07',15,'@cmd',10000,True)
            exported=time_csv(con).decode('utf8')
            self.assertIn("'=HYPERLINK",exported)
            self.assertIn("'@cmd",exported)

    def test_portal_import_dedupe_no_auto_served(self):
        with contextlib.closing(fixture_db()) as con:
            csv=b'identyfikator;sygnatura;data;tytul;opis\nabc;I C 10/26;2026-11-07;Postanowienie;do sprawdzenia\n'
            self.assertEqual(import_portal_csv(con,csv,1),(1,0))
            self.assertEqual(import_portal_csv(con,csv,1),(0,1))
            item=con.execute('SELECT * FROM dev3_portal_items').fetchone()
            self.assertEqual(item['reviewed'],0)
            self.assertIsNone(item['case_id'])
            with self.assertRaises(ValueError):import_portal_csv(con,b'id;date\n1;2',1)


class CalendarTests(unittest.TestCase):
    def test_inbound_creates_proposals_not_appointments(self):
        with contextlib.closing(fixture_db()) as con:
            responses=[{'items':[{'id':'g-1','summary':'Posiedzenie',
                'start':{'dateTime':'2026-11-29T11:00:00+01:00'},
                'end':{'dateTime':'2026-11-29T12:00:00+01:00'}}]}]
            with patch('rk_dev3_calendar._api',side_effect=lambda *a,**kw:responses.pop(0)):
                added,_=pull_proposals(con,'google','FAKE')
            self.assertEqual(added,1)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM case_appointments').fetchone()[0],1)
            pid=con.execute('SELECT id FROM dev3_calendar_pending').fetchone()[0]
            num=accept_proposal(con,pid,10,1)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM case_appointments').fetchone()[0],2)
            self.assertEqual(con.execute('SELECT status FROM dev3_calendar_pending WHERE id=?',(pid,)).fetchone()[0],'accepted')
            self.assertTrue(num>0)

    def test_google_publish_private_title_by_default(self):
        with contextlib.closing(fixture_db()) as con:
            requests=[]
            def fake_api(url,token,method='GET',body=None,etag=None):
                requests.append((url,method,body,etag))
                return {'id':'remote-7','etag':'etag1'}
            with patch('rk_dev3_calendar._api',side_effect=fake_api):
                publish_appointment(con,'google',7,'FAKE',False)
            self.assertEqual(requests[0][1],'POST')
            self.assertEqual(requests[0][2]['summary'],'Termin kancelarii')
            self.assertNotIn('Poufna rozprawa',str(requests))
            requests.clear()
            with patch('rk_dev3_calendar._api',side_effect=fake_api):
                publish_appointment(con,'google',7,'FAKE',False)
            self.assertEqual(requests[0][1],'PATCH')
            self.assertEqual(requests[0][3],'etag1')

    def test_graph_utc_start_converts_to_warsaw_time(self):
        with contextlib.closing(fixture_db()) as con:
            data={'value':[{'id':'o-1','subject':'Wizyta',
                'start':{'dateTime':'2026-11-29T10:00:00'},
                'end':{'dateTime':'2026-11-29T11:00:00'}}]}
            with patch('rk_dev3_calendar._api',return_value=data):
                pull_proposals(con,'outlook','FAKE')
            pid=con.execute('SELECT id FROM dev3_calendar_pending').fetchone()[0]
            new_id=accept_proposal(con,pid,11,1)
            row=con.execute('SELECT appointment_date,appointment_time FROM case_appointments WHERE id=?',(new_id,)).fetchone()
            self.assertEqual(row['appointment_date'],'2026-11-29')
            self.assertEqual(row['appointment_time'],'11:00')

    def test_external_api_url_is_rejected_without_network(self):
        from rk_dev3_calendar import _api
        with self.assertRaises(CalendarSyncError):
            _api('https://evil.example/api','NOT-A-TOKEN')
        with self.assertRaises(CalendarSyncError):
            _api('http://www.googleapis.com/calendar','NOT-A-TOKEN')

    def test_graph_publish_and_redirect_rejection(self):
        with contextlib.closing(fixture_db()) as con:
            with patch('rk_dev3_calendar._api',return_value={'id':'remote','@odata.etag':'W/"1"'}) as mock:
                publish_appointment(con,'outlook',7,'FAKE')
                self.assertEqual(mock.call_args.kwargs['body']['subject'],'Termin kancelarii')
            with self.assertRaises(CalendarSyncError):publish_appointment(con,'fake',7,'FAKE')


class InstallerTests(unittest.TestCase):
    def test_unique_anchor_only(self):
        self.assertEqual(once('abc','b','z','x'),'azc')
        with self.assertRaises(RuntimeError):once('bbb','b','a','x')
        with self.assertRaises(RuntimeError):once('abc','q','x','x')


if __name__ == '__main__':unittest.main(verbosity=2)
