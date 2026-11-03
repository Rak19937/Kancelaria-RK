# -*- coding: utf-8 -*-
"""Nakłada moduł Skrzynka wpływu na repo RK KANCELARIA z 17.09.2026.

Użycie: python ZASTOSUJ_POPRAWKE.py /ścieżka/do/Kancelaria-RK
Skrypt nie dotyka bazy danych ani plików klientów. Zachowuje kopie zmienianych
plików źródłowych w katalogu .rk_inbox_patch_backups (nie commituj go).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def replace_one(data: str, needle: str, replacement: str, key: str) -> str:
    if data.count(needle) != 1:
        raise RuntimeError(f'Nie można bezpiecznie nałożyć zmiany: {key} (liczba wystąpień: {data.count(needle)}).')
    return data.replace(needle, replacement, 1)


def patch(repo: Path) -> None:
    repo = repo.expanduser().resolve()
    app_path = repo / 'app.py'
    workflow_path = repo / '.github/workflows/main.yml'
    readme_path = repo / 'README.md'
    gitignore_path = repo / '.gitignore'
    if not app_path.is_file() or not workflow_path.is_file() or not readme_path.is_file():
        raise RuntimeError('Nie wskazano katalogu repozytorium RK KANCELARIA z plikami app.py, README.md i .github/workflows/main.yml.')
    app = app_path.read_text(encoding='utf-8')
    if 'from rk_inbox import InboxMixin, ensure_inbox_schema' in app:
        raise RuntimeError('Moduł Skrzynka wpływu jest już podłączony. Nie nakładaj poprawki ponownie.')
    if 'VERSION = "0.3.0-dev6"' not in app or 'SCHEMA_VERSION = 322' not in app:
        raise RuntimeError('Nieznany stan repozytorium. Poprawka dotyczy kodu z 17.09.2026 (0.3.0-dev6 / schemat 322).')

    app = replace_one(app,
        'from rk_paths import resolve_runtime_paths, installed_data_dir',
        'from rk_inbox import InboxMixin, ensure_inbox_schema\nfrom rk_paths import resolve_runtime_paths, installed_data_dir', 'import')
    app = replace_one(app, 'VERSION = "0.3.0-dev6"', 'VERSION = "0.3.1-dev1"', 'wersja')
    app = replace_one(app, 'SCHEMA_VERSION = 322', 'SCHEMA_VERSION = 323', 'schemat')
    app = replace_one(app,
        'class Handler(BaseHTTPRequestHandler):',
        'class Handler(InboxMixin, BaseHTTPRequestHandler):', 'klasa handler')
    app = replace_one(app,
        '        ensure_smart_schema(con)\n',
        '        ensure_smart_schema(con)\n        ensure_inbox_schema(con)\n', 'migracja DB')
    app = replace_one(app,
        '            ("/documents", "▤", "Dokumenty", "documents"),',
        '            ("/documents", "▤", "Dokumenty", "documents"),\n            ("/inbox", "✉", "Skrzynka wpływu", "inbox"),', 'nawigacja')
    app = replace_one(app,
        '            if path == "/documents": return self.documents_page(qs)',
        '''            if path == "/documents": return self.documents_page(qs)
            if path == "/inbox": return self.inbox_page()
            if re.fullmatch(r"/inbox/\\d+/file", path): return self.inbox_file(int(path.split("/")[2]))
            if re.fullmatch(r"/inbox/\\d+", path): return self.inbox_review(int(path.split("/")[2]))''', 'GET')
    app = replace_one(app,
        '            if path == "/task/create": return self.task_add_global(fields)',
        '''            if path == "/task/create": return self.task_add_global(fields)
            if path == "/inbox/upload": return self.inbox_upload(fields, files)
            if re.fullmatch(r"/inbox/\\d+/approve", path): return self.inbox_approve(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/inbox/\\d+/discard", path): return self.inbox_discard(int(path.split("/")[2]), fields)''', 'POST')
    app = replace_one(app,
        "<a class='btn primary' href='/quick-add'>+ Dokument</a> <a class='btn' href='/cases'>Wybierz sprawę</a>",
        "<a class='btn primary' href='/quick-add'>+ Dokument</a> <a class='btn' href='/inbox'>Skrzynka wpływu</a> <a class='btn' href='/cases'>Wybierz sprawę</a>", 'przycisk dokumentów')

    workflow = workflow_path.read_text(encoding='utf-8')
    workflow = replace_one(workflow,
        '          python TEST_CLOSED_CASE_ACTIONS_DEV6.py',
        '          python TEST_CLOSED_CASE_ACTIONS_DEV6.py\n          python TEST_INBOX_REVIEW.py', 'testy CI')
    workflow = replace_one(workflow,
        'python -m py_compile app.py desktop.py rk_paths.py rk_sync.py RK_KANCELARIA_DESKTOP.pyw',
        'python -m py_compile app.py rk_inbox.py desktop.py rk_paths.py rk_sync.py RK_KANCELARIA_DESKTOP.pyw', 'kompilacja CI')

    readme = readme_path.read_text(encoding='utf-8')
    readme = readme.replace('# RK KANCELARIA 0.3.0-dev4', '# RK KANCELARIA 0.3.1-dev1', 1)
    readme += '''\n\n## 0.3.1-dev1 — Skrzynka wpływu (weryfikacja człowieka)
- Dodawanie dokumentów PDF, DOCX, zdjęć i TXT/RTF do lokalnej kolejki przed przypisaniem do sprawy.
- Analiza OCR oraz wyświetlenie oryginału i fragmentów źródłowych.
- Sugestie: zadania, monity i jawne terminy **bez automatycznego wyliczania daty**.
- Każde działanie można zmienić, odznaczyć lub dodać dwie czynności ręcznie.
- Zapis dokumentu, wybranych działań i audytu następuje dopiero po ręcznym zatwierdzeniu.
- Ochrona przed duplikatami i ponownym zatwierdzeniem tego samego wpływu.
- Dane pozostają lokalnie w katalogu Data/dokumenty, bez usług AI/chmury.
- Uwaga: reguły tekstowe są pomocnicze; nie zastępują lektury pisma i oceny terminu.
Testy: `TEST_INBOX_REVIEW.py` (również GitHub Actions).\n'''

    # Najpierw weryfikacja wszystkich punktów; dopiero potem jakiekolwiek zapisy.
    for filename in ('rk_inbox.py', 'TEST_INBOX_REVIEW.py'):
        if not (HERE / filename).is_file():
            raise RuntimeError(f'Nie znaleziono pliku poprawki: {filename}')
        if (repo / filename).exists():
            raise RuntimeError(f'Plik {filename} już istnieje: sprawdź go ręcznie przed nadpisaniem.')
    output = {app_path: app, workflow_path: workflow, readme_path: readme}
    if gitignore_path.is_file():
        current_ignore = gitignore_path.read_text(encoding='utf-8')
        if '.rk_inbox_patch_backups/' not in current_ignore:
            output[gitignore_path] = current_ignore.rstrip() + '\n.rk_inbox_patch_backups/\n'
    backups = repo / '.rk_inbox_patch_backups'
    backups.mkdir(exist_ok=True)
    for path in output:
        dest = backups / path.relative_to(repo)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copy2(path, dest)
    for path, newcontent in output.items():
        path.write_text(newcontent, encoding='utf-8')
    for filename in ('rk_inbox.py', 'TEST_INBOX_REVIEW.py'):
        shutil.copy2(HERE / filename, repo / filename)

    print('Nałożono poprawkę Skrzynka wpływu 0.3.1-dev1.')
    print('Uruchom: python TEST_INBOX_REVIEW.py')
    print('Następnie zbuduj wersję Portable przez GitHub Actions.')
    print('Kopie źródeł: .rk_inbox_patch_backups (NIE commituj tego katalogu).')


if __name__ == '__main__':
    try:
        patch(Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd())
    except Exception as e:
        print(f'BŁĄD: {e}', file=sys.stderr)
        sys.exit(1)
