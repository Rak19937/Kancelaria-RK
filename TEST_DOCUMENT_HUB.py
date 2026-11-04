# -*- coding: utf-8 -*-
"""Testy relacji wiele-spraw/jeden-dokument bez plików klientów i bez internetu."""
import sqlite3
import unittest
from rk_document_hub import ensure_document_hub_schema, case_document_rows, DocumentHubMixin


class DocumentHubTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:')
        self.con.row_factory=sqlite3.Row
        self.con.execute('PRAGMA foreign_keys=ON')
        self.con.executescript('''
            CREATE TABLE cases(id INTEGER PRIMARY KEY, title TEXT, signature TEXT, status TEXT);
            CREATE TABLE documents(id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                title TEXT,stored_name TEXT,doc_date TEXT DEFAULT '',received_date TEXT DEFAULT '',
                delivered_date TEXT DEFAULT '',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO cases(id,title,signature,status) VALUES
                (1,'Sprawa przykładowa A','I C 123/26','active'),
                (2,'Sprawa przykładowa B','II C 456/26','active'),
                (3,'Sprawa przykładowa C','III C 789/26','active');
            INSERT INTO documents(id,case_id,title,stored_name) VALUES(9,1,'Pełnomocnictwo','file-9.pdf');
        ''')
        ensure_document_hub_schema(self.con)

    def tearDown(self):
        self.con.close()

    def test_schema_idempotent(self):
        ensure_document_hub_schema(self.con)
        ensure_document_hub_schema(self.con)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM documents').fetchone()[0],1)

    def test_one_original_shared_between_three_cases(self):
        self.con.execute('INSERT INTO document_case_links(document_id,case_id) VALUES(9,2)')
        self.con.execute('INSERT INTO document_case_links(document_id,case_id) VALUES(9,3)')
        for case_id in (1,2,3):
            docs=case_document_rows(self.con,case_id)
            self.assertEqual([d['id'] for d in docs],[9])
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM documents').fetchone()[0],1)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM document_case_links').fetchone()[0],2)

    def test_unlink_does_not_remove_source_document(self):
        self.con.execute('INSERT INTO document_case_links(document_id,case_id) VALUES(9,2)')
        self.con.execute('DELETE FROM document_case_links WHERE document_id=9 AND case_id=2')
        self.assertEqual(len(case_document_rows(self.con,2)),0)
        self.assertEqual(len(case_document_rows(self.con,1)),1)
        self.assertEqual(self.con.execute('SELECT stored_name FROM documents WHERE id=9').fetchone()[0],'file-9.pdf')

    def _handler(self):
        con=self.con
        class App:
            @staticmethod
            def db(): return con
            @staticmethod
            def case_read_only(connection, cid): return False
            @staticmethod
            def audit(*args): return None
            @staticmethod
            def layout(title, body, active=None): return body
        class Handler(DocumentHubMixin):
            def _hub_app(self): return App
            def current_author(self, fields): return 'Tester'
            def redirect(self, url): return ('REDIRECT',url)
            def send_html(self, body, status=200): return ('HTML',status,body)
            def send_error(self, status): return ('ERROR',status)
        return Handler()

    def test_actions_attach_and_detach_without_copy(self):
        h=self._handler()
        self.assertEqual(h.document_link_add(9,{'case_id':'2'}),('REDIRECT','/document/9/links'))
        self.assertEqual([d['id'] for d in case_document_rows(self.con,2)],[9])
        self.assertEqual(h.document_link_remove(9,{'case_id':'2'}),('REDIRECT','/document/9/links'))
        self.assertEqual(len(case_document_rows(self.con,2)),0)
        self.assertEqual(len(case_document_rows(self.con,1)),1)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM documents').fetchone()[0],1)

    def test_actions_power_of_attorney_save_and_remove(self):
        h=self._handler()
        form={'document_id':'9','principal':'Klient A','representative':'Pełnomocnik B',
              'authorization_scope':'Prowadzenie sprawy','validity_status':'do weryfikacji',
              'granted_on':'2026-11-04'}
        self.assertEqual(h.power_save(form),('REDIRECT','/powers'))
        r=self.con.execute('SELECT * FROM powers_of_attorney WHERE document_id=9').fetchone()
        self.assertEqual(r['principal'],'Klient A')
        form['principal']='Klient C'
        self.assertEqual(h.power_save(form),('REDIRECT','/powers'))
        self.assertEqual(self.con.execute('SELECT principal FROM powers_of_attorney WHERE document_id=9').fetchone()[0],'Klient C')
        self.assertEqual(h.power_remove({'document_id':'9'}),('REDIRECT','/powers'))
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM documents').fetchone()[0],1)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM powers_of_attorney').fetchone()[0],0)

    def test_invalid_power_date_rejected(self):
        h=self._handler()
        r=h.power_save({'document_id':'9','granted_on':'2026-02-30'})
        self.assertEqual(r[0],'HTML')
        self.assertEqual(r[1],400)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM powers_of_attorney').fetchone()[0],0)

    def test_powers_are_metadata_on_existing_document(self):
        self.con.execute('''INSERT INTO powers_of_attorney
            (document_id,principal,representative,authorization_scope)
            VALUES(9,'Mocodawca','Pełnomocnik','Do prowadzenia sprawy')''')
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM documents').fetchone()[0],1)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM powers_of_attorney').fetchone()[0],1)
        self.con.execute('DELETE FROM powers_of_attorney WHERE document_id=9')
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM documents').fetchone()[0],1)


if __name__=='__main__':
    unittest.main()
