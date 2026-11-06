# -*- coding: utf-8 -*-
"""Skrzynka wpływu: lokalna analiza i obowiązkowa weryfikacja człowieka.

Nie stanowi automatycznej analizy prawnej: nie oblicza terminów, nie przypisuje
sprawy i nie tworzy zadań bez wyraźnego zatwierdzenia formularza.
"""
from __future__ import annotations

import hashlib
import html
import json
import mimetypes
import re
import shutil
import sys
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import quote
from rk_unified_preview import render_preview, serve_local_file

ALLOWED_SUFFIXES = {'.pdf','.doc','.docx','.odt','.rtf','.txt','.md','.csv','.xlsx','.xlsm','.ods','.pptx',
                    '.png','.jpg','.jpeg','.bmp','.gif','.tif','.tiff','.webp',
                    '.mp3','.wav','.ogg','.oga','.m4a','.aac','.flac','.opus',
                    '.mp4','.m4v','.webm','.mov','.avi','.mkv','.wmv','.mpg','.mpeg','.eml','.zip'}
MAX_INBOX_BYTES = 20 * 1024 * 1024
ACTION_TYPES = ('Zadanie', 'Monit', 'Termin procesowy', 'Płatność')
SIGNATURE_RE = re.compile(
    r'(?<!\w)(?:[IVXLC]{1,6}\s+)?(?:[A-ZĄĆĘŁŃÓŚŹŻ]{1,5}\s+){1,3}\d{1,7}\s*/\s*\d{2,4}(?!\w)')
DEADLINE_RE = re.compile(
    r'(?i)\b(?:w\s+terminie|w\s+ciągu|nie\s+później\s+niż\s+w\s+terminie)\s+'
    r'(\d{1,3})\s+dni\b')


def escape(value: object) -> str:
    return html.escape(str(value if value is not None else ''), quote=True)


def valid_date(value: str) -> str:
    value = (value or '').strip()
    if not value:
        return ''
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('Data musi mieć poprawny format RRRR-MM-DD.')
    return value


def ensure_inbox_schema(con) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS inbox_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_name TEXT NOT NULL,
            stored_name TEXT NOT NULL UNIQUE,
            file_hash TEXT NOT NULL,
            extracted_text TEXT NOT NULL DEFAULT '',
            ocr_status TEXT NOT NULL DEFAULT '',
            ocr_used INTEGER NOT NULL DEFAULT 0,
            ocr_language TEXT NOT NULL DEFAULT '',
            suggestions_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'pending',
            document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
            created_by TEXT NOT NULL DEFAULT '',
            reviewed_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_inbox_items_status ON inbox_items(status,id DESC);
    """)


def _excerpt(text: str, start: int, end: int, maxlen: int = 220) -> str:
    a = max(0, start - 65)
    b = min(len(text), end + 115)
    return re.sub(r'\s+', ' ', text[a:b]).strip()[:maxlen]


def analyze_letter(text: str) -> dict:
    """Zwraca sugestie organizacyjne; nigdy nie wylicza dat końcowych."""
    text = (text or '')[:350000]
    signatures = []
    for m in SIGNATURE_RE.finditer(text[:40000]):
        sig = re.sub(r'\s+', ' ', m.group(0)).strip().upper()
        sig = re.sub(r'\s*/\s*', '/', sig)
        if sig not in signatures:
            signatures.append(sig)
        if len(signatures) >= 8:
            break
    suggestions = []
    seen = set()

    def add(kind: str, title: str, source: str, key: str) -> None:
        if key in seen or len(suggestions) >= 12:
            return
        seen.add(key)
        suggestions.append({'kind': kind, 'title': title, 'source': source[:240],
                            'due_date': '', 'priority': 'normal'})

    # Każdy termin jawny to wyłącznie propozycja sprawdzenia: bez daty i bez
    # domyślania się początku biegu, zasad liczenia lub strony zobowiązanej.
    for m in DEADLINE_RE.finditer(text):
        days = int(m.group(1))
        if 0 < days <= 365:
            add('Termin procesowy', f'Zweryfikować termin {days} dni i ustalić wymagane działanie',
                _excerpt(text, m.start(), m.end()), f'deadline-{m.start()}')

    triggers = [
        (r'(?i)\bzobowiązu(?:je|ją|jemy|jąc)\b|\bnakazuje\b',
         'Zbadać, kogo dotyczy zobowiązanie i przygotować odpowiednią czynność', 'Zadanie'),
        (r'(?i)\b(?:wezwa(?:nie|no|ł|ła)?\s+do\s+usunięcia\s+braków|braki\s+formalne)\b',
         'Zweryfikować braki formalne i wymagane uzupełnienia', 'Zadanie'),
        (r'(?i)\b(?:wyznacz\w*\s+termin\s+rozprawy|termin\s+rozprawy|zawiadomienie\s+o\s+rozprawie)\b',
         'Sprawdzić datę rozprawy i zaplanować przygotowanie', 'Termin procesowy'),
        (r'(?i)\b(?:odpowiedź\s+na\s+pozew|odpowiedzi\s+na\s+pozew)\b',
         'Zweryfikować potrzebę sporządzenia odpowiedzi na pozew', 'Zadanie'),
        (r'(?i)\b(?:wezwanie\s+do\s+zapłaty|wzywa\w*\s+do\s+zapłaty)\b',
         'Sprawdzić wezwanie do zapłaty i przygotować stanowisko', 'Zadanie'),
        (r'(?i)\bpostanowieni[aeu]\b',
         'Przeanalizować postanowienie i sprawdzić możliwe działania', 'Zadanie'),
        (r'(?i)\bwyrok\b',
         'Przeanalizować wyrok, doręczenie i ewentualne środki prawne', 'Zadanie'),
        (r'(?i)\b(?:oczekujemy\s+na\s+odpowiedź|prosimy\s+o\s+odpowiedź|przekazanie\s+stanowiska)\b',
         'Rozważyć monit lub kontrolę wpływu odpowiedzi', 'Monit'),
    ]
    for idx, (pattern, title, kind) in enumerate(triggers):
        m = re.search(pattern, text)
        if m:
            add(kind, title, _excerpt(text, m.start(), m.end()), f'trigger-{idx}')
    if not suggestions:
        add('Zadanie', 'Przeczytać pismo i ustalić dalsze czynności',
            'Brak bezpiecznych reguł rozpoznania.' if text.strip() else 'Brak odczytanego tekstu; konieczna kontrola oryginału.', 'default')
    # Typ dokumentu pozostaje edytowalną podpowiedzią; słowa z treści
    # mogą pochodzić z cytatu albo załącznika, więc nie są dowodem rodzaju.
    detected_type = 'Inne'
    prefix = text[:2500]
    for pattern, dtype in (
        (r'(?i)\bpostanowienie\b', 'Postanowienie'),
        (r'(?i)\bwyrok\b', 'Wyrok'),
        (r'(?i)\bwezwanie\b', 'Wezwanie'),
        (r'(?i)\b(?:pozew|apelacja|zażalenie|sprzeciw|wniosek dowodowy)\b', 'Pismo procesowe'),
    ):
        if re.search(pattern, prefix):
            detected_type = dtype
            break
    return {'signatures': signatures, 'suggestions': suggestions, 'document_type': detected_type}


class InboxMixin:
    """Metody wpinane do istniejącego Handler bez zmiany warstwy bezpieczeństwa sesji."""

    # Użycie type(self).__module__ zamiast import app chroni tryb __main__ (Portable).
    def _app(self):
        return sys.modules[type(self).__module__]

    def _inbox_error(self, message: str, status: int = 400, target: str = '/inbox'):
        a = self._app()
        body = (f"<div class='card'><h1>Nie udało się wykonać operacji</h1>"
                f"<p>{escape(message)}</p><a class='btn' href='{escape(target)}'>Wróć</a></div>")
        return self.send_html(a.layout('Skrzynka wpływu', body, 'inbox'), status)

    def inbox_page(self):
        a = self._app()
        with a.db() as con:
            rows = con.execute("SELECT * FROM inbox_items WHERE status='pending' ORDER BY id DESC LIMIT 150").fetchall()
        items = ''.join(
            f"<tr><td>{escape(r['created_at'][:16])}</td>"
            f"<td><b>{escape(r['original_name'])}</b><div class='small muted'>"
            f"{escape(r['ocr_status'])}</div></td>"
            f"<td><a class='btn small primary' href='/inbox/{r['id']}'>Weryfikuj</a></td></tr>"
            for r in rows)
        if not items:
            items = '<tr><td colspan="3">Brak dokumentów oczekujących na weryfikację.</td></tr>'
        body = f"""<div class='topbar'><div><h1>Skrzynka wpływu</h1>
        <div class='sub'>Lokalny OCR i propozycje czynności. Dokument ani zadania nie trafiają do sprawy bez Twojego zatwierdzenia.</div></div></div>
        <div class='card'><h2>Dodaj pismo do weryfikacji</h2>
        <form method='post' action='/inbox/upload' enctype='multipart/form-data' data-rk-inbox-upload="1">
        <label>Załącznik (pisma, zdjęcia, audio, wideo i inne; maks. 20 MB)</label>
        <input type='file' name='file' required accept='.pdf,.doc,.docx,.odt,.rtf,.txt,.md,.csv,.xlsx,.xlsm,.ods,.pptx,.png,.jpg,.jpeg,.bmp,.gif,.tif,.tiff,.webp,.mp3,.wav,.ogg,.oga,.m4a,.aac,.flac,.opus,.mp4,.m4v,.webm,.mov,.avi,.mkv,.wmv,.mpg,.mpeg,.eml,.zip'>
        <p class='small muted'>Analiza działa lokalnie. Data końcowa terminu, adresat zobowiązania i przypisanie sprawy zawsze wymagają ręcznej kontroli.</p>
        <button class='btn primary' type='submit'>Odczytaj i przygotuj propozycje</button><p id='rk-inbox-upload-feedback' class='small muted' role='status' aria-live='polite' hidden></p></form></div>
        <div class='card'><h2>Oczekujące ({len(rows)})</h2><div class='table-scroll'>
        <table><tr><th>Dodano</th><th>Dokument</th><th>Akcja</th></tr>{items}</table></div></div>"""
        return self.send_html(a.layout('Skrzynka wpływu', body, 'inbox'))

    def inbox_upload(self, fields, files):
        a = self._app()
        uploaded = files.get('file') if isinstance(files, dict) else None
        if not isinstance(uploaded, tuple) or not uploaded[0] or not isinstance(uploaded[1], bytes):
            return self._inbox_error('Wskaż prawidłowy plik.')
        name = a.safe_filename(uploaded[0]); data = uploaded[1]
        suffix = Path(name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            return self._inbox_error('Format pliku nie jest obsługiwany przez skrzynkę wpływu.')
        if not data or len(data) > MAX_INBOX_BYTES:
            return self._inbox_error('Plik musi mieć od 1 bajta do 20 MB.', 413)
        folder = a.FILES_DIR / '_inbox'
        stored = uuid.uuid4().hex + suffix
        dest = folder / stored
        # Przetwarzanie jest lokalne. OCR skanów wymaga dostępnego Tesseracta.
        try:
            extracted, used, status, language = a.extract_document_text(name, data)
            analysis = analyze_letter(extracted)
            a.atomic_write_bytes(dest, data)
            with a.db() as con:
                cur = con.execute("""INSERT INTO inbox_items
                    (original_name, stored_name, file_hash, extracted_text, ocr_status,
                     ocr_used, ocr_language, suggestions_json, created_by)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (name, stored, hashlib.sha256(data).hexdigest(), extracted[:5000000],
                     status, int(bool(used)), language,
                     json.dumps(analysis, ensure_ascii=False), self.current_author(fields)))
                item_id = cur.lastrowid
        except Exception as exc:
            dest.unlink(missing_ok=True)
            a.log_app_exception('/inbox/upload', exc)
            return self._inbox_error('Nie udało się przeanalizować pliku. Oryginał nie został dopisany do sprawy.', 500)
        return self.redirect(f'/inbox/{item_id}')

    def inbox_review(self, item_id: int):
        a = self._app()
        with a.db() as con:
            row = con.execute('SELECT * FROM inbox_items WHERE id=?', (item_id,)).fetchone()
            cases = con.execute("SELECT id,signature,internal_signature,title FROM cases ORDER BY status='closed',title").fetchall()
        if not row:
            return self.send_error(404)
        if row['status'] != 'pending':
            return self.redirect(f"/document/{row['document_id']}/open" if row['document_id'] else '/inbox')
        analysis = json.loads(row['suggestions_json'])
        sigs = analysis.get('signatures', [])
        sigset = {re.sub(r'\s+', '', s).upper() for s in sigs}
        ranked = sorted(cases, key=lambda c: (0 if any(re.sub(r'\s+', '', c[k] or '').upper() in sigset
                   for k in ('signature', 'internal_signature') if c[k]) else 1, c['title'].casefold()))
        choices = "<option value=''>— wybierz i sprawdź sprawę —</option>" + ''.join(
            f"<option value='{c['id']}'>{escape(c['signature'] or c['internal_signature'] or 'Bez sygnatury')} — {escape(c['title'])}</option>"
            for c in ranked)
        signatures = ', '.join(sigs) if sigs else 'Nie rozpoznano jednoznacznej sygnatury'
        proposed_dtype = analysis.get('document_type', 'Inne')
        dtype_choices = ''.join(
            f"<option value='{escape(k)}' {'selected' if k == proposed_dtype else ''}>{escape(k)}</option>"
            for k in ('Inne', 'Pismo procesowe', 'Postanowienie', 'Wyrok', 'Wezwanie', 'Korespondencja'))
        warning = ("Nie udało się odczytać tekstu. Obejrzyj oryginał i uzupełnij wszystko ręcznie."
                   if not row['extracted_text'].strip() else
                   'OCR może zawierać błędy. Każdą propozycję porównaj z oryginałem.')
        options = ''.join(f"<option value='{escape(k)}'>{escape(k)}</option>" for k in ACTION_TYPES)
        parts = []
        proposals = analysis.get('suggestions', [])[:12]
        for idx in range(len(proposals) + 2):
            p = proposals[idx] if idx < len(proposals) else {'title': '', 'kind': 'Zadanie', 'source': '', 'priority': 'normal'}
            is_suggestion = idx < len(proposals)
            kinds = ''.join(f"<option value='{escape(k)}' {'selected' if p.get('kind') == k else ''}>{escape(k)}</option>"
                            for k in ACTION_TYPES)
            source = f"<div class='small muted'>Wskazówka OCR: {escape(p.get('source',''))}</div>" if p.get('source') else ''
            parts.append(f"""<div class='card' style='padding:14px'>
                <label><input type='checkbox' name='act_{idx}_selected' value='1' style='width:auto' {'checked' if is_suggestion else ''}>
                  {'Propozycja' if is_suggestion else 'Nowa czynność'} {idx+1} — uwzględnij po zatwierdzeniu</label>
                {source}<div class='form-grid'>
                <div><label>Rodzaj</label><select name='act_{idx}_kind'>{kinds}</select></div>
                <div><label>Data (tylko po ręcznej kontroli)</label><input type='date' name='act_{idx}_due'></div>
                <div class='full'><label>Opis / polecenie (edytowalne)</label>
                <input name='act_{idx}_title' maxlength='500' value='{escape(p.get('title',''))}'></div>
                <div><label>Priorytet</label><select name='act_{idx}_priority'>
                <option value='normal'>Normalny</option><option value='high'>Wysoki</option></select></div></div></div>""")
        preview = render_preview(a.FILES_DIR / '_inbox' / row['stored_name'], row['original_name'],
            f'/inbox/{item_id}/file',pdf_pages_base=f'/preview/inbox/{item_id}/page',
            image_url=f'/preview/inbox/{item_id}/image')
        snippet = escape(row['extracted_text'][:20000]) or 'Brak tekstu. Zobacz oryginał.'
        body = f"""<div class='topbar'><div><h1>Sprawdź pismo przed przyjęciem</h1>
        <div class='sub'>{escape(row['original_name'])} · OCR: {escape(row['ocr_status'])}</div></div>
        <a class='btn' href='/inbox'>Wróć do skrzynki</a></div>
        <div class='notice'><b>Wymagana kontrola:</b> {escape(warning)}
        Terminy i monity nie otrzymują automatycznej daty, nawet gdy dokument podaje liczbę dni.</div>
        <div class='card'><h2>Oryginalny dokument</h2>
        <a class='btn small' href='/inbox/{item_id}/file?download=1'>Pobierz oryginał</a>
        {preview}<details><summary>Odczytany tekst (może być błędny)</summary>
        <pre style='white-space:pre-wrap;max-height:400px;overflow:auto'>{snippet}</pre></details></div>
        <form method='post' action='/inbox/{item_id}/approve'>
        <div class='card'><h2>1. Sprawdź i przypisz pismo</h2>
        <p class='small'>Odczytane sygnatury: <b>{escape(signatures)}</b>. To tylko podpowiedź, sprawę wybierasz ręcznie.</p>
        <div class='form-grid'><div class='full'><label>Sprawa *</label><select name='case_id' required>{choices}</select></div>
        <div class='full'><label>Tytuł dokumentu *</label><input name='title' required maxlength='500' value='{escape(Path(row['original_name']).stem)}'></div>
        <div><label>Rodzaj (podpowiedź)</label><select name='doc_type'>{dtype_choices}</select></div>
        <div><label>Data pisma</label><input type='date' name='doc_date'></div>
        <div><label>Data wpływu</label><input type='date' name='received_date'></div>
        <div><label>Data doręczenia</label><input type='date' name='delivered_date'></div>
        <div class='full'><label><input type='checkbox' name='allow_duplicate' value='1' style='width:auto'>
        Zezwól na identyczny plik, jeżeli świadomie dodaję kopię do kolejnej sprawy</label></div></div></div>
        <h2>2. Zmień / odznacz proponowane działania</h2>
        <p class='small muted'>Zaznaczone propozycje zapiszą się dopiero po końcowym zatwierdzeniu. Dla terminu procesowego ustal ręcznie początek biegu i datę końcową. Datę możesz pozostawić pustą, a zadanie uzupełnić później.</p>
        {''.join(parts)}<div class='card'><h2>3. Ostateczne zatwierdzenie</h2>
        <label><input type='checkbox' required name='verified' value='yes' style='width:auto'>
        Porównałem/porównałam dane i zaznaczone działania z oryginalnym pismem.</label>
        <button class='btn primary' type='submit'>Zapisz dokument i zaznaczone czynności</button></div></form>
        <form method='post' action='/inbox/{item_id}/discard'
          onsubmit="return confirm('Odrzucić dokument ze skrzynki bez zapisywania do sprawy?');">
          <button class='btn danger'>Odrzuć dokument</button></form>"""
        return self.send_html(a.layout('Weryfikacja pisma', body, 'inbox'))

    def inbox_file(self, item_id: int):
        a=self._app()
        with a.db() as con:
            row=con.execute('SELECT original_name,stored_name,status FROM inbox_items WHERE id=?',(item_id,)).fetchone()
        if not row or row['status']!='pending' or not row['stored_name']:
            return self.send_error(404)
        stored=row['stored_name']
        folder=(a.FILES_DIR/'_inbox').resolve()
        if Path(stored).name!=stored:return self.send_error(404)
        p=(folder/stored).resolve()
        if p.parent!=folder or not p.is_file():return self.send_error(404)
        return serve_local_file(self,p,row['original_name'] or p.name)

    def inbox_approve(self, item_id: int, fields):
        a = self._app()
        if fields.get('verified') != 'yes':
            return self._inbox_error('Zaznacz potwierdzenie ręcznej weryfikacji.', target=f'/inbox/{item_id}')
        try:
            cid = int(fields.get('case_id') or 0)
        except ValueError:
            cid = 0
        title = (fields.get('title') or '').strip()[:500]
        if cid <= 0 or not title:
            return self._inbox_error('Sprawa i tytuł pisma są wymagane.', target=f'/inbox/{item_id}')
        try:
            ddate, rdate, delivered = (valid_date(fields.get(k, ''))
                for k in ('doc_date', 'received_date', 'delivered_date'))
        except ValueError as exc:
            return self._inbox_error(str(exc), target=f'/inbox/{item_id}')
        dtype = (fields.get('doc_type') or 'Inne').strip()[:100]
        if dtype not in {'Inne', 'Pismo procesowe', 'Postanowienie', 'Wyrok', 'Wezwanie', 'Korespondencja'}:
            return self._inbox_error('Nieprawidłowy rodzaj dokumentu.', target=f'/inbox/{item_id}')
        with a.db() as con:
            row = con.execute('SELECT * FROM inbox_items WHERE id=?', (item_id,)).fetchone()
        if not row:
            return self.send_error(404)
        if row['status'] == 'approved' and row['document_id']:
            return self.redirect(f"/document/{row['document_id']}/open")
        if row['status'] != 'pending':
            return self._inbox_error('Pismo już zostało rozpatrzone.', 409)
        proposals = json.loads(row['suggestions_json']).get('suggestions', [])[:12]
        selected = []
        # Walidacja kompletu danych PRZED zapisaniem dokumentu i zadań.
        for idx in range(len(proposals) + 2):
            if fields.get(f'act_{idx}_selected') != '1':
                continue
            item_title = (fields.get(f'act_{idx}_title') or '').strip()[:500]
            if not item_title:
                return self._inbox_error(f'Czynność {idx+1} nie ma opisu.', target=f'/inbox/{item_id}')
            kind = fields.get(f'act_{idx}_kind') or 'Zadanie'
            if kind not in ACTION_TYPES:
                return self._inbox_error('Nieprawidłowy typ czynności.', target=f'/inbox/{item_id}')
            priority = fields.get(f'act_{idx}_priority') or 'normal'
            if priority not in {'normal', 'high'}:
                return self._inbox_error('Nieprawidłowy priorytet.', target=f'/inbox/{item_id}')
            try:
                due = valid_date(fields.get(f'act_{idx}_due', ''))
            except ValueError as exc:
                return self._inbox_error(f'Czynność {idx+1}: {exc}', target=f'/inbox/{item_id}')
            source = proposals[idx].get('source', '') if idx < len(proposals) else 'Czynność wpisana ręcznie.'
            selected.append((kind, item_title, due, priority, source))
        original = row['original_name']; staged = a.FILES_DIR / '_inbox' / row['stored_name']
        dest = None; doc_id = None; author = self.current_author(fields)
        try:
            with a.db() as con:
                con.execute('BEGIN IMMEDIATE')
                live = con.execute('SELECT * FROM inbox_items WHERE id=?', (item_id,)).fetchone()
                if not live or live['status'] != 'pending':
                    raise ValueError('Dokument został już rozpatrzony w innej sesji.')
                if not con.execute('SELECT 1 FROM cases WHERE id=?', (cid,)).fetchone():
                    raise ValueError('Wybrana sprawa nie istnieje.')
                if not staged.is_file():
                    raise ValueError('Brak oryginalnego pliku w skrzynce wpływu.')
                existing = con.execute('SELECT id FROM documents WHERE file_hash=? LIMIT 1', (live['file_hash'],)).fetchone()
                if existing and fields.get('allow_duplicate') != '1':
                    raise ValueError('Identyczny plik istnieje już w kartotece. Sprawdź dokumenty albo świadomie zaznacz zgodę na duplikat.')
                folder = a.FILES_DIR / f'sprawa_{cid}'
                stored = uuid.uuid4().hex + Path(original).suffix.lower()
                dest = folder / stored
                raw = staged.read_bytes()
                if hashlib.sha256(raw).hexdigest() != live['file_hash']:
                    raise ValueError('Plik oczekujący został zmieniony lub uszkodzony. Wgraj go ponownie.')
                a.atomic_write_bytes(dest, raw)
                cur = con.execute("""INSERT INTO documents
                    (case_id,doc_date,received_date,delivered_date,doc_type,doc_status,title,description,
                    stored_name,original_name,created_by,updated_by,file_hash,extracted_text,
                    ocr_used,ocr_status,ocr_language,indexed_at)
                    VALUES(?,?,?,?,?,'Aktywny',?,'',?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                    (cid,ddate,rdate,delivered,dtype,title,stored,original,author,author,
                     live['file_hash'], live['extracted_text'], live['ocr_used'],
                     live['ocr_status'], live['ocr_language']))
                doc_id = cur.lastrowid
                # FTS można odtworzyć; jego brak nie może zablokować przyjęcia dokumentu.
                try:
                    con.execute("INSERT INTO document_fts(document_id,case_id,title,filename,body) VALUES(?,?,?,?,?)",
                                (doc_id, cid, title, original, live['extracted_text']))
                except Exception:
                    pass
                a.audit(con, cid, 'document', doc_id, 'Przyjęto pismo ze skrzynki wpływu',
                        f'{title}; plik: {original}; zweryfikował: {author}', author)
                for kind, item_title, due, priority, source in selected:
                    notes = f'Źródło: pismo #{doc_id} ({original}).\nPropozycja OCR zweryfikowana przez użytkownika.\nFragment: {source}'
                    task = con.execute("""INSERT INTO tasks
                        (case_id,title,due_date,status,priority,depends_on,notes,task_type,created_by,updated_by)
                        VALUES(?,?,?,'open',?,'',?,?,?,?)""",
                        (cid, item_title, due, priority, notes, kind, author, author))
                    a.sync_task_alert(con, task.lastrowid, author)
                    a.audit(con, cid, 'task', task.lastrowid, 'Zatwierdzono czynność z pisma',
                            f'{kind}: {item_title}; data: {due or "nieustalona"}; źródło: pismo #{doc_id}', author)
                con.execute("UPDATE inbox_items SET status='approved',document_id=?,reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP,extracted_text='',suggestions_json='[]' WHERE id=?",
                            (doc_id, author, item_id))
        except Exception as exc:
            if dest:
                dest.unlink(missing_ok=True)
            if isinstance(exc, ValueError):
                return self._inbox_error(str(exc), 409, f'/inbox/{item_id}')
            a.log_app_exception('/inbox/approve', exc)
            return self._inbox_error('Nie udało się zapisać pisma i czynności; nie zatwierdzono zmian.', 500, f'/inbox/{item_id}')
        staged.unlink(missing_ok=True)
        return self.redirect(f'/document/{doc_id}/open')

    def inbox_discard(self, item_id: int, fields):
        a = self._app()
        with a.db() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute('SELECT * FROM inbox_items WHERE id=?', (item_id,)).fetchone()
            if not row or row['status'] != 'pending':
                return self._inbox_error('Dokument nie jest już oczekujący.', 409)
            con.execute("UPDATE inbox_items SET status='discarded',reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP,extracted_text='',suggestions_json='[]' WHERE id=?",
                        (self.current_author(fields), item_id))
        (a.FILES_DIR / '_inbox' / row['stored_name']).unlink(missing_ok=True)
        return self.redirect('/inbox')
