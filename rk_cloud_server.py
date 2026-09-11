# -*- coding: utf-8 -*-
"""RK KANCELARIA DEV8 — prosty Cloud Bridge z PostgreSQL.

To bezpieczny magazyn wersjonowanych pełnych snapshotów kancelarii, a nie mechanizm
równoczesnego scalania rekordów. PUT wykorzystuje optimistic locking (base_version),
więc nowszy snapshot nie może zostać cicho nadpisany starszym.

Zmienne środowiskowe:
  DATABASE_URL=postgresql://...
  RK_CLOUD_TOKEN=dlugi-losowy-token
  RK_CLOUD_HOST=127.0.0.1
  RK_CLOUD_PORT=8787
  RK_CLOUD_MAX_MB=1024
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

try:
    import psycopg
except Exception as exc:  # pragma: no cover
    raise SystemExit('Brak psycopg. Zainstaluj: pip install -r requirements_cloud.txt') from exc

DATABASE_URL=os.getenv('DATABASE_URL','').strip()
TOKEN=os.getenv('RK_CLOUD_TOKEN','').strip()
HOST=os.getenv('RK_CLOUD_HOST','127.0.0.1').strip() or '127.0.0.1'
PORT=int(os.getenv('RK_CLOUD_PORT','8787'))
MAX_BYTES=int(os.getenv('RK_CLOUD_MAX_MB','1024'))*1024*1024
OFFICE_RE=re.compile(r'^/api/v1/offices/([^/]+)/(meta|snapshot)$')

if not DATABASE_URL:
    raise SystemExit('Ustaw DATABASE_URL.')
if len(TOKEN)<16:
    raise SystemExit('Ustaw RK_CLOUD_TOKEN (minimum 16 znaków).')


def db():
    return psycopg.connect(DATABASE_URL)


def init_db():
    with db() as con:
        con.execute('''CREATE TABLE IF NOT EXISTS rk_office_snapshots(
            office_id TEXT PRIMARY KEY,
            version BIGINT NOT NULL DEFAULT 0,
            payload BYTEA NOT NULL,
            sha256 TEXT NOT NULL,
            size_bytes BIGINT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )''')


class Handler(BaseHTTPRequestHandler):
    server_version='RKCloud/0.2.0-dev8'
    def log_message(self,fmt,*args):
        print('%s - %s' % (self.address_string(),fmt%args))

    def json(self,status,obj):
        raw=json.dumps(obj,ensure_ascii=False).encode('utf-8')
        self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(raw))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(raw)

    def authorized(self):
        got=self.headers.get('Authorization','')
        expected='Bearer '+TOKEN
        if not hmac.compare_digest(got,expected):
            self.json(401,{'error':'Brak autoryzacji Cloud.'}); return False
        return True

    def parse_target(self):
        m=OFFICE_RE.match(urlparse(self.path).path)
        if not m: return None,None
        office=unquote(m.group(1)).strip()
        if not office or len(office)>180: return None,None
        return office,m.group(2)

    def do_GET(self):
        if urlparse(self.path).path=='/health':
            return self.json(200,{'ok':True,'service':'RK KANCELARIA Cloud Bridge','version':'0.2.0-dev8'})
        if not self.authorized(): return
        office,kind=self.parse_target()
        if not office: return self.json(404,{'error':'Nieznany endpoint.'})
        with db() as con:
            row=con.execute('SELECT office_id,version,sha256,size_bytes,updated_at,payload FROM rk_office_snapshots WHERE office_id=%s',(office,)).fetchone()
        if not row: return self.json(404,{'error':'Brak snapshotu dla tej kancelarii.'})
        if kind=='meta':
            return self.json(200,{'office_id':row[0],'version':row[1],'sha256':row[2],'size':row[3],'updated_at':row[4].isoformat(),'exists':True})
        payload=bytes(row[5])
        self.send_response(200); self.send_header('Content-Type','application/zip'); self.send_header('Content-Length',str(len(payload)))
        self.send_header('X-RK-Version',str(row[1])); self.send_header('X-RK-SHA256',row[2]); self.send_header('X-RK-Updated-At',row[4].isoformat())
        self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(payload)

    def do_PUT(self):
        if not self.authorized(): return
        office,kind=self.parse_target()
        if not office or kind!='snapshot': return self.json(404,{'error':'Nieznany endpoint.'})
        try: length=int(self.headers.get('Content-Length','0'))
        except ValueError: return self.json(400,{'error':'Błędny Content-Length.'})
        if length<=0 or length>MAX_BYTES: return self.json(413,{'error':f'Snapshot ma nieprawidłowy rozmiar. Limit: {MAX_BYTES//1024//1024} MB.'})
        try: base=int(self.headers.get('X-RK-Base-Version','0') or 0)
        except ValueError: return self.json(400,{'error':'Błędny X-RK-Base-Version.'})
        payload=self.rfile.read(length)
        if len(payload)!=length: return self.json(400,{'error':'Przerwane przesyłanie snapshotu.'})
        if payload[:2]!=b'PK': return self.json(400,{'error':'Snapshot nie jest archiwum ZIP.'})
        digest=hashlib.sha256(payload).hexdigest(); now=datetime.now(timezone.utc)
        with db() as con:
            row=con.execute('SELECT version FROM rk_office_snapshots WHERE office_id=%s FOR UPDATE',(office,)).fetchone()
            current=int(row[0]) if row else 0
            if base!=current:
                con.rollback(); return self.json(409,{'error':f'Konflikt wersji: serwer ma v{current}, klient bazuje na v{base}. Najpierw pobierz nowszy stan lub świadomie rozwiąż konflikt.','server_version':current})
            new=current+1
            if row:
                con.execute('UPDATE rk_office_snapshots SET version=%s,payload=%s,sha256=%s,size_bytes=%s,updated_at=%s WHERE office_id=%s',(new,payload,digest,len(payload),now,office))
            else:
                con.execute('INSERT INTO rk_office_snapshots(office_id,version,payload,sha256,size_bytes,updated_at) VALUES(%s,%s,%s,%s,%s,%s)',(office,new,payload,digest,len(payload),now))
        return self.json(200,{'office_id':office,'version':new,'sha256':digest,'size':len(payload),'updated_at':now.isoformat(),'exists':True})


if __name__=='__main__':
    init_db(); print(f'RK Cloud Bridge: http://{HOST}:{PORT}')
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
