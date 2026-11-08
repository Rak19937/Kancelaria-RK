#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Idempotent UX6 source migration. Never touches Data, databases or client files.

Usage: python ZASTOSUJ_UX6.py . --dry-run
       python ZASTOSUJ_UX6.py .
       python ZASTOSUJ_UX6.py . --verify
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

MARKER = 'RK_UX6_20261108 = True'
EXPECTED = {'app.py','rk_dev3.py','rk_inbox.py'}
BASE = Path(__file__).resolve().parent


def replace_once(text, old, new, what):
    if new in text:return text
    count=text.count(old)
    if count!=1:
        raise RuntimeError(f'Niebezpieczny punkt aktualizacji: {what}; wystąpień: {count}. Nie zmieniono źródeł.')
    return text.replace(old,new,1)


def patch_app(s):
    if MARKER in s:return s
    if 'VERSION = "0.4.0-dev5"' not in s:
        raise RuntimeError('Wymagana zatwierdzona baza RK KANCELARIA 0.4.0-dev5.')
    anchor='APP_NAME = "RK KANCELARIA"'
    s=replace_once(s,anchor,
        'from rk_ux6 import Ux6Mixin, ensure_ux6_schema, delete_case_dependencies, choice_exists as ux6_choice_exists\n\n'+anchor,
        'import nowego modułu')
    s=replace_once(s,'VERSION = "0.4.0-dev5"',
        'VERSION = "0.4.0-dev5"\n'+MARKER,
        'znacznik wersji UX6')
    s=replace_once(s,'        ensure_dev5_vault_schema(con)',
        '        ensure_dev5_vault_schema(con)\n        ensure_ux6_schema(con)',
        'inicjalizacja dodatkowych tabel')
    s=replace_once(s,'class Handler(Dev5AccessMixin,',
        'class Handler(Ux6Mixin, Dev5AccessMixin,',
        'HTTP mixin')
    s=replace_once(s,'        content=csrf_html(content,token)',
        '''        if '</head>' in content and '/assets/rk_ux6.js' not in content:
            ux6_assets=('<link rel="stylesheet" href="/assets/rk_ux6.css">'
                        '<script defer src="/assets/rk_ux6.js"></script>')
            content=content.replace('</head>',ux6_assets+'</head>',1)
        content=csrf_html(content,token)''',
        'arkusze i skrypt czytelności')
    s=replace_once(s,'            if self.dev5_access_get(path, qs): return',
        '            if self.dev5_access_get(path, qs): return\n            if self.ux6_get(path, qs): return',
        'obsługa GET UX6')
    s=replace_once(s,'            if self.dev5_access_post(path, fields, files): return',
        '            if self.dev5_access_post(path, fields, files): return\n            if self.ux6_post(path, fields, files): return',
        'obsługa POST UX6')
    # Calendar: dedup strictly equivalent presentation items only; detailed
    # day view always retains *all* source records and separate edit routes.
    s=replace_once(s,'            key=(str(d),int(cid or 0),url or norm)',
        '            key=(str(d),int(cid or 0),norm)',
        'łączenie wizualnych duplikatów')
    s=replace_once(s,
        '            more = f"<div class=\'small muted\'>+{len(items)-5} więcej</div>" if len(items) > 5 else \'\'',
        '            more = f"<a class=\'ux6-day-open\' href=\'/calendar/day?date={cur.isoformat()}\'>+{len(items)-5} więcej — otwórz dzień</a>" if len(items) > 5 else \'\'',
        'link do ukrytych pozycji kalendarza')
    s=replace_once(s,
        '            cells.append(f"<div class=\'calendar-day{cls}\'><div class=\'calendar-day-num\'>{cur.day}</div>{\'\'.join(event_parts)}{more}</div>")',
        '            day_url=f"/calendar/day?date={cur.isoformat()}"\n'
        '            cells.append(f"<div class=\'calendar-day{cls}\'><div class=\'calendar-day-num\'>{cur.day}</div>{\'\'.join(event_parts)}{more}<a class=\'ux6-day-open\' href=\'{day_url}\'>✎ Zobacz / edytuj dzień</a></div>")',
        'edycja każdego dnia z kalendarza')
    # Only custom values saved by authenticated admin are accepted.
    s=replace_once(s,"        if typ not in ALERT_TYPES: typ = 'Inne'",
        "        if typ not in ALERT_TYPES and not ux6_choice_exists(db,'alert_type',typ): typ = 'Inne'",
        'własne typy kalendarza')
    task_old="        if task_type not in ACTIONABLE_ALERT_TYPES:\n            task_type='Zadanie'"
    task_new="        if task_type not in ACTIONABLE_ALERT_TYPES and not ux6_choice_exists(db,'task_type',task_type):\n            task_type='Zadanie'"
    if s.count(task_old)!=2:
        raise RuntimeError('Niezgodny schemat tworzenia i edycji zadań; przerwano aktualizację.')
    s=s.replace(task_old,task_new)
    # New tab reachable from edit case regardless of the selected workspace view.
    s=replace_once(s,"        self.send_html(layout('Edycja',body,'cases'))",
        "        body += f'<div class=\"card\"><a class=\"btn primary\" href=\"/case/{cid}/phases\">＋ Etapy równoległe (np. proces + mediacja)</a></div>'\n"
        "        self.send_html(layout('Edycja',body,'cases'))",
        'skróty do etapów sprawy')
    # Give non-admin users a clear explanation rather than a misleading
    # delete button which appears usable but later returns HTTP 403.
    cf_start=s.index("    def case_delete_confirm(self,cid,message='")
    cf_end=s.index('    def case_delete(self,cid,f):',cf_start)
    confirm=s[cf_start:cf_end]
    confirm=replace_once(confirm,
        "        disabled=' disabled' if c['status']!='closed' else ''",
        "        disabled=' disabled' if c['status']!='closed' else ''\n"
        "        who=current_request_user()\n"
        "        if not who or who['role']!='admin':\n"
        "            disabled=' disabled'\n"
        "            closed_note += '<div class=\"error\">Trwałe usuwanie spraw jest dostępne tylko dla administratora.</div>'",
        'informacja o uprawnieniach administratora')
    s=s[:cf_start]+confirm+s[cf_end:]
    # Case delete: confirmed + verified source snapshot required BEFORE touching DB.
    start=s.index('    def case_delete(self,cid,f):')
    end=s.index('    def case_pin_toggle(',start)
    sub=s[start:end]
    sub=replace_once(sub,'        raw,snapshot_name=create_data_snapshot_zip()',
        '''        try:
            raw,snapshot_name=create_data_snapshot_zip()
        except (OSError,RuntimeError,sqlite3.Error) as exc:
            log_app_exception(f'/case/{cid}/snapshot',exc)
            return self.case_delete_confirm(cid,f'Nie udało się utworzyć pełnej kopii. Usuwanie przerwano: {exc}')''',
        'zabezpieczenie tworzenia snapshotu')
    sub=replace_once(sub,'        atomic_write_bytes(backup_path,raw)',
        '''        try:
            atomic_write_bytes(backup_path,raw)
            if not backup_path.is_file() or backup_path.stat().st_size!=len(raw):
                raise RuntimeError('Zapis kopii nie jest kompletny.')
        except (OSError,RuntimeError) as exc:
            log_app_exception(f'/case/{cid}/save-snapshot',exc)
            return self.case_delete_confirm(cid,f'Nie zapisano kompletnego snapshotu. Sprawa nie została usunięta: {exc}')''',
        'potwierdzenie zapisanej kopii')
    sub=replace_once(sub,
        '''        author=self.current_author(f); folder=FILES_DIR/f"sprawa_{cid}"
        with db() as con:
            vault_names=[r[0] for r in con.execute(
                'SELECT stored_name FROM dev3_vault_files WHERE case_id=?',(cid,))]
            immutable_audit(con,None,'case',cid,'Trwale usunięto sprawę po wykonaniu snapshotu',
                            f"{c['title']} · kopia: {backup_path.name}",author)
            con.execute("DELETE FROM cases WHERE id=?",(cid,))''',
        '''        author=self.current_author(f); folder=FILES_DIR/f"sprawa_{cid}"
        try:
            with db() as con:
                vault_names=[r[0] for r in con.execute(
                    'SELECT stored_name FROM dev3_vault_files WHERE case_id=?',(cid,))]
                immutable_audit(con,None,'case',cid,'Trwale usunięto sprawę po wykonaniu snapshotu',
                                f"{c['title']} · kopia: {backup_path.name}",author)
                delete_case_dependencies(con,cid)
        except (sqlite3.Error,ValueError) as exc:
            log_app_exception(f'/case/{cid}/delete-db',exc)
            return self.case_delete_confirm(cid,
                f'Baza zablokowała usunięcie powiązanych danych. Cofnięto zmiany. Snapshot: {backup_path.name}. Szczegóły: {exc}')''',
        'bezpieczne usuwanie rekordów zależnych')
    s=s[:start]+sub+s[end:]
    ast.parse(s,filename='app.py')
    return s


def patch_dev3(s):
    marker="        self._dev3_html('Etap postępowania',body+'</div>','stages')"
    replacement=("        body += '<p><a class=\"btn primary\" href=\"/case/%d/phases\">＋ Etapy równoległe / dodaj własny etap</a></p>' % case_id\n"
                 "        self._dev3_html('Etap postępowania',body+'</div>','stages')")
    s=replace_once(s,marker,replacement,'własne równoległe etapy w module Etapy')
    ast.parse(s,filename='rk_dev3.py')
    return s


def patch_inbox(s):
    old="        if dtype not in {'Inne', 'Pismo procesowe', 'Postanowienie', 'Wyrok', 'Wezwanie', 'Korespondencja'}:"
    new=("        if dtype not in {'Inne', 'Pismo procesowe', 'Postanowienie', 'Wyrok', 'Wezwanie', 'Korespondencja'} "
         "and not a.ux6_choice_exists(a.db,'doc_type',dtype):")
    s=replace_once(s,old,new,'własne rodzaje dokumentów w skrzynce')
    ast.parse(s,filename='rk_inbox.py')
    return s


def verify(root):
    app=(root/'app.py').read_text('utf-8')
    tests=['RK_UX6_20261108 = True','class Handler(Ux6Mixin,','if self.ux6_get(path, qs): return',
           'if self.ux6_post(path, fields, files): return','ensure_ux6_schema(con)',
           'delete_case_dependencies(con,cid)','<a class=\'ux6-day-open\'']
    for t in tests:
        if t not in app:raise RuntimeError('Brakuje poprawki: '+t)
    for n in ('rk_ux6.py','rk_dev3.py','rk_inbox.py'):
        ast.parse((root/n).read_text('utf-8'),filename=n)
    if not (root/'assets/rk_ux6.css').is_file() or not (root/'assets/rk_ux6.js').is_file():
        raise RuntimeError('Brak plików interfejsu UX6.')
    return 'UX6: wdrożenie zweryfikowane.'


def apply(root,dry_run=False):
    root=Path(root).resolve()
    for n in EXPECTED:
        if not (root/n).is_file():raise RuntimeError('Brak pliku repozytorium: '+n)
    # Ensure all included new assets are present BEFORE any write.
    for n in ('rk_ux6.py','assets/rk_ux6.css','assets/rk_ux6.js'):
        if not (root/n).is_file():raise RuntimeError('Brak pliku poprawki UX6: '+n)
    sources={n:(root/n).read_text(encoding='utf-8') for n in EXPECTED}
    if MARKER in sources['app.py']:
        return verify(root)+' Już zastosowano.'
    updated={'app.py':patch_app(sources['app.py']),
             'rk_dev3.py':patch_dev3(sources['rk_dev3.py']),
             'rk_inbox.py':patch_inbox(sources['rk_inbox.py'])}
    if dry_run:return 'DRY RUN: struktura zgodna, zmiany gotowe; nic nie zapisano.'
    backup=root/'.rk_backup_before_ux6'
    backup.mkdir(exist_ok=True)
    for name,orig in sources.items():
        target=backup/name
        if target.exists() and target.read_text('utf-8')!=orig:
            raise RuntimeError('Odmienny plik poprzedniej kopii '+name+'; przerwano, by nie nadpisać historii.')
        if not target.exists():shutil.copy2(root/name,target)
    changed=[]
    try:
        for name,code in updated.items():
            dest=root/name
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',newline='\n',dir=root,
                 prefix='.ux6_',suffix='.tmp',delete=False) as tmp:
                tmp.write(code);tmp.flush();os.fsync(tmp.fileno());temporary=Path(tmp.name)
            try:os.replace(temporary,dest)
            finally:temporary.unlink(missing_ok=True)
            changed.append(name)
        return verify(root)
    except Exception:
        # Revert only files written in this invocation.
        for name in reversed(changed):shutil.copy2(backup/name,root/name)
        raise


def cli():
    ap=argparse.ArgumentParser();ap.add_argument('root',nargs='?',default='.')
    ap.add_argument('--dry-run',action='store_true');ap.add_argument('--verify',action='store_true')
    args=ap.parse_args()
    try: print(verify(Path(args.root)) if args.verify else apply(Path(args.root),args.dry_run))
    except Exception as exc: print('UX6: wstrzymano aktualizację:',exc);raise SystemExit(1)

if __name__=='__main__':cli()
