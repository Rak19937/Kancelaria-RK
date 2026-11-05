# -*- coding: utf-8 -*-
"""Drugi krok zbiorczej aktualizacji RK KANCELARIA 0.3.7-dev1.
Uruchom po ZASTOSUJ_WORKSPACE_PLUS.py. Nie dotyka folderu Data.
"""
from __future__ import annotations
import os
from pathlib import Path
import sys
import tempfile
import argparse

MARK='from rk_case_categories import CaseCategoryMixin, ensure_case_categories_schema, category_form, save_categories, category_map, category_chips'


def once(src,old,new,label):
    n=src.count(old)
    if n!=1:raise RuntimeError(f'{label}: oczekiwano jednej kotwicy, znaleziono {n}. Niczego nie zapisano.')
    return src.replace(old,new,1)


def patch_method(src,start,end,steps,label):
    i=src.find(start);j=src.find(end,i+len(start)) if i>=0 else -1
    if i<0 or j<0:raise RuntimeError(f'{label}: brak granic metody.')
    frag=src[i:j]
    for old,new,step in steps:frag=once(frag,old,new,label+'/'+step)
    return src[:i]+frag+src[j:]


def apply_app(src):
    if MARK in src:
        must=['SCHEMA_VERSION = 329','ensure_case_categories_schema(con)',
              'self.category_catalog_page()', 'save_categories(con,cid,f)',
              'category_filter_control', 'category_form(con,cid)']
        if not all(x in src for x in must):raise RuntimeError('Wykryto niepełną integrację kategorii.')
        compile(src,'app.py','exec')
        return src
    if 'VERSION = "0.3.7-dev1"' not in src or 'SCHEMA_VERSION = 328' not in src:
        raise RuntimeError('Wymagana uprzednia integracja 0.3.7-dev1 (schemat 328).')
    src=once(src,
       'from rk_workspace_plus import WorkspacePlusMixin, ensure_workspace_plus_schema, appointments_table, assignee_html, selected_ids, set_task_assignees, nav_strip, linked_sidecases, archived_appointments_html, task_assignees_map, upcoming_alerts_multi as upcoming_alerts',
       'from rk_workspace_plus import WorkspacePlusMixin, ensure_workspace_plus_schema, appointments_table, assignee_html, selected_ids, set_task_assignees, nav_strip, linked_sidecases, archived_appointments_html, task_assignees_map, upcoming_alerts_multi as upcoming_alerts\n'+MARK,
       'import')
    src=once(src,'SCHEMA_VERSION = 328','SCHEMA_VERSION = 329','schemat')
    src=once(src,
       'class Handler(WorkspacePlusMixin, CorrespondenceMixin, ActionCenterMixin, DocumentHubMixin, InboxMixin, BaseHTTPRequestHandler):',
       'class Handler(CaseCategoryMixin, WorkspacePlusMixin, CorrespondenceMixin, ActionCenterMixin, DocumentHubMixin, InboxMixin, BaseHTTPRequestHandler):',
       'Handler')
    src=once(src,'        ensure_workspace_plus_schema(con)',
             '        ensure_workspace_plus_schema(con)\n        ensure_case_categories_schema(con)', 'migracja')
    src=once(src,'            ("/cases", "§", "Sprawy", "cases"),',
             '            ("/cases", "§", "Sprawy", "cases"),\n'
             '            ("/case-categories", "▧", "Kategorie spraw", "case-categories"),','menu')
    src=once(src,'            if path == "/cases": return self.cases(qs, closed_only=False)',
             '            if path == "/cases": return self.cases(qs, closed_only=False)\n'
             '            if path == "/case-categories": return self.category_catalog_page()', 'GET')
    src=once(src,'            if path == "/deadline/create": return self.deadline_create(fields)',
             '            if path == "/deadline/create": return self.deadline_create(fields)\n'
             '            if path == "/case-category/create": return self.category_create(fields)\n'
             '            if re.fullmatch(r"/case-category/\\d+/rename",path): return self.category_rename(int(path.split("/")[2]),fields)', 'POST')
    src=patch_method(src,'    def case_new(self):','    def case_create(self, f):',[
        ('            entities=con.execute("SELECT id,display_name,pesel,nip,krs FROM entities ORDER BY display_name COLLATE NOCASE").fetchall()',
         '            entities=con.execute("SELECT id,display_name,pesel,nip,krs FROM entities ORDER BY display_name COLLATE NOCASE").fetchall()\n            category_field=category_form(con)', 'form'),
        ("        <details class='advanced-fields full'><summary>Więcej informacji — sygnatury, sąd, prowadzący, druga strona…</summary>",
         "        {category_field}<details class='advanced-fields full'><summary>Więcej informacji — sygnatury, sąd, prowadzący, druga strona…</summary>", 'show'),
        ("<div><label>Kategoria</label><input name='category' placeholder='np. cywilna, rodzinna, karna'></div>",
         "<input type='hidden' name='category' value=''>", 'legacy')
    ],'case_new')
    src=patch_method(src,'    def case_edit(self,cid):','    def case_update(self,cid,f):',[
        ('            users=con.execute("SELECT id,author_name,function FROM users WHERE is_active=1 ORDER BY author_name").fetchall()',
         '            users=con.execute("SELECT id,author_name,function FROM users WHERE is_active=1 ORDER BY author_name").fetchall()\n            category_field=category_form(con,cid)', 'form'),
        ("<div><label>Kategoria</label><input name='category' value='{esc(c['category'])}'></div>",
         "{category_field}<input type='hidden' name='category' value='{esc(c['category'])}'>", 'legacy')
    ],'case_edit')
    src=patch_method(src,'    def case_create(self, f):','    def case_edit(self,cid):',[
        ("            set_case_tags(con,cid,f.get('tags',''))",
         "            set_case_tags(con,cid,f.get('tags',''))\n            save_categories(con,cid,f)", 'save')
    ],'case_create')
    src=patch_method(src,'    def case_update(self,cid,f):','    def case_delete_confirm(self,cid,message',[
        ("            set_case_tags(con,cid,f.get('tags',''))",
         "            set_case_tags(con,cid,f.get('tags',''))\n"
         "            changes=save_categories(con,cid,f)\n"
         "            if changes and changes[0]!=changes[1]:\n"
         "                audit(con,cid,'case',cid,'Zmieniono kategorie sprawy',\n"
         "                      ', '.join(changes[0])+' → '+', '.join(changes[1]),author)", 'save')
    ],'case_update')
    src=patch_method(src,'    def case_workspace(self, cid, qs=None):','    def case_view_simple(self, cid, qs=None):',[
        ("        shown_sig,sig_kind=display_case_signature(cid,c['signature'],c['internal_signature'])",
         "        with db() as con: selected_category_html=category_chips(category_map(con,[cid]).get(cid,[]))\n"
         "        shown_sig,sig_kind=display_case_signature(cid,c['signature'],c['internal_signature'])", 'badges'),
        ("<span>{esc(c['category']) or 'Kategoria: —'}</span>",
         "<span>Kategorie: {selected_category_html}</span>",'heading')
    ],'case_workspace')
    src=patch_method(src,'    def cases(self, qs, closed_only=False):','    def case_new(self):',[
        ("        tag=(qs.get('tag') or [''])[0].strip()",
         "        tag=(qs.get('tag') or [''])[0].strip()\n"
         "        try: category_filter=int((qs.get('category_id') or ['0'])[0] or 0)\n"
         "        except ValueError: category_filter=0\n"
         "        category_filter=max(category_filter,0)", 'filter'),
        ("        if focus=='waiting': sql += \" AND c.waiting_for<>''\"",
         "        if category_filter:\n"
         "            sql += \" AND EXISTS (SELECT 1 FROM case_category_assignments cc WHERE cc.case_id=c.id AND cc.category_id=?)\"\n"
         "            params.append(category_filter)\n"
         "        if focus=='waiting': sql += \" AND c.waiting_for<>''\"", 'sql'),
        ('            rows=con.execute(sql,params).fetchall()',
         '            rows=con.execute(sql,params).fetchall()\n'
         '            category_by_case=category_map(con,[r["id"] for r in rows])\n'
         '            all_categories=con.execute("SELECT id,name FROM case_category_catalog ORDER BY name COLLATE NOCASE").fetchall()', 'map'),
        ('        def tags_for(cid,limit=3):',
         '        def categories_for(cid):return category_chips(category_by_case.get(cid,[]))\n'
         '        def tags_for(cid,limit=3):','category links'),
        ("        if tag: common.append('tag='+quote(tag))",
         "        if tag: common.append('tag='+quote(tag))\n"
         "        if category_filter: common.append('category_id='+str(category_filter))", 'persist'),
        ('''<div class='case-tags'>{tags_for(r['id']) or '<span class="small muted">bez tagów</span>'}</div>''',
         '''<div class='case-tags'>{categories_for(r['id'])} {tags_for(r['id'])}</div>''', 'cards'),
        ("<div class='case-tags' style='margin-top:5px'>{tags_for(r['id'])}</div>",
         "<div class='case-tags' style='margin-top:5px'>{categories_for(r['id'])} {tags_for(r['id'])}</div>", 'table'),
        ('        mine_hidden="<input type=\'hidden\' name=\'mine\' value=\'1\'>" if mine else \'\'',
         '        mine_hidden="<input type=\'hidden\' name=\'mine\' value=\'1\'>" if mine else \'\'\n        category_filter_control=("<div><label>Kategoria sprawy</label><select name=\'category_id\'>"\n            +"<option value=\'\'>Wszystkie kategorie</option>"\n            +\'\'.join(f"<option value=\'{r[\'id\']}\' {\'selected\' if category_filter==r[\'id\'] else \'\'}>{esc(r[\'name\'])}</option>" for r in all_categories)\n            +"</select></div>")', 'dropdown'),
        ("{status_filter}<div class='full'><button class='btn'>Filtruj</button>",
         "{status_filter}{category_filter_control}<div class='full'><button class='btn'>Filtruj</button>", 'filter ui'),
        ('        new_button=\'\' if closed_only else \'<a class="btn primary" href="/case/new">+ Nowa sprawa</a>\'',
         '        new_button=\'\' if closed_only else \'<a class="btn primary" href="/case/new">+ Nowa sprawa</a>\'\n        extra_action += \' <a class="btn" href="/case-categories">Kategorie spraw</a>\'', 'catalogue'),
    ],'cases')
    compile(src,'app.py','exec')
    return src


def update(root,dry_run=False):
    root=Path(root).resolve()
    for fn in ('app.py','rk_case_categories.py','README.md'):
        if not (root/fn).is_file():raise RuntimeError('Brakuje '+fn)
    compile((root/'rk_case_categories.py').read_text(encoding='utf-8'),'rk_case_categories.py','exec')
    p=root/'app.py';original=p.read_text(encoding='utf-8');updated=apply_app(original)
    readme=root/'README.md';old=readme.read_text(encoding='utf-8')
    extra='''\n\n## RK KANCELARIA 0.3.7-dev1 — otwarty katalog kategorii\n- Wiele kategorii w jednej sprawie, własne kategorie, filtrowanie i zmiana nazw.\n- Stare kategorie przenoszone bez usuwania historii.\n- Katalog korzysta wyłącznie z lokalnej bazy.\n'''
    new=old if '## RK KANCELARIA 0.3.7-dev1 — otwarty katalog kategorii' in old else old+extra
    if dry_run:
        print('OK: katalog kategorii; test bez zapisu.');return
    modified=[]
    try:
        for file,before,after in ((p,original,updated),(readme,old,new)):
            if before==after:continue
            fd,t=tempfile.mkstemp(prefix='.rk-category-',suffix='.tmp',dir=root)
            with os.fdopen(fd,'w',encoding='utf8',newline='\n') as h:h.write(after)
            os.replace(t,file);modified.append((file,before))
    except BaseException:
        for file,prior in reversed(modified):file.write_text(prior,encoding='utf8')
        raise
    print('RK KANCELARIA: zintegrowano kategorie spraw, schemat 329.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',nargs='?',default='.')
    parser.add_argument('--dry-run',action='store_true');args=parser.parse_args()
    try:update(args.root,args.dry_run)
    except Exception as e:print('BŁĄD KATEGORII:',e,file=sys.stderr);raise SystemExit(1)
