# -*- coding: utf-8 -*-
"""RK KANCELARIA 0.3.6-dev1: wiązanie rekordów i kontrola usuwania terminów.

Ten moduł tworzy odnośniki wyłącznie z istniejących identyfikatorów rekordów.
Nie rozpoznaje przypadkowych nazw w wolnym tekście i nie oblicza terminów.
"""
from __future__ import annotations

import html
import re
from urllib.parse import urlsplit


def esc(value):
    return html.escape(str(value if value is not None else ''), quote=True)


def safe_back(value, fallback='/tasks'):
    """Odrzucamy obce adresy, //host, backslash oraz znaki sterujące."""
    value=str(value or '').strip()
    if not value.startswith('/') or value.startswith('//') or '\\' in value:
        return fallback
    if any(ord(ch)<32 or ord(ch)==127 for ch in value):
        return fallback
    p=urlsplit(value)
    if p.scheme or p.netloc or p.path.startswith('//'):
        return fallback
    return value[:900]


def _existing_table(con, name):
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone())


def _link(url,label,cls='case-link'):
    return f"<a class='{cls}' href='{esc(url)}'>{esc(label)}</a>"


def _delete_form(resource, resource_id, case_id, return_to, name):
    url=f'/{resource}/{int(resource_id)}/delete'
    message=f'Przenieść {name} do Kosza? Wpis będzie można przywrócić.'
    return (f"<form method='post' action='{esc(url)}' style='display:inline' "
            f"onsubmit='return confirm({esc(chr(34)+message+chr(34))})'>"
            f"<input type='hidden' name='case_id' value='{int(case_id)}'>"
            f"<input type='hidden' name='return_to' value='{esc(return_to)}'>"
            "<button type='submit' class='btn small danger'>Do kosza</button></form>")


def case_deadline_rows(tasks, alerts, case_row, fmt_date, *, is_readonly=False):
    """Każdy widoczny termin ma swoje źródło i dokładną akcję (bez heurystyk po tytule)."""
    cid=int(case_row['id'])
    back=f'/case/{cid}?tab=deadlines'
    rows=[]
    task_ids=set()
    for task in tasks:
        if not task['due_date']:
            continue
        tid=int(task['id']); task_ids.add(tid)
        href=f'/task/{tid}/edit?return_to=%2Fcase%2F{cid}%3Ftab%3Ddeadlines'
        actions=f"<a class='btn small' href='{href}'>Otwórz</a>"
        if not is_readonly:
            actions+=' '+_delete_form('task',tid,cid,back,'zadanie / termin')
        typ=str(task['task_type'] or 'Zadanie')
        status=' · wykonane' if task['status']=='done' else ''
        rows.append((str(task['due_date']),0,tid,
          f"<tr><td><b>{fmt_date(task['due_date'])}</b></td><td>{esc(typ+status)}</td>"
          f"<td>{_link(href,task['title'])}</td><td class='nowrap'>{actions}</td></tr>"))
    for alert in alerts:
        when=str(alert['alert_date'] or '')
        if not when: continue
        sid=int(alert['source_id'] or 0) if alert['source_type']=='task' else 0
        if sid in task_ids:
            continue  # nie duplikujemy alertu o tej samej czynności
        aid=int(alert['id'])
        if sid:
            href=f'/task/{sid}/edit'
            link=_link(href,alert['title'])
            actions=f"<a class='btn small' href='{href}'>Otwórz zadanie</a>"
        else:
            link=_link(f'/calendar?case_id={cid}',alert['title'])
            actions=f"<a class='btn small' href='/calendar?case_id={cid}'>Kalendarz</a>"
        if not is_readonly:
            actions+=' '+_delete_form('alert',aid,cid,back,'alert')
        rows.append((when,1,aid,
          f"<tr><td><b>{fmt_date(when)}</b></td><td>{esc(alert['alert_type'] or 'Alert')}</td>"
          f"<td>{link}</td><td class='nowrap'>{actions}</td></tr>"))
    if case_row['next_date']:
        href=f'/case/{cid}/edit'
        actions=f"<a class='btn small' href='{href}'>Edytuj sprawę</a>"
        if not is_readonly:
            actions+=(f" <form method='post' action='/case/{cid}/clear-next-date' style='display:inline' "
                     "onsubmit='return confirm(&quot;Wyczyścić datę następnej czynności w sprawie?&quot;)'>"
                     f"<input type='hidden' name='return_to' value='{back}'>"
                     "<button type='submit' class='btn small danger'>Wyczyść datę</button></form>")
        rows.append((str(case_row['next_date']),2,cid,
          f"<tr><td><b>{fmt_date(case_row['next_date'])}</b></td><td>Następna czynność w sprawie</td>"
          f"<td>{_link(href,case_row['next_step'] or case_row['title'])}</td>"
          f"<td class='nowrap'>{actions}</td></tr>"))
    return ''.join(x[3] for x in sorted(rows,key=lambda x:(x[0],x[1],x[2])))


def linked_records_panel(con, kind, row):
    """Powiązania wyłącznie istniejące w bazie; linki kierują do rzeczywistych rekordów."""
    if kind not in {'task','document','draft'}: return ''
    rid=int(row['id'])
    cid=int(row['case_id'] or 0)
    parts=[]; seen=set()
    def add(href,label):
        if href not in seen:
            parts.append(_link(href,label,'btn small'))
            seen.add(href)
    if cid:
        add(f'/case/{cid}', 'Sprawa')
        add(f'/case/{cid}?tab=deadlines','Terminy sprawy')
        add(f'/case/{cid}?tab=documents','Dokumenty sprawy')
        add(f'/case/{cid}?tab=tasks','Zadania sprawy')
        if _existing_table(con,'correspondence_records'):
            add(f'/correspondence?case_id={cid}','Korespondencja sprawy')
    if kind=='task':
        for d in con.execute('SELECT id,title FROM documents WHERE linked_task_id=? ORDER BY id DESC LIMIT 25',(rid,)).fetchall():
            add(f"/document/{d['id']}/open",'Dokument: '+str(d['title'])[:74])
        if _existing_table(con,'correspondence_records'):
            for r in con.execute('SELECT id,subject FROM correspondence_records WHERE followup_task_id=? ORDER BY id DESC LIMIT 15',(rid,)).fetchall():
                add(f"/correspondence/{r['id']}",'Korespondencja: '+str(r['subject'])[:74])
        if _existing_table(con,'workflow_proposals') and _existing_table(con,'workflow_reviews'):
            sql=('SELECT r.source_type,r.source_id,r.source_title FROM workflow_proposals p '
                 'JOIN workflow_reviews r ON r.id=p.review_id WHERE p.task_id=? LIMIT 20')
            for p in con.execute(sql,(rid,)).fetchall():
                if p['source_type']=='document': add(f"/document/{p['source_id']}/open",'Źródło: '+str(p['source_title'])[:74])
                if p['source_type']=='draft': add(f"/draft/{p['source_id']}",'Projekt źródłowy: '+str(p['source_title'])[:74])
    elif kind=='document':
        linked=int(row['linked_task_id'] or 0)
        if linked and con.execute('SELECT 1 FROM tasks WHERE id=?',(linked,)).fetchone():
            add(f'/task/{linked}/edit','Powiązane zadanie / termin')
        if _existing_table(con,'correspondence_records'):
            for r in con.execute('''SELECT id,subject FROM correspondence_records
                WHERE document_id=? OR dispatch_receipt_id=? OR delivery_receipt_id=? ORDER BY id DESC LIMIT 20''',(rid,rid,rid)).fetchall():
                add(f"/correspondence/{r['id']}",'Korespondencja: '+str(r['subject'])[:74])
    elif kind=='draft' and _existing_table(con,'correspondence_records'):
        for r in con.execute('SELECT id,subject FROM correspondence_records WHERE draft_id=? ORDER BY id DESC LIMIT 20',(rid,)).fetchall():
            add(f"/correspondence/{r['id']}",'Wysyłka: '+str(r['subject'])[:74])
    if kind in {'document','draft'} and _existing_table(con,'workflow_reviews') and _existing_table(con,'workflow_proposals'):
        source_type='document' if kind=='document' else 'draft'
        sql=('SELECT p.task_id,t.title FROM workflow_reviews r JOIN workflow_proposals p ON p.review_id=r.id '
             'JOIN tasks t ON t.id=p.task_id WHERE r.source_type=? AND r.source_id=? '
             'AND p.status=\'approved\' ORDER BY p.id DESC LIMIT 20')
        for t in con.execute(sql,(source_type,rid)).fetchall():
            add(f"/task/{t['task_id']}/edit",'Wynik analizy: '+str(t['title'])[:74])
    return ("<div class='card' style='margin-top:14px'><h2>Powiązane elementy</h2>"
            "<p class='small muted'>Odnośniki prowadzą do konkretnych rekordów w tej kancelarii.</p>"
            "<div class='case-control-bar' style='flex-wrap:wrap;gap:8px'>"+ ' '.join(parts) + '</div></div>') if parts else ''
