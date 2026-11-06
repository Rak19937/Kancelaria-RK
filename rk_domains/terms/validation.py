"""Daty i godziny kontrolne (bez automatycznego liczenia terminów prawnych)."""
from __future__ import annotations
import re
from datetime import date

def date_iso(value, required=True):
    value = str(value or '').strip()
    if not value and not required:
        return ''
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError('Podaj poprawną datę w formacie RRRR-MM-DD.')
    if value != parsed.isoformat():
        raise ValueError('Data musi być w formacie RRRR-MM-DD.')
    return value

def time_hm(value):
    value = str(value or '').strip()
    if not value:
        return ''
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value):
        raise ValueError('Godzina musi mieć format GG:MM.')
    return value
