# -*- coding: utf-8 -*-
import contextlib
import sqlite3
import unittest
import rk_caseflow as cf


def fixture():
    c=sqlite3.connect(':memory:')
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.executescript('''
    CREATE TABLE cases(id INTEGER PRIMARY KEY,title TEXT,signature TEXT DEFAULT '',internal_signature TEXT DEFAULT '',client TEXT DEFAULT '',status TEXT DEFAULT 'active',next_step TEXT DEFAULT '',next_date TEXT DEFAULT '');
    CREATE TABLE tasks(id INTEGER PRIMARY KEY,case_id INTEGER REFERENCES cases(id),title TEXT,status TEXT DEFAULT 'open',due_date TEXT DEFAULT '',task_type TEXT DEFAULT 'Zadanie',created_at TEXT DEFAULT '2026-11-30',updated_by TEXT DEFAULT '',completed_at TEXT DEFAULT '',completed_by TEXT DEFAULT '');
    CREATE TABLE documents(id INTEGER PRIMARY KEY,case_id INTEGER REFERENCES cases(id),title TEXT,doc_date TEXT DEFAULT '',received_date TEXT DEFAULT '',delivered_date TEXT DEFAULT '',created_at TEXT DEFAULT '2026-11-30',doc_type TEXT DEFAULT '',doc_status TEXT DEFAULT '',parent_document_id INTEGER,original_name TEXT DEFAULT '');
    CREATE TABLE document_case_links(document_id INTEGER,case_id INTEGER);
    CREATE TABLE case_relations(source_case_id INTEGER,target_case_id INTEGER);
    CREATE TABLE side_case_dependencies(id INTEGER PRIMARY KEY,parent_case_id INTEGER,child_case_id INTEGER,needed_item TEXT,status TEXT);
    CREATE TABLE events(id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT,event_date TEXT,event_type TEXT,description TEXT DEFAULT '');
    CREATE TABLE process_events(id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT,event_date TEXT,next_date TEXT DEFAULT '',event_type TEXT DEFAULT '',description TEXT DEFAULT '');
    CREATE TABLE case_appointments(id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT,appointment_date TEXT,appointment_time TEXT DEFAULT '',status TEXT DEFAULT 'planned');
    CREATE TABLE case_assertions(id INTEGER PRIMARY KEY,case_id INTEGER,side TEXT,statement TEXT,status TEXT,legal_significance TEXT DEFAULT '',sort_order INTEGER DEFAULT 0,is_archived INTEGER DEFAULT 0);
    CREATE TABLE case_evidence(id INTEGER PRIMARY KEY,assertion_id INTEGER,title TEXT,evidence_type TEXT,status TEXT,document_id INTEGER,source_reference TEXT DEFAULT '',notes TEXT DEFAULT '',is_archived INTEGER DEFAULT 0);
    CREATE TABLE document_events(id INTEGER PRIMARY KEY,case_id INTEGER,document_id INTEGER,event_date TEXT,event_type TEXT,title TEXT,description TEXT,is_archived INTEGER DEFAULT 0);
    CREATE TABLE writing_projects(id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT,due_date TEXT);
    CREATE TABLE correspondence_records(id INTEGER PRIMARY KEY,case_id INTEGER,subject TEXT,sent_on TEXT,delivered_on TEXT,received_on TEXT,expected_reply_on TEXT,direction TEXT);
    INSERT INTO cases(id,title,signature,client) VALUES(1,'Sprawa główna','I C 12/26','Klient A'),(2,'Sprawa poboczna','II SA 20/26','Klient A'),(3,'Obca sprawa','I C 999/26','Klient B');
    INSERT INTO tasks(id,case_id,title,status,due_date) VALUES(1,1,'Pismo','open','2026-11-25'),(2,1,'Uzyskaj dokument','open','2026-11-09'),(3,2,'Pismo do urzędu','open','2026-11-05'),(4,3,'Inny klient','open','2026-11-12');
    INSERT INTO documents(id,case_id,title,doc_date,received_date) VALUES(1,1,'Starsze pismo','2026-09-01','2026-10-01'),(2,1,'Nowsze pismo','2026-10-02','2026-10-05'),(3,3,'Cudzy dokument','2026-08-01','2026-08-05');
    INSERT INTO side_case_dependencies(id,parent_case_id,child_case_id,needed_item,status) VALUES(7,1,2,'Zaświadczenie','waiting');
    INSERT INTO case_assertions(id,case_id,side,statement,status) VALUES(1,1,'nasze','Fakt sporny','sporne');
    INSERT INTO case_evidence(id,assertion_id,title,evidence_type,status,document_id) VALUES(1,1,'Starsze pismo','Dokument','do przeprowadzenia',1);
    ''')
    cf.ensure_caseflow_schema(c)
    return c


class CoreTests(unittest.TestCase):
    def setUp(self):self.c=fixture()
    def tearDown(self):self.c.close()
    def test_schema_idempotent(self):
        cf.ensure_caseflow_schema(self.c); cf.ensure_caseflow_schema(self.c)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='task_dependencies'").fetchone()[0],1)
    def test_blocker_counts_one_query(self):
        cf.add_dependency(self.c,1,'task',2)
        cf.add_dependency(self.c,1,'sidecase',7)
        self.assertEqual(cf.dependency_blocking_counts(self.c,[1,2,3]),{1:2})
        self.c.execute("UPDATE tasks SET status='done' WHERE id=2")
        self.assertEqual(cf.dependency_blocking_counts(self.c,[1,2]),{1:1})
    def test_blocker_counts_empty(self):
        self.assertEqual(cf.dependency_blocking_counts(self.c,[]),{})
    def test_unresolved_snapshots_are_independent(self):
        cf.add_dependency(self.c,1,'task',2)
        self.assertEqual(cf.unresolved_dependencies(self.c,1)[0]['reference_id'],2)
    def test_task_dependency_unresolved(self):
        cf.add_dependency(self.c,1,'task',2)
        self.assertEqual(len(cf.unresolved_dependencies(self.c,1)),1)
        self.c.execute("UPDATE tasks SET status='done' WHERE id=2")
        self.assertFalse(cf.unresolved_dependencies(self.c,1))
    def test_duplicate_is_ignored(self):
        cf.add_dependency(self.c,1,'task',2);cf.add_dependency(self.c,1,'task',2)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM task_dependencies').fetchone()[0],1)
    def test_self_cycle_rejected(self):
        with self.assertRaisesRegex(ValueError,'cykl'):cf.add_dependency(self.c,1,'task',1)
    def test_long_cycle_rejected(self):
        cf.add_dependency(self.c,1,'task',2);cf.add_dependency(self.c,2,'task',3)
        with self.assertRaisesRegex(ValueError,'cykl'):cf.add_dependency(self.c,3,'task',1)
    def test_related_case_allowed(self):
        cf.add_dependency(self.c,1,'task',3)
        self.assertEqual(len(cf.unresolved_dependencies(self.c,1)),1)
    def test_foreign_case_rejected(self):
        with self.assertRaisesRegex(ValueError,'powiązanych'):cf.add_dependency(self.c,1,'task',4)
    def test_foreign_document_rejected(self):
        with self.assertRaisesRegex(ValueError,'powiązanych'):cf.add_dependency(self.c,1,'document',3)
    def test_document_available(self):
        cf.add_dependency(self.c,1,'document',2)
        self.assertFalse(cf.unresolved_dependencies(self.c,1))
    def test_sidecase_status(self):
        cf.add_dependency(self.c,1,'sidecase',7)
        self.assertTrue(cf.unresolved_dependencies(self.c,1))
        self.c.execute("UPDATE side_case_dependencies SET status='received' WHERE id=7")
        self.assertFalse(cf.unresolved_dependencies(self.c,1))
    def test_invalid_reference(self):
        with self.assertRaises(ValueError):cf.add_dependency(self.c,1,'document',999)
        with self.assertRaises(ValueError):cf.add_dependency(self.c,1,'wrong',3)
    def test_chronological_not_insertion(self):
        self.c.execute("INSERT INTO events(id,case_id,title,event_date,event_type) VALUES(5,1,'Najstarszy','2026-01-05','Akt')")
        self.c.execute("INSERT INTO events(id,case_id,title,event_date,event_type) VALUES(2,1,'Nowszy','2026-11-01','Akt')")
        items=cf.chronology_items(self.c,1)
        self.assertEqual([r['date'] for r in items],sorted(r['date'] for r in items))
        self.assertEqual(items[0]['title'],'Najstarszy')
    def test_document_has_separate_dates(self):
        x=[e for e in cf.chronology_items(self.c,1) if e['id']==1 and e['source'].startswith('document')]
        self.assertEqual({y['date'] for y in x},{'2026-09-01','2026-10-01'})
    def test_unrelated_document_hidden_from_timeline(self):
        self.assertNotIn('Cudzy dokument',[x['title'] for x in cf.chronology_items(self.c,1)])
    def test_escape(self):
        self.assertEqual(cf.esc('<script>'), '&lt;script&gt;')
    def test_invalid_date_skipped(self):
        self.c.execute("INSERT INTO events(id,case_id,title,event_date,event_type) VALUES(7,1,'Zepsuta','xyz','Akt')")
        self.assertNotIn('Zepsuta',[x['title'] for x in cf.chronology_items(self.c,1)])

# Runtime handlers use _app(self)=module containing class; our fixture deliberately
# simulates app globals without modifying the production application.
_TEST_CONNECTION=None
@contextlib.contextmanager
def db():
    yield _TEST_CONNECTION

def case_read_only(con,cid):
    return False

def sync_task_alert(con,tid,author=''):
    return None

def audit(con,*args):
    return None

def layout(title,body,key=''):
    return body

class Dummy(cf.CaseflowMixin):
    def __init__(self):self.sent=None;self.redirected=None
    def send_html(self,body,status=200):self.sent=(body,status)
    def send_error(self,code):self.sent=('error',code)
    def redirect(self,url):self.redirected=url
    def current_author(self,fields=None):return 'Tester'

class PageTests(unittest.TestCase):
    def setUp(self):
        global _TEST_CONNECTION
        self.c=fixture();_TEST_CONNECTION=self.c;self.h=Dummy()
    def tearDown(self):
        global _TEST_CONNECTION
        _TEST_CONNECTION=None;self.c.close()
    def test_documents_initial_only_case_cards(self):
        self.h.caseflow_documents({})
        self.assertIn('Sprawa główna',self.h.sent[0]);self.assertNotIn('Starsze pismo',self.h.sent[0])
        self.assertNotIn('Cudzy dokument',self.h.sent[0])
    def test_documents_selected_only_case(self):
        self.h.caseflow_documents({'case_id':['1']})
        self.assertIn('Starsze pismo',self.h.sent[0]);self.assertNotIn('Cudzy dokument',self.h.sent[0])
        self.assertLess(self.h.sent[0].find('Starsze pismo'),self.h.sent[0].find('Nowsze pismo'))
    def test_documents_reversed(self):
        self.h.caseflow_documents({'case_id':['1'],'order':['desc']})
        self.assertLess(self.h.sent[0].find('Nowsze pismo'),self.h.sent[0].find('Starsze pismo'))
    def test_evidence_by_case(self):
        self.h.caseflow_evidence({'case_id':['1']})
        self.assertIn('Fakt sporny',self.h.sent[0]);self.assertIn('/document/1/open',self.h.sent[0])
    def test_central_evidence_no_details_default(self):
        self.h.caseflow_evidence({})
        self.assertIn('Sprawa główna',self.h.sent[0]);self.assertNotIn('Fakt sporny',self.h.sent[0])
    def test_chronology_page_sort(self):
        self.h.caseflow_chronology(1,{})
        self.assertIn('Starsze pismo',self.h.sent[0])
        self.assertNotIn('Cudzy dokument',self.h.sent[0])
    def test_nav_search(self):
        self.h.caseflow_navigate({'q':['Starsze']})
        self.assertIn('/document/1/open',self.h.sent[0])
    def test_pending_task_complete_has_warning(self):
        cf.add_dependency(self.c,1,'task',2)
        self.assertTrue(self.h.caseflow_before_finish(1))
        self.assertIn('niespełnione zależności',self.h.sent[0].lower())
        self.assertEqual(self.c.execute('SELECT status FROM tasks WHERE id=1').fetchone()[0],'open')
    def test_complete_with_reason_is_audited(self):
        cf.add_dependency(self.c,1,'task',2)
        self.h.caseflow_force_complete(1,{'reason':'Zaświadczenie już nie jest wymagane.'})
        self.assertEqual(self.c.execute('SELECT status FROM tasks WHERE id=1').fetchone()[0],'done')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM task_dependency_overrides').fetchone()[0],1)
    def test_complete_without_reason_rejected(self):
        cf.add_dependency(self.c,1,'task',2)
        self.h.caseflow_force_complete(1,{'reason':'nie'})
        self.assertEqual(self.c.execute('SELECT status FROM tasks WHERE id=1').fetchone()[0],'open')
    def test_dependency_page(self):
        cf.add_dependency(self.c,1,'sidecase',7)
        self.h.caseflow_dependencies_page(1)
        self.assertIn('Zaświadczenie',self.h.sent[0]);self.assertIn('Oczekuje',self.h.sent[0])

if __name__=='__main__':unittest.main(verbosity=2)
