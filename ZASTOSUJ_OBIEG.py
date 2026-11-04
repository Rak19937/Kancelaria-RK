# -*- coding: utf-8 -*-
"""Wdróż RK KANCELARIA 0.3.4-dev1 na istniejącą wersję 0.3.3-dev1.

Bezpieczny patch źródeł app.py i README.md: wszystkie kotwice weryfikowane
przed zapisem, transakcja na plikach, nie otwiera Data ani bazy użytkownika.
Idempotentny — ponowne uruchomienie nie dubluje tras ani zmian.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile

VERSION = '0.3.4-dev1'
MARK = 'from rk_action_center import ActionCenterMixin, ensure_action_center_schema'


def once(s, old, new, label):
    occurrences = s.count(old)
    if occurrences != 1:
        raise RuntimeError(f'{label}: oczekiwano jednego fragmentu, wykryto {occurrences}. Nie dokonano zmian.')
    return s.replace(old, new, 1)


def apply_app(src):
    if MARK in src:
        must = ('VERSION = "0.3.4-dev1"', 'SCHEMA_VERSION = 325',
                'class Handler(ActionCenterMixin, DocumentHubMixin, InboxMixin, BaseHTTPRequestHandler):',
                'ensure_action_center_schema(con)',
                'self.action_center_analyze(', 'self.action_center_decide(',
                'self.action_center_page()', '/workflow/review/',
                "href='/workflow'")
        if all(x in src for x in must):
            return src
        raise RuntimeError('Znaleziono niepełną aktualizację Centrum decyzji. Nie nadpisano pliku.')

    if 'VERSION = "0.3.3-dev1"' not in src or 'SCHEMA_VERSION = 324' not in src:
        raise RuntimeError('Wymagana jest poprawnie zintegrowana wersja 0.3.3-dev1.')
    if 'from rk_unified_preview import render_preview, serve_local_file, serve_pdf_page, serve_tiff_as_png' not in src:
        raise RuntimeError('Brak modułu podglądu 0.3.3 — nie wykonano zmian.')

    src = once(src,
        'from rk_unified_preview import render_preview, serve_local_file, serve_pdf_page, serve_tiff_as_png',
        'from rk_unified_preview import render_preview, serve_local_file, serve_pdf_page, serve_tiff_as_png\n'+MARK,
        'import Centrum decyzji')
    src = once(src, 'VERSION = "0.3.3-dev1"', 'VERSION = "0.3.4-dev1"', 'wersja')
    src = once(src, 'SCHEMA_VERSION = 324', 'SCHEMA_VERSION = 325', 'schemat bazy')
    src = once(src, 'class Handler(DocumentHubMixin, InboxMixin, BaseHTTPRequestHandler):',
        'class Handler(ActionCenterMixin, DocumentHubMixin, InboxMixin, BaseHTTPRequestHandler):',
        'dziedziczenie Handler')
    src = once(src,'        ensure_document_hub_schema(con)',
        '        ensure_document_hub_schema(con)\n        ensure_action_center_schema(con)', 'inicjalizacja baz')
    src = once(src,'            ("/inbox", "✉", "Skrzynka wpływu", "inbox"),',
        '            ("/inbox", "✉", "Skrzynka wpływu", "inbox"),\n'
        '            ("/workflow", "☑", "Centrum decyzji", "workflow"),', 'menu')
    src = once(src,'            if path == "/inbox": return self.inbox_page()',
        '            if path == "/inbox": return self.inbox_page()\n'
        '            if path == "/workflow": return self.action_center_page()\n'
        '            if re.fullmatch(r"/workflow/review/\\d+",path): return self.action_center_review_page(int(path.split("/")[3]))',
        'GET')
    src = once(src,'            if path == "/inbox/upload": return self.inbox_upload(fields, files)',
        '            if path == "/inbox/upload": return self.inbox_upload(fields, files)\n'
        '            if re.fullmatch(r"/workflow/analyze/(document|draft)/\\d+",path):\n'
        '                return self.action_center_analyze(path.split("/")[3],int(path.split("/")[4]),fields)\n'
        '            if re.fullmatch(r"/workflow/review/\\d+/decide",path):\n'
        '                return self.action_center_decide(int(path.split("/")[3]),fields)\n'
        '            if re.fullmatch(r"/workflow/review/\\d+/add",path):\n'
        '                return self.action_center_add(int(path.split("/")[3]),fields)',
        'POST')
    src = once(src,
        '        toolbar += f" <a class=\'btn\' href=\'/document/{did}/links\'>Powiązania spraw</a>"',
        '        toolbar += f" <a class=\'btn\' href=\'/document/{did}/links\'>Powiązania spraw</a>"\n'
        '        toolbar += (f" <form method=\'post\' action=\'/workflow/analyze/document/{did}\' "\n'
        '                    "style=\'display:inline\'><button class=\'btn primary\'>Zaproponuj czynności</button></form>"\n'
        '                    " <a class=\'btn\' href=\'/workflow\'>Centrum decyzji</a>")',
        'akcje dokumentu')
    draft_anchor = '        file_buttons=f"<a class=\'btn\' href=\'/draft/{did}/download\'>Pobierz plik</a>" if d[\'stored_name\'] else \'\''
    src = once(src,draft_anchor,draft_anchor+'\n'
        '        center_action=(f"<form method=\'post\' action=\'/workflow/analyze/draft/{did}\' "\n'
        '                       "style=\'display:inline\'><button class=\'btn primary\'>Zaproponuj czynności</button></form>")',
        'przycisk projektu')
    src = once(src,'{file_buttons} {to_doc}', '{file_buttons} {center_action} {to_doc}', 'formularz projektu')
    compile(src, 'app.py', 'exec')
    return src


def update(root: Path, dry_run=False):
    root=root.resolve()
    for name in ('app.py','README.md','rk_action_center.py'):
        if not (root/name).is_file():
            raise RuntimeError(f'Brakuje pliku {name}.')
    compile((root/'rk_action_center.py').read_text(encoding='utf-8'),'rk_action_center.py','exec')
    old=(root/'app.py').read_text(encoding='utf-8')
    new=apply_app(old)
    readme=(root/'README.md').read_text(encoding='utf-8')
    if readme.startswith('# RK KANCELARIA 0.3.2-dev1'):
        readme=readme.replace('# RK KANCELARIA 0.3.2-dev1','# RK KANCELARIA 0.3.4-dev1',1)
    if '## Centrum decyzji — 0.3.4-dev1' not in readme:
        readme += '''\n\n## Centrum decyzji — 0.3.4-dev1\n\n- Lokalna, regułowa analiza tekstu istniejących dokumentów i projektów pism.\n- Propozycje czynności, monitów i sprawdzenia terminów do poprawienia, odrzucenia lub zatwierdzenia.\n- Powiązanie zapisanych zadań ze źródłem w historii, bez wysyłania danych do sieci.\n- Przed wpisaniem terminu procesowego trzeba ręcznie potwierdzić daty, podstawę i sposób wyliczenia.\n- OCR skanów i transkrypcja nagrań nie są zgadywane; gdy nie ma tekstu, wymagana jest ręczna ocena.\n- Addytywna migracja schematu SQLite do wersji 325. Nie dotyka plików użytkownika podczas kompilacji.\n'''
    updates=[(root/'app.py',old,new),(root/'README.md',(root/'README.md').read_text(encoding='utf-8'),readme)]
    if dry_run:
        print('RK KANCELARIA 0.3.4-dev1 — weryfikacja integratora poprawna. Bez zapisu.')
        return
    changed=[]
    try:
        for target,before,after in updates:
            if before==after:continue
            fd,tmp=tempfile.mkstemp(prefix='.rk-workflow-',suffix='.tmp',dir=root)
            try:
                with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as stream:
                    stream.write(after)
                os.replace(tmp,target)
                changed.append((target,before))
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
    except Exception:
        for target,before in reversed(changed):target.write_text(before,encoding='utf-8')
        raise
    print('RK KANCELARIA 0.3.4-dev1: połączono Centrum decyzji. Zmiany: '+
          (', '.join(x.name for x,_ in changed) if changed else 'brak — aktualizacja już obecna'))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('root',nargs='?',default='.')
    ap.add_argument('--dry-run',action='store_true')
    args=ap.parse_args()
    try:update(Path(args.root),args.dry_run)
    except Exception as exc:
        print('BŁĄD INTEGRACJI CENTRUM DECYZJI: '+str(exc),file=sys.stderr)
        raise SystemExit(1)
