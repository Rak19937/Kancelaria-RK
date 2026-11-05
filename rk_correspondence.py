# -*- coding: utf-8 -*-
"""RK KANCELARIA 0.3.5-dev1 — lokalny rejestr korespondencji i monity.

Wiadomości i dokumenty pozostają w lokalnej bazie. Nie ma wysyłania poczty,
portali sądowych ani wyliczania terminów prawnych. Daty oczekiwanej odpowiedzi
są wyłącznie datami kontrolnymi wpisanymi przez użytkownika.
"""
from __future__ import annotations

import html
import re
import sys
from datetime import date

CHANNELS = {
    'email': 'E-mail', 'postal': 'Poczta tradycyjna',
    'e-doreczenia': 'e-Doręczenia', 'portal': 'Portal Informacyjny',
    'epu': 'EPU', 'hand': 'Osobiście / biuro podawcze',
    'other': 'Inny kanał',
}
STATUSES = {
    'outgoing': {'prepared': 'Przygotowane', 'sent': 'Wysłane',
                 'delivered': 'Doręczone', 'answered': 'Otrzymano odpowiedź',
                 'closed': 'Zamknięte'},
    'incoming': {'received': 'Odebrane', 'handled': 'Obsłużone',
                 'closed': 'Zamknięte'},
}


def esc(value):
    return html.escape(str(value if value is not None else ''), quote=True)


def iso_date(value):
    s = str(value or '').strip()
    if not s:
        return ''
    try:
        d = date.fromisoformat(s)
        if d.isoformat() != s:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('Nieprawidłowa data. Wymagany format RRRR-MM-DD.')
    return s


def needs_followup(row, today=None, reply_count=0):
    """Wyłącznie sugestia organizacyjna z daty ręcznie wpisanej przez użytkownika."""
    today = today or date.today()
    try:
        return (row['direction'] == 'outgoing'
                and int(row['response_expected'] or 0) == 1
                and bool(row['expected_reply_on'])
                and date.fromisoformat(row['expected_reply_on']) < today
                and row['status'] not in ('answered', 'closed')
                and not reply_count)
    except (KeyError, ValueError, TypeError, IndexError):
        return False


def ensure_correspondence_schema(con):
    """Addytywna i idempotentna migracja; brak migracji danych użytkownika."""
    con.executescript('''
    CREATE TABLE IF NOT EXISTS correspondence_records (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
       direction TEXT NOT NULL CHECK(direction IN ('outgoing','incoming')),
       status TEXT NOT NULL DEFAULT 'prepared',
       channel TEXT NOT NULL DEFAULT 'other',
       subject TEXT NOT NULL,
       counterparty TEXT NOT NULL DEFAULT '',
       reference_number TEXT NOT NULL DEFAULT '',
       sent_on TEXT NOT NULL DEFAULT '',
       delivered_on TEXT NOT NULL DEFAULT '',
       received_on TEXT NOT NULL DEFAULT '',
       answered_on TEXT NOT NULL DEFAULT '',
       response_expected INTEGER NOT NULL DEFAULT 0,
       expected_reply_on TEXT NOT NULL DEFAULT '',
       document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
       draft_id INTEGER REFERENCES writing_projects(id) ON DELETE SET NULL,
       dispatch_receipt_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
       delivery_receipt_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
       reply_to_id INTEGER REFERENCES correspondence_records(id) ON DELETE SET NULL,
       followup_task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
       notes TEXT NOT NULL DEFAULT '',
       created_by TEXT NOT NULL DEFAULT '',
       updated_by TEXT NOT NULL DEFAULT '',
       created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
       updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_corr_case ON correspondence_records(case_id,id DESC);
    CREATE INDEX IF NOT EXISTS idx_corr_due ON correspondence_records(response_expected,expected_reply_on);
    CREATE INDEX IF NOT EXISTS idx_corr_reply ON correspondence_records(reply_to_id);
    CREATE TABLE IF NOT EXISTS correspondence_events (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       correspondence_id INTEGER NOT NULL REFERENCES correspondence_records(id) ON DELETE CASCADE,
       action TEXT NOT NULL,
       details TEXT NOT NULL DEFAULT '',
       actor TEXT NOT NULL DEFAULT '',
       occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_corr_events ON correspondence_events(correspondence_id,id DESC);
    ''')


def _event(con, record_id, action, details, actor):
    con.execute('INSERT INTO correspondence_events(correspondence_id,action,details,actor) VALUES(?,?,?,?)',
                (record_id, action, str(details or '')[:1600], str(actor or '')[:120]))


def _has_reply(con, record_id):
    return bool(con.execute("SELECT 1 FROM correspondence_records WHERE reply_to_id=? AND direction='incoming' LIMIT 1",
                            (record_id,)).fetchone())


def _belongs_to_case(con, case_id, document_id):
    if not document_id:
        return True
    return bool(con.execute('''SELECT 1 FROM documents d WHERE d.id=? AND
        (d.case_id=? OR EXISTS(SELECT 1 FROM document_case_links l
        WHERE l.document_id=d.id AND l.case_id=?))''',
        (document_id, case_id, case_id)).fetchone())


def _draft_belongs_to_case(con, case_id, draft_id):
    if not draft_id:
        return True
    return bool(con.execute('SELECT 1 FROM writing_projects WHERE id=? AND case_id=?',
                            (draft_id, case_id)).fetchone())


def _integer(value, label):
    try:
        n = int(value or 0)
        if n < 0:
            raise ValueError()
        return n
    except (ValueError, TypeError):
        raise ValueError('Nieprawidłowy identyfikator: ' + label)


def _status_label(row):
    return STATUSES.get(row['direction'], {}).get(row['status'], row['status'])


class CorrespondenceMixin:
    def _corr_app(self):
        return sys.modules[type(self).__module__]

    def _corr_error(self, message, code=400, target='/correspondence'):
        a = self._corr_app()
        body = ("<div class='card'><h1>Nie udało się zapisać korespondencji</h1>"
                f'<p>{esc(message)}</p><a class="btn" href="{esc(target)}">Wróć</a></div>')
        return self.send_html(a.layout('Korespondencja', body, 'correspondence'), code)

    def correspondence_page(self, qs=None):
        a = self._corr_app()
        qs = qs or {}
        try:
            selected = _integer((qs.get('case_id') or ['0'])[0], 'sprawa')
        except ValueError:
            selected = 0
        direction = (qs.get('direction') or [''])[0]
        query = (qs.get('q') or [''])[0].strip()[:120]
        with a.db() as con:
            cases = con.execute('SELECT id,title,signature,internal_signature FROM cases ORDER BY title LIMIT 1500').fetchall()
            sql = '''SELECT r.*, c.title case_title, c.signature, c.internal_signature,
                (SELECT COUNT(*) FROM correspondence_records rr WHERE rr.reply_to_id=r.id AND rr.direction='incoming') replies
                FROM correspondence_records r JOIN cases c ON c.id=r.case_id WHERE 1=1'''
            params = []
            if selected:
                sql += ' AND r.case_id=?'; params.append(selected)
            if direction in ('outgoing', 'incoming'):
                sql += ' AND r.direction=?'; params.append(direction)
            if query:
                sql += ' AND (r.subject LIKE ? OR r.counterparty LIKE ? OR r.reference_number LIKE ?)'
                params.extend(['%'+query+'%']*3)
            sql += ' ORDER BY r.id DESC LIMIT 300'
            rows = con.execute(sql, params).fetchall()
        options = "<option value=''>Wszystkie sprawy</option>" + ''.join(
            f"<option value='{c['id']}' {'selected' if c['id']==selected else ''}>"
            f"{esc(c['signature'] or c['internal_signature'] or c['title'])}</option>" for c in cases)
        cards = []
        late = 0
        for r in rows:
            overdue = needs_followup(r, reply_count=r['replies'])
            if overdue:
                late += 1
            direction_label = 'Wychodzące' if r['direction']=='outgoing' else 'Przychodzące'
            extra = (' <span class="pill" style="color:#a23b2b">Sugerowany monit</span>' if overdue else '')
            if r['response_expected'] and r['expected_reply_on']:
                extra += f" <span class='small muted'>Odpowiedź kontrolna: {esc(r['expected_reply_on'])}</span>"
            cards.append(
                "<tr>"
                f"<td><a href='/correspondence/{r['id']}'><b>{esc(r['subject'])}</b></a>"
                f"<div class='small muted'>{esc(r['counterparty'])} · {esc(r['reference_number'])}</div>{extra}</td>"
                f"<td>{esc(r['signature'] or r['internal_signature'] or r['case_title'])}</td>"
                f"<td>{direction_label} · {esc(CHANNELS.get(r['channel'],r['channel']))}</td>"
                f"<td>{esc(_status_label(r))}</td>"
                f"<td>{esc(r['sent_on'] or r['received_on'] or '—')}</td>"
                f"<td><a class='btn small' href='/correspondence/{r['id']}'>Otwórz</a></td></tr>")
        body = ("<div class='topbar'><div><h1>Obieg korespondencji</h1>"
                "<div class='sub'>Nadania, doręczenia, odpowiedzi, dowody i monity — bez automatycznego wysyłania.</div>"
                "</div><a class='btn primary' href='/correspondence/new'>+ Zarejestruj pismo</a></div>"
                f"<div class='card'><b>Widoczne wpisy wymagające kontroli: {late}</b> "
                "<span class='small muted'>Po przekroczeniu ręcznie wpisanej daty oczekiwanej odpowiedzi program proponuje sprawdzenie sprawy, a nie automatyczny monit.</span></div>"
                "<div class='card'><form method='get' action='/correspondence' class='searchbar'>"
                f"<input name='q' placeholder='Szukaj po temacie, adresacie lub znaku' value='{esc(query)}'>"
                f"<select name='case_id'>{options}</select>"
                "<select name='direction'><option value=''>Wszystkie</option>"
                f"<option value='outgoing' {'selected' if direction=='outgoing' else ''}>Wychodzące</option>"
                f"<option value='incoming' {'selected' if direction=='incoming' else ''}>Przychodzące</option>"
                "</select><button class='btn'>Filtruj</button></form></div>"
                f"<div class='card'><div class='table-scroll'><table><tr><th>Dokument</th><th>Sprawa</th>"
                f"<th>Rodzaj / kanał</th><th>Status</th><th>Data</th><th></th></tr>{''.join(cards) or '<tr><td colspan=6>Brak wpisów.</td></tr>'}</table></div></div>"
                "<div class='notice'>Data oczekiwanej odpowiedzi jest jedynie terminem organizacyjnym wpisanym przez użytkownika. "
                "Nie oznacza terminu wynikającego z przepisów prawa.</div>")
        return self.send_html(a.layout('Obieg korespondencji', body, 'correspondence'))

    def correspondence_form(self, qs=None, record_id=None):
        a = self._corr_app()
        qs = qs or {}
        with a.db() as con:
            old = con.execute('SELECT * FROM correspondence_records WHERE id=?', (record_id,)).fetchone() if record_id else None
            if record_id and not old:
                return self.send_error(404)
            cases = con.execute('SELECT id,title,signature,internal_signature FROM cases ORDER BY title LIMIT 1500').fetchall()
            initial_document = _integer((qs.get('document_id') or ['0'])[0], 'dokument') if not old else 0
            initial_draft = _integer((qs.get('draft_id') or ['0'])[0], 'projekt') if not old else 0
            cid = old['case_id'] if old else _integer((qs.get('case_id') or ['0'])[0], 'sprawa')
            source = None
            if not old and initial_document:
                source = con.execute('SELECT case_id,title FROM documents WHERE id=?',(initial_document,)).fetchone()
                if source and not cid: cid=source['case_id']
            if not old and initial_draft:
                source = con.execute('SELECT case_id,title FROM writing_projects WHERE id=?',(initial_draft,)).fetchone()
                if source and not cid: cid=source['case_id'] or 0
            c = con.execute('SELECT * FROM cases WHERE id=?', (cid,)).fetchone() if cid else None
            docs = con.execute('''SELECT d.id,d.title,d.original_name FROM documents d WHERE
                    d.case_id=? OR EXISTS(SELECT 1 FROM document_case_links l WHERE l.document_id=d.id AND l.case_id=?)
                    ORDER BY d.id DESC LIMIT 500''',(cid,cid)).fetchall() if c else []
            drafts = con.execute('SELECT id,title FROM writing_projects WHERE case_id=? ORDER BY id DESC LIMIT 200',(cid,)).fetchall() if c else []
            parents = con.execute('''SELECT id,subject FROM correspondence_records
                          WHERE case_id=? AND direction='outgoing' AND id<>? ORDER BY id DESC LIMIT 200''',
                          (cid,record_id or 0)).fetchall() if c else []
        opts = "<option value=''>Wybierz sprawę</option>" + ''.join(
            f"<option value='{c['id']}' {'selected' if c['id']==cid else ''}>{esc(c['signature'] or c['internal_signature'] or c['title'])}</option>"
            for c in cases)
        header = ('Edytuj wpis korespondencji' if old else 'Rejestruj korespondencję')
        if not c:
            body = (f"<div class='topbar'><h1>{header}</h1></div><div class='card'>"
                    "<p>Wybierz sprawę przed dodaniem korespondencji.</p>"
                    f"<form method='get' action='/correspondence/new'><select name='case_id' required>{opts}</select>"
                    "<button class='btn primary'>Dalej</button></form></div>")
            return self.send_html(a.layout(header,body,'correspondence'))
        def value(key, default=''):
            return old[key] if old else default
        def select(name, options, selected, label):
            # Zmiana kierunku ustawia poprawny, domyślny status; reszta pozostaje edytowalna.
            onchange = (' onchange="var s=this.form.elements.status; '
                        'if(s){s.value=this.value===\'incoming\'?\'received\':\'prepared\';}"'
                        if name == 'direction' else '')
            return (f"<div><label>{esc(label)}</label><select name='{name}'{onchange}>"
                    + ''.join(f"<option value='{esc(key)}' {'selected' if key==selected else ''}>{esc(label)}</option>"
                              for key,label in options.items()) + '</select></div>')
        doc_opts = {'0':'— bez powiązania —', **{str(d['id']):f"{d['title']} ({d['original_name'] or 'bez pliku'})" for d in docs}}
        draft_opts = {'0':'— bez powiązania —', **{str(d['id']):d['title'] for d in drafts}}
        parent_opts = {'0':'— bez powiązania —', **{str(d['id']):d['subject'] for d in parents}}
        direction = value('direction', (qs.get('direction') or ['outgoing'])[0])
        if direction not in STATUSES: direction='outgoing'
        status = value('status', 'prepared' if direction=='outgoing' else 'received')
        if status not in STATUSES[direction]: status=next(iter(STATUSES[direction]))
        initial_subject = source['title'] if source else ''
        selected_doc = value('document_id',initial_document) or 0
        selected_draft = value('draft_id',initial_draft) or 0
        parent_id = value('reply_to_id',_integer((qs.get('reply_to_id') or ['0'])[0], 'odpowiedź')) or 0
        # Edycja nie przenosi automatycznie korespondencji do innej sprawy.
        action = f"/correspondence/{record_id}/update" if old else '/correspondence/create'
        chosen_case = esc(c['signature'] or c['internal_signature'] or c['title'])
        body = [f"<div class='topbar'><div><h1>{header}</h1><div class='sub'>Sprawa: {chosen_case}</div></div>"
                f"<a class='btn' href='/correspondence/{record_id}'>{'Wróć'}</a></div>" if old else
                f"<div class='topbar'><h1>{header}</h1><a class='btn' href='/correspondence'>Wróć</a></div>"]
        body.append(f"<div class='card'><form method='post' action='{action}' class='form-grid'>"
                    f"<input type='hidden' name='case_id' value='{cid}'>"
                    f"<div class='full'><label>Sprawa</label><b>{chosen_case}</b></div>")
        body.append(select('direction',{'outgoing':'Wychodzące','incoming':'Przychodzące'},direction,'Kierunek'))
        statuses = dict(STATUSES['outgoing']); statuses.update(STATUSES['incoming'])
        body.append(select('status',statuses,status,'Status (ręcznie potwierdzony)'))
        body.append(select('channel',CHANNELS,value('channel','other'),'Kanał'))
        def field(name,label,default='',kind='text',full=False):
            val = value(name,default)
            return (f"<div class='{'full' if full else ''}'><label>{esc(label)}</label>"
                    f"<input type='{kind}' name='{name}' value='{esc(val)}'"
                    + (' maxlength="500"' if name=='subject' else '') + '></div>')
        body.append(field('subject','Temat / nazwa pisma *',initial_subject,full=True))
        body.append(field('counterparty','Adresat / nadawca'))
        body.append(field('reference_number','Znak pisma / nr przesyłki'))
        body.append(field('sent_on','Data wysłania','',kind='date'))
        body.append(field('delivered_on','Data doręczenia','',kind='date'))
        body.append(field('received_on','Data otrzymania','',kind='date'))
        body.append(field('answered_on','Data otrzymania odpowiedzi','',kind='date'))
        checked='checked' if value('response_expected',0) else ''
        body.append(f"<div class='full'><label><input type='checkbox' name='response_expected' value='1' style='width:auto' {checked}> Oczekujemy odpowiedzi</label></div>")
        body.append(field('expected_reply_on','Data kontrolna oczekiwanej odpowiedzi (wpisana ręcznie)','',kind='date',full=True))
        body.append(select('document_id',doc_opts,str(selected_doc),'Powiązany dokument'))
        body.append(select('draft_id',draft_opts,str(selected_draft),'Powiązany projekt pisma'))
        body.append(select('dispatch_receipt_id',doc_opts,str(value('dispatch_receipt_id',0) or 0),'Dowód nadania (dokument)'))
        body.append(select('delivery_receipt_id',doc_opts,str(value('delivery_receipt_id',0) or 0),'Dowód doręczenia (dokument)'))
        body.append(select('reply_to_id',parent_opts,str(parent_id),'Odpowiedź na korespondencję (dla przychodzących)'))
        body.append(f"<div class='full'><label>Notatki</label><textarea name='notes' rows='5'>{esc(value('notes',''))}</textarea></div>")
        body.append("<div class='full small muted'>Zapis jedynie rejestruje czynność. Nie wysyła pisma, "
                    "nie uznaje przesyłki za doręczoną bez ręcznej zmiany statusu i nie wylicza terminów ustawowych.</div>"
                    "<div class='full'><button class='btn primary' type='submit'>Zapisz korespondencję</button></div></form></div>")
        return self.send_html(a.layout(header,''.join(body),'correspondence'))

    def correspondence_save(self, fields, record_id=None):
        a = self._corr_app()
        fields = fields or {}
        try:
            cid = _integer(fields.get('case_id'), 'sprawa')
            if not cid:
                raise ValueError('Przypisz korespondencję do sprawy.')
            direction = str(fields.get('direction','outgoing'))
            if direction not in STATUSES:
                raise ValueError('Nieprawidłowy kierunek korespondencji.')
            status = str(fields.get('status') or ('prepared' if direction=='outgoing' else 'received'))
            if status not in STATUSES[direction]:
                raise ValueError('Status nie pasuje do wybranego kierunku pisma.')
            channel = str(fields.get('channel') or 'other')
            if channel not in CHANNELS:
                raise ValueError('Nieprawidłowy kanał nadania.')
            subject = str(fields.get('subject') or '').strip()[:500]
            if not subject:
                raise ValueError('Podaj temat pisma.')
            values = {'case_id':cid,'direction':direction,'status':status,'channel':channel,
                      'subject':subject,'counterparty':str(fields.get('counterparty') or '').strip()[:500],
                      'reference_number':str(fields.get('reference_number') or '').strip()[:180],
                      'notes':str(fields.get('notes') or '').strip()[:12000]}
            for key in ('sent_on','delivered_on','received_on','answered_on','expected_reply_on'):
                values[key]=iso_date(fields.get(key,''))
            values['response_expected'] = int(fields.get('response_expected')=='1' or bool(values['expected_reply_on']))
            if direction=='outgoing':
                if status in ('sent','delivered','answered') and not values['sent_on']:
                    raise ValueError('Dla wskazanego statusu wychodzącego wpisz datę wysłania.')
                if status=='delivered' and not values['delivered_on']:
                    raise ValueError('Dla statusu doręczonego wpisz datę doręczenia.')
                if status=='answered' and not values['answered_on']:
                    raise ValueError('Dla statusu odpowiedzi wpisz datę jej otrzymania.')
                if values['delivered_on'] and values['sent_on'] and values['delivered_on']<values['sent_on']:
                    raise ValueError('Data doręczenia nie może poprzedzać daty wysłania.')
                if values['answered_on'] and values['sent_on'] and values['answered_on']<values['sent_on']:
                    raise ValueError('Odpowiedź nie może poprzedzać wysyłki.')
            for field in ('document_id','draft_id','dispatch_receipt_id','delivery_receipt_id','reply_to_id'):
                values[field] = _integer(fields.get(field), field) or None
            if values['reply_to_id'] and direction!='incoming':
                raise ValueError('Powiązanie odpowiedzi jest dostępne tylko dla pisma przychodzącego.')
            author = self.current_author(fields)
        except ValueError as exc:
            return self._corr_error(str(exc))
        with a.db() as con:
            old = con.execute('SELECT * FROM correspondence_records WHERE id=?', (record_id,)).fetchone() if record_id else None
            if record_id and not old:
                return self.send_error(404)
            if old and cid!=old['case_id']:
                return self._corr_error('Nie można zmienić sprawy przy edycji wpisu.', 409)
            if not con.execute('SELECT 1 FROM cases WHERE id=?',(cid,)).fetchone():
                return self._corr_error('Nie znaleziono sprawy.', 404)
            for field in ('document_id','dispatch_receipt_id','delivery_receipt_id'):
                if not _belongs_to_case(con,cid,values[field]):
                    return self._corr_error('Dokument lub potwierdzenie nie jest powiązane z wybraną sprawą.', 409)
            if not _draft_belongs_to_case(con,cid,values['draft_id']):
                return self._corr_error('Projekt pisma nie należy do wybranej sprawy.', 409)
            if values['reply_to_id']:
                if values['reply_to_id']==record_id:
                    return self._corr_error('Pismo nie może stanowić odpowiedzi na samo siebie.')
                parent = con.execute("SELECT 1 FROM correspondence_records WHERE id=? AND case_id=? AND direction='outgoing'",
                                     (values['reply_to_id'],cid)).fetchone()
                if not parent:
                    return self._corr_error('Odpowiedź musi dotyczyć pisma wychodzącego z tej samej sprawy.',409)
            cols = ('case_id','direction','status','channel','subject','counterparty','reference_number',
                    'sent_on','delivered_on','received_on','answered_on','response_expected',
                    'expected_reply_on','document_id','draft_id','dispatch_receipt_id',
                    'delivery_receipt_id','reply_to_id','notes')
            if old:
                changed=[f'{key}: {str(old[key])[:90]} → {str(values[key])[:90]}'
                         for key in cols if (old[key] or '') != (values[key] or '')]
                if changed:
                    con.execute('UPDATE correspondence_records SET '+','.join(f'{x}=?' for x in cols)+
                                ',updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                                [values[x] for x in cols]+[author,record_id])
                    _event(con,record_id,'Zmiana wpisu','; '.join(changed)[:1600],author)
                    a.audit(con,cid,'correspondence',record_id,'Zmieniono korespondencję',
                            '; '.join(changed)[:1800],author)
                new_id=record_id
            else:
                cur=con.execute('INSERT INTO correspondence_records ('+','.join(cols)+',created_by,updated_by) VALUES ('+
                                ','.join(['?']*(len(cols)+2))+')',
                                [values[x] for x in cols]+[author,author])
                new_id=cur.lastrowid
                _event(con,new_id,'Dodano korespondencję',subject,author)
                a.audit(con,cid,'correspondence',new_id,'Zarejestrowano korespondencję',
                        f'{subject} · {direction} · {channel}',author)
        return self.redirect(f'/correspondence/{new_id}')

    def correspondence_detail(self, record_id):
        a = self._corr_app()
        with a.db() as con:
            r = con.execute('''SELECT r.*,c.title case_title,c.signature,c.internal_signature
                FROM correspondence_records r JOIN cases c ON c.id=r.case_id WHERE r.id=?''',(record_id,)).fetchone()
            if not r:
                return self.send_error(404)
            events=con.execute('SELECT * FROM correspondence_events WHERE correspondence_id=? ORDER BY id DESC LIMIT 80',(record_id,)).fetchall()
            replies=con.execute("SELECT id,subject,received_on FROM correspondence_records WHERE reply_to_id=? AND direction='incoming' ORDER BY id DESC",(record_id,)).fetchall()
            task=con.execute('SELECT id,title,status,due_date FROM tasks WHERE id=?',(r['followup_task_id'],)).fetchone() if r['followup_task_id'] else None
            docs={d['id']:d for d in con.execute('SELECT id,title FROM documents WHERE id IN (?,?,?)',
                   (r['document_id'],r['dispatch_receipt_id'],r['delivery_receipt_id'])).fetchall()}
            draft=con.execute('SELECT id,title FROM writing_projects WHERE id=?',(r['draft_id'],)).fetchone() if r['draft_id'] else None
        overdue=needs_followup(r,reply_count=len(replies))
        def linkdoc(key):
            d=docs.get(r[key])
            return (f"<a href='/document/{d['id']}/open'>{esc(d['title'])}</a>" if d else '—')
        def item(label, value):
            return f'<tr><th>{esc(label)}</th><td>{value}</td></tr>'
        rows=[item('Sprawa',f"<a href='/case/{r['case_id']}'>{esc(r['signature'] or r['internal_signature'] or r['case_title'])}</a>"),
              item('Kierunek','Wychodzące' if r['direction']=='outgoing' else 'Przychodzące'),
              item('Status',esc(_status_label(r))),item('Kanał',esc(CHANNELS.get(r['channel'],r['channel']))),
              item('Adresat / nadawca',esc(r['counterparty'] or '—')),
              item('Znak / nr przesyłki',esc(r['reference_number'] or '—')),
              item('Data wysłania',esc(r['sent_on'] or '—')),
              item('Data doręczenia',esc(r['delivered_on'] or '—')),
              item('Data wpływu',esc(r['received_on'] or '—')),
              item('Data odpowiedzi',esc(r['answered_on'] or '—')),
              item('Oczekiwana odpowiedź','Tak' if r['response_expected'] else 'Nie'),
              item('Data kontrolna',esc(r['expected_reply_on'] or '—')),
              item('Powiązany dokument',linkdoc('document_id')),
              item('Projekt pisma',f"<a href='/draft/{draft['id']}'>{esc(draft['title'])}</a>" if draft else '—'),
              item('Dowód nadania',linkdoc('dispatch_receipt_id')),
              item('Dowód doręczenia',linkdoc('delivery_receipt_id')),
              item('Notatki',f'<div style="white-space:pre-wrap">{esc(r["notes"] or "—")}</div>')]
        replies_html=''.join(f"<li><a href='/correspondence/{x['id']}'>{esc(x['subject'])}</a> · {esc(x['received_on'] or 'bez daty')}</li>" for x in replies)
        if r['reply_to_id']:
            rows.append(item('Odpowiedź na',f"<a href='/correspondence/{r['reply_to_id']}'>Pismo #{r['reply_to_id']}</a>"))
        history=''.join(f"<tr><td>{esc(x['occurred_at'])}</td><td>{esc(x['action'])}</td><td>{esc(x['actor'])}</td><td>{esc(x['details'])}</td></tr>" for x in events)
        suggestion = ''
        can_follow=(r['direction']=='outgoing' and r['response_expected'] and r['status'] not in ('answered','closed') and not replies)
        if overdue:
            suggestion=("<div class='notice'><b>Sugerowany monit:</b> minęła ręcznie wprowadzona data oczekiwanej odpowiedzi. "
                        "Sprawdź historię doręczeń i ewentualne odpowiedzi przed utworzeniem zadania.</div>")
        if can_follow:
            current = (f"<p>Istniejące zadanie: <a href='/task/{task['id']}/edit'>{esc(task['title'])}</a> · {esc(task['status'])}</p>" if task else '')
            disabled=(task is not None and task['status']=='open')
            suggestion += (f"<div class='card'><h2>Monit do zatwierdzenia</h2>{current}"
                "<p class='small muted'>Utworzenie zadania nie wysyła żadnego pisma. Datę działania wskazujesz ręcznie.</p>"
                f"<form method='post' action='/correspondence/{record_id}/followup' class='form-grid'>"
                f"<div class='full'><label>Tytuł zadania</label><input name='title' value='{esc('Zweryfikować odpowiedź i rozważyć monit: '+r['subject'][:160])}' required></div>"
                "<div><label>Data zadania (opcjonalnie, ręcznie)</label><input type='date' name='due_date'></div>"
                "<div class='full'><label><input type='checkbox' name='confirmed' value='yes' required style='width:auto'>"
                "Sprawdziłem doręczenie i brak odpowiedzi; chcę utworzyć zadanie do dalszej oceny.</label></div>"
                f"<div class='full'><button class='btn primary' {'disabled' if disabled else ''}>Utwórz zadanie monitowe</button></div>"
                "</form></div>")
        reply_button=(f"<a class='btn primary' href='/correspondence/new?case_id={r['case_id']}&direction=incoming&reply_to_id={record_id}'>Zarejestruj odpowiedź</a>"
                      if r['direction']=='outgoing' else '')
        body=(f"<div class='topbar'><div><h1>{esc(r['subject'])}</h1><div class='sub'>Obieg korespondencji · #{record_id}</div></div>"
              f"<div><a class='btn' href='/correspondence'>Rejestr</a> "
              f"<a class='btn' href='/correspondence/{record_id}/edit'>Edytuj</a> {reply_button}</div></div>"
              f"{suggestion}<div class='card'><h2>Metryka korespondencji</h2><table>{''.join(rows)}</table></div>"
              f"<div class='card'><h2>Odpowiedzi powiązane</h2><ul>{replies_html or '<li>Brak powiązanych odpowiedzi.</li>'}</ul></div>"
              f"<div class='card'><h2>Historia zmian</h2><div class='table-scroll'><table>"
              f"<tr><th>Data</th><th>Operacja</th><th>Osoba</th><th>Informacja</th></tr>"
              f"{history or '<tr><td colspan=4>Brak historii.</td></tr>'}</table></div></div>"
              "<div class='small muted'>Rejestr jest narzędziem organizacyjnym. Nie potwierdza skutecznego doręczenia ani terminów procesowych bez dokumentów źródłowych.</div>")
        return self.send_html(a.layout('Korespondencja',body,'correspondence'))

    def correspondence_followup(self, record_id, fields):
        a=self._corr_app()
        if fields.get('confirmed')!='yes':
            return self._corr_error('Potwierdź weryfikację przed utworzeniem zadania.',400,f'/correspondence/{record_id}')
        try:
            due=iso_date(fields.get('due_date'))
            title=str(fields.get('title') or '').strip()[:500]
            if not title:
                raise ValueError('Podaj tytuł zadania.')
        except ValueError as exc:
            return self._corr_error(str(exc),400,f'/correspondence/{record_id}')
        author=self.current_author(fields)
        with a.db() as con:
            r=con.execute('SELECT * FROM correspondence_records WHERE id=?',(record_id,)).fetchone()
            if not r:
                return self.send_error(404)
            if r['direction']!='outgoing' or not r['response_expected'] or r['status'] in ('answered','closed') or _has_reply(con,record_id):
                return self._corr_error('Brak aktualnej podstawy do proponowania monitu dla tej korespondencji.',409,f'/correspondence/{record_id}')
            if r['followup_task_id']:
                t=con.execute('SELECT status FROM tasks WHERE id=?',(r['followup_task_id'],)).fetchone()
                if t and t['status']=='open':
                    return self._corr_error('Istnieje już otwarte zadanie monitowe. Nie utworzono duplikatu.',409,f'/correspondence/{record_id}')
            notes=(f"Monit wyłącznie do ręcznej oceny. Źródło: korespondencja #{record_id}: {r['subject']}. "
                   f"Data oczekiwanej odpowiedzi (organizacyjna): {r['expected_reply_on'] or 'nie wpisano'}. "
                   'Potwierdź treść i skuteczność doręczenia przed podjęciem czynności.')
            cur=con.execute('''INSERT INTO tasks(case_id,title,due_date,status,priority,depends_on,notes,
                    task_type,created_by,updated_by) VALUES(?,?,?,'open','normal','',?,'Monit',?,?)''',
                    (r['case_id'],title,due,notes,author,author))
            tid=cur.lastrowid
            con.execute('UPDATE correspondence_records SET followup_task_id=?,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                        (tid,author,record_id))
            _event(con,record_id,'Zatwierdzono propozycję zadania monitowego',f'Zadanie #{tid}; termin: {due or "bez daty"}',author)
            a.audit(con,r['case_id'],'correspondence',record_id,'Zatwierdzono zadanie monitowe',
                    f'Zadanie #{tid}, ręczna data: {due or "brak"}',author)
            a.sync_task_alert(con,tid,author)
        return self.redirect(f'/correspondence/{record_id}')
