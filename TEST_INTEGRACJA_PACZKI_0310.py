#!/usr/bin/env python3
"""Testy instalacji na źródłach *syntetycznych*, nie na prawdziwym repozytorium."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ZASTOSUJ_AKTUALIZACJE as install

PKG=Path(__file__).resolve().parent


def make_fixture_app():
    getlines=[]
    for p,(m,kind) in install.GET_ROUTES.items():
        args={'':'','q':'qs','q_closed_false':'qs, closed_only=False','q_closed_true':'qs, closed_only=True'}[kind]
        getlines.append(f'            if path == "{p}": return self.{m}({args})')
    postlines=[]
    for p,(m,kind) in install.POST_ROUTES.items():
        args={'':'','f':'fields','ff':'fields, files'}[kind]
        postlines.append(f"            if path == '{p}': return self.{m}({args})")
    # Dokładne kotwice z kodu 0.3.8-dev1 (uproszczony szkielet wykonawczy).
    return '''import re
from rk_document_hub import DocumentHubMixin, case_document_rows, ensure_document_hub_schema
VERSION = "0.3.8-dev1"

def layout(title: str, body: str, active: str = "") -> str:
    user = None
    nav_sections = [
        ('PRACA', []),
        ('WIĘCEJ', []),
        ('SYSTEM', [])
    ]
    nav_parts=[]
    for section,items in nav_sections:
        links = ''
        if section=='SYSTEM':
            opened=''
            nav_parts.append(f'<details class="nav-system"{opened}><summary><span>USTAWIENIA I SYSTEM</span><span class="nav-system-arrow">›</span></summary><div class="nav-system-links">{links}</div></details>')
        else:
            nav_parts.append('')
    nav_html=''.join(nav_parts)
    if user:
        role = "Administrator" if user['role']=='admin' else "Użytkownik"
    else:
        role = ''
    return f\'\'\'<link rel="stylesheet" href="/assets/rk_app.css?v={VERSION}">
<script src="/assets/rk_app.js?v={VERSION}" defer></script>\'\'\'

def writing_tabs(active: str):
    pass

class Handler:
    def do_GET(self):
        path='/'
        qs={}
        if not self.require_auth(): return
        try:
            if path == '/onboarding': return self.onboarding_page()
''' + '\n'.join(getlines) + '''
        except Exception:
            raise

    def do_POST(self):
        path='/logout'
        fields={}
        files={}
        if not self.require_auth(): return
        try:
''' + '\n'.join(postlines) + '''
            if re.fullmatch(r"/admin/user/\\d+/update", path): return self.user_update(1,fields)
        except Exception:
            raise

    def dashboard(self):
        today = '2026-11-05'
        week_end = '2026-11-12'
        uid = 1
        with db() as con:
            status_counts = {r['status']: r['cnt'] for r in con.execute('SELECT 1').fetchall()}; counts = status_counts
            due_today=1; overdue_count=0; next7_count=0; high_count=0
            dated=[]; undated=[]; upcoming=[]; recent_events=[]; pinned=[]; recent_cases=[]
            sig_ids=[]
            sig_map=load_external_signature_map(con,sig_ids)
        def case_mini(r, extra=''):
            return ''
        return counts

    def case_next_action_complete(self,cid,f):
        return None

    def document_view(self,did,qs=None):
        d={'case_id':1}
        toolbar = ''
        toolbar += f" <a class='btn' href='/document/{did}/links'>Powiązania spraw</a>"
        extra_css = '<style></style>'
        body = ''
        with db() as con: body += linked_records_panel(con,'document',d)
        self.send_html(layout('Podgląd dokumentu',extra_css+body,'documents'))
'''


def make_fixture_caseflow():
    return '''import sqlite3

def quick_nav_html():
    return ("<form action='/navigate' method='get'")

class CaseflowMixin:
    def caseflow_chronology(self,cid,qs):
        items=[]; reverse=False; head=''; a=None
        parts=[]
        for x in reversed(items) if reverse else items:
            parts.append(f'<div class="card" style="padding:12px;margin:8px 0">'
                         f'{x}</div>')
        return self.send_html(a.layout('Chronologia sprawy',head+''.join(parts) if parts else head+'<div class="card">Brak datowanych wpisów.</div>','cases'))

    def caseflow_navigate(self,qs):
        a=None; q='test'
        if not q: return self.redirect('/cases')
        like='%'+q+'%'
        with a.db() as con:
            cases=con.execute(''' + "'''SELECT id FROM cases WHERE title LIKE ?'''" + ''' ,(like,)).fetchall()
            tasks=con.execute(''' + "'''SELECT id FROM tasks WHERE title LIKE ?'''" + ''' ,(like,)).fetchall()
            docs=con.execute(''' + "'''SELECT id FROM documents WHERE title LIKE ?'''" + ''' ,(like,)).fetchall()
        rows=['<h2>Sprawy</h2>']
        return rows

    def caseflow_task_summary(self,tid):
        return None

    def caseflow_dependencies_page(self,tid):
        task={'title':'t'}; entries=[]
        body=(f'<div class="topbar"><h1>Zależności: {esc(task["title"])}</h1></div>'
              '<div class="card"><p class="small muted">Zadanie zależne nie jest automatycznie wykonywane. Potwierdzenie spełnienia warunków pozostaje po stronie użytkownika.</p>'
              +'</div>')
        return body
'''


def fixture(tmp):
    repo=Path(tmp)
    (repo/'assets').mkdir()
    app=make_fixture_app(); cf=make_fixture_caseflow()
    js='''    if (key === 'k') {
      e.preventDefault();
      const inp = document.querySelector('[data-global-search], #globalSearchInput');
      if (inp) { inp.focus(); inp.select(); }
      else location.href = '/search?focus=1';
    } else if (key === 'j') {'''
    # Skrót z app.py musi być widoczny dla poprzedniego instalatora.
    app += "\n# <span class='kbd'>Ctrl+K</span> szukaj\n"
    (repo/'app.py').write_text(app,encoding='utf-8')
    (repo/'rk_caseflow.py').write_text(cf,encoding='utf-8')
    (repo/'assets/rk_app.js').write_text(js,encoding='utf-8')
    for name in install.REGRESSION_TEST_BLOBS:
        source = (PKG/'fixtures'/(name+'.txt')).read_text(encoding='utf-8')
        (repo/name).write_text(source,encoding='utf-8')
        install.REGRESSION_TEST_BLOBS[name] = install.git_blob_sha(source)
    wf=(repo/'.github/workflows/main.yml')
    wf.parent.mkdir(parents=True)
    # Niewielki wzorzec workflow jest wbudowany w test, aby GitHub Actions
    # nie wymagał osobnego pliku w ukrytym katalogu fixtures/.github.
    # Test nadal wywołuje rzeczywisty instalator oraz sprawdza transakcję i rollback.
    fake_workflow = (
        "name: Minimal test workflow fixture\n"
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "      - name: Tests\n"
        "        run: |\n"
        "          python TEST_INTEGRACJA_CASEFLOW.py\n"
        "          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }\n"
        "          python RK_KANCELARIA_DESKTOP.pyw --self-test\n"
    )
    wf.write_text(fake_workflow,encoding='utf-8')
    install.WORKFLOW_BLOB=install.git_blob_sha(fake_workflow)
    (repo/'Data').mkdir()
    (repo/'Data/client.db').write_bytes(b'CONFIDENTIAL_TEST_BYTES')
    return repo


class EndToEndTests(unittest.TestCase):
    def test_clean_038_to_0310_single_transaction_and_idempotence(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=fixture(tmp)
            blobs={name:install.git_blob_sha((repo/name).read_text(encoding='utf-8')) for name in install.BASE_BLOBS}
            with patch.dict(install.BASE_BLOBS,blobs,clear=True):
                changes,old,_=install.build_changes(repo,PKG)
                self.assertIn(install.NEW_VERSION,changes[repo/'app.py'])
                self.assertNotIn('nav_sections = [',changes[repo/'app.py'])
                self.assertIn('dashboard_snapshot(',changes[repo/'app.py'])
                self.assertIn('dispatch_static_get(',changes[repo/'app.py'])
                self.assertIn('dispatch_static_post(',changes[repo/'app.py'])
                self.assertIn('find_navigation_matches(',changes[repo/'rk_caseflow.py'])
                self.assertIn('Ctrl+F',changes[repo/'app.py'])
                self.assertNotIn("key === 'k'",changes[repo/'assets/rk_app.js'])
                install.write_transaction(repo,changes,old,'.rk_backup_before_0310')
                changes_again,old_again,msg=install.build_changes(repo,PKG)
            self.assertIsNone(changes_again)
            self.assertIn('już istnieje',msg)
            self.assertEqual((repo/'Data/client.db').read_bytes(),b'CONFIDENTIAL_TEST_BYTES')
            self.assertTrue((repo/'.rk_backup_before_0310/app.py').exists())
            self.assertTrue((repo/'rk_routes.py').exists())
            from PRZYWROC_0310 import main as restore
            self.assertEqual(restore([str(repo)]),0)  # podgląd bez zmian
            self.assertTrue((repo/'rk_routes.py').exists())
            self.assertEqual(restore([str(repo),'--restore']),0)
            self.assertFalse((repo/'rk_routes.py').exists())
            self.assertIn('VERSION = "0.3.8-dev1"',(repo/'app.py').read_text(encoding='utf-8'))
            self.assertEqual((repo/'Data/client.db').read_bytes(),b'CONFIDENTIAL_TEST_BYTES')

    def test_upgrade_previous_039_dev2_without_overwriting_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=fixture(tmp)
            from _rk_ux_patch_support import apply_app, apply_caseflow, remove_legacy_search_shortcut
            (repo/'app.py').write_text(apply_app((repo/'app.py').read_text(encoding='utf-8')), encoding='utf-8')
            (repo/'rk_caseflow.py').write_text(apply_caseflow((repo/'rk_caseflow.py').read_text(encoding='utf-8')),encoding='utf-8')
            (repo/'assets/rk_app.js').write_text(remove_legacy_search_shortcut((repo/'assets/rk_app.js').read_text(encoding='utf-8')),encoding='utf-8')
            (repo/'rk_ux.py').write_text((PKG/'fixtures/rk_ux_previous.py.txt').read_text(encoding='utf-8'),encoding='utf-8')
            for name in ('rk_ux.js','rk_ux.css'):
                (repo/'assets'/name).write_text((PKG/'assets'/name).read_text(encoding='utf-8'),encoding='utf-8')
            data_before=(repo/'Data/client.db').read_bytes()
            changes,originals,label=install.build_changes(repo,PKG)
            self.assertIn('installed',label)
            self.assertIn(install.NEW_VERSION,changes[repo/'app.py'])
            self.assertIn('list_open_case_tasks',changes[repo/'rk_ux.py'])
            self.assertIn('find_navigation_matches',changes[repo/'rk_caseflow.py'])
            install.write_transaction(repo,changes,originals,'.rk_backup_before_0310')
            self.assertEqual((repo/'Data/client.db').read_bytes(),data_before)
            from PRZYWROC_0310 import main as restore
            self.assertEqual(restore([str(repo),'--restore']),0)
            self.assertIn('VERSION = "0.3.9-dev2"',(repo/'app.py').read_text(encoding='utf-8'))
            self.assertTrue((repo/'assets/rk_ux.js').is_file())
            self.assertEqual((repo/'Data/client.db').read_bytes(),data_before)

    def test_upgrade_previous_039_dev1_and_hotfix(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=fixture(tmp)
            from _rk_ux_patch_support import apply_app,apply_caseflow
            app=apply_app((repo/'app.py').read_text(encoding='utf-8'))
            app=app.replace('VERSION = "0.3.9-dev2"','VERSION = "0.3.9-dev1"')
            app=app.replace("<span class='kbd'>Ctrl+F</span> szukaj", "<span class='kbd'>Ctrl+K</span> szukaj")
            (repo/'app.py').write_text(app,encoding='utf-8')
            (repo/'rk_caseflow.py').write_text(apply_caseflow((repo/'rk_caseflow.py').read_text(encoding='utf-8')),encoding='utf-8')
            js=(PKG/'assets/rk_ux.js').read_text(encoding='utf-8')
            js=js.replace('Ctrl+F — otwórz','Ctrl+K — otwórz')
            js=js.replace("(e.ctrlKey||e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase()==='f'",
                          "(e.ctrlKey||e.metaKey) && e.key.toLowerCase()==='k'")
            js=js.replace('if(!e.repeat){modal.hidden?open():close();}','modal.hidden?open():close();')
            (repo/'assets/rk_ux.js').write_text(js,encoding='utf-8')
            (repo/'rk_ux.py').write_text((PKG/'fixtures/rk_ux_previous.py.txt').read_text(encoding='utf-8'),encoding='utf-8')
            changes,_,_=install.build_changes(repo,PKG)
            self.assertIn(install.NEW_VERSION,changes[repo/'app.py'])
            self.assertNotIn('Ctrl+K',changes[repo/'assets/rk_ux.js'])
            self.assertNotIn("key === 'k'",changes[repo/'assets/rk_app.js'])

    def test_incompatible_branch_does_not_modify_anything(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=fixture(tmp)
            before=(repo/'app.py').read_bytes()
            with self.assertRaises(RuntimeError):
                install.build_changes(repo,PKG)
            self.assertEqual((repo/'app.py').read_bytes(),before)
            self.assertFalse((repo/'.rk_backup_before_0310').exists())

if __name__=='__main__':unittest.main(verbosity=2)
