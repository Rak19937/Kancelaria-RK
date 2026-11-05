#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cofnięcie 0.3.10-dev1 do dokładnych źródeł sprzed aktualizacji.

Domyślnie wyłącznie podgląd. Przywracanie wymaga --restore. Nie usuwa Data.
Odmawia usuwania plików nowych modułów, jeśli zostały ręcznie zmienione.
"""
import argparse
import shutil
import sys
from pathlib import Path

VERSION = 'VERSION = "0.3.10-dev1"'
GENERATED = ('rk_navigation.py','rk_routes.py','rk_dashboard_data.py',
             'rk_search_data.py','rk_document_data.py','TEST_ARCHITEKTURA_0310.py')
BASE_ONLY = ('rk_ux.py','assets/rk_ux.js','assets/rk_ux.css','TEST_UX_039.py')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repo',type=Path)
    parser.add_argument('--restore',action='store_true',help='wykonaj przywracanie po weryfikacji')
    args=parser.parse_args(argv)
    repo=args.repo.resolve()
    package=Path(__file__).resolve().parent
    backup=repo/'.rk_backup_before_0310'
    app=repo/'app.py'
    if not backup.is_dir() or not (backup/'app.py').is_file():
        raise RuntimeError('Nie znaleziono kompletnej kopii .rk_backup_before_0310.')
    if not app.is_file() or VERSION not in app.read_text(encoding='utf-8'):
        raise RuntimeError('To nie jest zainstalowany wariant 0.3.10-dev1; bez zmian.')
    old_base=not (backup/'rk_ux.py').exists()
    created=list(GENERATED)+list(BASE_ONLY if old_base else ())
    for rel in created:
        target=repo/rel; source=package/rel
        if not target.is_file() or not source.is_file():
            raise RuntimeError(f'Brak modułu do bezpiecznego wycofania: {rel}.')
        if target.read_bytes()!=source.read_bytes():
            raise RuntimeError(f'{rel} zmieniono po instalacji; nie usunięto niczego.')
    original_files=[p for p in backup.rglob('*') if p.is_file()]
    if any('Data' in p.relative_to(backup).parts for p in original_files):
        raise RuntimeError('Nieoczekiwana kopia Data. Przerwano.')
    print('Pliki do przywrócenia:',len(original_files),'| pliki nowych modułów do usunięcia:',len(created))
    if not args.restore:
        print('Tylko kontrola. Aby cofnąć: py PRZYWROC_0310.py "KATALOG_REPO" --restore')
        return 0
    for rel in created:
        (repo/rel).unlink()
    for src in original_files:
        dest=repo/src.relative_to(backup)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dest)
    print('Źródła przywrócone. Kopię pozostawiono. Katalog Data bez zmian.')
    return 0

if __name__=='__main__':
    try: sys.exit(main())
    except Exception as exc:
        print('BŁĄD:',exc,file=sys.stderr)
        sys.exit(2)
