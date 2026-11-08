# -*- coding: utf-8 -*-
"""Google Calendar / Microsoft Graph: explicit OAuth refresh-token setup.

No password scraping, no credentials in SQLite, and no automatic court deadline
interpretation. Incoming events are proposals requiring assignment to a case.
Publishing requires an explicit click; conflict preconditions prevent silent edits.
"""
from __future__ import annotations
import hashlib
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone, time as dtime
from zoneinfo import ZoneInfo
from rk_dev5_calendar_reconcile import linked_event, record_published, mark_missing

SUPPORTED=('google','outlook')

class CalendarSyncError(RuntimeError):pass

def _post_form(url: str, fields: dict) -> dict:
    data=urllib.parse.urlencode(fields).encode()
    req=urllib.request.Request(url,data=data,method='POST',headers={'Content-Type':'application/x-www-form-urlencoded'})
    try:
        with urllib.request.urlopen(req,timeout=20) as resp:
            return json.loads(resp.read(1024*1024).decode())
    except urllib.error.HTTPError as exc:
        raise CalendarSyncError('Nie można odświeżyć autoryzacji (HTTP %s)'%exc.code) from exc
    except (OSError,ValueError) as exc:
        raise CalendarSyncError('Błąd odświeżania połączenia kalendarza') from exc

def access_token(provider: str) -> str:
    if provider=='google':
        cid=os.environ.get('RK_GOOGLE_CLIENT_ID','').strip()
        token=os.environ.get('RK_GOOGLE_REFRESH_TOKEN','').strip()
        secret=os.environ.get('RK_GOOGLE_CLIENT_SECRET','').strip()
        if not cid or not token:raise CalendarSyncError('Skonfiguruj RK_GOOGLE_CLIENT_ID i RK_GOOGLE_REFRESH_TOKEN')
        fields={'client_id':cid,'refresh_token':token,'grant_type':'refresh_token'}
        if secret: fields['client_secret']=secret
        endpoint='https://oauth2.googleapis.com/token'
    elif provider=='outlook':
        cid=os.environ.get('RK_MS_CLIENT_ID','').strip()
        token=os.environ.get('RK_MS_REFRESH_TOKEN','').strip()
        tenant=os.environ.get('RK_MS_TENANT','common').strip()
        if not cid or not token:raise CalendarSyncError('Skonfiguruj RK_MS_CLIENT_ID i RK_MS_REFRESH_TOKEN')
        if not tenant.replace('-','').isalnum():raise CalendarSyncError('Niepoprawna konfiguracja tenant')
        fields={'client_id':cid,'refresh_token':token,'grant_type':'refresh_token','scope':'offline_access Calendars.ReadWrite'}
        endpoint=f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token'
    else:raise CalendarSyncError('Nieznany dostawca kalendarza')
    obj=_post_form(endpoint,fields)
    if not obj.get('access_token'):raise CalendarSyncError('Usługa nie zwróciła tokenu dostępu')
    return str(obj['access_token'])

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise CalendarSyncError('Odrzucono przekierowanie API poza ustalony punkt końcowy')

def _api(url:str,token:str,method='GET',body:dict|None=None,etag:str|None=None) -> dict:
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in ('www.googleapis.com','graph.microsoft.com'):
        raise CalendarSyncError('Niedozwolony adres API')
    if parsed.username or parsed.password:raise CalendarSyncError('Nieprawidłowy adres')
    headers={'Authorization':'Bearer '+token,'Accept':'application/json'}
    if etag:headers['If-Match']=etag
    data=None
    if body is not None:
        data=json.dumps(body,ensure_ascii=False).encode('utf-8')
        headers['Content-Type']='application/json'
    req=urllib.request.Request(url,data=data,headers=headers,method=method)
    try:
        with urllib.request.build_opener(_NoRedirect).open(req,timeout=35) as response:
            raw=response.read(4*1024*1024)
            return json.loads(raw.decode('utf-8')) if raw else {}
    except urllib.error.HTTPError as exc:
        if exc.code==409 and method=='POST':raise CalendarSyncError('Wydarzenie o podanym identyfikatorze już istnieje (HTTP 409)') from exc
        if exc.code in (409,412):raise CalendarSyncError('Konflikt wersji zdalnego wydarzenia. Odśwież dane przed ponowną próbą.') from exc
        if exc.code in (401,403):raise CalendarSyncError('Brak autoryzacji kalendarza — sprawdź uprawnienia OAuth.') from exc
        raise CalendarSyncError('Kalendarz zwrócił błąd HTTP %s'%exc.code) from exc
    except (OSError,ValueError) as exc:
        if isinstance(exc,CalendarSyncError):raise
        raise CalendarSyncError('Błąd połączenia z kalendarzem') from exc

def _google_endpoint() -> str:
    calendar_id=os.environ.get('RK_GOOGLE_CALENDAR_ID','primary')
    if not 1<=len(calendar_id)<=254:raise CalendarSyncError('Nieprawidłowy identyfikator kalendarza')
    return 'https://www.googleapis.com/calendar/v3/calendars/'+urllib.parse.quote(calendar_id,safe='')+'/events'

def _outlook_endpoint() -> str:
    return 'https://graph.microsoft.com/v1.0/me/events'


def pull_proposals(con,provider:str,token:str,days:int=90)->tuple[int,int]:
    """Pull candidate events only; never create judicial deadlines automatically."""
    if provider not in SUPPORTED:raise CalendarSyncError('Nieznany kalendarz')
    today=datetime.now(ZoneInfo('Europe/Warsaw')).date()
    end=today+timedelta(days=min(max(days,1),365))
    # Provider API uses UTC boundaries; they must represent midnight in Poland,
    # including the DST offset on each boundary (rather than 00:00 UTC).
    start_utc=datetime.combine(today,dtime.min,ZoneInfo('Europe/Warsaw')).astimezone(timezone.utc)
    end_utc=datetime.combine(end+timedelta(days=1),dtime.min,ZoneInfo('Europe/Warsaw')).astimezone(timezone.utc)
    time_min=start_utc.isoformat().replace('+00:00','Z')
    time_max=end_utc.isoformat().replace('+00:00','Z')
    if provider=='google':
        url=_google_endpoint()+'?'+urllib.parse.urlencode({'timeMin':time_min,'timeMax':time_max,'singleEvents':'true','maxResults':'250'})
        event_key='items'; next_key='nextPageToken'
    else:
        url='https://graph.microsoft.com/v1.0/me/calendarView?'+urllib.parse.urlencode({'startDateTime':time_min,'endDateTime':time_max,'$top':'100'})
        event_key='value'; next_key='@odata.nextLink'
    added=updated=0
    seen_ids=set()
    for page in range(5):
        payload=_api(url,token)
        for obj in payload.get(event_key,[]):
            if not isinstance(obj,dict) or not obj.get('id'):continue
            eid=str(obj['id'])[:400]
            seen_ids.add(eid)
            if provider=='google':
                if obj.get('status')=='cancelled':
                    linked_event(con,provider,eid,obj)
                    continue
                title=obj.get('summary') or '(bez tytułu)'
                start=(obj.get('start') or {}).get('dateTime') or (obj.get('start') or {}).get('date','')
                stop=(obj.get('end') or {}).get('dateTime') or (obj.get('end') or {}).get('date','')
            else:
                if obj.get('isCancelled'):
                    linked_event(con,provider,eid,obj)
                    continue
                title=obj.get('subject') or '(bez tytułu)'
                start=(obj.get('start') or {}).get('dateTime','')
                stop=(obj.get('end') or {}).get('dateTime','')
            if not start or not stop:continue
            if linked_event(con,provider,eid,obj):continue
            title=str(title)[:300];start=str(start)[:80];stop=str(stop)[:80]
            h=hashlib.sha256(json.dumps((title,start,stop),ensure_ascii=False).encode()).hexdigest()
            prev=con.execute('SELECT payload_hash FROM dev3_calendar_pending WHERE provider=? AND external_id=?',(provider,eid)).fetchone()
            con.execute('''INSERT INTO dev3_calendar_pending(provider,external_id,title,start_at,end_at,payload_hash)
                VALUES(?,?,?,?,?,?) ON CONFLICT(provider,external_id) DO UPDATE SET
                title=excluded.title,start_at=excluded.start_at,end_at=excluded.end_at,payload_hash=excluded.payload_hash
                WHERE dev3_calendar_pending.status='pending' ''',(provider,eid,title,start,stop,h))
            if prev:
                if prev[0]!=h:updated+=1
            else:added+=1
        marker=payload.get(next_key)
        if not marker:break
        if provider=='google':
            parsed=urllib.parse.urlsplit(url)
            q=urllib.parse.parse_qs(parsed.query)
            q['pageToken']=[marker]
            url=urllib.parse.urlunsplit((parsed.scheme,parsed.netloc,parsed.path,urllib.parse.urlencode(q,doseq=True),''))
        else:
            if not str(marker).startswith('https://graph.microsoft.com/'):
                raise CalendarSyncError('Odrzucono zewnętrzny adres paginacji')
            url=marker
        # Close SQLite write transaction before the next potentially slow API call.
        # Previously a slow pagination request could hold a database write lock.
        con.commit()
        if page == 4 and marker:
            raise CalendarSyncError('Kalendarz zawiera więcej niż 5 stron wydarzeń. Import nie jest kompletny; uruchom ponownie po ograniczeniu zakresu.')
    mark_missing(con,provider,seen_ids,today,end)
    return added,updated


def publish_appointment(con,provider:str,appointment_id:int,token:str,share_title:bool=False,duration_minutes:int=60)->str:
    if provider not in SUPPORTED:raise CalendarSyncError('Nieznany kalendarz')
    row=con.execute('SELECT a.*,c.title case_title FROM case_appointments a JOIN cases c ON c.id=a.case_id WHERE a.id=?',(appointment_id,)).fetchone()
    if not row:raise CalendarSyncError('Nie znaleziono terminu kancelarii')
    date_str=str(row['appointment_date']);time_str=str(row['appointment_time'] or '09:00')
    try:
        start=datetime.fromisoformat(date_str+'T'+time_str)
        if start.tzinfo is not None:raise ValueError()
    except ValueError as exc:raise CalendarSyncError('Nieprawidłowy termin lokalny') from exc
    if not 1<=duration_minutes<=1440:raise CalendarSyncError('Czas wydarzenia musi wynosić 1–1440 minut')
    end=start+timedelta(minutes=duration_minutes)
    title=str(row['title'])[:250] if share_title else 'Termin kancelarii'
    existing=con.execute('SELECT external_id,etag FROM dev3_calendar_links WHERE provider=? AND appointment_id=?',(provider,appointment_id)).fetchone()
    if provider=='google':
        endpoint=_google_endpoint()
        body={'summary':title,'start':{'dateTime':start.isoformat(),'timeZone':'Europe/Warsaw'},
              'end':{'dateTime':end.isoformat(),'timeZone':'Europe/Warsaw'}}
    else:
        endpoint=_outlook_endpoint()
        body={'subject':title,'start':{'dateTime':start.isoformat(),'timeZone':'Central European Standard Time'},
              'end':{'dateTime':end.isoformat(),'timeZone':'Central European Standard Time'}}
    if existing:
        dest=endpoint+'/'+urllib.parse.quote(existing[0],safe='')
        prior_etag=existing[1]
        if not prior_etag:
            current=_api(dest,token)
            prior_etag=str(current.get('etag') or current.get('@odata.etag') or '')
            if not prior_etag:
                raise CalendarSyncError('Nie można potwierdzić wersji wydarzenia. Aktualizacja zablokowana.')
        result=_api(dest,token,method='PATCH',body=body,etag=prior_etag)
        external=existing[0]
    else:
        # An idempotency token must be durable BEFORE a remote API request.
        intent=con.execute('SELECT request_id FROM dev5_calendar_publish_intents WHERE provider=? AND appointment_id=?',
                           (provider,appointment_id)).fetchone()
        newly_created=not bool(intent)
        if newly_created:
            con.execute('INSERT OR IGNORE INTO dev5_calendar_publish_intents(provider,appointment_id,request_id) VALUES(?,?,?)',
                        (provider,appointment_id,secrets.token_hex(16)))
            con.commit()
        intent=con.execute('SELECT request_id FROM dev5_calendar_publish_intents WHERE provider=? AND appointment_id=?',
                           (provider,appointment_id)).fetchone()
        request_id=str(intent[0])
        if provider=='google':
            body['id']=request_id
            body['extendedProperties']={'private':{'rkPublishIntent':request_id}}
            found=None
            if not newly_created:
                try:
                    found=_api(endpoint+'/'+urllib.parse.quote(request_id,safe=''),token)
                except CalendarSyncError as exc:
                    if 'HTTP 404' not in str(exc):raise
            if found:
                if ((found.get('extendedProperties') or {}).get('private') or {}).get('rkPublishIntent')!=request_id:
                    raise CalendarSyncError('Zdalny identyfikator jest zajęty przez inne wydarzenie')
                result=found
            else:
                try:
                    result=_api(endpoint,token,method='POST',body=body)
                except CalendarSyncError as exc:
                    if 'HTTP 409' not in str(exc):raise
                    result=_api(endpoint+'/'+urllib.parse.quote(request_id,safe=''),token)
                    if ((result.get('extendedProperties') or {}).get('private') or {}).get('rkPublishIntent')!=request_id:
                        raise CalendarSyncError('Konflikt identyfikatora wydarzenia')
        else:
            # Microsoft Graph transactionId identifies repeated creation attempts.
            body['transactionId']=request_id
            result=_api(endpoint,token,method='POST',body=body)
        external=str(result.get('id') or '')
        if not external:raise CalendarSyncError('API nie zwróciło identyfikatora wydarzenia')
    etag=str(result.get('etag') or result.get('@odata.etag') or '')
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
    record_published(con,provider,external,title,start.strftime('%Y-%m-%dT%H:%M'),end.strftime('%Y-%m-%dT%H:%M'))
    return external


def accept_proposal(con,pending_id:int,case_id:int,user_id:int) -> int:
    p=con.execute("SELECT * FROM dev3_calendar_pending WHERE id=? AND status='pending'",(pending_id,)).fetchone()
    if not p:raise ValueError('Brak aktywnej propozycji kalendarza')
    if not con.execute('SELECT 1 FROM cases WHERE id=?',(case_id,)).fetchone():raise ValueError('Nieznana sprawa')
    stamp=str(p['start_at'])
    # Graph returns UTC by default; Google returns RFC3339 with offset. Convert
    # deliberately, not by slicing a UTC timestamp and calling it local time.
    try:
        if 'T' not in stamp:
            day=date.fromisoformat(stamp).isoformat();clock=''
        else:
            dt=datetime.fromisoformat(stamp.replace('Z','+00:00'))
            if dt.tzinfo is None:
                if p['provider']=='outlook':dt=dt.replace(tzinfo=timezone.utc)
                else:raise ValueError('Wydarzenie nie zawiera strefy czasowej')
            dt=dt.astimezone(ZoneInfo('Europe/Warsaw'))
            day=dt.date().isoformat();clock=dt.strftime('%H:%M')
    except Exception as exc:
        raise ValueError('Nie można ustalić strefy czasowej. Zweryfikuj wydarzenie ręcznie.') from exc
    cur=con.execute('''INSERT INTO case_appointments(case_id,title,appointment_date,appointment_time,kind,notes,created_by,updated_by)
       VALUES(?,?,?,?,'Termin z kalendarza',?,?,?)''',(case_id,p['title'][:250],day,clock,'Zaimportowano po potwierdzeniu przez użytkownika',str(user_id),str(user_id)))
    con.execute("UPDATE dev3_calendar_pending SET status='accepted' WHERE id=?",(pending_id,))
    con.execute('INSERT INTO dev3_calendar_links(provider,appointment_id,external_id) VALUES(?,?,?)',(p['provider'],cur.lastrowid,p['external_id']))
    return cur.lastrowid
