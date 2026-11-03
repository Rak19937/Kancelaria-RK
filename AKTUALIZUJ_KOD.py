# -*- coding: utf-8 -*-
"""Automatyczna, powtarzalna integracja Skrzynki wpływu w RK KANCELARIA.

W GitHub Actions uruchamiana po pobraniu repo, PRZED testami i buildem.
Bez danych użytkowników, kopii baz i operacji sieciowych.
Zmienia wyłącznie pliki źródłowe app.py i README.md.

Nie uruchamiać w katalogu rozpakowanego programu EXE.
"""
from __future__ import annotations

import sys
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"Integracja przerwana: {label}: oczekiwano 1 wystąpienia, wykryto {count}.")
    return source.replace(old, new, 1)


def update(repo: Path) -> bool:
    root = repo.resolve()
    app_path = root / 'app.py'
    readme_path = root / 'README.md'
    if not app_path.is_file() or not readme_path.is_file():
        raise RuntimeError('Brakuje app.py lub README.md w katalogu repozytorium.')
    for name in ('rk_inbox.py', 'TEST_INBOX_REVIEW.py'):
        if not (root / name).is_file():
            raise RuntimeError(f'Brakuje pliku aktualizacji: {name}')

    app = app_path.read_text(encoding='utf-8')
    # Idempotentność: po pierwszym zapisie plików źródłowych, workflow nadal
    # może być uruchamiany ponownie bez wykonywania podwójnej migracji.
    if 'from rk_inbox import InboxMixin, ensure_inbox_schema' in app:
        required = (
            'VERSION = "0.3.1-dev1"', 'SCHEMA_VERSION = 323',
            'class Handler(InboxMixin, BaseHTTPRequestHandler):',
            'ensure_inbox_schema(con)',
            'if path == "/inbox": return self.inbox_page()',
            'if path == "/inbox/upload": return self.inbox_upload(fields, files)',
        )
        if not all(marker in app for marker in required):
            raise RuntimeError('Wykryto częściową/niespójną integrację. Nie nadpisuję źródeł.')
        print('Skrzynka wpływu jest już poprawnie podłączona do app.py; bez zmian.')
        return False
    if 'VERSION = "0.3.0-dev6"' not in app or 'SCHEMA_VERSION = 322' not in app:
        raise RuntimeError('Nieznana wersja app.py. Wymagane źródła z 17.09.2026 (0.3.0-dev6, schemat 322).')

    patches = (
        ('from rk_paths import resolve_runtime_paths, installed_data_dir',
         'from rk_inbox import InboxMixin, ensure_inbox_schema\nfrom rk_paths import resolve_runtime_paths, installed_data_dir',
         'import modułu'),
        ('VERSION = "0.3.0-dev6"', 'VERSION = "0.3.1-dev1"', 'numer wersji'),
        ('SCHEMA_VERSION = 322', 'SCHEMA_VERSION = 323', 'numer schematu'),
        ('class Handler(BaseHTTPRequestHandler):',
         'class Handler(InboxMixin, BaseHTTPRequestHandler):', 'Handler'),
        ('        ensure_smart_schema(con)\n',
         '        ensure_smart_schema(con)\n        ensure_inbox_schema(con)\n', 'migracja SQLite'),
        ('            ("/documents", "▤", "Dokumenty", "documents"),',
         '            ("/documents", "▤", "Dokumenty", "documents"),\n'
         '            ("/inbox", "✉", "Skrzynka wpływu", "inbox"),', 'nawigacja'),
        ('            if path == "/documents": return self.documents_page(qs)',
         '            if path == "/documents": return self.documents_page(qs)\n'
         '            if path == "/inbox": return self.inbox_page()\n'
         '            if re.fullmatch(r"/inbox/\\d+/file", path): return self.inbox_file(int(path.split("/")[2]))\n'
         '            if re.fullmatch(r"/inbox/\\d+", path): return self.inbox_review(int(path.split("/")[2]))',
         'obsługa GET'),
        ('            if path == "/task/create": return self.task_add_global(fields)',
         '            if path == "/task/create": return self.task_add_global(fields)\n'
         '            if path == "/inbox/upload": return self.inbox_upload(fields, files)\n'
         '            if re.fullmatch(r"/inbox/\\d+/approve", path): return self.inbox_approve(int(path.split("/")[2]), fields)\n'
         '            if re.fullmatch(r"/inbox/\\d+/discard", path): return self.inbox_discard(int(path.split("/")[2]), fields)',
         'obsługa POST'),
        ("<a class='btn primary' href='/quick-add'>+ Dokument</a> <a class='btn' href='/cases'>Wybierz sprawę</a>",
         "<a class='btn primary' href='/quick-add'>+ Dokument</a> <a class='btn' href='/inbox'>Skrzynka wpływu</a> <a class='btn' href='/cases'>Wybierz sprawę</a>",
         'skrót dokumentów'),
    )
    updated = app
    # Sprawdź WSZYSTKIE punkty przed pierwszym zapisem.
    for before, after, label in patches:
        updated = replace_once(updated, before, after, label)

    readme = readme_path.read_text(encoding='utf-8')
    if '## 0.3.1-dev1 — Skrzynka wpływu' not in readme:
        if readme.startswith('# RK KANCELARIA 0.3.0-dev4'):
            readme = readme.replace('# RK KANCELARIA 0.3.0-dev4', '# RK KANCELARIA 0.3.1-dev1', 1)
        readme += '''\n\n## 0.3.1-dev1 — Skrzynka wpływu\n- OCR lokalny i sugestie czynności na podstawie pisma (heurystyki, nie analiza prawna).\n- Obowiązkowy wybór sprawy i ręczna weryfikacja danych, terminów, monitów oraz zadań.\n- Zaznaczane i edytowalne działania zapisują się dopiero po wyraźnym zatwierdzeniu.\n- Kalendarz otrzymuje zatwierdzone czynności z datą; terminy nie są obliczane automatycznie.\n- Nie wysyła dokumentów do zewnętrznych usług.\n- Testy: TEST_INBOX_REVIEW.py.\n'''

    # Zapisy tylko po pozytywnej walidacji wszystkich patchy.
    app_path.write_text(updated, encoding='utf-8')
    if readme != readme_path.read_text(encoding='utf-8'):
        readme_path.write_text(readme, encoding='utf-8')
    print('Skrzynka wpływu 0.3.1-dev1 została włączona do źródeł.')
    return True


if __name__ == '__main__':
    try:
        update(Path(sys.argv[1] if len(sys.argv) > 1 else '.'))
    except Exception as exc:
        print(f'BŁĄD AKTUALIZACJI: {exc}', file=sys.stderr)
        raise SystemExit(1)
