# -*- coding: utf-8 -*-
"""RK KANCELARIA UX6: concurrent case phases, editable calendar and saved choices.

All mutations use the authenticated application's existing CSRF and SQLite
transaction boundary; no client files are read or copied by this module.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date
from html import escape

KINDS = {'phase', 'alert_type', 'task_type', 'doc_type', 'event_type', 'appointment_kind'}
DEFAULT_PHASES = ('Postępowanie przedsądowe', 'Postępowanie sądowe', 'Postępowanie odwoławcze',
                  'Egzekucja', 'Mediacja', 'Negocjacje', 'Czynności zabezpieczające', 'Inny etap')


def ensure_ux6_schema(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS ux6_case_phases(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
        label TEXT NOT NULL CHECK(length(label) BETWEEN 1 AND 100),
        state TEXT NOT NULL DEFAULT 'active' CHECK(state IN ('active','done')),
        description TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS ux6_phase_case ON ux6_case_phases(case_id,state);
    CREATE TABLE IF NOT EXISTS ux6_custom_choices(
        kind TEXT NOT NULL, value TEXT NOT NULL COLLATE NOCASE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(kind,value)
    );
    ''')


def checked_name(raw, maximum=100):
    v=' '.join(str(raw or '').split()).strip()
    if not v or len(v)>maximum or any(ord(c)<32 for c in v):
        raise ValueError(f'Wpisz od 1 do {maximum} znaków (bez znaków sterujących).')
    return v


def save_choice(con, kind, raw):
    if kind not in KINDS: raise ValueError('Nieznana lista wyboru.')
    name=checked_name(raw)
    con.execute('INSERT OR IGNORE INTO ux6_custom_choices(kind,value) VALUES(?,?)', (kind,name))
    return name


def choice_exists(db_factory, kind, value):
    if kind not in KINDS or not value or len(str(value))>100:return False
    try:
        with db_factory() as con:
            return con.execute('SELECT 1 FROM ux6_custom_choices WHERE kind=? AND value=?',
                               (kind,value)).fetchone() is not None
    except (sqlite3.Error,OSError):return False


def delete_case_dependencies(con, case_id):
    """Remove only direct *case-owned* non-cascading rows. Preserve audit history.

    A constraint that cannot be resolved safely is reported, not bypassed via
    PRAGMA foreign_keys=OFF. Caller has already created a verified full snapshot.
    """
    whitelisted = ('case_', 'user_case_', 'dev3_', 'dev4_', 'dev5_', 'ux6_')
    extra = {'document_case_links','alerts','tasks','documents','events',
             'process_events','parties','side_case_dependencies'}
    tables=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for table in tables:
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',table):continue
        if table=='cases':continue
        fks=list(con.execute(f'PRAGMA foreign_key_list("{table}")'))
        for fk in fks:
            if str(fk[2])!='cases' or str(fk[6]).upper() not in ('NO ACTION','RESTRICT'):continue
            col=str(fk[3])
            if col not in ('case_id','source_case_id','target_case_id','parent_case_id','child_case_id'):
                continue
            if not (table.startswith(whitelisted) or table in extra) or 'audit' in table.lower():
                # Deleting a shared or historic record without review is unsafe.
                continue
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',col):continue
            con.execute(f'DELETE FROM "{table}" WHERE "{col}"=?',(case_id,))
    con.execute('DELETE FROM cases WHERE id=?',(case_id,))
    remaining=con.execute('SELECT 1 FROM cases WHERE id=?',(case_id,)).fetchone()
    if remaining: raise ValueError('Sprawa nadal znajduje się w bazie — transakcja cofnięta.')


class Ux6Mixin:
    def ux6_app(self):return self._dev3_app()

    def ux6_page(self, title, body, status=200):
        a=self.ux6_app()
        return self.send_html(a.layout(title,body,'calendar' if 'Kalendarz' in title else 'stages'),status)

    def ux6_case(self, con, cid, *, write=False):
        user=self.ux6_app().current_request_user()
        if not user:return None
        # These legacy endpoints are limited to administrators until scoped
        # permissions for granular phase management are implemented.
        if user['role']!='admin':return None
        row=con.execute('SELECT id,title,status FROM cases WHERE id=?',(cid,)).fetchone()
        if not row:return None
        if write and self.ux6_app().case_read_only(con,cid):return None
        return row

    def ux6_get(self,path,qs):
        if path=='/ux6/choices':self.ux6_choice_list((qs.get('kind') or [''])[0]);return True
        mm=re.fullmatch(r'/case/(\d+)/phases',path)
        if mm:self.ux6_phases(int(mm[1]));return True
        if path=='/calendar/day':self.ux6_calendar_day((qs.get('date') or [''])[0]);return True
        mm=re.fullmatch(r'/calendar/alert/(\d+)/edit',path)
        if mm:self.ux6_alert_edit(int(mm[1]));return True
        return False

    def ux6_post(self,path,fields,files):
        if path=='/ux6/choice':self.ux6_choice_add(fields);return True
        mm=re.fullmatch(r'/case/(\d+)/phases/(add|toggle|delete)',path)
        if mm:self.ux6_phase_mutate(int(mm[1]),mm[2],fields);return True
        mm=re.fullmatch(r'/calendar/alert/(\d+)/update',path)
        if mm:self.ux6_alert_update(int(mm[1]),fields);return True
        return False

    def ux6_choice_list(self,kind):
        if kind not in KINDS:return self.send_error(400)
        import json
        a=self.ux6_app()
        with a.db() as con:
            choices=[r[0] for r in con.execute(
                'SELECT value FROM ux6_custom_choices WHERE kind=? ORDER BY value COLLATE NOCASE',(kind,))]
        raw=json.dumps({'choices':choices},ensure_ascii=False).encode('utf-8')
        self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store')
        self.end_headers();self.wfile.write(raw)

    def ux6_choice_add(self,f):
        a=self.ux6_app();u=a.current_request_user()
        if not u or u['role']!='admin':return self.send_error(403)
        try:
            with a.db() as con:value=save_choice(con,f.get('kind'),f.get('value'))
        except ValueError as exc:
            return self.ux6_page('Błąd wyboru',f'<div class="card"><p>{escape(str(exc))}</p></div>',400)
        # Return a tiny predictable JSON response for the authenticated JS form.
        import json
        raw=json.dumps({'ok':True,'value':value},ensure_ascii=False).encode('utf-8')
        self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store')
        self.end_headers();self.wfile.write(raw)

    def ux6_phases(self,cid):
        a=self.ux6_app()
        with a.db() as con:
            c=self.ux6_case(con,cid)
            if not c:return self.send_error(404)
            phases=con.execute('SELECT * FROM ux6_case_phases WHERE case_id=? ORDER BY state,id DESC',(cid,)).fetchall()
            custom=con.execute("SELECT value FROM ux6_custom_choices WHERE kind='phase' ORDER BY value COLLATE NOCASE").fetchall()
        opts=''.join(f'<option value="{escape(v,quote=True)}">' for v in dict.fromkeys([*DEFAULT_PHASES,*(r['value'] for r in custom)]))
        rows=[]
        for r in phases:
            active=r['state']=='active';toggle='Zakończ' if active else 'Wznów';mark='W toku' if active else 'Zakończony'
            rows.append(f'''<article class="ux6-phase-row"><div><b>{escape(r['label'])}</b>
                <span class="ux6-phase-status">{mark}</span><p>{escape(r['description'] or 'Bez uwag')}</p>
                <small>Dodano {escape(r['created_at'])}</small></div>
                <div class="ux6-phase-actions"><form method="post" action="/case/{cid}/phases/toggle">
                <input type="hidden" name="phase_id" value="{r['id']}"><button class="btn">{toggle}</button></form>
                <form method="post" action="/case/{cid}/phases/delete" onsubmit="return confirm('Usunąć ten etap z historii?')">
                <input type="hidden" name="phase_id" value="{r['id']}"><button class="btn danger">Usuń</button></form></div></article>''')
        form=f'''<form method="post" action="/case/{cid}/phases/add" class="form-grid">
            <div class="full"><label>Etap równoległy</label><input name="phase" list="ux6-phase-options" maxlength="100" required
            placeholder="Np. postępowanie sądowe albo mediacja"><datalist id="ux6-phase-options">{opts}</datalist></div>
            <div class="full"><label>Opis (opcjonalny)</label><textarea name="description" maxlength="2000" placeholder="Np. mediacja równolegle z postępowaniem sądowym"></textarea></div>
            <div class="full"><button class="btn primary">Dodaj równoległy etap</button></div></form>'''
        body=(f'''<div class="topbar"><div><h1>Etapy prowadzenia sprawy</h1><div class="sub">{escape(c['title'])}</div></div>
            <div><a class="btn" href="/case/{cid}/stage">Etap główny</a>
            <a class="btn" href="/case/{cid}">Powrót do sprawy</a></div></div>
            <div class="notice"><b>Kilka etapów jednocześnie:</b> możesz prowadzić proces sądowy, mediację i negocjacje równolegle.
            Etap główny pozostaje zachowany w dotychczasowym systemie.</div>
            <section class="card"><h2>Aktywne i zakończone etapy</h2>{''.join(rows) or '<p>Brak dodatkowych etapów.</p>'}</section>
            <section class="card"><h2>Dodaj etap</h2>{form}</section>''')
        self.ux6_page('Etapy sprawy',body)

    def ux6_phase_mutate(self,cid,action,f):
        a=self.ux6_app();user=a.current_request_user()
        with a.db() as con:
            c=self.ux6_case(con,cid,write=True)
            if not c:return self.send_error(403)
            if action=='add':
                try:
                    label=checked_name(f.get('phase'))
                    notes=str(f.get('description') or '').strip()[:2000]
                    save_choice(con,'phase',label)
                except ValueError as exc:
                    return self.ux6_page('Nieprawidłowy etap',f'<div class="card">{escape(str(exc))}</div>',400)
                # Avoid accidental duplicate active phases.
                old=con.execute('SELECT 1 FROM ux6_case_phases WHERE case_id=? AND label=? COLLATE NOCASE AND state=?',
                                (cid,label,'active')).fetchone()
                if old:return self.redirect(f'/case/{cid}/phases')
                con.execute('INSERT INTO ux6_case_phases(case_id,label,description,created_by) VALUES(?,?,?,?)',
                            (cid,label,notes,user['author_name']))
            else:
                try:phase_id=int(f.get('phase_id') or 0)
                except ValueError:return self.send_error(400)
                row=con.execute('SELECT id,state FROM ux6_case_phases WHERE id=? AND case_id=?',(phase_id,cid)).fetchone()
                if not row:return self.send_error(404)
                if action=='toggle':
                    con.execute('UPDATE ux6_case_phases SET state=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                                ('done' if row['state']=='active' else 'active',phase_id))
                else:con.execute('DELETE FROM ux6_case_phases WHERE id=? AND case_id=?',(phase_id,cid))
        return self.redirect(f'/case/{cid}/phases')

    def ux6_calendar_day(self,raw):
        a=self.ux6_app()
        if a.current_request_user()['role']!='admin':return self.send_error(403)
        try: d=date.fromisoformat(raw).isoformat()
        except (TypeError,ValueError):return self.send_error(400,'Nieprawidłowa data.')
        def link(href,label,title,subtitle=''):
            return f'<div class="ux6-day-item"><div><b>{escape(label)}</b> · {escape(title)}<p>{escape(subtitle)}</p></div><a class="btn" href="{escape(href,quote=True)}">Edytuj</a></div>'
        with a.db() as con:
            alerts=con.execute('''SELECT a.*,c.title case_title FROM alerts a LEFT JOIN cases c ON c.id=a.case_id
                   WHERE a.alert_date=? AND a.status='open' ORDER BY a.id''',(d,)).fetchall()
            tasks=con.execute('''SELECT t.*,c.title case_title FROM tasks t JOIN cases c ON c.id=t.case_id
                   WHERE t.due_date=? AND t.status<>'done' ORDER BY t.id''',(d,)).fetchall()
            appts=con.execute('''SELECT p.*,c.title case_title FROM case_appointments p JOIN cases c ON c.id=p.case_id
                   WHERE p.appointment_date=? AND p.status='planned' ORDER BY p.appointment_time,p.id''',(d,)).fetchall()
            events=con.execute('''SELECT e.*,c.title case_title FROM events e JOIN cases c ON c.id=e.case_id
                   WHERE e.event_date=? ORDER BY e.id''',(d,)).fetchall()
            processes=con.execute('''SELECT p.*,c.title case_title FROM process_events p JOIN cases c ON c.id=p.case_id
                   WHERE p.event_date=? OR p.next_date=? ORDER BY p.id''',(d,d)).fetchall()
        rows=[];linked=set()
        for r in alerts:
            if r['source_type']=='task' and r['source_id']:
                href=f'/task/{r["source_id"]}/edit';linked.add(int(r['source_id']))
            else:href=f'/calendar/alert/{r["id"]}/edit'
            rows.append(link(href,'Alert / termin',r['title'],r['case_title'] or 'Bez sprawy'))
        for r in tasks:
            if r['id'] not in linked:rows.append(link(f'/task/{r["id"]}/edit','Zadanie',r['title'],r['case_title']))
        for r in appts:rows.append(link(f'/appointment/{r["id"]}','Spotkanie / termin',r['title'],
                                      f'{r["appointment_time"]} · {r["case_title"]}'))
        for r in events:rows.append(link(f'/event/{r["id"]}/edit','Zdarzenie',r['title'],r['case_title']))
        for r in processes:rows.append(link(f'/process-event/{r["id"]}/edit','Historia / proces',r['title'],r['case_title']))
        body=(f'<div class="topbar"><div><h1>Kalendarz: {escape(d)}</h1>'
              '<div class="sub">Edytuj termin lub zadanie bez wyszukiwania go w sprawie.</div></div>'
              f'<a class="btn" href="/calendar?month={d[:7]}">← Wróć do miesiąca</a></div>'
              f'<div class="card"><h2>Wpisy dnia</h2>{"".join(rows) or "<p>Brak wpisów na ten dzień.</p>"}</div>'
              '<div class="notice">Terminy procesowe muszą zostać zweryfikowane przez użytkownika; zmiana daty nie stanowi automatycznej oceny biegu terminu.</div>')
        self.ux6_page('Kalendarz — edycja dnia',body)

    def ux6_alert_edit(self,aid):
        a=self.ux6_app()
        with a.db() as con:
            r=con.execute('SELECT * FROM alerts WHERE id=?',(aid,)).fetchone()
        if not r:return self.send_error(404)
        if r['source_type']=='task' and r['source_id']:
            return self.redirect(f'/task/{r["source_id"]}/edit')
        if a.current_request_user()['role']!='admin':return self.send_error(403)
        html=f'''<div class="topbar"><h1>Edytuj wpis kalendarza</h1>
        <a class="btn" href="/calendar/day?date={escape(r['alert_date'])}">Wróć do dnia</a></div>
        <div class="card"><form method="post" action="/calendar/alert/{aid}/update" class="form-grid">
        <div class="full"><label>Nazwa</label><input name="title" required maxlength="250" value="{escape(r['title'],quote=True)}"></div>
        <div><label>Data</label><input name="alert_date" type="date" required value="{escape(r['alert_date'],quote=True)}"></div>
        <div><label>Rodzaj</label><input name="alert_type" maxlength="100" value="{escape(r['alert_type'],quote=True)}" required></div>
        <div><label>Priorytet</label><select name="priority">{''.join(f'<option value="{x}" {"selected" if r["priority"]==x else ""}>{label}</option>' for x,label in [('normal','Normalny'),('high','Wysoki'),('critical','Krytyczny')])}</select></div>
        <div class="full"><label>Opis</label><textarea name="description" maxlength="4000">{escape(r['description'] or '')}</textarea></div>
        <div class="full"><button class="btn primary">Zapisz termin</button></div></form></div>'''
        self.ux6_page('Kalendarz — edycja wpisu',html)

    def ux6_alert_update(self,aid,f):
        a=self.ux6_app()
        if a.current_request_user()['role']!='admin':return self.send_error(403)
        try:
            title=checked_name(f.get('title'),250)
            d=date.fromisoformat(str(f.get('alert_date') or '')).isoformat()
            typ=checked_name(f.get('alert_type'))
            priority=str(f.get('priority') or 'normal')
            if priority not in ('normal','high','critical'):raise ValueError('Nieprawidłowy priorytet.')
        except (ValueError,TypeError) as exc:
            return self.ux6_page('Błąd daty',f'<div class="card">{escape(str(exc))}</div>',400)
        with a.db() as con:
            r=con.execute('SELECT * FROM alerts WHERE id=?',(aid,)).fetchone()
            if not r:return self.send_error(404)
            if r['source_type']=='task' and r['source_id']:
                return self.redirect(f'/task/{r["source_id"]}/edit')
            if r['case_id'] and a.case_read_only(con,int(r['case_id'])):return self.send_error(403)
            con.execute('UPDATE alerts SET title=?,alert_date=?,alert_type=?,priority=?,description=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                        (title,d,typ,priority,str(f.get('description') or '')[:4000],aid))
            save_choice(con,'alert_type',typ)
        return self.redirect('/calendar/day?date='+d)
