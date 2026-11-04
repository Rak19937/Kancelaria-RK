# -*- coding: utf-8 -*-
"""Regresja podglądu bez danych kancelarii; nie wymaga uruchamiania serwera."""
from __future__ import annotations

import io
import pathlib
import tempfile
import unittest
import zipfile
from rk_unified_preview import render_preview,serve_local_file, _mime_for
from ZASTOSUJ_PODGLAD import apply_app,apply_inbox,MARK


class HandlerStub:
    def __init__(self,headers=None,path='/test'):
        self.headers=headers or {}
        self.path=path
        self.headers_out={}
        self.wfile=io.BytesIO()
        self.code=None
    def send_response(self,c):self.code=c
    def send_header(self,k,v):self.headers_out[k.lower()]=v
    def end_headers(self):pass
    def send_error(self,c,*args):self.code=c


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.dir=pathlib.Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def f(self,name,data):
        p=self.dir/name;p.write_bytes(data);return p
    def test_text_escapes_dangerous_html(self):
        p=self.f('a.html',b'<script>alert(123)</script>')
        h=render_preview(p,p.name,'/local/file')
        self.assertIn('&lt;script&gt;',h)
        self.assertNotIn('<script>alert(123)',h)
    def test_word_with_paragraphs_and_bold(self):
        p=self.dir/'projekt.docx'
        with zipfile.ZipFile(p,'w') as z:
            z.writestr('word/document.xml',
              '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
              '<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Pozew &amp; zalacznik</w:t></w:r></w:p>'
              '<w:p><w:r><w:t>&lt;img onerror=x&gt;</w:t></w:r></w:p></w:body></w:document>')
        h=render_preview(p,p.name,'/draft/1/file')
        self.assertIn('<strong>Pozew &amp; zalacznik</strong>',h)
        self.assertIn('&lt;img onerror=x&gt;',h)
        self.assertNotIn('<img onerror=x>',h)
    def test_image_audio_video_and_unsupported(self):
        for name,expected in [('foto.jpg','<img '),('film.mp4','<video '),('dzwiek.mp3','<audio '),('stary.doc','nie ma bezpiecznego podglądu')]:
            with self.subTest(name=name):
                p=self.f(name,b'TEST')
                self.assertIn(expected,render_preview(p,name,'/document/10/file'))
    def test_azure_urls_rejected(self):
        p=self.f('a.txt',b'ok')
        with self.assertRaises(ValueError):render_preview(p,p.name,'//evil.com')
    def test_pdf_pages_local_rendering(self):
        try:
            import fitz
        except ImportError:
            self.skipTest('PyMuPDF nie jest zainstalowane')
        from rk_unified_preview import serve_pdf_page
        p=self.dir/'pismo.pdf'
        with fitz.open() as pdf:
            page=pdf.new_page()
            page.insert_text((60,60),'Przykladowe pismo')
            pdf.save(str(p))
        preview=render_preview(p,p.name,'/draft/3/file',pdf_pages_base='/preview/draft/3/page')
        self.assertIn('/preview/draft/3/page/1',preview)
        h=HandlerStub(path='/preview/draft/3/page/1?zoom=1')
        serve_pdf_page(h,p,1)
        self.assertEqual(h.code,200)
        self.assertTrue(h.wfile.getvalue().startswith(b'\x89PNG'))

    def test_range_partial_and_suffix(self):
        p=self.f('movie.mp4',bytes(range(100)))
        h=HandlerStub({'Range':'bytes=10-19'})
        serve_local_file(h,p,p.name)
        self.assertEqual((h.code,h.wfile.getvalue(),h.headers_out.get('content-range')),(206,bytes(range(10,20)),'bytes 10-19/100'))
        h=HandlerStub({'Range':'bytes=-5'})
        serve_local_file(h,p,p.name)
        self.assertEqual(h.wfile.getvalue(),bytes(range(95,100)))
        h=HandlerStub({'Range':'bytes=110-'})
        serve_local_file(h,p,p.name)
        self.assertEqual(h.code,416)
    def test_attachment_and_filename(self):
        p=self.f('test.docx',b'ok')
        h=HandlerStub()
        serve_local_file(h,p,p.name)
        self.assertEqual(h.headers_out['content-disposition'].split(';')[0],'attachment')
        h=HandlerStub(path='/draft/1/file?download=1')
        serve_local_file(h,self.f('sound.mp3',b'ok'),'sound.mp3')
        self.assertEqual(h.headers_out['content-disposition'].split(';')[0],'attachment')
    def test_zip_traversal_is_only_listed_never_extracted(self):
        p=self.dir/'lista.zip'
        with zipfile.ZipFile(p,'w') as z:z.writestr('../niebezpieczne.txt','dane')
        h=render_preview(p,p.name,'/doc/file')
        self.assertIn('../niebezpieczne.txt',h)
        self.assertFalse((self.dir.parent/'niebezpieczne.txt').exists())
    def test_inbox_integration_and_idempotency(self):
        source="""from urllib.parse import quote
ALLOWED_SUFFIXES = {'.pdf', '.docx', '.txt', '.rtf', '.png', '.jpg', '.jpeg',
                    '.bmp', '.tif', '.tiff', '.webp'}
class InboxMixin:
    def inbox_page(self):
        # <label>Plik (PDF, DOCX, obraz lub TXT/RTF; maks. 20 MB)</label>
        # accept='.pdf,.docx,.txt,.rtf,.png,.jpg,.jpeg,.bmp,.tif,.tiff,.webp'
        pass
    def inbox_review(self, item_id):
        ext = Path(row['original_name']).suffix.lower()
        preview = 'preview'
        snippet = escape(row['extracted_text'][:20000]) or 'Brak tekstu. Zobacz oryginał.'
        body = \"<a class='btn small' href='/inbox/{item_id}/file' target='_blank' rel='noopener'>Otwórz oryginał</a>\"
    def inbox_file(self, item_id: int):
        self.send_response(200)
        self.send_header('Content-Type','application/pdf')
        self.send_header('Content-Length','100')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        try:
            self.wfile.write(b'dane testowe')
        except Exception:
            pass
    def inbox_approve(self, item_id: int, fields):
        pass
"""
        patched=apply_inbox(source)
        self.assertIn('render_preview(a.FILES_DIR',patched)
        self.assertIn(".mp4','.m4v'",patched)
        self.assertEqual(patched,apply_inbox(patched))

    def test_source_integration_signatures(self):
        # Testujemy samą logikę patchera na kopii neutralnego minimalnego szkieletu.
        mock='''VERSION = "0.3.2-dev1"
from rk_document_hub import DocumentHubMixin, case_document_rows, ensure_document_hub_schema
class Handler:
    def do_GET(self):
            if re.fullmatch(r"/document/\\d+/page/\\d+", path): return self.document_pdf_page(int(path.split("/")[2]), int(path.split("/")[4]))
            if re.fullmatch(r"/draft/\\d+/download", path): return self.draft_download(int(path.split("/")[2]))
    def document_view(self,did,qs=None):
        if ext=='.pdf':preview='pdf'
        elif ext in {'.docx','.txt','.md','.csv','.log','.rtf'}: preview=text_preview('Podgląd tekstowy dokumentu')
        elif ext in {'.xlsx','.xlsm'}: preview=text_preview('Podgląd arkusza kalkulacyjnego (wartości komórek)')
        elif ext in {'.png','.jpg','.jpeg','.gif','.webp','.bmp','.tif','.tiff'}:
            preview='image'
        else: preview=text_preview(f'Format {ext or "bez rozszerzenia"} nie ma własnego stabilnego podglądu')
    def document_file(self,did,download=False):
        ctype=mimetypes.guess_type(d['original_name'] or p.name)[0] or 'application/octet-stream'
        self.send_response(200)
    def document_relocate(self,did,f,files):
        pass
    def draft_view(self,did,message=''):
        file_buttons=f"<a class='btn' href='/draft/{did}/download'>Pobierz plik</a>" if d['stored_name'] else ''
        content='<h2>Treść projektu</h2>{content}</div>'
    def draft_download(self,did):
        pass
'''
        patched=apply_app(mock)
        self.assertIn('def unified_preview_asset(',patched)
        self.assertIn('VERSION = "0.3.3-dev1"',patched)
        self.assertEqual(patched,apply_app(patched))


if __name__=='__main__':unittest.main(verbosity=2)
