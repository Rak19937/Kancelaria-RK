#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RK KANCELARIA dev4 -> dev5 (full): one-pass, fail-closed source migration.

Run in GitHub checkout, not in EXE or Data/. Uses the THREE original dev5 files,
adds case-scoped ACL, journaled vault and calendar-change review. All source
transformations are validated BEFORE writing anything; --verify is read-only.
"""
from __future__ import annotations
import argparse
import ast
import os
import re
import sys
import tempfile
from pathlib import Path

from ZASTOSUJ_040_DEV5 import PATCHES as BASE_PATCHES, once

FULL_MARKER='RK_040_DEV5_FULL_REPAIR_20261108'
EXTRAS=('rk_dev5_acl.py','rk_dev5_vault.py','rk_dev5_calendar_reconcile.py',
        'TEST_RK_DEV5_SECURITY.py','TEST_RK_DEV5.py','rk_dev5_snapshot.py')


def patch_app(s):
    p='app.py'
    s=once(s,'RK_040_DEV5_STABILIZATION_20261108 = True',
           'RK_040_DEV5_STABILIZATION_20261108 = True\n'+FULL_MARKER+' = True',p)
    s=once(s,'from rk_dev4 import Dev4Mixin',
      'from rk_dev4 import Dev4Mixin\nfrom rk_dev5_acl import Dev5AccessMixin, ensure_dev5_acl_schema\nfrom rk_dev5_vault import ensure_dev5_vault_schema, recover_vault_journal',p)
    s=once(s,'class Handler(Dev4Mixin, Dev3Mixin,',
      'class Handler(Dev5AccessMixin, Dev4Mixin, Dev3Mixin,',p)
    s=once(s,'        ensure_dev4_schema(con)\n    start_worker(sys.modules[__name__])',
      '        ensure_dev4_schema(con)\n        ensure_dev5_acl_schema(con)\n        ensure_dev5_vault_schema(con)\n    recover_vault_journal(db,FILES_DIR)\n    start_worker(sys.modules[__name__])',p)
    s=once(s,'            if self.dev4_get(path, qs): return',
      '            if self.dev5_access_get(path, qs): return\n            if self.dev4_get(path, qs): return',p)
    s=once(s,'        self._autosave_mode = fields.get("_autosave", "") == "1" or self.headers.get("X-Sprawnik-Autosave") == "1"',
      '        if self.dev5_access_post(path, fields, files): return\n        self._autosave_mode = fields.get("_autosave", "") == "1" or self.headers.get("X-Sprawnik-Autosave") == "1"',p)
    s=once(s,"<a class='btn primary-soft' href='/case/{cid}/history'>Historia sprawy</a>",
      "<a class='btn primary-soft' href='/case/{cid}/history'>Historia sprawy</a><a class='btn' href='/case/{cid}/access'>Uprawnienia</a>",p)
    # Session cookies are bearer tokens. Never expose a multi-user installation
    # over clear-text LAN HTTP; reverse proxy with HTTPS and secure cookie flag.
    s=once(s,'LOCAL_MODE = HOST in {"127.0.0.1", "localhost", "::1"}',
      """LOCAL_MODE = HOST in {"127.0.0.1", "localhost", "::1"}
if not LOCAL_MODE and os.getenv('RK_HTTPS_PROXY','0').strip().lower() not in {'1','true','yes'}:
    raise RuntimeError('Dostęp sieciowy do RK KANCELARIA wymaga HTTPS i RK_HTTPS_PROXY=1; uruchom lokalnie lub skonfiguruj TLS.')""",p)
    # Never downgrade a failed encrypted backup to an unencrypted one.
    s=once(s,"""                except Exception:
                    p=DAILY_BACKUPS_DIR/f'rk_kancelaria_{today}_{stamp}.sqlite3'; os.replace(tmp,p)""",
      """                except Exception:
                    tmp.unlink(missing_ok=True)
                    raise RuntimeError('Nie zapisano kopii: szyfrowanie zawiodło. Nie utworzono jawnej kopii SQLite.')""",p)
    return s


def patch_core(s):
    p='rk_dev3_core.py'
    # Allow isolated fixture_db() and production to create calendar-review tables.
    s=once(s,"     ''')\n\n\ndef set_stage(con, case_id: int, stage: str, actor: int, note: str = '') -> None:",
      "    ''')\n    from rk_dev5_calendar_reconcile import ensure_dev5_calendar_schema\n    ensure_dev5_calendar_schema(con)\n\n\ndef set_stage(con, case_id: int, stage: str, actor: int, note: str = '') -> None:",p)
    return s


def patch_calendar(s):
    p='rk_dev3_calendar.py'
    s=once(s,'from zoneinfo import ZoneInfo',
      'from zoneinfo import ZoneInfo\nfrom rk_dev5_calendar_reconcile import linked_event, record_published, mark_missing',p)
    s=once(s,"            if con.execute('SELECT 1 FROM dev3_calendar_links WHERE provider=? AND external_id=?',(provider,eid)).fetchone():continue",
      "            if linked_event(con,provider,eid,obj):continue",p)
    s=once(s,"                if obj.get('status')=='cancelled':continue",
      "                if obj.get('status')=='cancelled':\n                    linked_event(con,provider,eid,obj)\n                    continue",p)
    s=once(s,"                if obj.get('isCancelled'):continue",
      "                if obj.get('isCancelled'):\n                    linked_event(con,provider,eid,obj)\n                    continue",p)
    s=once(s,'    added=updated=0\n    for page in range(5):',
      '    added=updated=0\n    seen_ids=set()\n    for page in range(5):',p)
    s=once(s,"            eid=str(obj['id'])[:400]",
      "            eid=str(obj['id'])[:400]\n            seen_ids.add(eid)",p)
    s=once(s,'    return added,updated\n\n\ndef publish_appointment',
      '    mark_missing(con,provider,seen_ids,today,end)\n    return added,updated\n\n\ndef publish_appointment',p)
    s=once(s,'         (provider,appointment_id,external,etag))\n    return external',
      "         (provider,appointment_id,external,etag))\n    record_published(con,provider,external,title,start.strftime('%Y-%m-%dT%H:%M'),end.strftime('%Y-%m-%dT%H:%M'))\n    return external",p)
    return s


def patch_dev3(s):
    p='rk_dev3.py'
    s=once(s,"            '/calendar-sync/dismiss':lambda:self.dev3_calendar_dismiss(fields),",
      "            '/calendar-sync/dismiss':lambda:self.dev3_calendar_dismiss(fields),\n            '/calendar-sync/review':lambda:self.dev3_calendar_review(fields),",p)
    target="        self._dev3_html('Integracje kalendarza',''.join(s),'calendar-sync')"
    panel='''        with a.db() as con:
            changes=con.execute("SELECT * FROM dev5_calendar_changes WHERE status='pending' ORDER BY id DESC LIMIT 100").fetchall()
        s.append('<div class="card"><h2>Zmiany z kalendarzy wymagające decyzji</h2>')
        for ch in changes:
            s.append('<div class="dev3-item"><b>%s</b> · %s · %s — %s%s<form method="post" action="/calendar-sync/review"><input type="hidden" name="change_id" value="%s"><button name="decision" value="accept" class="btn small">Zatwierdź zmianę w RK</button><button name="decision" value="dismiss" class="btn small">Odrzuć zmianę</button></form></div>' % (
                esc(ch['provider']),esc(ch['title']),esc(ch['start_at']),esc(ch['end_at']),
                ' · ANULOWANO ZEWNĘTRZNIE' if ch['cancelled'] else ' · BRAK W ZAKRESIE — sprawdź ręcznie' if ch['missing'] else '',int(ch['id'])))
        if not changes:s.append('<p>Brak zewnętrznych zmian wymagających kontroli.</p>')
        s.append('</div>')
'''
    s=once(s,target,panel+target,p)
    # dev3.py ends with Dev3Mixin methods, so an indented method belongs to it.
    s+='''
    def dev3_calendar_review(self,f):
        if not self._dev3_admin():return
        from rk_dev5_calendar_reconcile import accept_change
        a=self._dev3_app();user=self._dev3_me()
        try:change_id=int(f.get('change_id') or 0)
        except (TypeError,ValueError):raise ValueError('Niepoprawny numer propozycji')
        decision=f.get('decision','')
        if decision not in ('accept','dismiss'):raise ValueError('Wybierz decyzję')
        with a.db() as con:
            appointment_id=accept_change(con,change_id,user['id'],decision=='accept')
            audit_if_available(con,None,user['id'],'Kontrola kalendarza',f'Wydarzenie {appointment_id}: {decision}')
        self.redirect('/calendar-sync')
'''
    return s


def patch_dev4(s):
    p='rk_dev4.py'
    beginning=s.index('    def dev4_vault_change(self,file_id,kind,fields):')
    # Existing dev4_vault_change is the last method in this file.
    s=s[:beginning]+'''    def dev4_vault_change(self,file_id,kind,fields):
        app=self._dev3_app();user=self._dev3_me()
        from rk_dev5_vault import vault_change_safe
        if kind=='delete' and fields.get('confirmation')!='USUŃ':
            raise ValueError('Wpisz USUŃ, aby usunąć dokument sejfu')
        vault_change_safe(app.db,app.FILES_DIR,file_id,user['id'],user['role']=='admin',kind,
                          fields.get('old_passphrase',''),fields.get('new_passphrase',''))
        self.redirect('/vault')
'''
    return s


def patch_workflow(s):
    return once(s,'          python TEST_RK_DEV5.py\n          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }',
      '          python TEST_RK_DEV5.py\n          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n          python TEST_RK_DEV5_SECURITY.py\n          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }', '.github/workflows/main.yml')


def patch_test_dev4(s):
    """Preserve old functional test; initialize the new journal on fixture SQLite."""
    p='TEST_RK_DEV4.py'
    s=once(s,'from rk_dev4 import Dev4Mixin\n',
           'from rk_dev4 import Dev4Mixin\nfrom rk_dev5_vault import ensure_dev5_vault_schema\n',p)
    s=once(s,
      'class Dev4UiTests(unittest.TestCase):\n    def setUp(self):self.con=fixture_db();ensure_dev4_schema(self.con)',
      'class Dev4UiTests(unittest.TestCase):\n    def setUp(self):self.con=fixture_db();ensure_dev4_schema(self.con);ensure_dev5_vault_schema(self.con)',p)
    return s


def patch_test_ui(s):
    """Keep E2E authorization assertions aligned to dev5 deny-by-default."""
    p='TEST_UI_HTTP_040_DEV2.py'
    s=once(s,
      "            code,user_html,_=request(other,base+'/inbox')\n            assert code==200",
      """            # dev5 restricts the legacy global inbox for regular accounts.
            # The user must instead have access to the case-scoped workspace.
            code,_,_=request(other,base+'/inbox')
            assert code==403,'Globalna skrzynka wplywu powinna byc niedostepna'
            code,user_html,_=request(other,base+'/my-cases')
            assert code==200,('my-cases',code,user_html[:400])""",p)
    return s


TEST_PATCHES={'TEST_RK_DEV4.py':patch_test_dev4,
              'TEST_UI_HTTP_040_DEV2.py':patch_test_ui}


STAGE2={'app.py':patch_app,'rk_dev3_core.py':patch_core,
        'rk_dev3_calendar.py':patch_calendar,'rk_dev3.py':patch_dev3,
        'rk_dev4.py':patch_dev4,'.github/workflows/main.yml':patch_workflow}


def run(root:Path,verify=False,dry_run=False):
    root=root.resolve()
    if not (root/'app.py').is_file():raise RuntimeError('Podaj katalog źródeł repozytorium z app.py')
    app=(root/'app.py').read_text('utf-8')
    if verify:
        checks={'app.py':['VERSION = "0.4.0-dev5"',FULL_MARKER,'Dev5AccessMixin','dev5_access_get','dev5_access_post',
                           'recover_vault_journal'],
                'rk_dev3.py':['def dev3_calendar_review','def dev3_worktime_page(self,qs=None)'],
                'rk_dev4.py':['vault_change_safe','def dev4_time_history'],
                '.github/workflows/main.yml':['TEST_RK_DEV5_SECURITY.py'],
                'rk_dev3_calendar.py':['linked_event(con,provider,eid,obj)'],
                'TEST_RK_DEV4.py':['ensure_dev5_vault_schema(self.con)'],
                'TEST_UI_HTTP_040_DEV2.py':["base+'/my-cases'", "assert code==403,'Globalna skrzynka wplywu powinna byc niedostepna'"]}
        for rel,items in checks.items():
            data=(root/rel).read_text('utf-8')
            for needle in items:
                if needle not in data:raise RuntimeError('Brak poprawki: '+rel+' -> '+needle)
        print('DEV5 FULL: znaczniki zgodne (nie zastępuje pełnych testów)');return
    if 'VERSION = "0.4.0-dev4"' not in app or FULL_MARKER in app:
        raise RuntimeError('Przyjmuję wyłącznie czyste źródła dev4; żadnych zmian nie zapisano')
    for file in (*EXTRAS,'ZASTOSUJ_040_DEV5.py'):
        if not (root/file).is_file():raise RuntimeError('Brak pliku '+file+'; żadnych zmian nie zapisano')
        if file.endswith('.py'):ast.parse((root/file).read_text('utf8'),filename=file)
    changes={}
    for rel,transform in BASE_PATCHES.items():
        original=(root/rel).read_text('utf-8')
        patched=transform(original)
        if rel in STAGE2:patched=STAGE2[rel](patched)
        if rel.endswith('.py'):ast.parse(patched,filename=rel)
        changes[rel]=(original,patched)
    for rel,transform in TEST_PATCHES.items():
        original=(root/rel).read_text('utf-8')
        patched=transform(original)
        ast.parse(patched,filename=rel)
        changes[rel]=(original,patched)
    print('Weryfikacja statyczna przeszła, zmienione pliki:')
    for name in sorted(changes):print('  '+name)
    if dry_run:print('DRY RUN: bez zapisu');return
    written=[]
    try:
        for name,(_,value) in changes.items():
            target=root/name
            fd,tmp=tempfile.mkstemp(prefix='.rk_dev5_full_',dir=target.parent)
            try:
                with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
                    f.write(value);f.flush();os.fsync(f.fileno())
                os.replace(tmp,target)
                written.append(name)
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
    except BaseException:
        for name in reversed(written):(root/name).write_text(changes[name][0],encoding='utf-8')
        raise
    print('DEV5 FULL: źródła zapisane; uruchom testy przed commitem')


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('root',nargs='?',default='.')
    ap.add_argument('--dry-run',action='store_true')
    ap.add_argument('--verify',action='store_true')
    args=ap.parse_args()
    try:run(Path(args.root),args.verify,args.dry_run)
    except Exception as exc:
        print('AKTUALIZACJA ZABLOKOWANA:',str(exc),file=sys.stderr)
        raise SystemExit(1)
