# -*- coding: utf-8 -*-
"""RK KANCELARIA 0.3.4-dev1 — lokalne propozycje czynności i ręczne zatwierdzanie.

Moduł nie wyznacza terminów procesowych i nie wykonuje żadnej czynności sam.
Propozycje powstają regułowo na podstawie dostępnego tekstu dokumentu/projektu.
Dopiero świadome zatwierdzenie tworzy zadanie, a odrzucenie nie tworzy niczego.
"""
from __future__ import annotations

import hashlib
import html
import re
import sys
from datetime import date
from pathlib import Path

TASK_TYPES = ('Zadanie', 'Monit', 'Termin procesowy', 'Płatność')
PRIORITIES = ('normal', 'high')
MAX_SOURCE = 200_000
MAX_ACTIONS = 12


def esc(value) -> str:
    return html.escape(str(value if value is not None else ''), quote=True)


def valid_iso_date(raw: str) -> str:
    raw = str(raw or '').strip()
    if not raw:
        return ''
    try:
        d = date.fromisoformat(raw)
        if d.isoformat() != raw:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError('Podaj poprawną datę RRRR-MM-DD.')
    return raw


def source_fingerprint(source_type: str, row) -> str:
    """Powstrzymuje zatwierdzenie propozycji ze zmienionej treści źródła."""
    def col(key):
        try:
            return str(row[key] or '')
        except (IndexError, KeyError):
            return ''
    # Dokumenty w oryginalnym schemacie NIE mają updated_at; plik i indeks
    # identyfikujemy przez stored_name, file_hash oraz extracted_text.
    parts = (source_type, col('id'), col('title'), col('stored_name'),
             col('file_hash') if source_type == 'document' else col('updated_at'),
             col('extracted_text') if source_type == 'document' else col('content'))
    return hashlib.sha256('\x1f'.join(parts).encode('utf-8')).hexdigest()


def _snippet(source: str, match: re.Match, around: int = 125) -> str:
    lo = max(0, match.start() - around)
    hi = min(len(source), match.end() + around)
    return re.sub(r'\s+', ' ', source[lo:hi]).strip()[:320]


def suggest_actions(text: str) -> list[dict]:
    """Ostrożne sugestie: wzorce w tekście, bez oceny prawnej ani dat końcowych."""
    text = str(text or '')[:MAX_SOURCE]
    out = []
    seen = set()

    def add(title: str, kind: str, priority: str, source_excerpt: str, rationale: str):
        key = (kind, title)
        if key in seen or len(out) >= MAX_ACTIONS:
            return
        seen.add(key)
        out.append(dict(title=title, kind=kind, priority=priority,
                        source_excerpt=source_excerpt[:320], rationale=rationale[:500]))

    rules = [
        (r'\b(?:postanowieni[aeu]|wyrok(?:u|iem)?|nakaz(?:u|em)?\s+zapłaty|zarządzeni[aeu])\b',
         'Zweryfikować treść rozstrzygnięcia oraz możliwość i tryb reakcji', 'Zadanie', 'high',
         'Rozpoznano wzmiankę o rozstrzygnięciu; dopuszczalność środka zaskarżenia wymaga oceny prawnika.'),
        (r'\b(?:zobowiązuj\w*|wzywa\w*\s+do|przedłoży\w*|uzupełni\w*\s+brak\w*)\b',
         'Zweryfikować zakres zobowiązania i przygotować wymagane działanie', 'Zadanie', 'high',
         'Rozpoznano możliwe zobowiązanie; ustal dokładny zakres, adresata i datę doręczenia.'),
        (r'\b(?:rozpraw\w*|posiedzeni\w*|przesłuchani\w*|stawiennictw\w*)\b',
         'Sprawdzić termin posiedzenia oraz przygotowanie do udziału', 'Zadanie', 'high',
         'Sprawdź wezwanie, tryb, miejsce, obowiązki i datę przed wpisaniem do kalendarza.'),
        (r'\b(?:doręczeni\w*|doręczon\w*|odebran\w*|odbior\w*)\b',
         'Ustalić i udokumentować datę oraz sposób doręczenia', 'Zadanie', 'high',
         'Data doręczenia może mieć znaczenie dla biegu terminu; nie jest ustalana automatycznie.'),
        (r'\b(?:wezwan\w*\s+do\s+zapłaty|faktur\w*|należnoś\w*|płatnoś\w*|odsetk\w*)\b',
         'Zweryfikować stan należności i potrzebę monitu', 'Monit', 'normal',
         'Sprawdź dokumenty księgowe, wymagalność i historię kontaktu przed monitem.'),
        (r'\b(?:mediacj\w*|ugod\w*|posiedzeni\w*\s+mediacyjn\w*)\b',
         'Sprawdzić dalsze czynności związane z mediacją lub ugodą', 'Zadanie', 'normal',
         'Zweryfikuj status i poufność mediacji; nie ujawniaj treści rozmów w korespondencji.'),
        (r'\b(?:opini\w*\s+biegł\w*|biegł\w*\s+sądow\w*)\b',
         'Przeanalizować opinię biegłego i potrzebę stanowiska procesowego', 'Zadanie', 'normal',
         'Ocena opinii i terminów na zastrzeżenia wymaga weryfikacji akt i zarządzeń.'),
    ]
    for pattern, title, kind, priority, note in rules:
        m = re.search(pattern, text, re.I)
        if m:
            add(title, kind, priority, _snippet(text, m), note)

    term = re.search(r'(?i)\b(?:w\s+terminie|w\s+ciągu|nie\s+później\s+niż)\s+(\d{1,3})\s+dni\b', text)
    if term:
        add('Zweryfikować podstawę, początek biegu i obliczenie terminu wskazanego w piśmie',
            'Zadanie', 'high', _snippet(text, term),
            'W piśmie wskazano okres liczony w dniach; program NIE wyznacza daty końcowej.')

    if not out:
        add('Zapoznać się z treścią dokumentu i określić dalsze czynności', 'Zadanie', 'normal',
            text[:220] if text.strip() else '',
            ('Brak automatycznie rozpoznanych czynności. Treść jest dostępna do ręcznej oceny.'
             if text.strip() else
             'Nie odczytano tekstu. Dla skanów uruchom OCR, dla nagrań dodaj zweryfikowaną transkrypcję; analiza nie odgaduje zawartości pliku.'))
    return out[:MAX_ACTIONS]


def ensure_action_center_schema(con):
    """Addytywna, powtarzalna migracja — bez zmian w tabelach spraw i zadań."""
    con.executescript('''
    CREATE TABLE IF NOT EXISTS workflow_reviews (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source_type TEXT NOT NULL CHECK(source_type IN ('document','draft')),
      source_id INTEGER NOT NULL,
      case_id INTEGER,
      source_title TEXT NOT NULL DEFAULT '',
      source_hash TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','closed','superseded')),
      analyzed_by TEXT NOT NULL DEFAULT '',
      analyzed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      reviewed_at TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_workflow_reviews_status ON workflow_reviews(status,id DESC);
    CREATE INDEX IF NOT EXISTS idx_workflow_reviews_source ON workflow_reviews(source_type,source_id,id DESC);
    CREATE TABLE IF NOT EXISTS workflow_proposals (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      review_id INTEGER NOT NULL REFERENCES workflow_reviews(id) ON DELETE CASCADE,
      kind TEXT NOT NULL DEFAULT 'Zadanie',
      title TEXT NOT NULL,
      priority TEXT NOT NULL DEFAULT 'normal',
      source_excerpt TEXT NOT NULL DEFAULT '',
      rationale TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
      final_title TEXT NOT NULL DEFAULT '',
      final_kind TEXT NOT NULL DEFAULT '',
      final_due_date TEXT NOT NULL DEFAULT '',
      final_basis TEXT NOT NULL DEFAULT '',
      final_base_date TEXT NOT NULL DEFAULT '',
      final_calculation TEXT NOT NULL DEFAULT '',
      task_id INTEGER,
      decided_by TEXT NOT NULL DEFAULT '',
      decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_workflow_proposals_review ON workflow_proposals(review_id,status,id);
    ''')


class ActionCenterMixin:
    def _center_app(self):
        return sys.modules[type(self).__module__]

    def _center_error(self, message, status=400, return_to='/workflow'):
        app = self._center_app()
        body = ("<div class='card'><h1>Nie wykonano operacji</h1>"
                f"<p>{esc(message)}</p><a class='btn' href='{esc(return_to)}'>Wróć</a></div>")
        return self.send_html(app.layout('Centrum decyzji', body, 'workflow'), status)

    def _center_source(self, con, kind, source_id):
        if kind == 'document':
            row = con.execute('SELECT * FROM documents WHERE id=?', (source_id,)).fetchone()
            if not row:
                return None
            text = str(row['extracted_text'] or '')
        elif kind == 'draft':
            row = con.execute('SELECT * FROM writing_projects WHERE id=?', (source_id,)).fetchone()
            if not row:
                return None
            text = str(row['content'] or '')
        else:
            return None
        return row, text, source_fingerprint(kind, row)

    def action_center_page(self):
        a = self._center_app()
        with a.db() as con:
            rows = con.execute('''SELECT r.*, c.title case_title, c.signature,
                (SELECT COUNT(*) FROM workflow_proposals p WHERE p.review_id=r.id AND p.status='pending') pending_count
                FROM workflow_reviews r LEFT JOIN cases c ON c.id=r.case_id
                ORDER BY r.status='pending' DESC,r.id DESC LIMIT 120''').fetchall()
            inbox = con.execute("SELECT id,original_name,ocr_status,created_at FROM inbox_items WHERE status='pending' ORDER BY id DESC LIMIT 50").fetchall()
        inbox_cards = ''.join(
            f"<div class='card' style='margin:12px 0'><b>Nowe pismo w skrzynce wpływu: {esc(i['original_name'])}</b>"
            f"<p class='small muted'>OCR: {esc(i['ocr_status'])} · {esc(str(i['created_at'])[:16])}</p>"
            f"<a class='btn small primary' href='/inbox/{i['id']}'>Zweryfikuj pismo i propozycje</a></div>"
            for i in inbox)
        cards = []
        for r in rows:
            source_url = f"/{'document' if r['source_type']=='document' else 'draft'}/{r['source_id']}{'/open' if r['source_type']=='document' else ''}"
            label = 'Dokument' if r['source_type'] == 'document' else 'Projekt pisma'
            status = 'Do decyzji' if r['status'] == 'pending' else ('Zakończono' if r['status']=='closed' else 'Zastąpiono nową analizą')
            cards.append(
                "<div class='card' style='margin:12px 0'>"
                f"<h3 style='margin-top:0'><a href='/workflow/review/{r['id']}'>{esc(r['source_title'])}</a></h3>"
                f"<p class='small muted'>{esc(label)} · {esc(r['signature'] or r['case_title'] or 'Bez przypisanej sprawy')} · {esc(status)} · "
                f"{int(r['pending_count'])} oczekujących · {esc(str(r['analyzed_at'])[:16])}</p>"
                f"<a class='btn small primary' href='/workflow/review/{r['id']}'>Otwórz propozycje</a> "
                f"<a class='btn small' href='{source_url}'>Zobacz źródło</a></div>"
            )
        body = ("<div class='topbar'><div><h1>Centrum decyzji</h1><div class='sub'>Propozycje czynności z dokumentów i projektów pism do ręcznej oceny.</div></div></div>"
                "<div class='notice'>Program działa na podstawie lokalnych reguł, nie zastępuje analizy prawnej. Nie oblicza terminów, "
                "nie wysyła korespondencji i nie tworzy zadań bez Twojego zatwierdzenia.</div>"
                "<p><a class='btn' href='/inbox'>Skrzynka wpływu</a> <a class='btn' href='/documents'>Dokumenty</a> "
                "<a class='btn' href='/drafts'>Projekty pism</a></p>"
                + ("<h2>Nowe pisma do przyjęcia</h2>" + inbox_cards if inbox_cards else '')
                + "<h2>Propozycje z dokumentów i projektów</h2>"
                + (''.join(cards) or "<div class='card empty'>Brak analiz. Otwórz dokument lub projekt i kliknij „Zaproponuj czynności”.</div>"))
        return self.send_html(a.layout('Centrum decyzji', body, 'workflow'))

    def action_center_analyze(self, source_type, source_id, fields):
        a = self._center_app()
        if source_type not in ('document', 'draft'):
            return self.send_error(404)
        author = self.current_author(fields)
        with a.db() as con:
            source = self._center_source(con, source_type, source_id)
            if not source:
                return self.send_error(404)
            row, text, fingerprint = source
            # Szybki odczyt plików tekstowych, gdy indeks jeszcze nie zdążył powstać.
            # PDF/skany i multimedia nie są po cichu transkrybowane ani OCR-owane.
            if not text.strip():
                filename = str(row['original_name'] or '')
                stored = str(row['stored_name'] or '')
                ext = Path(filename).suffix.lower()
                if ext in {'.docx','.txt','.rtf','.md','.csv','.log','.xlsx','.xlsm'} and stored and Path(stored).name == stored:
                    base = (a.FILES_DIR / f"sprawa_{row['case_id']}") if source_type=='document' else a.DRAFTS_DIR
                    path = (base / stored).resolve()
                    if path.parent == base.resolve() and path.is_file() and path.stat().st_size <= 8 * 1024 * 1024:
                        extracted, used, state, language = a.extract_document_text(filename, path.read_bytes(),force_ocr=False)
                        if extracted.strip():
                            text = extracted
                            if source_type == 'document':
                                con.execute('''UPDATE documents SET extracted_text=?,indexed_at=CURRENT_TIMESTAMP,
                                    ocr_used=?,ocr_status=?,ocr_language=? WHERE id=?''',
                                    (extracted[:5_000_000],used,state,language,source_id))
                                source = self._center_source(con, source_type, source_id)
                                row, _, fingerprint = source
            latest = con.execute('''SELECT id FROM workflow_reviews
                 WHERE source_type=? AND source_id=? AND status='pending'
                 ORDER BY id DESC LIMIT 1''', (source_type,source_id)).fetchone()
            if latest and fields.get('reanalyze') != '1':
                return self.redirect(f"/workflow/review/{latest['id']}")
            cid = row['case_id']
            if cid and a.case_read_only(con, cid):
                return self._center_error('Sprawa jest zablokowana.',403)
            # Gdy brak tekstu, tworzymy tylko propozycję ręcznej analizy, bez udawania transkrypcji/OCR.
            proposals = suggest_actions(text)
            if latest:
                con.execute("UPDATE workflow_reviews SET status='superseded',reviewed_at=CURRENT_TIMESTAMP WHERE id=?", (latest['id'],))
            cur = con.execute('''INSERT INTO workflow_reviews
                (source_type,source_id,case_id,source_title,source_hash,analyzed_by)
                VALUES(?,?,?,?,?,?)''',
                (source_type,source_id,cid,row['title'],fingerprint,author))
            rid = cur.lastrowid
            for p in proposals:
                con.execute('''INSERT INTO workflow_proposals
                    (review_id,kind,title,priority,source_excerpt,rationale)
                    VALUES(?,?,?,?,?,?)''',
                    (rid,p['kind'],p['title'],p['priority'],p['source_excerpt'],p['rationale']))
            a.audit(con,cid,'workflow_review',rid,'Przygotowano propozycje czynności',
                    f'Źródło: {source_type} #{source_id}; propozycje: {len(proposals)}',author)
        return self.redirect(f'/workflow/review/{rid}')

    def action_center_review_page(self, review_id):
        a = self._center_app()
        with a.db() as con:
            rev = con.execute('SELECT r.*,c.title case_title,c.signature FROM workflow_reviews r '
                              'LEFT JOIN cases c ON c.id=r.case_id WHERE r.id=?',(review_id,)).fetchone()
            proposals = con.execute('SELECT * FROM workflow_proposals WHERE review_id=? ORDER BY id',
                                    (review_id,)).fetchall() if rev else []
            source = self._center_source(con,rev['source_type'],rev['source_id']) if rev else None
        if not rev:
            return self.send_error(404)
        editable = rev['status'] == 'pending'
        stale = not source or source[2] != rev['source_hash']
        if stale:
            notice = "<div class='error'><b>Źródło zostało zmienione lub usunięte.</b> Zaktualizuj analizę, zanim zatwierdzisz propozycje.</div>"
        elif not rev['case_id']:
            notice = "<div class='notice'>Projekt nie jest przypisany do sprawy. Możesz przejrzeć propozycje, ale zapisanie zadań wymaga przypisania projektu do sprawy.</div>"
        else:
            notice = "<div class='notice'>To są wyłącznie propozycje. Wszystkie daty i podstawy prawne wymagają osobnej, ręcznej weryfikacji. Pole wyboru jest domyślnie odznaczone.</div>"
        cards = []
        for p in proposals:
            if p['status'] != 'pending' or not editable:
                result = f"<b>{esc(p['status'])}</b>" + (f" · zadanie #{p['task_id']}" if p['task_id'] else '')
                cards.append(f"<div class='card' style='margin:12px 0'><b>{esc(p['title'])}</b><div class='small muted'>{result}</div></div>")
                continue
            types = ''.join(f"<option value='{esc(k)}' {'selected' if k==p['kind'] else ''}>{esc(k)}</option>" for k in TASK_TYPES)
            priority = ''.join(f"<option value='{k}' {'selected' if k==p['priority'] else ''}>{'Wysoki' if k=='high' else 'Normalny'}</option>" for k in PRIORITIES)
            key = f"p_{p['id']}"
            cards.append(f"""<div class='card' style='margin:14px 0'>
              <label><input type='checkbox' name='{key}_selected' value='1' style='width:auto'> <b>Wybierz propozycję #{p['id']}</b></label>
              <div class='small muted'><b>Dlaczego:</b> {esc(p['rationale'])}</div>
              <details><summary>Fragment źródła</summary><blockquote style='white-space:pre-wrap'>{esc(p['source_excerpt']) or 'Brak odczytanego tekstu'}</blockquote></details>
              <div class='form-grid' style='margin-top:8px'>
                <div class='full'><label>Opis czynności — można poprawić</label><input name='{key}_title' maxlength='500' value='{esc(p['title'])}'></div>
                <div><label>Rodzaj</label><select name='{key}_kind'>{types}</select></div>
                <div><label>Priorytet</label><select name='{key}_priority'>{priority}</select></div>
                <div class='full'><label>Źródło / podstawa (wpisz samodzielnie)</label><input name='{key}_basis' maxlength='800' placeholder='np. treść zarządzenia z dnia…'></div>
                <div><label>Data początku biegu (gdy dotyczy)</label><input name='{key}_base_date' type='date'></div>
                <div><label>Data wykonania / termin po sprawdzeniu</label><input name='{key}_due_date' type='date'></div>
                <div class='full'><label>Sposób obliczenia / uzasadnienie terminu</label><textarea name='{key}_calculation' rows='2' maxlength='1200' placeholder='Np. jakie przepisy, zdarzenie początkowe i reguły liczenia zweryfikowano'></textarea></div>
                <div class='full small muted'>Jeśli wybierzesz „Termin procesowy”, wszystkie pola dotyczące dat, podstawy i sposobu obliczenia są obowiązkowe.</div>
              </div></div>""")
        active_count = sum(p['status']=='pending' for p in proposals)
        form = ''
        if editable and active_count:
            form = ("<div class='card'><label><input type='checkbox' name='review_confirm' value='yes' required style='width:auto'> "
                    "Potwierdzam, że zweryfikowano wybrane propozycje z oryginałem. W razie wpisania daty zweryfikowano ją samodzielnie.</label>"
                    "<label><input type='checkbox' name='deadline_verified' value='yes' style='width:auto'> "
                    "Sprawdziłem datę doręczenia, podstawę, początek biegu oraz sposób obliczenia każdego zatwierdzanego terminu procesowego.</label>"
                    "<button class='btn primary' name='decision' value='approve'>Zatwierdź zaznaczone i utwórz zadania</button> "
                    "<button class='btn' name='decision' value='reject'>Odrzuć zaznaczone</button></div>")
        if editable:
            cards_html = f"<form method='post' action='/workflow/review/{review_id}/decide'>{''.join(cards)}{form}</form>"
            add = f"""<div class='card'><h2>Dodaj własną propozycję</h2><form method='post' action='/workflow/review/{review_id}/add'>
            <label>Opis</label><input name='title' maxlength='500' required><label>Rodzaj</label>
            <select name='kind'>{''.join(f'<option>{esc(t)}</option>' for t in TASK_TYPES)}</select>
            <button class='btn'>Dodaj do weryfikacji (bez tworzenia zadania)</button></form></div>"""
        else:
            cards_html = ''.join(cards)
            add = ''
        source_url = f"/{rev['source_type']}/{rev['source_id']}{'/open' if rev['source_type']=='document' else ''}"
        renew = (f"<form method='post' action='/workflow/analyze/{rev['source_type']}/{rev['source_id']}' style='display:inline'>"
                 "<input type='hidden' name='reanalyze' value='1'><button class='btn'>Przeanalizuj ponownie</button></form>" if source else '')
        body = f"""<div class='topbar'><div><h1>Ocena propozycji: {esc(rev['source_title'])}</h1>
        <div class='sub'>{esc(rev['signature'] or rev['case_title'] or 'Nie przypisano sprawy')} · status: {esc(rev['status'])}</div></div>
        <div><a class='btn' href='/workflow'>← Centrum decyzji</a> <a class='btn' href='{source_url}'>Oryginał</a> {renew}</div></div>
        {notice}<p class='small muted'>Zapis zadania nastąpi wyłącznie po kliknięciu „Zatwierdź zaznaczone”.
        W szczególności program nie przyjmuje automatycznie terminu procesowego.</p>{cards_html}{add}"""
        return self.send_html(a.layout('Ocena propozycji',body,'workflow'))

    def action_center_add(self, review_id, fields):
        a = self._center_app()
        title = str(fields.get('title') or '').strip()[:500]
        kind = fields.get('kind') or 'Zadanie'
        if not title or kind not in TASK_TYPES:
            return self._center_error('Podaj opis i prawidłowy rodzaj czynności.',400,f'/workflow/review/{review_id}')
        with a.db() as con:
            rev = con.execute('SELECT * FROM workflow_reviews WHERE id=?', (review_id,)).fetchone()
            if not rev or rev['status']!='pending':
                return self._center_error('Analiza nie jest już otwarta.',409)
            con.execute('INSERT INTO workflow_proposals(review_id,kind,title,priority,rationale) VALUES(?,?,?, ?, ?)',
                        (review_id,kind,title,'normal','Czynność dopisana ręcznie przez użytkownika.'))
            a.audit(con,rev['case_id'],'workflow_review',review_id,'Dodano ręczną propozycję czynności',title,self.current_author(fields))
        return self.redirect(f'/workflow/review/{review_id}')

    def action_center_decide(self, review_id, fields):
        a = self._center_app()
        action = fields.get('decision')
        if action not in ('approve','reject'):
            return self._center_error('Nieznana decyzja.',400,f'/workflow/review/{review_id}')
        if fields.get('review_confirm') != 'yes':
            return self._center_error('Potwierdź ręczne sprawdzenie oryginału.',400,f'/workflow/review/{review_id}')
        author = self.current_author(fields)
        with a.db() as con:
            rev = con.execute('SELECT * FROM workflow_reviews WHERE id=?', (review_id,)).fetchone()
            if not rev:
                return self.send_error(404)
            if rev['status'] != 'pending':
                return self._center_error('Ta analiza została już zamknięta lub zastąpiona.',409)
            source = self._center_source(con,rev['source_type'],rev['source_id'])
            if not source or source[2]!=rev['source_hash']:
                return self._center_error('Źródło zostało zmienione. Przeanalizuj je ponownie.',409,f'/workflow/review/{review_id}')
            rows = con.execute("SELECT * FROM workflow_proposals WHERE review_id=? AND status='pending' ORDER BY id",
                               (review_id,)).fetchall()
            selected = [p for p in rows if fields.get(f"p_{p['id']}_selected") == '1']
            if not selected:
                return self._center_error('Zaznacz co najmniej jedną propozycję.',400,f'/workflow/review/{review_id}')
            if action == 'approve' and (not rev['case_id'] or
                    not con.execute('SELECT id FROM cases WHERE id=?',(rev['case_id'],)).fetchone()):
                return self._center_error('Przypisz projekt do istniejącej sprawy przed utworzeniem zadań.',409,f'/workflow/review/{review_id}')
            if rev['case_id'] and a.case_read_only(con,rev['case_id']):
                return self._center_error('Sprawa jest zablokowana przed zmianami.',403,f'/workflow/review/{review_id}')
            decisions = []
            # Walidacja wszystkich pól PRZED pierwszym zapisem; jeden błąd = zero zmian.
            for p in selected:
                key=f"p_{p['id']}"
                title = str(fields.get(key+'_title') or '').strip()[:500]
                kind = fields.get(key+'_kind') or p['kind']
                priority = fields.get(key+'_priority') or p['priority']
                basis = str(fields.get(key+'_basis') or '').strip()[:800]
                calculation = str(fields.get(key+'_calculation') or '').strip()[:1200]
                try:
                    start_date=valid_iso_date(fields.get(key+'_base_date',''))
                    due_date=valid_iso_date(fields.get(key+'_due_date',''))
                except ValueError as exc:
                    return self._center_error(f'Propozycja #{p["id"]}: {exc}',400,f'/workflow/review/{review_id}')
                if not title or kind not in TASK_TYPES or priority not in PRIORITIES:
                    return self._center_error(f'Propozycja #{p["id"]}: popraw opis, rodzaj i priorytet.',400,f'/workflow/review/{review_id}')
                if start_date and due_date and due_date < start_date:
                    return self._center_error(f'Propozycja #{p["id"]}: data końcowa jest wcześniejsza niż początek biegu.',400,f'/workflow/review/{review_id}')
                if action=='approve' and kind=='Termin procesowy' and not (
                        fields.get('deadline_verified') == 'yes' and start_date and due_date and basis and calculation):
                    return self._center_error(
                        'Termin procesowy wymaga ręcznego sprawdzenia, daty początkowej i końcowej, podstawy oraz sposobu obliczenia.',
                        400,f'/workflow/review/{review_id}')
                decisions.append((p,title,kind,priority,basis,start_date,due_date,calculation))
            for p,title,kind,priority,basis,start_date,due_date,calculation in decisions:
                # Roszczenie wiersza przed utworzeniem zadania. Zabezpiecza też
                # przed równoczesnym podwójnym zatwierdzeniem tego samego wpisu.
                target_status = 'approved' if action=='approve' else 'rejected'
                claim=con.execute("UPDATE workflow_proposals SET status=? WHERE id=? AND status='pending'",
                                  (target_status,p['id']))
                if claim.rowcount != 1:
                    raise RuntimeError('Propozycja została już rozpatrzona; odśwież widok.')
                task_id=None
                if action=='approve':
                    note = (f"Źródło: {rev['source_type']} #{rev['source_id']} / analiza #{review_id}.\n"
                            f"Fragment: {p['source_excerpt']}\nPowód propozycji: {p['rationale']}\n"
                            f"Podstawa podana przez użytkownika: {basis}\n"
                            f"Początek biegu: {start_date}\nSposób weryfikacji: {calculation}\n"
                            'Weryfikacja wykonana ręcznie; to nie jest automatycznie obliczony termin.')
                    cur=con.execute('''INSERT INTO tasks
                         (case_id,title,due_date,status,priority,depends_on,notes,task_type,created_by,updated_by,
                          deadline_base_date,deadline_rule,deadline_source,deadline_manual)
                         VALUES(?,?,?,'open',?,'',?,?,?,?,?,?,?,1)''',
                         (rev['case_id'],title,due_date,priority,note,kind,author,author,
                          start_date,calculation,basis or p['source_excerpt']))
                    task_id=cur.lastrowid
                    a.sync_task_alert(con,task_id,author)
                    a.audit(con,rev['case_id'],'task',task_id,'Zatwierdzono propozycję czynności',
                            f'Analiza #{review_id}; typ: {kind}; termin: {due_date or "nieustalony"}',author)
                con.execute('''UPDATE workflow_proposals SET status=?,final_title=?,final_kind=?,final_due_date=?,
                      final_basis=?,final_base_date=?,final_calculation=?,task_id=?,decided_by=?,decided_at=CURRENT_TIMESTAMP
                      WHERE id=? AND status IN ('approved','rejected') ''',
                      ('approved' if action=='approve' else 'rejected',title,kind,due_date,basis,start_date,calculation,task_id,author,p['id']))
            remaining=con.execute("SELECT COUNT(*) FROM workflow_proposals WHERE review_id=? AND status='pending'",(review_id,)).fetchone()[0]
            if not remaining:
                con.execute("UPDATE workflow_reviews SET status='closed',reviewed_at=CURRENT_TIMESTAMP WHERE id=?",(review_id,))
            a.audit(con,rev['case_id'],'workflow_review',review_id,
                    'Zatwierdzono propozycje' if action=='approve' else 'Odrzucono propozycje',
                    f'Liczba decyzji: {len(decisions)}',author)
        return self.redirect(f'/workflow/review/{review_id}')
