#!/usr/bin/env python3
"""Testy instalatora uruchamiane wyłącznie z rozpakowanej paczki."""
import tempfile
import unittest
from pathlib import Path

from _rk_ux_patch_support import (
    NEW_VERSION, apply_app, apply_caseflow, git_blob_sha,
    modify_existing, remove_legacy_search_shortcut,
    replace_once, write_transaction,
)


class PatchTests(unittest.TestCase):
    def test_patch_anchor_must_be_unique(self):
        self.assertEqual(replace_once('ab', 'a', 'c', 'test'), 'cb')
        for content in ('aa', 'b'):
            with self.assertRaises(RuntimeError):
                replace_once(content, 'a', 'c', 'test')

    def test_remove_duplicate_legacy_handler(self):
        legacy = """  document.addEventListener('keydown', e => {
    if (!e.ctrlKey || e.altKey || e.metaKey) return;
    const key = String(e.key || '').toLowerCase();
    if (key === 'k') {
      e.preventDefault();
      const inp = document.querySelector('[data-global-search], #globalSearchInput');
      if (inp) { inp.focus(); inp.select(); }
      else location.href = '/search?focus=1';
    } else if (key === 'j') {
      e.preventDefault();
      location.href = '/quick-add';
    }
  });"""
        fixed = remove_legacy_search_shortcut(legacy)
        self.assertNotIn("key === 'k'", fixed)
        self.assertIn("key === 'j'", fixed)
        self.assertIn("location.href = '/quick-add'", fixed)

    def test_upgrade_existing_039(self):
        app = '''VERSION = "0.3.9-dev1"
from rk_ux import doc_workspace_panel
<script src="/assets/rk_ux.js?v={VERSION}" defer></script>
<span class='kbd'>Ctrl+K</span> szukaj'''
        old_js = """    if (key === 'k') {
      e.preventDefault();
      const inp = document.querySelector('[data-global-search], #globalSearchInput');
      if (inp) { inp.focus(); inp.select(); }
      else location.href = '/search?focus=1';
    } else if (key === 'j') {"""
        old_ux = """<small>Ctrl+K — otwórz</small>
if((e.ctrlKey||e.metaKey) && e.key.toLowerCase()==='k'){
e.preventDefault();e.stopImmediatePropagation();modal.hidden?open():close();return;
}"""
        a, j, u = modify_existing(app, old_js, old_ux)
        self.assertIn(NEW_VERSION, a)
        self.assertIn('Ctrl+F</span>', a)
        self.assertNotIn("key === 'k'", j)
        self.assertIn("key === 'j'", j)
        self.assertIn("!e.altKey && !e.shiftKey && e.key.toLowerCase()==='f'", u)
        self.assertNotIn('Ctrl+K', u)

    def test_backup_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            old = repo / 'app.py'
            old.write_text('old', encoding='utf-8')
            data = repo / 'Data' / 'client.db'
            data.parent.mkdir()
            data.write_text('untouched', encoding='utf-8')
            write_transaction(repo, {old: 'new', repo / 'rk_ux.py': 'ok'}, (old,), '.patch_backup')
            self.assertEqual(old.read_text(encoding='utf-8'), 'new')
            self.assertEqual((repo / '.patch_backup' / 'app.py').read_text(encoding='utf-8'), 'old')
            self.assertEqual(data.read_text(encoding='utf-8'), 'untouched')
            with self.assertRaises(RuntimeError):
                write_transaction(repo, {old: 'bad'}, (old,), '.patch_backup')
            self.assertEqual(old.read_text(encoding='utf-8'), 'new')

    def test_git_blob_hash(self):
        self.assertEqual(git_blob_sha('hello\n'), 'ce013625030ba8dba906f756967f9e9ca394464a')

    def test_new_app_patches_syntax_anchors(self):
        sample = '''VERSION = "0.3.8-dev1"
from rk_document_hub import DocumentHubMixin, case_document_rows, ensure_document_hub_schema
<link rel="stylesheet" href="/assets/rk_app.css?v={VERSION}">
<script src="/assets/rk_app.js?v={VERSION}" defer></script>
if section=='SYSTEM':
nav_parts.append(f'<details class="nav-system"{opened}><summary><span>USTAWIENIA I SYSTEM</span><span class="nav-system-arrow">›</span></summary><div class="nav-system-links">{links}</div></details>')
with db() as con: body += linked_records_panel(con,'document',d)
        self.send_html(layout('Podgląd dokumentu',extra_css+body,'documents'))
toolbar += f" <a class='btn' href='/document/{did}/links'>Powiązania spraw</a>"
<span class='kbd'>Ctrl+K</span> szukaj'''
        patched = apply_app(sample)
        self.assertIn('VERSION = "0.3.9-dev2"', patched)
        self.assertIn('rk_ux.css', patched)
        self.assertIn('rk_ux.js', patched)
        self.assertIn('Ctrl+F</span>', patched)
        self.assertNotIn('Ctrl+K', patched)

    def test_caseflow_patches(self):
        sample = '''import sqlite3
def quick_nav_html():
    return ("<form action='/navigate' method='get'
        parts=[]
        for x in reversed(items) if reverse else items:
            parts.append(f'<div class="card" style="padding:12px;margin:8px 0">'
        return self.send_html(a.layout('Chronologia sprawy',head+''.join(parts) if parts else head+'<div class="card">Brak datowanych wpisów.</div>','cases'))
        body=(f'<div class="topbar"><h1>Zależności: {esc(task["title"])}</h1></div>'
              '<div class="card"><p class="small muted">Zadanie zależne nie jest automatycznie wykonywane. Potwierdzenie spełnienia warunków pozostaje po stronie użytkownika.</p>' '''
        patched = apply_caseflow(sample)
        self.assertIn("form action='/search'", patched)
        self.assertIn('data-ux-source', patched)
        self.assertIn('rk-ux-chain-step', patched)


if __name__ == '__main__':
    unittest.main(verbosity=2)
