#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline security, rollback, format and durable OCR tests (synthetic files)."""
from __future__ import annotations
import contextlib
import io
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
import zipfile
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

from rk_core.cloud_security import CloudCryptoError, validate_cloud_url, encrypt_cloud_snapshot, decrypt_cloud_snapshot
from rk_core.request_security import csrf_for_session,csrf_html,csrf_valid,same_origin_request
from rk_core.schema_version import SCHEMA_VERSION
from rk_core.sync_atomic import commit_staged, pending_sync_journal, recover_interrupted, SyncRecoveryRequired
from rk_domains.documents.format_support import extract_extra_text
from rk_domains.inbox.worker import ensure_async_schema,job_state,retry_job
from rk_domains.inbox.service import stage_inbox_upload


class SecurityTests(unittest.TestCase):
    def test_schema_constant_used_by_sync(self):
        import rk_sync
        self.assertEqual(SCHEMA_VERSION,331)
        self.assertEqual(rk_sync.SCHEMA_VERSION,SCHEMA_VERSION)

    def test_https_required_outside_loopback(self):
        self.assertEqual(validate_cloud_url('https://office.example.org'),'https://office.example.org')
        self.assertEqual(validate_cloud_url('http://127.0.0.1:8787'),'http://127.0.0.1:8787')
        for url in ('http://office.example.org','http://192.168.0.5','http://127.0.0.1.evil.org','https://x:y@office.org'):
            with self.subTest(url=url),self.assertRaises(CloudCryptoError):validate_cloud_url(url)

    def test_cloud_end_to_end_encryption_and_authentication(self):
        plain=b'PK\x03\x04'+os.urandom(4096)
        encrypted=encrypt_cloud_snapshot(plain,'Mocne haslo 2026!')
        self.assertNotIn(plain,encrypted)
        self.assertTrue(encrypted.startswith(b'RKCLD2'))
        self.assertEqual(decrypt_cloud_snapshot(encrypted,'Mocne haslo 2026!'),plain)
        with self.assertRaises(CloudCryptoError):decrypt_cloud_snapshot(encrypted,'Nieprawidlowe haslo!')
        damaged=bytearray(encrypted);damaged[-18]^=1
        with self.assertRaises(CloudCryptoError):decrypt_cloud_snapshot(bytes(damaged),'Mocne haslo 2026!')
        with self.assertRaises(CloudCryptoError):decrypt_cloud_snapshot(plain,'Mocne haslo 2026!')

    def test_csrf_fields_origin_and_javascript_hook(self):
        session='temporary-local-session-key'
        token=csrf_for_session(session)
        markup=csrf_html('<html><head></head><body><form method="post"><button>Save</button></form><form method="get"></form></body></html>',token)
        self.assertEqual(markup.count('name="_rk_csrf"'),1)
        self.assertIn('/assets/rk_csrf.js',markup)
        hdr={'Host':'127.0.0.1:8765','Origin':'http://127.0.0.1:8765'}
        self.assertTrue(same_origin_request(hdr))
        self.assertTrue(csrf_valid(session,{'_rk_csrf':token},hdr))
        self.assertFalse(csrf_valid(session,{},hdr))
        self.assertFalse(same_origin_request({'Host':'127.0.0.1:8765','Origin':'https://evil.invalid'}))
        self.assertFalse(same_origin_request({'Host':'127.0.0.1:8765','Origin':'null'}))

    def test_sync_failure_restores_complete_previous_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'Data';data.mkdir();backup=data/'backup_synchronizacji'/'snapshot';backup.mkdir(parents=True)
            stage=data/'stage';stage.mkdir()
            managed=('dokumenty','projekty_pism')
            (data/'sprawnik.sqlite3').write_bytes(b'old-db')
            (backup/'sprawnik.sqlite3').write_bytes(b'old-db')
            (stage/'sprawnik.sqlite3').write_bytes(b'new-db')
            for d in managed:
                (data/d).mkdir();(backup/d).mkdir();(stage/d).mkdir()
                (data/d/'old.txt').write_text('OLD '+d)
                (backup/d/'old.txt').write_text('OLD '+d)
                (stage/d/'new.txt').write_text('NEW '+d)
            count=[0]
            def faulty_replace(src,dst):
                count[0]+=1
                if count[0]==2:raise OSError('Symulacja awarii w trakcie kopiowania')
                shutil.rmtree(dst);shutil.copytree(src,dst)
            with self.assertRaisesRegex(SyncRecoveryRequired,'przywrócono'):
                commit_staged(data,backup,stage/'sprawnik.sqlite3',stage,managed,faulty_replace,lambda _: (True,''))
            self.assertEqual((data/'sprawnik.sqlite3').read_bytes(),b'old-db')
            for d in managed:
                self.assertEqual((data/d/'old.txt').read_text(),'OLD '+d)
                self.assertFalse((data/d/'new.txt').exists())
            self.assertIsNone(pending_sync_journal(data))

    def test_doc_formats_and_unsupported_format(self):
        odt=io.BytesIO()
        with zipfile.ZipFile(odt,'w') as z:
            z.writestr('content.xml','<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><text:p>Pismo testowe</text:p></office:body></office:document-content>')
        text,_,status,_=extract_extra_text('pismo.odt',odt.getvalue())
        self.assertIn('Pismo testowe',text)
        self.assertEqual(status,'tekst_fragment')
        text,_,status,_=extract_extra_text('archiwum.zip',b'PK01')
        self.assertEqual(text,'')
        self.assertEqual(status,'bez_odczytu_formatu')
        text,_,status,_=extract_extra_text('mail.eml',b'Subject: Test\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nHello World')
        self.assertIn('Hello World',text)


class WorkerTests(unittest.TestCase):
    def test_queued_inbox_does_not_block_http_or_create_case_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);f=root/'documents';f.mkdir()
            dbfile=root/'db.sqlite3'
            # Context manager on sqlite3.Connection commits, but does not close.
            # Explicit closing prevents WinError 32 in Windows CI.
            with contextlib.closing(sqlite3.connect(dbfile)) as con:
                con.execute('''CREATE TABLE inbox_items(id INTEGER PRIMARY KEY,original_name TEXT,stored_name TEXT,file_hash TEXT,
                    extracted_text TEXT,ocr_status TEXT,ocr_used INTEGER,ocr_language TEXT,suggestions_json TEXT,created_by TEXT,
                    status TEXT DEFAULT 'pending')''')
                con.execute('CREATE TABLE documents(id INTEGER PRIMARY KEY)')
                ensure_async_schema(con)
                con.commit()
            @contextlib.contextmanager
            def getdb():
                # Preserve transaction commit/rollback semantics AND reliably close
                # every connection, including the OCR worker's background handles.
                with contextlib.closing(sqlite3.connect(dbfile,timeout=15)) as con:
                    con.row_factory=sqlite3.Row
                    with con:
                        yield con
            def fake_ocr(name,data):
                time.sleep(0.25)
                return ('Sąd zobowiązuje w terminie 14 dni',0,'tekst','')
            app=SimpleNamespace(FILES_DIR=f,INBOX_ASYNC_MODE=True,db=getdb,
                safe_filename=lambda s:Path(s).name,extract_document_text=fake_ocr,
                atomic_write_bytes=lambda p,b:(p.parent.mkdir(parents=True,exist_ok=True),p.write_bytes(b)),
                log_app_exception=lambda *args:None)
            start=time.monotonic()
            ident=stage_inbox_upload(app,('pismo.txt',b'test'), 'test',allowed_suffixes={'.txt'},max_bytes=1024)
            self.assertLess(time.monotonic()-start,0.2,'Upload jest blokowany przez OCR.')
            with getdb() as con:
                self.assertEqual(con.execute('SELECT COUNT(*) FROM documents').fetchone()[0],0)
            for _ in range(80):
                with getdb() as con:
                    state=job_state(con,ident)
                if state['state']=='ready':break
                time.sleep(.05)
            else:self.fail('Worker nie ukończył testowego OCR.')
            with getdb() as con:
                row=con.execute('SELECT extracted_text,status FROM inbox_items WHERE id=?',(ident,)).fetchone()
                self.assertIn('14 dni',row['extracted_text'])
                self.assertEqual(row['status'],'pending')
                self.assertEqual(con.execute('SELECT COUNT(*) FROM documents').fetchone()[0],0)


if __name__=='__main__':unittest.main(verbosity=2)
