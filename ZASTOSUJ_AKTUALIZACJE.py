#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RK KANCELARIA 0.3.10-dev1 — jedna aktualizacja UX + porządkowanie architektury.

Działa na niezmienionym 0.3.8-dev1 lub na zainstalowanym UX 0.3.9-dev1/dev2.
Zmienia wyłącznie kod źródłowy, nie modyfikuje katalogu Data i schematu SQLite.
Wszystkie sprawdzenia i kompilacje następują PRZED pierwszym zapisem.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from _rk_ux_patch_support import (
    BASE_BLOBS, git_blob_sha, apply_app, apply_caseflow,
    remove_legacy_search_shortcut, modify_existing, replace_once, write_transaction,
)
from rk_routes import GET_ROUTES, POST_ROUTES

SOURCE_VERSION = 'VERSION = "0.3.8-dev1"'
V1_VERSION = 'VERSION = "0.3.9-dev1"'
V2_VERSION = 'VERSION = "0.3.9-dev2"'
NEW_VERSION = 'VERSION = "0.3.10-dev1"'
MODULES = (
    'rk_ux.py', 'rk_navigation.py', 'rk_routes.py', 'rk_dashboard_data.py',
    'rk_search_data.py', 'rk_document_data.py',
    'assets/rk_ux.css', 'assets/rk_ux.js',
    'TEST_UX_039.py', 'TEST_ARCHITEKTURA_0310.py',
)


WORKFLOW_BLOB = '200d1f4fee127ddf2f9e673e0d66495fb2b8d856'


def patch_ci_workflow(source):
    """CI Windows uruchamia nowe testy przed budową Portable."""
    s = replace_once(source,
        '''          python TEST_INTEGRACJA_CASEFLOW.py
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
          python RK_KANCELARIA_DESKTOP.pyw --self-test''',
        '''          python TEST_INTEGRACJA_CASEFLOW.py
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
          python -m py_compile rk_ux.py rk_navigation.py rk_routes.py rk_dashboard_data.py rk_search_data.py rk_document_data.py
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
          python TEST_UX_039.py
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
          python TEST_ARCHITEKTURA_0310.py
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
          python RK_KANCELARIA_DESKTOP.pyw --self-test''',
        'CI: nowe testy')
    return s

REGRESSION_TEST_BLOBS = {
    'TEST_STABILIZACJA.py': '33b4179154a2e91035ae486b45e54a72e3a71c8d',
    'TEST_AKTUALIZACJA_ZBIORCZA.py': '3552a65c82bd616bf0148fbc344e518c40926a15',
    'TEST_UI_PERFORMANCE_DEV4.py': 'be55f78afbfbd4746e65ef6dc6d816182b993e72',
}


def patch_regression_test(name, source):
    """Zmienia oczekiwania testów po przeniesieniu menu i tras z app.py.

    Testy nadal sprawdzają te same funkcje i bezpieczeństwo, ale kontrolują
    nowe źródła prawdy zamiast szukać nieistniejących już linii w app.py.
    """
    s = source
    if name == 'TEST_UI_PERFORMANCE_DEV4.py':
        s = replace_once(s,
            '    source = (ROOT / "app.py").read_text(encoding="utf-8")\n    css =',
            '    source = (ROOT / "app.py").read_text(encoding="utf-8")\n'
            '    nav_source = (ROOT / "rk_navigation.py").read_text(encoding="utf-8")\n    css =',
            'test UI: źródło nawigacji')
        s = replace_once(s,
            '''    assert '("/drafts", "✎", "Pisma", "drafts")' in source
    assert '("/draft/templates", "▣", "Szablony pism"' not in source''',
            '''    assert "('/drafts', '✎', 'Pisma', 'drafts')" in nav_source
    assert "('/draft/templates', '▣', 'Szablony pism'" not in nav_source''',
            'test UI: sprawdzenie menu')
    elif name == 'TEST_STABILIZACJA.py':
        s = replace_once(s,
            'from pathlib import Path\n',
            'from pathlib import Path\nfrom rk_navigation import NAV_SECTIONS\nfrom rk_routes import GET_ROUTES\n',
            'test stabilizacji: importy')
        for marker in (
            '''            '("/inbox", "✉", "Skrzynka wpływu", "inbox")',\n''',
            '''            'if path == "/inbox": return self.inbox_page()',\n''',
        ):
            s = replace_once(s, marker, '', 'test stabilizacji: przeniesiony marker')
        s = replace_once(s,
            '                self.assertIn(marker, self.src)\n\n    def test_about_and_license(self):',
            '''                self.assertIn(marker, self.src)
        items = [item for section,links in NAV_SECTIONS for item in links]
        self.assertIn(('/inbox','✉','Skrzynka wpływu','inbox'), items)
        self.assertEqual(GET_ROUTES['/inbox'], ('inbox_page',''))

    def test_about_and_license(self):''',
            'test stabilizacji: istniejąca nawigacja')
        s = replace_once(s,
            '''    def test_about_and_license(self):
        for marker in ('def about_page(self):',
                       '("/about", "ⓘ", "O programie", "about")',
                       'if path == "/about": return self.about_page()'):
            self.assertIn(marker, self.src)
        self.assertTrue((ROOT / 'LICENSE.txt').is_file())''',
            '''    def test_about_and_license(self):
        self.assertIn('def about_page(self):', self.src)
        items = [item for section,links in NAV_SECTIONS for item in links]
        self.assertIn(('/about','ⓘ','O programie','about'), items)
        self.assertEqual(GET_ROUTES['/about'], ('about_page',''))
        self.assertTrue((ROOT / 'LICENSE.txt').is_file())''',
            'test stabilizacji: strona o programie')
    elif name == 'TEST_AKTUALIZACJA_ZBIORCZA.py':
        s = replace_once(s,
            'import unittest\n',
            'import unittest\nfrom rk_routes import GET_ROUTES\n',
            'test zbiorczy: importy tras')
        for marker in (
            '''            'if path == "/powers": return self.powers_page(qs)',\n''',
            '''            'if path == "/inbox": return self.inbox_page()',\n''',
            '''            'if path == "/workflow": return self.action_center_page()',\n''',
        ):
            s = replace_once(s,marker,'','test zbiorczy: przeniesiona trasa')
        s = replace_once(s,
            '''                self.assertIn(marker,self.source)

    def test_neutral_placeholders(self):''',
            '''                self.assertIn(marker,self.source)
        self.assertEqual(GET_ROUTES['/powers'], ('powers_page', 'q'))
        self.assertEqual(GET_ROUTES['/inbox'], ('inbox_page', ''))
        self.assertEqual(GET_ROUTES['/workflow'], ('action_center_page', ''))

    def test_neutral_placeholders(self):''',
            'test zbiorczy: kontrakty tras')
    else:
        raise RuntimeError('Nieobsługiwany test: '+name)
    compile(s,name,'exec')
    return s


def replace_between(s, beginning, ending, replacement, label, *, start=0, stop=None):
    """Wymaga jednej niepustej kotwicy w zadanym obszarze."""
    if stop is None:
        stop = len(s)
    area = s[start:stop]
    if area.count(beginning) != 1 or area.count(ending) != 1:
        raise RuntimeError(f'{label}: zmienione kotwice w bazowym kodzie; nic nie zapisano.')
    i = s.index(beginning, start, stop)
    j = s.index(ending, i + len(beginning), stop)
    if not i < j:
        raise RuntimeError(label + ': błędna kolejność kotwic.')
    return s[:i] + replacement + s[j:]


def _call_signature(arg_type):
    return {
        '': '', 'q': 'qs', 'f': 'fields', 'ff': 'fields, files',
        'q_closed_false': 'qs, closed_only=False',
        'q_closed_true': 'qs, closed_only=True',
    }[arg_type]


def remove_static_routes(block, routes, label):
    """Przenosi do rejestru tylko trasy o identycznych nazwach i argumentach."""
    for path, (method, arg_type) in routes.items():
        matched = list(re.finditer(
            r'^ {12}if path == (?P<quote>[\'\"])(?P<path>[^\'\"]+)(?P=quote): '
            r'return self\.(?P<method>[a-zA-Z_][a-zA-Z0-9_]*)\((?P<args>.*)\)\s*$',
            block, re.MULTILINE))
        exact = [m for m in matched if m.group('path') == path]
        if len(exact) != 1:
            raise RuntimeError(f'{label}: oczekiwano 1 trasy {path}, znaleziono {len(exact)}.')
        match = exact[0]
        if match.group('method') != method or match.group('args') != _call_signature(arg_type):
            raise RuntimeError(f'{label}: niezgodna sygnatura trasy {path}: '
                               f'{match.group("method")}({match.group("args")}).')
        block = block[:match.start()] + block[match.end():]
    return block


def refactor_app(s):
    s = replace_once(s, V2_VERSION, NEW_VERSION, 'nowa wersja')
    s = replace_once(s, 'from rk_ux import doc_workspace_panel',
        'from rk_ux import doc_workspace_panel\n'
        'from rk_navigation import render_sidebar_navigation\n'
        'from rk_dashboard_data import dashboard_snapshot\n'
        'from rk_routes import dispatch_static_get, dispatch_static_post', 'import warstw')

    # 1. Odciążenie layout() z definicji menu i budowania HTML nawigacji.
    lay = s.index('def layout(title: str, body: str, active: str = "") -> str:')
    s = replace_between(
        s,
        '    nav_sections = [\n',
        "    if user:\n        role = \"Administrator\"",
        '    nav_html = render_sidebar_navigation(active, user, esc)\n',
        'nawigacja', start=lay,
        stop=s.index('def writing_tabs(', lay)
    )

    # 2. Odczyty danych pulpitu w jednym serwisie, szablon/HTML bez zmian.
    dash = s.index('    def dashboard(self):')
    s = replace_between(
        s,
        '        with db() as con:\n            status_counts = ',
        "        def case_mini(r, extra=''):",
        '''        with db() as con:
            snapshot = dashboard_snapshot(con, today, week_end, uid, load_external_signature_map, STATUS_LABELS)
        counts = snapshot['counts']
        due_today = snapshot['due_today']
        overdue_count = snapshot['overdue_count']
        next7_count = snapshot['next7_count']
        high_count = snapshot['high_count']
        dated = snapshot['dated']
        undated = snapshot['undated']
        upcoming = snapshot['upcoming']
        recent_events = snapshot['recent_events']
        pinned = snapshot['pinned']
        recent_cases = snapshot['recent_cases']
        sig_map = snapshot['sig_map']
''',
        'dane pulpitu', start=dash,
        stop=s.index('    def case_next_action_complete(', dash)
    )

    # 3. Wydzielone, jawne rejestry prostych tras.
    start = s.index('    def do_GET(self):')
    end = s.index('    def do_POST(self):', start)
    get_block = s[start:end]
    get_block = remove_static_routes(get_block, GET_ROUTES, 'GET')
    get_block = replace_once(
        get_block,
        '        try:\n            if path == \'/onboarding\': return self.onboarding_page()',
        "        try:\n            if dispatch_static_get(self, path, qs): return\n            if path == '/onboarding': return self.onboarding_page()",
        'GET dispatch po require_auth'
    )
    s = s[:start] + get_block + s[end:]
    start = s.index('    def do_POST(self):')
    end = s.index('    def ', start + len('    def do_POST(self):'))
    post_block = s[start:end]
    post_block = remove_static_routes(post_block, POST_ROUTES, 'POST')
    post_block = replace_once(
        post_block,
        '            if re.fullmatch(r"/admin/user/\\d+/update", path):',
        '            if dispatch_static_post(self, path, fields, files): return\n'
        '            if re.fullmatch(r"/admin/user/\\d+/update", path):',
        'POST dispatch po kontroli dostępu'
    )
    s = s[:start] + post_block + s[end:]
    return s


def refactor_caseflow(s):
    s = replace_once(s, 'from rk_ux import timeline_category',
                     'from rk_ux import timeline_category\nfrom rk_search_data import find_navigation_matches',
                     'import wyszukiwania')
    # Dotychczasowa trasa /navigate nadal działa. Tylko SQL przechodzi do serwisu.
    p = s.index('    def caseflow_navigate(self,qs):')
    e = s.index('    def caseflow_task_summary(self,tid):',p)
    s = replace_between(s,
        "        like='%'+q+'%'\n        with a.db() as con:",
        "        rows=['<h2>Sprawy</h2>']",
        "        with a.db() as con:\n            cases,tasks,docs=find_navigation_matches(con,q)\n",
        'zapytania nawigacji', start=p, stop=e)
    return s


def refactor_existing_ux(s):
    """Wariant dla już zainstalowanego UX; bez nadpisywania innych zmian."""
    s = replace_once(s, 'from html import escape\n',
                     'from html import escape\nfrom rk_document_data import list_open_case_tasks\n',
                     'import danych panelu')
    s = replace_between(s,
        "    tasks = con.execute('''SELECT id,title,due_date,status,priority FROM tasks",
        '    heading = escape(',
        '    tasks = list_open_case_tasks(con, cid)\n',
        'odczyty panelu dokumentu')
    return s


def build_changes(repo: Path, package: Path):
    paths = {name: repo / name for name in BASE_BLOBS}
    for name, path in paths.items():
        if not path.is_file():
            raise RuntimeError(f'Brak {name}: wskaż katalog źródeł repozytorium, nie portable EXE.')
    current = {name: path.read_text(encoding='utf-8') for name,path in paths.items()}
    app = current['app.py']; caseflow=current['rk_caseflow.py']; old_js=current['assets/rk_app.js']
    if NEW_VERSION in app:
        return None, (), 'Wersja 0.3.10-dev1 już istnieje — bez zmian.'
    if SOURCE_VERSION in app:
        for name,sha in BASE_BLOBS.items():
            if git_blob_sha(current[name]) != sha:
                raise RuntimeError(f'{name}: zmieniony względem commita bazowego; nie nadpisano.')
        app = apply_app(app)
        caseflow = apply_caseflow(caseflow)
        old_js = remove_legacy_search_shortcut(old_js)
        ux_js = (package / 'assets/rk_ux.js').read_text(encoding='utf-8')
        extra_ux = ['rk_ux.py','assets/rk_ux.css','assets/rk_ux.js','TEST_UX_039.py']
        for rel in extra_ux:
            if (repo / rel).exists():
                raise RuntimeError(f'{rel} istnieje w czystym repo; przerwano bez zmian.')
        ux = 'base'
    elif V1_VERSION in app:
        ux_js_path = repo / 'assets/rk_ux.js'
        if not ux_js_path.is_file():
            raise RuntimeError('Brak assets/rk_ux.js w poprzedniej aktualizacji.')
        app, old_js, ux_js = modify_existing(app, old_js, ux_js_path.read_text(encoding='utf-8'))
        ux = 'installed'
    elif V2_VERSION in app:
        if 'from rk_ux import doc_workspace_panel' not in app or '/assets/rk_ux.js?v={VERSION}' not in app:
            raise RuntimeError('Wersja 0.3.9-dev2 nie ma oczekiwanej struktury UX.')
        if "key === 'k'" in old_js or 'Ctrl+K' in (repo / 'assets/rk_ux.js').read_text(encoding='utf-8'):
            raise RuntimeError('Niespójne skróty starego UX. Bez zmian.')
        ux_js = (repo / 'assets/rk_ux.js').read_text(encoding='utf-8')
        ux = 'installed'
    else:
        raise RuntimeError('Wymagane źródła 0.3.8-dev1 albo UX 0.3.9-dev1/dev2. Bez zmian.')

    if ux == 'base':
        ux_source = (Path(package) / 'rk_ux.py').read_text(encoding='utf-8')
    else:
        old_ux_path = repo / 'rk_ux.py'
        if not old_ux_path.is_file():
            raise RuntimeError('Brak rk_ux.py poprzedniej aktualizacji.')
        ux_source = refactor_existing_ux(old_ux_path.read_text(encoding='utf-8'))

    app = refactor_app(app)
    caseflow = refactor_caseflow(caseflow)
    changes = {
        paths['app.py']: app,
        paths['rk_caseflow.py']: caseflow,
        paths['assets/rk_app.js']: old_js,
        repo / 'rk_ux.py': ux_source,
        repo / 'assets/rk_ux.js': ux_js,
    }
    # Nowe architektoniczne moduły; instalacja nie zastępuje przypadkowych plików użytkownika.
    for rel in ('rk_navigation.py','rk_routes.py','rk_dashboard_data.py',
                'rk_search_data.py','rk_document_data.py','TEST_ARCHITEKTURA_0310.py'):
        if (repo / rel).exists():
            raise RuntimeError(f'Plik {rel} już istnieje. Bez zmian.')
        changes[repo / rel] = (package / rel).read_text(encoding='utf-8')
    if ux == 'base':
        for rel in ('assets/rk_ux.css','TEST_UX_039.py'):
            changes[repo / rel] = (package / rel).read_text(encoding='utf-8')
    # Aktualizacja historycznych testów sprawdzających lokalizację tras w app.py.
    for rel, sha in REGRESSION_TEST_BLOBS.items():
        target = repo / rel
        if not target.is_file():
            raise RuntimeError(f'Brak testu regresyjnego {rel}; bez zmian.')
        text = target.read_text(encoding='utf-8')
        if git_blob_sha(text) != sha:
            raise RuntimeError(f'Test {rel} został zmieniony od czasu przeglądu; bez zmian.')
        changes[target] = patch_regression_test(rel,text)
    workflow = repo / '.github/workflows/main.yml'
    if not workflow.is_file() or git_blob_sha(workflow.read_text(encoding='utf-8')) != WORKFLOW_BLOB:
        raise RuntimeError('Workflow CI jest inny niż w zatwierdzonym repozytorium; bez zmian.')
    changes[workflow] = patch_ci_workflow(workflow.read_text(encoding='utf-8'))
    originals = tuple(path for path in changes if path.is_file())
    for path, content in changes.items():
        if path.suffix == '.py':
            compile(content, str(path), 'exec')
    return changes, originals, f'Zebrano {len(changes)} zmian; źródło: {ux}.'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repo', type=Path, help='katalog rozpakowanych źródeł repozytorium')
    parser.add_argument('--dry-run', action='store_true', help='sprawdza bez zapisu')
    args=parser.parse_args(argv)
    repo=args.repo.resolve(); package=Path(__file__).resolve().parent
    changes, originals, message = build_changes(repo,package)
    print(message)
    if changes is None:
        return 0
    if args.dry_run:
        print('DRY RUN OK — nic nie zapisano; Data pozostaje bez zmian.')
        return 0
    write_transaction(repo, changes, originals, '.rk_backup_before_0310')
    print('Gotowe. Uruchom TEST_ARCHITEKTURA_0310.py, TEST_UX_039.py i komplet testów repo oraz build Windows Portable.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print('BŁĄD:',exc,file=sys.stderr)
        sys.exit(2)
