# -*- coding: utf-8 -*-
"""RK KANCELARIA 0.3.7-dev1: terminarz, zespoły, sprawy zależne i nawigacja.
Bez usług sieciowych; żadnych automatycznych decyzji procesowych.
"""
from __future__ import annotations
import calendar
import html
import re
import sqlite3
import sys
from datetime import date, timedelta
from urllib.parse import quote


def esc(x):
    return html.escape(str(x if x is not None else ''), quote=True)


def _app(obj):
    return sys.modules[type(obj).__module__]


def date_iso(value, required=True):
    value = str(value or '').strip()
    if not value and not required:
        return ''
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError('Podaj poprawną datę w formacie RRRR-MM-DD.')
    if value != parsed.isoformat():
        raise ValueError('Data musi być w formacie RRRR-MM-DD.')
    return value


def time_hm(value):
    value = str(value or '').strip()
    if not value:
        return ''
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value):
        raise ValueError('Godzina musi mieć format GG:MM.')
    return value


def ensure_workspace_plus_schema(con: sqlite3.Connection):
    """Idempotentna migracja: nie zmienia istniejących terminów ani spraw."""
    con.executescript('''
    CREATE TABLE IF NOT EXISTS case_appointments (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
      title TEXT NOT NULL,
      appointment_date TEXT NOT NULL,
      appointment_time TEXT NOT NULL DEFAULT '',
      kind TEXT NOT NULL DEFAULT 'Termin ustalony',
      location TEXT NOT NULL DEFAULT '',
      notes TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'planned' CHECK(status IN ('planned','done','cancelled')),
      created_by TEXT NOT NULL DEFAULT '',
      updated_by TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_appointments_case_date ON case_appointments(case_id,appointment_date);
    CREATE INDEX IF NOT EXISTS idx_appointments_date ON case_appointments(appointment_date);
    CREATE TABLE IF NOT EXISTS appointment_assignees (
      appointment_id INTEGER NOT NULL REFERENCES case_appointments(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      PRIMARY KEY(appointment_id,user_id)
    );
    CREATE INDEX IF NOT EXISTS idx_appointment_assignees_user ON appointment_assignees(user_id,appointment_id);
    CREATE TABLE IF NOT EXISTS task_assignees (
      task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      PRIMARY KEY(task_id,user_id)
    );
    CREATE INDEX IF NOT EXISTS idx_task_assignees_user ON task_assignees(user_id,task_id);
    CREATE TABLE IF NOT EXISTS side_case_dependencies (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      parent_case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
      child_case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
      needed_item TEXT NOT NULL,
      note TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'waiting' CHECK(status IN ('waiting','received','not_needed')),
      document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
      created_by TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(parent_case_id,child_case_id),
      CHECK(parent_case_id<>child_case_id)
    );
    CREATE INDEX IF NOT EXISTS idx_side_child ON side_case_dependencies(child_case_id);
    CREATE TABLE IF NOT EXISTS deleted_appointments(
       id INTEGER PRIMARY KEY,
       payload_json TEXT NOT NULL,
       deleted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
       deleted_by TEXT NOT NULL DEFAULT ''
    );
    ''')
    # Zachowujemy dotychczasowe pojedyncze przypisania. Nigdy nie nadpisujemy
    # później ręcznej listy osób na podstawie przestarzałego pola legacy.
    con.execute('''INSERT OR IGNORE INTO task_assignees(task_id,user_id)
                   SELECT t.id,t.assigned_user_id FROM tasks t
                   JOIN users u ON u.id=t.assigned_user_id WHERE t.assigned_user_id IS NOT NULL
                   AND NOT EXISTS(SELECT 1 FROM task_assignees a WHERE a.task_id=t.id)''')


def selected_ids(fields, con, prefix='assign_user_'):
    """Formularz zawiera osobne klucze checkboxów (read_post nie zachowuje tablic)."""
    ids = []
    for key, value in fields.items():
        if not key.startswith(prefix) or str(value) not in ('1', 'on', 'yes'):
            continue
        raw = key[len(prefix):]
        if raw.isascii() and raw.isdigit():
            ids.append(int(raw))
    ids = sorted(set(ids))
    if ids:
        q = ','.join('?' for _ in ids)
        valid = {x[0] for x in con.execute(f'SELECT id FROM users WHERE is_active=1 AND id IN ({q})', ids)}
        if valid != set(ids):
            raise ValueError('Wskazano nieaktywnego lub nieistniejącego użytkownika.')
    return ids


def set_task_assignees(con, task_id, ids):
    row=con.execute('SELECT case_id FROM tasks WHERE id=?',(task_id,)).fetchone()
    if not row:
        raise ValueError('Nie znaleziono zadania.')
    ids=sorted(set(int(x) for x in ids))
    con.execute('DELETE FROM task_assignees WHERE task_id=?',(task_id,))
    con.executemany('INSERT INTO task_assignees(task_id,user_id) VALUES(?,?)',[(task_id,i) for i in ids])
    con.execute('UPDATE tasks SET assigned_user_id=? WHERE id=?',(ids[0] if ids else None,task_id))


def assignee_html(con, entity, entity_id=0, selected=None):
    users=con.execute('SELECT id,author_name,function FROM users WHERE is_active=1 ORDER BY author_name').fetchall()
    if selected is None:
        selected=set()
        if entity=='task' and entity_id:
            selected={x[0] for x in con.execute('SELECT user_id FROM task_assignees WHERE task_id=?',(entity_id,))}
            if not selected:
                x=con.execute('SELECT assigned_user_id FROM tasks WHERE id=?',(entity_id,)).fetchone()
                if x and x[0]:selected={x[0]}
        if entity=='appointment' and entity_id:
            selected={x[0] for x in con.execute('SELECT user_id FROM appointment_assignees WHERE appointment_id=?',(entity_id,))}
    return ('<div class="full"><label>Przypisani użytkownicy (można wybrać kilka)</label>'
            '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:7px">'+
            ''.join(f'<label style="font-size:13px;display:inline-flex;align-items:center;gap:5px">'
                    f'<input type="checkbox" style="width:auto" name="assign_user_{u["id"]}" value="1" '
                    f'{"checked" if u["id"] in selected else ""}> {esc(u["author_name"])}</label>' for u in users)+
            '</div></div>')


def task_assignees_map(con, task_ids):
    ids=sorted({int(x) for x in task_ids})
    if not ids:return {}
    placeholders=','.join('?' for _ in ids)
    rows=con.execute(f'''SELECT ta.task_id, GROUP_CONCAT(u.author_name, ', ') display
            FROM task_assignees ta JOIN users u ON u.id=ta.user_id
            WHERE ta.task_id IN ({placeholders}) GROUP BY ta.task_id''',ids).fetchall()
    return {r['task_id']:r['display'] for r in rows}


def nav_strip(title=''):
    return ("<nav aria-label='Szybka nawigacja' style='margin:0 0 12px;display:flex;gap:8px;flex-wrap:wrap;align-items:center'>"
            "<a class='btn small' href='/'>⌂ Pulpit</a>"
            "<a class='btn small' href='/my-calendar'>▦ Mój kalendarz</a>"
            "<a class='btn small' href='/cases'>§ Sprawy</a>"
            "<a class='btn small' href='/tasks'>✓ Zadania</a>"
            "<a class='btn small' href='/today'>◷ Dzisiaj</a>"
            f"<span class='small muted'> / {esc(title)}</span></nav>")


def appointments_table(con, case_id):
    rows=con.execute('''SELECT a.*, GROUP_CONCAT(u.author_name, ', ') users
                        FROM case_appointments a
                        LEFT JOIN appointment_assignees au ON au.appointment_id=a.id
                        LEFT JOIN users u ON u.id=au.user_id
                        WHERE a.case_id=? GROUP BY a.id ORDER BY a.appointment_date,a.appointment_time,a.id''',(case_id,)).fetchall()
    return ''.join(
        f'<tr><td>{esc(r["appointment_date"])} {esc(r["appointment_time"])}</td>'
        f'<td><a class="case-link" href="/appointment/{r["id"]}"><b>{esc(r["title"])}</b></a>'
        f'<div class="small muted">{esc(r["users"] or "Bez przypisania")} · {esc(r["location"])}</div></td>'
        f'<td>{esc(r["status"])}</td><td><a class="btn small" href="/appointment/{r["id"]}">Otwórz</a></td></tr>' for r in rows)


def archived_appointments_html(con, cid):
    import json
    rows=con.execute('SELECT id,payload_json,deleted_at FROM deleted_appointments ORDER BY deleted_at DESC LIMIT 80').fetchall()
    parts=[]
    for r in rows:
        try:
            payload=json.loads(r['payload_json'])
            record=payload.get('record',payload)
            if int(record.get('case_id',0))!=int(cid):continue
            parts.append(f'<div><span>{esc(record.get("appointment_date",""))} · {esc(record.get("title",""))}</span> '
                         f'<form method="post" action="/appointment/{r["id"]}/restore" style="display:inline">'
                         '<button class="btn small">Przywróć termin</button></form></div>')
        except (ValueError,TypeError,KeyError):continue
    return ''.join(parts)


def linked_sidecases(con, cid):
    rows=con.execute('''SELECT d.*,c.title case_title,c.signature FROM side_case_dependencies d
                        JOIN cases c ON c.id=CASE WHEN d.parent_case_id=? THEN d.child_case_id ELSE d.parent_case_id END
                        WHERE d.parent_case_id=? OR d.child_case_id=? ORDER BY d.id DESC''',(cid,cid,cid)).fetchall()
    parts=[]
    for r in rows:
        other = r['child_case_id'] if r['parent_case_id']==cid else r['parent_case_id']
        typ='Sprawa poboczna' if r['parent_case_id']==cid else 'Sprawa główna'
        docs=con.execute('''SELECT id,title FROM documents WHERE case_id IN (?,?)
                ORDER BY id DESC LIMIT 150''',(r['parent_case_id'],r['child_case_id'])).fetchall()
        options='<option value="">— brak powiązanego dokumentu —</option>'+''.join(
            f'<option value="{d["id"]}" {"selected" if d["id"]==r["document_id"] else ""}>{esc(d["title"])}</option>' for d in docs)
        linked_doc=(f'<p class="small">Dokument: <a href="/document/{r["document_id"]}/open">Otwórz dokument źródłowy</a></p>'
                    if r['document_id'] else '<p class="small muted">Brak dokumentu potwierdzającego.</p>')
        action = (f'<form method="post" action="/sidecase/{r["id"]}/status" class="form-grid">'
                  f'<div><label>Postęp</label><select name="status"><option value="waiting" {"selected" if r["status"]=="waiting" else ""}>Oczekujemy</option>'
                  f'<option value="received" {"selected" if r["status"]=="received" else ""}>Uzyskano</option>'
                  f'<option value="not_needed" {"selected" if r["status"]=="not_needed" else ""}>Niepotrzebne</option></select></div>'
                  f'<div><label>Powiązany dokument</label><select name="document_id">{options}</select></div>'
                  '<div class="full"><button class="btn small">Zapisz postęp</button></div></form>') if r['parent_case_id']==cid else ''
        parts.append(f'<div class="card" style="margin-bottom:10px">'
                     f'<a class="case-link" href="/case/{other}"><b>{esc(typ)}: {esc(r["case_title"])}</b></a>'
                     f'<p class="small">Potrzebujemy: {esc(r["needed_item"])} · Status: {esc(r["status"])}</p>'
                     f'<p class="small muted">{esc(r["note"])}</p>{linked_doc}{action}</div>')
    return ''.join(parts) or '<div class="empty">Brak spraw pobocznych i zależności.</div>'


def upcoming_alerts_multi(con, user_id=None, days=14):
    """Zachowuje dotychczasowe monity, ale pokazuje alert zadania każdemu przypisanemu."""
    end=(date.today()+timedelta(days=days)).isoformat()
    if user_id:
        return con.execute('''SELECT a.*,c.title case_title,c.signature,c.internal_signature FROM alerts a
                 LEFT JOIN cases c ON c.id=a.case_id
                 WHERE a.status='open' AND a.alert_date<=?
                 AND (a.assigned_user_id IS NULL OR a.assigned_user_id=?
                      OR (a.source_type='task' AND EXISTS(
                           SELECT 1 FROM task_assignees ta
                           WHERE ta.task_id=a.source_id AND ta.user_id=?)))
                 ORDER BY a.alert_date,a.priority DESC,a.id''',(end,user_id,user_id)).fetchall()
    return con.execute('''SELECT a.*,c.title case_title,c.signature,c.internal_signature FROM alerts a
                 LEFT JOIN cases c ON c.id=a.case_id
                 WHERE a.status='open' AND a.alert_date<=?
                 ORDER BY a.alert_date,a.priority DESC,a.id''',(end,)).fetchall()


def personal_calendar_items(con, uid, first, last):
    """Elementy jawnie przypisane lub należące do spraw prowadzonych przez użytkownika.
    Nie ujawniaj w kalendarzu osobistym wszystkich spraw pozostałych użytkowników.
    """
    items=[]
    tasks=con.execute('''SELECT t.id,t.case_id,t.title,t.due_date,c.title case_title
        FROM tasks t JOIN cases c ON c.id=t.case_id
        WHERE t.status='open' AND t.due_date BETWEEN ? AND ?
        AND (EXISTS(SELECT 1 FROM task_assignees ta WHERE ta.task_id=t.id AND ta.user_id=?)
        OR (NOT EXISTS(SELECT 1 FROM task_assignees ta WHERE ta.task_id=t.id)
            AND (t.assigned_user_id=? OR (t.assigned_user_id IS NULL AND c.lead_user_id=?))))''',
        (first,last,uid,uid,uid)).fetchall()
    for r in tasks:items.append((r['due_date'],'Zadanie',r['title'],f'/task/{r["id"]}/edit',r['case_title']))
    appts=con.execute('''SELECT a.id,a.case_id,a.title,a.appointment_date,a.appointment_time,c.title case_title
       FROM case_appointments a JOIN cases c ON c.id=a.case_id
       WHERE a.status='planned' AND a.appointment_date BETWEEN ? AND ?
       AND (EXISTS(SELECT 1 FROM appointment_assignees au WHERE au.appointment_id=a.id AND au.user_id=?)
       OR (c.lead_user_id=? AND NOT EXISTS(SELECT 1 FROM appointment_assignees au WHERE au.appointment_id=a.id)))''',
       (first,last,uid,uid)).fetchall()
    for r in appts:items.append((r['appointment_date'],'Termin',r['title']+((' · '+r['appointment_time']) if r['appointment_time'] else ''),f'/appointment/{r["id"]}',r['case_title']))
    # Inne daty dla spraw, których użytkownik jest prowadzącym. Terminy bez przypisania
    # nie znikają z jego widoku, ale pochodzą wyłącznie z prowadzonych spraw.
    cases=con.execute('''SELECT id,title,next_date,next_step FROM cases
         WHERE lead_user_id=? AND next_date BETWEEN ? AND ? AND next_date != '' ''', (uid,first,last)).fetchall()
    for r in cases:items.append((r['next_date'],'Następny ruch',r['next_step'] or r['title'],f'/case/{r["id"]}?tab=deadlines',r['title']))
    events=con.execute('''SELECT e.id,e.event_date,e.title,c.title case_title
         FROM events e JOIN cases c ON c.id=e.case_id WHERE c.lead_user_id=? AND e.event_date BETWEEN ? AND ?''',
         (uid,first,last)).fetchall()
    for r in events:items.append((r['event_date'],'Zdarzenie',r['title'],f'/event/{r["id"]}/edit',r['case_title']))
    process=con.execute('''SELECT p.id,p.event_date,p.next_date,p.title,c.title case_title
         FROM process_events p JOIN cases c ON c.id=p.case_id
         WHERE c.lead_user_id=? AND (p.event_date BETWEEN ? AND ? OR p.next_date BETWEEN ? AND ?)''',
         (uid,first,last,first,last)).fetchall()
    for r in process:
        if r['event_date'] and first<=r['event_date']<=last:
            items.append((r['event_date'],'Proces',r['title'],f'/process-event/{r["id"]}/edit',r['case_title']))
        if r['next_date'] and first<=r['next_date']<=last and r['next_date']!=r['event_date']:
            items.append((r['next_date'],'Następny termin',r['title'],f'/process-event/{r["id"]}/edit',r['case_title']))
    alerts=con.execute('''SELECT al.id,al.case_id,al.alert_date,al.title,c.title case_title
         FROM alerts al LEFT JOIN cases c ON c.id=al.case_id
         WHERE al.status='open' AND al.alert_date BETWEEN ? AND ?
         AND COALESCE(al.source_type,'')<>'task'
         AND (al.assigned_user_id=? OR (al.assigned_user_id IS NULL AND c.lead_user_id=?))''',
         (first,last,uid,uid)).fetchall()
    for r in alerts:items.append((r['alert_date'],'Monit / alert',r['title'],f'/calendar?month={r["alert_date"][:7]}&case_id={r["case_id"] or 0}',r['case_title'] or 'Bez sprawy'))
    drafts=con.execute('''SELECT w.id,w.due_date,w.title,c.title case_title
         FROM writing_projects w JOIN cases c ON c.id=w.case_id
         WHERE c.lead_user_id=? AND w.due_date BETWEEN ? AND ? AND w.due_date<>''
           AND w.status NOT IN ('Złożony','Archiwalny')''',(uid,first,last)).fetchall()
    for r in drafts:items.append((r['due_date'],'Projekt pisma',r['title'],f'/draft/{r["id"]}',r['case_title']))
    pending=con.execute('''SELECT cr.id,cr.expected_reply_on,cr.subject,c.title case_title
         FROM correspondence_records cr JOIN cases c ON c.id=cr.case_id
         WHERE c.lead_user_id=? AND cr.response_expected=1
           AND cr.expected_reply_on BETWEEN ? AND ?
           AND cr.answered_on='' AND NOT EXISTS(SELECT 1 FROM correspondence_records r
                 WHERE r.reply_to_id=cr.id AND r.direction='incoming')''',
         (uid,first,last)).fetchall()
    for r in pending:items.append((r['expected_reply_on'],'Odpowiedź na pismo',r['subject'],f'/correspondence/{r["id"]}',r['case_title']))
    return sorted(items,key=lambda x:(x[0],x[1],x[2]))


class WorkspacePlusMixin:
    def _plus_fail(self,message,status=400,target='/cases'):
        a=_app(self)
        return self.send_html(a.layout('Nie wykonano operacji',f'<div class="card"><h2>Nie wykonano operacji</h2><p>{esc(message)}</p><a class="btn" href="{esc(target)}">Wróć</a></div>'),status)

    def appointment_save(self,fields,appointment_id=0):
        a=_app(self)
        try:
            cid=int(fields.get('case_id') or 0)
            title=str(fields.get('title') or '').strip()[:240]
            apdate=date_iso(fields.get('appointment_date'))
            aptime=time_hm(fields.get('appointment_time'))
            kind=str(fields.get('kind') or 'Termin ustalony').strip()[:80]
            location=str(fields.get('location') or '').strip()[:240]
            notes=str(fields.get('notes') or '').strip()[:2000]
            status=str(fields.get('status') or 'planned').strip()
            if not cid or not title:raise ValueError('Wybierz sprawę i wpisz nazwę terminu.')
            if status not in ('planned','done','cancelled'):raise ValueError('Nieprawidłowy status.')
            with a.db() as con:
                if not con.execute('SELECT 1 FROM cases WHERE id=?',(cid,)).fetchone():raise ValueError('Nie znaleziono sprawy.')
                ids=selected_ids(fields,con)
                author=self.current_author(fields)
                if appointment_id:
                    old=con.execute('SELECT * FROM case_appointments WHERE id=?',(appointment_id,)).fetchone()
                    if not old: return self.send_error(404)
                    if cid!=old['case_id']:raise ValueError('Nie można przenieść terminu do innej sprawy w tym formularzu.')
                    con.execute('''UPDATE case_appointments SET title=?,appointment_date=?,appointment_time=?,kind=?,location=?,notes=?,status=?,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?''',
                        (title,apdate,aptime,kind,location,notes,status,author,appointment_id))
                    con.execute('DELETE FROM appointment_assignees WHERE appointment_id=?',(appointment_id,))
                    rid=appointment_id
                else:
                    row=con.execute('''INSERT INTO case_appointments(case_id,title,appointment_date,appointment_time,kind,location,notes,status,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                                    (cid,title,apdate,aptime,kind,location,notes,status,author,author))
                    rid=row.lastrowid
                con.executemany('INSERT INTO appointment_assignees(appointment_id,user_id) VALUES(?,?)',[(rid,x) for x in ids])
                a.audit(con,cid,'appointment',rid,'Zapisano termin ustalony',f'{title} · {apdate} {aptime} · użytkownicy: {ids}',author)
            return self.redirect(f'/appointment/{rid}')
        except (ValueError,sqlite3.IntegrityError) as e:
            return self._plus_fail(str(e),target=f'/case/{fields.get("case_id","0")}?tab=deadlines')

    def appointment_page(self,rid):
        a=_app(self)
        with a.db() as con:
            r=con.execute('SELECT * FROM case_appointments WHERE id=?',(rid,)).fetchone()
            if not r:return self.send_error(404)
            assigned={x[0] for x in con.execute('SELECT user_id FROM appointment_assignees WHERE appointment_id=?',(rid,))}
            widgets=assignee_html(con,'appointment',rid,selected=assigned)
        opts=''.join(f'<option value="{x}" {"selected" if r["status"]==x else ""}>{label}</option>' for x,label in [('planned','Planowany'),('done','Odbył się'),('cancelled','Odwołany')])
        body=(f'<div class="topbar"><h1><a href="/case/{r["case_id"]}?tab=deadlines">Terminy sprawy</a> / {esc(r["title"])}</h1></div>'
              f'<div class="card"><form method="post" action="/appointment/{rid}/update" class="form-grid">'
              f'<input type="hidden" name="case_id" value="{r["case_id"]}">'
              f'<div class="full"><label>Nazwa terminu</label><input name="title" required value="{esc(r["title"])}"></div>'
              f'<div><label>Data</label><input name="appointment_date" type="date" required value="{esc(r["appointment_date"])}"></div>'
              f'<div><label>Godzina (opcjonalna)</label><input name="appointment_time" type="time" value="{esc(r["appointment_time"])}"></div>'
              f'<div><label>Rodzaj</label><input name="kind" value="{esc(r["kind"])}"></div>'
              f'<div><label>Miejsce</label><input name="location" value="{esc(r["location"])}"></div>'
              f'<div><label>Status</label><select name="status">{opts}</select></div>'
              f'<div class="full"><label>Notatki</label><textarea name="notes">{esc(r["notes"])}</textarea></div>'
              f'{widgets}<div class="full"><button class="btn primary">Zapisz zmiany</button></div></form></div>'
              f'<div class="card"><form method="post" action="/appointment/{rid}/delete" onsubmit="return confirm(\'Usunąć ten termin?\')">'
              '<button class="btn danger">Usuń termin</button></form></div>')
        self.send_html(a.layout('Termin ustalony',body,'calendar'))

    def appointment_delete(self,rid,fields):
        a=_app(self)
        import json
        with a.db() as con:
            r=con.execute('SELECT * FROM case_appointments WHERE id=?',(rid,)).fetchone()
            if not r:return self.send_error(404)
            users=[x[0] for x in con.execute('SELECT user_id FROM appointment_assignees WHERE appointment_id=?',(rid,))]
            payload={'record':dict(r),'assignees':users}
            con.execute('INSERT INTO deleted_appointments(id,payload_json,deleted_by) VALUES(?,?,?)',
                        (rid,json.dumps(payload,ensure_ascii=False),self.current_author(fields)))
            con.execute('DELETE FROM case_appointments WHERE id=?',(rid,))
            a.audit(con,r['case_id'],'appointment',rid,'Usunięto termin ustalony',r['title'],self.current_author(fields))
        self.redirect(f'/case/{r["case_id"]}?tab=deadlines')

    def appointment_restore(self,rid,fields):
        a=_app(self)
        import json
        with a.db() as con:
            tr=con.execute('SELECT * FROM deleted_appointments WHERE id=?',(rid,)).fetchone()
            if not tr:return self.send_error(404)
            if con.execute('SELECT 1 FROM case_appointments WHERE id=?',(rid,)).fetchone():
                return self._plus_fail('Identyfikator terminu został zajęty. Nie zmieniono danych.',409)
            payload=json.loads(tr['payload_json']);row=payload.get('record',payload)
            if not con.execute('SELECT 1 FROM cases WHERE id=?',(row['case_id'],)).fetchone():
                return self._plus_fail('Nie istnieje już sprawa powiązana z terminem.',409)
            columns=('id','case_id','title','appointment_date','appointment_time','kind',
                     'location','notes','status','created_by','updated_by','created_at','updated_at')
            con.execute(f'INSERT INTO case_appointments({",".join(columns)}) VALUES({",".join("?" for _ in columns)})',
                        tuple(row.get(k) for k in columns))
            for user_id in payload.get('assignees',[]):
                if con.execute('SELECT 1 FROM users WHERE id=?',(user_id,)).fetchone():
                    con.execute('INSERT INTO appointment_assignees(appointment_id,user_id) VALUES(?,?)',(rid,user_id))
            con.execute('DELETE FROM deleted_appointments WHERE id=?',(rid,))
            a.audit(con,row['case_id'],'appointment',rid,'Przywrócono termin',row['title'],self.current_author(fields))
        self.redirect(f'/appointment/{rid}')

    def task_assignments_save(self,tid,fields):
        a=_app(self)
        with a.db() as con:
            r=con.execute('SELECT case_id,title FROM tasks WHERE id=?',(tid,)).fetchone()
            if not r:return self.send_error(404)
            try:ids=selected_ids(fields,con)
            except ValueError as e:return self._plus_fail(str(e),target=f'/task/{tid}/edit')
            set_task_assignees(con,tid,ids)
            a.audit(con,r['case_id'],'task',tid,'Zmieniono współprzypisanie',f'{r["title"]}: {ids}',self.current_author(fields))
        self.redirect(f'/task/{tid}/edit')

    def sidecase_page(self,parent_id):
        a=_app(self)
        with a.db() as con:
            parent=con.execute('SELECT id,title,client FROM cases WHERE id=?',(parent_id,)).fetchone()
            if not parent:return self.send_error(404)
            links=linked_sidecases(con,parent_id)
        form=f'''<div class="card"><h2>Utwórz sprawę poboczną</h2><p class="small muted">Oddzielne postępowanie z własnymi dokumentami, zadaniami i terminami. Nie przenosi dokumentów automatycznie do sprawy głównej.</p>
        <form method="post" action="/case/{parent_id}/sidecase" class="form-grid">
        <div class="full"><label>Nazwa *</label><input name="title" required placeholder="np. Wniosek o zaświadczenie z urzędu"></div>
        <div class="full"><label>Przedmiot *</label><input name="subject" required placeholder="np. uzyskanie zaświadczenia potrzebnego do sprawy głównej"></div>
        <div class="full"><label>Co jest potrzebne sprawie głównej? *</label><input name="needed_item" required placeholder="np. zaświadczenie organu X"></div>
        <div><label>Organ / urząd</label><input name="court"></div><div><label>Kategoria</label><input name="category" value="administracyjna"></div>
        <div><label>Sygnatura (jeśli znana)</label><input name="signature"></div>
        <div class="full"><label>Opis zależności</label><textarea name="note"></textarea></div>
        <div class="full"><button class="btn primary">Utwórz sprawę poboczną</button></div></form></div>'''
        self.send_html(a.layout('Sprawy poboczne',f'<div class="topbar"><h1>Sprawy poboczne: <a href="/case/{parent_id}">{esc(parent["title"])}</a></h1></div><h2>Zależności</h2>{links}{form}','cases'))

    def sidecase_create(self,parent_id,fields):
        a=_app(self)
        title=str(fields.get('title') or '').strip()[:240]
        subject=str(fields.get('subject') or '').strip()[:1000]
        needed=str(fields.get('needed_item') or '').strip()[:500]
        if not title or not subject or not needed:return self._plus_fail('Wymagane: nazwa, przedmiot i oczekiwany dokument/czynność.',target=f'/case/{parent_id}/sidecases')
        with a.db() as con:
            parent=con.execute('SELECT id,client,lead_user_id FROM cases WHERE id=?',(parent_id,)).fetchone()
            if not parent:return self.send_error(404)
            author=self.current_author(fields)
            row=con.execute('''INSERT INTO cases(title,subject,client,lead_user_id,signature,court,category,status,created_by,updated_by)
                               VALUES(?,?,?,?,?,?,?,'active',?,?)''',
                            (title,subject,parent['client'],parent['lead_user_id'],str(fields.get('signature') or '')[:120],
                             str(fields.get('court') or '')[:240],str(fields.get('category') or '')[:100],author,author))
            child_id=row.lastrowid
            # Jeśli katalog już zainstalowano, kategoryzuj sprawę poboczną od razu.
            if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='case_category_catalog'").fetchone():
                from rk_case_categories import legacy_to_categories
                legacy_to_categories(con,child_id,str(fields.get('category') or ''))
            con.execute('''INSERT INTO side_case_dependencies(parent_case_id,child_case_id,needed_item,note,created_by)
                           VALUES(?,?,?,?,?)''',(parent_id,child_id,needed,str(fields.get('note') or '')[:2000],author))
            # Reuse native relationship graph (with explicit dependency row as source of truth).
            con.execute('''INSERT INTO case_relations(source_case_id,target_case_id,relation_type,note,created_by,updated_by)
                           VALUES(?,?,'main_related',?,?,?)''',(parent_id,child_id,'Sprawa poboczna: '+needed,author,author))
            a.audit(con,parent_id,'case',child_id,'Utworzono sprawę poboczną',f'{title}; wymagane: {needed}',author)
        self.redirect(f'/case/{child_id}')

    def sidecase_status(self,dep_id,fields):
        a=_app(self)
        status=str(fields.get('status') or '').strip()
        if status not in ('waiting','received','not_needed'):return self._plus_fail('Nieprawidłowy status zależności.')
        with a.db() as con:
            r=con.execute('SELECT * FROM side_case_dependencies WHERE id=?',(dep_id,)).fetchone()
            if not r:return self.send_error(404)
            try:doc_id=int(fields.get('document_id') or 0) or None
            except (TypeError,ValueError):return self._plus_fail('Nieprawidłowy numer dokumentu.')
            if doc_id and not con.execute('SELECT 1 FROM documents WHERE id=? AND case_id IN (?,?)',
                                          (doc_id,r['parent_case_id'],r['child_case_id'])).fetchone():
                return self._plus_fail('Dokument nie należy do sprawy głównej ani pobocznej.')
            con.execute('UPDATE side_case_dependencies SET status=?,document_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                        (status,doc_id,dep_id))
            a.audit(con,r['parent_case_id'],'sidecase',dep_id,'Zmieniono status zależności',
                    f'{status} · dokument {doc_id or "—"}',self.current_author(fields))
        self.redirect(f'/case/{r["parent_case_id"]}/sidecases')

    def my_calendar_page(self,qs=None):
        a=_app(self)
        user=a.current_request_user()
        if not user:return self.send_error(403)
        qs=qs or {}
        raw=(qs.get('month') or [date.today().strftime('%Y-%m')])[0]
        try:first=date.fromisoformat(raw+'-01')
        except ValueError:first=date.today().replace(day=1)
        begin=first-timedelta(days=first.weekday())
        last=first.replace(day=calendar.monthrange(first.year,first.month)[1])
        end=last+timedelta(days=6-last.weekday())
        prev=(first-timedelta(days=1)).replace(day=1)
        next_month=(last+timedelta(days=1))
        with a.db() as con:
            items=personal_calendar_items(con,user['id'],begin.isoformat(),end.isoformat())
        grouped={}
        for item in items:grouped.setdefault(item[0],[]).append(item)
        day=begin;boxes=[]
        while day<=end:
            key=day.isoformat();events=grouped.get(key,[])
            links=''.join(f'<a title="{esc(t)} — {esc(c)}" href="{esc(url)}" style="display:block;margin:3px 0;font-size:12px;line-height:1.25">{esc(k)}: {esc(t)}</a>' for _,k,t,url,c in events[:7])
            if len(events)>7:links+=f'<span class="small muted">+{len(events)-7} pozostałych</span>'
            css='background:#ecf5f0;' if day==date.today() else ''
            if day.month!=first.month:css+='opacity:.60;'
            boxes.append(f'<div style="min-height:92px;border:1px solid var(--line,#d9e1df);padding:8px;border-radius:8px;{css}"><b>{day.day}</b>{links}</div>')
            day+=timedelta(days=1)
        upcoming=''.join(f'<tr><td>{esc(d)}</td><td>{esc(k)}</td><td><a href="{esc(url)}">{esc(t)}</a></td><td>{esc(c)}</td></tr>' for d,k,t,url,c in items)
        body=(f'<div class="topbar"><div><h1>Mój kalendarz</h1><div class="sub">Zadania i terminy przypisane do Ciebie oraz zdarzenia spraw, które prowadzisz.</div></div>'
              f'<div><a class="btn" href="/my-calendar?month={prev:%Y-%m}">←</a> <b>{first:%m.%Y}</b> '
              f'<a class="btn" href="/my-calendar?month={next_month:%Y-%m}">→</a> <a class="btn" href="/calendar">Kalendarz całej kancelarii</a></div></div>'
              '<div class="card" style="overflow-x:auto"><div style="min-width:770px;display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:5px;">'
              +''.join(f'<b style="text-align:center">{x}</b>' for x in ('Pon','Wt','Śr','Czw','Pt','Sob','Niedz'))
              +''.join(boxes)+'</div></div>'
              '<div class="card"><h2>Wydarzenia w wybranym okresie</h2><div class="table-scroll"><table><tr><th>Data</th><th>Rodzaj</th><th>Wydarzenie</th><th>Sprawa</th></tr>'+upcoming+'</table></div></div>')
        self.send_html(a.layout('Mój kalendarz',body,'mycalendar'))
