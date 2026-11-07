#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RK KANCELARIA 0.4.0-dev3 - idempotent, rollback-safe source update.

Run once from source repository before compilation. This script never opens Data.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import os
import tempfile
from pathlib import Path

VERSION_OLD = 'VERSION = "0.4.0-dev2"'
VERSION_NEW = 'VERSION = "0.4.0-dev3"'
MARKER = 'RK_DEV3_LEGALTECH_NAV_20261107'
MODULES = ('rk_dev3.py','rk_dev3_core.py','rk_dev3_calendar.py','assets/rk_dev3_nav.js','assets/rk_dev3_nav.css','TEST_RK_DEV3.py','TEST_MIGRATOR_040_DEV3.py')


def once(source: str, old: str, new: str, name: str) -> str:
    count=source.count(old)
    if count!=1:
        raise RuntimeError(f'{name}: niejednoznaczny kod źródłowy (kotwic: {count}); niczego nie zmieniono.')
    return source.replace(old,new,1)


def read_repo(root: Path):
    originals={}
    for rel in ('app.py','rk_navigation.py','rk_core/schema_version.py',
                'TEST_ARCHITEKTURA_040.py','TEST_STABILIZACJA_040_DEV2.py','RAPORT_JAKOSCI_040.py',
                'AUDYT_I_TESTY_RK_040_DEV2.py','requirements.txt','RK_KANCELARIA_PORTABLE.spec'):
        src=root/rel
        if not src.is_file():raise RuntimeError('Brak pliku: '+rel)
        originals[rel]=src.read_text(encoding='utf-8')
    for rel in MODULES:
        if not (root/rel).is_file():raise RuntimeError('Brak nowego modułu: '+rel)
    return originals


def changes(root: Path):
    old=read_repo(root)
    app=old['app.py']
    if VERSION_NEW in app:
        if MARKER not in app:raise RuntimeError('Znaleziono dev3 bez znacznika aktualizacji')
        for rel,fragment in (('rk_navigation.py',"'/worktime'"),
            ('rk_core/schema_version.py','SCHEMA_VERSION = 331'),
            ('requirements.txt','tzdata>=2025.2,<2028'),
            ('RK_KANCELARIA_PORTABLE.spec',"'tzdata'"),
            ('TEST_ARCHITEKTURA_040.py',VERSION_NEW)):
            if fragment not in old[rel]:raise RuntimeError('Niekompletna instalacja dev3: '+rel)
        return {}
    if app.count(VERSION_OLD)!=1:raise RuntimeError('Wymagana działająca wersja 0.4.0-dev2')
    app=once(app,VERSION_OLD,VERSION_NEW+'\n'+MARKER+' = True','wersja')
    app=once(app,'from rk_inbox import InboxMixin, ensure_inbox_schema',
        'from rk_inbox import InboxMixin, ensure_inbox_schema\nfrom rk_dev3 import Dev3Mixin\nfrom rk_dev3_core import ensure_dev3_schema',
        'import dev3')
    app=once(app,'    start_worker(sys.modules[__name__])',
        '    with db() as con:\n        ensure_dev3_schema(con)\n    start_worker(sys.modules[__name__])','migracja schematu')
    app=once(app,'class Handler(CaseflowMixin, CaseCategoryMixin,',
        'class Handler(Dev3Mixin, CaseflowMixin, CaseCategoryMixin,','rejestracja mixin')
    app=once(app,'<div class="app"><aside class="sidebar"><div class="brand">',
        '<div class="app"><aside class="sidebar"><div class="dev3-nav-controls"><button type="button" data-dev3-nav-toggle class="dev3-nav-trigger" aria-label="Otwórz lub przypnij menu" aria-expanded="false" title="Rozwiń menu">☰</button><button type="button" data-dev3-nav-pin class="dev3-nav-pin" aria-label="Przypnij menu" aria-pressed="false" title="Przypnij menu">📌</button></div><div class="dev3-nav-filter"><input type="search" data-dev3-nav-filter placeholder="Szukaj zakładki…" aria-label="Wyszukaj zakładkę"></div><div class="brand">',
        'panel boczny')
    app=once(app,'<link rel="stylesheet" href="/assets/rk_ux.css?v={VERSION}">',
        '<link rel="stylesheet" href="/assets/rk_ux.css?v={VERSION}">\n<link rel="stylesheet" href="/assets/rk_dev3_nav.css?v={VERSION}">',
        'CSS nawigacji')
    app=once(app,'<script src="/assets/rk_ux.js?v={VERSION}" defer></script></body></html>',
        '<script src="/assets/rk_ux.js?v={VERSION}" defer></script><script src="/assets/rk_dev3_nav.js?v={VERSION}" defer></script></body></html>',
        'JS nawigacji')
    app=once(app,'            if dispatch_static_get(self, path, qs): return',
        '            if self.dev3_get(path, qs): return\n            if dispatch_static_get(self, path, qs): return',
        'routing GET')
    app=once(app,'            if dispatch_static_post(self, path, fields, files): return',
        '            if self.dev3_post(path, fields, files): return\n            if dispatch_static_post(self, path, fields, files): return',
        'routing POST')
    out={'app.py':app}
    nav=old['rk_navigation.py']
    nav=once(nav,"        ('/my-calendar', '▣', 'Mój kalendarz', 'mycalendar'),",
            "        ('/my-calendar', '▣', 'Mój kalendarz', 'mycalendar'),\n"
            "        ('/worktime', '◷', 'Czas pracy i rozliczenia', 'worktime'),\n"
            "        ('/stages', '▤', 'Etapy postępowań', 'stages'),\n"
            "        ('/vault', '◇', 'Sejf dokumentów', 'vault'),",'nawigacja PRACA')
    nav=once(nav,"    ('/cloud', '☁', 'Cloud / PWA', 'cloud'),",
            "    ('/cloud', '☁', 'Cloud / PWA', 'cloud'),\n"
            "    ('/calendar-sync', '▦', 'Google / Outlook', 'calendar-sync'),\n"
            "    ('/court-portal', '⚖', 'Portal Informacyjny', 'court-portal'),",'nawigacja ADMIN')
    out['rk_navigation.py']=nav
    out['rk_core/schema_version.py']=once(old['rk_core/schema_version.py'],'SCHEMA_VERSION = 330','SCHEMA_VERSION = 331','wersja bazy')
    out['requirements.txt']=once(old['requirements.txt'],'openpyxl>=3.1,<4','openpyxl>=3.1,<4\ntzdata>=2025.2,<2028','strefy czasowe na Windows')
    spec=once(old['RK_KANCELARIA_PORTABLE.spec'],"for pkg in ('reportlab', 'openpyxl'):","for pkg in ('reportlab', 'openpyxl', 'tzdata'):",'pakowanie stref czasowych')
    out['RK_KANCELARIA_PORTABLE.spec']=once(spec,"        'cryptography',","        'cryptography',\n        'tzdata',",'hiddenimports tzdata')
    out['TEST_ARCHITEKTURA_040.py']=once(old['TEST_ARCHITEKTURA_040.py'],
        "self.assertIn('VERSION = \"0.4.0-dev2\"',app)",
        "self.assertIn('VERSION = \"0.4.0-dev3\"',app)",'test architektury')
    out['TEST_STABILIZACJA_040_DEV2.py']=once(old['TEST_STABILIZACJA_040_DEV2.py'],
        'self.assertEqual(SCHEMA_VERSION,330)','self.assertEqual(SCHEMA_VERSION,331)','test wersji schematu')
    out['RAPORT_JAKOSCI_040.py']=once(old['RAPORT_JAKOSCI_040.py'],
        "'version':'0.4.0-dev2'","'version':'0.4.0-dev3'",'wersja raportu')
    out['AUDYT_I_TESTY_RK_040_DEV2.py']=once(old['AUDYT_I_TESTY_RK_040_DEV2.py'],
        "'version':'0.4.0-dev2'","'version':'0.4.0-dev3'",'wersja audytu')
    for rel,src in out.items():
        if rel.endswith('.py'):ast.parse(src,filename=rel)
    return {k:v for k,v in out.items() if old[k]!=v}


def apply(root: Path,dry_run=False,verify=False):
    root=root.resolve()
    out=changes(root)
    if verify:
        if out:raise RuntimeError('Nie zastosowano aktualizacji dev3: '+', '.join(out))
        return 'OK: RK KANCELARIA dev3 zweryfikowana'
    if dry_run:return 'DRY RUN OK: %d zmodyfikowanych plików, Data nietknięte'%len(out)
    if not out:return 'RK KANCELARIA dev3 już zainstalowana; bez zmian'
    backup=root/'.rk_backup_before_040_dev3'
    if backup.exists():raise RuntimeError('Istnieje poprzedni backup. Sprawdź ręcznie przed ponowną instalacją.')
    backup.mkdir(parents=True,exist_ok=False)
    old={name:(root/name).read_bytes() for name in out}
    for name,data in old.items():
        path=backup/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    (backup/'manifest.json').write_text(json.dumps({name:hashlib.sha256(data).hexdigest() for name,data in old.items()},indent=2),encoding='utf-8')
    written=[]
    try:
        for name,body in out.items():
            dst=root/name
            fd,tmp=tempfile.mkstemp(prefix='.rk_dev3_',dir=str(dst.parent))
            try:
                with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
                    f.write(body);f.flush();os.fsync(f.fileno())
                os.replace(tmp,dst);written.append(name)
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
    except BaseException:
        for name in written:(root/name).write_bytes(old[name])
        raise
    return 'Zastosowano RK KANCELARIA 0.4.0-dev3: '+', '.join(written)+'. Dane /Data pozostawiono bez zmian.'

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('repo',nargs='?',default='.')
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--verify',action='store_true')
    a=p.parse_args()
    try:print(apply(Path(a.repo),a.dry_run,a.verify))
    except Exception as exc:print('RK DEV3 ERROR:',exc);raise SystemExit(1)
