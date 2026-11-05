# -*- coding: utf-8 -*-
"""Idempotentny integrator 0.3.7-dev1, bez dotykania folderu Data."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys
import tempfile

MARK='from rk_workspace_plus import WorkspacePlusMixin, ensure_workspace_plus_schema, appointments_table, assignee_html, selected_ids, set_task_assignees, nav_strip, linked_sidecases, archived_appointments_html, task_assignees_map, upcoming_alerts_multi as upcoming_alerts'


def once(src,old,new,label):
    n=src.count(old)
    if n != 1:
        raise RuntimeError(f'{label}: niejednoznaczna kotwica (wystąpień {n}); niczego nie zapisano.')
    return src.replace(old,new,1)


def method_change(src,start,end,transforms,label):
    a=src.find(start)
    b=src.find(end,a+len(start)) if a>=0 else -1
    if a<0 or b<0:raise RuntimeError(f'{label}: nie znaleziono granic metody.')
    chunk=src[a:b]
    for old,new,key in transforms:chunk=once(chunk,old,new,f'{label}/{key}')
    return src[:a]+chunk+src[b:]


def apply_app(src):
    if MARK in src:
        required=['VERSION = "0.3.7-dev1"',
                  'ensure_workspace_plus_schema(con)','self.my_calendar_page(qs)',
                  'self.appointment_save(fields)', 'self.sidecase_create(',
                  'task_assignments_save(',"appointments_table(con,cid)",
                  'if path == "/my-calendar"','assignees_html_task']
        if all(t in src for t in required) and ('SCHEMA_VERSION = 328' in src or 'SCHEMA_VERSION = 329' in src):
            return src
        raise RuntimeError('Niedokończona integracja 0.3.7 — wymagana ręczna kontrola wersji źródła.')
    if 'VERSION = "0.3.6-dev1"' not in src:
        raise RuntimeError('Aktualizacja wymaga kompletnej 0.3.6-dev1; odmowa nadpisania źródła.')
    src=once(src,'from rk_record_navigation import case_deadline_rows, linked_records_panel, safe_back',
             'from rk_record_navigation import case_deadline_rows, linked_records_panel, safe_back\n'+MARK,'import')
    src=once(src,'VERSION = "0.3.6-dev1"','VERSION = "0.3.7-dev1"','version')
    src=once(src,'SCHEMA_VERSION = 327','SCHEMA_VERSION = 328','schema_version')
    src=once(src,'class Handler(CorrespondenceMixin, ActionCenterMixin, DocumentHubMixin, InboxMixin, BaseHTTPRequestHandler):',
             'class Handler(WorkspacePlusMixin, CorrespondenceMixin, ActionCenterMixin, DocumentHubMixin, InboxMixin, BaseHTTPRequestHandler):','Handler')
    src=once(src,'        ensure_correspondence_schema(con)',
             '        ensure_correspondence_schema(con)\n        ensure_workspace_plus_schema(con)','migracja')
    src=once(src,'            ("/calendar", "▦", "Kalendarz", "calendar"),',
             '            ("/calendar", "▦", "Kalendarz kancelarii", "calendar"),\n'
             '            ("/my-calendar", "▣", "Mój kalendarz", "mycalendar"),','nawigacja/menu')
    src=once(src,'def layout(title: str, body: str, active: str = "") -> str:\n    user = current_request_user()',
             'def layout(title: str, body: str, active: str = "") -> str:\n    body = nav_strip(title) + body\n    user = current_request_user()', 'globalne skróty')
    src=once(src,'<div class="live-clock-card" aria-label="Aktualny czas">',
             '<a href="/my-calendar" class="live-clock-card" style="display:block;text-decoration:none;color:inherit" title="Otwórz mój kalendarz" aria-label="Otwórz mój kalendarz">','zegar do kalendarza')
    src=once(src,'<div id="liveClockDate" class="live-clock-date">{esc(today_label)}</div></div>',
             '<div id="liveClockDate" class="live-clock-date">{esc(today_label)} · kliknij, by otworzyć kalendarz</div></a>','zamknięcie zegara')
    src=once(src,'            if path == "/calendar": return self.calendar_page(qs)',
             '            if path == "/calendar": return self.calendar_page(qs)\n'
             '            if path == "/my-calendar": return self.my_calendar_page(qs)\n'
             '            if re.fullmatch(r"/appointment/\\d+",path): return self.appointment_page(int(path.split("/")[2]))\n'
             '            if re.fullmatch(r"/case/\\d+/sidecases",path): return self.sidecase_page(int(path.split("/")[2]))','GET')
    src=once(src,'            if path == "/deadline/create": return self.deadline_create(fields)',
             '            if path == "/deadline/create": return self.deadline_create(fields)\n'
             '            if path == "/appointment/create": return self.appointment_save(fields)\n'
             '            if re.fullmatch(r"/appointment/\\d+/update",path): return self.appointment_save(fields,int(path.split("/")[2]))\n'
             '            if re.fullmatch(r"/appointment/\\d+/delete",path): return self.appointment_delete(int(path.split("/")[2]),fields)\n'
             '            if re.fullmatch(r"/appointment/\\d+/restore",path): return self.appointment_restore(int(path.split("/")[2]),fields)\n'
             '            if re.fullmatch(r"/task/\\d+/assignees",path): return self.task_assignments_save(int(path.split("/")[2]),fields)\n'
             '            if re.fullmatch(r"/case/\\d+/sidecase",path): return self.sidecase_create(int(path.split("/")[2]),fields)\n'
             '            if re.fullmatch(r"/sidecase/\\d+/status",path): return self.sidecase_status(int(path.split("/")[2]),fields)', 'POST')
    # Zakładka Terminy: planowane daty i osobny formularz do wielu terminów.
    start='    def case_workspace(self, cid, qs=None):'
    end='    def case_view_simple(self, cid, qs=None):'
    # W niektórych wydaniach kolejna metoda może mieć inny podpis:
    if end not in src:
        end='    def calendar_page(self, qs):'
    x=src.find(start); y=src.find(end,x+len(start))
    if x<0 or y<0:raise RuntimeError('case_workspace: granice nieznane')
    frag=src[x:y]
    frag=once(frag,'            readonly=case_read_only(con,cid)',
              '            readonly=case_read_only(con,cid)\n            task_people=task_assignees_map(con,[t[\'id\'] for t in tasks])\n            appointments_count=con.execute("SELECT COUNT(*) FROM case_appointments WHERE case_id=? AND status=\'planned\'",(cid,)).fetchone()[0]', 'liczba terminów')
    frag=once(frag,"('deadlines','Terminy',str(len(next_dates)))", "('deadlines','Terminy',str(len(next_dates)+appointments_count))",'licznik')
    # twórz obiekt widgetu przed renderowaniem zakładek, bez dodatkowego zapytania dla każdej pętli.
    frag=once(frag, "        shown_sig,sig_kind=display_case_signature(cid,c['signature'],c['internal_signature'])",
              "        with db() as con:\n            assignees_html_task = assignee_html(con,'task')\n        shown_sig,sig_kind=display_case_signature(cid,c['signature'],c['internal_signature'])",'assignees_html_task')
    frag=once(frag,"done=t['status']=='done'; assignee=esc(t['assigned_name']) if t['assigned_name'] else '—'",
              "done=t['status']=='done'; assignee=esc(task_people.get(t['id']) or t['assigned_name'] or '—')",'nazwy wykonawców')
    frag=once(frag,"<div><label>Wykonawca</label><select name='assigned_user_id'>{user_opts}</select></div>",'', 'usuń przestarzały wybór pojedynczego wykonawcy')
    frag=once(frag,"<div class='full'><label>Zależność</label><input name='depends_on'></div><div class='full'><label>Notatka</label><textarea name='notes'></textarea></div><div class='full'><button class='btn primary'>Dodaj</button>",
              "<div class='full'><label>Zależność</label><input name='depends_on'></div><div class='full'><label>Notatka</label><textarea name='notes'></textarea></div><input type='hidden' name='_multi_assignees' value='1'>{assignees_html_task}<div class='full'><button class='btn primary'>Dodaj</button>",'multi-add-case')
    frag=once(frag,"        elif tab=='evidence':", '''            with db() as con:
                appointment_lines=appointments_table(con,cid)
                appointment_archive=archived_appointments_html(con,cid)
                appointment_users=assignee_html(con,'appointment')
            new_appointment=f"""<details class='card smart-add'><summary>+ Nowy termin ustalony (data bez wyliczania)</summary>
                <form method='post' action='/appointment/create' class='form-grid'>
                <input type='hidden' name='case_id' value='{cid}'>
                <div class='full'><label>Nazwa *</label><input name='title' required placeholder='np. druga mediacja'></div>
                <div><label>Data *</label><input type='date' name='appointment_date' required></div>
                <div><label>Godzina</label><input type='time' name='appointment_time'></div>
                <div><label>Rodzaj</label><input name='kind' value='Termin ustalony'></div>
                <div><label>Miejsce</label><input name='location'></div>
                <div class='full'><label>Notatka</label><textarea name='notes'></textarea></div>
                {appointment_users}<div class='full'><button class='btn primary'>Dodaj termin</button></div></form></details>"""
            content += (f"<div class='card'><h2>Terminy ustalone — wiele dat dla jednej sprawy</h2>"
                        f"<p class='small muted'>Rozprawa, druga mediacja, posiedzenie i spotkania mogą istnieć równolegle. "
                        f"Nie są automatycznie liczone jako terminy procesowe.</p>"
                        f"{new_appointment}<table><tr><th>Data</th><th>Termin</th><th>Status</th><th></th></tr>"
                        f"{appointment_lines or '<tr><td colspan=4>Brak terminów ustalonych.</td></tr>'}</table>"
                        f"<details><summary>Kosz terminów ustalonych</summary>{appointment_archive or 'Brak usuniętych terminów.'}</details></div>"
                        f"<div class='card'><a class='btn primary' href='/case/{cid}/sidecases'>Sprawy poboczne i wymagane dokumenty</a></div>")

        elif tab=='evidence':''','appointments')
    # Powiązania bocznych postępowań są widoczne także po wejściu w sprawę.
    frag=once(frag,"          <div class='case-workspace-actions'>{badge(c['status'])}{closed_actions}",
              "          <div class='case-workspace-actions'>{badge(c['status'])}{closed_actions}<a class='btn small' href='/case/{cid}/sidecases'>Sprawy poboczne</a>", 'link-sidecases')
    src=src[:x]+frag+src[y:]
    # Globalny kalendarz także odczytuje niezależne terminy ustalone.
    src=method_change(src,'    def calendar_page(self, qs):','    def deadline_suggestion_accept(self, sid, f):',[
        ('''            cases = con.execute("SELECT id,title,signature,internal_signature FROM cases WHERE status<>'closed' ORDER BY signature='',signature,title").fetchall()''',
         '''            appointments = con.execute(
                f"SELECT * FROM case_appointments WHERE status='planned' AND appointment_date BETWEEN ? AND ?{' AND case_id=?' if case_filter else ''}", params
            ).fetchall()
            cases = con.execute("SELECT id,title,signature,internal_signature FROM cases WHERE status<>'closed' ORDER BY signature='',signature,title").fetchall()''','appointment query'),
        ('''        for r in case_dates:
            # Pole ogólne w sprawie jest tylko fallbackiem.''',
         '''        for r in appointments:
            add_item(r['appointment_date'],r['kind'],r['title']+((' · '+r['appointment_time']) if r['appointment_time'] else ''),
                     r['case_id'],'high',f"/appointment/{r['id']}")
        for r in case_dates:
            # Pole ogólne w sprawie jest tylko fallbackiem.''','appointment rows')], 'calendar_page')
    # Oddzielny panel przy zadaniu, bez zmiany semantyki autosave starego formularza.
    src=once(src,'        body += related_nav', '''        with db() as con:
            assignees_html_task=assignee_html(con,'task',tid)
        body += (f"<div class='card'><h3>Przypisani do zadania / terminu</h3>"
                 f"<form method='post' action='/task/{tid}/assignees' class='form-grid'>"
                 f"{assignees_html_task}<div class='full'><button class='btn primary'>Zapisz osoby</button></div>"
                 "</form></div>")
        body += related_nav''','współprzypisywanie w zadaniu')
    # Zadania globalne: nowy filtr 'moje' obejmuje całą listę współprzypisanych.
    src=once(src,'            if mine: sql += " AND t.assigned_user_id=?"; params.append(uid)',
             '''            if mine:
                sql += " AND (EXISTS(SELECT 1 FROM task_assignees ta WHERE ta.task_id=t.id AND ta.user_id=?) OR (t.assigned_user_id=? AND NOT EXISTS(SELECT 1 FROM task_assignees ta WHERE ta.task_id=t.id)))"
                params.extend([uid,uid])''','filtr moje zadania')
    # Formularz tworzenia z listy Zadań.
    src=method_change(src,'    def tasks_page(self,qs):','    def documents_page(self,qs):',[
        ("        user_opts='<option value=\"\">— nie przypisano —</option>'+''.join(f\"<option value='{x['id']}'>{esc(user_display_name(x))}</option>\" for x in users)",
         "        user_opts='<option value=\"\">— nie przypisano —</option>'+''.join(f\"<option value='{x['id']}'>{esc(user_display_name(x))}</option>\" for x in users)\n        with db() as con: assignees_html_task=assignee_html(con,'task')",'widget'),
        ("        parts=[]","        with db() as con: task_people=task_assignees_map(con,[r['id'] for r in rows])\n        parts=[]", 'mapa wykonawców'),
        ("            if r['assigned_name']: assigned=r['assigned_name']+((' — '+r['assigned_function']) if r['assigned_function'] else '')","            if r['assigned_name']: assigned=r['assigned_name']+((' — '+r['assigned_function']) if r['assigned_function'] else '')\n            assigned=task_people.get(r['id']) or assigned", 'współwykonawcy'),
        ("        <div class='full'><label>Wykonawca</label><select name='assigned_user_id'>{user_opts}</select></div>",'', 'stary wybór wykonawcy'),
        ("        <div class='full'><button class='btn primary'>Dodaj zadanie</button></div></form>",
         "        <input type='hidden' name='_multi_assignees' value='1'>{assignees_html_task}<div class='full'><button class='btn primary'>Dodaj zadanie</button></div></form>",'checkboxes')], 'tasks_page')
    # Szybkie dodawanie: jeden widget używany w formularzu zadania i w kalkulatorze.
    src=method_change(src,'    def quick_add_page(self,qs):','    def deadline_page(self,qs):',[
        ("        case_opts,user_opts=self._quick_case_and_user_options()",
         "        case_opts,user_opts=self._quick_case_and_user_options()\n        with db() as con: assignees_html_task=assignee_html(con,'task')",'widget'),
        ("<div><label>Wykonawca</label><select name='assigned_user_id'>{user_opts}</select></div>",'', 'single task'),
        ("<div class='full'><label>Wykonawca</label><select name='assigned_user_id'>{user_opts}</select></div>",'', 'single deadline'),
        ("<div class='full'><button class='btn primary'>Dodaj</button></div></form></div>",
         "<input type='hidden' name='_multi_assignees' value='1'>{assignees_html_task}<div class='full'><button class='btn primary'>Dodaj</button></div></form></div>",'nowe zadanie'),
        ("<div class='full'><button class='btn primary'>Wylicz i dodaj termin</button></div></form></div>",
         "<input type='hidden' name='_multi_assignees' value='1'>{assignees_html_task}<div class='full'><button class='btn primary'>Wylicz i dodaj termin</button></div></form></div>",'termin')], 'quick_add_page')
    # Terminy wyliczane i zadania: zapis dodatkowych przypisań wewnątrz transakcji.
    src=method_change(src,'    def deadline_create(self,f):','    def quick_event_add(self,f):',[
        ('            sync_task_alert(con,cur.lastrowid,a)',
         "            if f.get('_multi_assignees')=='1':\n                set_task_assignees(con,cur.lastrowid,selected_ids(f,con))\n            sync_task_alert(con,cur.lastrowid,a",'sync')], 'deadline_create')
    src=method_change(src,'    def task_add(self,cid,f):','    def task_add_global(self,f):',[
        ('            sync_task_alert(con,cur.lastrowid,a)',
         "            if f.get('_multi_assignees')=='1':\n                ids=selected_ids(f,con)\n                set_task_assignees(con,cur.lastrowid,ids)\n                assigned=ids[0] if ids else None\n            sync_task_alert(con,cur.lastrowid,a",'sync')], 'task_add')
    # W starym edytorze zachowaj listę wielu wykonawców przy niezmienionym 'głównym'.
    src=method_change(src,'    def task_update(self,tid,f):','    def document_edit(self,did):',[
        ('            sync_task_alert(con,tid,a)',
         "            if old['assigned_user_id'] != assigned:\n                set_task_assignees(con,tid,[assigned] if assigned else [])\n            sync_task_alert(con,tid,a",'legacy edit')], 'task_update')
    # Od tej pory wersja źródła jest jednoznaczna.
    compile(src,'app.py','exec')
    return src


def update(root,dry_run=False):
    root=Path(root).resolve()
    for f in ('app.py','rk_workspace_plus.py','README.md'):
        if not (root/f).is_file():raise RuntimeError('Brak wymaganego pliku '+f)
    compile((root/'rk_workspace_plus.py').read_text(encoding='utf-8'),'rk_workspace_plus.py','exec')
    old=(root/'app.py').read_text(encoding='utf-8');new=apply_app(old)
    oldread=(root/'README.md').read_text(encoding='utf-8')
    extra='''\n\n## RK KANCELARIA 0.3.7-dev1 — Kalendarz, zespoły i sprawy poboczne
- Wiele niezależnych terminów ustalonych w jednej sprawie (bez automatycznego liczenia terminów ustawowych).
- Kalendarz osobisty z przypisanymi zadaniami, terminami i datami spraw prowadzonych przez danego użytkownika.
- Zadania i terminy przypisywane wielu użytkownikom, z zachowaniem dotychczasowych przypisań.
- Tworzenie odrębnych spraw pobocznych z kontrolą wymaganych dokumentów/czynności.
- Skróty nawigacyjne na każdym ekranie i kalendarz otwierany po kliknięciu zegara na pulpicie.
- Addytywna migracja SQLite do 328. Program nie podejmuje samodzielnych decyzji prawnych.
'''
    readme=oldread if '## RK KANCELARIA 0.3.7-dev1' in oldread else oldread+extra
    if dry_run:
        print('OK: analiza aktualizacji 0.3.7; nie zapisano danych.')
        return
    updates=[(root/'app.py',old,new),(root/'README.md',oldread,readme)]
    changed=[]
    try:
        for path,before,after in updates:
            if before==after:continue
            fd,tmp=tempfile.mkstemp(dir=root,prefix='.rk-037-',suffix='.tmp')
            with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as file:file.write(after)
            os.replace(tmp,path)
            changed.append((path,before))
    except BaseException:
        for path,before in reversed(changed):path.write_text(before,encoding='utf-8')
        raise
    print('RK KANCELARIA 0.3.7-dev1: zintegrowano; zmodyfikowano:',*[p.name for p,_ in changed])


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('root',nargs='?',default='.');ap.add_argument('--dry-run',action='store_true');args=ap.parse_args()
    try:update(args.root,args.dry_run)
    except Exception as e:print('BŁĄD INTEGRACJI 0.3.7:',e,file=sys.stderr);raise SystemExit(1)
