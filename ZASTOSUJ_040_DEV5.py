#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RK KANCELARIA 0.4.0-dev5: fail-closed source patch, no database migration.

Apply to a clean 0.4.0-dev4 checkout. Does not touch Data/, customer files,
secrets or backups. Optional --dry-run and --verify.
"""
from __future__ import annotations
import argparse
import ast
import os
import sys
import tempfile
from pathlib import Path

VERSION = '0.4.0-dev5'


def once(src: str, before: str, after: str, path: str) -> str:
    count=src.count(before)
    if count!=1:
        raise RuntimeError(f'{path}: wymagany unikatowy fragment (znaleziono {count}); wstrzymano aktualizację')
    return src.replace(before,after,1)


def patch_core(src: str) -> str:
    name='rk_dev3_core.py'
    src=once(src,"    dialect=csv.Sniffer().sniff(sample,delimiters=';,\\t') if sample else csv.excel\n    rows=csv.DictReader(io.StringIO(data),dialect=dialect)",
"""    try:
        dialect=csv.Sniffer().sniff(sample,delimiters=';,\\t') if sample else csv.excel
    except csv.Error as exc:
        raise ValueError('Nie można odczytać formatu CSV. Sprawdź nagłówki i separator.') from exc
    rows=csv.DictReader(io.StringIO(data),dialect=dialect)""",name)
    src=once(src,"        value=(ref,(row.get('sygnatura') or '')[:150],(row.get('tytul') or '')[:250],\n               (row.get('data') or '')[:20],(row.get('opis') or '')[:4000],actor)",
"""        date_value=(row.get('data') or '').strip()
        if date_value:
            try:
                if not re.fullmatch(r'\\d{4}-\\d{2}-\\d{2}',date_value):raise ValueError('format')
                date.fromisoformat(date_value)
            except ValueError as exc:
                raise ValueError(f'Wiersz {i+2}: data musi mieć format RRRR-MM-DD') from exc
        value=(ref,(row.get('sygnatura') or '')[:150],(row.get('tytul') or '')[:250],
               date_value,(row.get('opis') or '')[:4000],actor)""",name)
    src=once(src,"       UNIQUE(provider,external_id)\n    );\n    ''')","       UNIQUE(provider,external_id)\n    );\n    CREATE TABLE IF NOT EXISTS dev5_calendar_publish_intents (\n         provider TEXT NOT NULL CHECK(provider IN ('google','outlook')),\n         appointment_id INTEGER NOT NULL REFERENCES case_appointments(id) ON DELETE CASCADE,\n         request_id TEXT NOT NULL,\n         PRIMARY KEY(provider,appointment_id), UNIQUE(provider,request_id)\n     );\n     ''')",name)
    return src


def patch_calendar(src: str) -> str:
    name='rk_dev3_calendar.py'
    src=once(src,'from datetime import date, datetime, timedelta, timezone\n','from datetime import date, datetime, timedelta, timezone, time as dtime\n',name)
    src=once(src,'import os\n','import os\nimport secrets\n',name)
    src=once(src,"    today=date.today(); end=today+timedelta(days=min(max(days,1),365))\n    if provider=='google':",
"""    today=datetime.now(ZoneInfo('Europe/Warsaw')).date()
    end=today+timedelta(days=min(max(days,1),365))
    # Provider API uses UTC boundaries; they must represent midnight in Poland,
    # including the DST offset on each boundary (rather than 00:00 UTC).
    start_utc=datetime.combine(today,dtime.min,ZoneInfo('Europe/Warsaw')).astimezone(timezone.utc)
    end_utc=datetime.combine(end+timedelta(days=1),dtime.min,ZoneInfo('Europe/Warsaw')).astimezone(timezone.utc)
    time_min=start_utc.isoformat().replace('+00:00','Z')
    time_max=end_utc.isoformat().replace('+00:00','Z')
    if provider=='google':""",name)
    src=once(src,"{'timeMin':today.isoformat()+'T00:00:00Z','timeMax':end.isoformat()+'T23:59:59Z','singleEvents':'true','maxResults':'250'}",
                "{'timeMin':time_min,'timeMax':time_max,'singleEvents':'true','maxResults':'250'}",name)
    src=once(src,"{'startDateTime':today.isoformat()+'T00:00:00Z','endDateTime':end.isoformat()+'T23:59:59Z','$top':'100'}",
                "{'startDateTime':time_min,'endDateTime':time_max,'$top':'100'}",name)
    src=once(src,"        if page == 4 and marker:\n            raise CalendarSyncError(\"Kalendarz zawiera więcej niż 5 stron wydarzeń. Import przerwany, aby nie ukrywać pominiętych terminów.\")",
"""        # Close SQLite write transaction before the next potentially slow API call.
        # Previously a slow pagination request could hold a database write lock.
        con.commit()
        if page == 4 and marker:
            raise CalendarSyncError('Kalendarz zawiera więcej niż 5 stron wydarzeń. Import nie jest kompletny; uruchom ponownie po ograniczeniu zakresu.')""",name)
    src=once(src,"        if exc.code in (409,412):raise CalendarSyncError('Konflikt wersji zdalnego wydarzenia. Odśwież dane przed ponowną próbą.') from exc","        if exc.code==409 and method=='POST':raise CalendarSyncError('Wydarzenie o podanym identyfikatorze już istnieje (HTTP 409)') from exc\n        if exc.code in (409,412):raise CalendarSyncError('Konflikt wersji zdalnego wydarzenia. Odśwież dane przed ponowną próbą.') from exc",name)
    # When updating an existing remote event, never discard its conflict token.
    src=once(src,"        result=_api(dest,token,method='PATCH',body=body,etag=existing[1] or None)\n        external=existing[0]",
"""        prior_etag=existing[1]
        if not prior_etag:
            current=_api(dest,token)
            prior_etag=str(current.get('etag') or current.get('@odata.etag') or '')
            if not prior_etag:
                raise CalendarSyncError('Nie można potwierdzić wersji wydarzenia. Aktualizacja zablokowana.')
        result=_api(dest,token,method='PATCH',body=body,etag=prior_etag)
        external=existing[0]""",name)
    src=once(src,"    else:\n        result=_api(endpoint,token,method='POST',body=body)\n        external=str(result.get('id') or '')\n        if not external:raise CalendarSyncError('API nie zwróciło identyfikatora wydarzenia')","    else:\n        # An idempotency token must be durable BEFORE a remote API request.\n        intent=con.execute('SELECT request_id FROM dev5_calendar_publish_intents WHERE provider=? AND appointment_id=?',\n                           (provider,appointment_id)).fetchone()\n        newly_created=not bool(intent)\n        if newly_created:\n            con.execute('INSERT OR IGNORE INTO dev5_calendar_publish_intents(provider,appointment_id,request_id) VALUES(?,?,?)',\n                        (provider,appointment_id,secrets.token_hex(16)))\n            con.commit()\n        intent=con.execute('SELECT request_id FROM dev5_calendar_publish_intents WHERE provider=? AND appointment_id=?',\n                           (provider,appointment_id)).fetchone()\n        request_id=str(intent[0])\n        if provider=='google':\n            body['id']=request_id\n            body['extendedProperties']={'private':{'rkPublishIntent':request_id}}\n            found=None\n            if not newly_created:\n                try:\n                    found=_api(endpoint+'/'+urllib.parse.quote(request_id,safe=''),token)\n                except CalendarSyncError as exc:\n                    if 'HTTP 404' not in str(exc):raise\n            if found:\n                if ((found.get('extendedProperties') or {}).get('private') or {}).get('rkPublishIntent')!=request_id:\n                    raise CalendarSyncError('Zdalny identyfikator jest zajęty przez inne wydarzenie')\n                result=found\n            else:\n                try:\n                    result=_api(endpoint,token,method='POST',body=body)\n                except CalendarSyncError as exc:\n                    if 'HTTP 409' not in str(exc):raise\n                    result=_api(endpoint+'/'+urllib.parse.quote(request_id,safe=''),token)\n                    if ((result.get('extendedProperties') or {}).get('private') or {}).get('rkPublishIntent')!=request_id:\n                        raise CalendarSyncError('Konflikt identyfikatora wydarzenia')\n        else:\n            # Microsoft Graph transactionId identifies repeated creation attempts.\n            body['transactionId']=request_id\n            result=_api(endpoint,token,method='POST',body=body)\n        external=str(result.get('id') or '')\n        if not external:raise CalendarSyncError('API nie zwróciło identyfikatora wydarzenia')",name)
    src=once(src,"    con.execute('''INSERT INTO dev3_calendar_links(provider,appointment_id,external_id,etag) VALUES(?,?,?,?)\n         ON CONFLICT(provider,appointment_id) DO UPDATE SET external_id=excluded.external_id,etag=excluded.etag,synced_at=CURRENT_TIMESTAMP''',\n         (provider,appointment_id,external,str(result.get('etag') or result.get('@odata.etag') or '')))\n    return external",
"""    etag=str(result.get('etag') or result.get('@odata.etag') or '')
    if not etag:
        # Some APIs omit ETag in a PATCH response. Fetch it rather than wiping
        # the local token and allowing a later blind write.
        latest=_api(endpoint+'/'+urllib.parse.quote(external,safe=''),token)
        etag=str(latest.get('etag') or latest.get('@odata.etag') or '')
    if not etag:
        raise CalendarSyncError('Wydarzenie zapisano zdalnie, ale nie można ustalić jego wersji. Przed kolejną publikacją zweryfikuj je ręcznie.')
    con.execute('''INSERT INTO dev3_calendar_links(provider,appointment_id,external_id,etag) VALUES(?,?,?,?)
         ON CONFLICT(provider,appointment_id) DO UPDATE SET external_id=excluded.external_id,etag=excluded.etag,synced_at=CURRENT_TIMESTAMP''',
         (provider,appointment_id,external,etag))
    return external""",name)
    return src


def patch_dev3(src: str) -> str:
    name='rk_dev3.py'
    src=once(src,"if path=='/worktime': self.dev3_worktime_page();return True",
                "if path=='/worktime': self.dev3_worktime_page(qs);return True",name)
    src=once(src,'    def dev3_worktime_page(self):\n',
"""    def dev3_worktime_page(self,qs=None):
        try: page=max(1,min(10000,int((qs or {}).get('page',['1'])[0])))
        except (ValueError,TypeError,IndexError): page=1
        page_size=60
        offset=(page-1)*page_size
""",name)
    src=once(src,"            entries=con.execute('''SELECT t.*,c.title case_title,c.signature,u.author_name\n                FROM dev3_time_entries t JOIN cases c ON c.id=t.case_id LEFT JOIN users u ON u.id=t.user_id\n                '''+filter_sql+' ORDER BY t.activity_date DESC,t.id DESC LIMIT 120',() if u['role']=='admin' else (u['id'],)).fetchall()",
"""            params=() if u['role']=='admin' else (u['id'],)
            total=con.execute('SELECT COUNT(*) FROM dev3_time_entries t '+filter_sql,params).fetchone()[0]
            entries=con.execute('''SELECT t.*,c.title case_title,c.signature,u.author_name
                FROM dev3_time_entries t JOIN cases c ON c.id=t.case_id LEFT JOIN users u ON u.id=t.user_id
                '''+filter_sql+' ORDER BY t.activity_date DESC,t.id DESC LIMIT ? OFFSET ?',params+(page_size,offset)).fetchall()""",name)
    src=once(src,'<a class="btn" href="/worktime/export">Eksport CSV</a></div>',
                '<div><a class="btn" href="/worktime/history">Historia korekt</a> <a class="btn" href="/worktime/export">Eksport CSV</a></div></div>',name)
    src=once(src,"        body.append('</tbody></table></div>')\n        self._dev3_html('Czas pracy',''.join(body),'worktime')",
"""        body.append('</tbody></table>')
        body.append('<p class="small">Strona %d · wpisy %d–%d z %d</p>'%(page,min(offset+1,total) if total else 0,min(offset+len(entries),total),total))
        if page>1:body.append('<a class="btn small" href="/worktime?page=%d">← Poprzednia</a> '%(page-1))
        if offset+page_size<total:body.append('<a class="btn small" href="/worktime?page=%d">Następna →</a>'%(page+1))
        body.append('</div>')
        self._dev3_html('Czas pracy',''.join(body),'worktime')""",name)
    src=once(src,"ORDER BY a.appointment_date DESC LIMIT 120",
                "ORDER BY CASE WHEN a.appointment_date >= date('now','localtime') THEN 0 ELSE 1 END, CASE WHEN a.appointment_date >= date('now','localtime') THEN a.appointment_date END ASC, a.appointment_date DESC, a.appointment_time ASC LIMIT 120",name)
    # Court portal: centralized portal may be hosted for more than one appellate area.
    # Keep the official default, allow a verified local override.
    src=once(src,"        s=['<div class=\"topbar\"><div><h1>Portal Informacyjny — import do weryfikacji</h1><p class=\"sub\">Obsługa ręcznie wyeksportowanych danych; automatyczne API wymaga autoryzacji i oficjalnej specyfikacji.</p></div><a class=\"btn\" href=\"https://portal.wroclaw.sa.gov.pl\" target=\"_blank\" rel=\"noopener noreferrer\">Otwórz Portal</a></div>']",
"""        portal_url=os.environ.get('RK_COURT_PORTAL_URL','https://portal.wroclaw.sa.gov.pl/#/login').strip()
        from urllib.parse import urlsplit
        parsed=urlsplit(portal_url)
        if parsed.scheme!='https' or not re.fullmatch(r'portal\\.[a-z0-9-]+\\.sa\\.gov\\.pl',parsed.hostname or '') or parsed.username or parsed.password:
            portal_url='https://portal.wroclaw.sa.gov.pl/#/login'
        s=['<div class="topbar"><div><h1>Portal Informacyjny — import do weryfikacji</h1><p class="sub">Obsługa ręcznie wyeksportowanych danych; automatyczne API wymaga autoryzacji i oficjalnej specyfikacji.</p></div><a class="btn" href="%s" target="_blank" rel="noopener noreferrer">Otwórz Portal</a></div>'%esc(portal_url)]""",name)
    return src


def patch_dev4(src: str) -> str:
    name='rk_dev4.py'
    src=once(src,'import re\n','import re\nimport json\nimport os\nimport uuid\n',name)
    src=once(src,"        m=re.fullmatch(r'/worktime/(\\d+)/edit',path)",
"""        if path=='/worktime/history':
            self.dev4_time_history(qs);return True
        m=re.fullmatch(r'/worktime/(\\d+)/edit',path)""",name)
    # Correct before data is deleted: rename ciphertext to tombstone and roll back if DB commit fails.
    begin=src.index('    def dev4_vault_change(self,file_id,kind,fields):')
    src=src[:begin]+"""    def dev4_time_history(self,qs):
        app=self._dev3_app();user=self._dev3_me()
        try:page=max(1,min(10000,int((qs or {}).get('page',['1'])[0])))
        except (ValueError,TypeError,IndexError):page=1
        limit=50
        where='' if user['role']=='admin' else 'WHERE t.user_id=?'
        params=() if user['role']=='admin' else (user['id'],)
        with app.db() as con:
            total=con.execute('SELECT COUNT(*) FROM dev4_time_corrections h JOIN dev3_time_entries t ON t.id=h.entry_id '+where,params).fetchone()[0]
            rows=con.execute('''SELECT h.*,t.activity_date,t.description,t.minutes,t.rate_grosze,
                t.billable,t.case_id FROM dev4_time_corrections h
                JOIN dev3_time_entries t ON t.id=h.entry_id '''+where+
                ' ORDER BY h.id DESC LIMIT ? OFFSET ?',params+(limit,(page-1)*limit)).fetchall()
        out=['<div class="topbar"><h1>Historia korekt czasu pracy</h1><a class="btn" href="/worktime">Wróć</a></div><div class="card">']
        for r in rows:
            try:old=json.loads(r['previous_value'])
            except (ValueError,TypeError):old={}
            out.append('<div class="dev3-item"><b>Wpis #%s · korekta %s</b><p>Przed: %s · %s minut · %s</p><p>Aktualnie: %s · %s minut · %s</p><details><summary>Pozostałe poprzednie dane</summary><pre>%s</pre></details></div>'%(
                int(r['entry_id']),esc(r['created_at']),esc(old.get('activity_date','—')),
                esc(old.get('minutes','—')),esc(old.get('description','')),
                esc(r['activity_date']),esc(r['minutes']),esc(r['description']),
                esc(json.dumps(old,ensure_ascii=False,indent=2))))
        if not rows:out.append('<p>Brak korekt na tej stronie.</p>')
        out.append('<p>Strona %s · łączna liczba korekt: %s</p>'%(page,total))
        if page>1:out.append('<a class="btn small" href="/worktime/history?page=%s">← Poprzednia</a> '%(page-1))
        if page*limit<total:out.append('<a class="btn small" href="/worktime/history?page=%s">Następna →</a>'%(page+1))
        out.append('</div>')
        self._dev3_html('Historia korekt',''.join(out),'worktime')

    def dev4_vault_change(self,file_id,kind,fields):
        app=self._dev3_app();user=self._dev3_me()
        with app.db() as con:
            row=con.execute('SELECT * FROM dev3_vault_files WHERE id=?',(file_id,)).fetchone()
            if not row:raise ValueError('Plik sejfu nie istnieje')
            permitted=user['role']=='admin' or row['owner_id']==user['id']
            if not permitted:raise ValueError('Brak uprawnień do zmiany pliku')
            path=vault_file_path(app.FILES_DIR,row['stored_name'])
        if kind=='rotate':
            # Keep the old encrypted bytes until DB audit transaction commits.
            # If that audit fails, revert the atomic replacement.
            old_ciphertext=path.read_bytes()
            try:
                with app.db() as con:
                    vault_rotate(con,app.FILES_DIR,file_id,permitted,
                                 fields.get('old_passphrase',''),fields.get('new_passphrase',''))
                    action_log(con,row['case_id'],user['id'],'Zmiana hasła sejfu',f'Plik {file_id}')
            except Exception:
                from rk_core.files import atomic_write_bytes
                if path.exists() and path.read_bytes()!=old_ciphertext:
                    atomic_write_bytes(path,old_ciphertext)
                raise
        else:
            if fields.get('confirmation')!='USUŃ':
                raise ValueError('Wpisz USUŃ, aby usunąć plik sejfu')
            if not path.is_file():raise ValueError('Brak szyfrogramu; usuwanie wstrzymano')
            staged=path.with_name('.pending_delete_'+uuid.uuid4().hex+'.rkv')
            os.replace(path,staged)
            try:
                with app.db() as con:
                    action_log(con,row['case_id'],user['id'],'Usunięcie pliku sejfu',f'Plik {file_id}')
                    vault_delete(con,app.FILES_DIR,file_id,permitted)
            except Exception:
                os.replace(staged,path)
                raise
            try:
                staged.unlink()
            except OSError as exc:
                # An encrypted orphan remains, intentionally outside active vault.
                app.log_app_exception('/vault/%s/delete-orphan'%file_id,exc)
                raise ValueError('Wpis usunięto, ale pozostał zaszyfrowany plik techniczny. Skontaktuj się z administratorem.') from exc
        self.redirect('/vault')
"""
    return src


def patch_routes(src: str) -> str:
    return once(src,"    '/backup/encrypted': ('encrypted_backup', 'f'),",
                "    '/backup/encrypted': ('encrypted_backup', 'f'),\n    '/backup/snapshot/download': ('full_snapshot_download_encrypted', 'f'),",'rk_routes.py')


def patch_app(src: str) -> str:
    name='app.py'
    src=once(src,'VERSION = "0.4.0-dev4"','VERSION = "0.4.0-dev5"\nRK_040_DEV5_STABILIZATION_20261108 = True',name)
    src=once(src,'from rk_dev3_core import ensure_dev3_schema',
                'from rk_dev3_core import ensure_dev3_schema, encrypt_vault, decrypt_vault, MAGIC as VAULT_MAGIC',name)
    src=once(src,'from rk_core.files import atomic_write_bytes',
                'from rk_core.files import atomic_write_bytes\nfrom rk_dev5_snapshot import sha256_path, verify_snapshot_manifest',name)
    src=once(src,'SESSION_CACHE_SECONDS = 8.0',
                'SESSION_CACHE_SECONDS = 0.0  # Bezpiecznie: natychmiast sprawdzaj rolę i aktywność w SQLite',name)
    # Snapshot internal ZIP now records SHA-256 for every included member.
    src=once(src,"            z.write(tmp,'sprawnik.sqlite3')",
                "            z.write(tmp,'sprawnik.sqlite3')\n            file_hashes={'sprawnik.sqlite3':sha256_path(tmp)}",name)
    src=once(src,"            z.writestr('snapshot.json',json.dumps(meta,ensure_ascii=False,indent=2))\n            for root,prefix in ((FILES_DIR,'dokumenty'),(DRAFTS_DIR,'projekty_pism')):",
                "            for root,prefix in ((FILES_DIR,'dokumenty'),(DRAFTS_DIR,'projekty_pism')):",name)
    src=once(src,'                            try: z.write(fp,f"{prefix}/{fp.relative_to(root).as_posix()}")',
"""                            try:
                                arc=f'{prefix}/{fp.relative_to(root).as_posix()}'
                                z.write(fp,arc)
                                file_hashes[arc]=sha256_path(fp)""",name)
    src=once(src,'                                raise RuntimeError(f"Nie można wykonać kompletnej kopii: {fp}") from exc\n        return out.getvalue()',
"""                                raise RuntimeError(f"Nie można wykonać kompletnej kopii: {fp}") from exc
            meta['file_sha256']=file_hashes
            z.writestr('snapshot.json',json.dumps(meta,ensure_ascii=False,indent=2))
        return out.getvalue()""",name)
    src=once(src,"        if meta.get('format')!='RK-KANCELARIA-DATA-SNAPSHOT':\n            return False,'Nieprawidłowy format snapshotu RK KANCELARIA.'",
"""        if meta.get('format')!='RK-KANCELARIA-DATA-SNAPSHOT':
            return False,'Nieprawidłowy format snapshotu RK KANCELARIA.'
        verify_snapshot_manifest(z,meta,allow_legacy=True)""",name)
    src=once(src,"                names=set(z.namelist())\n                db_copy=Path(td)/'sprawnik.sqlite3'",
"""                names=set(z.namelist())
                manifest=json.loads(z.read('snapshot.json').decode('utf-8'))
                checked=verify_snapshot_manifest(z,manifest,allow_legacy=True)
                db_copy=Path(td)/'sprawnik.sqlite3'""",name)
    src=once(src,"                details=' · '.join(f'{k}: {v}' for k,v in counts.items())+f' · pliki dokumentów: komplet · {name}'",
                "                details=' · '.join(f'{k}: {v}' for k,v in counts.items())+f' · pliki dokumentów: komplet · SHA-256: {checked} plików · {name}'",name)

    src=once(src,"            # Vault files remain accessible after deleting their original owner.\n            moved=con.execute(\"UPDATE dev3_vault_files SET owner_id=? WHERE owner_id=?\",(me['id'],uid)).rowcount\n            if moved:action_log(con,None,me['id'],'Przejęcie sejfu po usunięciu konta',\n                                f'Użytkownik {uid}; dokumenty {moved}')",
"""            # Deletion must not silently transfer encrypted files whose passwords
            # the administrator may not know. Require explicit vault handover first.
            held=con.execute('SELECT COUNT(*) FROM dev3_vault_files WHERE owner_id=?',(uid,)).fetchone()[0]
            if held:
                return self.user_edit_page(uid,'Konto ma %s plików sejfu. Przed usunięciem przekaż pliki i hasła właścicielowi lub dezaktywuj konto; automatyczne przejęcie nie odszyfrowuje dokumentów.'%held)""",name)
    # Replace naked local export with a user-chosen passphrase.
    old="""    def full_snapshot_download(self):
        if not self.require_admin(): return
        data,name=create_data_snapshot_zip()
        try:
            with db() as con: immutable_audit(con,None,'snapshot',None,'Pobrano pełny snapshot danych',f'{name} · {len(data)} B',self.current_author())
        except Exception: pass
        self.send_response(200); self.send_header('Content-Type','application/zip'); self.send_header('Content-Disposition',f\"attachment; filename*=UTF-8''{quote(name)}\"); self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(data)
"""
    new="""    def full_snapshot_download(self):
        if not self.require_admin(): return
        body='''<div class="topbar"><h1>Zaszyfruj pełny snapshot</h1><a class="btn" href="/backups">Wróć</a></div>
        <div class="card"><p>Pełna kopia zawiera bazę kancelarii i wszystkie załączniki.
        Wybierz silne hasło (minimum 12 znaków); nie jest ono zapisywane przez aplikację.
        Bez hasła odzyskanie danych z kopii będzie niemożliwe.</p>
        <form method="post" action="/backup/snapshot/download">
        <label>Hasło kopii</label><input type="password" name="passphrase" minlength="12" autocomplete="new-password" required>
        <label>Powtórz hasło</label><input type="password" name="passphrase_confirm" minlength="12" autocomplete="new-password" required>
        <button class="btn primary">Pobierz zaszyfrowany snapshot</button></form></div>'''
        self.send_html(layout('Pełny snapshot',body,'backups'))

    def full_snapshot_download_encrypted(self,f):
        if not self.require_admin(): return
        password=f.get('passphrase','') or ''
        if len(password)<12 or password!=f.get('passphrase_confirm',''):
            return self.send_html(layout('Błąd hasła','<div class="card">Hasło musi mieć co najmniej 12 znaków, a oba pola muszą być identyczne.</div>','backups'),400)
        raw,name=create_data_snapshot_zip()
        data=encrypt_vault(raw,password)
        secure_name=name+'.rkenc'
        with db() as con:
            immutable_audit(con,None,'snapshot',None,'Pobrano zaszyfrowany snapshot',secure_name,self.current_author())
        self.send_response(200)
        self.send_header('Content-Type','application/octet-stream')
        self.send_header('Content-Disposition',f"attachment; filename*=UTF-8''{quote(secure_name)}")
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers();self.wfile.write(data)
"""
    src=once(src,old,new,name)
    src=once(src,"<input type='file' name='snapshot' accept='.zip' required><button class='btn'>Zweryfikuj i przygotuj restore</button>",
"<input type='file' name='snapshot' accept='.zip,.rkenc' required><label>Hasło (tylko dla pliku .rkenc)</label><input type='password' name='passphrase' autocomplete='off'><button class='btn'>Zweryfikuj i przygotuj restore</button>",name)
    src=once(src,"        if not uploaded or not uploaded[1]: return self.recovery_page('Wybierz plik snapshot ZIP.')\n        create_shutdown_backup(retention=30)\n        ok,msg=schedule_data_snapshot_restore(uploaded[1],uploaded[0] or 'snapshot',0)",
"""        if not uploaded or not uploaded[1]: return self.recovery_page('Wybierz plik snapshot ZIP lub RKENC.')
        raw=uploaded[1]
        if raw.startswith(VAULT_MAGIC):
            try:raw=decrypt_vault(raw,f.get('passphrase',''))
            except ValueError as exc:return self.recovery_page('Błąd hasła kopii lub uszkodzona kopia: '+str(exc))
        create_shutdown_backup(retention=30)
        ok,msg=schedule_data_snapshot_restore(raw,uploaded[0] or 'snapshot',0)""",name)
    return src


def patch_workflow(src: str) -> str:
    name='.github/workflows/main.yml'
    src=once(src,'name: Build RK KANCELARIA Windows Portable (dev4)',
                'name: Build RK KANCELARIA Windows Portable (dev5)',name)
    src=once(src,"if ($code.Contains('VERSION = \"0.4.0-dev4\"')) {",
                "if ($code.Contains('VERSION = \"0.4.0-dev5\"')) {",name)
    src=once(src,"Write-Host 'Dev4 już obecna — pomijam historyczne migratory.'",
                "Write-Host 'Dev5 już obecna — pomijam historyczne migratory.'",name)
    src=once(src,"throw 'Dev4 wymaga działającej wersji dev3 R2. Wstrzymano migrację nieznanej wersji.'",
                "throw 'Dev5 wymaga działającej wersji dev3 R2. Wstrzymano migrację nieznanej wersji.'",name)
    src=once(src,"""      - name: Zastosuj RK 0.4.0-dev4 — naprawy i migracja bez danych klientów
        shell: pwsh
        run: |
          python ZASTOSUJ_040_DEV4.py . --dry-run
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
          python ZASTOSUJ_040_DEV4.py .
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
          python ZASTOSUJ_040_DEV4.py . --verify
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
""","""      - name: Zweryfikuj kod aktualizacji 0.4.0-dev5
        shell: pwsh
        run: |
          python ZASTOSUJ_040_DEV5.py . --verify
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
""",name)
    src=once(src,'      - name: Audyt, testy regresji, samokontrola backendu',
                "      - name: Testy regresji dev5\n        shell: pwsh\n        run: |\n          python TEST_RK_DEV5.py\n          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n      - name: Audyt, testy regresji, samokontrola backendu",name)
    # The previous dev4 workflow automatically pushed any generated edits to main.
    # With the dev5 package the repository must contain committed, reviewed source.
    # Remove the self-push step; CI now checks the committed files directly.
    start=src.index('      - name: Zapisz przetestowane zmiany źródeł na main')
    end=src.index('      - name: Utwórz Portable ZIP',start)
    src=src[:start]+src[end:]
    src=once(src,'name: RK-KANCELARIA-DEV4-TESTY','name: RK-KANCELARIA-DEV5-TESTY',name)
    return src


PATCHES={
    'app.py':patch_app,
    'rk_dev3_core.py':patch_core,
    'rk_dev3_calendar.py':patch_calendar,
    'rk_dev3.py':patch_dev3,
    'rk_dev4.py':patch_dev4,
    'rk_routes.py':patch_routes,
    '.github/workflows/main.yml':patch_workflow,
    'TEST_ARCHITEKTURA_040.py':lambda src:once(src,'self.assertIn(\'VERSION = "0.4.0-dev4"\',app)',
        'self.assertIn(\'VERSION = "0.4.0-dev5"\',app)','TEST_ARCHITEKTURA_040.py'),
    'RAPORT_JAKOSCI_040.py':lambda src:once(src,"'version':'0.4.0-dev4'","'version':'0.4.0-dev5'",'RAPORT_JAKOSCI_040.py'),
    'AUDYT_I_TESTY_RK_040_DEV2.py':lambda src:once(src,"'version':'0.4.0-dev4'","'version':'0.4.0-dev5'",'AUDYT_I_TESTY_RK_040_DEV2.py'),
    'rk_windows_version.txt':lambda src:once(
        once(once(src,'filevers=(0, 4, 0, 4), prodvers=(0, 4, 0, 4)',
                'filevers=(0, 4, 0, 5), prodvers=(0, 4, 0, 5)','rk_windows_version.txt'),
            "StringStruct('FileVersion', '0.4.0.4')","StringStruct('FileVersion', '0.4.0.5')",'rk_windows_version.txt'),
        "StringStruct('ProductVersion', '0.4.0-dev4')","StringStruct('ProductVersion', '0.4.0-dev5')",'rk_windows_version.txt'),
}


def run(root: Path, verify: bool=False, dry_run: bool=False) -> None:
    app=root/'app.py'
    if not app.is_file():raise RuntimeError('Brak app.py we wskazanym katalogu')
    version=(app.read_text('utf-8').split('VERSION = ',1)[-1][:22])
    if verify:
        if '0.4.0-dev5' not in version:raise RuntimeError('Nie wykryto dev5 w app.py')
        for rel,needle in [('rk_dev3.py','def dev3_worktime_page(self,qs=None)'),
            ('rk_dev4.py','def dev4_time_history(self,qs)'),
            ('rk_routes.py',"'/backup/snapshot/download'"),
            ('.github/workflows/main.yml','python TEST_RK_DEV5.py')]:
            if needle not in (root/rel).read_text('utf-8'):
                raise RuntimeError('Brak zmiany: '+rel)
        print('DEV5: wersja i punkty integracji — OK')
        return
    if '0.4.0-dev4' not in version:raise RuntimeError('Oczekiwana wersja 0.4.0-dev4. Nie zmieniono plików.')
    changes={}
    for rel,func in PATCHES.items():
        old=(root/rel).read_text('utf-8')
        new=func(old)
        if rel.endswith('.py'):ast.parse(new,filename=rel)
        changes[rel]=(old,new)
    if not (root/'rk_dev5_snapshot.py').is_file():
        raise RuntimeError('Brak rk_dev5_snapshot.py obok patchera. Nie zmieniono plików.')
    ast.parse((root/'rk_dev5_snapshot.py').read_text('utf-8'),filename='rk_dev5_snapshot.py')
    if not (root/'TEST_RK_DEV5.py').is_file():
        raise RuntimeError('Brak TEST_RK_DEV5.py obok patchera. Nie zmieniono plików.')
    ast.parse((root/'TEST_RK_DEV5.py').read_text('utf-8'),filename='TEST_RK_DEV5.py')
    print('Zmiany zaplanowane i sprawdzone składniowo:')
    for path in changes:print(' -',path)
    if dry_run:print('DRY RUN: żadne pliki nie zostały zmienione');return
    # All source edits validated before any write. Restore originals on IO errors.
    written=[]
    try:
        for rel,(old,new) in changes.items():
            target=root/rel
            tmp=target.with_name(target.name+'.dev5tmp')
            tmp.write_text(new,encoding='utf-8',newline='')
            os.replace(tmp,target)
            written.append(rel)
    except Exception:
        for rel in reversed(written):
            (root/rel).write_text(changes[rel][0],encoding='utf-8',newline='')
        raise
    print('DEV5: kod został zaktualizowany. Uruchom python TEST_RK_DEV5.py')


if __name__=='__main__':
    # This historical dev5 patcher supplies BASE_PATCHES to the full updater.
    # Do not accidentally install only the incomplete hotfix: delegate CLI.
    from ZASTOSUJ_040_DEV5_PELNA import run as run_full
    parser=argparse.ArgumentParser(description='RK KANCELARIA dev5 full repair')
    parser.add_argument('root',nargs='?',default='.')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--verify',action='store_true')
    options=parser.parse_args()
    try:run_full(Path(options.root),options.verify,options.dry_run)
    except Exception as exc:
        print('AKTUALIZACJA WSTRZYMANA:',exc,file=sys.stderr)
        raise SystemExit(1)
