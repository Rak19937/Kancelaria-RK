"""Zapytania o dokumenty jednej sprawy (bez kopiowania plików)."""
from __future__ import annotations
import sqlite3

def case_document_rows(con: sqlite3.Connection, case_id: int):
    """Dokumenty główne i współdzielone, bez powielania identyfikatorów."""
    return con.execute('''
        SELECT d.* FROM documents d
        WHERE d.case_id=? OR EXISTS (
            SELECT 1 FROM document_case_links l
            WHERE l.document_id=d.id AND l.case_id=?
        )
        ORDER BY COALESCE(NULLIF(d.delivered_date,''),NULLIF(d.received_date,''),
                          NULLIF(d.doc_date,''),d.created_at) DESC,d.id DESC
    ''', (case_id, case_id)).fetchall()
