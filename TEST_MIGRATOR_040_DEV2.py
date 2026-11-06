#!/usr/bin/env python3
"""Testy nieinwazyjnego instalatora: dry-run, rollback, idempotencja, Data."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
import ZASTOSUJ_040_DEV2 as u

APP='''from __future__ import annotations
import re,os,sqlite3,io,zipfile,threading
from pathlib import Path
from rk_paths import resolve_runtime_paths, installed_data_dir
VERSION = "0.4.0-dev1"
SCHEMA_VERSION = 330
MAX_POST_BYTES = 256 * 1024 * 1024

def init_db() -> None:
    with db() as con:
        con.execute('PRAGMA user_version=330')

def _run_tesseract_on_file(cmd, image, lang):
    return subprocess.run([cmd],timeout=120).stdout

def schedule_data_snapshot_restore(raw: bytes,source='file',cloud_version=0):
    try:
        z=zipfile.ZipFile(io.BytesIO(raw),'r')
        if True:
            parts=[x for x in Path(rel).parts if x not in {'','.','..'}]
        return True,''
    except Exception:return False,''

class Handler:
    def send_html(self, content: str, status=200):
        data = content.encode('utf-8')
        return data
    def set_session_cookie(self, token: str):
        self.send_header('Set-Cookie', token)
    def do_GET(self):
        if path == "/system/ws":
            return self.websocket_presence((qs.get("tab") or [""])[0])
    def do_POST(self):
        u = urlparse(self.path); path = u.path
        try:
            fields, files = self.read_post()
        except Exception:pass
        if path == "/system/closing":
            client_closing((parse_qs(u.query).get("tab") or [""])[0]); return self.send_no_content()
            if path == "/inbox/upload": return self.inbox_upload(fields, files)
        return None
    def cloud_page(self):
        html="""<button class='btn primary'>Wyślij do Cloud</button><button class='btn'>Pobierz z Cloud</button>"""
        return html
    def cloud_config_update(self,f):
        url = ''
        if url and not re.match(r'^https?://',url,re.I): return self.cloud_page('Adres Cloud musi zaczynać się od http:// lub https://.')
    def cloud_push(self,f):
        return None
    def cloud_pull(self,f):
        return None
    def backup(self):
        return None
    def trash_purge(self,trash_id,f):
        return None
    def case_unlock(self,cid,f):
        return None
    def case_lock(self,cid,f):
        return None
    def case_delete(self,cid,f):
        return None

def main():
    apply_pending_restore_if_any()
    return True
'''

INBOX='''from __future__ import annotations
from rk_domains.inbox.service import stage_inbox_upload, InboxUploadValidationError

def ensure_inbox_schema(con):
    con.executescript("CREATE TABLE IF NOT EXISTS inbox_items(id INTEGER PRIMARY KEY)")

class InboxMixin:
    def inbox_review(self, item_id: int):
        a=self._app()
        with a.db() as con:
            row = con.execute('SELECT * FROM inbox_items WHERE id=?',(item_id,)).fetchone()
            cases = con.execute("SELECT id,signature,internal_signature,title FROM cases ORDER BY status='closed',title").fetchall()
        if not row:
            return self.send_error(404)
        if row['status'] != 'pending':
            return self.redirect('/inbox')
        return self.send_html('hello')
    def inbox_approve(self, item_id: int, fields):
        a=self._app()
        with a.db() as con:
            row = con.execute('SELECT * FROM inbox_items WHERE id=?', (item_id,)).fetchone()
        if not row:return self.send_error(404)
        if row['status'] == 'approved' and row['document_id']:
            return self.redirect('/inbox')
        return self.redirect('/inbox')
    def inbox_discard(self, item_id: int, fields):
        return True
UI_COPY='Analiza działa lokalnie. Data końcowa terminu, adresat zobowiązania i przypisanie sprawy zawsze wymagają ręcznej kontroli.'
'''

SYNC='''from __future__ import annotations
from rk_paths import installed_data_dir, resolve_runtime_paths
from pathlib import Path
SCHEMA_VERSION = 240

def copy_full_state(source: Path, destination: Path, label: str) -> Path:
    return destination
'''
CLOUD='''import urllib.request
HEADERS={'Content-Type':'application/zip'}
ACCEPT={'Accept':'application/zip'}

def _base(url: str) -> str:
    return url
'''
CLOUD_SERVER="""CONTENT_TYPE='application/zip'
def put(payload):
    if payload[:2]!=b'PK': return self.json(400,{'error':'Snapshot nie jest archiwum ZIP.'})
    self.send_header('Content-Type','application/zip')
"""
OCR='''import zipfile
import xml.etree.ElementTree as ET
import os
from pathlib import Path

def extract_document_text(filename,data,force_ocr=False):
    ext=Path(filename).suffix.lower()
    max_pages=max(1,int(os.getenv('RK_OCR_MAX_PAGES','300') or 300))
    try:
        if ext=='.docx':
            with zipfile.ZipFile(io.BytesIO(data),'r') as z:
                xml=z.read('word/document.xml')
            root=ET.fromstring(xml); texts=[]
        if True:
            total=min(len(doc),max_pages)
            for i in range(total):
                page=doc.load_page(i)
                pix=page.get_pixmap(matrix=fitz.Matrix(dpi/72,dpi/72),alpha=False)
    except Exception:pass
    return ('',0,'nieobslugiwany_format','')
'''


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.repo=Path(self.tmp.name)
        data={'app.py':APP,'rk_inbox.py':INBOX,'rk_sync.py':SYNC,'rk_cloud.py':CLOUD,
              'rk_cloud_server.py':CLOUD_SERVER,'rk_domains/documents/ocr.py':OCR,
              'assets/service-worker.js':"const CACHE='rk-kancelaria-static-0.3.0-dev4';\nconst STATIC=[\n  '/assets/rk_app.js',\n];\n",
              'TEST_ARCHITEKTURA_040.py':'''def test(self,app):\n    self.assertIn('VERSION = "0.4.0-dev1"',app)\n''',
              'RAPORT_JAKOSCI_040.py':"report={'version':'0.4.0-dev1'}\n"}
        for name,content in data.items():
            path=self.repo/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content,encoding='utf-8')
        (self.repo/'Data').mkdir()
        (self.repo/'Data'/'sprawnik.sqlite3').write_bytes(b'TEST PRIVATE DB NOT MODIFIED')

    def test_success_dry_run_repeat_and_data_integrity(self):
        before=(self.repo/'Data'/'sprawnik.sqlite3').read_bytes()
        self.assertIn('DRY RUN',u.apply(self.repo,True))
        self.assertIn('0.4.0-dev1',(self.repo/'app.py').read_text())
        self.assertIn('Zainstalowano',u.apply(self.repo))
        self.assertIn('0.4.0-dev2',(self.repo/'app.py').read_text())
        self.assertIn('już zainstalowana',u.apply(self.repo))
        self.assertEqual(before,(self.repo/'Data'/'sprawnik.sqlite3').read_bytes())
        self.assertTrue((self.repo/'.rk_backup_before_040_dev2'/'app.py').is_file())

    def test_unknown_version_fails_closed(self):
        app=self.repo/'app.py'
        app.write_text(app.read_text().replace('0.4.0-dev1','0.4.0-dev3'),encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError,'0.4.0-dev1'):
            u.apply(self.repo,True)
        self.assertFalse((self.repo/'.rk_backup_before_040_dev2').exists())

if __name__=='__main__':unittest.main(verbosity=2)
