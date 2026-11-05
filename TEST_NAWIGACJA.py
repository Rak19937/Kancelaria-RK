# -*- coding: utf-8 -*-
"""Testy regresji terminów, kart powiązań, kasowania i URL-i wewnętrznych."""
import sqlite3
import unittest
from rk_record_navigation import case_deadline_rows, linked_records_panel, safe_back


def row(**kw): return kw

class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:')
        self.con.row_factory=sqlite3.Row
        self.con.executescript('''
        PRAGMA foreign_keys=ON;
        CREATE TABLE cases (id INTEGER PRIMARY KEY,title TEXT, next_date TEXT DEFAULT '',next_step TEXT DEFAULT '');
        CREATE TABLE documents (id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT,linked_task_id INTEGER);
        CREATE TABLE writing_projects (id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT);
        CREATE TABLE tasks (id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT);
        INSERT INTO cases(id,title) VALUES(1,'Sprawa testowa');
        INSERT INTO tasks(id,case_id,title) VALUES(7,1,'Mediacja'),(8,1,'Termin odpowiedzi');
        INSERT INTO documents(id,case_id,title,linked_task_id) VALUES(10,1,'Protokół z posiedzenia',7);
        CREATE TABLE workflow_reviews(id INTEGER PRIMARY KEY,source_type TEXT,source_id INTEGER,source_title TEXT);
        CREATE TABLE workflow_proposals(id INTEGER PRIMARY KEY,review_id INTEGER,task_id INTEGER,status TEXT);
        INSERT INTO workflow_reviews VALUES(1,'draft',12,'Projekt stanowiska');
        INSERT INTO workflow_proposals VALUES(1,1,7,'approved');
        CREATE TABLE correspondence_records (id INTEGER PRIMARY KEY,case_id INTEGER,subject TEXT,
            followup_task_id INTEGER,document_id INTEGER,dispatch_receipt_id INTEGER,delivery_receipt_id INTEGER,draft_id INTEGER);
        INSERT INTO correspondence_records VALUES(4,1,'Wezwanie do zapłaty',7,10,NULL,NULL,12);
        ''')
    def tearDown(self):self.con.close()
    def dates(self,tasks=None,alerts=None,c=None):
        if tasks is None:tasks=[]
        if alerts is None:alerts=[]
        if c is None:c=row(id=1,title='Sprawa testowa',next_date='',next_step='')
        return case_deadline_rows(tasks,alerts,c,lambda v:str(v),is_readonly=False)
    def task(self,tid,title='Mediacja'):
        return row(id=tid,title=title,task_type='Termin procesowy',status='open',due_date='2026-11-16')
    def alert(self,aid,src_type='',src_id=None):
        return row(id=aid,alert_date='2026-11-16',alert_type='Monit',title='Pilne',source_type=src_type,source_id=src_id)
    def test_date_rows_link_by_id(self):
        h=self.dates([self.task(7),self.task(8,'Mediacja')])
        self.assertIn('/task/7/edit',h)
        self.assertIn('/task/8/edit',h)
        self.assertIn('/task/7/delete',h)
        self.assertIn('/task/8/delete',h)
        self.assertEqual(h.count('>Do kosza</button>'),2)
    def test_no_duplicate_task_alert(self):
        h=self.dates([self.task(7)],[self.alert(44,'task',7)])
        self.assertNotIn('/alert/44/delete',h)
        self.assertEqual(h.count('<tr>'),1)
    def test_manual_alert_has_independent_delete(self):
        h=self.dates([], [self.alert(33)])
        self.assertIn('/alert/33/delete',h)
        self.assertNotIn('/task/33/delete',h)
    def test_next_date_is_not_task(self):
        h=self.dates(c=row(id=1,title='Sprawa',next_date='2026-12-01',next_step='Mediacja'))
        self.assertIn('/case/1/clear-next-date',h)
        self.assertIn('/case/1/edit',h)
        self.assertNotIn('/task/',h)
    def test_next_date_action_not_readonly(self):
        h=case_deadline_rows([],[],row(id=1,title='Sprawa',next_date='2026-12-01',next_step='Mediacja'),lambda x:x,is_readonly=True)
        self.assertNotIn('clear-next-date',h)
        self.assertIn('/case/1/edit',h)
    def test_escape_title_and_url(self):
        h=self.dates([self.task(7,'<img src=x onerror=alert(1)>')])
        self.assertIn('&lt;img',h)
        self.assertNotIn('<img',h)
    def test_safe_back_rejects_external_and_newline(self):
        for raw in ['https://bad.example','//bad.example','/\\bad','/x\ny','/%0a\\host','javascript:alert(1)','']:
            self.assertEqual(safe_back(raw,'/case/1'),'/case/1')
        self.assertEqual(safe_back('/case/1?tab=deadlines'),'/case/1?tab=deadlines')
    def test_task_links_exact_records(self):
        t=self.con.execute('SELECT * FROM tasks WHERE id=7').fetchone()
        h=linked_records_panel(self.con,'task',t)
        for expected in ['/document/10/open','/draft/12','/correspondence/4','/case/1?tab=deadlines']:
            self.assertIn(expected.replace('&','&amp;'),h)
    def test_document_links_back_to_task_and_correspondence(self):
        d=self.con.execute('SELECT * FROM documents WHERE id=10').fetchone()
        h=linked_records_panel(self.con,'document',d)
        self.assertIn('/task/7/edit',h)
        self.assertIn('/correspondence/4',h)
    def test_draft_links_back_to_correspondence(self):
        d=self.con.execute('SELECT * FROM writing_projects WHERE id=12').fetchone()
        # dokument może zostać utworzony bez wcześniejszego projektu pisma
        self.assertEqual(d,None)
        self.con.execute("INSERT INTO writing_projects VALUES(12,1,'Projekt stanowiska')")
        d=self.con.execute('SELECT * FROM writing_projects WHERE id=12').fetchone()
        h=linked_records_panel(self.con,'draft',d)
        self.assertIn('/correspondence/4',h)
        self.assertIn('/task/7/edit',h)
    def test_empty_optional_tables(self):
        self.con.execute('DROP TABLE workflow_proposals')
        self.con.execute('DROP TABLE workflow_reviews')
        self.con.execute('DROP TABLE correspondence_records')
        t=self.con.execute('SELECT * FROM tasks WHERE id=7').fetchone()
        h=linked_records_panel(self.con,'task',t)
        self.assertIn('/document/10/open',h)
    def test_no_fake_links_from_matching_titles(self):
        self.con.execute("INSERT INTO documents VALUES(11,1,'Mediacja',NULL)")
        t=self.con.execute('SELECT * FROM tasks WHERE id=7').fetchone()
        h=linked_records_panel(self.con,'task',t)
        self.assertNotIn('/document/11/open',h)
        self.assertIn('/document/10/open',h)

if __name__=='__main__':unittest.main(verbosity=2)
