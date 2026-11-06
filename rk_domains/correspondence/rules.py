"""Czyste reguły pomocnicze korespondencji, bez działań w bazie."""
from __future__ import annotations
from datetime import date

def iso_date(value):
    s = str(value or '').strip()
    if not s:
        return ''
    try:
        d = date.fromisoformat(s)
        if d.isoformat() != s:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('Nieprawidłowa data. Wymagany format RRRR-MM-DD.')
    return s

def needs_followup(row, today=None, reply_count=0):
    """Wyłącznie sugestia organizacyjna z daty ręcznie wpisanej przez użytkownika."""
    today = today or date.today()
    try:
        return (row['direction'] == 'outgoing'
                and int(row['response_expected'] or 0) == 1
                and bool(row['expected_reply_on'])
                and date.fromisoformat(row['expected_reply_on']) < today
                and row['status'] not in ('answered', 'closed')
                and not reply_count)
    except (KeyError, ValueError, TypeError, IndexError):
        return False
