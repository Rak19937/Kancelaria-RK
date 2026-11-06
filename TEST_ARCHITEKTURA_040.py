#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0.4.0-dev1: real tests without customer files and without network access."""
from __future__ import annotations

import ast
import hashlib
import io
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from datetime import date
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

from rk_core.database import db_connection
from rk_core.files import atomic_write_bytes
from rk_core.http import parse_multipart
from rk_domains.cases.repository import load_external_signature_map
from rk_domains.correspondence.rules import iso_date, needs_followup
from rk_domains.documents.ocr import extract_document_text
from rk_domains.documents.repository import case_document_rows
from rk_domains.inbox.analysis import analyze_letter
from rk_domains.inbox.service import stage_inbox_upload, InboxUploadValidationError
from rk_domains.tasks.assignments import selected_ids, set_task_assignees, task_assignees_map
from rk_domains.terms.validation import date_iso, time_hm

ROOT = Path(__file__).resolve().parent


class ArchitectureTests(unittest.TestCase):
    def test_modules_do_not_import_monolith(self):
        for root in (ROOT/'rk_core', ROOT/'rk_domains'):
            for py in root.rglob('*.py'):
                with self.subTest(path=py.relative_to(ROOT)):
                    tree = ast.parse(py.read_text(encoding='utf-8'))
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            self.assertFalse(any(a.name == 'app' or a.name.startswith('app.') for a in node.names))
                        if isinstance(node, ast.ImportFrom):
                            self.assertNotEqual(node.module, 'app')

    def test_import_graph_no_circular_imports(self):
        modules = {}
        for folder in ('rk_core', 'rk_domains'):
            for py in (ROOT/folder).rglob('*.py'):
                path=py.relative_to(ROOT)
                name='.'.join(path.with_suffix('').parts)
                if name.endswith('.__init__'): name=name[:-9]
                modules[name]=py
        graph={k:set() for k in modules}
        for name,py in modules.items():
            tree=ast.parse(py.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom) and node.level==0 and node.module:
                    for target in modules:
                        if target == node.module:graph[name].add(target)
                if isinstance(node,ast.Import):
                    for imp in node.names:
                        if imp.name in modules:graph[name].add(imp.name)
        def visit(node,active,done):
            self.assertNotIn(node,active,'Cykliczny import: '+' -> '.join(active+[node]))
            if node in done:return
            for dep in graph[node]:visit(dep,active+[node],done)
            done.add(node)
        done=set()
        for name in modules:visit(name,[],done)

    def test_source_wiring_preserves_public_interfaces(self):
        app=(ROOT/'app.py').read_text(encoding='utf-8')
        inbox=(ROOT/'rk_inbox.py').read_text(encoding='utf-8')
        self.assertIn('VERSION = "0.4.0-dev1"',app)
        self.assertIn('from rk_core.database import db_connection',app)
        self.assertIn('from rk_core.http import parse_multipart',app)
        self.assertIn('from rk_domains.documents.ocr import extract_document_text as _extract_document_text',app)
        self.assertIn('stage_inbox_upload(',inbox)
        self.assertIn('def inbox_approve(',inbox)  # ręczna weryfikacja nie została usunięta

    def test_db_commit_rollback_foreign_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'test.sqlite3'; d=Path(tmp)
            with db_connection(db,d) as con:
                self.assertEqual(con.execute('PRAGMA foreign_keys').fetchone()[0],1)
                con.execute('CREATE TABLE a (id INTEGER PRIMARY KEY, name TEXT)')
                con.execute('INSERT INTO a(name) VALUES(?)',('bezpieczne',))
            with self.assertRaises(RuntimeError):
                with db_connection(db,d) as con:
                    con.execute('INSERT INTO a(name) VALUES(?)',('niezapisane',))
                    raise RuntimeError('rollback')
            with db_connection(db,d) as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM a').fetchone()[0],1)

    def test_atomic_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/'nested'/'letter.txt'
            atomic_write_bytes(dest,b'legal-test')
            self.assertEqual(dest.read_bytes(),b'legal-test')
            self.assertFalse(any(dest.parent.glob('*.tmp_*')))

    def test_multipart_text_and_file(self):
        boundary='aBoundary'
        body=(f'--{boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\nTest\r\n'
              f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="x.txt"\r\n'
              'Content-Type: text/plain\r\n\r\nAla ma kota\r\n'
              f'--{boundary}--\r\n').encode()
        headers=Message(); headers['Content-Type']=f'multipart/form-data; boundary={boundary}'
        fields,files=parse_multipart(headers,body)
        self.assertEqual(fields['title'],'Test')
        self.assertEqual(files['file'][:2],('x.txt',b'Ala ma kota'))

    def test_ocr_text_and_docx_without_engine(self):
        no=lambda: ''
        config={'find_tesseract':no,'ocr_language_for':lambda _: 'pol',
                'run_tesseract':lambda *args: ''}
        text,used,status,lang=extract_document_text('pismo.txt','Pismo procesowe'.encode(),**config)
        self.assertEqual((text,used,status,lang),('Pismo procesowe',0,'tekst',''))
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as z:
            z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Test OCR</w:t></w:r></w:p></w:body></w:document>')
        result=extract_document_text('pismo.docx',data.getvalue(),**config)
        self.assertIn('Test OCR',result[0])

    def test_suggestions_cannot_set_procedural_due_date(self):
        info=analyze_letter('Sygn. I C 104/26. Sąd zobowiązuje do odpowiedzi w terminie 14 dni.')
        self.assertTrue(any('14 dni' in p['title'] for p in info['suggestions']))
        self.assertTrue(all(not p.get('due_date') for p in info['suggestions']))

    def test_inbox_staged_not_approved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            con=sqlite3.connect(root/'test.db')
            con.row_factory=sqlite3.Row
            con.executescript('''CREATE TABLE inbox_items (id INTEGER PRIMARY KEY, original_name TEXT,
              stored_name TEXT, file_hash TEXT,extracted_text TEXT,ocr_status TEXT,ocr_used INT,
              ocr_language TEXT,suggestions_json TEXT,created_by TEXT,status TEXT DEFAULT 'pending');''')
            @contextmanager
            def db():
                try:yield con;con.commit()
                except Exception:con.rollback();raise
            fake=SimpleNamespace(FILES_DIR=root/'dokumenty',safe_filename=lambda name:Path(name).name,
                extract_document_text=lambda *args:('w terminie 14 dni',0,'tekst',''),
                atomic_write_bytes=atomic_write_bytes,db=db)
            item=stage_inbox_upload(fake,('pismo.txt',b'test'), 'testowy',allowed_suffixes={'.txt'}, max_bytes=100)
            self.assertEqual(item,1)
            row=con.execute('SELECT * FROM inbox_items').fetchone()
            self.assertEqual(row['status'],'pending')
            self.assertEqual(row['original_name'],'pismo.txt')
            self.assertEqual((root/'dokumenty'/'_inbox'/row['stored_name']).read_bytes(),b'test')
            with self.assertRaises(InboxUploadValidationError):
                stage_inbox_upload(fake,('pismo.exe',b'test'),'testowy',allowed_suffixes={'.txt'},max_bytes=100)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM inbox_items').fetchone()[0],1)
            con.close()

    def test_dates_and_correspondence(self):
        self.assertEqual(date_iso('2026-11-06'),'2026-11-06')
        self.assertEqual(time_hm('14:30'),'14:30')
        self.assertEqual(iso_date(''),'')
        with self.assertRaises(ValueError):date_iso('2026-02-30')
        row={'direction':'outgoing','response_expected':1,'expected_reply_on':'2026-11-01','status':'sent'}
        self.assertTrue(needs_followup(row,today=date(2026,11,6)))
        self.assertFalse(needs_followup(row,today=date(2026,11,6),reply_count=1))

    def test_assignments_and_repository(self):
        con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
        con.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY,author_name TEXT,is_active INT);
            CREATE TABLE tasks(id INTEGER PRIMARY KEY,case_id INT,assigned_user_id INT);
            CREATE TABLE task_assignees(task_id INT,user_id INT);
            CREATE TABLE case_external_signatures(case_id INT,label TEXT,signature TEXT,id INT);
            CREATE TABLE cases(id INTEGER PRIMARY KEY,title TEXT);
            CREATE TABLE documents(id INTEGER PRIMARY KEY,case_id INT,title TEXT,doc_date TEXT,
              received_date TEXT,delivered_date TEXT,created_at TEXT);
            CREATE TABLE document_case_links(document_id INT,case_id INT);''')
        con.execute("INSERT INTO users VALUES(1,'Jan',1)")
        con.execute('INSERT INTO tasks VALUES(5,10,NULL)')
        con.execute("INSERT INTO case_external_signatures VALUES(10,'sąd','I C 1/26',1)")
        con.execute("INSERT INTO cases VALUES(10,'Sprawa')")
        con.execute("INSERT INTO documents VALUES(3,10,'Pismo','','2026-11-05','','2026-11-05')")
        ids=selected_ids({'assign_user_1':'1'},con)
        self.assertEqual(ids,[1]);set_task_assignees(con,5,ids)
        self.assertIn('Jan',task_assignees_map(con,[5])[5])
        self.assertEqual(load_external_signature_map(con,[10])[10][1],'I C 1/26')
        self.assertEqual(case_document_rows(con,10)[0]['id'],3)
        con.close()


if __name__=='__main__':unittest.main(verbosity=2)
