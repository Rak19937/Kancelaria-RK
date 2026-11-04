# -*- coding: utf-8 -*-
"""RK KANCELARIA 0.3.2-dev1 — jednoetapowy bezpieczny integrator źródeł.

Kolejność: istniejąca skrzynka wpływu -> stabilizacja/licencja ->
neutralne podpowiedzi -> rejestr pełnomocnictw i wiele powiązań dokumentów.

Źródła są najpierw modyfikowane w tymczasowym katalogu; pliki baz danych
użytkownika, dokumenty i katalog Data nie są otwierane przez integrator.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile

VERSION = '0.3.2-dev1'
MARKER = 'from rk_document_hub import DocumentHubMixin, case_document_rows, ensure_document_hub_schema'


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: oczekiwano jednego wystąpienia, znaleziono {count}; niczego nie zapisano.')
    return source.replace(old, new, 1)


def apply_hub(source: str) -> str:
    if MARKER in source:
        if all(key in source for key in (
            'class Handler(DocumentHubMixin, InboxMixin, BaseHTTPRequestHandler):',
            'ensure_document_hub_schema(con)',
            'if path == "/powers": return self.powers_page(qs)',
            "docs=case_document_rows(con,cid)",
            'self.document_link_add(',
            'self.document_link_remove(',
            'self.power_save(',
            'self.power_remove(',
        )):
            return source
        raise RuntimeError('Wykryto niepełną aktualizację katalogu; odmawiam nadpisania.')

    if 'VERSION = "0.3.1-dev1"' not in source or 'SCHEMA_VERSION = 323' not in source:
        raise RuntimeError('Oczekiwano kodu po integracji skrzynki wpływu 0.3.1-dev1.')

    changes = [
        ('from rk_inbox import InboxMixin, ensure_inbox_schema',
         MARKER + '\nfrom rk_inbox import InboxMixin, ensure_inbox_schema', 'import katalogu'),
        ('VERSION = "0.3.1-dev1"', f'VERSION = "{VERSION}"', 'wersja programu'),
        ('SCHEMA_VERSION = 323', 'SCHEMA_VERSION = 324', 'numer schematu'),
        ('DOC_TYPES = ["Pismo procesowe", "Wniosek", "Apelacja", "Zażalenie", "Odpowiedź", "Postanowienie", "Wyrok", "Uzasadnienie", "Opinia biegłego", "Dowód", "Korespondencja", "Załącznik", "Inne"]',
         'DOC_TYPES = ["Pismo procesowe", "Wniosek", "Apelacja", "Zażalenie", "Odpowiedź", "Postanowienie", "Wyrok", "Uzasadnienie", "Opinia biegłego", "Dowód", "Korespondencja", "Pełnomocnictwo", "Załącznik", "Inne"]',
         'rodzaj dokumentu Pełnomocnictwo'),
        ('class Handler(InboxMixin, BaseHTTPRequestHandler):',
         'class Handler(DocumentHubMixin, InboxMixin, BaseHTTPRequestHandler):', 'Handler'),
        ('        ensure_inbox_schema(con)\n',
         '        ensure_inbox_schema(con)\n        ensure_document_hub_schema(con)\n', 'tabele powiązań'),
        ('            ("/documents", "▤", "Dokumenty", "documents"),',
         '            ("/documents", "▤", "Dokumenty", "documents"),\n'
         '            ("/powers", "§", "Pełnomocnictwa", "powers"),', 'menu pełnomocnictw'),
        ('            if path == "/documents": return self.documents_page(qs)',
         '            if path == "/documents": return self.documents_page(qs)\n'
         '            if path == "/powers": return self.powers_page(qs)\n'
         '            if re.fullmatch(r"/powers/\\d+/edit",path): return self.power_edit_page(int(path.split("/")[2]))\n'
         '            if re.fullmatch(r"/document/\\d+/links",path): return self.document_links_page(int(path.split("/")[2]))',
         'trasy GET'),
        ('            if path == "/task/create": return self.task_add_global(fields)',
         '            if path == "/task/create": return self.task_add_global(fields)\n'
         '            if path == "/powers/save": return self.power_save(fields)\n'
         '            if path == "/powers/remove": return self.power_remove(fields)\n'
         '            if re.fullmatch(r"/document/\\d+/link",path): return self.document_link_add(int(path.split("/")[2]),fields)\n'
         '            if re.fullmatch(r"/document/\\d+/unlink",path): return self.document_link_remove(int(path.split("/")[2]),fields)',
         'trasy POST'),
        ('            docs=con.execute("""SELECT * FROM documents WHERE case_id=?\n'
         '                                ORDER BY COALESCE(NULLIF(delivered_date,\'\'),NULLIF(received_date,\'\'),NULLIF(doc_date,\'\'),created_at) DESC,id DESC""",(cid,)).fetchall()',
         '            docs=case_document_rows(con,cid)', 'powiązane dokumenty w karcie sprawy'),
        ('                rows.append(f"<tr><td>{fmt_date(d[\'doc_date\'])}<div class=\'small muted\'>wpływ {fmt_date(d[\'received_date\'])} · doręczenie {fmt_date(d[\'delivered_date\'])}</div></td><td>{disclosure}</td><td>{state}</td><td><a class=\'btn small\' href=\'/document/{d[\'id\']}/edit\'>Edytuj</a></td></tr>")',
         '                doc_actions = (f"<a class=\'btn small\' href=\'/document/{d[\'id\']}/edit\'>Edytuj</a>"\n'
         '                               if d[\'case_id\'] == cid else "<span class=\'small muted\'>Dokument współdzielony</span>")\n'
         '                doc_actions += f" <a class=\'btn small\' href=\'/document/{d[\'id\']}/links\'>Powiązania</a>"\n'
         '                rows.append(f"<tr><td>{fmt_date(d[\'doc_date\'])}<div class=\'small muted\'>wpływ {fmt_date(d[\'received_date\'])} · doręczenie {fmt_date(d[\'delivered_date\'])}</div></td><td>{disclosure}</td><td>{state}</td><td>{doc_actions}</td></tr>")',
         'akcje dokumentów w karcie sprawy'),
        ('<div class=\'muted\'>Dokumenty i załączniki wyłącznie tej sprawy.</div>',
         '<div class=\'muted\'>Dokumenty sprawy i powiązane dokumenty bez kopiowania plików.</div>',
         'opis dokumentów'),
        ("            doc_sig_map=load_external_signature_map(con,[r['case_id'] for r in rows])",
         '            doc_sig_map=load_external_signature_map(con,[r[\'case_id\'] for r in rows])\n            shared_doc_rows=con.execute("""SELECT d.id,d.title,c.id case_id,c.title case_title,c.signature\n                    FROM document_case_links l JOIN documents d ON d.id=l.document_id\n                    JOIN cases c ON c.id=l.case_id\n                    WHERE (?=\'\' OR d.title LIKE ? OR d.original_name LIKE ? OR c.title LIKE ? OR c.signature LIKE ?)\n                    ORDER BY l.created_at DESC LIMIT 150""",(q,f\'%{q}%\',f\'%{q}%\',f\'%{q}%\',f\'%{q}%\')).fetchall()', 'wyszukiwanie współdzielonych dokumentów'),
        ('        folders_html=\'\'.join(folders) or \'<div class="empty">Brak dokumentów.</div>\'',
         '        folders_html=\'\'.join(folders) or \'<div class="empty">Brak dokumentów.</div>\'\n        shared_rows=\'\'.join(f"<tr><td><a href=\'/document/{r[\'id\']}/open\'>{esc(r[\'title\'])}</a></td>"\n                            f"<td><a href=\'/case/{r[\'case_id\']}?tab=documents\'>{esc(r[\'signature\'] or r[\'case_title\'])}</a></td>"\n                            f"<td><a class=\'btn small\' href=\'/document/{r[\'id\']}/links\'>Powiązania</a></td></tr>"\n                            for r in shared_doc_rows)\n        shared_panel=("<div class=\'card\'><h2>Dokumenty powiązane z dodatkowymi sprawami</h2>"\n                      "<table><tr><th>Dokument</th><th>Sprawa</th><th>Akcje</th></tr>"+shared_rows+"</table></div>") if shared_rows else \'\'', 'współdzielone dokumenty w katalogu'),
        ('<div class=\'doc-folders\'>{folders_html}</div>{script}"""',
         '<div class=\'doc-folders\'>{folders_html}</div>{shared_panel}{script}"""', 'wyświetlenie powiązań w katalogu'),
        ('        max_chars=160_000; bodytxt,status=self._preview_text_now(d,p,ext)',
         '        toolbar += f" <a class=\'btn\' href=\'/document/{did}/links\'>Powiązania spraw</a>"\n'
         '        max_chars=160_000; bodytxt,status=self._preview_text_now(d,p,ext)',
         'przycisk powiązań w dokumencie'),
        ('    def document_delete(self,did,f):\n        cid=int(f.get(\'case_id\',\'0\') or 0); a=self.current_author(f)',
         '    def document_delete(self,did,f):\n'
         '        with db() as con:\n'
         '            shared=con.execute("SELECT 1 FROM document_case_links WHERE document_id=? LIMIT 1",(did,)).fetchone()\n'
         '            if shared:\n'
         '                body=f"<div class=\'card\'><h1>Dokument jest współdzielony</h1>" + \\\n'
         '                    f"<p>Najpierw odłącz go od dodatkowych spraw. Oryginalny plik nie został usunięty.</p>" + \\\n'
         '                    f"<a class=\'btn primary\' href=\'/document/{did}/links\'>Powiązania dokumentu</a></div>"\n'
         '                return self.send_html(layout("Dokument współdzielony",body,"documents"),409)\n'
         '        cid=int(f.get(\'case_id\',\'0\') or 0); a=self.current_author(f)',
         'blokada usunięcia współdzielonego dokumentu'),
        ('    def case_delete(self,cid,f):\n        with db() as con:',
         '    def case_delete(self,cid,f):\n'
         '        with db() as con:\n'
         '            shared=con.execute("SELECT 1 FROM documents d JOIN document_case_links l ON l.document_id=d.id WHERE d.case_id=? LIMIT 1",(cid,)).fetchone()\n'
         '            if shared:\n'
         '                return self.send_html(layout("Sprawa z dokumentami współdzielonymi",\n'
         '                    "<div class=\'card\'><h1>Nie można usunąć sprawy źródłowej</h1>"\n'
         '                    "<p>Najpierw odłącz dokumenty współdzielone w ich kartach. Nie usunięto żadnych danych.</p></div>",\n'
         '                    "cases"),409)\n'
         '        with db() as con:',
         'blokada usunięcia sprawy źródłowej'),
        ('        if q and not results: items=\'<tr><td colspan=2>Brak wyników w metadanych.</td></tr>\'',
         '        if q and not results: items=\'<tr><td colspan=2>Brak wyników w metadanych.</td></tr>\'',
         'wyszukiwarka (kotwica)')
    ]
    for old,new,label in changes:
        if old == new:
            if source.count(old) != 1:
                raise RuntimeError(f'Nieoczekiwany kod wyszukiwarki: {source.count(old)} wystąpień.')
            continue
        source = replace_once(source, old, new, label)

    # Wynik wyszukiwania dokumentu ma prowadzić bezpośrednio do dokumentu,
    # nie do sprawy źródłowej. Id dokumentu umieszczamy tylko dla tego typu wyniku.
    search_before = "results += [('Dokument',r['case_id'],r['title'],"
    search_after = "results += [('Dokument',r['id'],r['title'],"
    source = replace_once(source, search_before,search_after, 'wyszukiwarka: identyfikator dokumentu')
    source = replace_once(
        source,
        "            if kind=='Podmiot':\n",
        "            if kind=='Dokument':\n                href=f'/document/{cid}/open'\n"
        "            elif kind=='Podmiot':\n",
        'wyszukiwarka: link do dokumentu')
    # Następna gałąź else poprzednio obsługiwała wszystkie rodzaje, nadal działa.
    compile(source,'app.py','exec')
    return source


def make_readme(readme: str) -> str:
    heading='## 0.3.2-dev1 — Stabilizacja, dokumenty współdzielone i pełnomocnictwa'
    if heading not in readme:
        readme += '''\n\n## 0.3.2-dev1 — Stabilizacja, dokumenty współdzielone i pełnomocnictwa
- Skrzynka wpływu: uruchomienie istniejącego modułu, ręczna weryfikacja, bez samoczynnej decyzji o terminach.
- Pełnomocnictwa: rejestr na podstawie już wgranych dokumentów; decyzja o umocowaniu należy do prawnika.
- Jeden dokument może być widoczny w wielu sprawach bez kopiowania oryginalnego pliku.
- Dokumenty współdzielone mają blokadę przypadkowego usunięcia ze sprawy źródłowej.
- Wyszukiwarka: wynik dokumentu otwiera bezpośrednio dokument.
- Podpowiedzi i dane demonstracyjne są neutralne; nie zawierają przykładów rzeczywistych spraw.
- Przed instalacją wykonaj kopię Data. Testy na osobnej kopii bazy.
'''
    if readme.startswith('# RK KANCELARIA 0.3.1-dev1'):
        readme=readme.replace('# RK KANCELARIA 0.3.1-dev1','# RK KANCELARIA 0.3.2-dev1',1)
    return readme


def _load(path: Path, name: str):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Nie udało się załadować: {path}')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def update(root: Path, dry_run: bool=False):
    root=root.resolve()
    needed=['app.py','README.md','rk_inbox.py','TEST_INBOX_REVIEW.py','LICENSE.txt',
            'RK_STABILIZACJA.py','RK_WYCZYSC_PODPOWIEDZI.py','rk_document_hub.py','AKTUALIZUJ_KOD.py']
    for name in needed:
        if not (root/name).is_file():
            raise RuntimeError(f'Brak wymaganego pliku {name} w {root}')
    with tempfile.TemporaryDirectory(prefix='rk-upgrade-') as temp:
        stage=Path(temp)
        for name in ['app.py','README.md','rk_inbox.py','TEST_INBOX_REVIEW.py','LICENSE.txt']:
            shutil.copy2(root/name,stage/name)
        current=(stage/'app.py').read_text(encoding='utf-8')
        if MARKER not in current:
            _load(root/'AKTUALIZUJ_KOD.py','rk_upgrade_inbox').update(stage)
            _load(root/'RK_STABILIZACJA.py','rk_upgrade_about').update(stage)
        app=(stage/'app.py').read_text(encoding='utf-8')
        app=_load(root/'RK_WYCZYSC_PODPOWIEDZI.py','rk_upgrade_clean').sanitize(app)
        app=apply_hub(app)
        readme=make_readme((stage/'README.md').read_text(encoding='utf-8'))
        compile(app,'app.py','exec')
        compile((root/'rk_document_hub.py').read_text(encoding='utf-8'),'rk_document_hub.py','exec')
        if dry_run:
            print('Weryfikacja bez zapisu OK — źródła zgodne z pakietem 0.3.2-dev1.')
            return
        old_app=(root/'app.py').read_bytes()
        old_readme=(root/'README.md').read_bytes()
        # Nie zapisujemy kopii app.py w repozytorium, ponieważ starszy kod
        # może zawierać poufne przykłady. Rollback w razie wyjątku jest lokalny.
        replacements=[(root/'app.py',app.encode('utf-8')),(root/'README.md',readme.encode('utf-8'))]
        try:
            for target, data in replacements:
                fd,tmpname=tempfile.mkstemp(prefix='.rk-update-',suffix='.tmp',dir=target.parent)
                try:
                    with os.fdopen(fd,'wb') as f: f.write(data)
                    os.replace(tmpname,target)
                finally:
                    if os.path.exists(tmpname): os.unlink(tmpname)
        except Exception:
            (root/'app.py').write_bytes(old_app)
            (root/'README.md').write_bytes(old_readme)
            raise
    print('RK KANCELARIA 0.3.2-dev1: przygotowano połączone źródła. Baz danych nie dotykano.')


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('root',nargs='?',default='.')
    ap.add_argument('--dry-run',action='store_true')
    args=ap.parse_args()
    try: update(Path(args.root),args.dry_run)
    except Exception as exc:
        print('BŁĄD AKTUALIZACJI: '+str(exc), file=sys.stderr)
        raise SystemExit(1)
