#!/usr/bin/env python3
"""Test instalatora 0.4 na syntetycznym repo. Bez prawdziwej bazy ani akt klienta."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import ZASTOSUJ_040 as upgrade

ROOT=Path(__file__).resolve().parent

APP='''from __future__ import annotations
import contextlib,sqlite3,os
from pathlib import Path
from rk_paths import resolve_runtime_paths, installed_data_dir
VERSION = "0.3.10-dev1"
DATA_DIR=Path('Data');DB_PATH=DATA_DIR/'x.db';ERROR_LOG=DATA_DIR/'error.log';PERF_LOG=DATA_DIR/'perf.log'
@contextlib.contextmanager
def db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con=sqlite3.connect(DB_PATH,timeout=15,cached_statements=256)
    con.row_factory=sqlite3.Row
    try:
        con.execute('PRAGMA foreign_keys = ON')
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def atomic_write_bytes(path: Path, data: bytes):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(data)

def log_app_exception(path, exc):
    pass

def log_slow_request(path, elapsed):
    pass

def load_external_signature_map(con,case_ids):
    return {}

def extract_document_text(filename: str, data: bytes, force_ocr: bool=False) -> tuple[str,int,str,str]:
    a=_run_tesseract_on_file('cmd','file','pol')
    b=_run_tesseract_on_file('cmd','file','pol')
    return ('',0,'','')

def parse_multipart(headers,body):
    ctype=headers.get('Content-Type','')
    synthetic=(f"Content-Type: {ctype}\\r\\nMIME-Version: 1.0\\r\\n\\r\\n").encode()+body
    msg=BytesParser(policy=email_policy).parsebytes(synthetic)
    fields={};files={}
    return fields,files
'''
INBOX='''from __future__ import annotations
import re,sys
from urllib.parse import quote
SIGNATURE_RE=re.compile(r'\\d+')
DEADLINE_RE=re.compile(r'\\d+\\s+dni')
def _excerpt(text,start,end,maxlen=220):
    return text[start:end]
def analyze_letter(text):
    return {'signatures': [],'suggestions': [], 'document_type':'Inne'}
class InboxMixin:
    def _app(self):return sys.modules[type(self).__module__]
    def inbox_upload(self,fields,files):
        a=self._app()
        return self.redirect('/inbox')
    def inbox_approve(self,fields,files):
        return None
'''
WORKSPACE='''from __future__ import annotations
import re
from datetime import date
from urllib.parse import quote
def date_iso(value,required=True):
    return value
def time_hm(value):
    return value
def selected_ids(fields,con,prefix='assign_user_'):
    return []
def set_task_assignees(con,task_id,ids):
    return None
def task_assignees_map(con,task_ids):
    return {}
'''
CORRESPONDENCE='''from __future__ import annotations
from datetime import date
def iso_date(value):
    return value
def needs_followup(row,today=None,reply_count=0):
    return False
'''
DOCUMENTS='''from __future__ import annotations
import sqlite3
from urllib.parse import quote
def case_document_rows(con:sqlite3.Connection,case_id:int):
    return []
'''


def fixture(root):
    for name,source in {'app.py':APP,'rk_inbox.py':INBOX,'rk_workspace_plus.py':WORKSPACE,
                        'rk_correspondence.py':CORRESPONDENCE,'rk_document_hub.py':DOCUMENTS}.items():
        (root/name).write_text(source,encoding='utf-8')
    (root/'Data').mkdir()
    (root/'Data'/'oryginalna_baza.sqlite3').write_bytes(b'PRIVATE_FROZEN_BYTES')


class MigrationTests(unittest.TestCase):
    def test_one_transaction_idempotent_and_no_data_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root)
            report=upgrade.apply(root,ROOT,dry_run=True)
            self.assertIn('DRY RUN OK',report)
            self.assertIn('0.3.10', (root/'app.py').read_text(encoding='utf-8'))
            message=upgrade.apply(root,ROOT)
            self.assertIn('0.4.0',message)
            self.assertIn('0.4.0-dev1',(root/'app.py').read_text(encoding='utf-8'))
            self.assertTrue((root/'rk_core/database.py').exists())
            self.assertTrue((root/'rk_domains/inbox/service.py').exists())
            self.assertIn('już zainstalowana',upgrade.apply(root,ROOT))
            self.assertEqual((root/'Data'/'oryginalna_baza.sqlite3').read_bytes(),b'PRIVATE_FROZEN_BYTES')
            self.assertTrue((root/'.rk_backup_before_040/app.py').is_file())

    def test_incompatible_version_refused_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root)
            app=root/'app.py'
            app.write_text(app.read_text().replace('0.3.10-dev1','0.3.8-dev1'))
            with self.assertRaisesRegex(RuntimeError,'Wymagana wersja'):
                upgrade.apply(root,ROOT)
            self.assertFalse((root/'.rk_backup_before_040').exists())

    def test_unexpected_function_refused_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root)
            app=root/'app.py'
            app.write_text(app.read_text().replace('def parse_multipart','def gone_parser'))
            with self.assertRaises(RuntimeError):upgrade.apply(root,ROOT)
            self.assertFalse((root/'rk_domains').exists())


if __name__=='__main__':unittest.main(verbosity=2)
