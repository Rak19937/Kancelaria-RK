# -*- coding: utf-8 -*-
"""RK KANCELARIA dev5: deny-by-default case and document access.

Legacy screens may join data from many cases. Non-admins therefore use a
case-scoped workspace; unrestricted legacy routes are intentionally disabled.
Do NOT replace this gate with navigation-only restrictions.
"""
from __future__ import annotations
import html
import re
from pathlib import Path
from urllib.parse import quote


def esc(value):
    return html.escape(str('' if value is None else value), quote=True)


def ensure_dev5_acl_schema(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS dev5_case_grants (
        case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        permission TEXT NOT NULL CHECK(permission IN ('read','edit')),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(case_id,user_id)
    );
    CREATE INDEX IF NOT EXISTS idx_dev5_grants_user ON dev5_case_grants(user_id,case_id);
    ''')


def can_access_case(con, user_id:int, case_id:int, permission:str='read') -> bool:
    """Active administrator or explicit grant/lead. Unassigned cases stay private."""
    if permission not in ('read','edit'):raise ValueError('Nieznane uprawnienie')
    u=con.execute('SELECT role,is_active FROM users WHERE id=?',(int(user_id),)).fetchone()
    if not u or not u['is_active']:return False
    if not con.execute('SELECT 1 FROM cases WHERE id=?',(int(case_id),)).fetchone():return False
    if u['role']=='admin':return True
    # Existing case lead is a valid case assignment, without a retroactive grant.
    lead=con.execute('SELECT lead_user_id FROM cases WHERE id=?',(int(case_id),)).fetchone()[0]
    if lead is not None and int(lead)==int(user_id):return True
    grant=con.execute('SELECT permission FROM dev5_case_grants WHERE case_id=? AND user_id=?',
                      (int(case_id),int(user_id))).fetchone()
    return bool(grant and (permission=='read' or grant[0]=='edit'))


def case_scoped_document(con, user_id:int, case_id:int, document_id:int):
    if not can_access_case(con,user_id,case_id):return None
    return con.execute('SELECT * FROM documents WHERE id=? AND case_id=?',
                       (int(document_id),int(case_id))).fetchone()


def grant_case(con, actor_id:int, case_id:int, target_id:int, permission:str):
    if permission not in ('read','edit'):raise ValueError('Niepoprawny zakres dostępu')
    if not can_access_case(con,actor_id,case_id,'edit'):
        raise PermissionError('Brak praw do nadawania dostępu')
    actor=con.execute('SELECT role FROM users WHERE id=?',(actor_id,)).fetchone()
    if not actor or actor['role']!='admin':raise PermissionError('Uprawnienia może nadawać tylko administrator')
    target=con.execute('SELECT role,is_active FROM users WHERE id=?',(target_id,)).fetchone()
    if not target or not target['is_active'] or target['role']!='user':
        raise ValueError('Wybierz aktywnego użytkownika (nie administratora)')
    con.execute('''INSERT INTO dev5_case_grants(case_id,user_id,permission) VALUES(?,?,?)
        ON CONFLICT(case_id,user_id) DO UPDATE SET permission=excluded.permission''',
        (case_id,target_id,permission))


def revoke_case(con, actor_id:int, case_id:int, target_id:int):
    actor=con.execute('SELECT role,is_active FROM users WHERE id=?',(actor_id,)).fetchone()
    if not actor or not actor['is_active'] or actor['role']!='admin':
        raise PermissionError('Tylko administrator może odebrać dostęp')
    if not con.execute('SELECT 1 FROM cases WHERE id=?',(case_id,)).fetchone():
        raise ValueError('Nie znaleziono sprawy')
    return con.execute('DELETE FROM dev5_case_grants WHERE case_id=? AND user_id=?',
                       (case_id,target_id)).rowcount


def secure_page(title, body):
    # No legacy global sidebar, cross-case widgets, or content-derived quick links.
    return '''<!doctype html><html lang="pl"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <meta name="referrer" content="same-origin"><title>%s – RK KANCELARIA</title>
    <link rel="icon" href="/assets/rk_kancelaria.ico"><style>
    *{box-sizing:border-box}body{font:15px system-ui,Segoe UI,sans-serif;margin:0;background:#f3f6f4;color:#1b302b}
    header{background:#093b32;color:white;padding:18px max(20px,calc((100vw - 1000px)/2))}
    header a{color:white}main{max-width:1000px;padding:20px;margin:auto}
    a{color:#12634b}nav{display:flex;gap:18px;flex-wrap:wrap}header nav a{color:white}
    h1{font-size:1.7rem}h2{font-size:1.2rem}.card{background:white;padding:18px;border:1px solid #d5e0db;border-radius:12px;margin:14px 0}
    .item{padding:11px 2px;border-bottom:1px solid #e4ebe7}.small{color:#57746c;font-size:13px}
    input,textarea,select{padding:9px;border:1px solid #afc6be;border-radius:6px;max-width:100%%}
    button,.btn{display:inline-block;padding:8px 14px;background:#10644e;color:white;text-decoration:none;border:0;border-radius:7px;cursor:pointer}
    button.danger{background:#9b302b}label{display:block;margin:12px 0 5px}
    </style></head><body><header><nav><strong>RK KANCELARIA</strong><a href="/my-cases">Moje sprawy</a><a href="/account">Moje konto</a>
    <form method="post" action="/logout"><button>Wyloguj</button></form></nav></header>
    <main><h1>%s</h1>%s</main></body></html>''' % (esc(title), esc(title), body)


class Dev5AccessMixin:
    """HTTP gate; call immediately after require_auth() and CSRF validation."""

    def _rk5(self):return self._dev3_app()
    def _rk5_user(self):return self._dev3_me()

    def _rk5_send(self,title,body,code=200):
        page=secure_page(title,body)
        # Keep the existing desktop tab-presence mechanism alive; otherwise
        # auto-shutdown could close the application while this view is open.
        presence=getattr(self._rk5(),'client_presence_script',lambda:'' )()
        if presence:page=page.replace('</body>','<script>'+presence+'</script></body>',1)
        return self.send_html(page,code)

    def _rk5_forbidden(self):
        return self._rk5_send('Brak dostępu',
          '<div class="card">Ten ekran nie jest dostępny w trybie ograniczonego dostępu. '
          'Skorzystaj z przydzielonych spraw lub skontaktuj się z administratorem.</div>',403)

    def dev5_access_get(self,path,qs):
        user=self._rk5_user()
        admin=user['role']=='admin'
        manage=re.fullmatch(r'/case/(\d+)/access',path)
        if manage and admin:
            self.dev5_access_admin(int(manage[1]));return True
        if admin:return False
        if path=='/':self.redirect('/my-cases');return True
        if path=='/account':self.dev5_access_account();return True
        if path=='/my-cases':self.dev5_access_cases();return True
        detail=re.fullmatch(r'/my-cases/(\d+)',path)
        if detail:self.dev5_access_case(int(detail[1]));return True
        file=re.fullmatch(r'/my-cases/(\d+)/documents/(\d+)/(file|preview)',path)
        if file:self.dev5_access_document(int(file[1]),int(file[2]),file[3]);return True
        pdf=re.fullmatch(r'/my-cases/(\d+)/documents/(\d+)/page/(\d+)',path)
        if pdf:self.dev5_access_pdf_page(int(pdf[1]),int(pdf[2]),int(pdf[3]));return True
        self._rk5_forbidden();return True

    def dev5_access_post(self,path,fields,files):
        user=self._rk5_user()
        admin=user['role']=='admin'
        change=re.fullmatch(r'/case/(\d+)/access/(grant|revoke)',path)
        if admin and change:
            self.dev5_access_admin_change(int(change[1]),change[2],fields);return True
        if admin:return False
        if path=='/logout':return False
        if path=='/account/update':self.dev5_access_account_update(fields);return True
        if path=='/account/password':self.dev5_access_account_password(fields);return True
        note=re.fullmatch(r'/my-cases/(\d+)/note',path)
        if note:self.dev5_access_note(int(note[1]),fields);return True
        task=re.fullmatch(r'/my-cases/(\d+)/tasks/(\d+)/toggle',path)
        if task:self.dev5_access_task(int(task[1]),int(task[2]));return True
        self._rk5_forbidden();return True

    def dev5_access_admin(self,cid):
        app=self._rk5()
        with app.db() as con:
            c=con.execute('SELECT id,title,signature,lead_user_id FROM cases WHERE id=?',(cid,)).fetchone()
            users=con.execute("SELECT id,author_name,role FROM users WHERE is_active=1 ORDER BY author_name").fetchall()
            grants=con.execute('''SELECT g.user_id,g.permission,u.author_name
                FROM dev5_case_grants g JOIN users u ON u.id=g.user_id
                WHERE g.case_id=? ORDER BY u.author_name''',(cid,)).fetchall()
        if c is None:return self.send_error(404)
        options=''.join(f'<option value="{x["id"]}">{esc(x["author_name"])}</option>' for x in users if x['role']=='user')
        entries=''.join(f'<div class="item">{esc(x["author_name"])} — {"Edycja" if x["permission"]=="edit" else "Odczyt"}'
          f'<form method="post" action="/case/{cid}/access/revoke"><input type="hidden" name="user_id" value="{x["user_id"]}"><button class="danger">Odbierz dostęp</button></form></div>' for x in grants)
        body=f'''<div class="card"><p>Sprawa: <strong>{esc(c['signature'])} · {esc(c['title'])}</strong></p>
        <p>Prowadzący sprawę automatycznie ma dostęp do odczytu i edycji. Administratorzy mają dostęp do wszystkich spraw.</p>
        <form method="post" action="/case/{cid}/access/grant">
        <label>Użytkownik</label><select name="user_id" required>{options}</select>
        <label>Zakres</label><select name="permission"><option value="read">Tylko odczyt</option><option value="edit">Odczyt i ograniczona edycja (notatki, zadania)</option></select>
        <button>Nadaj dostęp</button></form></div><div class="card"><h2>Przydzielone osoby</h2>{entries or '<p>Brak dodatkowych przydziałów.</p>'}</div>
        <a class="btn" href="/case/{cid}">Wróć do sprawy</a>'''
        self._rk5_send('Dostęp do sprawy',body)

    def dev5_access_admin_change(self,cid,kind,fields):
        app=self._rk5();user=self._rk5_user()
        try:uid=int(fields.get('user_id') or 0)
        except (TypeError,ValueError):return self._rk5_send('Nieprawidłowy formularz','Błędny użytkownik',400)
        try:
            with app.db() as con:
                if kind=='grant':grant_case(con,user['id'],cid,uid,fields.get('permission',''))
                else:revoke_case(con,user['id'],cid,uid)
                from rk_dev4_core import action_log
                action_log(con,cid,user['id'],'Zmiana dostępu do sprawy',f'{kind}: konto {uid}')
        except (ValueError,PermissionError) as exc:
            return self._rk5_send('Nie udało się zmienić dostępu',esc(exc),400)
        self.redirect(f'/case/{cid}/access')

    def dev5_access_cases(self):
        app=self._rk5();user=self._rk5_user()
        with app.db() as con:
            rows=con.execute('''SELECT c.id,c.signature,c.title,c.next_date,c.status
            FROM cases c WHERE c.lead_user_id=? OR EXISTS (
              SELECT 1 FROM dev5_case_grants g WHERE g.case_id=c.id AND g.user_id=?)
            ORDER BY c.status='closed',c.next_date='',c.next_date,c.id DESC LIMIT 500''',
            (user['id'],user['id'])).fetchall()
        body='<div class="card"><p class="small">Widzisz tylko sprawy przypisane przez administratora albo takie, w których jesteś prowadzącym.</p>'
        for r in rows:
            body+=f'<div class="item"><a href="/my-cases/{r["id"]}"><strong>{esc(r["signature"])} — {esc(r["title"])}</strong></a> <span class="small">{esc(r["next_date"])}</span></div>'
        body+=('</div>' if rows else '<p>Nie przydzielono Ci jeszcze spraw.</p></div>')
        self._rk5_send('Moje sprawy',body)

    def _rk5_check_case(self,con,cid,write=False):
        return can_access_case(con,self._rk5_user()['id'],cid,'edit' if write else 'read')

    def dev5_access_case(self,cid):
        app=self._rk5()
        with app.db() as con:
            if not self._rk5_check_case(con,cid):return self.send_error(404)
            c=con.execute('SELECT id,signature,title,subject,client,court,status,next_date,next_step FROM cases WHERE id=?',(cid,)).fetchone()
            docs=con.execute('''SELECT id,title,doc_date,original_name,stored_name FROM documents WHERE case_id=?
                ORDER BY COALESCE(NULLIF(doc_date,''),created_at) DESC,id DESC LIMIT 300''',(cid,)).fetchall()
            tasks=con.execute('''SELECT id,title,due_date,status FROM tasks WHERE case_id=?
                ORDER BY CASE WHEN status='open' THEN 0 ELSE 1 END,due_date,id LIMIT 150''',(cid,)).fetchall()
            terms=con.execute('''SELECT title,appointment_date,appointment_time FROM case_appointments WHERE case_id=?
                ORDER BY appointment_date ASC,appointment_time ASC LIMIT 100''',(cid,)).fetchall()
            notes=con.execute('''SELECT note,author,created_at FROM case_notes WHERE case_id=?
                ORDER BY id DESC LIMIT 50''',(cid,)).fetchall()
            can_edit=self._rk5_check_case(con,cid,write=True)
        body=f'<div class="card"><p><b>Klient:</b> {esc(c["client"])} · <b>Sąd:</b> {esc(c["court"])} · <b>Status:</b> {esc(c["status"])}</p><p>{esc(c["subject"])}</p><p><b>Następna czynność:</b> {esc(c["next_step"])} · {esc(c["next_date"])}</p></div>'
        body+='<div class="card"><h2>Dokumenty</h2>'
        for x in docs:
            if x['stored_name']:
                links=f' <a href="/my-cases/{cid}/documents/{x["id"]}/preview">Podgląd</a> · <a href="/my-cases/{cid}/documents/{x["id"]}/file?download=1">Pobierz</a>'
            else:links=' (bez pliku)'
            body+=f'<div class="item">{esc(x["doc_date"])} · {esc(x["title"])}{links}</div>'
        body+='</div><div class="card"><h2>Zadania</h2>'
        for x in tasks:
            toggle=(f'<form method="post" action="/my-cases/{cid}/tasks/{x["id"]}/toggle"><button>{"Wznów" if x["status"]!="open" else "Zakończ"}</button></form>' if can_edit else '')
            body+=f'<div class="item">{esc(x["due_date"])} · {esc(x["title"])} · {esc(x["status"])} {toggle}</div>'
        body+='</div><div class="card"><h2>Terminy</h2>'
        for x in terms:body+=f'<div class="item">{esc(x["appointment_date"])} {esc(x["appointment_time"])} · {esc(x["title"])}</div>'
        body+='</div><div class="card"><h2>Notatki</h2>'
        for x in notes:body+=f'<div class="item">{esc(x["created_at"])} · {esc(x["author"])}: {esc(x["note"])}</div>'
        if can_edit:body+=f'''<form method="post" action="/my-cases/{cid}/note"><label>Dodaj notatkę</label><textarea name="note" required maxlength="4000"></textarea><button>Dodaj</button></form>'''
        body+='</div>'
        self._rk5_send(f'Sprawa {c["signature"]} — {c["title"]}',body)

    def dev5_access_document(self,cid,did,view):
        app=self._rk5()
        with app.db() as con:
            d=case_scoped_document(con,self._rk5_user()['id'],cid,did)
        if not d:return self.send_error(404)
        state,path,reason=app.document_state(d)
        if state!='ok' or not path:return self.send_error(404)
        filename=d['original_name'] or path.name
        if view=='file':return app.serve_local_file(self,path,filename,download=False)
        url=f'/my-cases/{cid}/documents/{did}/file'
        preview=app.render_preview(path,filename,url,pdf_pages_base=f'/my-cases/{cid}/documents/{did}/page')
        self._rk5_send(esc(d['title']),preview)

    def dev5_access_pdf_page(self,cid,did,page):
        app=self._rk5()
        with app.db() as con:d=case_scoped_document(con,self._rk5_user()['id'],cid,did)
        if not d:return self.send_error(404)
        state,path,_=app.document_state(d)
        if state!='ok' or path.suffix.lower()!='.pdf':return self.send_error(404)
        return app.serve_pdf_page(self,path,page)

    def dev5_access_note(self,cid,f):
        app=self._rk5();user=self._rk5_user()
        note=(f.get('note','') or '').strip()
        if not 1<=len(note)<=4000:return self._rk5_send('Błąd','Treść notatki: 1–4000 znaków',400)
        with app.db() as con:
            if not self._rk5_check_case(con,cid,write=True):return self.send_error(404)
            con.execute('INSERT INTO case_notes(case_id,note,author) VALUES(?,?,?)',(cid,note,user['author_name']))
        self.redirect(f'/my-cases/{cid}')

    def dev5_access_task(self,cid,tid):
        app=self._rk5()
        with app.db() as con:
            if not self._rk5_check_case(con,cid,write=True):return self.send_error(404)
            row=con.execute('SELECT status FROM tasks WHERE id=? AND case_id=?',(tid,cid)).fetchone()
            if not row:return self.send_error(404)
            con.execute('UPDATE tasks SET status=? WHERE id=? AND case_id=?',
                        ('done' if row['status']=='open' else 'open',tid,cid))
        self.redirect(f'/my-cases/{cid}')

    def dev5_access_account(self,message=''):
        app=self._rk5();user=self._rk5_user()
        note=f'<div class="card">{esc(message)}</div>' if message else ''
        body=f'''{note}<div class="card"><form method="post" action="/account/update">
        <label>Login</label><input name="username" value="{esc(user['username'])}" required>
        <label>Autor wpisów</label><input name="author_name" value="{esc(user['author_name'])}" required>
        <label>Funkcja</label><input name="function" value="{esc(user['function'])}">
        <button>Zapisz konto</button></form></div>
        <div class="card"><h2>Zmień hasło</h2><form method="post" action="/account/password">
        <label>Obecne</label><input name="current_password" type="password" required>
        <label>Nowe</label><input name="new_password" type="password" minlength="8" required>
        <label>Powtórz</label><input name="new_password2" type="password" minlength="8" required>
        <button>Zmień hasło</button></form></div>'''
        self._rk5_send('Moje konto',body)

    def dev5_access_account_update(self,f):
        app=self._rk5();user=self._rk5_user()
        username=app.normalize_username(f.get('username','') or '')
        author=(f.get('author_name','') or '').strip()[:120]
        fun=(f.get('function','') or '').strip()[:120]
        if not app.valid_username(username) or not author:
            return self.dev5_access_account('Niepoprawny login lub autor.')
        try:
            with app.db() as con:
                con.execute('UPDATE users SET username=?,author_name=?,function=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                            (username,author,fun,user['id']))
        except Exception:
            return self.dev5_access_account('Nie udało się zapisać danych. Sprawdź, czy login nie jest zajęty.')
        self.redirect('/my-cases')

    def dev5_access_account_password(self,f):
        app=self._rk5();user=self._rk5_user()
        if not app.verify_password(f.get('current_password',''),user['password_hash'],user['password_salt']):
            return self.dev5_access_account('Niepoprawne obecne hasło.')
        new=f.get('new_password','') or ''
        if len(new)<8 or new!=f.get('new_password2',''):
            return self.dev5_access_account('Nowe hasło musi mieć co najmniej 8 znaków i zgadzać się w obu polach.')
        hashed,salt=app.password_hash(new)
        with app.db() as con:
            con.execute('UPDATE users SET password_hash=?,password_salt=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                        (hashed,salt,user['id']))
            con.execute('DELETE FROM user_sessions WHERE user_id=?',(user['id'],))
        self.redirect('/login')
