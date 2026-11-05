# -*- coding: utf-8 -*-
"""RK KANCELARIA 0.3.6-dev1 — usuwanie terminów i nawigacja po rekordach.

Patcher idempotentny. Nie otwiera bazy danych, nie przetwarza katalogu Data.
Wykonuje zmiany wyłącznie w kodzie źródłowym, z atomowym zapisem i kontrolą kotwic.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys
import tempfile

VERSION='0.3.6-dev1'
MARK='from rk_record_navigation import case_deadline_rows, linked_records_panel, safe_back'


def once(s,old,new,label):
    n=s.count(old)
    if n!=1:
        raise RuntimeError(f'{label}: oczekiwano 1 fragmentu, znaleziono {n}. Nie zapisano zmian.')
    return s.replace(old,new,1)


def apply_app(src):
    if MARK in src:
        required=('VERSION = "0.3.6-dev1"','SCHEMA_VERSION = 327',
                  'case_deadline_rows(tasks,alerts,c,fmt_date',
                  'def clear_case_next_date(',
                  'linked_records_panel(con,\'task\',t)',
                  'for kind, title, cid, pr, url in items[:5]:',
                  'self.clear_case_next_date(',
                  "'/task/{r['id']}/edit")
        if all(x in src for x in required):return src
        raise RuntimeError('Niekompletna wcześniejsza integracja 0.3.6 — źródła bez zmian.')
    if 'VERSION = "0.3.5-dev1"' not in src or 'SCHEMA_VERSION = 326' not in src:
        raise RuntimeError('Wymagana zintegrowana wersja 0.3.5-dev1 — Obieg korespondencji.')
    if 'from rk_correspondence import CorrespondenceMixin, ensure_correspondence_schema' not in src:
        raise RuntimeError('Nie znaleziono modułu Obieg korespondencji 0.3.5.')
    src=once(src,'from rk_correspondence import CorrespondenceMixin, ensure_correspondence_schema',
             'from rk_correspondence import CorrespondenceMixin, ensure_correspondence_schema\n'+MARK,'import nawigacji')
    src=once(src,'VERSION = "0.3.5-dev1"','VERSION = "0.3.6-dev1"','numer wersji')
    src=once(src,'SCHEMA_VERSION = 326','SCHEMA_VERSION = 327','wersja schematu')
    # Karta sprawy: terminy z typem źródła, edycją i operacją usuwania.
    old='''            deadline_rows=[]
            seen=set()
            for d,k,t in next_dates:
                key=(d,t)
                if key in seen: continue
                seen.add(key); deadline_rows.append(f"<tr><td><b>{fmt_date(d)}</b></td><td>{esc(k)}</td><td>{esc(t)}</td></tr>")'''
    src=once(src,old,
             '            deadline_table_html=case_deadline_rows(tasks,alerts,c,fmt_date,is_readonly=readonly)',
             'zakładka Terminy — identyfikatory zamiast tytułów')
    src=once(src,
             '<table><tr><th>Data</th><th>Rodzaj</th><th>Czynność</th></tr>{\'\'.join(deadline_rows) or \'<tr><td colspan=3>Brak terminów.</td></tr>\'}</table>',
             '<table><tr><th>Data</th><th>Źródło</th><th>Czynność — otwórz</th><th>Akcje</th></tr>{deadline_table_html or \'<tr><td colspan=4>Brak terminów.</td></tr>\'}</table>',
             'tabela Terminy — linki i przyciski')
    # Wyraźnie odróżniaj usuwanie terminu-zadania od daty w karcie sprawy.
    src=once(src,'            if path == "/deadline": return self.deadline_page(qs)',
             '            if path == "/deadline": return self.deadline_page(qs)', 'spójność GET')
    src=once(src,'            if path == "/deadline/create": return self.deadline_create(fields)',
             '            if path == "/deadline/create": return self.deadline_create(fields)\n'
             '            if re.fullmatch(r"/case/\\d+/clear-next-date",path): return self.clear_case_next_date(int(path.split("/")[2]),fields)',
             'POST wyczyść następną datę')
    meth='''    def clear_case_next_date(self,cid,f):
        author=self.current_author(f)
        with db() as con:
            row=con.execute('SELECT id,title,next_date,next_step FROM cases WHERE id=?',(cid,)).fetchone()
            if not row:return self.send_error(404)
            if case_read_only(con,cid):return self.send_error(403)
            if row['next_date']:
                con.execute("UPDATE cases SET next_date='',next_step='',updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(author,cid))
                audit(con,cid,'case',cid,'Wyczyszczono następny termin sprawy',
                    f"Data: {row['next_date']} · czynność: {row['next_step']}",author)
        return self.redirect(safe_back(f.get('return_to'),f'/case/{cid}?tab=deadlines'))

'''
    src=once(src,'    def deadline_create(self,f):',meth+'    def deadline_create(self,f):','czyszczenie daty sprawy')
    # Wyszukiwanie powiązanych dokumentów, terminów, projektów, korespondencji.
    src=once(src,'        if not t: return self.send_error(404)\n        prio=',
             "        if not t: return self.send_error(404)\n"
             "        with db() as con: related_nav=linked_records_panel(con,'task',t)\n"
             "        prio=",'panel w zadaniu')
    src=once(src,"        self.send_html(layout('Edycja zadania',body,'tasks'))",
             '''        # Przycisk usunięcia również dla Terminów procesowych; operacja przenosi do Kosza.
        body += related_nav
        body += (f"<div class='card'><h3>Usuń zadanie / termin</h3>"
                 f"<form method='post' action='/task/{tid}/delete' "
                 "onsubmit='return confirm(&quot;Przenieść termin lub zadanie do Kosza?&quot;)'>"
                 f"<input type='hidden' name='case_id' value='{t['case_id']}'>"
                 f"<input type='hidden' name='return_to' value='{esc(safe_back(return_to,back_href))}'>"
                 "<button class='btn danger' type='submit'>Przenieś do Kosza</button></form></div>")
        self.send_html(layout('Edycja zadania',body,'tasks'))''','usuwanie z edytora terminu')
    # Kontekst dokumentu i projektu pisma (bez kopiowania plików).
    src=once(src,"        self.send_html(layout('Podgląd dokumentu',extra_css+body,'documents'))",
             "        with db() as con: body += linked_records_panel(con,'document',d)\n"
             "        self.send_html(layout('Podgląd dokumentu',extra_css+body,'documents'))",
             'odnośniki w dokumentach')
    src=once(src,"        self.send_html(layout('Projekt pisma',body,'drafts'))",
             "        with db() as con: body += linked_records_panel(con,'draft',d)\n"
             "        self.send_html(layout('Projekt pisma',body,'drafts'))",
             'odnośniki w projektach')
    # Tytuły w listach od razu przechodzą do właściwego zadania.
    src=once(src,
             "<span class='mini-badge'>{esc(row_get(t,'task_type','Zadanie'))}</span> <b>{esc(t['title'])}</b><small>",
             "<span class='mini-badge'>{esc(row_get(t,'task_type','Zadanie'))}</span> <a class='case-link' href='/task/{t['id']}/edit?return_to=%2Fcase%2F{cid}%3Ftab%3Dtasks'><b>{esc(t['title'])}</b></a><small>",
             'kliknięcie zadania w warsztacie sprawy')
    src=once(src,
             "<span class='mini-badge'>{esc(row_get(t,'task_type','Zadanie') or 'Zadanie')}</span> <b>{esc(t['title'])}</b></div>",
             "<span class='mini-badge'>{esc(row_get(t,'task_type','Zadanie') or 'Zadanie')}</span> <a class='case-link' href='/task/{t['id']}/edit'><b>{esc(t['title'])}</b></a></div>",
             'kliknięcie zadania w prostym widoku sprawy')
    src=once(src,
             "<span class='mini-badge'>{esc(row_get(r,'task_type','Zadanie') or 'Zadanie')}</span> <b>{esc(r['title'])}</b>{dep}{deadline_meta}",
             "<span class='mini-badge'>{esc(row_get(r,'task_type','Zadanie') or 'Zadanie')}</span> <a class='case-link' href='/task/{r['id']}/edit'><b>{esc(r['title'])}</b></a>{dep}{deadline_meta}",
             'kliknięcie zadania w globalnej liście')
    src=once(src,
             "<td><b>{esc(r['title'])}</b>{assigned}{meta}</td>",
             "<td><a class='case-link' href='/task/{r['id']}/edit'><b>{esc(r['title'])}</b></a>{assigned}{meta}</td>",
             'kliknięcie zadania z widoku Dzisiaj')
    src=once(src,
             "<td><b class='{cls}'>{esc(r['title'])}</b>{dep}</td>",
             "<td><a class='case-link' href='/task/{r['id']}/edit'><b class='{cls}'>{esc(r['title'])}</b></a>{dep}</td>",
             'zadania z datą na Pulpicie')
    src=once(src,
             "<td><b>{esc(r['title'])}</b>{dep}</td>",
             "<td><a class='case-link' href='/task/{r['id']}/edit'><b>{esc(r['title'])}</b></a>{dep}</td>",
             'zadania bez daty na Pulpicie')
    # Kalendarz przechowuje URL, nie tylko nazwę i numer sprawy.
    src=once(src,
             "        def add_item(d, kind, title, cid=0, priority='normal'):",
             "        def add_item(d, kind, title, cid=0, priority='normal', url=''):",
             'tożsamość pozycji kalendarza')
    src=once(src,
             "            key=(str(d),int(cid or 0),norm)",
             "            key=(str(d),int(cid or 0),url or norm)",
             'bez zlewania różnych rekordów w kalendarzu')
    src=once(src,
             "            bydate.setdefault(d, []).append((kind, title, cid, priority))",
             "            bydate.setdefault(d, []).append((kind, title, cid, priority, url))",
             'kalendarz — URL w wydarzeniu')
    src=once(src,
             "            add_item(r['alert_date'], r['alert_type'], r['title'], r['case_id'] or 0, r['priority'])",
             "            alert_target=(f\"/task/{r['source_id']}/edit\" if r['source_type']=='task' and r['source_id'] else (f\"/case/{r['case_id']}?tab=deadlines\" if r['case_id'] else '/calendar'))\n"
             "            add_item(r['alert_date'], r['alert_type'], r['title'], r['case_id'] or 0, r['priority'],alert_target)",
             'odnośniki alertów w kalendarzu')
    src=once(src,
             "            add_item(r['due_date'], 'Zadanie', r['title'], r['case_id'], r['priority'])",
             "            add_item(r['due_date'], 'Zadanie', r['title'], r['case_id'], r['priority'],f\"/task/{r['id']}/edit\")",
             'zadania w kalendarzu')
    src=once(src,
             "                add_item(r['event_date'], r['event_type'] or 'Proces', r['title'], r['case_id'], 'normal')",
             "                add_item(r['event_date'], r['event_type'] or 'Proces', r['title'], r['case_id'], 'normal',f\"/process-event/{r['id']}/edit\")",
             'zdarzenia procesowe w kalendarzu')
    src=once(src,
             "                add_item(r['next_date'], 'Następny termin', r['title'], r['case_id'], 'high')",
             "                add_item(r['next_date'], 'Następny termin', r['title'], r['case_id'], 'high',f\"/process-event/{r['id']}/edit\")",
             'następna data zdarzenia procesowego')
    src=once(src,
             "            add_item(r['event_date'], r['event_type'] or 'Czynność', r['title'], r['case_id'], 'normal')",
             "            add_item(r['event_date'], r['event_type'] or 'Czynność', r['title'], r['case_id'], 'normal',f\"/event/{r['id']}/edit\")",
             'zdarzenia kancelarii w kalendarzu')
    src=once(src,
             "                add_item(r['next_date'], 'Termin', r['next_step'] or r['title'], r['id'], 'high')",
             "                add_item(r['next_date'], 'Termin', r['next_step'] or r['title'], r['id'], 'high',f\"/case/{r['id']}/edit\")",
             'termin główny sprawy w kalendarzu')
    src=once(src,
             "            for kind, title, cid, pr in items[:5]:",
             "            for kind, title, cid, pr, url in items[:5]:",
             'otwieranie pozycji kalendarza')
    src=once(src,
             "                event_parts.append(f\"<a class='calendar-event p-{esc(pr)}' href='/case/{cid}'>{content}</a>\" if cid else f\"<div class='calendar-event p-{esc(pr)}'>{content}</div>\")",
             "                target=url or (f'/case/{cid}' if cid else '')\n"
             "                event_parts.append(f\"<a class='calendar-event p-{esc(pr)}' href='{esc(target)}'>{content}</a>\" if target else f\"<div class='calendar-event p-{esc(pr)}'>{content}</div>\")",
             'linki kalendarza do właściwych obiektów')
    compile(src,'app.py','exec')
    return src


def update(root:Path,dry_run:bool=False):
    root=root.resolve()
    for name in ('app.py','README.md','rk_record_navigation.py'):
        if not (root/name).is_file():raise RuntimeError('Brakuje pliku '+name)
    compile((root/'rk_record_navigation.py').read_text(encoding='utf-8'),'rk_record_navigation.py','exec')
    original=(root/'app.py').read_text(encoding='utf-8')
    new=apply_app(original)
    old_readme=(root/'README.md').read_text(encoding='utf-8')
    readme=old_readme
    if readme.startswith('# RK KANCELARIA 0.3.5-dev1'):
        readme=readme.replace('# RK KANCELARIA 0.3.5-dev1','# RK KANCELARIA 0.3.6-dev1',1)
    if '## Terminy i nawigacja — 0.3.6-dev1' not in readme:
        readme += '''\n\n## Terminy i nawigacja — 0.3.6-dev1\n\n- W zakładce **Terminy** widoczny jest rzeczywisty rekord źródłowy, odnośnik i przycisk przeniesienia zadania/alertu do Kosza.\n- Datę „następnej czynności w sprawie” można osobno wyczyścić; nie jest zadaniem.\n- Tytuły zadań są klikalne w warsztacie sprawy, widoku Dzisiaj, Pulpicie, listach i kalendarzu.\n- W edytorze zadań, dokumentach i projektach pism jest panel powiązań z innymi rekordami.\n- W kalendarzu kliknięcie prowadzi do konkretnego zadania, zdarzenia lub sprawy zamiast zawsze do ogólnej karty.\n- Usunięcie zadania zachowuje mechanizm Kosza i historii. Nie usuwamy żadnych wpisów w czasie migracji.\n- Odnośniki opierają się wyłącznie na rzeczywistych identyfikatorach, bez zgadywania relacji po nazwie.\n'''
    if dry_run:
        print('0.3.6-dev1: patch poprawny; nie zapisano zmian.')
        return
    changes=[]
    try:
        for target,before,after in ((root/'app.py',original,new),(root/'README.md',old_readme,readme)):
            if before==after:continue
            fd,tmp=tempfile.mkstemp(prefix='.rk-links-',suffix='.tmp',dir=root)
            try:
                with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:f.write(after)
                os.replace(tmp,target)
                changes.append((target,before))
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
    except Exception:
        for target,before in reversed(changes):target.write_text(before,encoding='utf-8')
        raise
    print('RK KANCELARIA 0.3.6-dev1: '+(', '.join(x.name for x,_ in changes) or 'już zainstalowano'))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('root',nargs='?',default='.')
    p.add_argument('--dry-run',action='store_true')
    args=p.parse_args()
    try:update(Path(args.root),args.dry_run)
    except Exception as e:
        print('BŁĄD INTEGRACJI NAWIGACJI: '+str(e),file=sys.stderr)
        raise SystemExit(1)
