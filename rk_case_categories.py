# -*- coding: utf-8 -*-
"""RK KANCELARIA 0.3.7: otwarty katalog kategorii spraw, wiele-do-wielu."""
from __future__ import annotations
import html
import re
import sqlite3
import sys

DEFAULTS=('Sprawa cywilna','Sprawa karna','Sprawa administracyjna','Sprawa rodzinna',
          'Sprawa gospodarcza','Sprawa z zakresu prawa pracy','Sprawa spadkowa','Sprawa egzekucyjna','Inna')
ALIASES={x.casefold():x for x in DEFAULTS}
ALIASES.update({'cywilna':DEFAULTS[0],'karna':DEFAULTS[1], 'administracyjna':DEFAULTS[2],
                'rodzinna':DEFAULTS[3], 'gospodarcza':DEFAULTS[4], 'spadkowa':DEFAULTS[6],
                'egzekucyjna':DEFAULTS[7]})

def esc(v):return html.escape(str(v if v is not None else ''),quote=True)
def _app(obj):return sys.modules[type(obj).__module__]

def normalized(v,legacy=False):
    name=' '.join(str(v or '').strip().split())
    if len(name)>90 or any(ord(c)<32 for c in name):raise ValueError('Nazwa kategorii ma maksymalnie 90 znaków.')
    return ALIASES.get(name.casefold(),name) if legacy else name

def get_or_create(con,name):
    name=normalized(name)
    if not name:raise ValueError('Nazwa kategorii jest wymagana.')
    con.execute('INSERT OR IGNORE INTO case_category_catalog(name) VALUES(?)',(name,))
    return con.execute('SELECT id FROM case_category_catalog WHERE name=? COLLATE NOCASE',(name,)).fetchone()[0]

def legacy_to_categories(con,cid,category):
    for part in re.split('[;,]',str(category or '')):
        n=normalized(part,True)
        if n:
            con.execute('INSERT OR IGNORE INTO case_category_assignments(case_id,category_id) VALUES(?,?)',
                        (cid,get_or_create(con,n)))

def ensure_case_categories_schema(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS case_category_catalog(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL UNIQUE COLLATE NOCASE,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS case_category_assignments(
      case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
      category_id INTEGER NOT NULL REFERENCES case_category_catalog(id) ON DELETE RESTRICT,
      PRIMARY KEY(case_id,category_id));
    CREATE INDEX IF NOT EXISTS idx_case_category_filter ON case_category_assignments(category_id,case_id);
    ''')
    for name in DEFAULTS:get_or_create(con,name)
    for row in con.execute("SELECT id,category FROM cases WHERE TRIM(COALESCE(category,''))<>''"):
        if not con.execute('SELECT 1 FROM case_category_assignments WHERE case_id=?',(row['id'],)).fetchone():
            legacy_to_categories(con,row['id'],row['category'])

def names_for(con,cid):
    return [r[0] for r in con.execute('''SELECT c.name FROM case_category_assignments a
        JOIN case_category_catalog c ON c.id=a.category_id WHERE a.case_id=? ORDER BY c.name COLLATE NOCASE''',(cid,))]

def save_categories(con,cid,fields):
    if fields.get('_categories_form')!='1':return None
    if not con.execute('SELECT 1 FROM cases WHERE id=?',(cid,)).fetchone():raise ValueError('Sprawa nie istnieje.')
    ids=[]
    for key,value in fields.items():
        if key.startswith('case_cat_') and str(value) in ('1','on'):
            value_id=key[9:]
            if not value_id.isascii() or not value_id.isdecimal():raise ValueError('Niepoprawna kategoria.')
            ids.append(int(value_id))
    ids=sorted(set(ids))
    if ids:
        q=','.join('?' for _ in ids)
        valid={r[0] for r in con.execute(f'SELECT id FROM case_category_catalog WHERE id IN ({q})',ids)}
        if valid!=set(ids):raise ValueError('Wybrano nieistniejącą kategorię.')
    fresh=normalized(fields.get('new_category_name'))
    if fresh:ids.append(get_or_create(con,fresh))
    ids=sorted(set(ids))
    before=names_for(con,cid)
    con.execute('DELETE FROM case_category_assignments WHERE case_id=?',(cid,))
    con.executemany('INSERT INTO case_category_assignments(case_id,category_id) VALUES(?,?)',((cid,i) for i in ids))
    after=names_for(con,cid)
    con.execute('UPDATE cases SET category=? WHERE id=?',(after[0] if after else '',cid))
    return before,after

def category_form(con,cid=0):
    selected={r[0] for r in con.execute('SELECT category_id FROM case_category_assignments WHERE case_id=?',(cid,))} if cid else set()
    rows=con.execute('SELECT id,name FROM case_category_catalog ORDER BY name COLLATE NOCASE')
    labels=''.join(f'<label style="display:inline-flex;align-items:center;gap:5px;margin:5px 13px 5px 0">'
                   f'<input type="checkbox" name="case_cat_{r["id"]}" value="1" style="width:auto" '
                   f'{"checked" if r["id"] in selected else ""}> {esc(r["name"])}</label>' for r in rows)
    return ("<div class='full'><input type='hidden' name='_categories_form' value='1'>"
            "<label>Kategorie — wybierz jedną lub kilka</label><div style='display:flex;flex-wrap:wrap'>"
            +labels+"</div><label>Nowa kategoria (opcjonalnie)</label>"
            "<input name='new_category_name' maxlength='90' placeholder='np. Sprawa podatkowa'>"
            "<div class='small muted'><a href='/case-categories'>Katalog kategorii spraw</a></div></div>")

def category_map(con,case_ids):
    case_ids=sorted(set(int(x) for x in case_ids))
    if not case_ids:return {}
    q=','.join('?' for _ in case_ids)
    rows=con.execute(f'''SELECT a.case_id,c.id,c.name FROM case_category_assignments a
        JOIN case_category_catalog c ON c.id=a.category_id
        WHERE a.case_id IN ({q}) ORDER BY c.name COLLATE NOCASE''',case_ids)
    result={}
    for r in rows:result.setdefault(r['case_id'],[]).append((r['id'],r['name']))
    return result

def category_chips(pairs):
    if not pairs:return '<span class="small muted">Bez kategorii</span>'
    return ' '.join(f'<a class="tag" href="/cases?category_id={i}">{esc(name)}</a>' for i,name in pairs)

class CaseCategoryMixin:
    def category_catalog_page(self):
        a=_app(self)
        with a.db() as con:
            rows=con.execute('''SELECT c.id,c.name,COUNT(x.case_id) cnt FROM case_category_catalog c
                LEFT JOIN case_category_assignments x ON x.category_id=c.id
                GROUP BY c.id ORDER BY c.name COLLATE NOCASE''').fetchall()
        table=''.join(f'''<tr><td><a class="case-link" href="/cases?category_id={r['id']}">{esc(r['name'])}</a></td>
              <td>{r['cnt']}</td><td><form method="post" action="/case-category/{r['id']}/rename">
              <input name="name" value="{esc(r['name'])}" maxlength="90" required>
              <button class="btn small">Zmień nazwę</button></form></td></tr>''' for r in rows)
        body=("<div class='topbar'><h1>Katalog kategorii spraw</h1><a class='btn' href='/cases'>Sprawy</a></div>"
              "<div class='card'><h2>Dodaj kategorię</h2><form method='post' action='/case-category/create' class='form-grid'>"
              "<input name='name' required maxlength='90' placeholder='np. Sprawa podatkowa'>"
              "<button class='btn primary'>Dodaj</button></form></div>"
              "<div class='card table-scroll'><table><tr><th>Kategoria — kliknij, aby filtrować</th><th>Spraw</th><th>Nazwa</th></tr>"
              +table+'</table></div>')
        self.send_html(a.layout('Katalog kategorii',body,'case-categories'))

    def category_create(self,f):
        a=_app(self)
        try:
            with a.db() as con:get_or_create(con,f.get('name'))
        except ValueError as ex:return self.send_error(400,str(ex))
        self.redirect('/case-categories')

    def category_rename(self,category_id,f):
        a=_app(self)
        try:
            name=normalized(f.get('name'))
            if not name:raise ValueError('Nazwa kategorii jest wymagana.')
            with a.db() as con:
                old=con.execute('SELECT id FROM case_category_catalog WHERE id=?',(category_id,)).fetchone()
                if not old:return self.send_error(404)
                con.execute('UPDATE case_category_catalog SET name=? WHERE id=?',(name,category_id))
                cases=[r[0] for r in con.execute('SELECT case_id FROM case_category_assignments WHERE category_id=?',(category_id,))]
                for cid in cases:
                    arr=names_for(con,cid)
                    con.execute('UPDATE cases SET category=? WHERE id=?',(arr[0] if arr else '',cid))
        except ValueError as ex:return self.send_error(400,str(ex))
        except sqlite3.IntegrityError:return self.send_error(409,'Taka kategoria już istnieje.')
        self.redirect('/case-categories')

# Alias używane przez zewnętrzne testy migracji.
category_names=names_for
category_selector=category_form
save_case_categories=save_categories
category_case_map=category_map
render_case_categories=category_chips
ensure_legacy_category=legacy_to_categories
CaseCategoriesMixin=CaseCategoryMixin

def selected_category_ids(con,fields):
    result=[]
    for key,value in fields.items():
        if key.startswith('case_cat_') and str(value) in ('1','on'):
            suffix=key[9:]
            if not suffix.isascii() or not suffix.isdecimal():raise ValueError('Niepoprawny identyfikator')
            result.append(int(suffix))
    return sorted(set(result))
