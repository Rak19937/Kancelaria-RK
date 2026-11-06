#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RK KANCELARIA 0.4.0-dev1: kontrolowana migracja kodu A+B+C.

Rozdziela warstwy bez migracji SQLite i bez odczytu katalogu Data. Źródła
0.3.10 wymagane; operacja jest transakcyjna na poziomie plików źródłowych.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

OLD_VERSION = 'VERSION = "0.3.10-dev1"'
NEW_VERSION = 'VERSION = "0.4.0-dev1"'
MODULE_MARKER = '# RK040: modular architecture'

# Usługa wpływu jest w paczce instalatora: na GitHub wystarczą pliki główne.
SERVICE_CODE = '"""RK KANCELARIA 0.4: staging pism przed akceptacją przez człowieka.\n\nNie tworzy dokumentu w sprawie ani zadań. Zmiana stanu wyłącznie po\nręcznym zatwierdzeniu, obsługiwanym w dotychczasowym InboxMixin.\n"""\nfrom __future__ import annotations\n\nimport hashlib\nimport json\nimport uuid\nfrom pathlib import Path\n\nfrom rk_domains.inbox.analysis import analyze_letter\n\n\nclass InboxUploadValidationError(ValueError):\n    def __init__(self, message: str, status: int = 400):\n        super().__init__(message)\n        self.status = status\n\n\ndef stage_inbox_upload(app, uploaded, author: str, *, allowed_suffixes: set[str], max_bytes: int) -> int:\n    """Umieść wpływ w buforze; nigdy nie przypisuj go automatycznie do sprawy."""\n    if not isinstance(uploaded, tuple) or len(uploaded) < 2 or not uploaded[0] or not isinstance(uploaded[1], bytes):\n        raise InboxUploadValidationError(\'Wskaż prawidłowy plik.\')\n    name = app.safe_filename(uploaded[0])\n    data = uploaded[1]\n    suffix = Path(name).suffix.lower()\n    if suffix not in allowed_suffixes:\n        raise InboxUploadValidationError(\'Format pliku nie jest obsługiwany przez skrzynkę wpływu.\')\n    if not data or len(data) > max_bytes:\n        raise InboxUploadValidationError(\'Plik musi mieć od 1 bajta do 20 MB.\', 413)\n\n    dest = app.FILES_DIR / \'_inbox\' / (uuid.uuid4().hex + suffix)\n    try:\n        extracted, used, status, language = app.extract_document_text(name, data)\n        analysis = analyze_letter(extracted)\n        app.atomic_write_bytes(dest, data)\n        with app.db() as con:\n            cur = con.execute(\'\'\'INSERT INTO inbox_items\n                (original_name, stored_name, file_hash, extracted_text, ocr_status,\n                 ocr_used, ocr_language, suggestions_json, created_by)\n                VALUES(?,?,?,?,?,?,?,?,?)\'\'\',\n                (name, dest.name, hashlib.sha256(data).hexdigest(), extracted[:5000000],\n                 status, int(bool(used)), language,\n                 json.dumps(analysis, ensure_ascii=False), author))\n            return int(cur.lastrowid)\n    except Exception:\n        dest.unlink(missing_ok=True)\n        raise\n'


def function_source(src: str, name: str, klass: str | None = None) -> str:
    tree = ast.parse(src)
    nodes = tree.body
    if klass:
        found = [n for n in nodes if isinstance(n, ast.ClassDef) and n.name == klass]
        if len(found) != 1:
            raise RuntimeError(f'Nie znaleziono klasy {klass}')
        nodes = found[0].body
    found = [n for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if len(found) != 1:
        raise RuntimeError(f'Nie znaleziono jednoznacznej funkcji {klass + "." if klass else ""}{name}')
    node = found[0]
    if klass:
        begin = node.lineno
    else:
        begin = min([node.lineno] + [d.lineno for d in node.decorator_list])
    return ''.join(src.splitlines(keepends=True)[begin - 1:node.end_lineno]).rstrip('\n') + '\n'


def function_replace(src: str, name: str, replacement: str, klass: str | None = None) -> str:
    tree = ast.parse(src)
    nodes = tree.body
    if klass:
        nodes = next((n.body for n in nodes if isinstance(n, ast.ClassDef) and n.name == klass), None)
        if nodes is None: raise RuntimeError(f'Brak klasy: {klass}')
    found = [n for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if len(found) != 1: raise RuntimeError(f'Brak jednoznacznej metody: {name}')
    node = found[0]
    start = min([node.lineno] + ([] if klass else [d.lineno for d in node.decorator_list]))
    lines = src.splitlines(keepends=True)
    lines[start - 1:node.end_lineno] = [replacement.rstrip() + '\n'] if replacement else []
    return ''.join(lines)


def remove_constants(src: str, names: set[str]) -> str:
    nodes = ast.parse(src).body
    found = {}
    for node in nodes:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            key = node.targets[0].id
            if key in names:
                found[key] = (node.lineno, node.end_lineno)
    if set(found) != names:
        raise RuntimeError(f'Brak stałych: {names - set(found)}')
    lines = src.splitlines(keepends=True)
    for start, end in sorted(found.values(), reverse=True):
        del lines[start - 1:end]
    return ''.join(lines)


def append_import(src: str, anchor: str, block: str, where: str) -> str:
    if src.count(anchor) != 1:
        raise RuntimeError(f'{where}: brak dokładnej kotwicy importu')
    return src.replace(anchor, anchor + block.rstrip('\n') + '\n', 1)


def source_package(*items: str) -> str:
    return '# RK KANCELARIA 0.4.0-dev1 — osobne odpowiedzialności, bez importu app.py.\n'


def stage(repo: Path, package: Path) -> dict[Path, str]:
    required = ('app.py','rk_inbox.py','rk_workspace_plus.py','rk_correspondence.py','rk_document_hub.py')
    sources = {}
    for name in required:
        f = repo/name
        if not f.is_file(): raise RuntimeError(f'Brak: {name}')
        sources[name] = f.read_text(encoding='utf-8')
    app = sources['app.py']
    if NEW_VERSION in app:
        for rel in ('rk_core/database.py','rk_core/files.py','rk_core/http.py',
                    'rk_core/diagnostics.py','rk_domains/documents/ocr.py',
                    'rk_domains/inbox/analysis.py','rk_domains/inbox/service.py',
                    'rk_domains/cases/repository.py','rk_domains/tasks/assignments.py',
                    'rk_domains/terms/validation.py','rk_domains/correspondence/rules.py'):
            if not (repo/rel).is_file():
                raise RuntimeError('Wersja 0.4 ma niekompletne moduły: '+rel)
        return {}
    if OLD_VERSION not in app:
        raise RuntimeError('Wymagana wersja 0.3.10-dev1. Przerwano bez zmian.')
    for snippet in ('def extract_document_text(', 'def parse_multipart(', 'def atomic_write_bytes(',
                    'def db():','def load_external_signature_map(', 'class InboxMixin:'):
        if snippet not in ('\n'+app+'\n'+sources['rk_inbox.py']):
            raise RuntimeError('Źródło ma inną strukturę: '+snippet)

    built: dict[str, str] = {}
    # ETAP A: transakcje, pliki, HTTP i diagnostyka. Kontrakt API zostaje.
    db_src = function_source(app,'db').replace('def db():','def db_connection(db_path, data_dir):',1)
    db_src = db_src.replace('DATA_DIR.mkdir(', 'data_dir.mkdir(').replace('sqlite3.connect(DB_PATH,', 'sqlite3.connect(db_path,')
    built['rk_core/database.py'] = ('"""Krótko żyjące transakcje SQLite. Bez globalnego stanu aplikacji."""\n'
         'from __future__ import annotations\nimport sqlite3\nfrom contextlib import contextmanager\n\n'
         + db_src.replace('@contextlib.contextmanager', '@contextmanager', 1))
    app = function_replace(app,'db',
         '@contextlib.contextmanager\ndef db():\n    """Zachowane API: połączenie z bazą na kontekst żądania."""\n'
         '    with db_connection(DB_PATH, DATA_DIR) as con:\n        yield con\n')

    parser = function_source(app, 'parse_multipart')
    built['rk_core/http.py'] = ('"""Obsługa formularzy multipart; żadnej zależności od serwera aplikacji."""\n'
         'from __future__ import annotations\nfrom email.parser import BytesParser\n'
         'from email.policy import default as email_policy\n\n'+parser)
    app = function_replace(app,'parse_multipart','')

    writer = function_source(app,'atomic_write_bytes')
    built['rk_core/files.py'] = ('"""Zapis plików przez plik tymczasowy i os.replace."""\n'
          'from __future__ import annotations\nimport os\nimport uuid\nfrom pathlib import Path\n\n'+writer)
    app = function_replace(app,'atomic_write_bytes','')

    built['rk_core/diagnostics.py'] = '''"""Lokalne logowanie problemów; nie wysyła żadnych danych do sieci."""
from __future__ import annotations
import traceback
from pathlib import Path
from datetime import datetime


def write_exception(error_log: Path, path: str, exc: Exception) -> None:
    try:
        error_log.parent.mkdir(parents=True, exist_ok=True)
        with error_log.open('a', encoding='utf-8') as f:
            f.write(f"\\n[{datetime.now().isoformat(timespec='seconds')}] {path}\\n")
            traceback.print_exc(file=f)
    except Exception:
        pass


def write_slow_request(perf_log: Path, path: str, elapsed: float) -> None:
    if elapsed < 0.75: return
    try:
        perf_log.parent.mkdir(parents=True, exist_ok=True)
        with perf_log.open('a', encoding='utf-8') as f:
            f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {elapsed*1000:.0f} ms | {path}\\n")
    except Exception:
        pass
'''
    app = function_replace(app, 'log_app_exception',
        'def log_app_exception(path: str, exc: Exception) -> None:\n'
        '    return write_exception(ERROR_LOG, path, exc)\n')
    app = function_replace(app, 'log_slow_request',
        'def log_slow_request(path: str, elapsed: float) -> None:\n'
        '    return write_slow_request(PERF_LOG, path, elapsed)\n')

    # ETAP B: sprawy (repo), dokumenty (SQL/OCR), zadania, terminy, korespondencja, wpływ.
    case_query = function_source(app, 'load_external_signature_map')
    built['rk_domains/cases/repository.py'] = ('"""Odczyt sygnatur spraw — jedno zbiorcze zapytanie SQLite."""\n'
        'from __future__ import annotations\nimport sqlite3\n\n' + case_query)
    app = function_replace(app,'load_external_signature_map','')

    document_ocr = function_source(app,'extract_document_text')
    document_ocr = document_ocr.replace(
        'def extract_document_text(filename: str, data: bytes, force_ocr: bool=False) -> tuple[str,int,str,str]:',
        'def extract_document_text(filename: str, data: bytes, force_ocr: bool=False, *, find_tesseract, ocr_language_for, run_tesseract) -> tuple[str,int,str,str]:',1)
    if document_ocr.count('_run_tesseract_on_file(') != 2:
        raise RuntimeError('OCR: liczba wywołań Tesseract zmieniona; przerwano')
    document_ocr = document_ocr.replace('_run_tesseract_on_file(', 'run_tesseract(')
    built['rk_domains/documents/ocr.py'] = ('"""Wydzielony odczyt tekstu z dokumentów; zależności OCR przekazywane jawnie."""\n'
        'from __future__ import annotations\nimport io\nimport os\nimport tempfile\nimport zipfile\n'
        'import xml.etree.ElementTree as ET\nfrom pathlib import Path\n\n' + document_ocr)
    app = function_replace(app,'extract_document_text',
        'def extract_document_text(filename: str, data: bytes, force_ocr: bool=False) -> tuple[str,int,str,str]:\n'
        '    """Kompatybilność interfejsu; obsługę formatów realizuje moduł dokumentów."""\n'
        '    return _extract_document_text(filename, data, force_ocr,\n'
        '        find_tesseract=find_tesseract, ocr_language_for=ocr_language_for,\n'
        '        run_tesseract=_run_tesseract_on_file)\n')

    document_hub = sources['rk_document_hub.py']
    repository = function_source(document_hub,'case_document_rows')
    built['rk_domains/documents/repository.py'] = (
        '"""Zapytania o dokumenty jednej sprawy (bez kopiowania plików)."""\n'
        'from __future__ import annotations\nimport sqlite3\n\n' + repository)
    document_hub = function_replace(document_hub,'case_document_rows','')
    document_hub = append_import(document_hub,'from urllib.parse import quote\n',
         'from rk_domains.documents.repository import case_document_rows\n','rk_document_hub.py')
    sources['rk_document_hub.py'] = document_hub

    # Odrębna logika terminów i przypisywania zadań.
    ws = sources['rk_workspace_plus.py']
    built['rk_domains/terms/validation.py'] = ('"""Daty i godziny kontrolne (bez automatycznego liczenia terminów prawnych)."""\n'
        'from __future__ import annotations\nimport re\nfrom datetime import date\n\n'
        + function_source(ws,'date_iso') + '\n' + function_source(ws,'time_hm'))
    for name in ('date_iso','time_hm'):
        ws=function_replace(ws,name,'')
    built['rk_domains/tasks/assignments.py'] = ('"""Przypisywanie użytkowników do zadań: SQL bez warstwy HTTP i HTML."""\n'
        'from __future__ import annotations\n\n'
        + '\n'.join(function_source(sources['rk_workspace_plus.py'],n)
                     for n in ('selected_ids','set_task_assignees','task_assignees_map')))
    for name in ('selected_ids','set_task_assignees','task_assignees_map'):
        ws=function_replace(ws,name,'')
    ws=append_import(ws,'from urllib.parse import quote\n',
        'from rk_domains.terms.validation import date_iso, time_hm\n'
        'from rk_domains.tasks.assignments import selected_ids, set_task_assignees, task_assignees_map\n',
        'rk_workspace_plus.py')
    sources['rk_workspace_plus.py']=ws

    corr = sources['rk_correspondence.py']
    built['rk_domains/correspondence/rules.py'] = (
        '"""Czyste reguły pomocnicze korespondencji, bez działań w bazie."""\n'
        'from __future__ import annotations\nfrom datetime import date\n\n'
        + function_source(corr,'iso_date') + '\n' + function_source(corr,'needs_followup'))
    corr=function_replace(corr,'iso_date','')
    corr=function_replace(corr,'needs_followup','')
    corr=append_import(corr,'from datetime import date\n',
        'from rk_domains.correspondence.rules import iso_date, needs_followup\n','rk_correspondence.py')
    sources['rk_correspondence.py']=corr

    inbox=sources['rk_inbox.py']
    constants=[]
    tree=ast.parse(inbox)
    for name in ('SIGNATURE_RE','DEADLINE_RE'):
        found=[n for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1
               and isinstance(n.targets[0],ast.Name) and n.targets[0].id==name]
        if len(found)!=1: raise RuntimeError('Brak wzorca '+name)
        constants.append(''.join(inbox.splitlines(keepends=True)[found[0].lineno-1:found[0].end_lineno]))
    built['rk_domains/inbox/analysis.py'] = (
        '"""Reguły analizy pism: wyłącznie sugestie, bez automatycznych decyzji."""\n'
        'from __future__ import annotations\nimport re\n\n'
        + '\n'.join(constants) + '\n' + function_source(inbox,'_excerpt') + '\n'
        + function_source(inbox,'analyze_letter'))
    inbox=remove_constants(inbox, {'SIGNATURE_RE','DEADLINE_RE'})
    inbox=function_replace(inbox,'_excerpt','')
    inbox=function_replace(inbox,'analyze_letter','')
    inbox=append_import(inbox,'from urllib.parse import quote\n',
        'from rk_domains.inbox.analysis import analyze_letter, SIGNATURE_RE, DEADLINE_RE, _excerpt\n'
        'from rk_domains.inbox.service import stage_inbox_upload, InboxUploadValidationError\n',
        'rk_inbox.py')
    inbox=function_replace(inbox,'inbox_upload',
'''    def inbox_upload(self, fields, files):
        """Kontroler: walidacja i zapis pliku są w rk_domains.inbox.service."""
        a = self._app()
        uploaded = files.get('file') if isinstance(files, dict) else None
        try:
            item_id = stage_inbox_upload(a, uploaded, self.current_author(fields),
                allowed_suffixes=ALLOWED_SUFFIXES, max_bytes=MAX_INBOX_BYTES)
        except InboxUploadValidationError as exc:
            return self._inbox_error(str(exc), exc.status)
        except Exception as exc:
            a.log_app_exception('/inbox/upload', exc)
            return self._inbox_error('Nie udało się przeanalizować pliku. Oryginał nie został dopisany do sprawy.', 500)
        return self.redirect(f'/inbox/{item_id}')
''',klass='InboxMixin')
    sources['rk_inbox.py']=inbox

    built['rk_domains/inbox/service.py']=SERVICE_CODE

    app = append_import(app, 'from rk_paths import resolve_runtime_paths, installed_data_dir\n',
        'from rk_core.database import db_connection\n'
        'from rk_core.http import parse_multipart\n'
        'from rk_core.files import atomic_write_bytes\n'
        'from rk_core.diagnostics import write_exception, write_slow_request\n'
        'from rk_domains.documents.ocr import extract_document_text as _extract_document_text\n'
        'from rk_domains.cases.repository import load_external_signature_map\n', 'app.py')
    if app.count(OLD_VERSION)!=1:raise RuntimeError('Nieoczekiwana liczba oznaczeń wersji 0.3.10')
    app=app.replace(OLD_VERSION,NEW_VERSION,1)
    sources['app.py']=app

    for sub in ('rk_core', 'rk_domains','rk_domains/cases','rk_domains/documents',
                'rk_domains/tasks','rk_domains/terms','rk_domains/correspondence','rk_domains/inbox'):
        init = sub+'/__init__.py'
        if not (repo/init).is_file():built[init]='"""Moduły RK KANCELARIA 0.4.0-dev1."""\n'
    all_changes={repo/k:v for k,v in {**sources,**built}.items()}
    # Preflight bez modyfikacji danych użytkownika.
    for path, content in all_changes.items():
        if path.suffix=='.py':compile(content,str(path),'exec')
    for rel in built:
        target=repo/rel
        if target.is_file() and target.read_text(encoding='utf-8')!=built[rel]:
            raise RuntimeError(f'Nowy moduł już istnieje z inną treścią: {rel}. Nie nadpisano.')
    return all_changes


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def apply(repo: Path, package: Path, *, dry_run: bool=False) -> str:
    repo=repo.resolve()
    changes=stage(repo, package)
    if not changes:return 'Wersja 0.4.0-dev1 już zainstalowana. Bez zmian.'
    if dry_run:
        return f'DRY RUN OK: {len(changes)} plików; nie dotknięto Data ani bazy.'
    backup=repo/'.rk_backup_before_040'
    if backup.exists():
        raise RuntimeError('Katalog kopii aktualizacji 0.4 już istnieje. Nie nadpisano go.')
    originals={p: p.read_bytes() if p.is_file() else None for p in changes}
    backup.mkdir(parents=True,exist_ok=False)
    manifest={}
    for path,raw in originals.items():
        rel=path.relative_to(repo).as_posix()
        if raw is None:
            manifest[rel]={'existed':False}
        else:
            manifest[rel]={'existed':True,'sha256':_sha(raw)}
            dest=backup/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
    (backup/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    installed=[]
    try:
        for p,content in changes.items():
            p.parent.mkdir(parents=True,exist_ok=True)
            fd,tmp=tempfile.mkstemp(prefix='.rk040_',dir=p.parent)
            try:
                with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
                    f.write(content);f.flush();os.fsync(f.fileno())
                os.replace(tmp,p)
                installed.append(p)
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
    except Exception:
        for path in reversed(installed):
            data=originals[path]
            if data is None:path.unlink(missing_ok=True)
            else:path.write_bytes(data)
        raise
    return f'RK KANCELARIA 0.4.0-dev1: zmieniono {len(changes)} plików. Kopia: {backup.name}'


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('repo',nargs='?',default='.')
    p.add_argument('--dry-run',action='store_true')
    a=p.parse_args(argv)
    print(apply(Path(a.repo), Path(__file__).resolve().parent, dry_run=a.dry_run))
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print('BŁĄD AKTUALIZACJI 0.4:',exc,file=sys.stderr)
        raise SystemExit(2)
