# -*- coding: utf-8 -*-
"""RK KANCELARIA 0.3.8-dev1 — nawigacja, zależności, dowody i chronologia.

Nie używa usług sieciowych i nie wydaje ocen prawnych. Zależności są jawnie
zatwierdzane przez człowieka; automatyczne sortowanie nie zmienia dat źródłowych.
"""
from __future__ import annotations

import html
import re
import sqlite3
from rk_ux import timeline_category
from rk_search_data import find_navigation_matches
import sys
from datetime import date
from urllib.parse import quote


def esc(value):
    return html.escape(str(value if value is not None else ''), quote=True)


def _app(handler):
    return sys.modules[type(handler).__module__]


def _table(con, name):
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def ensure_caseflow_schema(con):
    """Idempotentna migracja. Bez zmian dat, zadań, dowodów i dokumentów użytkownika."""
    con.executescript('''
        CREATE TABLE IF NOT EXISTS task_dependencies (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
          requirement_type TEXT NOT NULL CHECK(requirement_type IN ('task','document','sidecase')),
          reference_id INTEGER NOT NULL CHECK(reference_id > 0),
          note TEXT NOT NULL DEFAULT '',
          created_by TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(task_id, requirement_type, reference_id)
        );
        CREATE INDEX IF NOT EXISTS idx_task_dependencies_task ON task_dependencies(task_id,id);
        CREATE INDEX IF NOT EXISTS idx_task_dependencies_ref ON task_dependencies(requirement_type,reference_id);
        CREATE TABLE IF NOT EXISTS task_dependency_overrides (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
          unresolved_snapshot TEXT NOT NULL,
          reason TEXT NOT NULL,
          actor TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_dependency_overrides_task ON task_dependency_overrides(task_id,id);
    ''')


def _related_case_ids(con, cid):
    ids={int(cid)}
    if _table(con,'side_case_dependencies'):
        for r in con.execute('''SELECT parent_case_id,child_case_id FROM side_case_dependencies
                               WHERE parent_case_id=? OR child_case_id=?''',(cid,cid)):
            ids.add(int(r[0])); ids.add(int(r[1]))
    if _table(con,'case_relations'):
        for r in con.execute('''SELECT source_case_id,target_case_id FROM case_relations
                               WHERE source_case_id=? OR target_case_id=?''',(cid,cid)):
            ids.add(int(r[0])); ids.add(int(r[1]))
    return ids


def _requirement(con, kind, ref_id):
    """Zwraca (stan spełniony, etykieta, href, case_id); brak rekordu = niespełniona."""
    if kind=='task':
        r=con.execute('SELECT id,title,status,case_id FROM tasks WHERE id=?',(ref_id,)).fetchone()
        return (r['status']=='done',r['title'],f'/task/{ref_id}/edit',r['case_id']) if r else (False,'Usunięte zadanie', '',0)
    if kind=='document':
        r=con.execute('SELECT id,title,case_id FROM documents WHERE id=?',(ref_id,)).fetchone()
        # Istnienie dokumentu potwierdza powiązanie; nie gwarantuje jego ważności prawnej.
        return (True,r['title'],f'/document/{ref_id}/open',r['case_id']) if r else (False,'Usunięty dokument','',0)
    if kind=='sidecase':
        if not _table(con,'side_case_dependencies'):
            return (False,'Brak powiązania spraw', '',0)
        r=con.execute('''SELECT d.id,d.needed_item,d.status,d.parent_case_id,d.child_case_id,
                       c.title child_title FROM side_case_dependencies d
                       JOIN cases c ON c.id=d.child_case_id WHERE d.id=?''',(ref_id,)).fetchone()
        return (r['status'] in ('received','not_needed'),r['needed_item']+' · '+r['child_title'],
                f'/case/{r["parent_case_id"]}/sidecases',r['parent_case_id']) if r else (False,'Usunięta zależność spraw','',0)
    return False,'Nieznane powiązanie','',0


def dependency_rows(con, task_id):
    rows=con.execute('SELECT * FROM task_dependencies WHERE task_id=? ORDER BY id',(task_id,)).fetchall()
    return [{**dict(r),'resolved':_requirement(con,r['requirement_type'],r['reference_id'])[0],
             'label':_requirement(con,r['requirement_type'],r['reference_id'])[1],
             'href':_requirement(con,r['requirement_type'],r['reference_id'])[2]}
            for r in rows]



def dependency_blocking_counts(con, task_ids):
    """Jedno zapytanie dla listy zadań; bez pobierania każdej zależności osobno."""
    ids=sorted({int(i) for i in task_ids})
    if not ids:return {}
    result={}
    for offset in range(0,len(ids),400):
        subset=ids[offset:offset+400]
        marks=','.join('?' for _ in subset)
        rows=con.execute(f'''SELECT d.task_id,COUNT(*) unresolved FROM task_dependencies d
            WHERE d.task_id IN ({marks}) AND NOT (
                (d.requirement_type='task' AND EXISTS(SELECT 1 FROM tasks t
                  WHERE t.id=d.reference_id AND t.status='done')) OR
                (d.requirement_type='document' AND EXISTS(SELECT 1 FROM documents x
                  WHERE x.id=d.reference_id)) OR
                (d.requirement_type='sidecase' AND EXISTS(SELECT 1 FROM side_case_dependencies s
                  WHERE s.id=d.reference_id AND s.status IN ('received','not_needed')))
            ) GROUP BY d.task_id''',subset).fetchall()
        result.update({int(r['task_id']):int(r['unresolved']) for r in rows})
    return result

def unresolved_dependencies(con, task_id):
    return [x for x in dependency_rows(con,task_id) if not x['resolved']]


def _would_cycle(con, task_id, ref_id):
    """Nowa krawędź task -> ref jest cyklem, jeżeli ref już zależy od task."""
    if task_id==ref_id:return True
    queue=[ref_id];seen=set()
    while queue:
        current=queue.pop()
        if current==task_id:return True
        if current in seen:continue
        seen.add(current)
        if len(seen)>10000:raise ValueError('Zbyt wiele zależności do zweryfikowania.')
        queue.extend(r[0] for r in con.execute('''SELECT reference_id FROM task_dependencies
                         WHERE task_id=? AND requirement_type='task' ''',(current,)).fetchall())
    return False


def add_dependency(con, task_id, requirement_type, ref_id, note='', author=''):
    if requirement_type not in ('task','document','sidecase'):
        raise ValueError('Nieprawidłowy rodzaj zależności.')
    try:task_id=int(task_id);ref_id=int(ref_id)
    except (ValueError,TypeError):raise ValueError('Błędny identyfikator.')
    if ref_id<1:raise ValueError('Wybierz element, od którego zależy zadanie.')
    task=con.execute('SELECT id,case_id FROM tasks WHERE id=?',(task_id,)).fetchone()
    if not task:raise ValueError('Nie znaleziono zadania.')
    resolved,label,url,ref_case=_requirement(con,requirement_type,ref_id)
    if not url:raise ValueError('Wskazany element nie istnieje.')
    if int(ref_case) not in _related_case_ids(con,task['case_id']):
        raise ValueError('Można wiązać tylko elementy tej sprawy lub jawnie powiązanych spraw.')
    if requirement_type=='task' and _would_cycle(con,task_id,ref_id):
        raise ValueError('Zależność powodowałaby cykl między zadaniami.')
    if requirement_type=='document':
        # Współdzielony dokument może być jawnie przypisany do sprawy.
        doc=con.execute('SELECT case_id FROM documents WHERE id=?',(ref_id,)).fetchone()
        if not doc:raise ValueError('Nie znaleziono dokumentu.')
    con.execute('''INSERT OR IGNORE INTO task_dependencies
          (task_id,requirement_type,reference_id,note,created_by) VALUES(?,?,?,?,?)''',
          (task_id,requirement_type,ref_id,str(note or '').strip()[:1200],str(author or '')[:120]))


def _sort_date(value):
    value=str(value or '').strip()
    try:
        if len(value)==10 and date.fromisoformat(value).isoformat()==value:return value
    except ValueError:pass
    return ''


def chronology_items(con, case_id):
    """Oś chronologiczna: data merytoryczna; data wprowadzenia tylko jawny fallback."""
    cid=int(case_id);items=[]
    def add(when,typ,title,url,details='',source='',ident=0):
        dt=_sort_date(when)
        if not dt:return
        items.append({'date':dt,'kind':typ,'title':str(title or ''), 'url':url,
                      'description':str(details or ''),'source':source,'id':int(ident or 0)})
    for r in con.execute('SELECT id,title,due_date,status,task_type FROM tasks WHERE case_id=?',(cid,)):
        add(r['due_date'],r['task_type'] or 'Zadanie',r['title'],f'/task/{r["id"]}/edit',r['status'],'task',r['id'])
    for r in con.execute('SELECT id,title,event_date,event_type,description FROM events WHERE case_id=?',(cid,)):
        add(r['event_date'],r['event_type'] or 'Czynność',r['title'],f'/event/{r["id"]}/edit',r['description'],'event',r['id'])
    for r in con.execute('SELECT id,title,event_date,next_date,event_type,description FROM process_events WHERE case_id=?',(cid,)):
        add(r['event_date'],'Proces: '+str(r['event_type'] or ''),r['title'],f'/process-event/{r["id"]}/edit',r['description'],'process',r['id'])
        if r['next_date'] and r['next_date']!=r['event_date']:
            add(r['next_date'],'Następny termin',r['title'],f'/process-event/{r["id"]}/edit','','process-next',r['id'])
    for r in con.execute('''SELECT d.id,d.title,d.doc_date,d.received_date,d.delivered_date,d.created_at
             FROM documents d WHERE (d.case_id=? OR EXISTS(
                SELECT 1 FROM document_case_links l WHERE l.document_id=d.id AND l.case_id=?))
                AND COALESCE(d.parent_document_id,0)=0''',(cid,cid)):
        url=f'/document/{r["id"]}/open'
        # Fizycznie różne daty dokumentu są osobnymi zdarzeniami — nie giną.
        if r['doc_date']:add(r['doc_date'],'Data dokumentu',r['title'],url,'','document',r['id'])
        if r['received_date']:add(r['received_date'],'Wpływ dokumentu',r['title'],url,'','document-received',r['id'])
        if r['delivered_date']:add(r['delivered_date'],'Doręczenie dokumentu',r['title'],url,'','document-delivered',r['id'])
        if not (r['doc_date'] or r['received_date'] or r['delivered_date']):
            add(str(r['created_at'] or '')[:10],'Dodano dokument (brak daty źródłowej)',r['title'],url,'Zastępczo data wprowadzenia','document-added',r['id'])
    if _table(con,'case_appointments'):
        for r in con.execute("SELECT id,title,appointment_date,appointment_time,status FROM case_appointments WHERE case_id=?",(cid,)):
            add(r['appointment_date'],'Termin ustalony',r['title'],f'/appointment/{r["id"]}',r['appointment_time']+' · '+r['status'],'appointment',r['id'])
    if _table(con,'document_events'):
        for r in con.execute('''SELECT id,document_id,event_date,event_type,title,description
                      FROM document_events WHERE case_id=? AND is_archived=0''',(cid,)):
            add(r['event_date'],'Z dokumentu: '+r['event_type'],r['title'],f'/document/{r["document_id"]}/open',r['description'],'doc-event',r['id'])
    if _table(con,'writing_projects'):
        for r in con.execute('SELECT id,title,due_date FROM writing_projects WHERE case_id=?',(cid,)):
            add(r['due_date'],'Termin projektu pisma',r['title'],f'/draft/{r["id"]}','','draft',r['id'])
    if _table(con,'correspondence_records'):
        for r in con.execute('''SELECT id,subject,sent_on,delivered_on,received_on,expected_reply_on,direction
                  FROM correspondence_records WHERE case_id=?''',(cid,)):
            for fld,typ in (('sent_on','Wysłano'),('delivered_on','Doręczono'),('received_on','Wpłynęło'),('expected_reply_on','Oczekiwana odpowiedź (organizacyjnie)')):
                if r[fld]:add(r[fld],typ+' — korespondencja',r['subject'],f'/correspondence/{r["id"]}','','correspondence',r['id'])
    c=con.execute('SELECT title,next_step,next_date FROM cases WHERE id=?',(cid,)).fetchone()
    if c and c['next_date']:
        add(c['next_date'],'Następny ruch sprawy',c['next_step'] or c['title'],f'/case/{cid}/edit','','case-date',cid)
    return sorted(items,key=lambda r:(r['date'],r['kind'].casefold(),r['id']))


def quick_nav_html():
    return ("<form action='/search' method='get' class='card' style='margin:0 0 12px;padding:10px 14px;display:flex;gap:8px;align-items:center;flex-wrap:wrap'>"
            "<label for='rkquickfind' class='small' style='font-weight:700'>Przejdź do sprawy lub dokumentu</label>"
            "<input id='rkquickfind' name='q' style='flex:1;min-width:160px' placeholder='Sygnatura, klient, nazwa lub dokument…' required>"
            "<button class='btn small primary'>Szukaj</button>"
            "<a class='btn small' href='/documents'>Teczki dokumentów</a>"
            "<a class='btn small' href='/evidence'>Centrum dowodowe</a>"
            "</form>")


class CaseflowMixin:
    def _caseflow_error(self, message, code=400, back='/tasks'):
        a=_app(self)
        return self.send_html(a.layout('Nie wykonano operacji',
              f'<div class="card"><h2>Nie wykonano operacji</h2><p>{esc(message)}</p>'
              f'<a class="btn" href="{esc(back)}">Wróć</a></div>'),code)

    def caseflow_documents(self,qs):
        """Wybieramy teczkę, zanim program odczyta/dopiero pokaże jej dokumenty."""
        a=_app(self);qs=qs or {};q=str((qs.get('q') or [''])[0]).strip()[:180]
        try:cid=int((qs.get('case_id') or ['0'])[0] or 0)
        except (ValueError,TypeError):cid=0
        reverse=(qs.get('order') or ['asc'])[0]!='desc'
        with a.db() as con:
            sql='''SELECT c.id,c.title,c.signature,c.internal_signature,c.client,c.status,
                   (SELECT COUNT(*) FROM documents d WHERE d.case_id=c.id OR EXISTS(
                       SELECT 1 FROM document_case_links l WHERE l.document_id=d.id AND l.case_id=c.id)) doc_count
                   FROM cases c WHERE 1=1''';params=[]
            if q:
                like='%'+q+'%'
                sql+=' AND (c.title LIKE ? OR c.client LIKE ? OR c.signature LIKE ? OR c.internal_signature LIKE ?)'
                params=[like]*4
            sql+=' ORDER BY c.status=\'closed\',c.title COLLATE NOCASE LIMIT 250'
            cases=con.execute(sql,params).fetchall()
            c=con.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone() if cid else None
            docs=con.execute('''SELECT d.*,co.title source_case_title FROM documents d
                JOIN cases co ON co.id=d.case_id
                WHERE d.case_id=? OR EXISTS(SELECT 1 FROM document_case_links l
                      WHERE l.document_id=d.id AND l.case_id=?)''',(cid,cid)).fetchall() if c else []
        case_cards=''.join(f'<a class="card" href="/documents?case_id={r["id"]}" style="display:block;text-decoration:none;color:inherit;margin:0">'
                  f'<b>{esc(r["signature"] or r["internal_signature"] or "Bez sygnatury")} — {esc(r["title"])}</b>'
                  f'<div class="small muted">{esc(r["client"])} · {r["doc_count"]} dokumentów</div></a>' for r in cases)
        header=("<div class='topbar'><div><h1>Dokumenty — teczki spraw</h1>"
                "<div class='sub'>Najpierw wybierz sprawę. Dokumenty innych spraw nie są tu rozwijane.</div></div>"
                "<a class='btn' href='/cases'>Wszystkie sprawy</a></div>")
        picker=(f'<form method="get" action="/documents" class="card form-grid">'
                f'<div class="full"><label>Znajdź sprawę po sygnaturze, kliencie lub nazwie</label>'
                f'<input name="q" value="{esc(q)}" placeholder="Wpisz nazwę lub sygnaturę"></div>'
                '<div class="full"><button class="btn primary">Wyszukaj sprawę</button> '
                '<a class="btn" href="/documents">Wszystkie teczki</a></div></form>')
        if not c:
            notice='<div class="notice">Nie znaleziono wskazanej sprawy.</div>' if cid else ''
            body=header+picker+notice+f'<div style="display:grid;gap:8px">{case_cards or "Brak spraw."}</div>'
            return self.send_html(a.layout('Dokumenty',body,'documents'))
        def document_key(d):
            value=_sort_date(d['doc_date']) or _sort_date(d['received_date']) or _sort_date(d['delivered_date'])
            # Fallback daty dodania jawnie oznaczony w interfejsie.
            return (value or str(d['created_at'] or '')[:10],int(d['id']))
        docs=sorted(docs,key=document_key,reverse=not reverse)
        lines=[]
        for d in docs:
            dt=_sort_date(d['doc_date']) or _sort_date(d['received_date']) or _sort_date(d['delivered_date'])
            time_type=('data dokumentu' if _sort_date(d['doc_date']) else 'wpływ' if _sort_date(d['received_date']) else 'doręczenie' if _sort_date(d['delivered_date']) else 'data dodania')
            display_date=dt or str(d['created_at'] or '')[:10]
            attachment=' · Załącznik' if d['parent_document_id'] else ''
            source=f' · Źródło: {esc(d["source_case_title"])}' if d['case_id']!=cid else ''
            lines.append(f'<tr><td>{esc(display_date)}<div class="small muted">{time_type}</div></td>'
                        f'<td><a href="/document/{d["id"]}/open"><b>{esc(d["title"])}</b></a>'
                        f'<div class="small muted">{esc(d["doc_type"])}{attachment}{source}</div></td>'
                        f'<td>{esc(d["doc_status"])}</td>'
                        f'<td><a class="btn small" href="/document/{d["id"]}/edit">Edytuj</a></td></tr>')
        order='desc' if reverse else 'asc';other='asc' if reverse else 'desc'
        body=(header+f'<div class="card"><a href="/documents">← Wybierz inną sprawę</a>'
              f'<h2>{esc(c["signature"] or c["internal_signature"] or "Bez sygnatury")} — {esc(c["title"])}</h2>'
              f'<div><a class="btn small" href="/case/{cid}?tab=documents">Dokumenty w karcie sprawy</a> '
              f'<a class="btn small" href="/case/{cid}/chronology">Oś chronologiczna</a> '
              f'<a class="btn small" href="/evidence?case_id={cid}">Dowody tej sprawy</a></div></div>'
              f'<div class="card"><div class="section-head"><h2>{len(docs)} dokumentów — chronologicznie</h2>'
              f'<a class="btn small" href="/documents?case_id={cid}&order={other}">'
              f'{"Najnowsze najpierw" if reverse else "Najstarsze najpierw"}</a></div>'
              '<div class="table-scroll"><table><tr><th>Data i jej rodzaj</th><th>Dokument</th><th>Status</th><th></th></tr>'
              +(''.join(lines) or '<tr><td colspan="4">Brak dokumentów w tej sprawie.</td></tr>')+'</table></div></div>')
        return self.send_html(a.layout('Dokumenty sprawy',body,'documents'))

    def caseflow_evidence(self,qs):
        a=_app(self);qs=qs or {};q=str((qs.get('q') or [''])[0]).strip()[:180]
        try:cid=int((qs.get('case_id') or ['0'])[0] or 0)
        except (ValueError,TypeError):cid=0
        with a.db() as con:
            sql='''SELECT c.id,c.title,c.signature,c.internal_signature,c.client,
                  (SELECT COUNT(*) FROM case_assertions x WHERE x.case_id=c.id AND x.is_archived=0) facts,
                  (SELECT COUNT(*) FROM case_evidence e JOIN case_assertions x ON x.id=e.assertion_id
                   WHERE x.case_id=c.id AND x.is_archived=0 AND e.is_archived=0) proofs
                  FROM cases c WHERE 1=1''';args=[]
            if q:
                like='%'+q+'%';sql+=' AND (c.title LIKE ? OR c.client LIKE ? OR c.signature LIKE ? OR c.internal_signature LIKE ?)';args=[like]*4
            sql+=' ORDER BY c.status=\'closed\',c.title COLLATE NOCASE LIMIT 250'
            cases=con.execute(sql,args).fetchall()
            c=con.execute('SELECT id,title,signature FROM cases WHERE id=?',(cid,)).fetchone() if cid else None
            assertions=con.execute('''SELECT id,side,statement,status,legal_significance FROM case_assertions
                 WHERE case_id=? AND is_archived=0 ORDER BY sort_order,id''',(cid,)).fetchall() if c else []
            evidence=con.execute('''SELECT e.id,e.assertion_id,e.title,e.evidence_type,e.status,e.document_id,
                e.source_reference,e.notes,d.doc_date,d.received_date FROM case_evidence e
                JOIN case_assertions x ON x.id=e.assertion_id
                LEFT JOIN documents d ON d.id=e.document_id
                WHERE x.case_id=? AND x.is_archived=0 AND e.is_archived=0''',(cid,)).fetchall() if c else []
        head=("<div class='topbar'><div><h1>Centrum dowodowe</h1><div class='sub'>Wspólny dostęp do istniejącej mapy twierdzeń i dowodów; bez duplikowania dokumentów.</div></div></div>"
              f'<form method="get" action="/evidence" class="card form-grid"><div class="full"><label>Wybierz sprawę</label>'
              f'<input name="q" value="{esc(q)}" placeholder="Nazwa sprawy, klient, sygnatura"></div>'
              '<button class="btn primary">Szukaj</button></form>')
        if not c:
            cards=''.join(f'<a class="card" style="display:block;text-decoration:none;color:inherit" '
                         f'href="/evidence?case_id={r["id"]}">'
                         f'<b>{esc(r["signature"] or r["internal_signature"] or "Bez sygnatury")} — {esc(r["title"])}</b>'
                         f'<div class="small muted">{r["facts"]} twierdzeń · {r["proofs"]} dowodów</div></a>' for r in cases)
            return self.send_html(a.layout('Centrum dowodowe',head+cards,'evidence'))
        grouped={x['id']:[] for x in assertions}
        for e in evidence:grouped.setdefault(e['assertion_id'],[]).append(e)
        rows=[]
        for x in assertions:
            evs=sorted(grouped.get(x['id'],[]),key=lambda e:(_sort_date(e['doc_date']) or _sort_date(e['received_date']) or '',e['id']))
            evhtml=''.join(f'<div style="margin:7px 0;padding:6px 0;border-bottom:1px solid var(--border,#ddd)">'
                    f'{"<a href=\"/document/"+str(e["document_id"])+"/open\">" if e["document_id"] else ""}'
                    f'{esc(e["title"])}{"</a>" if e["document_id"] else ""}'
                    f' · <span class="small">{esc(e["status"])} · {esc(e["evidence_type"])}</span></div>' for e in evs)
            rows.append(f'<article class="card"><div class="small muted">{esc(x["side"])} · {esc(x["status"])}</div>'
                        f'<h3>{esc(x["statement"])}</h3><div class="small">Znaczenie prawne: {esc(x["legal_significance"])}</div>'
                        f'{evhtml or "<p class=\"small muted\">Brak przypisanych dowodów.</p>"}</article>')
        tools=(f'<div class="card"><h2>{esc(c["title"])} — {len(assertions)} twierdzeń, {len(evidence)} dowodów</h2>'
               f'<a class="btn primary" href="/case/{cid}?tab=evidence">Dodaj lub zmień dowody</a> '
               f'<a class="btn" href="/documents?case_id={cid}">Dokumenty sprawy</a> '
               f'<a class="btn" href="/case/{cid}/chronology">Chronologia sprawy</a> '
               '<a class="btn" href="/evidence">Wybierz inną sprawę</a></div>')
        return self.send_html(a.layout('Centrum dowodowe',head+tools+''.join(rows) if rows else head+tools+'<div class="notice">Nie dodano twierdzeń ani dowodów.</div>','evidence'))

    def caseflow_chronology(self,cid,qs):
        a=_app(self);qs=qs or {}
        order=(qs.get('order') or ['asc'])[0]; reverse=order=='desc'
        with a.db() as con:
            c=con.execute('SELECT id,title,signature FROM cases WHERE id=?',(cid,)).fetchone()
            if not c:return self.send_error(404)
            items=chronology_items(con,cid)
        parts=[]
        for x in reversed(items) if reverse else items:
            cat=timeline_category(x['source'])
            parts.append(f'<div class="card rk-ux-timeline-item" data-ux-source="{cat}" style="padding:12px;margin:8px 0">'
                         f'<div class="small muted">{esc(x["date"])} · {esc(x["kind"])}</div>'
                         f'<a class="case-link" href="{esc(x["url"])}"><b>{esc(x["title"])}</b></a>'
                         f'<div class="small muted">{esc(x["description"])}</div></div>')
        other='asc' if reverse else 'desc'
        head=(f'<div class="topbar"><div><h1>Chronologia: {esc(c["title"])}</h1>'
              '<div class="sub">Sortowanie według rzeczywistych dat wydarzeń, nie według dat wprowadzania do programu.</div></div></div>'
              f'<div class="card"><a class="btn" href="/case/{cid}">Karta sprawy</a> '
              f'<a class="btn" href="/documents?case_id={cid}">Dokumenty</a> '
              f'<a class="btn" href="/evidence?case_id={cid}">Dowody</a> '
              f'<a class="btn" href="/case/{cid}/chronology?order={other}">'
              f'{"Najstarsze najpierw" if reverse else "Najnowsze najpierw"}</a></div>')
        controls=('<div class="rk-ux-timeline-controls" role="group" aria-label="Filtr zdarzeń">'
                 + ''.join(f'<button type="button" class="btn small" data-ux-category="{key}" aria-pressed="{str(key=="all").lower()}">{label}</button>'
                 for key,label in [('all','Wszystkie'),('documents','Dokumenty'),('tasks','Zadania i terminy'),('correspondence','Korespondencja'),('events','Pozostałe')])
                 + '</div>')
        timeline='<section data-ux-timeline>'+controls+(''.join(parts) if parts else '<div class="card">Brak datowanych wpisów.</div>')+'</section>'
        return self.send_html(a.layout('Chronologia sprawy',head+timeline,'cases'))

    def caseflow_navigate(self,qs):
        a=_app(self);q=str((qs.get('q') or [''])[0]).strip()[:160]
        if not q:return self.redirect('/cases')
        with a.db() as con:
            cases,tasks,docs=find_navigation_matches(con,q)
        rows=['<h2>Sprawy</h2>']+[f'<p><a href="/case/{r["id"]}">{esc(r["signature"] or r["title"])}</a> — {esc(r["title"])}</p>' for r in cases]
        rows+=['<h2>Zadania</h2>']+[f'<p><a href="/task/{r["id"]}/edit">{esc(r["title"])}</a> · {esc(r["case_title"])}</p>' for r in tasks]
        rows+=['<h2>Dokumenty</h2>']+[f'<p><a href="/document/{r["id"]}/open">{esc(r["title"])}</a> · {esc(r["case_title"])}</p>' for r in docs]
        body=f'<div class="topbar"><h1>Wyniki wyszukiwania: {esc(q)}</h1></div><div class="card">'+''.join(rows)+'</div>'
        return self.send_html(a.layout('Nawigacja',body,'cases'))

    def caseflow_task_summary(self,tid):
        a=_app(self)
        with a.db() as con:
            row=con.execute('SELECT case_id FROM tasks WHERE id=?',(tid,)).fetchone()
            if not row:return ''
            entries=dependency_rows(con,tid)
        labels=''.join(f'<div>{"✓" if x["resolved"] else "!"} '
            f'{"<a href=\""+esc(x["href"])+"\">" if x["href"] else ""}'
            f'{esc(x["label"])}{"</a>" if x["href"] else ""}</div>' for x in entries)
        missing=sum(not x['resolved'] for x in entries)
        return (f'<div class="card"><h3>Zależności zadania · {missing} oczekujących</h3>'
                f'{labels or "<p class=\"small muted\">Brak zależności.</p>"}'
                f'<a class="btn primary" href="/task/{tid}/dependencies">Zarządzaj zależnościami</a></div>')

    def caseflow_dependencies_page(self,tid):
        a=_app(self)
        with a.db() as con:
            task=con.execute('SELECT t.*,c.title case_title FROM tasks t JOIN cases c ON c.id=t.case_id WHERE t.id=?',(tid,)).fetchone()
            if not task:return self.send_error(404)
            ids=sorted(_related_case_ids(con,task['case_id']))
            places=','.join('?' for _ in ids)
            related_tasks=con.execute(f'SELECT id,title,case_id,status FROM tasks WHERE case_id IN ({places}) AND id<>? ORDER BY due_date,id',ids+[tid]).fetchall()
            related_docs=con.execute(f'SELECT id,title,case_id FROM documents WHERE case_id IN ({places}) ORDER BY doc_date DESC,id DESC LIMIT 500',ids).fetchall()
            side=con.execute('SELECT id,needed_item,status FROM side_case_dependencies WHERE parent_case_id=? OR child_case_id=?',(task['case_id'],task['case_id'])).fetchall() if _table(con,'side_case_dependencies') else []
            entries=dependency_rows(con,tid)
        rows=''.join(f'<tr><td>{esc(x["requirement_type"])}</td><td>'
              f'{"<a href=\""+esc(x["href"])+"\">" if x["href"] else ""}'
              f'{esc(x["label"])}{"</a>" if x["href"] else ""}</td>'
              f'<td>{"Spełniona" if x["resolved"] else "Oczekuje"}</td>'
              f'<td><form method="post" action="/task-dependency/{x["id"]}/remove">'
              '<button class="btn small danger">Usuń powiązanie</button></form></td></tr>' for x in entries)
        opts='<option value="">— wybierz —</option>'
        opts+=''.join(f'<option value="task:{t["id"]}">Zadanie: {esc(t["title"])} ({esc(t["status"])})</option>' for t in related_tasks)
        opts+=''.join(f'<option value="document:{d["id"]}">Dokument: {esc(d["title"])}</option>' for d in related_docs)
        opts+=''.join(f'<option value="sidecase:{d["id"]}">Sprawa poboczna: {esc(d["needed_item"])} ({esc(d["status"])})</option>' for d in side)
        chain = '<div class="rk-ux-chain">' + ''.join(
            f'<div class="rk-ux-chain-step"><b>{"✓ Gotowe" if x["resolved"] else "⏳ Oczekuje"}</b>'
            f'<small>{esc(x["label"])}</small></div><span class="rk-ux-chain-arrow" aria-hidden="true">→</span>'
            for x in entries) + f'<div class="rk-ux-chain-step"><b>Zadanie</b><small>{esc(task["title"])}</small></div></div>'
        body=(f'<div class="topbar"><h1>Zależności: {esc(task["title"])}</h1></div>'
              f'<p><a class="btn" href="/task/{tid}/edit">← Zadanie</a> '
              f'<a class="btn" href="/case/{task["case_id"]}">Karta sprawy</a></p>'
              '<div class="card"><p class="small muted">Zadanie zależne nie jest automatycznie wykonywane. Potwierdzenie spełnienia warunków pozostaje po stronie użytkownika.</p>'
              +chain+
              f'<table><tr><th>Rodzaj</th><th>Wymagany element</th><th>Stan</th><th>Akcje</th></tr>{rows or "<tr><td colspan=\"4\">Brak zależności.</td></tr>"}</table></div>'
              f'<div class="card"><h2>Dodaj zależność</h2><form method="post" action="/task/{tid}/dependencies/add" class="form-grid">'
              f'<div class="full"><label>Zależy od</label><select name="reference" required>{opts}</select></div>'
              '<div class="full"><label>Dlaczego?</label><input name="note" placeholder="np. wymagane zaświadczenie z organu"></div>'
              '<div class="full"><button class="btn primary">Zapisz powiązanie</button></div></form></div>')
        return self.send_html(a.layout('Zależności zadania',body,'tasks'))

    def caseflow_dependency_add(self,tid,fields):
        a=_app(self)
        raw=str(fields.get('reference') or '')
        m=re.fullmatch(r'(task|document|sidecase):([1-9][0-9]*)',raw)
        if not m:return self._caseflow_error('Wybierz istniejący element.',back=f'/task/{tid}/dependencies')
        with a.db() as con:
            r=con.execute('SELECT case_id FROM tasks WHERE id=?',(tid,)).fetchone()
            if not r:return self.send_error(404)
            if a.case_read_only(con,r['case_id']):return self.send_error(403)
            try:add_dependency(con,tid,m.group(1),int(m.group(2)),fields.get('note',''),self.current_author(fields))
            except (ValueError,sqlite3.IntegrityError) as exc:
                return self._caseflow_error(str(exc),back=f'/task/{tid}/dependencies')
            a.audit(con,r['case_id'],'task',tid,'Dodano zależność',raw,self.current_author(fields))
        return self.redirect(f'/task/{tid}/dependencies')

    def caseflow_dependency_remove(self,dependency_id,fields):
        a=_app(self)
        with a.db() as con:
            d=con.execute('SELECT d.id,d.task_id,t.case_id FROM task_dependencies d JOIN tasks t ON t.id=d.task_id WHERE d.id=?',(dependency_id,)).fetchone()
            if not d:return self.send_error(404)
            if a.case_read_only(con,d['case_id']):return self.send_error(403)
            con.execute('DELETE FROM task_dependencies WHERE id=?',(dependency_id,))
            a.audit(con,d['case_id'],'task',d['task_id'],'Usunięto zależność',str(dependency_id),self.current_author(fields))
        return self.redirect(f'/task/{d["task_id"]}/dependencies')

    def caseflow_before_finish(self,tid,fields=None):
        """Zatrzymaj zwykłe oznaczanie wykonania, jeśli są nadal zależności."""
        a=_app(self)
        with a.db() as con: missing=unresolved_dependencies(con,tid)
        if not missing:return False
        details=''.join(f'<li>{esc(x["label"])}</li>' for x in missing)
        body=(f'<div class="card"><h2>Uwaga: zadanie ma niespełnione zależności</h2><ul>{details}</ul>'
              f'<a class="btn" href="/task/{tid}/dependencies">Sprawdź zależności</a>'
              f'<form method="post" action="/task/{tid}/force-complete" class="form-grid">'
              '<div class="full"><label>Uzasadnienie ręcznego zamknięcia mimo braków *</label>'
              '<textarea name="reason" required minlength="10"></textarea></div>'
              '<div><button class="btn danger">Zamknij świadomie mimo braków</button></div></form></div>')
        self.send_html(a.layout('Niespełnione zależności',body,'tasks'),409)
        return True

    def caseflow_force_complete(self,tid,fields):
        a=_app(self);reason=str(fields.get('reason') or '').strip()[:1200]
        if len(reason)<10:return self._caseflow_error('Podaj uzasadnienie (co najmniej 10 znaków).',back=f'/task/{tid}/dependencies')
        with a.db() as con:
            r=con.execute('SELECT case_id,title,status FROM tasks WHERE id=?',(tid,)).fetchone()
            if not r:return self.send_error(404)
            if a.case_read_only(con,r['case_id']):return self.send_error(403)
            missing=unresolved_dependencies(con,tid)
            if r['status']!='done':
                from datetime import datetime
                actor=self.current_author(fields)
                con.execute('''UPDATE tasks SET status='done',updated_by=?,completed_at=?,completed_by=? WHERE id=?''',
                            (actor,datetime.now().strftime('%Y-%m-%d %H:%M:%S'),actor,tid))
                a.sync_task_alert(con,tid,actor)
                con.execute('''INSERT INTO task_dependency_overrides(task_id,unresolved_snapshot,reason,actor)
                               VALUES(?,?,?,?)''',(tid,'; '.join(x['label'] for x in missing),reason,actor))
                a.audit(con,r['case_id'],'task',tid,'Zamknięto zadanie mimo zależności',reason,actor)
        return self.redirect(f'/task/{tid}/edit')
