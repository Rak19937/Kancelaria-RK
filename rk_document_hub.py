# -*- coding: utf-8 -*-
"""RK KANCELARIA: rejestr pełnomocnictw i powiązania dokumentów ze sprawami.

Brak kopiowania plików. Wiele spraw wskazuje ten sam dokument.
Żadnych zmian w danych istniejących dokumentów podczas migracji schematu.
"""
from __future__ import annotations

import html
import sqlite3
import sys
from urllib.parse import quote
from rk_domains.documents.repository import case_document_rows


def esc(value) -> str:
    return html.escape(str(value or ''), quote=True)


def ensure_document_hub_schema(con: sqlite3.Connection) -> None:
    con.executescript('''
    CREATE TABLE IF NOT EXISTS document_case_links (
        document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (document_id, case_id)
    );
    CREATE INDEX IF NOT EXISTS idx_document_case_links_case ON document_case_links(case_id,document_id);
    CREATE TABLE IF NOT EXISTS powers_of_attorney (
        document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
        principal TEXT NOT NULL DEFAULT '',
        representative TEXT NOT NULL DEFAULT '',
        authorization_scope TEXT NOT NULL DEFAULT '',
        granted_on TEXT NOT NULL DEFAULT '',
        validity_status TEXT NOT NULL DEFAULT 'do weryfikacji',
        notes TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    ''')




class DocumentHubMixin:
    def _hub_app(self):
        return sys.modules[type(self).__module__]

    def _hub_error(self, message: str, status: int = 400, target: str = '/documents'):
        a = self._hub_app()
        body = ("<div class='card'><h1>Operacja nie została wykonana</h1>"
                f"<p>{esc(message)}</p><a class='btn' href='{esc(target)}'>Wróć</a></div>")
        return self.send_html(a.layout('Dokumenty', body, 'documents'), status)

    def document_links_page(self, did: int):
        a = self._hub_app()
        with a.db() as con:
            d = con.execute('SELECT * FROM documents WHERE id=?', (did,)).fetchone()
            if not d:
                return self.send_error(404)
            owned = con.execute('SELECT id,title,signature,internal_signature FROM cases WHERE id=?', (d['case_id'],)).fetchone()
            links = con.execute('''SELECT c.id,c.title,c.signature,c.internal_signature FROM document_case_links l
                JOIN cases c ON c.id=l.case_id WHERE l.document_id=? ORDER BY c.title''',(did,)).fetchall()
            available = con.execute('''SELECT id,title,signature,internal_signature FROM cases
                WHERE id<>? AND id NOT IN (SELECT case_id FROM document_case_links WHERE document_id=?)
                ORDER BY title LIMIT 1000''', (d['case_id'],did)).fetchall()
            poa = con.execute('SELECT document_id FROM powers_of_attorney WHERE document_id=?',(did,)).fetchone()
        def case_label(c):
            return f"{c['signature'] or c['internal_signature'] or 'Bez sygnatury'} — {c['title']}"
        opts = ''.join(f"<option value='{c['id']}'>{esc(case_label(c))}</option>" for c in available)
        parts = [f"<li><a href='/case/{owned['id']}?tab=documents'>{esc(case_label(owned))}</a> <small>(sprawa źródłowa)</small></li>"] if owned else []
        for c in links:
            parts.append(f"<li><a href='/case/{c['id']}?tab=documents'>{esc(case_label(c))}</a> "
                         f"<form method='post' action='/document/{did}/unlink' style='display:inline'>"
                         f"<input type='hidden' name='case_id' value='{c['id']}'>"
                         "<button class='btn small' type='submit'>Odłącz</button></form></li>")
        options = f"<option value=''>— wybierz sprawę —</option>{opts}"
        body = f"""<div class='topbar'><div><h1>Powiązania dokumentu</h1>
          <div class='sub'>{esc(d['title'])}</div></div>
          <a class='btn' href='/document/{did}/open'>Wróć do dokumentu</a></div>
          <div class='card'><h2>Przypisane sprawy</h2><ul>{''.join(parts)}</ul>
          <p class='small muted'>Odłączenie ze sprawy dodatkowej nie usuwa dokumentu ani pliku.
          Sprawy źródłowej nie można odłączyć z tego widoku.</p></div>
          <div class='card'><h2>Dodaj powiązanie bez kopiowania pliku</h2>
          <form method='post' action='/document/{did}/link' class='form-grid'>
          <div class='full'><label>Dodatkowa sprawa</label><select name='case_id' required>{options}</select></div>
          <div><button class='btn primary'>Przypisz dokument</button></div></form></div>
          <div class='card'><h2>Pełnomocnictwa</h2>
          <p>{'Dokument jest w rejestrze pełnomocnictw.' if poa else 'Ten dokument nie jest jeszcze w rejestrze pełnomocnictw.'}</p>
          <a class='btn' href='/powers'>Przejdź do rejestru pełnomocnictw</a></div>"""
        return self.send_html(a.layout('Powiązania dokumentu', body, 'documents'))

    def document_link_add(self, did: int, fields):
        a = self._hub_app()
        try:
            cid = int(fields.get('case_id') or 0)
        except (ValueError, TypeError):
            cid = 0
        with a.db() as con:
            doc = con.execute('SELECT id,case_id,title FROM documents WHERE id=?',(did,)).fetchone()
            c = con.execute('SELECT id FROM cases WHERE id=?',(cid,)).fetchone()
            if not doc or not c:
                return self._hub_error('Nie znaleziono dokumentu lub sprawy.',404)
            if a.case_read_only(con, cid):
                return self._hub_error('Sprawa jest zablokowana przed zmianami.',403,f'/document/{did}/links')
            if cid != doc['case_id']:
                con.execute('INSERT OR IGNORE INTO document_case_links(document_id,case_id,created_by) VALUES(?,?,?)',
                            (did,cid,self.current_author(fields)))
                a.audit(con,cid,'document',did,'Powiązano istniejący dokument ze sprawą',
                        f"Dokument: {doc['title']} — bez kopiowania pliku",self.current_author(fields))
        return self.redirect(f'/document/{did}/links')

    def document_link_remove(self, did: int, fields):
        a = self._hub_app()
        try:
            cid = int(fields.get('case_id') or 0)
        except (ValueError, TypeError):
            cid = 0
        with a.db() as con:
            d = con.execute('SELECT case_id,title FROM documents WHERE id=?',(did,)).fetchone()
            if not d or cid <= 0 or cid == d['case_id']:
                return self._hub_error('Nie można odłączyć sprawy źródłowej.',409,f'/document/{did}/links')
            if a.case_read_only(con,cid):
                return self._hub_error('Sprawa jest zablokowana przed zmianami.',403,f'/document/{did}/links')
            removed = con.execute('DELETE FROM document_case_links WHERE document_id=? AND case_id=?',(did,cid)).rowcount
            if removed:
                a.audit(con,cid,'document',did,'Odłączono dokument od sprawy',
                        f"Dokument: {d['title']}; oryginalny plik pozostawiono",self.current_author(fields))
        return self.redirect(f'/document/{did}/links')

    def powers_page(self, qs):
        a = self._hub_app()
        q = (qs.get('q') or [''])[0].strip()[:150]
        like = f'%{q}%'
        with a.db() as con:
            rows = con.execute('''SELECT p.*, d.title,d.original_name,d.case_id,c.signature,c.internal_signature,c.title case_title
                FROM powers_of_attorney p JOIN documents d ON d.id=p.document_id
                JOIN cases c ON c.id=d.case_id
                WHERE (?='' OR p.principal LIKE ? OR p.representative LIKE ? OR p.authorization_scope LIKE ?
                       OR d.title LIKE ? OR c.signature LIKE ? OR c.internal_signature LIKE ?)
                ORDER BY p.updated_at DESC LIMIT 300''',(q,like,like,like,like,like,like)).fetchall()
            docs = con.execute('''SELECT d.id,d.title,d.original_name,c.signature,c.title case_title
                FROM documents d JOIN cases c ON c.id=d.case_id
                WHERE d.id NOT IN (SELECT document_id FROM powers_of_attorney)
                ORDER BY d.id DESC LIMIT 300''').fetchall()
        lines=[]
        for r in rows:
            note = f"<div class='small muted'>{esc(r['authorization_scope'])}</div>" if r['authorization_scope'] else ''
            lines.append(f"<tr><td><a href='/document/{r['document_id']}/open'><b>{esc(r['title'])}</b></a>{note}</td>"
                f"<td>{esc(r['principal'])}</td><td>{esc(r['representative'])}</td>"
                f"<td>{esc(r['validity_status'])}<div class='small muted'>{esc(r['granted_on'])}</div></td>"
                f"<td><a class='btn small' href='/powers/{r['document_id']}/edit'>Edytuj</a> "
                f"<a class='btn small' href='/document/{r['document_id']}/links'>Sprawy</a> "
                f"<form method='post' action='/powers/remove' style='display:inline' onsubmit=\"return confirm('Usunąć tylko z rejestru pełnomocnictw? Plik pozostanie w dokumentach.')\">"
                f"<input type='hidden' name='document_id' value='{r['document_id']}'><button class='btn small'>Usuń z rejestru</button></form></td></tr>")
        opts = "<option value=''>— wybierz wgrany dokument —</option>" + ''.join(
            f"<option value='{r['id']}'>{esc(r['title'])} ({esc(r['signature'] or r['case_title'])})</option>" for r in docs)
        body = f"""<div class='topbar'><div><h1>Pełnomocnictwa</h1>
          <div class='sub'>Jeden oryginał, możliwość powiązania z wieloma sprawami. Rejestr informacyjny — zakres umocowania weryfikuje prawnik.</div></div></div>
          <div class='card'><form method='get' action='/powers' class='searchbar'>
          <input name='q' value='{esc(q)}' placeholder='Mocodawca, pełnomocnik, zakres, dokument, sygnatura'>
          <button class='btn'>Szukaj</button></form></div>
          <div class='card table-scroll'><h2>Rejestr ({len(rows)})</h2><table>
          <tr><th>Dokument</th><th>Mocodawca</th><th>Pełnomocnik</th><th>Status / data</th><th>Akcje</th></tr>
          {''.join(lines) or '<tr><td colspan="5">Brak wpisów.</td></tr>'}</table></div>
          <div class='card'><h2>Dodaj dokument do rejestru</h2>
          <p class='small muted'>Najpierw wgraj pełnomocnictwo raz do dokumentów wybranej sprawy.
          Tutaj oznacz ten sam dokument jako pełnomocnictwo i powiąż go z dodatkowymi sprawami bez ponownego uploadu.</p>
          <form method='post' action='/powers/save' class='form-grid'>
          <div class='full'><label>Dokument *</label><select name='document_id' required>{opts}</select></div>
          <div><label>Mocodawca</label><input name='principal' maxlength='250'></div>
          <div><label>Pełnomocnik</label><input name='representative' maxlength='250'></div>
          <div class='full'><label>Zakres umocowania</label><textarea name='authorization_scope' rows='2' maxlength='3000'></textarea></div>
          <div><label>Data udzielenia</label><input type='date' name='granted_on'></div>
          <div><label>Status</label><select name='validity_status'><option>do weryfikacji</option><option>aktualne</option>
          <option>ograniczone</option><option>wygasłe</option></select></div>
          <div class='full'><label>Uwagi</label><textarea name='notes' maxlength='4000'></textarea></div>
          <div><button class='btn primary'>Dodaj do rejestru</button></div></form></div>"""
        return self.send_html(a.layout('Pełnomocnictwa', body, 'powers'))

    def power_edit_page(self, did: int):
        a=self._hub_app()
        with a.db() as con:
            r=con.execute('''SELECT p.*,d.title,d.case_id FROM powers_of_attorney p
                JOIN documents d ON d.id=p.document_id WHERE p.document_id=?''',(did,)).fetchone()
        if not r:
            return self.send_error(404)
        options=''.join(f"<option value='{esc(v)}' {'selected' if r['validity_status']==v else ''}>{esc(v)}</option>"
                        for v in ('do weryfikacji','aktualne','ograniczone','wygasłe'))
        body=f'''<div class='topbar'><div><h1>Edytuj pełnomocnictwo</h1>
          <div class='sub'>{esc(r['title'])}</div></div><a class='btn' href='/powers'>Powrót</a></div>
          <div class='card'><form method='post' action='/powers/save' class='form-grid'>
          <input type='hidden' name='document_id' value='{did}'>
          <div><label>Mocodawca</label><input name='principal' maxlength='250' value='{esc(r['principal'])}'></div>
          <div><label>Pełnomocnik</label><input name='representative' maxlength='250' value='{esc(r['representative'])}'></div>
          <div class='full'><label>Zakres umocowania</label><textarea name='authorization_scope' rows='3' maxlength='3000'>{esc(r['authorization_scope'])}</textarea></div>
          <div><label>Data udzielenia</label><input type='date' name='granted_on' value='{esc(r['granted_on'])}'></div>
          <div><label>Status (decyzja prawnika)</label><select name='validity_status'>{options}</select></div>
          <div class='full'><label>Uwagi</label><textarea name='notes' maxlength='4000'>{esc(r['notes'])}</textarea></div>
          <div class='full'><button class='btn primary'>Zapisz zmiany</button></div>
          </form></div>'''
        return self.send_html(a.layout('Edytuj pełnomocnictwo',body,'powers'))

    def power_save(self, fields):
        a=self._hub_app()
        try: did = int(fields.get('document_id') or 0)
        except (ValueError,TypeError): did = 0
        principal=(fields.get('principal') or '').strip()[:250]
        attorney=(fields.get('representative') or '').strip()[:250]
        scope=(fields.get('authorization_scope') or '').strip()[:3000]
        granted=(fields.get('granted_on') or '').strip()
        status=(fields.get('validity_status') or 'do weryfikacji').strip()
        notes=(fields.get('notes') or '').strip()[:4000]
        if status not in {'do weryfikacji','aktualne','ograniczone','wygasłe'}:
            return self._hub_error('Nieprawidłowy status pełnomocnictwa.',400,'/powers')
        if granted:
            import datetime
            try:
                if datetime.date.fromisoformat(granted).isoformat()!=granted:
                    raise ValueError()
            except ValueError:
                return self._hub_error('Nieprawidłowa data.',400,'/powers')
        with a.db() as con:
            d=con.execute('SELECT id,case_id,title FROM documents WHERE id=?',(did,)).fetchone()
            if not d:
                return self._hub_error('Nie znaleziono dokumentu.',404,'/powers')
            if a.case_read_only(con,d['case_id']):
                return self._hub_error('Sprawa jest zablokowana przed zmianami.',403,'/powers')
            con.execute('''INSERT INTO powers_of_attorney
                (document_id,principal,representative,authorization_scope,granted_on,validity_status,notes,created_by)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET
                principal=excluded.principal,representative=excluded.representative,
                authorization_scope=excluded.authorization_scope,granted_on=excluded.granted_on,
                validity_status=excluded.validity_status,notes=excluded.notes,
                updated_at=CURRENT_TIMESTAMP''',
                (did,principal,attorney,scope,granted,status,notes,self.current_author(fields)))
            a.audit(con,d['case_id'],'document',did,'Dodano do rejestru pełnomocnictw',
                    f"Dokument: {d['title']}",self.current_author(fields))
        return self.redirect('/powers')

    def power_remove(self, fields):
        a=self._hub_app()
        try: did=int(fields.get('document_id') or 0)
        except (ValueError,TypeError): did=0
        with a.db() as con:
            d=con.execute('SELECT case_id,title FROM documents WHERE id=?',(did,)).fetchone()
            if not d:
                return self._hub_error('Brak dokumentu.',404,'/powers')
            if a.case_read_only(con,d['case_id']):
                return self._hub_error('Sprawa jest zablokowana przed zmianami.',403,'/powers')
            removed=con.execute('DELETE FROM powers_of_attorney WHERE document_id=?',(did,)).rowcount
            if removed:
                a.audit(con,d['case_id'],'document',did,'Usunięto wpis z rejestru pełnomocnictw',
                        f"Oryginalny dokument zachowany: {d['title']}",self.current_author(fields))
        return self.redirect('/powers')
