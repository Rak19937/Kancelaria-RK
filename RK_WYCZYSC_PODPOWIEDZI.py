#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RK KANCELARIA — usuń przykłady oparte na rzeczywistych sprawach z app.py.

Uruchom lokalnie w katalogu ze źródłami programu: python RK_WYCZYSC_PODPOWIEDZI.py
Skrypt NIE otwiera ani nie modyfikuje bazy SQLite, plików klientów czy katalogu Data.
Skrypt zawiera tylko ogólne reguły czyszczenia i nie przechowuje
danych klientów. Po uruchomieniu sprawdź, czy app.py został oczyszczony.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import tempfile


def replace_one(source: str, pattern: str, replacement: str, label: str, flags: int = 0) -> str:
    updated, n = re.subn(pattern, lambda _m: replacement, source, flags=flags)
    if n != 1:
        raise RuntimeError(f"{label}: wymagano dokładnie jednego dopasowania, znaleziono {n}. Nie zapisano zmian.")
    return updated


def sanitize(source: str) -> str:
    replacements = [
        (r"title='Krótka nazwa robocza, np\. [^']*'", "title='Krótka nazwa robocza, np. sprawa o zapłatę'", "Opis pola nazwy sprawy"),
        (r"name='title' required autofocus placeholder='[^']*'", "name='title' required autofocus placeholder='np. Spółka A przeciwko Spółce B'", "Przykład nazwy sprawy"),
        (r"name='subject' required placeholder='[^']*'", "name='subject' required placeholder='np. zapłata wynikająca z umowy'", "Przedmiot sprawy"),
        (r"name='client' placeholder='[^']*'", "name='client' placeholder='np. Klient A'", "Przykład klienta"),
        (r"name='internal_signature' placeholder='[^']*'", "name='internal_signature' placeholder='np. RK/2026/001'", "Sygnatura wewnętrzna"),
        (r"<div class='full'><label>Tagi</label><input name='tags' placeholder='[^']*'", "<div class='full'><label>Tagi</label><input name='tags' placeholder='np. pilne, do analizy, termin'", "Przykłady tagów"),
        (r"<input name='q' value='\{esc\(q\)\}' placeholder='np\. [^']*'><button class='btn primary'>Szukaj tagu", "<input name='q' value='{esc(q)}' placeholder='np. termin, pilne, do analizy'><button class='btn primary'>Szukaj tagu", "Wyszukiwarka tagów"),
    ]
    for pattern, replacement, label in replacements:
        source = replace_one(source, pattern, replacement, label)

    # Zamień cały dobrowolny zestaw demonstracyjny na syntetyczne dane.
    # Dotychczasowy zestaw zawierał szczegóły rzeczywistych spraw.
    generic_demo = '''def seed_demo(con: sqlite3.Connection) -> None:
    """Fikcyjne dane demonstracyjne, wyłącznie po świadomym włączeniu demo."""
    cases = [
        ("I C 123/26", "Przykładowa sprawa o zapłatę", "Sąd Rejonowy", "cywilna", "Zapłata wynikająca z umowy", "active", "Sprawdzić dokumenty", "Wyłącznie fikcyjny przykład."),
        ("III RC 456/26", "Przykładowa sprawa rodzinna", "Sąd Rejonowy", "rodzinna", "Świadczenia alimentacyjne", "waiting", "Oczekiwać na korespondencję", "Wyłącznie fikcyjny przykład."),
    ]
    con.executemany(
        "INSERT INTO cases(signature,title,court,category,subject,status,next_step,notes) VALUES(?,?,?,?,?,?,?,?)",
        cases,
    )


'''
    source = replace_one(
        source,
        r'^def seed_demo\(con: sqlite3\.Connection\) -> None:\n.*?(?=^def esc\(s\) -> str:)',
        generic_demo,
        'Zestaw demonstracyjny',
        flags=re.MULTILINE | re.DOTALL,
    )
    compile(source, 'app.py', 'exec')
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', default='app.py', help='Ścieżka do app.py')
    parser.add_argument('--dry-run', action='store_true', help='Tylko walidacja, bez zapisu')
    args = parser.parse_args()
    path = Path(args.app).resolve()
    if not path.is_file():
        parser.error(f'Nie znaleziono: {path}')
    old = path.read_text(encoding='utf-8')
    updated = sanitize(old)
    if updated == old:
        print('Brak zmian.')
        return
    if args.dry_run:
        print('Kontrola poprawna: podpowiedzi i dane demonstracyjne mogą zostać oczyszczone.')
        return
    # Zapis atomowy; błędy walidacji nie zmieniają oryginału.
    fd, tmp_name = tempfile.mkstemp(prefix='.rk-app-clean-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as out:
            out.write(updated)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    print('Oczyszczono app.py. Nie zmodyfikowano żadnych danych użytkownika.')
    print('Sprawdź git diff app.py przed zatwierdzeniem zmian.')


if __name__ == '__main__':
    main()
