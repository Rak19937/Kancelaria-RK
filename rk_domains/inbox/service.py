"""Staging of incoming documents, optionally queued OCR (0.4-dev2).

No document or task is added to a case until explicit user approval.
"""
from __future__ import annotations
import hashlib
import json
import uuid
from pathlib import Path
from rk_domains.inbox.analysis import analyze_letter
from rk_domains.inbox.worker import queue_job,start_worker

class InboxUploadValidationError(ValueError):
    def __init__(self, message: str, status: int=400):
        super().__init__(message)
        self.status=status


def stage_inbox_upload(app, uploaded, author: str, *, allowed_suffixes: set[str], max_bytes: int) -> int:
    if not isinstance(uploaded, tuple) or len(uploaded)<2 or not uploaded[0] or not isinstance(uploaded[1],bytes):
        raise InboxUploadValidationError('Wskaż prawidłowy plik.')
    name=app.safe_filename(uploaded[0]);data=uploaded[1];suffix=Path(name).suffix.lower()
    if suffix not in allowed_suffixes:
        raise InboxUploadValidationError('Ten rodzaj pliku nie może zostać przyjęty.')
    if not data or len(data)>max_bytes:
        raise InboxUploadValidationError('Plik musi mieć od 1 bajta do 20 MB.',413)
    dest=app.FILES_DIR/'_inbox'/(uuid.uuid4().hex+suffix)
    async_mode=bool(getattr(app,'INBOX_ASYNC_MODE',False))
    committed=False
    try:
        if async_mode:
            # Upload is immediate. OCR worker only reads the saved original.
            analysis={'signatures':[],'suggestions':[],'document_type':'Inne'}
            extracted='';used=0;status='w_kolejce';language=''
        else:
            # Kept for existing offline test stubs and legacy integration tools.
            extracted,used,status,language=app.extract_document_text(name,data)
            analysis=analyze_letter(extracted)
        app.atomic_write_bytes(dest,data)
        with app.db() as con:
            cur=con.execute('''INSERT INTO inbox_items
                (original_name,stored_name,file_hash,extracted_text,ocr_status,
                 ocr_used,ocr_language,suggestions_json,created_by)
                VALUES(?,?,?,?,?,?,?,?,?)''',
                (name,dest.name,hashlib.sha256(data).hexdigest(),extracted[:5000000],
                 status,int(bool(used)),language,json.dumps(analysis,ensure_ascii=False),author))
            item_id=int(cur.lastrowid)
            if async_mode:queue_job(con,item_id)
        committed=True
        if async_mode:start_worker(app)
        return item_id
    except Exception:
        # Only remove the original when its DB record has not been committed.
        # If the worker failed after commit, leave the saved original recoverable.
        if not committed:dest.unlink(missing_ok=True)
        raise
