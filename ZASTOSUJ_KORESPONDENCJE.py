# -*- coding: utf-8 -*-
"""Integracja RK KANCELARIA 0.3.5-dev1 (obieg korespondencji).

Nie dotyka Data ani bazy użytkownika. Sprawdza wszystkie kotwice przed zapisem,
kompiluje wynik, wykonuje atomowe podmiany i umożliwia bezpieczne powtórzenie.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

VERSION='0.3.5-dev1'
MARK='from rk_correspondence import CorrespondenceMixin, ensure_correspondence_schema'


def once(s,old,new,label):
    count=s.count(old)
    if count!=1:
        raise RuntimeError(f'{label}: znaleziono {count} wystąpień zamiast jednego — plik nie został zmieniony.')
    return s.replace(old,new,1)


def apply_app(src):
    if MARK in src:
        required=(
            'VERSION = "0.3.5-dev1"','SCHEMA_VERSION = 326',
            'class Handler(CorrespondenceMixin, ActionCenterMixin, DocumentHubMixin, InboxMixin, BaseHTTPRequestHandler):',
            'ensure_correspondence_schema(con)',
            'self.correspondence_page(qs)',
            'self.correspondence_save(fields)',
            'self.correspondence_followup(',
            "href='/correspondence/new?case_id=",
        )
        if all(x in src for x in required):return src
        raise RuntimeError('Niedokończona integracja 0.3.5: odmowa nadpisania źródeł.')
    if 'VERSION = "0.3.4-dev1"' not in src or 'SCHEMA_VERSION = 325' not in src:
        raise RuntimeError('Wymagana zintegrowana wersja 0.3.4-dev1.')
    if 'from rk_action_center import ActionCenterMixin, ensure_action_center_schema' not in src:
        raise RuntimeError('Brak Centrum decyzji 0.3.4 — aktualizacja przerwana.')
    src=once(src,'from rk_action_center import ActionCenterMixin, ensure_action_center_schema',
             'from rk_action_center import ActionCenterMixin, ensure_action_center_schema\n'+MARK,
             'import nowego modułu')
    src=once(src,'VERSION = "0.3.4-dev1"','VERSION = "0.3.5-dev1"','wersja')
    src=once(src,'SCHEMA_VERSION = 325','SCHEMA_VERSION = 326','schemat')
    src=once(src,'class Handler(ActionCenterMixin, DocumentHubMixin, InboxMixin, BaseHTTPRequestHandler):',
             'class Handler(CorrespondenceMixin, ActionCenterMixin, DocumentHubMixin, InboxMixin, BaseHTTPRequestHandler):',
             'dziedziczenie Handler')
    src=once(src,'        ensure_action_center_schema(con)',
             '        ensure_action_center_schema(con)\n        ensure_correspondence_schema(con)',
             'inicjalizacja bazy')
    src=once(src,'            ("/workflow", "☑", "Centrum decyzji", "workflow"),',
             '            ("/workflow", "☑", "Centrum decyzji", "workflow"),\n'
             '            ("/correspondence", "✉", "Korespondencja", "correspondence"),',
             'menu')
    src=once(src,'            if path == "/workflow": return self.action_center_page()',
             '            if path == "/workflow": return self.action_center_page()\n'
             '            if path == "/correspondence": return self.correspondence_page(qs)\n'
             '            if path == "/correspondence/new": return self.correspondence_form(qs)\n'
             '            if re.fullmatch(r"/correspondence/\\d+/edit",path): return self.correspondence_form(record_id=int(path.split("/")[2]))\n'
             '            if re.fullmatch(r"/correspondence/\\d+",path): return self.correspondence_detail(int(path.split("/")[2]))',
             'trasy GET')
    src=once(src,'            if path == "/inbox/upload": return self.inbox_upload(fields, files)',
             '            if path == "/inbox/upload": return self.inbox_upload(fields, files)\n'
             '            if path == "/correspondence/create": return self.correspondence_save(fields)\n'
             '            if re.fullmatch(r"/correspondence/\\d+/update",path): return self.correspondence_save(fields,int(path.split("/")[2]))\n'
             '            if re.fullmatch(r"/correspondence/\\d+/followup",path): return self.correspondence_followup(int(path.split("/")[2]),fields)',
             'trasy POST')
    src=once(src,'        max_chars=160_000; bodytxt,status=self._preview_text_now(d,p,ext)',
             "        toolbar += f\" <a class='btn' href='/correspondence/new?case_id={d['case_id']}&document_id={did}'>Zarejestruj korespondencję</a>\"\n"
             '        max_chars=160_000; bodytxt,status=self._preview_text_now(d,p,ext)',
             'link w dokumentach')
    anchor='        to_doc=f"<form method=\'post\' action=\'/draft/{did}/to-document\' style=\'display:inline\'><button class=\'btn primary\'>Dodaj do dokumentów sprawy</button></form>" if d[\'case_id\'] else \'\''
    src=once(src,anchor,anchor+"\n"
             '        corr_action=(f"<a class=\'btn\' href=\'/correspondence/new?case_id={d[\'case_id\']}&draft_id={did}\'>Zarejestruj wysyłkę</a>" if d[\'case_id\'] else \'\')',
             'link z projektu')
    src=once(src,'{center_action} {to_doc}','{center_action} {corr_action} {to_doc}','akcje projektu')
    compile(src,'app.py','exec')
    return src


def update(root:Path,dry_run=False):
    root=root.resolve()
    for name in ('app.py','README.md','rk_correspondence.py'):
        if not (root/name).is_file():raise RuntimeError('Brakuje pliku '+name)
    compile((root/'rk_correspondence.py').read_text(encoding='utf-8'),'rk_correspondence.py','exec')
    old=(root/'app.py').read_text(encoding='utf-8')
    new=apply_app(old)
    original_readme=(root/'README.md').read_text(encoding='utf-8')
    readme=original_readme
    for v in ('0.3.2-dev1','0.3.4-dev1'):
        if readme.startswith('# RK KANCELARIA '+v):
            readme=readme.replace('# RK KANCELARIA '+v,'# RK KANCELARIA 0.3.5-dev1',1)
    if '## Obieg korespondencji — 0.3.5-dev1' not in readme:
        readme += '''\n\n## Obieg korespondencji — 0.3.5-dev1\n\n- Lokalny rejestr korespondencji wychodzącej i przychodzącej przypisanej do spraw.\n- Odrębne stany: przygotowano, wysłano, doręczono, odpowiedziano, zamknięto.\n- Dowód nadania, dowód doręczenia, dokument źródłowy i projekt pisma są wskazywane z istniejących dokumentów bez ich kopiowania.\n- Powiązane odpowiedzi i historia zmian.\n- Ręcznie wpisana data **organizacyjna** oczekiwanej odpowiedzi pokazuje sugestię monitu.\n- Monit to zadanie tworzone dopiero po potwierdzeniu; bez wysyłania jakiejkolwiek korespondencji.\n- Program **nie** ustala skuteczności doręczenia, nie oblicza terminów procesowych i nie interpretuje treści korespondencji.\n- Addytywna, idempotentna migracja SQLite do schematu 326; podczas budowania nie otwiera plików Data użytkownika.\n'''
    if dry_run:
        print('Weryfikacja integratora 0.3.5 OK — bez zapisu plików.')
        return
    changes=[]
    try:
        for target,before,after in ((root/'app.py',old,new),(root/'README.md',original_readme,readme)):
            if before==after:continue
            fd,tmp=tempfile.mkstemp(prefix='.rk-corr-',suffix='.tmp',dir=root)
            try:
                with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:f.write(after)
                os.replace(tmp,target)
                changes.append((target,before))
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
    except Exception:
        for target,before in reversed(changes):target.write_text(before,encoding='utf-8')
        raise
    print('RK KANCELARIA 0.3.5-dev1: integracja zakończona. Zmiany: '+(', '.join(x.name for x,_ in changes) or 'brak (już aktualne)'))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('root',nargs='?',default='.')
    ap.add_argument('--dry-run',action='store_true')
    args=ap.parse_args()
    try:update(Path(args.root),args.dry_run)
    except Exception as exc:
        print('BŁĄD AKTUALIZACJI KORESPONDENCJI: '+str(exc),file=sys.stderr)
        raise SystemExit(1)
