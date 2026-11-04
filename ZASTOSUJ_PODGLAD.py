# -*- coding: utf-8 -*-
"""RK KANCELARIA 0.3.3-dev1: bezpieczna integracja lokalnego podglądu.

Uruchom w katalogu repozytorium po wcześniejszej aktualizacji 0.3.2-dev1:
    python ZASTOSUJ_PODGLAD.py .

Najpierw sprawdza wszystkie kotwice i składnię w pamięci; dopiero potem
zastępuje app.py i rk_inbox.py. Katalog Data i bazy nie są modyfikowane.
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import sys
import tempfile
from pathlib import Path

MARK = 'from rk_unified_preview import render_preview, serve_local_file, serve_pdf_page, serve_tiff_as_png'


def once(s: str, old: str, new: str, label: str) -> str:
    n=s.count(old)
    if n!=1:raise RuntimeError(f'{label}: oczekiwano 1 wystąpienia, znaleziono {n}; nie zapisano zmian.')
    return s.replace(old,new,1)


def apply_app(s: str) -> str:
    if MARK in s:
        must=('def draft_inline_file(self,did):','def unified_preview_asset(self,kind,rid,part,page_no=None):',
              "VERSION = \"0.3.3-dev1\"", "render_preview(p,d['original_name'] or p.name", "self.unified_preview_asset(")
        if all(x in s for x in must):return s
        raise RuntimeError('Znaleziono niepełną wcześniejszą aktualizację podglądu — bez nadpisywania.')
    if 'VERSION = "0.3.2-dev1"' not in s:
        raise RuntimeError('Wymagana stabilna baza 0.3.2-dev1 (lub już kompletna aktualizacja).')
    s=once(s,'from rk_document_hub import DocumentHubMixin, case_document_rows, ensure_document_hub_schema',
           MARK+'\nfrom rk_document_hub import DocumentHubMixin, case_document_rows, ensure_document_hub_schema','import podglądu')
    s=once(s,'VERSION = "0.3.2-dev1"','VERSION = "0.3.3-dev1"','numer wersji')

    route_anchor='            if re.fullmatch(r"/document/\\d+/page/\\d+", path): return self.document_pdf_page(int(path.split("/")[2]), int(path.split("/")[4]))'
    route_new=(route_anchor+'\n'
               '            mm=re.fullmatch(r"/preview/(document|draft|inbox)/(\\d+)/(?:page/(\\d+)|image)",path)\n'
               '            if mm: return self.unified_preview_asset(mm.group(1),int(mm.group(2)),\n'
               '                "page" if mm.group(3) else "image",int(mm.group(3)) if mm.group(3) else None)')
    s=once(s,route_anchor,route_new,'trasa PDF/TIFF')
    s=once(s,'            if re.fullmatch(r"/draft/\\d+/download", path): return self.draft_download(int(path.split("/")[2]))',
           '            if re.fullmatch(r"/draft/\\d+/file", path): return self.draft_inline_file(int(path.split("/")[2]))\n'
           '            if re.fullmatch(r"/draft/\\d+/download", path): return self.draft_download(int(path.split("/")[2]))',
           'trasa strumieniowania projektu')

    start="        elif ext in {'.docx','.txt','.md','.csv','.log','.rtf'}: preview=text_preview('Podgląd tekstowy dokumentu')"
    stop='        else: preview=text_preview(f\'Format {ext or "bez rozszerzenia"} nie ma własnego stabilnego podglądu\')'
    if s.count(start)!=1 or s.count(stop)!=1:raise RuntimeError('Widok dokumentu zmienił strukturę; odmowa niepewnej podmiany.')
    a=s.index(start);b=s.index(stop,a)+len(stop)
    if b-a>4000 or a>b:raise RuntimeError('Niepoprawny zakres starego podglądu.')
    new=("        else:\n"
         "            preview=render_preview(p,d['original_name'] or p.name,f'/document/{did}/file',\n"
         "                pdf_pages_base=f'/document/{did}/page',image_url=f'/preview/document/{did}/image')")
    s=s[:a]+new+s[b:]

    # Ręcznie kontrolowany model plików chroni starsze dokumenty i powiązania.
    a="        ctype=mimetypes.guess_type(d['original_name'] or p.name)[0] or 'application/octet-stream'"
    b='    def document_relocate(self,did,f,files):'
    if s.count(a)!=1 or s.count(b)!=1:raise RuntimeError('Nie znaleziono pierwotnego strumieniowania dokumentu.')
    i=s.index(a);j=s.index(b,i)
    if j-i>2200 or j<i:raise RuntimeError('Niepoprawny zakres document_file.')
    s=s[:i]+"        return serve_local_file(self,p,d['original_name'] or p.name,download=download)\n\n"+s[j:]

    old="        file_buttons=f\"<a class='btn' href='/draft/{did}/download'>Pobierz plik</a>\" if d['stored_name'] else ''"
    new=(old+'\n'
         "        draft_preview=''\n"
         "        if d['stored_name']:\n"
         "            filename=d['stored_name']\n"
         "            p=(DRAFTS_DIR/filename).resolve()\n"
         "            if Path(filename).name==filename and p.parent==DRAFTS_DIR.resolve():\n"
         "                draft_preview=render_preview(p,d['original_name'] or filename,f'/draft/{did}/file',\n"
         "                    pdf_pages_base=f'/preview/draft/{did}/page',image_url=f'/preview/draft/{did}/image')\n"
         "            else: draft_preview=\"<div class='error'>Nieprawidłowa ścieżka pliku projektu.</div>\"")
    s=once(s,old,new,'karta projektu')
    s=once(s,"<h2>Treść projektu</h2>{content}</div>","<h2>Treść projektu</h2>{content}{draft_preview}</div>",'panel załącznika projektu')

    marker='    def draft_download(self,did):'
    impl='''    def draft_inline_file(self,did):
        with db() as con: d=con.execute('SELECT * FROM writing_projects WHERE id=?',(did,)).fetchone()
        if not d or not d['stored_name']: return self.send_error(404)
        stored=d['stored_name']
        if Path(stored).name!=stored: return self.send_error(404)
        p=(DRAFTS_DIR/stored).resolve()
        if p.parent!=DRAFTS_DIR.resolve() or not p.is_file(): return self.send_error(404)
        return serve_local_file(self,p,d['original_name'] or p.name)

    def unified_preview_asset(self,kind,rid,part,page_no=None):
        # Każda trasa trafia tutaj dopiero po require_auth() w do_GET.
        if kind=='document':
            with db() as con: d=con.execute('SELECT * FROM documents WHERE id=?',(rid,)).fetchone()
            if not d:return self.send_error(404)
            state,p,_=document_state(d)
            if state!='ok':return self.send_error(404)
            name=d['original_name'] or p.name
        elif kind=='draft':
            with db() as con: d=con.execute('SELECT stored_name,original_name FROM writing_projects WHERE id=?',(rid,)).fetchone()
            if not d or not d['stored_name']:return self.send_error(404)
            stored=d['stored_name']
            if Path(stored).name!=stored:return self.send_error(404)
            p=(DRAFTS_DIR/stored).resolve()
            if p.parent!=DRAFTS_DIR.resolve() or not p.is_file():return self.send_error(404)
            name=d['original_name'] or p.name
        elif kind=='inbox':
            with db() as con: d=con.execute('SELECT stored_name,original_name,status FROM inbox_items WHERE id=?',(rid,)).fetchone()
            if not d or d['status']!='pending' or not d['stored_name']:return self.send_error(404)
            stored=d['stored_name']
            folder=(FILES_DIR/'_inbox').resolve()
            if Path(stored).name!=stored:return self.send_error(404)
            p=(folder/stored).resolve()
            if p.parent!=folder or not p.is_file():return self.send_error(404)
            name=d['original_name'] or p.name
        else:return self.send_error(404)
        ext=Path(name).suffix.lower()
        if part=='page' and ext=='.pdf' and page_no:
            return serve_pdf_page(self,p,page_no)
        if part=='image' and ext in {'.tif','.tiff'}:
            return serve_tiff_as_png(self,p)
        return self.send_error(404)

'''
    s=once(s,marker,impl+marker,'metody podglądu')
    ast.parse(s,filename='app.py')
    return s


def apply_inbox(s:str) -> str:
    imported='from rk_unified_preview import render_preview, serve_local_file'
    if imported in s:
        if "pdf_pages_base=f'/preview/inbox/{item_id}/page'" in s and 'return serve_local_file(self,p,row[' in s:return s
        raise RuntimeError('Niepełna aktualizacja skrzynki wpływu.')
    s=once(s,'from urllib.parse import quote\n', 'from urllib.parse import quote\n'+imported+'\n','import preview do skrzynki')
    s=once(s,"ALLOWED_SUFFIXES = {'.pdf', '.docx', '.txt', '.rtf', '.png', '.jpg', '.jpeg',\n                    '.bmp', '.tif', '.tiff', '.webp'}",
           "ALLOWED_SUFFIXES = {'.pdf','.doc','.docx','.odt','.rtf','.txt','.md','.csv','.xlsx','.xlsm','.ods','.pptx',\n                    '.png','.jpg','.jpeg','.bmp','.gif','.tif','.tiff','.webp',\n                    '.mp3','.wav','.ogg','.oga','.m4a','.aac','.flac','.opus',\n                    '.mp4','.m4v','.webm','.mov','.avi','.mkv','.wmv','.mpg','.mpeg','.eml','.zip'}",
           'obsługiwane formaty wpływu')
    s=once(s,"<label>Plik (PDF, DOCX, obraz lub TXT/RTF; maks. 20 MB)</label>",
           "<label>Załącznik (pisma, zdjęcia, audio, wideo i inne; maks. 20 MB)</label>",
           'opis formatów')
    s=once(s,"accept='.pdf,.docx,.txt,.rtf,.png,.jpg,.jpeg,.bmp,.tif,.tiff,.webp'",
           "accept='.pdf,.doc,.docx,.odt,.rtf,.txt,.md,.csv,.xlsx,.xlsm,.ods,.pptx,.png,.jpg,.jpeg,.bmp,.gif,.tif,.tiff,.webp,.mp3,.wav,.ogg,.oga,.m4a,.aac,.flac,.opus,.mp4,.m4v,.webm,.mov,.avi,.mkv,.wmv,.mpg,.mpeg,.eml,.zip'",
           'pole wyboru pliku')
    start="        ext = Path(row['original_name']).suffix.lower()"
    end="        snippet = escape(row['extracted_text'][:20000]) or 'Brak tekstu. Zobacz oryginał.'"
    if s.count(start)!=1 or s.count(end)!=1:raise RuntimeError('Brak starych kotwic podglądu w skrzynce.')
    i=s.index(start);j=s.index(end,i)
    if j-i>1200:raise RuntimeError('Nieprawidłowy zakres HTML skrzynki.')
    replacement=("        preview = render_preview(a.FILES_DIR / '_inbox' / row['stored_name'], row['original_name'],\n"
                 "            f'/inbox/{item_id}/file',pdf_pages_base=f'/preview/inbox/{item_id}/page',\n"
                 "            image_url=f'/preview/inbox/{item_id}/image')\n")
    s=s[:i]+replacement+s[j:]
    s=once(s,"<a class='btn small' href='/inbox/{item_id}/file' target='_blank' rel='noopener'>Otwórz oryginał</a>",
           "<a class='btn small' href='/inbox/{item_id}/file?download=1'>Pobierz oryginał</a>",
           'przycisk w skrzynce')
    i=s.index('    def inbox_file(self, item_id: int):')
    j=s.index('    def inbox_approve(self, item_id: int, fields):',i)
    if not 300<j-i<2600: raise RuntimeError('Nieprawidłowy zakres wysyłania oryginału ze skrzynki.')
    implementation='''    def inbox_file(self, item_id: int):
        a=self._app()
        with a.db() as con:
            row=con.execute('SELECT original_name,stored_name,status FROM inbox_items WHERE id=?',(item_id,)).fetchone()
        if not row or row['status']!='pending' or not row['stored_name']:
            return self.send_error(404)
        stored=row['stored_name']
        folder=(a.FILES_DIR/'_inbox').resolve()
        if Path(stored).name!=stored:return self.send_error(404)
        p=(folder/stored).resolve()
        if p.parent!=folder or not p.is_file():return self.send_error(404)
        return serve_local_file(self,p,row['original_name'] or p.name)

'''
    s=s[:i]+implementation+s[j:]
    ast.parse(s,filename='rk_inbox.py')
    return s


def update(root:Path, dry_run:bool=False):
    root=root.resolve()
    files={'app.py':apply_app,'rk_inbox.py':apply_inbox}
    for name in ['rk_unified_preview.py',*files]:
        if not (root/name).is_file():raise RuntimeError('Brakuje pliku '+name)
    changes={}
    for name,func in files.items():
        original=(root/name).read_text(encoding='utf-8')
        result=func(original)
        compile(result,name,'exec')
        changes[name]=(original,result)
    if dry_run:
        print('Podgląd 0.3.3-dev1: wszystkie kotwice i składnia OK. Bez zapisu.')
        return
    # Zapisy atomowe, żadnych operacji na Data ani bazach użytkownika.
    modified=[]
    try:
        for name,(old,new) in changes.items():
            if new==old:continue
            target=root/name
            fd,temp=tempfile.mkstemp(prefix='.rk-preview-',suffix='.tmp',dir=root)
            try:
                with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as stream:stream.write(new)
                os.replace(temp,target)
                modified.append(name)
            finally:
                if os.path.exists(temp):os.unlink(temp)
    except Exception:
        for name in modified:(root/name).write_text(changes[name][0],encoding='utf-8')
        raise
    print('RK KANCELARIA 0.3.3-dev1: podgląd zintegrowany. Zmieniono: '+(', '.join(modified) if modified else 'brak (już aktualne)'))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('root',nargs='?',default='.')
    p.add_argument('--dry-run',action='store_true')
    args=p.parse_args()
    try:update(Path(args.root),args.dry_run)
    except Exception as exc:
        print('BŁĄD PODGLĄDU: '+str(exc),file=sys.stderr)
        raise SystemExit(1)
