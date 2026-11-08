# -*- coding: utf-8 -*-
"""Review-first synchronization for existing Google/Outlook-linked appointments.

External changes never silently overwrite legal deadlines. They become explicit
proposals requiring an administrator to accept or dismiss them.
"""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo

LOCAL=ZoneInfo('Europe/Warsaw')


def ensure_dev5_calendar_schema(con):
    con.executescript('''
      CREATE TABLE IF NOT EXISTS dev5_calendar_remote_state(
        provider TEXT NOT NULL, external_id TEXT NOT NULL, data_hash TEXT NOT NULL,
        PRIMARY KEY(provider,external_id)
      );
      CREATE TABLE IF NOT EXISTS dev5_calendar_changes(
        id INTEGER PRIMARY KEY,
        provider TEXT NOT NULL,external_id TEXT NOT NULL,
        appointment_id INTEGER NOT NULL REFERENCES case_appointments(id) ON DELETE CASCADE,
        data_hash TEXT NOT NULL, title TEXT NOT NULL,start_at TEXT NOT NULL,end_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','dismissed')),
        cancelled INTEGER NOT NULL DEFAULT 0, missing INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(provider,external_id)
      );
    ''')


def _stamp(value,provider):
    """Normalize RFC3339 and Graph UTC strings to Warsaw; avoid DST ignorance."""
    if not value:return ''
    if isinstance(value,dict):value=value.get('dateTime') or value.get('date') or ''
    value=str(value).strip()
    if not value:return ''
    if 'T' not in value:return date.fromisoformat(value).isoformat()
    dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None:
        # Graph calendarView defaults to UTC; application-generated Graph
        # bodies use local wall time but are normalized before calling here.
        if provider=='outlook':dt=dt.replace(tzinfo=timezone.utc)
        else:raise ValueError('Google wydarzenie nie ma strefy czasowej')
    return dt.astimezone(LOCAL).strftime('%Y-%m-%dT%H:%M')


def event_fields(provider,obj):
    if provider=='google':
        title=str(obj.get('summary') or '(bez tytułu)')[:250]
        start=_stamp(obj.get('start'),provider);end=_stamp(obj.get('end'),provider)
        cancelled=bool(obj.get('status')=='cancelled')
    elif provider=='outlook':
        title=str(obj.get('subject') or '(bez tytułu)')[:250]
        start=_stamp(obj.get('start'),provider);end=_stamp(obj.get('end'),provider)
        cancelled=bool(obj.get('isCancelled'))
    else:raise ValueError('Nieznany dostawca')
    if cancelled and not (start and end):
        # Some cancellation notifications contain only ID.
        start=end=''
    if not cancelled and not (start and end):raise ValueError('Brak dat wydarzenia')
    encoded=json.dumps([title,start,end,cancelled],ensure_ascii=False,separators=(',',':'))
    digest=hashlib.sha256(encoded.encode('utf-8')).hexdigest()
    return title,start,end,cancelled,digest


def linked_event(con,provider,external_id,obj):
    """Return True if linked; insert/update explicit change proposal if needed."""
    link=con.execute('SELECT appointment_id FROM dev3_calendar_links WHERE provider=? AND external_id=?',
                     (provider,external_id)).fetchone()
    if not link:return False
    title,start,end,cancelled,digest=event_fields(provider,obj)
    old=con.execute('SELECT data_hash FROM dev5_calendar_remote_state WHERE provider=? AND external_id=?',
                    (provider,external_id)).fetchone()
    if not old:
        con.execute('INSERT OR IGNORE INTO dev5_calendar_remote_state(provider,external_id,data_hash) VALUES(?,?,?)',
                    (provider,external_id,digest))
        return True
    if old[0]==digest:
        con.execute("DELETE FROM dev5_calendar_changes WHERE provider=? AND external_id=? AND status='pending'",
                    (provider,external_id))
        return True
    con.execute('''INSERT INTO dev5_calendar_changes(
        provider,external_id,appointment_id,data_hash,title,start_at,end_at,status,cancelled)
        VALUES(?,?,?,?,?,?,?,'pending',?)
        ON CONFLICT(provider,external_id) DO UPDATE SET
          data_hash=excluded.data_hash,title=excluded.title,
          start_at=excluded.start_at,end_at=excluded.end_at,
          status='pending',cancelled=excluded.cancelled,
          created_at=CURRENT_TIMESTAMP''',
        (provider,external_id,link[0],digest,title,start,end,int(cancelled)))
    return True


def accept_change(con,change_id,actor_id,accept=False):
    row=con.execute("SELECT * FROM dev5_calendar_changes WHERE id=? AND status='pending'",(change_id,)).fetchone()
    if not row:raise ValueError('Brak aktualnej zmiany kalendarza')
    if accept:
        if row['missing']:
            con.execute('''UPDATE case_appointments SET notes=COALESCE(notes,'') || ? WHERE id=?''',
                        ('\nUWAGA: wydarzenia nie odnaleziono w pobranym oknie; zweryfikuj u dostawcy kalendarza.',row['appointment_id']))
        elif row['cancelled']:
            # Court deadline must never be erased just because an external
            # calendar event disappeared. Mark it in notes, not delete.
            con.execute('''UPDATE case_appointments SET notes=COALESCE(notes,'') || ? WHERE id=?''',
                        ('\nUWAGA: zewnętrzne wydarzenie anulowane; termin wymaga kontroli ręcznej.',row['appointment_id']))
        else:
            start=row['start_at']
            if len(start)<16 or 'T' not in start:raise ValueError('Brak daty do aktualizacji')
            con.execute('''UPDATE case_appointments SET appointment_date=?,appointment_time=?,notes=COALESCE(notes,'') || ?
                           WHERE id=?''',
                        (start[:10],start[11:16], '\nZweryfikowano zmianę z kalendarza zewnętrznego.',row['appointment_id']))
    con.execute('''INSERT INTO dev5_calendar_remote_state(provider,external_id,data_hash) VALUES(?,?,?)
        ON CONFLICT(provider,external_id) DO UPDATE SET data_hash=excluded.data_hash''',
        (row['provider'],row['external_id'],row['data_hash']))
    con.execute('UPDATE dev5_calendar_changes SET status=? WHERE id=?',
                ('accepted' if accept else 'dismissed',change_id))
    return row['appointment_id']


def record_published(con,provider,external_id,title,local_start,local_end):
    # Preserve the state we intend to publish, so the first subsequent pull
    # can recognize a change immediately (no 'untracked baseline' window).
    encoded=json.dumps([title,local_start,local_end,False],ensure_ascii=False,separators=(',',':'))
    digest=hashlib.sha256(encoded.encode('utf-8')).hexdigest()
    con.execute('''INSERT INTO dev5_calendar_remote_state(provider,external_id,data_hash) VALUES(?,?,?)
        ON CONFLICT(provider,external_id) DO UPDATE SET data_hash=excluded.data_hash''',
        (provider,external_id,digest))
    con.execute("DELETE FROM dev5_calendar_changes WHERE provider=? AND external_id=? AND status='pending'",
                (provider,external_id))


def mark_missing(con,provider,seen_ids,start_day,end_day):
    """After a complete pull, flag linked appointments absent from the window.

    An event absent from the window may have moved outside it. This is a review
    notice, NEVER an automatic cancellation of a legal appointment.
    """
    rows=con.execute('''SELECT l.external_id,l.appointment_id,a.title,a.appointment_date,a.appointment_time,
        s.data_hash FROM dev3_calendar_links l
        JOIN case_appointments a ON a.id=l.appointment_id
        JOIN dev5_calendar_remote_state s ON s.provider=l.provider AND s.external_id=l.external_id
        WHERE l.provider=? AND a.appointment_date>=? AND a.appointment_date<=?''',
        (provider,start_day.isoformat(),end_day.isoformat())).fetchall()
    changes=0
    for row in rows:
        if row['external_id'] in seen_ids:continue
        digest=hashlib.sha256(('not-present:'+str(row['external_id'])).encode()).hexdigest()
        if row['data_hash']==digest:continue
        start=str(row['appointment_date'] or '')+'T'+str(row['appointment_time'] or '09:00')
        con.execute('''INSERT INTO dev5_calendar_changes(provider,external_id,appointment_id,
            data_hash,title,start_at,end_at,status,cancelled,missing)
            VALUES(?,?,?,?,?,?,?,'pending',0,1)
            ON CONFLICT(provider,external_id) DO UPDATE SET
                data_hash=excluded.data_hash,title=excluded.title,start_at=excluded.start_at,
                end_at=excluded.end_at,status='pending',cancelled=0,missing=1,
                created_at=CURRENT_TIMESTAMP''',
            (provider,row['external_id'],row['appointment_id'],digest,row['title'],start,''))
        changes+=1
    return changes
