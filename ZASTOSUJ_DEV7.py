#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Transactional-ish DEV7 source patcher: dry run, verify, atomic file writes.

Never edits Data/, SQLite databases, or client documents. The original files
are saved in .rk_backup_before_dev7 for recovery. On a failed write, patched
source files are restored from the verified originals.
"""
from __future__ import annotations

import argparse
import ast
import os
import shutil
import tempfile
from pathlib import Path

MARKER='RK_DEV7_STABILITY_20261110 = True'
FILES=('app.py','rk_ux6.py')


def replace_unique(s,old,new,label):
    if new in s:return s
    n=s.count(old)
    if n!=1:raise RuntimeError(f'Punkt aktualizacji {label}: oczekiwano 1 wystąpienia, znaleziono {n}. Nie zmieniono plików.')
    return s.replace(old,new,1)


def patch_app(s):
    if MARKER in s:return s
    if 'RK_UX6_20261108 = True' not in s or 'VERSION = "0.4.0-dev5"' not in s:
        raise RuntimeError('Wymagana baza 0.4.0-dev5 z zatwierdzonym UX6.')
    s=replace_unique(s,
        'from rk_ux6 import Ux6Mixin, ensure_ux6_schema, delete_case_dependencies, choice_exists as ux6_choice_exists',
        'from rk_ux6 import Ux6Mixin, ensure_ux6_schema, delete_case_dependencies, choice_exists as ux6_choice_exists\n'
        'from rk_dev7_stability import (check_case_form, preflight_case_delete, verify_backup_snapshot,\n'
        '                               assert_deleted_case_integrity)',
        'importy zabezpieczeń')
    s=replace_unique(s,'RK_UX6_20261108 = True','RK_UX6_20261108 = True\n'+MARKER,'znacznik stabilizacji')
    s=replace_unique(s,
        '    def case_create(self, f):\n',
        '''    def case_create(self, f):
        try:
            check_case_form(f, STATUS_LABELS, new=True)
        except ValueError as exc:
            return self.send_html(layout('Sprawdź dane sprawy',
                f'<div class="card friendly-error"><h1>Nie zapisano sprawy</h1><p>{esc(str(exc))}</p>'
                '<p>Wróć do formularza i popraw dane.</p><a class="btn" href="/case/new">Wróć</a></div>',
                'cases'),400)
''','walidacja tworzenia sprawy')
    s=replace_unique(s,
        '    def case_update(self,cid,f):\n',
        '''    def case_update(self,cid,f):
        try:
            check_case_form(f, STATUS_LABELS, new=False)
        except ValueError as exc:
            return self.send_html(layout('Sprawdź dane sprawy',
                f'<div class="card friendly-error"><h1>Nie zapisano zmian</h1><p>{esc(str(exc))}</p>'
                f'<a class="btn" href="/case/{cid}/edit">Wróć do edycji</a></div>',
                'cases'),400)
''','walidacja edycji sprawy')
    # Patch only the body of deletion handler so unrelated identical strings
    # in other functions are never replaced by mistake.
    start=s.index('    def case_delete(self,cid,f):')
    end=s.index('    def case_pin_toggle(',start)
    sub=s[start:end]
    sub=replace_unique(sub,
        "        if (f.get('confirmation','') or '').strip()!='USUŃ' or f.get('acknowledge')!='1':\n"
        "            return self.case_delete_confirm(cid,'Nie potwierdzono usunięcia. Wpisz dokładnie „USUŃ” i zaznacz pole potwierdzenia.')",
        '''        if (f.get('confirmation','') or '').strip()!='USUŃ' or f.get('acknowledge')!='1':
            return self.case_delete_confirm(cid,'Nie potwierdzono usunięcia. Wpisz dokładnie „USUŃ” i zaznacz pole potwierdzenia.')
        # Zweryfikuj powiązania w SAVEPOINT — bez trwałych zmian.
        try:
            with db() as con:
                preflight_case_delete(con,cid,delete_case_dependencies)
        except (sqlite3.Error,ValueError) as exc:
            log_app_exception(f'/case/{cid}/preflight',exc)
            return self.case_delete_confirm(cid,
                f'Nie można bezpiecznie usunąć tej sprawy. Dane pozostały bez zmian. {exc}')''',
        'wstępna próba usuwania')
    sub=replace_unique(sub,
        '''            if not backup_path.is_file() or backup_path.stat().st_size!=len(raw):
                raise RuntimeError('Zapis kopii nie jest kompletny.')''',
        '''            if not backup_path.is_file() or backup_path.stat().st_size!=len(raw):
                raise RuntimeError('Zapis kopii nie jest kompletny.')
            verify_backup_snapshot(backup_path,raw)''',
        'weryfikacja możliwości odtworzenia snapshotu')
    sub=replace_unique(sub,
        '                delete_case_dependencies(con,cid)',
        '                delete_case_dependencies(con,cid)\n'
        '                assert_deleted_case_integrity(con,cid)',
        'kontrola transakcji DELETE')
    s=s[:start]+sub+s[end:]
    # Not every failure means nothing has been written: avoid a false promise.
    start=s.index('    def do_POST(self):')
    end=s.index('    def setup_page(',start)
    post=s[start:end]
    post=replace_unique(post,
        'Nie udało się otworzyć tej części programu. Twoje zapisane dane nie zostały usunięte.',
        'Nie udało się dokończyć czynności. Sprawdź, czy zmiana jest widoczna, zanim spróbujesz ponownie. Szczegóły są w logu.',
        'rzetelny komunikat po niepowodzeniu POST')
    s=s[:start]+post+s[end:]
    ast.parse(s,filename='app.py')
    return s


def patch_ux6(s):
    old="                   WHERE p.appointment_date=? ORDER BY p.appointment_time,p.id''',(d,)).fetchall()"
    new="                   WHERE p.appointment_date=? AND p.status='planned' ORDER BY p.appointment_time,p.id''',(d,)).fetchall()"
    s=replace_unique(s,old,new,'ukrycie zakończonych/odwołanych spotkań w kalendarzu')
    ast.parse(s,filename='rk_ux6.py')
    return s


def verify(root):
    root=Path(root)
    app=(root/'app.py').read_text(encoding='utf-8')
    ux=(root/'rk_ux6.py').read_text(encoding='utf-8')
    for item in (MARKER,'preflight_case_delete(con,cid,delete_case_dependencies)',
                 'verify_backup_snapshot(backup_path,raw)','assert_deleted_case_integrity(con,cid)',
                 'check_case_form(f, STATUS_LABELS, new=False)'):
        if item not in app:raise RuntimeError('Brakuje elementu DEV7: '+item)
    if "WHERE p.appointment_date=? AND p.status='planned'" not in ux:
        raise RuntimeError('Brakuje poprawki kalendarza DEV7.')
    for name in FILES:
        ast.parse((root/name).read_text('utf-8'),filename=name)
    return 'DEV7: poprawki źródeł zweryfikowane.'


def apply(root,dry_run=False):
    root=Path(root).resolve()
    if not (root/'rk_dev7_stability.py').is_file():
        raise RuntimeError('Brakuje rk_dev7_stability.py; nic nie zmieniono.')
    originals={n:(root/n).read_text(encoding='utf-8') for n in FILES}
    if MARKER in originals['app.py']:
        return verify(root)+' Już zainstalowano.'
    updated={'app.py':patch_app(originals['app.py']),
             'rk_ux6.py':patch_ux6(originals['rk_ux6.py'])}
    if dry_run:return 'DEV7 DRY RUN: kod zgodny, brak zmian na dysku.'
    backup=root/'.rk_backup_before_dev7'
    backup.mkdir(parents=True,exist_ok=True)
    for name in FILES:
        p=backup/name
        if p.exists() and p.read_text(encoding='utf-8')!=originals[name]:
            raise RuntimeError('Istnieje inna kopia źródła przed aktualizacją: '+name)
        if not p.exists():shutil.copy2(root/name,p)
    done=[]
    try:
        for name,code in updated.items():
            dest=root/name
            with tempfile.NamedTemporaryFile('w',encoding='utf-8',newline='\n',
                    dir=root,prefix='.rk_dev7_',suffix='.tmp',delete=False) as handle:
                temp=Path(handle.name);handle.write(code);handle.flush();os.fsync(handle.fileno())
            try:os.replace(temp,dest)
            finally:temp.unlink(missing_ok=True)
            done.append(name)
        return verify(root)
    except Exception:
        for name in reversed(done):shutil.copy2(backup/name,root/name)
        raise


def main():
    p=argparse.ArgumentParser()
    p.add_argument('root',nargs='?',default='.')
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--verify',action='store_true')
    args=p.parse_args()
    try:
        print(verify(Path(args.root)) if args.verify else apply(Path(args.root),args.dry_run))
    except Exception as exc:
        print('DEV7: instalacja wstrzymana:',exc)
        raise SystemExit(1)


if __name__=='__main__':main()
