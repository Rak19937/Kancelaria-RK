# -*- coding: utf-8 -*-
"""RK KANCELARIA dev3: web UI for stages, hours, encrypted vault and integrations."""
from __future__ import annotations
import html
import os
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import quote
from rk_dev3_core import (STAGES,set_stage,rate_grosze,start_timer,stop_timer,add_manual_time,
                          time_csv,vault_can_view,vault_store,decrypt_vault,import_portal_csv)
from rk_dev3_calendar import (SUPPORTED,CalendarSyncError,access_token,pull_proposals,
                              publish_appointment,accept_proposal)
from rk_dev4_core import audit_if_available


def esc(value):
    return html.escape(str('' if value is None else value),quote=True)


def cases_select(rows, name='case_id', selected=None):
    return '<select name="%s" required><option value="">— wybierz sprawę —</option>%s</select>'%(
        esc(name),''.join('<option value="%s" %s>%s</option>'%(r['id'],'selected' if str(selected)==str(r['id']) else '',
              esc((r['signature'] or '—')+' · '+r['title'])) for r in rows))


class Dev3Mixin:
    def _dev3_app(self):
        return sys.modules[type(self).__module__]

    def _dev3_me(self):
        user=self._dev3_app().current_request_user()
        if not user:raise ValueError('Zaloguj się ponownie.')
        return user

    def _dev3_html(self,title,body,active=''):
        return self.send_html(self._dev3_app().layout(title,body,active))

    def _dev3_error(self,exc,code=400):
        a=self._dev3_app()
        self.send_html(a.layout('Błąd operacji','<div class="card"><h1>Operacja nie została wykonana</h1><p>%s</p><a class="btn" href="/">Wróć do pulpitu</a></div>'%esc(str(exc))),code)

    def _dev3_admin(self):
        if self._dev3_me()['role']!='admin':
            self._dev3_error('Ta operacja wymaga uprawnień administratora.',403)
            return False
        return True

    def dev3_get(self,path,qs):
        if path=='/worktime': self.dev3_worktime_page(qs);return True
        if path=='/worktime/export': self.dev3_worktime_export();return True
        if path=='/stages': self.dev3_stages_page();return True
        if re.fullmatch(r'/case/\d+/stage',path):self.dev3_case_stage_page(int(path.split('/')[2]));return True
        if path=='/vault':self.dev3_vault_page();return True
        if path=='/court-portal':self.dev3_court_page();return True
        if path=='/calendar-sync':self.dev3_calendar_page();return True
        return False

    def dev3_post(self,path,fields,files):
        funcs={
            '/worktime/start':lambda:self.dev3_start(fields),
            '/worktime/stop':lambda:self.dev3_stop(fields),
            '/worktime/cancel':lambda:self.dev3_cancel(),
            '/worktime/add':lambda:self.dev3_time_add(fields),
            '/vault/upload':lambda:self.dev3_vault_upload(fields,files),
            '/court-portal/import':lambda:self.dev3_court_import(files),
            '/calendar-sync/pull':lambda:self.dev3_calendar_pull(fields),
            '/calendar-sync/publish':lambda:self.dev3_calendar_publish(fields),
            '/calendar-sync/accept':lambda:self.dev3_calendar_accept(fields),
            '/calendar-sync/dismiss':lambda:self.dev3_calendar_dismiss(fields),
            '/calendar-sync/review':lambda:self.dev3_calendar_review(fields),
        }
        if re.fullmatch(r'/case/\d+/stage',path):fn=lambda:self.dev3_case_stage_save(int(path.split('/')[2]),fields)
        elif re.fullmatch(r'/worktime/\d+/delete',path):fn=lambda:self.dev3_time_delete(int(path.split('/')[2]))
        elif re.fullmatch(r'/vault/\d+/download',path):fn=lambda:self.dev3_vault_download(int(path.split('/')[2]),fields)
        elif re.fullmatch(r'/vault/\d+/grant',path):fn=lambda:self.dev3_vault_grant(int(path.split('/')[2]),fields)
        elif re.fullmatch(r'/vault/\d+/revoke',path):fn=lambda:self.dev3_vault_revoke(int(path.split('/')[2]),fields)
        elif re.fullmatch(r'/court-portal/\d+/review',path):fn=lambda:self.dev3_court_review(int(path.split('/')[2]),fields)
        else:fn=funcs.get(path)
        if not fn:return False
        try:fn()
        except (ValueError,CalendarSyncError,LookupError) as exc:self._dev3_error(exc)
        return True

    def dev3_stages_page(self):
        a=self._dev3_app()
        with a.db() as con:
            rows=con.execute('''SELECT c.id,c.signature,c.title,COALESCE(s.stage,'intake') stage
              FROM cases c LEFT JOIN dev3_case_stage s ON s.case_id=c.id
              ORDER BY c.status='closed',c.title LIMIT 200''').fetchall()
        parts=["<div class='topbar'><div><h1>Etapy postępowań</h1><p class='sub'>Etap sprawy nie zastępuje statusu zadania ani statusu zamknięcia.</p></div></div><div class='card'><table><thead><tr><th>Sprawa</th><th>Etap</th><th></th></tr></thead><tbody>"]
        for r in rows:
            parts.append('<tr><td>%s · %s</td><td>%s</td><td><a class="btn small" href="/case/%s/stage">Zmień</a></td></tr>'%(esc(r['signature']),esc(r['title']),esc(STAGES.get(r['stage'],r['stage'])),r['id']))
        parts.append('</tbody></table></div>')
        self._dev3_html('Etapy postępowań',''.join(parts),'stages')

    def dev3_case_stage_page(self,case_id):
        a=self._dev3_app()
        with a.db() as con:
            c=con.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
            if not c:return self.send_error(404)
            current=con.execute('SELECT stage,note FROM dev3_case_stage WHERE case_id=?',(case_id,)).fetchone()
            logs=con.execute('SELECT * FROM dev3_stage_log WHERE case_id=? ORDER BY id DESC LIMIT 30',(case_id,)).fetchall()
        val=current['stage'] if current else 'intake'
        options=''.join('<option value="%s" %s>%s</option>'%(k,'selected' if k==val else '',esc(v)) for k,v in STAGES.items())
        body='<div class="topbar"><h1>Etap sprawy: %s</h1></div><div class="card"><form method="post" action="/case/%s/stage"><label>Etap postępowania</label><select name="stage">%s</select><label>Uzasadnienie zmiany</label><textarea name="note" maxlength="2000"></textarea><button class="btn primary">Zapisz etap</button></form></div><div class="card"><h2>Historia etapów</h2>'%(esc(c['title']),case_id,options)
        body+=''.join('<p>%s · %s → %s · %s</p>'%(esc(r['created_at']),esc(STAGES.get(r['old_stage'],r['old_stage'])),esc(STAGES.get(r['new_stage'],r['new_stage'])),esc(r['note'])) for r in logs)
        body += '<p><a class="btn primary" href="/case/%d/phases">＋ Etapy równoległe / dodaj własny etap</a></p>' % case_id
        self._dev3_html('Etap postępowania',body+'</div>','stages')

    def dev3_case_stage_save(self,case_id,f):
        a=self._dev3_app();u=self._dev3_me()
        with a.db() as con:
            if a.case_read_only(con,case_id):
                raise ValueError('Sprawa jest zablokowana. Administrator musi ją najpierw odblokować.')
            set_stage(con,case_id,f.get('stage',''),u['id'],f.get('note',''))
            audit_if_available(con,case_id,u['id'],'Zmiana etapu postępowania',f.get('stage',''))
        self.redirect('/case/%d/stage'%case_id)

    def dev3_worktime_page(self,qs=None):
        try: page=max(1,min(10000,int((qs or {}).get('page',['1'])[0])))
        except (ValueError,TypeError,IndexError): page=1
        page_size=60
        offset=(page-1)*page_size
        a=self._dev3_app();u=self._dev3_me()
        with a.db() as con:
            cases=con.execute('SELECT id,signature,title FROM cases ORDER BY status="closed",title LIMIT 1000').fetchall()
            running=con.execute('''SELECT t.*,c.title case_title FROM dev3_time_running t JOIN cases c ON c.id=t.case_id WHERE user_id=?''',(u['id'],)).fetchone()
            filter_sql='' if u['role']=='admin' else 'WHERE t.user_id=?'
            if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dev4_time_voids'").fetchone():
                filter_sql+=(' AND ' if filter_sql else 'WHERE ')+"NOT EXISTS(SELECT 1 FROM dev4_time_voids v WHERE v.entry_id=t.id)"
            params=() if u['role']=='admin' else (u['id'],)
            total=con.execute('SELECT COUNT(*) FROM dev3_time_entries t '+filter_sql,params).fetchone()[0]
            entries=con.execute('''SELECT t.*,c.title case_title,c.signature,u.author_name
                FROM dev3_time_entries t JOIN cases c ON c.id=t.case_id LEFT JOIN users u ON u.id=t.user_id
                '''+filter_sql+' ORDER BY t.activity_date DESC,t.id DESC LIMIT ? OFFSET ?',params+(page_size,offset)).fetchall()
        body=['<div class="topbar"><div><h1>Ewidencja czasu pracy</h1><div class="sub">Stoper, ręczne wpisy i raport rozliczeń. Czas rejestrowany jest przy konkretnej sprawie.</div></div><div><a class="btn" href="/worktime/history">Historia korekt</a> <a class="btn" href="/worktime/export">Eksport CSV</a></div></div>']
        if running:
            body.append('<div class="card"><h2>Stoper jest uruchomiony</h2><p><b>%s</b> · od %s UTC</p><p>Upłynęło: <output data-rk-dev3-timer-start="%s">—</output></p><form method="post" action="/worktime/stop"><label>Stawka PLN za godzinę</label><input type="number" name="rate" step="0.01" min="0" value="0"><label><input type="checkbox" name="billable" value="1" checked> Rozliczalne</label><button class="btn primary">Zatrzymaj i zapisz</button></form><form method="post" action="/worktime/cancel" onsubmit="return confirm(&#39;Anulować pomiar bez zapisywania czasu?&#39;)"><button class="btn danger">Anuluj pomiar bez zapisywania</button></form></div>'%(esc(running['case_title']),esc(running['started_at']),esc(running['started_at'])))
        else:
            body.append('<div class="card"><h2>Rozpocznij pomiar czasu</h2><form method="post" action="/worktime/start">'+cases_select(cases)+'<label>Opis czynności</label><input name="description" maxlength="1000" placeholder="np. analiza pozwu"><button class="btn primary">Uruchom stoper</button></form></div>')
        body.append('<div class="card"><h2>Dodaj czas ręcznie</h2><form method="post" action="/worktime/add" class="form-grid"><div><label>Sprawa</label>'+cases_select(cases)+'</div><div><label>Data</label><input type="date" name="day" value="%s" required></div><div><label>Minuty</label><input type="number" name="minutes" min="1" max="1440" value="60" required></div><div><label>Stawka PLN/h</label><input type="number" name="rate" step="0.01" min="0" value="0"></div><div class="full"><label>Opis</label><input name="description" maxlength="2000"></div><div class="full"><label><input type="checkbox" name="billable" checked value="1"> Rozliczalne</label></div><button class="btn primary">Zapisz czas</button></form></div>'%date.today().isoformat())
        body.append('<div class="card"><h2>Ostatnie wpisy</h2><table><thead><tr><th>Data</th><th>Sprawa</th><th>Pracownik</th><th>Minuty</th><th>Kwota</th><th></th></tr></thead><tbody>')
        for x in entries:
            total=(x['minutes']*x['rate_grosze']//60/100) if x['billable'] else 0
            delete=('<a class="btn small" href="/worktime/%d/edit">Popraw</a> <form method="post" style="display:inline" action="/worktime/%d/delete" onsubmit="return confirm(\'Anulować wpis i zachować historię?\')"><button class="btn small danger">Anuluj wpis</button></form>'%(x['id'],x['id'])) if (u['role']=='admin' or x['user_id']==u['id']) else ''
            body.append('<tr><td>%s</td><td>%s<br><span class="small">%s</span></td><td>%s</td><td>%s</td><td>%.2f PLN</td><td>%s</td></tr>'%(esc(x['activity_date']),esc(x['case_title']),esc(x['description']),esc(x['author_name']),x['minutes'],total,delete))
        body.append('</tbody></table>')
        body.append('<p class="small">Strona %d · wpisy %d–%d z %d</p>'%(page,min(offset+1,total) if total else 0,min(offset+len(entries),total),total))
        if page>1:body.append('<a class="btn small" href="/worktime?page=%d">← Poprzednia</a> '%(page-1))
        if offset+page_size<total:body.append('<a class="btn small" href="/worktime?page=%d">Następna →</a>'%(page+1))
        body.append('</div>')
        self._dev3_html('Czas pracy',''.join(body),'worktime')

    def dev3_start(self,f):
        a=self._dev3_app();u=self._dev3_me()
        with a.db() as con:
            start_timer(con,u['id'],int(f.get('case_id') or 0),f.get('description',''))
            audit_if_available(con,int(f.get('case_id') or 0),u['id'],'Uruchomienie stopera')
        self.redirect('/worktime')

    def dev3_stop(self,f):
        a=self._dev3_app();u=self._dev3_me()
        with a.db() as con:
            stop_timer(con,u['id'],rate_grosze(f.get('rate') or '0'),bool(f.get('billable')))
            audit_if_available(con,None,u['id'],'Zatrzymanie stopera i zapis czasu')
        self.redirect('/worktime')

    def dev3_cancel(self):
        a=self._dev3_app();u=self._dev3_me()
        with a.db() as con:
            changed=con.execute('DELETE FROM dev3_time_running WHERE user_id=?',(u['id'],)).rowcount
            if not changed:raise ValueError('Nie ma aktywnego stopera do anulowania')
            audit_if_available(con,None,u['id'],'Anulowanie stopera bez zapisu')
        self.redirect('/worktime')

    def dev3_time_add(self,f):
        a=self._dev3_app();u=self._dev3_me()
        with a.db() as con:
            add_manual_time(con,int(f.get('case_id') or 0),u['id'],f.get('day',''),int(f.get('minutes') or 0),f.get('description',''),rate_grosze(f.get('rate') or '0'),bool(f.get('billable')))
            audit_if_available(con,int(f.get('case_id') or 0),u['id'],'Ręczny wpis czasu pracy')
        self.redirect('/worktime')

    def dev3_time_delete(self,entry_id):
        a=self._dev3_app();u=self._dev3_me()
        with a.db() as con:
            row=con.execute('SELECT * FROM dev3_time_entries WHERE id=?',(entry_id,)).fetchone()
            if not row:return self.send_error(404)
            if u['role']!='admin' and row['user_id']!=u['id']:return self._dev3_error('Brak uprawnień do tego wpisu',403)
            con.execute('DELETE FROM dev3_time_entries WHERE id=?',(entry_id,))
        self.redirect('/worktime')

    def dev3_worktime_export(self):
        a=self._dev3_app();u=self._dev3_me()
        with a.db() as con:data=time_csv(con,None if u['role']=='admin' else u['id'])
        self.send_response(200);self.send_header('Content-Type','text/csv; charset=utf-8')
        self.send_header('Content-Disposition','attachment; filename="rk_czas_pracy.csv"')
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)

    def dev3_vault_page(self):
        a=self._dev3_app();u=self._dev3_me()
        with a.db() as con:
            cases=con.execute('SELECT id,title,signature FROM cases ORDER BY title LIMIT 1000').fetchall()
            where='' if u['role']=='admin' else '''WHERE v.owner_id=? OR EXISTS(SELECT 1 FROM dev3_vault_grants g WHERE g.file_id=v.id AND g.user_id=?)'''
            files=con.execute('''SELECT v.*,c.title case_title FROM dev3_vault_files v JOIN cases c ON c.id=v.case_id '''+where+' ORDER BY v.id DESC',() if u['role']=='admin' else (u['id'],u['id'])).fetchall()
            people=con.execute('SELECT id,author_name FROM users WHERE is_active=1 ORDER BY author_name').fetchall()
            active_grants=con.execute('''SELECT g.file_id,g.user_id,u.author_name FROM dev3_vault_grants g
                JOIN users u ON u.id=g.user_id WHERE u.is_active=1 ORDER BY u.author_name''').fetchall()
        s=['<div class="topbar"><div><h1>Szyfrowany sejf dokumentów</h1><p class="sub">Osobny, szyfrowany magazyn plików (AES-256-GCM). Nie zmienia istniejących dokumentów. Hasło nie jest zapisywane.</p></div></div>']
        s.append('<div class="card"><h2>Dodaj plik do sejfu</h2><form method="post" action="/vault/upload" enctype="multipart/form-data"><label>Sprawa</label>'+cases_select(cases)+'<label>Nazwa dokumentu</label><input name="title" maxlength="250"><label>Plik (do 16 MB)</label><input type="file" name="file" required><label>Hasło szyfrowania (minimum 12 znaków)</label><input type="password" name="passphrase" minlength="12" required autocomplete="new-password"><button class="btn primary">Zaszyfruj i zapisz</button></form></div>')
        s.append('<div class="card"><h2>Zapisane pliki</h2><table><thead><tr><th>Dokument</th><th>Sprawa</th><th>Dostęp</th><th>Otwieranie</th></tr></thead><tbody>')
        for x in files:
            if u['role']=='admin' or x['owner_id']==u['id']:
                grants='<form method="post" action="/vault/%d/grant"><label>Udostępnij użytkownikowi</label><select name="user_id">%s</select><button class="btn small">Nadaj dostęp</button></form>'%(x['id'],''.join('<option value="%s">%s</option>'%(p['id'],esc(p['author_name'])) for p in people))
                grants+=''.join('<form method="post" action="/vault/%d/revoke" onsubmit="return confirm(\'Cofnąć dostęp do pliku?\')"><input type="hidden" name="user_id" value="%s"><button class="btn small">Cofnij dostęp: %s</button></form>'%(x['id'],g['user_id'],esc(g['author_name'])) for g in active_grants if g['file_id']==x['id'])
            else:grants='<span class="small">Udostępniony</span>'
            form='<form method="post" action="/vault/%d/download"><input type="password" name="passphrase" placeholder="Hasło pliku" required><button class="btn small">Odszyfruj i pobierz</button></form>'%x['id']
            if u['role']=='admin' or x['owner_id']==u['id']:
                form+=('<details><summary>Zmień hasło / Usuń dokument</summary>'
                       '<form method="post" action="/vault/%d/rotate"><input type="password" name="old_passphrase" placeholder="Dotychczasowe hasło" required><input type="password" name="new_passphrase" placeholder="Nowe hasło (min. 12 znaków)" minlength="12" required><button class="btn small">Zmień hasło</button></form>'
                       '<form method="post" action="/vault/%d/delete"><label>Aby usunąć, wpisz USUŃ</label><input name="confirmation" required><button class="btn small danger">Usuń plik</button></form></details>')%(x['id'],x['id'])
            s.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(esc(x['title']),esc(x['case_title']),grants,form))
        s.append('</tbody></table></div><p class="small">Uwaga: utrata hasła uniemożliwi odszyfrowanie pliku. Samo nadanie dostępu nie ujawnia hasła. Sejf chroni zawartość, ale tytuł dokumentu i powiązanie ze sprawą pozostają w bazie danych.</p>')
        self._dev3_html('Sejf dokumentów',''.join(s),'vault')

    def dev3_vault_upload(self,f,files):
        a=self._dev3_app();u=self._dev3_me()
        uploaded=files.get('file')
        if not uploaded or not uploaded[1]:raise ValueError('Wybierz plik')
        with a.db() as con:vault_store(con,a.FILES_DIR,int(f.get('case_id') or 0),u['id'],uploaded[0],uploaded[1],f.get('passphrase',''),f.get('title',''))
        self.redirect('/vault')

    def dev3_vault_grant(self,file_id,f):
        a=self._dev3_app();u=self._dev3_me();target=int(f.get('user_id') or 0)
        with a.db() as con:
            row=con.execute('SELECT owner_id FROM dev3_vault_files WHERE id=?',(file_id,)).fetchone()
            if not row:return self.send_error(404)
            if u['role']!='admin' and row['owner_id']!=u['id']:return self._dev3_error('Brak uprawnień',403)
            if not con.execute('SELECT 1 FROM users WHERE id=? AND is_active=1',(target,)).fetchone():raise ValueError('Nieznany użytkownik')
            con.execute('INSERT OR IGNORE INTO dev3_vault_grants(file_id,user_id) VALUES(?,?)',(file_id,target))
            audit_if_available(con,None,u['id'],'Dostęp do sejfu nadany',f'Plik {file_id}, użytkownik {target}')
        self.redirect('/vault')

    def dev3_vault_revoke(self,file_id,f):
        a=self._dev3_app();u=self._dev3_me()
        try:target=int(f.get('user_id') or 0)
        except (TypeError,ValueError):raise ValueError('Nieprawidłowy użytkownik')
        with a.db() as con:
            row=con.execute('SELECT owner_id FROM dev3_vault_files WHERE id=?',(file_id,)).fetchone()
            if not row:return self.send_error(404)
            if u['role']!='admin' and row['owner_id']!=u['id']:
                return self._dev3_error('Brak uprawnień',403)
            if target==row['owner_id']:raise ValueError('Nie można usunąć dostępu właściciela')
            con.execute('DELETE FROM dev3_vault_grants WHERE file_id=? AND user_id=?',(file_id,target))
            audit_if_available(con,None,u['id'],'Dostęp do sejfu cofnięty',f'Plik {file_id}, użytkownik {target}')
        self.redirect('/vault')

    def dev3_vault_download(self,file_id,f):
        a=self._dev3_app();u=self._dev3_me()
        with a.db() as con:
            if not vault_can_view(con,file_id,u['id'],u['role']=='admin'):
                return self._dev3_error('Brak uprawnień do pliku',403)
            row=con.execute('SELECT * FROM dev3_vault_files WHERE id=?',(file_id,)).fetchone()
        if not row:return self.send_error(404)
        if not re.fullmatch(r'[0-9a-f]{32}\.rkv',row['stored_name']):
            raise ValueError('Nieprawidłowy identyfikator magazynu')
        path=a.FILES_DIR/'_vault'/row['stored_name']
        try:data=decrypt_vault(path.read_bytes(),f.get('passphrase',''))
        except OSError:raise ValueError('Plik sejfu nie istnieje')
        import hashlib
        if hashlib.sha256(data).hexdigest()!=row['digest_sha256']:
            raise ValueError('Weryfikacja integralności dokumentu nie powiodła się')
        # Force download, never render untrusted documents as HTML in the origin.
        name=Path(row['original_name'].replace('\\','/')).name.replace('"','_').replace('\r','').replace('\n','')
        safe_name=name.encode('ascii','ignore').decode() or 'dokument'
        disposition='attachment; filename="%s"; filename*=UTF-8\'\'%s'%(safe_name,quote(name,safe=''))
        self.send_response(200);self.send_header('Content-Type','application/octet-stream')
        self.send_header('Content-Disposition',disposition)
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

    def dev3_court_page(self):
        if not self._dev3_admin():return
        a=self._dev3_app()
        with a.db() as con:
            rows=con.execute('SELECT * FROM dev3_portal_items ORDER BY id DESC LIMIT 150').fetchall()
            cases=con.execute('SELECT id,signature,title FROM cases ORDER BY title LIMIT 1000').fetchall()
        portal_url=os.environ.get('RK_COURT_PORTAL_URL','https://portal.wroclaw.sa.gov.pl/#/login').strip()
        from urllib.parse import urlsplit
        parsed=urlsplit(portal_url)
        if parsed.scheme!='https' or not re.fullmatch(r'portal\.[a-z0-9-]+\.sa\.gov\.pl',parsed.hostname or '') or parsed.username or parsed.password:
            portal_url='https://portal.wroclaw.sa.gov.pl/#/login'
        s=['<div class="topbar"><div><h1>Portal Informacyjny — import do weryfikacji</h1><p class="sub">Obsługa ręcznie wyeksportowanych danych; automatyczne API wymaga autoryzacji i oficjalnej specyfikacji.</p></div><a class="btn" href="%s" target="_blank" rel="noopener noreferrer">Otwórz Portal</a></div>'%esc(portal_url)]
        s.append('<div class="card"><h2>Import listy CSV (UTF-8)</h2><p>Kolumny: <code>identyfikator;sygnatura;data;tytul;opis</code>. Import nie odbiera doręczeń ani nie tworzy terminów procesowych.</p><form method="post" action="/court-portal/import" enctype="multipart/form-data"><input type="file" name="file" accept=".csv" required><button class="btn primary">Zaimportuj do kontroli</button></form></div>')
        s.append('<div class="card"><h2>Informacje oczekujące na ocenę</h2>')
        for r in rows:
            s.append('<div class="dev3-item"><b>%s</b> · %s · %s<p>%s</p>'%(esc(r['signature']),esc(r['event_date']),esc(r['document_title']),esc(r['details'])))
            s.append('<form method="post" action="/court-portal/%d/review"><label>%s</label>%s<button class="btn small">%s</button></form>'%(r['id'],'Zmień przypisanie' if r['reviewed'] else 'Przypisz do sprawy',cases_select(cases,selected=r['case_id']),'Zapisz przypisanie' if r['reviewed'] else 'Zatwierdź kontrolę'))
            if r['reviewed']:
                s.append('<form method="post" action="/court-portal/%d/review"><input type="hidden" name="action" value="undo"><button class="btn small">Cofnij weryfikację</button></form>'%r['id'])
            s.append('</div>')
        s.append('</div>')
        self._dev3_html('Portal Informacyjny — import',''.join(s),'court-portal')

    def dev3_court_import(self,files):
        if not self._dev3_admin():return
        a=self._dev3_app();u=self._dev3_me();upload=files.get('file')
        if not upload or not upload[1]:raise ValueError('Brak pliku CSV')
        with a.db() as con:added,dup=import_portal_csv(con,upload[1],u['id'])
        self.redirect('/court-portal')

    def dev3_court_review(self,row_id,f):
        if not self._dev3_admin():return
        a=self._dev3_app();undo=f.get('action')=='undo'
        cid=0 if undo else int(f.get('case_id') or 0)
        if not undo and not cid:raise ValueError('Wybierz sprawę przed zatwierdzeniem')
        with a.db() as con:
            if not con.execute('SELECT 1 FROM dev3_portal_items WHERE id=?',(row_id,)).fetchone():
                return self.send_error(404)
            if cid and not con.execute('SELECT 1 FROM cases WHERE id=?',(cid,)).fetchone():raise ValueError('Nieznana sprawa')
            con.execute('UPDATE dev3_portal_items SET reviewed=?,case_id=? WHERE id=?',(0 if undo else 1,cid or None,row_id))
            audit_if_available(con,cid or None,self._dev3_me()['id'],'Weryfikacja importu sądowego',f'Wpis {row_id}; cofnięcie {undo}')
        self.redirect('/court-portal')

    def dev3_calendar_page(self):
        if not self._dev3_admin():return
        a=self._dev3_app()
        with a.db() as con:
            cases=con.execute('SELECT id,signature,title FROM cases ORDER BY title LIMIT 1000').fetchall()
            pending=con.execute("SELECT * FROM dev3_calendar_pending WHERE status='pending' ORDER BY id DESC LIMIT 80").fetchall()
            terms=con.execute('''SELECT a.id,a.title,a.appointment_date,c.title case_title FROM case_appointments a JOIN cases c ON c.id=a.case_id ORDER BY CASE WHEN a.appointment_date >= date('now','localtime') THEN 0 ELSE 1 END, CASE WHEN a.appointment_date >= date('now','localtime') THEN a.appointment_date END ASC, a.appointment_date DESC, a.appointment_time ASC LIMIT 120''').fetchall()
        s=['<div class="topbar"><div><h1>Kalendarze Google i Outlook</h1><p class="sub">Wymiana danych po świadomym uruchomieniu; wydarzenia przychodzące wymagają przypisania do sprawy.</p></div></div>']
        for provider,envname in [('google','RK_GOOGLE_REFRESH_TOKEN'),('outlook','RK_MS_REFRESH_TOKEN')]:
            ready=bool(os.environ.get(envname) and os.environ.get('RK_GOOGLE_CLIENT_ID' if provider=='google' else 'RK_MS_CLIENT_ID'))
            s.append('<div class="card"><h2>%s — %s</h2><form method="post" action="/calendar-sync/pull"><input type="hidden" name="provider" value="%s"><button class="btn" %s>Pobierz wydarzenia do weryfikacji</button></form></div>'%(provider.title(),'konfiguracja dostępna' if ready else 'brak autoryzacji OAuth',provider,'' if ready else 'disabled'))
        s.append('<div class="card"><h2>Opublikuj wybrany termin</h2><form method="post" action="/calendar-sync/publish"><label>Dostawca</label><select name="provider"><option value="google">Google</option><option value="outlook">Outlook</option></select><label>Czas wydarzenia (minuty)</label><input type="number" name="duration" value="60" min="1" max="1440" required><label>Termin</label><select name="appointment_id">')
        s.extend('<option value="%d">%s · %s · %s</option>'%(t['id'],esc(t['appointment_date']),esc(t['case_title']),esc(t['title'])) for t in terms)
        s.append('</select><label><input type="checkbox" name="share_title" value="1"> Udostępnij pełny tytuł w zewnętrznym kalendarzu (potencjalne dane poufne)</label><button class="btn primary">Wyślij wybrany termin</button></form></div>')
        s.append('<div class="card"><h2>Oczekujące wydarzenia z kalendarzy</h2>')
        for r in pending:
            s.append('<div class="dev3-item"><b>%s</b> · %s (%s)<form method="post" action="/calendar-sync/accept"><input type="hidden" name="pending_id" value="%d"><label>Przypisz do sprawy</label>%s<button class="btn small">Zatwierdź i utwórz termin</button></form><form method="post" action="/calendar-sync/dismiss"><input type="hidden" name="pending_id" value="%d"><button class="btn small danger">Odrzuć propozycję</button></form></div>'%(esc(r['title']),esc(r['start_at']),esc(r['provider']),r['id'],cases_select(cases),r['id']))
        s.append('</div><p class="small">Integracja wymaga własnej konfiguracji OAuth. Brak połączenia nie wstrzymuje lokalnego kalendarza. Nie są automatycznie wyliczane terminy procesowe ani odbierane doręczenia.</p>')
        with a.db() as con:
            changes=con.execute("SELECT * FROM dev5_calendar_changes WHERE status='pending' ORDER BY id DESC LIMIT 100").fetchall()
        s.append('<div class="card"><h2>Zmiany z kalendarzy wymagające decyzji</h2>')
        for ch in changes:
            s.append('<div class="dev3-item"><b>%s</b> · %s · %s — %s%s<form method="post" action="/calendar-sync/review"><input type="hidden" name="change_id" value="%s"><button name="decision" value="accept" class="btn small">Zatwierdź zmianę w RK</button><button name="decision" value="dismiss" class="btn small">Odrzuć zmianę</button></form></div>' % (
                esc(ch['provider']),esc(ch['title']),esc(ch['start_at']),esc(ch['end_at']),
                ' · ANULOWANO ZEWNĘTRZNIE' if ch['cancelled'] else ' · BRAK W ZAKRESIE — sprawdź ręcznie' if ch['missing'] else '',int(ch['id'])))
        if not changes:s.append('<p>Brak zewnętrznych zmian wymagających kontroli.</p>')
        s.append('</div>')
        self._dev3_html('Integracje kalendarza',''.join(s),'calendar-sync')

    def dev3_calendar_pull(self,f):
        if not self._dev3_admin():return
        provider=f.get('provider','')
        a=self._dev3_app();token=access_token(provider)
        with a.db() as con:pull_proposals(con,provider,token)
        self.redirect('/calendar-sync')

    def dev3_calendar_publish(self,f):
        if not self._dev3_admin():return
        provider=f.get('provider','')
        a=self._dev3_app();token=access_token(provider)
        try:duration=int(f.get('duration') or 60)
        except (TypeError,ValueError):raise ValueError('Nieprawidłowy czas wydarzenia')
        with a.db() as con:publish_appointment(con,provider,int(f.get('appointment_id') or 0),token,bool(f.get('share_title')),duration)
        self.redirect('/calendar-sync')

    def dev3_calendar_dismiss(self,f):
        if not self._dev3_admin():return
        a=self._dev3_app()
        with a.db() as con:
            changed=con.execute("UPDATE dev3_calendar_pending SET status='dismissed' WHERE id=? AND status='pending'",
                                (int(f.get('pending_id') or 0),)).rowcount
            if not changed:raise ValueError('Nie znaleziono oczekującej propozycji')
        self.redirect('/calendar-sync')

    def dev3_calendar_accept(self,f):
        if not self._dev3_admin():return
        a=self._dev3_app();u=self._dev3_me()
        with a.db() as con:accept_proposal(con,int(f.get('pending_id') or 0),int(f.get('case_id') or 0),u['id'])
        self.redirect('/calendar-sync')

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
