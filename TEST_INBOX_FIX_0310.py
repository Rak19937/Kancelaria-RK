#!/usr/bin/env python3
"""Test nieinwazyjnej poprawki interfejsu skrzynki wpływu 0.3.10."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import ZASTOSUJ_SKRZYNKA_FIX as fix

OLD_HTML = '''def inbox_page():
    return """<form method='post' action='/inbox/upload' enctype='multipart/form-data'>
    <input type='file' name='file' required>
    <button class='btn primary'>Odczytaj i przygotuj propozycje</button></form>"""
'''
OLD_JS = '''(() => { 'use strict';})();\n'''

class InboxFixTests(unittest.TestCase):
    def fixture(self, tmp: str) -> Path:
        repo=Path(tmp)
        (repo/'assets').mkdir()
        (repo/'app.py').write_text('VERSION = "0.3.10-dev1"\n',encoding='utf-8')
        (repo/'rk_inbox.py').write_text(OLD_HTML,encoding='utf-8')
        (repo/'assets/rk_app.js').write_text(OLD_JS,encoding='utf-8')
        (repo/'Data').mkdir()
        (repo/'Data/akta.db').write_bytes(b'PRIVATE_TEST_DATABASE')
        return repo

    def test_form_is_normal_post_with_feedback(self):
        result=fix.fix_inbox(OLD_HTML)
        self.assertIn("action='/inbox/upload' enctype='multipart/form-data' data-rk-inbox-upload",result)
        self.assertIn('Odczytaj i przygotuj propozycje',result)
        self.assertIn('aria-live=\'polite\'', result)
        self.assertIn("type='submit'",result)
        self.assertIn('role=\'status\'',result)

    def test_javascript_keeps_native_post_and_validates_file(self):
        updated=fix.fix_js(OLD_JS)
        for marker in ('submit', 'fileInput.files', '20 * 1024 * 1024',
                       'aria-live', 'Trwa odczytywanie', 'e.preventDefault()'):
            if marker!='aria-live': self.assertIn(marker,updated)
        self.assertNotIn('fetch(',updated)
        self.assertEqual(updated,fix.fix_js(updated))

    def test_atomic_idempotent_no_db_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=self.fixture(tmp)
            sha={name:fix.sha_git((repo/name).read_bytes()) for name in fix.BASE_SHA}
            with patch.dict(fix.BASE_SHA,sha,clear=True):
                self.assertIn('DRY RUN OK',fix.apply(repo, True))
                self.assertNotIn(fix.MARKER,(repo/'rk_inbox.py').read_text(encoding='utf8'))
                fix.apply(repo)
                self.assertIn(fix.MARKER,(repo/'rk_inbox.py').read_text(encoding='utf8'))
                self.assertIn(fix.JS_MARKER,(repo/'assets/rk_app.js').read_text(encoding='utf8'))
                self.assertIn('już',fix.apply(repo))
                self.assertEqual((repo/'Data/akta.db').read_bytes(),b'PRIVATE_TEST_DATABASE')
                self.assertTrue((repo/'.rk_inbox_fix_backup_0310/rk_inbox.py').exists())
                self.assertTrue((repo/'.rk_inbox_fix_backup_0310/assets/rk_app.js').exists())

    def test_modified_source_refused_before_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=self.fixture(tmp)
            before=(repo/'rk_inbox.py').read_bytes()
            with self.assertRaisesRegex(RuntimeError,'niezgodna wersja'):
                fix.apply(repo)
            self.assertEqual((repo/'rk_inbox.py').read_bytes(),before)
            self.assertFalse((repo/'.rk_inbox_fix_backup_0310').exists())

    def test_unsupported_program_version_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=self.fixture(tmp)
            (repo/'app.py').write_text('VERSION = "0.3.8-dev1"\n',encoding='utf8')
            with self.assertRaisesRegex(RuntimeError,'0.3.10'):
                fix.apply(repo)

if __name__ == '__main__': unittest.main(verbosity=2)
