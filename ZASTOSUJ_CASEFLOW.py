# -*- coding: utf-8 -*-
"""Idempotentny integrator RK KANCELARIA 0.3.8-dev1.

Preflight całego źródła i modułu przed zapisem. Nie czyta / nie modyfikuje Data.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys
import tempfile

VERSION='0.3.8-dev1'
MARK='from rk_caseflow import CaseflowMixin, ensure_caseflow_schema, quick_nav_html, dependency_rows, unresolved_dependencies, dependency_blocking_counts'


def once(src,old,new,label):
    n=src.count(old)
    if n!=1:
        raise RuntimeError(f'{label}: oczekiwano jednej kotwicy, znaleziono {n}. Niczego nie zapisano.')
    return src.replace(old,new,1)


def method(src,start,end,replacements,label):
    first=src.find(start)
    last=src.find(end,first+len(start)) if first>=0 else -1
    if first<0 or last<0:
        raise RuntimeError(f'{label}: nie znaleziono metody ({start!r}, {end!r}).')
    chunk=src[first:last]
    for old,new,key in replacements:chunk=once(chunk,old,new,f'{label}/{key}')
    return src[:first]+chunk+src[last:]


def apply_app(src):
    if MARK in src:
        required=('VERSION = "0.3.8-dev1"','SCHEMA_VERSION = 330',
                  'ensure_caseflow_schema(con)','self.caseflow_documents(qs)',
                  'self.caseflow_evidence(qs)','self.caseflow_chronology(',
                  'self.caseflow_dependency_add(', 'self.caseflow_before_finish(',
                  'self.caseflow_force_complete(', 'quick_nav_html()',
                  'self.caseflow_task_summary(tid)')
        if all(x in src for x in required):return src
        raise RuntimeError('Niespójne źródła 0.3.8; integracja zatrzymana bez zapisu.')
    if 'VERSION = "0.3.7-dev1"' not in src or 'SCHEMA_VERSION = 329' not in src:
        raise RuntimeError('Ta aktualizacja wymaga kompletnego RK KANCELARIA 0.3.7-dev1 (schemat 329).')
    src=once(src,
        'from rk_case_categories import CaseCategoryMixin, ensure_case_categories_schema, category_form, save_categories, category_map, category_chips',
        'from rk_case_categories import CaseCategoryMixin, ensure_case_categories_schema, category_form, save_categories, category_map, category_chips\n'+MARK,
        'import')
    src=once(src,'VERSION = "0.3.7-dev1"','VERSION = "0.3.8-dev1"','wersja')
    src=once(src,'SCHEMA_VERSION = 329','SCHEMA_VERSION = 330','schemat')
    src=once(src,
        'class Handler(CaseCategoryMixin, WorkspacePlusMixin, CorrespondenceMixin, ActionCenterMixin, DocumentHubMixin, InboxMixin, BaseHTTPRequestHandler):',
        'class Handler(CaseflowMixin, CaseCategoryMixin, WorkspacePlusMixin, CorrespondenceMixin, ActionCenterMixin, DocumentHubMixin, InboxMixin, BaseHTTPRequestHandler):',
        'handler')
    src=once(src,'        ensure_case_categories_schema(con)',
        '        ensure_case_categories_schema(con)\n        ensure_caseflow_schema(con)','migracja')
    src=once(src,'            ("/documents", "▤", "Dokumenty", "documents"),',
        '            ("/documents", "▤", "Dokumenty — teczki", "documents"),\n'
        '            ("/evidence", "⚖", "Centrum dowodowe", "evidence"),','menu')
    src=once(src,'def layout(title: str, body: str, active: str = "") -> str:\n    body = nav_strip(title) + body',
        'def layout(title: str, body: str, active: str = "") -> str:\n    body = nav_strip(title) + quick_nav_html() + body','szybka_nawigacja')
    src=once(src,'            if path == "/case-categories": return self.category_catalog_page()',
        '            if path == "/case-categories": return self.category_catalog_page()\n'
        '            if path == "/evidence": return self.caseflow_evidence(qs)\n'
        '            if path == "/navigate": return self.caseflow_navigate(qs)\n'
        '            if re.fullmatch(r"/case/\\d+/chronology",path): return self.caseflow_chronology(int(path.split("/")[2]),qs)\n'
        '            if re.fullmatch(r"/task/\\d+/dependencies",path): return self.caseflow_dependencies_page(int(path.split("/")[2]))',
        'GET')
    src=once(src,'            if path == "/deadline/create": return self.deadline_create(fields)',
        '            if path == "/deadline/create": return self.deadline_create(fields)\n'
        '            if re.fullmatch(r"/task/\\d+/dependencies/add",path): return self.caseflow_dependency_add(int(path.split("/")[2]),fields)\n'
        '            if re.fullmatch(r"/task-dependency/\\d+/remove",path): return self.caseflow_dependency_remove(int(path.split("/")[2]),fields)\n'
        '            if re.fullmatch(r"/task/\\d+/force-complete",path): return self.caseflow_force_complete(int(path.split("/")[2]),fields)',
        'POST')

    # Dokumenty globalne: zamiast wczytywać wszystkie dokumenty, wybór teczki.
    start='    def documents_page(self,qs):'
    end='    def note_add(self,cid,f):'
    first=src.find(start);last=src.find(end,first+len(start)) if first>=0 else -1
    if first<0 or last<0:raise RuntimeError('Nie znaleziono granic globalnego modułu dokumentów.')
    src=src[:first]+"    def documents_page(self,qs):\n        return self.caseflow_documents(qs)\n\n"+src[last:]

    # Niewykonane zależności: normalne zamknięcie wymaga świadomego override.
    src=method(src,'    def task_toggle(self,tid,f):','    def task_delete(self,tid,f):',[
        ("                cid=r['case_id']; new='done' if r['status']!='done' else 'open'",
         "                cid=r['case_id']; new='done' if r['status']!='done' else 'open'\n"
         "                if new=='done' and self.caseflow_before_finish(tid,f):return",'guard')
    ],'task_toggle')
    src=method(src,'    def task_update(self,tid,f):','    def document_edit(self,did):',[
        ("            if not old: return self.send_error(404)",
         "            if not old: return self.send_error(404)\n"
         "            if old['status']!='done' and new['status']=='done' and self.caseflow_before_finish(tid,f):return",'guard')
    ],'task_update')
    src=method(src,'    def task_edit(self,tid,qs=None):','    def task_update(self,tid,f):',[
        ('        body += related_nav','        body += related_nav + self.caseflow_task_summary(tid)','panel')
    ],'task_edit')

    # Widok jednej sprawy: bezpośrednie przejścia i kolejność w oparciu o daty.
    src=method(src,'    def case_workspace(self, cid, qs=None):','    def case_view_simple(self, cid, qs=None):',[
        ("<a class='btn small' href='/case/{cid}/sidecases'>Sprawy poboczne</a>",
         "<a class='btn small' href='/case/{cid}/sidecases'>Sprawy poboczne</a>"
         "<a class='btn small' href='/case/{cid}/chronology'>Chronologia</a>"
         "<a class='btn small' href='/evidence?case_id={cid}'>Centrum dowodowe</a>", 'header'),
        ("<h2>Historia sprawy</h2><div class='muted'>Kilka dat z jednego dokumentu może tworzyć kilka osobnych zdarzeń.</div>",
         "<h2>Historia sprawy</h2><div class='muted'>Wpisy są układane według dat zdarzeń, nie według kolejności ich dodania.</div>", 'history-label'),
        ("<a class='btn' href='/case/{cid}/history'>Historia procesu i zmian</a>",
         "<a class='btn' href='/case/{cid}/chronology'>Wszystkie wydarzenia chronologicznie</a> "
         "<a class='btn' href='/case/{cid}/history'>Historia procesu i zmian</a>", 'history-button'),
        ("href=f\"/document/{x['source_id']}/open\" if x['source_type']=='document' else '#'",
         "href=(f\"/document/{x['source_id']}/open\" if x['source_type']=='document' else "
         "f\"/process-event/{x['source_id']}/edit\" if x['source_type']=='process_event' else "
         "f\"/event/{x['source_id']}/edit\" if x['source_type']=='event' else '#')",'timeline-links'),
        ("<a class='btn' href='/documents?case_id={cid}'>Widok globalny</a>",
         "<a class='btn' href='/documents?case_id={cid}'>Teczka dokumentów</a>", 'document-nav'),
        ("            readonly=case_read_only(con,cid)",
         "            readonly=case_read_only(con,cid)\n"
         "            blocked_task_counts=dependency_blocking_counts(con,[t['id'] for t in tasks])",'blocks-query'),
        ("                done=t['status']=='done'; assignee=esc(task_people.get(t['id']) or t['assigned_name'] or '—')",
         "                done=t['status']=='done'; assignee=esc(task_people.get(t['id']) or t['assigned_name'] or '—')\n"
         "                blocked=blocked_task_counts.get(t['id'],0)\n"
         "                blocked_note=(f\" <a class='case-link small' href='/task/{t['id']}/dependencies'>⏳ {blocked} oczekujących warunków</a>\" if blocked else '')",'blocks-render'),
        ("{fmt_date(t['due_date'])} · {assignee}","{fmt_date(t['due_date'])} · {assignee}{blocked_note}",'blocks-display'),

    ],'case_workspace')
    src=method(src,'    def tasks_page(self,qs):','    def documents_page(self,qs):',[
        ("            rows=con.execute(sql,params).fetchall()",
         "            rows=con.execute(sql,params).fetchall()\n"
         "            block_counts=dependency_blocking_counts(con,[r['id'] for r in rows])",'query'),
        ("            deadline_meta=''",
         "            blocked=block_counts.get(r['id'],0)\n"
         "            blocked_note=(f\"<div class='small'><a class='case-link' href='/task/{r['id']}/dependencies'>⏳ {blocked} niespełnionych zależności</a></div>\" if blocked else '')\n"
         "            deadline_meta=''", 'badge'),
        ("{dep}{deadline_meta}{auth_html}","{dep}{deadline_meta}{blocked_note}{auth_html}",'display'),
    ],'tasks_page')
    # Chronologia w widoku prostym: dotychczas 12 dokumentów wg id dodania.
    src=method(src,'    def case_view_simple(self, cid, qs=None):','    def calendar_page(self, qs):',[
        ("ORDER BY id DESC LIMIT 12", "ORDER BY COALESCE(NULLIF(doc_date,''),NULLIF(received_date,''),SUBSTR(created_at,1,10)) DESC,id DESC LIMIT 12",'document-sort')
    ],'case_simple')
    # Dziennik zmian jest odrębnym bytem: właściwa data wykonania, a nie data wydarzenia.
    src=method(src,'    def history_page(self,qs):','    def trash_page(self,qs):',[
        ('sql += " ORDER BY a.id DESC LIMIT 500"',
         'sql += " ORDER BY a.created_at DESC,a.id DESC LIMIT 500"','audit-sort')
    ],'audit_history')
    compile(src,'app.py','exec')
    return src


def update(root, dry_run=False):
    root=Path(root).resolve()
    for name in ('app.py','rk_caseflow.py','README.md'):
        if not (root/name).is_file():raise RuntimeError('Brak pliku '+name)
    compile((root/'rk_caseflow.py').read_text(encoding='utf8'),'rk_caseflow.py','exec')
    app_path=root/'app.py';old=app_path.read_text(encoding='utf8');new=apply_app(old)
    readme=root/'README.md';oldread=readme.read_text(encoding='utf8')
    title='## RK KANCELARIA 0.3.8-dev1 — teczki, zależności i chronologia'
    newread=oldread if title in oldread else oldread+('\n\n'+title+'\n'+
        '- Dokumenty otwierane po wybraniu sprawy; jedna teczka zamiast masowego widoku.\n'
        '- Centrum dowodowe prezentuje istniejące twierdzenia i dowody.\n'
        '- Zależności zadanie / dokument / sprawa poboczna z kontrolą cykli.\n'
        '- Oś czasu porządkuje rzeczywiste daty zdarzeń, oddzielnie od audytu zmian.\n'
        '- Zamknięcie mimo nieukończonych zależności wymaga świadomego uzasadnienia.\n')
    if dry_run:
        print('OK: 0.3.8 zgodna z bazą źródłową; bez zapisu.');return
    applied=[]
    try:
        for path,before,after in ((app_path,old,new),(readme,oldread,newread)):
            if after==before:continue
            fd,tmp=tempfile.mkstemp(dir=root,prefix='.rk-caseflow-',suffix='.tmp')
            with os.fdopen(fd,'w',encoding='utf8',newline='\n') as h:h.write(after)
            os.replace(tmp,path);applied.append((path,before))
    except BaseException:
        for path,before in reversed(applied):path.write_text(before,encoding='utf8')
        raise
    print('RK KANCELARIA 0.3.8-dev1: integracja zakończona (SCHEMA_VERSION=330).')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',nargs='?',default='.')
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    try:update(args.root,args.dry_run)
    except Exception as e:print('BŁĄD INTEGRACJI 0.3.8:',e,file=sys.stderr);raise SystemExit(1)
