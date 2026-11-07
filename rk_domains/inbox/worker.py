"""Durable single-worker queue for inbox OCR; no automatic approval of legal actions.

Pending jobs live in SQLite alongside inbox_items. A daemon thread processes one
job at a time, so large scans do not hold an HTTP request open. Jobs marked as
processing are returned to the queue after a process restart.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from rk_domains.inbox.analysis import analyze_letter

_LOCK = threading.Lock()
_WAKE = threading.Event()
_WORKER = None


def ensure_async_schema(con):
    con.execute('''CREATE TABLE IF NOT EXISTS inbox_analysis_jobs (
        inbox_id INTEGER PRIMARY KEY REFERENCES inbox_items(id) ON DELETE CASCADE,
        state TEXT NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','processing','ready','error')),
        error TEXT NOT NULL DEFAULT '',
        attempts INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')
    con.execute('CREATE INDEX IF NOT EXISTS idx_inbox_jobs_state ON inbox_analysis_jobs(state,inbox_id)')


def job_state(con, inbox_id: int):
    return con.execute('SELECT state,error,attempts FROM inbox_analysis_jobs WHERE inbox_id=?',(inbox_id,)).fetchone()


def queue_job(con, inbox_id: int):
    con.execute('''INSERT INTO inbox_analysis_jobs(inbox_id,state,error,updated_at)
        VALUES(?,'queued','',CURRENT_TIMESTAMP)
        ON CONFLICT(inbox_id) DO UPDATE SET state='queued',error='',updated_at=CURRENT_TIMESTAMP''',(inbox_id,))


def _one_job(app) -> bool:
    with app.db() as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('''SELECT j.inbox_id,i.original_name,i.stored_name
            FROM inbox_analysis_jobs j JOIN inbox_items i ON i.id=j.inbox_id
            WHERE j.state='queued' AND i.status='pending'
            ORDER BY j.inbox_id LIMIT 1''').fetchone()
        if not row:
            return False
        item_id=int(row['inbox_id']); filename=row['original_name']; stored=row['stored_name']
        con.execute('''UPDATE inbox_analysis_jobs SET state='processing',attempts=attempts+1,
            updated_at=CURRENT_TIMESTAMP WHERE inbox_id=?''',(item_id,))
    try:
        source=app.FILES_DIR/'_inbox'/stored
        raw=source.read_bytes()
        extracted,used,status,language=app.extract_document_text(filename,raw)
        analysis=analyze_letter(extracted)
        with app.db() as con:
            # Discard is a competing operation; never overwrite a discarded record.
            changed=con.execute('''UPDATE inbox_items SET extracted_text=?,ocr_used=?,
                ocr_status=?,ocr_language=?,suggestions_json=?
                WHERE id=? AND status='pending' ''',
                (extracted[:5_000_000],int(bool(used)),status,language,
                 json.dumps(analysis,ensure_ascii=False),item_id)).rowcount
            con.execute('''UPDATE inbox_analysis_jobs SET state=?,error='',updated_at=CURRENT_TIMESTAMP
                           WHERE inbox_id=?''',('ready' if changed else 'error',item_id))
    except Exception as exc:
        try:
            app.log_app_exception('/inbox/ocr-queue',exc)
            with app.db() as con:
                con.execute("UPDATE inbox_analysis_jobs SET state='error',error=?,updated_at=CURRENT_TIMESTAMP WHERE inbox_id=?",
                            (str(exc)[:180],item_id))
        except Exception:
            pass
    return True


def _loop(app):
    try:
        # Startup recovery of interrupted OCR, but never repeat completed work.
        with app.db() as con:
            con.execute("UPDATE inbox_analysis_jobs SET state='queued',updated_at=CURRENT_TIMESTAMP WHERE state='processing'")
        while True:
            if _one_job(app):
                continue
            _WAKE.wait(timeout=25)
            _WAKE.clear()
    except Exception as exc:
        try:app.log_app_exception('/inbox/worker',exc)
        except Exception:pass
    finally:
        global _WORKER
        with _LOCK:_WORKER=None


def start_worker(app) -> None:
    global _WORKER
    if not getattr(app,'INBOX_ASYNC_MODE',False):
        return
    with _LOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER=threading.Thread(target=_loop,args=(app,),name='rk-inbox-ocr',daemon=True)
            _WORKER.start()
    _WAKE.set()


def retry_job(app, inbox_id: int) -> bool:
    with app.db() as con:
        row=con.execute('''SELECT i.id FROM inbox_items i
            JOIN inbox_analysis_jobs j ON j.inbox_id=i.id
            WHERE i.id=? AND i.status='pending' AND j.state='error' ''',(inbox_id,)).fetchone()
        if not row:return False
        queue_job(con,inbox_id)
    start_worker(app)
    return True
