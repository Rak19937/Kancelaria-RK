#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Synthetic tests for dev3 migration, dry-run, idempotence, rollback and Data isolation."""
from __future__ import annotations
import shutil
import tempfile
import unittest
from pathlib import Path
from ZASTOSUJ_040_DEV3 import MODULES, apply

APP='''from rk_inbox import InboxMixin, ensure_inbox_schema
from pathlib import Path
import sys
VERSION = "0.4.0-dev2"

def init_db():
    start_worker(sys.modules[__name__])

def layout():
    return f\'''<link rel="stylesheet" href="/assets/rk_ux.css?v={VERSION}">
<div class="app"><aside class="sidebar"><div class="brand">
<script src="/assets/rk_ux.js?v={VERSION}" defer></script></body></html>\'''

class Handler(CaseflowMixin, CaseCategoryMixin, InboxMixin):
    def do_GET(self):
        try:
            if dispatch_static_get(self, path, qs): return
        except Exception:
            pass
    def do_POST(self):
        try:
            if dispatch_static_post(self, path, fields, files): return
        except Exception:
            pass
'''
NAV='''NAV_SECTIONS=(('PRACA',(
        ('/my-calendar', '▣', 'Mój kalendarz', 'mycalendar'),
)),)
ADMIN_ITEMS=(
    ('/cloud', '☁', 'Cloud / PWA', 'cloud'),
)
'''

def fixture(repo:Path):
    files={
        'app.py':APP,
        'rk_navigation.py':NAV,
        'rk_core/schema_version.py':'SCHEMA_VERSION = 330\n',
        'requirements.txt':'reportlab>=4.0,<5\nopenpyxl>=3.1,<4\n',
        'RK_KANCELARIA_PORTABLE.spec':"for pkg in ('reportlab', 'openpyxl'):\n    pass\nhiddenimports=[\n        'cryptography',\n]\n",
        'TEST_ARCHITEKTURA_040.py':"def check(self,app):\n    self.assertIn('VERSION = \"0.4.0-dev2\"',app)\n",
        'TEST_STABILIZACJA_040_DEV2.py':'def check(self):\n    self.assertEqual(SCHEMA_VERSION,330)\n',
        'RAPORT_JAKOSCI_040.py':"report={'version':'0.4.0-dev2'}\n",
        'AUDYT_I_TESTY_RK_040_DEV2.py':"report={'version':'0.4.0-dev2'}\n",
    }
    for name,content in files.items():
        path=repo/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content,encoding='utf8')
    for name in MODULES:
        src=Path(__file__).parent/name
        dest=repo/name;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dest)
    (repo/'Data').mkdir()
    (repo/'Data'/'sprawnik.sqlite3').write_bytes(b'DO NOT CHANGE MY DB')

class InstallerTests(unittest.TestCase):
    def test_apply_repeat_verify_dry_run_and_data_safety(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root)
            old=(root/'Data'/'sprawnik.sqlite3').read_bytes()
            self.assertIn('DRY RUN OK',apply(root,dry_run=True))
            self.assertIn('0.4.0-dev2',(root/'app.py').read_text())
            self.assertIn('Zastosowano',apply(root))
            self.assertIn('dev3',apply(root))
            self.assertIn('zweryfikowana',apply(root,verify=True))
            src=(root/'app.py').read_text()
            self.assertIn('from rk_dev3 import Dev3Mixin',src)
            self.assertIn('ensure_dev3_schema(con)',src)
            self.assertIn('if self.dev3_get(path, qs): return',src)
            self.assertIn('if self.dev3_post(path, fields, files): return',src)
            self.assertIn('tzdata>=2025.2,<2028',(root/'requirements.txt').read_text())
            self.assertIn("'tzdata'",(root/'RK_KANCELARIA_PORTABLE.spec').read_text())
            self.assertEqual((root/'Data'/'sprawnik.sqlite3').read_bytes(),old)
            self.assertTrue((root/'.rk_backup_before_040_dev3/app.py').is_file())

    def test_bad_version_refuses_all_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root)
            (root/'app.py').write_text(APP.replace('0.4.0-dev2','0.1.0'),encoding='utf8')
            with self.assertRaisesRegex(RuntimeError,'Wymagana'):apply(root)
            self.assertFalse((root/'.rk_backup_before_040_dev3').exists())
            self.assertEqual((root/'Data'/'sprawnik.sqlite3').read_bytes(),b'DO NOT CHANGE MY DB')

if __name__=='__main__':unittest.main(verbosity=2)
