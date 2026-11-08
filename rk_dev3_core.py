# -*- coding: utf-8 -*-
"""RK KANCELARIA dev3: isolated, additive business tables; no import of app.py."""
from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import secrets
import sqlite3
import uuid
from datetime import date, datetime, time, timezone, timedelta
from zoneinfo import ZoneInfo
from math import ceil
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

STAGES = {
    'intake': 'Przyjęcie sprawy',
    'pretrial': 'Etap przedprocesowy',
    'court': 'Postępowanie sądowe',
    'appeal': 'Postępowanie odwoławcze',
    'enforcement': 'Egzekucja',
    'settlement': 'Negocjacje / mediacja',
    'closed': 'Zakończona',
}


def ensure_dev3_schema(con: sqlite3.Connection) -> None:
    """Idempotent. Does not rewrite any existing case/documents or enable ACL retroactively."""
    con.executescript('''
    CREATE TABLE IF NOT EXISTS dev3_case_stage (
       case_id INTEGER PRIMARY KEY REFERENCES cases(id) ON DELETE CASCADE,
       stage TEXT NOT NULL DEFAULT 'intake', note TEXT NOT NULL DEFAULT '',
       updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
       updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS dev3_stage_log (
       id INTEGER PRIMARY KEY,case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
       old_stage TEXT NOT NULL,new_stage TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',
       user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
       created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS dev3_time_running (
       user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
       case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
       description TEXT NOT NULL DEFAULT '',
       started_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS dev3_time_entries (
       id INTEGER PRIMARY KEY,case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
       user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
       activity_date TEXT NOT NULL,minutes INTEGER NOT NULL CHECK(minutes BETWEEN 1 AND 1440),
       description TEXT NOT NULL DEFAULT '',billable INTEGER NOT NULL DEFAULT 1 CHECK(billable IN (0,1)),
       rate_grosze INTEGER NOT NULL DEFAULT 0 CHECK(rate_grosze BETWEEN 0 AND 100000000),
       source TEXT NOT NULL DEFAULT 'manual' CHECK(source IN ('manual','timer')),
       created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_dev3_time_case_date ON dev3_time_entries(case_id,activity_date);
    CREATE INDEX IF NOT EXISTS idx_dev3_time_user_date ON dev3_time_entries(user_id,activity_date);
    CREATE TABLE IF NOT EXISTS dev3_vault_files (
       id INTEGER PRIMARY KEY,case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
       owner_id INTEGER NOT NULL REFERENCES users(id),
       title TEXT NOT NULL,original_name TEXT NOT NULL,stored_name TEXT NOT NULL UNIQUE,
       byte_length INTEGER NOT NULL, digest_sha256 TEXT NOT NULL,
       created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS dev3_vault_grants (
       file_id INTEGER NOT NULL REFERENCES dev3_vault_files(id) ON DELETE CASCADE,
       user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
       PRIMARY KEY(file_id,user_id)
    );
    CREATE TABLE IF NOT EXISTS dev3_portal_items (
       id INTEGER PRIMARY KEY,origin TEXT NOT NULL DEFAULT 'manual_import',
       external_ref TEXT NOT NULL UNIQUE, signature TEXT NOT NULL DEFAULT '',
       document_title TEXT NOT NULL DEFAULT '',event_date TEXT NOT NULL DEFAULT '',
       details TEXT NOT NULL DEFAULT '',case_id INTEGER REFERENCES cases(id) ON DELETE SET NULL,
       reviewed INTEGER NOT NULL DEFAULT 0 CHECK(reviewed IN (0,1)),
       imported_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
       created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS dev3_calendar_links (
       provider TEXT NOT NULL CHECK(provider IN ('google','outlook')),
       appointment_id INTEGER NOT NULL REFERENCES case_appointments(id) ON DELETE CASCADE,
       external_id TEXT NOT NULL, etag TEXT NOT NULL DEFAULT '',
       synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
       PRIMARY KEY(provider,appointment_id),UNIQUE(provider,external_id)
    );
    CREATE TABLE IF NOT EXISTS dev3_calendar_pending (
       id INTEGER PRIMARY KEY,provider TEXT NOT NULL,external_id TEXT NOT NULL,
       title TEXT NOT NULL,start_at TEXT NOT NULL,end_at TEXT NOT NULL,
       payload_hash TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
       status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','dismissed')),
       UNIQUE(provider,external_id)
    );
    ''')


def set_stage(con, case_id: int, stage: str, actor: int, note: str = '') -> None:
    if stage not in STAGES:
        raise ValueError('Nieznany etap postępowania')
    if not con.execute('SELECT 1 FROM cases WHERE id=?',(case_id,)).fetchone():
        raise ValueError('Nie znaleziono sprawy')
    row=con.execute('SELECT stage FROM dev3_case_stage WHERE case_id=?',(case_id,)).fetchone()
    old = row[0] if row else ''
    if old == stage:
        return
    con.execute('INSERT INTO dev3_case_stage(case_id,stage,note,updated_by) VALUES(?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET stage=excluded.stage,note=excluded.note,updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP',(case_id,stage,note[:2000],actor))
    con.execute('INSERT INTO dev3_stage_log(case_id,old_stage,new_stage,note,user_id) VALUES(?,?,?,?,?)',(case_id,old,stage,note[:2000],actor))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def rate_grosze(value: str) -> int:
    try:
        d=Decimal(str(value).strip().replace(',','.'))
        if not d.is_finite() or d < 0 or d > 1000000:
            raise ValueError()
        return int((d*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    except (ValueError, InvalidOperation):
        raise ValueError('Stawka musi być kwotą od 0 do 1 000 000 PLN')


def start_timer(con, user_id: int, case_id: int, description: str='', now: datetime | None=None):
    now=now or _utcnow()
    if now.tzinfo is None: raise ValueError('Wymagana data ze strefą czasową')
    if not con.execute('SELECT 1 FROM cases WHERE id=?',(case_id,)).fetchone():
        raise ValueError('Nieznana sprawa')
    if con.execute('SELECT 1 FROM dev3_time_running WHERE user_id=?',(user_id,)).fetchone():
        raise ValueError('Stoper już jest uruchomiony. Zatrzymaj go przed rozpoczęciem następnego.')
    con.execute('INSERT INTO dev3_time_running(user_id,case_id,description,started_at) VALUES(?,?,?,?)',(user_id,case_id,description[:1000],now.astimezone(timezone.utc).isoformat()))


def stop_timer(con,user_id: int, rate: int=0, billable: bool=True, now: datetime | None=None) -> int:
    # Store every minute, splitting runs by local Polish calendar days.
    now=now or _utcnow()
    if now.tzinfo is None:raise ValueError('Wymagana data ze strefą czasową')
    row=con.execute('SELECT case_id,description,started_at FROM dev3_time_running WHERE user_id=?',(user_id,)).fetchone()
    if not row:raise ValueError('Stoper nie jest uruchomiony')
    started=datetime.fromisoformat(row[2]); elapsed=(now-started).total_seconds()
    if elapsed<0:raise ValueError('Zegar systemowy przesunął się wstecz')
    # Prevent an accidentally running timer for months from silently creating fake billable work.
    if elapsed>31*86400:raise ValueError('Pomiar przekracza 31 dni. Zweryfikuj go i anuluj lub rozlicz ręcznie.')
    if not 0<=rate<=100000000:raise ValueError('Nieprawidłowa stawka')
    tz=ZoneInfo('Europe/Warsaw')
    cursor=started.astimezone(timezone.utc)
    stop_at=now.astimezone(timezone.utc)
    segments=[]
    while cursor<stop_at:
        local_day=cursor.astimezone(tz).date()
        midnight=datetime.combine(local_day+timedelta(days=1),time.min,tzinfo=tz).astimezone(timezone.utc)
        boundary=min(midnight,stop_at)
        if boundary<=cursor:raise ValueError('Nie można ustalić lokalnej daty pomiaru')
        segments.append((local_day.isoformat(),(boundary-cursor).total_seconds()))
        cursor=boundary
    if not segments:segments=[(now.astimezone(tz).date().isoformat(),0)]
    remaining=max(1,ceil(elapsed/60))
    rows=[]
    for i,(day,seconds) in enumerate(segments):
        minutes=remaining if i==len(segments)-1 else min(remaining,int(seconds//60))
        remaining-=minutes
        while minutes>0:
            piece=min(1440,minutes)
            rows.append((day,piece))
            minutes-=piece
    if remaining:raise ValueError('Niepoprawny podział czasu')
    first_id=None
    for day,minutes in rows:
        cur=con.execute('''INSERT INTO dev3_time_entries(case_id,user_id,activity_date,minutes,description,billable,rate_grosze,source)
            VALUES(?,?,?,?,?,?,?,'timer')''',(row[0],user_id,day,minutes,row[1],int(bool(billable)),rate))
        if first_id is None:first_id=cur.lastrowid
    con.execute('DELETE FROM dev3_time_running WHERE user_id=?',(user_id,))
    return first_id


def add_manual_time(con, case_id: int,user_id: int, day: str, minutes: int, description: str,rate: int,billable: bool) -> int:
    try: date.fromisoformat(day)
    except (TypeError,ValueError):raise ValueError('Nieprawidłowa data')
    if not 1<=minutes<=1440:raise ValueError('Czas wpisu musi wynosić 1–1440 minut')
    if not con.execute('SELECT 1 FROM cases WHERE id=?',(case_id,)).fetchone():raise ValueError('Nieznana sprawa')
    cur=con.execute('''INSERT INTO dev3_time_entries(case_id,user_id,activity_date,minutes,description,billable,rate_grosze,source)
     VALUES(?,?,?,?,?,?,?,'manual')''',(case_id,user_id,day,minutes,description[:2000],int(bool(billable)),rate))
    return cur.lastrowid


def time_csv(con, user_id: int | None=None) -> bytes:
    out=io.StringIO();w=csv.writer(out,delimiter=';');w.writerow(['Data','Sprawa','Sygnatura','Prawnik','Czas (min)','Opis','Rozliczalne','Stawka PLN/h','Kwota PLN'])
    sql='''SELECT t.*,c.title,c.signature,u.author_name FROM dev3_time_entries t
         JOIN cases c ON c.id=t.case_id LEFT JOIN users u ON u.id=t.user_id'''
    args=[]
    if user_id is not None:sql+=' WHERE t.user_id=?';args=[user_id]
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dev4_time_voids'").fetchone():
        sql+= (' AND ' if args else ' WHERE ')+'NOT EXISTS(SELECT 1 FROM dev4_time_voids v WHERE v.entry_id=t.id)'
    sql+=' ORDER BY t.activity_date,t.id'
    def safe_cell(value):
        value=str('' if value is None else value)
        # CSV exported for office spreadsheets must not execute user supplied formulas.
        if value.lstrip().startswith(('=', '+', '-', '@')):
            return "'"+value
        return value
    for x in con.execute(sql,args):
        row=dict(x) if hasattr(x,'keys') else x
        vals=[row[k] for k in ('activity_date','title','signature','author_name','minutes','description','billable','rate_grosze')]
        cents=(vals[4]*vals[7]//60) if vals[6] else 0
        w.writerow([safe_cell(v) for v in vals[:6]]+['tak' if vals[6] else 'nie',f'{vals[7]/100:.2f}',f'{cents/100:.2f}'])
    return ('\ufeff'+out.getvalue()).encode('utf-8')


MAGIC=b'RKVAULT1'

def encrypt_vault(blob: bytes, password: str) -> bytes:
    if not isinstance(password,str) or len(password)<12:
        raise ValueError('Hasło sejfu musi mieć co najmniej 12 znaków')
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt=secrets.token_bytes(16);nonce=secrets.token_bytes(12)
    key=hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),salt,600000,32)
    return MAGIC+salt+nonce+AESGCM(key).encrypt(nonce,blob,MAGIC)


def decrypt_vault(blob: bytes, password: str) -> bytes:
    if not blob.startswith(MAGIC) or len(blob)<len(MAGIC)+16+12+16:
        raise ValueError('Nieprawidłowy plik sejfu')
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt=blob[8:24];nonce=blob[24:36]
    key=hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),salt,600000,32)
    try:return AESGCM(key).decrypt(nonce,blob[36:],MAGIC)
    except Exception as exc:raise ValueError('Niepoprawne hasło lub naruszona integralność pliku') from exc


def vault_can_view(con,file_id: int,user_id: int,is_admin: bool=False) -> bool:
    if is_admin:return bool(con.execute('SELECT 1 FROM dev3_vault_files WHERE id=?',(file_id,)).fetchone())
    return bool(con.execute('''SELECT 1 FROM dev3_vault_files v LEFT JOIN dev3_vault_grants g ON g.file_id=v.id AND g.user_id=?
       WHERE v.id=? AND (v.owner_id=? OR g.user_id IS NOT NULL)''',(user_id,file_id,user_id)).fetchone())


def vault_store(con,files_dir: Path,case_id:int,owner_id:int,name:str,data:bytes,password:str,title:str='') -> int:
    if not 1<=len(data)<=16*1024*1024:raise ValueError('Do sejfu można dodać plik do 16 MB')
    if not con.execute('SELECT 1 FROM cases WHERE id=?',(case_id,)).fetchone():raise ValueError('Nieznana sprawa')
    encoded=encrypt_vault(data,password)
    store=uuid.uuid4().hex+'.rkv';folder=files_dir/'_vault';folder.mkdir(parents=True,exist_ok=True)
    from rk_core.files import atomic_write_bytes
    path=folder/store
    atomic_write_bytes(path,encoded)
    try:
        cur=con.execute('''INSERT INTO dev3_vault_files(case_id,owner_id,title,original_name,stored_name,byte_length,digest_sha256)
          VALUES(?,?,?,?,?,?,?)''',(case_id,owner_id,(title or name)[:250],Path(name.replace('\\','/')).name[:255],store,len(data),hashlib.sha256(data).hexdigest()))
        return cur.lastrowid
    except Exception:
        path.unlink(missing_ok=True)
        raise


def import_portal_csv(con,raw:bytes,actor:int,max_rows:int=500) -> tuple[int,int]:
    if len(raw)>2*1024*1024:raise ValueError('Plik przekracza limit 2 MB')
    try:data=raw.decode('utf-8-sig')
    except UnicodeDecodeError:raise ValueError('Wymagany CSV w UTF-8')
    sample=data[:4096]
    dialect=csv.Sniffer().sniff(sample,delimiters=';,\t') if sample else csv.excel
    rows=csv.DictReader(io.StringIO(data),dialect=dialect)
    expected={'sygnatura','data','tytul','identyfikator'}
    if not rows.fieldnames or not expected.issubset(set(rows.fieldnames)):
        raise ValueError('Wymagane nagłówki CSV: identyfikator, sygnatura, data, tytul (opcjonalnie opis)')
    added=duplicate=0
    for i,row in enumerate(rows):
        if i>=max_rows:raise ValueError('Maksymalnie 500 rekordów na plik')
        ref=(row.get('identyfikator') or '').strip()
        if not ref:continue
        if len(ref)>200:raise ValueError('Zbyt długi identyfikator')
        value=(ref,(row.get('sygnatura') or '')[:150],(row.get('tytul') or '')[:250],
               (row.get('data') or '')[:20],(row.get('opis') or '')[:4000],actor)
        existing=con.execute('SELECT id,reviewed FROM dev3_portal_items WHERE external_ref=?',(ref,)).fetchone()
        if existing:
            duplicate+=1
            # Never silently overwrite a record already confirmed by a lawyer.
            if not existing['reviewed'] if hasattr(existing,'keys') else not existing[1]:
                con.execute('''UPDATE dev3_portal_items SET signature=?,document_title=?,event_date=?,details=?
                    WHERE id=? AND reviewed=0''',(*value[1:5],existing['id'] if hasattr(existing,'keys') else existing[0]))
        else:
            con.execute('''INSERT INTO dev3_portal_items(external_ref,signature,document_title,event_date,details,imported_by)
                VALUES(?,?,?,?,?,?)''',value)
            added+=1
    return added,duplicate
