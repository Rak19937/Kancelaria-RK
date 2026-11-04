# -*- coding: utf-8 -*-
"""RK KANCELARIA 0.3.1: poprawki ekranów i informacji o licencji.

Uruchamiaj po AKTUALIZUJ_KOD.py, wyłącznie w katalogu źródłowym.
Skrypt nie odczytuje ani nie zmienia baz danych, spraw i dokumentów użytkownika.
"""
from __future__ import annotations

import sys
from pathlib import Path

ABOUT_MARKER = '    def about_page(self):'


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: oczekiwano dokładnie 1 wystąpienia, znaleziono {count}.')
    return source.replace(old, new, 1)


def update(root: Path) -> bool:
    root = root.resolve()
    app_path = root / 'app.py'
    readme_path = root / 'README.md'
    license_path = root / 'LICENSE.txt'
    for p in (app_path, readme_path, license_path):
        if not p.is_file():
            raise RuntimeError(f'Brak wymaganego pliku: {p.name}')

    app = app_path.read_text(encoding='utf-8')
    required_inbox = (
        'from rk_inbox import InboxMixin, ensure_inbox_schema',
        'class Handler(InboxMixin, BaseHTTPRequestHandler):',
        'ensure_inbox_schema(con)',
        'if path == "/inbox": return self.inbox_page()',
        'if path == "/inbox/upload": return self.inbox_upload(fields, files)',
    )
    if not all(marker in app for marker in required_inbox):
        raise RuntimeError('Skrzynka wpływu nie została zintegrowana. Najpierw uruchom AKTUALIZUJ_KOD.py.')

    if ABOUT_MARKER in app:
        markers = (
            '("/about", "ⓘ", "O programie", "about")',
            'if path == "/about": return self.about_page()',
        )
        if not all(marker in app for marker in markers):
            raise RuntimeError('Wykryto niepełną integrację ekranu O programie — nie nadpisuję pliku.')
        changed = False
        updated = app
    else:
        # Wszystkie zamiany są kontrolowane i przygotowywane w pamięci PRZED zapisem.
        updated = replace_once(
            app,
            '            ("/backups", "⛁", "Kopie bezpieczeństwa", "backups"),',
            '            ("/backups", "⛁", "Kopie bezpieczeństwa", "backups"),\n'
            '            ("/about", "ⓘ", "O programie", "about"),',
            'nawigacja',
        )
        updated = replace_once(
            updated,
            '            if path == "/history": return self.history_page(qs)',
            '            if path == "/history": return self.history_page(qs)\n'
            '            if path == "/about": return self.about_page()',
            'obsługa GET',
        )
        new_method = '''    def about_page(self):
        body = (
            "<div class='topbar'><div><h1>O programie</h1>"
            f"<div class='sub'>{esc(APP_NAME)} · wersja {esc(VERSION)}</div></div></div>"
            "<div class='card'><h2>RK KANCELARIA</h2>"
            "<p>System wspomagający organizację pracy kancelarii prawnej.</p>"
            "<p><b>Projekt i rozwój:</b> Robert Kłosowski</p>"
            "<p>© 2026 Robert Kłosowski — w zakresie przysługujących praw.</p>"
            "<p><b>Status:</b> wersja rozwojowa. Oprogramowanie wspomaga pracę, "
            "lecz nie zastępuje samodzielnej oceny prawnej ani weryfikacji terminów.</p>"
            "<p>Korzystanie z komponentów zewnętrznych podlega ich własnym licencjom. "
            "Zasady korzystania opisano w pliku LICENSE.txt dołączonym do programu.</p></div>"
        )
        return self.send_html(layout('O programie', body, 'about'))

'''
        updated = replace_once(updated, '    def log_message(self, format, *args):',
                               new_method + '    def log_message(self, format, *args):',
                               'metoda O programie')
        changed = True

    readme = readme_path.read_text(encoding='utf-8')
    section = '''\n\n## Status projektu i zasady korzystania
RK KANCELARIA jest na etapie rozwoju i testów. Projekt i rozwój: Robert Kłosowski.
© 2026 Robert Kłosowski — w zakresie przysługujących praw.

Repozytorium nie jest obecnie udostępniane na licencji open source.
Nie jest udzielana ogólna zgoda na komercyjne rozpowszechnianie elementów
objętych prawami uprawnionego. Zewnętrzne biblioteki i narzędzia pozostają
objęte swoimi licencjami. Szczegóły: `LICENSE.txt`.

Odczyt pism może być niedokładny. Dane, daty, terminy i sugerowane czynności
wymagają każdorazowego sprawdzenia i zatwierdzenia przez użytkownika.
'''
    if '## Status projektu i zasady korzystania' not in readme:
        readme += section
    # Nie zapisuj fragmentarycznie: zamiany app.py są już zweryfikowane.
    if updated != app:
        app_path.write_text(updated, encoding='utf-8')
    if readme != readme_path.read_text(encoding='utf-8'):
        readme_path.write_text(readme, encoding='utf-8')
        changed = True
    print('RK KANCELARIA 0.3.1: integracja O programie i README — OK.' if changed
          else 'RK KANCELARIA 0.3.1: poprawki były już zastosowane.')
    return changed


if __name__ == '__main__':
    try:
        update(Path(sys.argv[1] if len(sys.argv) > 1 else '.'))
    except Exception as exc:
        print(f'BŁĄD STABILIZACJI: {exc}', file=sys.stderr)
        raise SystemExit(1)
