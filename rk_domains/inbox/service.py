"""RK KANCELARIA 0.4: staging pism przed akceptacją przez człowieka.

Nie tworzy dokumentu w sprawie ani zadań. Zmiana stanu wyłącznie po
ręcznym zatwierdzeniu, obsługiwanym w dotychczasowym InboxMixin.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from rk_domains.inbox.analysis import analyze_letter


class InboxUploadValidationError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def stage_inbox_upload(app, uploaded, author: str, *, allowed_suffixes: set[str], max_bytes: int) -> int:
    """Umieść wpływ w buforze; nigdy nie przypisuj go automatycznie do sprawy."""
    if not isinstance(uploaded, tuple) or len(uploaded) < 2 or not uploaded[0] or not isinstance(uploaded[1], bytes):
        raise InboxUploadValidationError('Wskaż prawidłowy plik.')
    name = app.safe_filename(uploaded[0])
    data = uploaded[1]
    suffix = Path(name).suffix.lower()
    if suffix not in allowed_suffixes:
        raise InboxUploadValidationError('Format pliku nie jest obsługiwany przez skrzynkę wpływu.')
    if not data or len(data) > max_bytes:
        raise InboxUploadValidationError('Plik musi mieć od 1 bajta do 20 MB.', 413)

    dest = app.FILES_DIR / '_inbox' / (uuid.uuid4().hex + suffix)
    try:
        extracted, used, status, language = app.extract_document_text(name, data)
        analysis = analyze_letter(extracted)
        app.atomic_write_bytes(dest, data)
        with app.db() as con:
            cur = con.execute('''INSERT INTO inbox_items
                (original_name, stored_name, file_hash, extracted_text, ocr_status,
                 ocr_used, ocr_language, suggestions_json, created_by)
                VALUES(?,?,?,?,?,?,?,?,?)''',
                (name, dest.name, hashlib.sha256(data).hexdigest(), extracted[:5000000],
                 status, int(bool(used)), language,
                 json.dumps(analysis, ensure_ascii=False), author))
            return int(cur.lastrowid)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
