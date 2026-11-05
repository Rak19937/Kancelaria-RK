#!/usr/bin/env python3
"""Regresja warstw 0.3.10, bez prawdziwych danych, usług sieciowych i pełnego app.py."""
import html
import sqlite3
import tempfile
import unittest
from pathlib import Path

from rk_navigation import render_sidebar_navigation, NAV_SECTIONS, ADMIN_ITEMS
from rk_routes import GET_ROUTES, POST_ROUTES, dispatch_static_get, dispatch_static_post
from rk_dashboard_data import dashboard_snapshot
from rk_search_data import find_navigation_matches
from rk_document_data import list_open_case_tasks
from ZASTOSUJ_AKTUALIZACJE import remove_static_routes, refactor_existing_ux, replace_between, NEW_VERSION


class NavigationTests(unittest.TestCase):
    def test_all_links_remain_and_admin_is_restricted(self):
        plain=render_sidebar_navigation('dashboard', {'role':'user'}, html.escape)
        admin=render_sidebar_navigation('audit', {'role':'admin'}, html.escape)
        for section, links in NAV_SECTIONS:
            for href, _, label, _ in links:
                self.assertIn(f'href="{html.escape(href)}"', plain)
        for href, _, _, _ in ADMIN_ITEMS:
            self.assertNotIn(f'href="{href}"', plain)
            self.assertIn(f'href="{href}"', admin)
        self.assertIn('<details class="nav-system" open>', admin)
        self.assertIn('USTAWIENIA I SYSTEM',admin)
        self.assertIn('>WIĘCEJ</span>',plain)

    def test_active_item_and_no_html_injection(self):
        r=render_sidebar_navigation('<script>',None,html.escape)
        self.assertNotIn('<script>',r)
        self.assertIn('href="/"',r)


class RouterTests(unittest.TestCase):
    def test_dispatch_signatures_and_missing_path(self):
        class Fake:
            def __init__(self): self.called=[]
            def __getattr__(self, name):
                def handler(*args,**kwargs): self.called.append((name,args,kwargs))
                return handler
        f=Fake(); q={'q':['x']}; fields={'a':'b'}; files={'z':b'x'}
        self.assertTrue(dispatch_static_get(f,'/',q))
        self.assertTrue(dispatch_static_get(f,'/cases',q))
        self.assertTrue(dispatch_static_get(f,'/cases/closed',q))
        self.assertFalse(dispatch_static_get(f,'/case/1',q))
        self.assertEqual(f.called[0],('dashboard',(),{}))
        self.assertEqual(f.called[1],('cases',(q,),{'closed_only':False}))
        self.assertEqual(f.called[2],('cases',(q,),{'closed_only':True}))
        self.assertTrue(dispatch_static_post(f,'/logout',fields,files))
        self.assertTrue(dispatch_static_post(f,'/recovery/snapshot-import',fields,files))
        self.assertFalse(dispatch_static_post(f,'/case/1/delete',fields,files))
        self.assertEqual(f.called[-2],('logout_submit',(),{}))
        self.assertEqual(f.called[-1],('full_snapshot_import',(fields,files),{}))

    def test_all_registered_routes_have_exact_removable_anchors(self):
        calls={'':'','q':'qs','f':'fields','ff':'fields, files',
               'q_closed_false':'qs, closed_only=False','q_closed_true':'qs, closed_only=True'}
        for routes in (GET_ROUTES,POST_ROUTES):
            source='\n'.join(
                f'            if path == "{path}": return self.{method}({calls[kind]})'
                for path,(method,kind) in routes.items())+'\n'
            result=remove_static_routes(source,routes,'test')
            self.assertFalse(result.strip())
            with self.assertRaises(RuntimeError):
                remove_static_routes(source.replace('return self.', 'return other.'),routes,'test')

    def test_route_registry_does_not_include_auth_or_unusual_routes(self):
        for p in ('/setup','/login','/system/heartbeat','/document/1/file'):
            self.assertNotIn(p,GET_ROUTES)
        self.assertNotIn('/setup',POST_ROUTES)
        self.assertNotIn('/login',POST_ROUTES)
        self.assertNotIn('/case/1/update',POST_ROUTES)
        self.assertEqual(len(GET_ROUTES),len(set(GET_ROUTES)))
        self.assertEqual(len(POST_ROUTES),len(set(POST_ROUTES)))


class DashboardDataTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.executescript('''
            CREATE TABLE cases (id INTEGER PRIMARY KEY, status TEXT, title TEXT,
              signature TEXT,internal_signature TEXT,next_date TEXT,next_step TEXT);
            CREATE TABLE tasks (id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT,
              status TEXT,due_date TEXT,priority TEXT);
            CREATE TABLE events (id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT,
              event_date TEXT,event_type TEXT,created_by TEXT);
            CREATE TABLE user_case_pins (user_id INTEGER,case_id INTEGER);
            CREATE TABLE user_case_recent (user_id INTEGER,case_id INTEGER,opened_at TEXT);
            INSERT INTO cases VALUES (1,'active','Sprawa 1','I C 1/26','','2026-11-10','Rozprawa');
            INSERT INTO cases VALUES (2,'closed','Sprawa 2','I C 2/26','','','');
            INSERT INTO tasks VALUES (10,1,'Dzisiaj','open','2026-11-05','high');
            INSERT INTO tasks VALUES (11,1,'Bez daty','open','','normal');
            INSERT INTO tasks VALUES (12,2,'Zamknięte','open','2026-11-05','high');
            INSERT INTO events VALUES (1,1,'Wezwanie','2026-11-01','Zdarzenie','Test');
            INSERT INTO user_case_pins VALUES (3,1);
            INSERT INTO user_case_recent VALUES (3,1,'2026-11-05 09:00:00');
        ''')
    def tearDown(self):self.db.close()
    def test_sql_results_preserve_counts_order_and_identity(self):
        called=[]
        def signature_loader(db,ids):
            called.extend(ids)
            return {x:'test' for x in ids}
        x=dashboard_snapshot(self.db,'2026-11-05','2026-11-12',3,signature_loader,['active','closed'])
        self.assertEqual(x['counts'],{'active':1,'closed':1})
        self.assertEqual(x['due_today'],1)
        self.assertEqual(x['high_count'],1)
        self.assertEqual(x['overdue_count'],0)
        self.assertEqual(x['next7_count'],0)
        self.assertEqual([r['id'] for r in x['dated']],[10])
        self.assertEqual([r['id'] for r in x['undated']],[11])
        self.assertEqual([r['id'] for r in x['pinned']],[1])
        self.assertEqual([r['id'] for r in x['recent_cases']],[1])
        self.assertEqual([r['id'] for r in x['upcoming']],[1])
        self.assertEqual([r['id'] for r in x['recent_events']],[1])
        self.assertIn(1,called)

    def test_not_logged_in_returns_no_pins(self):
        x=dashboard_snapshot(self.db,'2026-11-05','2026-11-12',None,lambda con,ids:{},['active'])
        self.assertEqual(x['pinned'],[])
        self.assertEqual(x['recent_cases'],[])


class SearchAndDocumentTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.executescript('''
            CREATE TABLE cases (id INTEGER PRIMARY KEY,title TEXT,signature TEXT,internal_signature TEXT,client TEXT);
            CREATE TABLE tasks (id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT,due_date TEXT,status TEXT,priority TEXT);
            CREATE TABLE documents (id INTEGER PRIMARY KEY,case_id INTEGER,title TEXT,original_name TEXT,
              doc_date TEXT,received_date TEXT,created_at TEXT);
            INSERT INTO cases VALUES (1,'Pozew Nowak','I C 123/26','','Jan Nowak');
            INSERT INTO tasks VALUES (10,1,'Odpowiedź na pozew','2026-12-05','open','high');
            INSERT INTO tasks VALUES (11,1,'Archiwum','2026-12-05','done','normal');
            INSERT INTO documents VALUES (20,1,'Pozew','pozew.pdf','2026-10-05','','2026-11-05');
        ''')
    def tearDown(self):self.db.close()
    def test_search_and_case_task_list(self):
        cases,tasks,docs=find_navigation_matches(self.db,'Nowak')
        self.assertEqual(len(cases),1)
        self.assertEqual(len(tasks),0)
        self.assertEqual(len(docs),0)
        cases,tasks,docs=find_navigation_matches(self.db,'pozew')
        self.assertEqual([r['id'] for r in cases],[1])
        self.assertEqual([r['id'] for r in tasks],[10])
        self.assertEqual([r['id'] for r in docs],[20])
        open_tasks=list_open_case_tasks(self.db,1)
        self.assertEqual([r['id'] for r in open_tasks],[10])
        self.assertEqual(find_navigation_matches(self.db,''),([],[],[]))


class InstallerSafetyTests(unittest.TestCase):
    def test_ux_patch_existing_imports_and_sql_are_split(self):
        old='''from html import escape
    tasks = con.execute(\'\'\'SELECT id,title,due_date,status,priority FROM tasks
        WHERE case_id=? AND status='open' LIMIT 8\'\'\', (cid,)).fetchall()
    heading = escape(x)'''
        updated=refactor_existing_ux(old)
        self.assertIn('from rk_document_data import list_open_case_tasks',updated)
        self.assertIn('tasks = list_open_case_tasks(con, cid)',updated)
        self.assertNotIn('con.execute',updated)

    def test_anchor_checks_fail_closed(self):
        with self.assertRaises(RuntimeError):
            replace_between('abc','X','z','new','test')
        self.assertIn('0.3.10-dev1',NEW_VERSION)

if __name__=='__main__': unittest.main(verbosity=2)
