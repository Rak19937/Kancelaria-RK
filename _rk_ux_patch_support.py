#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bezpieczna aktualizacja UX RK KANCELARIA 0.3.9-dev2.

Obsługuje oryginalne źródła 0.3.8-dev1 oraz poprawkę skrótu
w już zainstalowanym 0.3.9-dev1. Nie czyta ani nie modyfikuje Data.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path


# Git blob hashes plików w commicie d32bde00292adfc0ef118ae121b9a9af2f0e17a0.
BASE_BLOBS = {
    'app.py': '8c1b78319c8a8445ffeba0b87f142f223d901742',
    'rk_caseflow.py': '1872e6d24a8ed2d1570278b75b955688bc421b11',
    'assets/rk_app.js': '8707c6ade6a141d37914a0dcfc6f9a0e2362e4bc',
}
OLD_VERSION = 'VERSION = "0.3.8-dev1"'
PREVIOUS_VERSION = 'VERSION = "0.3.9-dev1"'
NEW_VERSION = 'VERSION = "0.3.9-dev2"'


def git_blob_sha(text: str) -> str:
    data = text.encode('utf-8')
    return hashlib.sha1(f'blob {len(data)}\0'.encode('ascii') + data).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: oczekiwano 1 kotwicy, znaleziono {count}; nic nie zapisano.')
    return text.replace(old, new, 1)


def apply_app(source: str) -> str:
    s = replace_once(source, OLD_VERSION, NEW_VERSION, 'wersja')
    s = replace_once(s,
        'from rk_document_hub import DocumentHubMixin, case_document_rows, ensure_document_hub_schema',
        'from rk_document_hub import DocumentHubMixin, case_document_rows, ensure_document_hub_schema\nfrom rk_ux import doc_workspace_panel',
        'import panelu')
    s = replace_once(s,
        '<link rel="stylesheet" href="/assets/rk_app.css?v={VERSION}">',
        '<link rel="stylesheet" href="/assets/rk_app.css?v={VERSION}">\n<link rel="stylesheet" href="/assets/rk_ux.css?v={VERSION}">', 'CSS')
    s = replace_once(s,
        '<script src="/assets/rk_app.js?v={VERSION}" defer></script>',
        '<script src="/assets/rk_app.js?v={VERSION}" defer></script>\n<script src="/assets/rk_ux.js?v={VERSION}" defer></script>', 'JS')
    s = replace_once(s, "if section=='SYSTEM':", "if section in ('SYSTEM','WIĘCEJ'):", 'zwijanie sekcji')
    s = replace_once(s,
        "nav_parts.append(f'<details class=\"nav-system\"{opened}><summary><span>USTAWIENIA I SYSTEM</span><span class=\"nav-system-arrow\">›</span></summary><div class=\"nav-system-links\">{links}</div></details>')",
        "nav_parts.append(f'<details class=\"nav-system\"{opened}><summary><span>{esc(section) if section==\"WIĘCEJ\" else \"USTAWIENIA I SYSTEM\"}</span><span class=\"nav-system-arrow\">›</span></summary><div class=\"nav-system-links\">{links}</div></details>')",
        'etykieta menu')
    s = replace_once(s,
        "with db() as con: body += linked_records_panel(con,'document',d)\n        self.send_html(layout('Podgląd dokumentu',extra_css+body,'documents'))",
        """with db() as con:
            readonly = case_read_only(con, d['case_id'])
            context_panel = doc_workspace_panel(con, d, readonly)
            linked = linked_records_panel(con,'document',d)
        # Bez zmian w danych dokumentów, oryginalnym podglądzie i relacjach.
        body = f'<div class="rk-ux-document-grid"><div class="rk-ux-main">{body}</div>{context_panel}</div>' + linked
        self.send_html(layout('Podgląd dokumentu',extra_css+body,'documents'))""",
        'podgląd dokumentu')
    s = replace_once(s,
        "toolbar += f\" <a class='btn' href='/document/{did}/links'>Powiązania spraw</a>\"",
        "toolbar += f\" <a class='btn' href='/document/{did}/links'>Powiązania spraw</a> <a class='btn' href='/quick-add?case_id={d['case_id']}'>+ Dodaj w tej sprawie</a>\"",
        'dodawanie kontekstowe')
    s = replace_once(s, '<span class=\'kbd\'>Ctrl+K</span> szukaj', '<span class=\'kbd\'>Ctrl+F</span> szukaj', 'podpowiedź skrótu')
    return s


def apply_caseflow(source: str) -> str:
    s = replace_once(source,
        "def quick_nav_html():\n    return (\"<form action='/navigate' method='get'",
        "def quick_nav_html():\n    return (\"<form action='/search' method='get'", 'jedna wyszukiwarka')
    s = replace_once(s, 'import sqlite3', 'import sqlite3\nfrom rk_ux import timeline_category', 'import kategorii')
    s = replace_once(s,
        """        parts=[]
        for x in reversed(items) if reverse else items:
            parts.append(f'<div class="card" style="padding:12px;margin:8px 0">'""",
        """        parts=[]
        for x in reversed(items) if reverse else items:
            cat=timeline_category(x['source'])
            parts.append(f'<div class="card rk-ux-timeline-item" data-ux-source="{cat}" style="padding:12px;margin:8px 0">'""",
        'kategorie chronologii')
    s = replace_once(s,
        """        return self.send_html(a.layout('Chronologia sprawy',head+''.join(parts) if parts else head+'<div class="card">Brak datowanych wpisów.</div>','cases'))""",
        """        controls=('<div class="rk-ux-timeline-controls" role="group" aria-label="Filtr zdarzeń">'
                 + ''.join(f'<button type="button" class="btn small" data-ux-category="{key}" aria-pressed="{str(key=="all").lower()}">{label}</button>'
                 for key,label in [('all','Wszystkie'),('documents','Dokumenty'),('tasks','Zadania i terminy'),('correspondence','Korespondencja'),('events','Pozostałe')])
                 + '</div>')
        timeline='<section data-ux-timeline>'+controls+(''.join(parts) if parts else '<div class="card">Brak datowanych wpisów.</div>')+'</section>'
        return self.send_html(a.layout('Chronologia sprawy',head+timeline,'cases'))""",
        'filtry chronologii')
    s = replace_once(s,
        """        body=(f'<div class="topbar"><h1>Zależności: {esc(task["title"])}</h1></div>'""",
        """        chain = '<div class="rk-ux-chain">' + ''.join(
            f'<div class="rk-ux-chain-step"><b>{"✓ Gotowe" if x["resolved"] else "⏳ Oczekuje"}</b>'
            f'<small>{esc(x["label"])}</small></div><span class="rk-ux-chain-arrow" aria-hidden="true">→</span>'
            for x in entries) + f'<div class="rk-ux-chain-step"><b>Zadanie</b><small>{esc(task["title"])}</small></div></div>'
        body=(f'<div class="topbar"><h1>Zależności: {esc(task["title"])}</h1></div>'""",
        'schemat zależności')
    s = replace_once(s,
        """              '<div class="card"><p class="small muted">Zadanie zależne nie jest automatycznie wykonywane. Potwierdzenie spełnienia warunków pozostaje po stronie użytkownika.</p>'""",
        """              '<div class="card"><p class="small muted">Zadanie zależne nie jest automatycznie wykonywane. Potwierdzenie spełnienia warunków pozostaje po stronie użytkownika.</p>'
              +chain+""",
        'widok łańcucha')
    return s


def remove_legacy_search_shortcut(source: str) -> str:
    # Skrót Ctrl+F obsługuje wyłącznie nowe okno wyszukiwania (capture phase).
    # Dawny handler Ctrl+K nie powinien działać równolegle.
    old = """    if (key === 'k') {
      e.preventDefault();
      const inp = document.querySelector('[data-global-search], #globalSearchInput');
      if (inp) { inp.focus(); inp.select(); }
      else location.href = '/search?focus=1';
    } else if (key === 'j') {"""
    return replace_once(source, old, "    if (key === 'j') {", 'stary handler Ctrl+K')


def modify_existing(source_app: str, old_js: str, old_ux_js: str):
    """Hotfix dla wcześniejszego 0.3.9-dev1, bez ponownego nakładania łatki UX."""
    if 'from rk_ux import doc_workspace_panel' not in source_app or '/assets/rk_ux.js?v={VERSION}' not in source_app:
        raise RuntimeError('To nie jest wcześniejsza paczka UX 0.3.9-dev1.')
    new_app = replace_once(source_app, PREVIOUS_VERSION, NEW_VERSION, 'wersja wcześniejszej paczki')
    new_app = replace_once(new_app, "<span class='kbd'>Ctrl+K</span> szukaj", "<span class='kbd'>Ctrl+F</span> szukaj", 'opis skrótu')
    new_js = remove_legacy_search_shortcut(old_js)
    new_ux = replace_once(old_ux_js, 'Ctrl+K — otwórz', 'Ctrl+F — otwórz', 'opis okna wyszukiwania')
    new_ux = replace_once(new_ux, "(e.ctrlKey||e.metaKey) && e.key.toLowerCase()==='k'", "(e.ctrlKey||e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase()==='f'", 'skrót wyszukiwania')
    new_ux = replace_once(new_ux,
        "e.preventDefault();e.stopImmediatePropagation();modal.hidden?open():close();return;",
        "e.preventDefault();e.stopImmediatePropagation();if(!e.repeat){modal.hidden?open():close();}return;",
        'powtarzanie skrótu')
    return new_app, new_js, new_ux


def write_transaction(repo: Path, changes: dict[Path, str], original_paths: tuple[Path, ...], backup_name: str):
    backup = repo / backup_name
    if backup.exists():
        raise RuntimeError(f'Istnieje {backup_name}. Nie nadpisano poprzedniej kopii.')
    # Najpierw zapisujemy backupy oryginalnych źródeł. Nie dotykamy katalogu Data.
    backup.mkdir()
    written = []
    try:
        for path in original_paths:
            rel = path.relative_to(repo)
            dest = backup / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        for path, content in changes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
            written.append(path)
    except Exception:
        for path in original_paths:
            old = backup / path.relative_to(repo)
            if old.exists():
                shutil.copy2(old, path)
        for path in written:
            if path not in original_paths and path.exists():
                path.unlink()
        raise
    print(f'Zmieniono {len(changes)} plików; kopia poprzednich źródeł: {backup_name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repo', type=Path)
    parser.add_argument('--dry-run', action='store_true', help='Sprawdź zgodność bez modyfikowania plików')
    args = parser.parse_args()
    repo, src = args.repo.resolve(), Path(__file__).resolve().parent
    paths = {name: repo / name for name in BASE_BLOBS}
    for name, target in paths.items():
        if not target.is_file():
            parser.error(f'Brak pliku źródłowego {name}. Wskaż katalog repozytorium, nie EXE.')
    current = {name: path.read_text(encoding='utf-8') for name, path in paths.items()}
    app = current['app.py']
    if NEW_VERSION in app:
        print('RK KANCELARIA 0.3.9-dev2 jest już obecna. Bez zmian.')
        return 0
    if OLD_VERSION in app:
        # Dokładny commit bazowy. Zapobiega częściowemu patchowaniu nowszego kodu.
        for name, expected in BASE_BLOBS.items():
            actual = git_blob_sha(current[name])
            if actual != expected:
                raise RuntimeError(f'{name}: źródło różni się od bazowego commita (Git blob {actual}). Bez zmian.')
        changes = {
            paths['app.py']: apply_app(app),
            paths['rk_caseflow.py']: apply_caseflow(current['rk_caseflow.py']),
            paths['assets/rk_app.js']: remove_legacy_search_shortcut(current['assets/rk_app.js']),
        }
        extra = ('rk_ux.py', 'assets/rk_ux.css', 'assets/rk_ux.js', 'TEST_UX_039.py')
        for rel in extra:
            target = repo / rel
            if target.exists():
                raise RuntimeError(f'{rel} już istnieje — nie nadpisano.')
            changes[target] = (src / rel).read_text(encoding='utf-8')
        originals = tuple(paths.values())
        backup = '.rk_ux_039_backup'
        label = 'Świeża aktualizacja z 0.3.8-dev1'
    elif PREVIOUS_VERSION in app:
        ux_js = repo / 'assets/rk_ux.js'
        if not ux_js.is_file():
            raise RuntimeError('Brak poprzedniej nakładki assets/rk_ux.js. Bez zmian.')
        fresh_app, fresh_legacy, fresh_ux = modify_existing(app, current['assets/rk_app.js'], ux_js.read_text(encoding='utf-8'))
        changes = {paths['app.py']: fresh_app, paths['assets/rk_app.js']: fresh_legacy, ux_js: fresh_ux}
        originals = tuple(changes)
        backup = '.rk_ux_039_shortcut_backup'
        label = 'Poprawka istniejącej instalacji 0.3.9-dev1'
    else:
        raise RuntimeError('Nieobsługiwana wersja programu; wymagane 0.3.8-dev1 lub 0.3.9-dev1. Bez zmian.')
    for target, content in changes.items():
        if target.suffix == '.py':
            compile(content, str(target), 'exec')
    print(f'{label}: sprawdzono wersję, kotwice, składnię Pythona. Schemat SQLite bez zmian.')
    if args.dry_run:
        print('DRY RUN: nic nie zapisano.')
        return 0
    write_transaction(repo, changes, originals, backup)
    print('Uruchom: py TEST_UX_039.py; py -m py_compile app.py rk_caseflow.py rk_ux.py; testy regresyjne repo.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'BŁĄD: {exc}', file=sys.stderr)
        sys.exit(2)
