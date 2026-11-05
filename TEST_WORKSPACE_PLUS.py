# -*- coding: utf-8 -*-
"""Testy niezależne od instancji Portable; używać również w GitHub Actions."""
import importlib.util
from pathlib import Path
import sqlite3
import sys
import unittest
import contextlib
from types import SimpleNamespace
from unittest.mock import patch
import rk_workspace_plus as plus
from datetime import date

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from rk_workspace_plus import (ensure_workspace_plus_schema,selected_ids,set_task_assignees,
    assignee_html,personal_calendar_items,appointments_table,linked_sidecases,date_iso,time_hm,
    WorkspacePlusMixin,upcoming_alerts_multi)
from ZASTOSUJ_WORKSPACE_PLUS import apply_app

class DBTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:')
        self.con.row_factory=sqlite3.Row
        self.con.execute('PRAGMA foreign_keys=ON')
        self.con.executescript('''
        CREATE TABLE cases(id INTEGER PRIMARY KEY,title TEXT,client TEXT,lead_user_id INTEGER,signature TEXT DEFAULT '',internal_signature TEXT DEFAULT '',next_date TEXT DEFAULT '',next_step TEXT DEFAULT '',subject TEXT DEFAULT '',court TEXT DEFAULT '',category TEXT DEFAULT '',status TEXT DEFAULT 'active',created_by TEXT DEFAULT '',updated_by TEXT DEFAULT '');
        CREATE TABLE users(id INTEGER PRIMARY KEY,author_name TEXT,username TEXT,function TEXT DEFAULT '',is_active INTEGER DEFAULT 1);
        CREATE TABLE tasks(id INTEGER PRIMARY KEY,case_id INTEGER REFERENCES cases(id),title TEXT,status TEXT DEFAULT 'open',due_date TEXT,assigned_user_id INTEGER);
        CREATE TABLE events(id INTEGER PRIMARY KEY,case_id INTEGER,event_date TEXT,title TEXT);
        CREATE TABLE process_events(id INTEGER PRIMARY KEY,case_id INTEGER,event_date TEXT,next_date TEXT,title TEXT);
        CREATE TABLE documents(id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT);
        CREATE TABLE alerts(id INTEGER PRIMARY KEY,case_id INTEGER,alert_date TEXT,title TEXT,status TEXT,source_type TEXT,source_id INTEGER,assigned_user_id INTEGER,priority TEXT DEFAULT 'normal');
        CREATE TABLE writing_projects(id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT,due_date TEXT,status TEXT);
        CREATE TABLE correspondence_records(id INTEGER PRIMARY KEY,case_id INTEGER,subject TEXT,response_expected INTEGER,expected_reply_on TEXT,answered_on TEXT,reply_to_id INTEGER,direction TEXT);
        CREATE TABLE case_relations(id INTEGER PRIMARY KEY,source_case_id INTEGER,target_case_id INTEGER,relation_type TEXT,note TEXT,created_by TEXT,updated_by TEXT);
        INSERT INTO users(id,author_name,username,is_active) VALUES(1,'Anna','anna',1),(2,'Jan','jan',1),(3,'Maria','maria',0);
        INSERT INTO cases(id,title,client,lead_user_id,next_date,next_step) VALUES(1,'Główna','X',1,'2026-11-14','Odpowiedź'),(2,'Poboczna','X',2,'','');
        INSERT INTO tasks(id,case_id,title,due_date,assigned_user_id) VALUES(1,1,'Mediacja','2026-11-16',1),(2,2,'Zadanie Jana','2026-11-16',2);
        INSERT INTO events VALUES(1,1,'2026-11-17','Posiedzenie'),(2,2,'2026-11-17','Wizyta');
        INSERT INTO process_events VALUES(1,1,'2026-11-18','2026-11-19','Opinia');
        ''')
        ensure_workspace_plus_schema(self.con)
    def tearDown(self):self.con.close()
    @contextlib.contextmanager
    def _db(self):
        yield self.con
        self.con.commit()

    def _handler(self):
        class Handler(WorkspacePlusMixin):
            redirected=''
            def current_author(self,fields=None):return 'Tester'
            def redirect(self,target):self.redirected=target
            def send_error(self,*args):raise AssertionError(f'Błąd HTTP: {args}')
            def send_html(self,*args):raise AssertionError(f'Błąd formularza: {args}')
        return Handler()

    def _app(self):
        return SimpleNamespace(db=self._db, audit=lambda *args:None,
                               layout=lambda name,content,active='':content)

    def test_appointment_create_delete_restore(self):
        h=self._handler()
        with patch.object(plus,'_app',lambda obj:self._app()):
            h.appointment_save({'case_id':'1','title':'Druga mediacja','appointment_date':'2026-12-01',
                                'appointment_time':'11:00','assign_user_1':'1','assign_user_2':'1'})
            r=self.con.execute('SELECT * FROM case_appointments').fetchone()
            self.assertEqual(r['title'],'Druga mediacja')
            rid=r['id']
            self.assertEqual(self.con.execute('SELECT COUNT(*) FROM appointment_assignees').fetchone()[0],2)
            h.appointment_delete(rid,{})
            self.assertEqual(self.con.execute('SELECT COUNT(*) FROM case_appointments').fetchone()[0],0)
            self.assertIn('Przywróć termin',plus.archived_appointments_html(self.con,1))
            h.appointment_restore(rid,{})
            self.assertEqual(self.con.execute('SELECT COUNT(*) FROM case_appointments').fetchone()[0],1)
            self.assertEqual(self.con.execute('SELECT COUNT(*) FROM appointment_assignees').fetchone()[0],2)

    def test_child_case_creation_and_dependency(self):
        h=self._handler()
        with patch.object(plus,'_app',lambda obj:self._app()):
            h.sidecase_create(1,{'title':'Wniosek do urzędu','subject':'Uzyskanie odpisu',
                                  'needed_item':'Odpis decyzji','court':'Urząd Miasta','category':'administracyjna'})
            child=self.con.execute("SELECT id FROM cases WHERE title='Wniosek do urzędu'").fetchone()
            self.assertTrue(child)
            dep=self.con.execute('SELECT * FROM side_case_dependencies').fetchone()
            self.assertEqual((dep['parent_case_id'],dep['child_case_id']),(1,child[0]))
            self.assertEqual(self.con.execute("SELECT COUNT(*) FROM case_relations WHERE relation_type='main_related'").fetchone()[0],1)
            self.con.execute('INSERT INTO documents(id,case_id,title) VALUES(40,?,?)',(child[0],'Odpis decyzji'))
            h.sidecase_status(dep['id'],{'status':'received','document_id':'40'})
            stored=self.con.execute('SELECT status,document_id FROM side_case_dependencies WHERE id=?',(dep['id'],)).fetchone()
            self.assertEqual((stored[0],stored[1]),('received',40))

    def test_migration_idempotent_preserves(self):
        ensure_workspace_plus_schema(self.con)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],2)
        self.assertEqual(self.con.execute('SELECT user_id FROM task_assignees WHERE task_id=1').fetchone()[0],1)
    def test_multi_assignees(self):
        set_task_assignees(self.con,1,[2,1,2])
        self.assertEqual([x[0] for x in self.con.execute('SELECT user_id FROM task_assignees WHERE task_id=1 ORDER BY user_id')],[1,2])
        self.assertEqual(self.con.execute('SELECT assigned_user_id FROM tasks WHERE id=1').fetchone()[0],1)
    def test_invalid_user_not_allowed(self):
        with self.assertRaises(ValueError):selected_ids({'assign_user_3':'1'},self.con)
        with self.assertRaises(ValueError):selected_ids({'assign_user_999':'1'},self.con)
    def test_valid_checkbox_keys(self):
        self.assertEqual(selected_ids({'assign_user_1':'1','assign_user_2':'1','assign_user_bad':'1'},self.con),[1,2])
    def test_due_dates_iso(self):
        self.assertEqual(date_iso('2026-11-05'),'2026-11-05')
        for x in ['05.11.2026','2026-02-30','2026-01-1','']:
            with self.assertRaises(ValueError):date_iso(x)
    def test_hour(self):
        self.assertEqual(time_hm('16:30'),'16:30')
        for x in ['25:00','12:99','12:3']:
            with self.assertRaises(ValueError):time_hm(x)
    def test_appts_distinct(self):
        self.con.execute("INSERT INTO case_appointments(case_id,title,appointment_date) VALUES(1,'Mediacja','2026-11-16')")
        self.con.execute("INSERT INTO case_appointments(case_id,title,appointment_date) VALUES(1,'Mediacja nr 2','2026-12-01')")
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM case_appointments WHERE case_id=1').fetchone()[0],2)
        self.assertIn('Mediacja nr 2',appointments_table(self.con,1))
    def test_user_calendar_shows_assigned_not_others(self):
        set_task_assignees(self.con,1,[1,2])
        events=personal_calendar_items(self.con,1,'2026-11-01','2026-11-30')
        self.assertTrue(any(x[2]=='Mediacja' for x in events))
        self.assertFalse(any(x[2]=='Zadanie Jana' for x in events))
        self.assertFalse(any(x[2]=='Wizyta' for x in events))
        self.assertTrue(any(x[2]=='Odpowiedź' for x in events))
        self.assertTrue(any(x[2]=='Posiedzenie' for x in events))
        events2=personal_calendar_items(self.con,2,'2026-11-01','2026-11-30')
        self.assertTrue(any(x[2]=='Mediacja' for x in events2))
        self.assertFalse(any(x[2]=='Posiedzenie' for x in events2))
    def test_appt_calendar(self):
        cur=self.con.execute("INSERT INTO case_appointments(case_id,title,appointment_date) VALUES(1,'Posiedzenie niejawne','2026-11-22')")
        rid=cur.lastrowid
        self.con.execute('INSERT INTO appointment_assignees VALUES(?,?)',(rid,2))
        a=personal_calendar_items(self.con,1,'2026-11-01','2026-11-30')
        b=personal_calendar_items(self.con,2,'2026-11-01','2026-11-30')
        self.assertFalse(any('Posiedzenie niejawne' in x[2] for x in a))
        self.assertTrue(any('Posiedzenie niejawne' in x[2] for x in b))
    def test_subcase_deps(self):
        self.con.execute("INSERT INTO side_case_dependencies(parent_case_id,child_case_id,needed_item) VALUES(1,2,'Zaświadczenie')")
        self.assertIn('Zaświadczenie',linked_sidecases(self.con,1))
        self.assertIn('Sprawa główna',linked_sidecases(self.con,2))
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute("INSERT INTO side_case_dependencies(parent_case_id,child_case_id,needed_item) VALUES(1,1,'Błąd')")
    def test_escaped_usernames(self):
        self.con.execute("UPDATE users SET author_name='<script>alert(1)</script>' WHERE id=1")
        h=assignee_html(self.con,'task',1)
        self.assertIn('&lt;script&gt;',h)
        self.assertNotIn('<script>',h)
    def test_alert_visible_to_every_task_assignee(self):
        set_task_assignees(self.con,1,[1,2])
        self.con.execute("INSERT INTO alerts(id,case_id,alert_date,title,status,source_type,source_id,assigned_user_id) VALUES(10,1,?,'Mediacja','open','task',1,1)",(date.today().isoformat(),))
        self.assertTrue(any(r['id']==10 for r in upcoming_alerts_multi(self.con,2)))
        self.assertTrue(any(r['id']==10 for r in upcoming_alerts_multi(self.con,1)))

    def test_personal_calendar_alerts_drafts_and_outgoing(self):
        self.con.execute("INSERT INTO alerts(id,case_id,alert_date,title,status,source_type,assigned_user_id) VALUES(1,1,'2026-11-20','Pismo do urzędu','open','',1)")
        self.con.execute("INSERT INTO writing_projects(id,case_id,title,due_date,status) VALUES(1,1,'Projekt zażalenia','2026-11-21','Roboczy')")
        self.con.execute("INSERT INTO correspondence_records(id,case_id,subject,response_expected,expected_reply_on,answered_on,direction) VALUES(1,1,'Odpowiedź urzędu',1,'2026-11-22','','outgoing')")
        rows=personal_calendar_items(self.con,1,'2026-11-01','2026-11-30')
        self.assertTrue(any(x[2]=='Pismo do urzędu' for x in rows))
        self.assertTrue(any(x[2]=='Projekt zażalenia' for x in rows))
        self.assertTrue(any(x[2]=='Odpowiedź urzędu' for x in rows))
        self.con.execute("INSERT INTO correspondence_records(id,case_id,subject,response_expected,expected_reply_on,answered_on,reply_to_id,direction) VALUES(2,1,'Otrzymano',0,'','',1,'incoming')")
        rows=personal_calendar_items(self.con,1,'2026-11-01','2026-11-30')
        self.assertFalse(any(x[2]=='Odpowiedź urzędu' for x in rows))

    def test_unassigned_appointment_visible_for_case_lead(self):
        self.con.execute("INSERT INTO case_appointments(case_id,title,appointment_date) VALUES(1,'Mediacja dodatkowa','2026-11-27')")
        one=personal_calendar_items(self.con,1,'2026-11-01','2026-11-30')
        two=personal_calendar_items(self.con,2,'2026-11-01','2026-11-30')
        self.assertTrue(any(x[2]=='Mediacja dodatkowa' for x in one))
        self.assertFalse(any(x[2]=='Mediacja dodatkowa' for x in two))

    def test_calendar_does_not_show_unassigned_foreign(self):
        self.con.execute("INSERT INTO tasks(id,case_id,title,due_date) VALUES(3,2,'Prywatne Jana','2026-11-20')")
        self.assertFalse(any(x[2]=='Prywatne Jana' for x in personal_calendar_items(self.con,1,'2026-11-01','2026-11-30')))

class PatchTests(unittest.TestCase):
    def test_old_source_rejected(self):
        with self.assertRaises(RuntimeError):apply_app('VERSION = "0.3.5-dev1"')
    def test_no_mutation_of_unexpected_version(self):
        with self.assertRaises(RuntimeError):apply_app('VERSION = "0.3.8-dev1"')

if __name__=='__main__':unittest.main(verbosity=2)
