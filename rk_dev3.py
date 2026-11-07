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
        if path=='/worktime': self.dev3_worktime_page();return True
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
            '/worktime/add':lambda:self.dev3_time_add(fields),
            '/vault/upload':lambda:self.dev3_vault_upload(fields,files),
            '/court-portal/import':lambda:self.dev3_court_import(files),
            '/calendar-sync/pull':lambda:self.dev3_calendar_pull(fields),
            '/calendar-sync/publish':lambda:self.dev3_calendar_publish(fields),
            '/calendar-sync/accept':lambda:self.dev3_calendar_accept(fields),
        }
        if re.fullmatch(r'/case/\d+/stage',path):fn=lambda:self.dev3_case_stage_save(int(path.split('/')[2]),fields)
        elif re.fullmatch(r'/worktime/\d+/delete',path):fn=lambda:self.dev3_time_delete(int(path.split('/')[2]))
        elif re.fullmatch(r'/vault/\d+/download',path):fn=lambda:self.dev3_vault_download(int(path.split('/')[2]),fields)
        elif re.fullmatch(r'/vault/\d+/grant',path):fn=lambda:self.dev3_vault_grant(int(path.split('/')[2]),fields)
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
        self._dev3_html('Etap postępowania',body+'</div>','stages')

    def dev3_case_stage_save(self,case_id,f):
        a=self._dev3_app();u=self._dev3_me()
        with a.db() as con:
            if a.case_read_only(con,case_id):
                raise ValueError('Sprawa jest zablokowana. Administrator musi ją najpierw odblokować.')
            set_stage(con,case_id,f.get('stage',''),u['id'],f.get('note',''))
        self.redirect('/case/%d/stage'%case_id)

    def dev3_worktime_page(self):
        a=self._dev3_app();u=self._dev3_me()
        with a.db() as con:
            cases=con.execute('SELECT id,signature,title FROM cases ORDER BY status="closed",title LIMIT 1000').fetchall()
            running=con.execute('''SELECT t.*,c.title case_title FROM dev3_time_running t JOIN cases c ON c.id=t.case_id WHERE user_id=?''',(u['id'],)).fetchone()
            filter_sql='' if u['role']=='admin' else 'WHERE t.user_id=?'
            entries=con.execute('''SELECT t.*,c.title case_title,c.signature,u.author_name
                FROM dev3_time_entries t JOIN cases c ON c.id=t.case_id LEFT JOIN users u ON u.id=t.user_id
                '''+filter_sql+' ORDER BY t.activity_date DESC,t.id DESC LIMIT 120',() if u['role']=='admin' else (u['id'],)).fetchall()
        body=['<div class="topbar"><div><h1>Ewidencja czasu pracy</h1><div class="sub">Stoper, ręczne wpisy i raport rozliczeń. Czas rejestrowany jest przy konkretnej sprawie.</div></div><a class="btn" href="/worktime/export">Eksport CSV</a></div>']
        if running:
            body.append('<div class="card"><h2>Stoper jest uruchomiony</h2><p><b>%s</b> · od %s UTC</p><form method="post" action="/worktime/stop"><label>Stawka PLN za godzinę</label><input type="number" name="rate" step="0.01" min="0" value="0"><label><input type="checkbox" name="billable" value="1" checked> Rozliczalne</label><button class="btn primary">Zatrzymaj i zapisz</button></form></div>'%(esc(running['case_title']),esc(running['started_at'])))
        else:
            body.append('<div class="card"><h2>Rozpocznij pomiar czasu</h2><form method="post" action="/worktime/start">'+cases_select(cases)+'<label>Opis czynności</label><input name="description" maxlength="1000" placeholder="np. analiza pozwu"><button class="btn primary">Uruchom stoper</button></form></div>')
        body.append('<div class="card"><h2>Dodaj czas ręcznie</h2><form method="post" action="/worktime/add" class="form-grid"><div><label>Sprawa</label>'+cases_select(cases)+'</div><div><label>Data</label><input type="date" name="day" value="%s" required></div><div><label>Minuty</label><input type="number" name="minutes" min="1" max="1440" value="60" required></div><div><label>Stawka PLN/h</label><input type="number" name="rate" step="0.01" min="0" value="0"></div><div class="full"><label>Opis</label><input name="description" maxlength="2000"></div><div class="full"><label><input type="checkbox" name="billable" checked value="1"> Rozliczalne</label></div><button class="btn primary">Zapisz czas</button></form></div>'%date.today().isoformat())
        body.append('<div class="card"><h2>Ostatnie wpisy</h2><table><thead><tr><th>Data</th><th>Sprawa</th><th>Pracownik</th><th>Minuty</th><th>Kwota</th><th></th></tr></thead><tbody>')
        for x in entries:
            total=(x['minutes']*x['rate_grosze']//60/100) if x['billable'] else 0
            delete='<form method="post" action="/worktime/%d/delete" onsubmit="return confirm(\'Usunąć wpis?\')"><button class="btn small danger">Usuń</button></form>'%x['id'] if (u['role']=='admin' or x['user_id']==u['id']) else ''
            body.append('<tr><td>%s</td><td>%s<br><span class="small">%s</span></td><td>%s</td><td>%s</td><td>%.2f PLN</td><td>%s</td></tr>'%(esc(x['activity_date']),esc(x['case_title']),esc(x['description']),esc(x['author_name']),x['minutes'],total,delete))
        body.append('</tbody></table></div>')
        self._dev3_html('Czas pracy',''.join(body),'worktime')

    def dev3_start(self,f):
        a=self._dev3_app();u=self._dev3_me()
        with a.db() as con:start_timer(con,u['id'],int(f.get('case_id') or 0),f.get('description',''))
        self.redirect('/worktime')

    def dev3_stop(self,f):
        a=self._dev3_app();u=self._dev3_me()
        with a.db() as con:stop_timer(con,u['id'],rate_grosze(f.get('rate') or '0'),bool(f.get('billable')))
        self.redirect('/worktime')

    def dev3_time_add(self,f):
        a=self._dev3_app();u=self._dev3_me()
        with a.db() as con:add_manual_time(con,int(f.get('case_id') or 0),u['id'],f.get('day',''),int(f.get('minutes') or 0),f.get('description',''),rate_grosze(f.get('rate') or '0'),bool(f.get('billable')))
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
        s=['<div class="topbar"><div><h1>Szyfrowany sejf dokumentów</h1><p class="sub">Osobny, szyfrowany magazyn plików (AES-256-GCM). Nie zmienia istniejących dokumentów. Hasło nie jest zapisywane.</p></div></div>']
        s.append('<div class="card"><h2>Dodaj plik do sejfu</h2><form method="post" action="/vault/upload" enctype="multipart/form-data"><label>Sprawa</label>'+cases_select(cases)+'<label>Nazwa dokumentu</label><input name="title" maxlength="250"><label>Plik (do 16 MB)</label><input type="file" name="file" required><label>Hasło szyfrowania (minimum 12 znaków)</label><input type="password" name="passphrase" minlength="12" required autocomplete="new-password"><button class="btn primary">Zaszyfruj i zapisz</button></form></div>')
        s.append('<div class="card"><h2>Zapisane pliki</h2><table><thead><tr><th>Dokument</th><th>Sprawa</th><th>Dostęp</th><th>Otwieranie</th></tr></thead><tbody>')
        for x in files:
            if u['role']=='admin' or x['owner_id']==u['id']:
                grants='<form method="post" action="/vault/%d/grant"><label>Udostępnij użytkownikowi</label><select name="user_id">%s</select><button class="btn small">Nadaj dostęp</button></form>'%(x['id'],''.join('<option value="%s">%s</option>'%(p['id'],esc(p['author_name'])) for p in people))
            else:grants='<span class="small">Udostępniony</span>'
            form='<form method="post" action="/vault/%d/download"><input type="password" name="passphrase" placeholder="Hasło pliku" required><button class="btn small">Odszyfruj i pobierz</button></form>'%x['id']
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
        s=['<div class="topbar"><div><h1>Portal Informacyjny — import do weryfikacji</h1><p class="sub">Obsługa ręcznie wyeksportowanych danych; automatyczne API wymaga autoryzacji i oficjalnej specyfikacji.</p></div><a class="btn" href="https://portal.wroclaw.sa.gov.pl" target="_blank" rel="noopener noreferrer">Otwórz Portal</a></div>']
        s.append('<div class="card"><h2>Import listy CSV (UTF-8)</h2><p>Kolumny: <code>identyfikator;sygnatura;data;tytul;opis</code>. Import nie odbiera doręczeń ani nie tworzy terminów procesowych.</p><form method="post" action="/court-portal/import" enctype="multipart/form-data"><input type="file" name="file" accept=".csv" required><button class="btn primary">Zaimportuj do kontroli</button></form></div>')
        s.append('<div class="card"><h2>Informacje oczekujące na ocenę</h2>')
        for r in rows:
            s.append('<div class="dev3-item"><b>%s</b> · %s · %s<p>%s</p>'%(esc(r['signature']),esc(r['event_date']),esc(r['document_title']),esc(r['details'])))
            if not r['reviewed']:
                s.append('<form method="post" action="/court-portal/%d/review"><label>Przypisz do sprawy</label>%s<button class="btn small">Zatwierdź kontrolę</button></form>'%(r['id'],cases_select(cases)))
            else:s.append('<p class="small">Zweryfikowano</p>')
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
        a=self._dev3_app();cid=int(f.get('case_id') or 0)
        with a.db() as con:
            if cid and not con.execute('SELECT 1 FROM cases WHERE id=?',(cid,)).fetchone():raise ValueError('Nieznana sprawa')
            con.execute('UPDATE dev3_portal_items SET reviewed=1,case_id=? WHERE id=?',(cid or None,row_id))
        self.redirect('/court-portal')

    def dev3_calendar_page(self):
        if not self._dev3_admin():return
        a=self._dev3_app()
        with a.db() as con:
            cases=con.execute('SELECT id,signature,title FROM cases ORDER BY title LIMIT 1000').fetchall()
            pending=con.execute("SELECT * FROM dev3_calendar_pending WHERE status='pending' ORDER BY id DESC LIMIT 80").fetchall()
            terms=con.execute('''SELECT a.id,a.title,a.appointment_date,c.title case_title FROM case_appointments a JOIN cases c ON c.id=a.case_id ORDER BY a.appointment_date DESC LIMIT 120''').fetchall()
        s=['<div class="topbar"><div><h1>Kalendarze Google i Outlook</h1><p class="sub">Wymiana danych po świadomym uruchomieniu; wydarzenia przychodzące wymagają przypisania do sprawy.</p></div></div>']
        for provider,envname in [('google','RK_GOOGLE_REFRESH_TOKEN'),('outlook','RK_MS_REFRESH_TOKEN')]:
            ready=bool(os.environ.get(envname) and os.environ.get('RK_GOOGLE_CLIENT_ID' if provider=='google' else 'RK_MS_CLIENT_ID'))
            s.append('<div class="card"><h2>%s — %s</h2><form method="post" action="/calendar-sync/pull"><input type="hidden" name="provider" value="%s"><button class="btn" %s>Pobierz wydarzenia do weryfikacji</button></form></div>'%(provider.title(),'konfiguracja dostępna' if ready else 'brak autoryzacji OAuth',provider,'' if ready else 'disabled'))
        s.append('<div class="card"><h2>Opublikuj wybrany termin</h2><form method="post" action="/calendar-sync/publish"><label>Dostawca</label><select name="provider"><option value="google">Google</option><option value="outlook">Outlook</option></select><label>Termin</label><select name="appointment_id">')
        s.extend('<option value="%d">%s · %s · %s</option>'%(t['id'],esc(t['appointment_date']),esc(t['case_title']),esc(t['title'])) for t in terms)
        s.append('</select><label><input type="checkbox" name="share_title" value="1"> Udostępnij pełny tytuł w zewnętrznym kalendarzu (potencjalne dane poufne)</label><button class="btn primary">Wyślij wybrany termin</button></form></div>')
        s.append('<div class="card"><h2>Oczekujące wydarzenia z kalendarzy</h2>')
        for r in pending:
            s.append('<div class="dev3-item"><b>%s</b> · %s (%s)<form method="post" action="/calendar-sync/accept"><input type="hidden" name="pending_id" value="%d"><label>Przypisz do sprawy</label>%s<button class="btn small">Zatwierdź i utwórz termin</button></form></div>'%(esc(r['title']),esc(r['start_at']),esc(r['provider']),r['id'],cases_select(cases)))
        s.append('</div><p class="small">Integracja wymaga własnej konfiguracji OAuth. Brak połączenia nie wstrzymuje lokalnego kalendarza. Nie są automatycznie wyliczane terminy procesowe ani odbierane doręczenia.</p>')
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
        with a.db() as con:publish_appointment(con,provider,int(f.get('appointment_id') or 0),token,bool(f.get('share_title')))
        self.redirect('/calendar-sync')

    def dev3_calendar_accept(self,f):
        if not self._dev3_admin():return
        a=self._dev3_app();u=self._dev3_me()
        with a.db() as con:accept_proposal(con,int(f.get('pending_id') or 0),int(f.get('case_id') or 0),u['id'])
        self.redirect('/calendar-sync')
