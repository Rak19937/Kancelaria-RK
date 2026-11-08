#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CI safety-regression checks for the release workflow and audit script."""
from __future__ import annotations
import ast
import tempfile
import unittest
from pathlib import Path
from RK_DEV5_AUDYT_REPO import run

ROOT=Path(__file__).resolve().parent

class RepoAuditTests(unittest.TestCase):
    def fixture(self,path,source='x=1\n'):
        (path/'app.py').write_text(source,encoding='utf8')
        (path/'RK_KANCELARIA_PORTABLE.spec').write_text('x=1',encoding='utf8')

    def test_syntax_error_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.fixture(root,'def boom(:\n')
            result=run(root)
            self.assertTrue(result['critical_count'])
            self.assertIn('PYTHON_SYNTAX',result['by_code'])

    def test_clean_tree_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.fixture(root)
            result=run(root)
            self.assertEqual(result['critical_count'],0)
            self.assertEqual(result['python_syntax_valid'],1)

    def test_dynamic_eval_is_warning_not_proof_of_exploit(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);self.fixture(root,'result=eval(expression)\n')
            result=run(root)
            self.assertIn('EVAL_OR_EXEC',result['by_code'])
            self.assertEqual(result['critical_count'],0)

    def test_no_auto_commit_workflow(self):
        patch=(ROOT/'ZASTOSUJ_040_DEV5_PELNA.py').read_text('utf8')
        self.assertIn("if rel == '.github/workflows/main.yml':",patch)
        ast.parse(patch)
        workflow=(ROOT/'.github/workflows/aktualizacja-dev5.yml').read_text('utf8')
        self.assertNotIn('git add -- app.py .github/workflows',workflow)
        for line in workflow.splitlines():
            if 'git add --' in line:self.assertNotIn('.github/workflows/',line)

    def test_main_is_manual_only(self):
        main=(ROOT/'.github/workflows/main.yml').read_text('utf8')
        self.assertIn('workflow_dispatch:',main)
        self.assertNotIn('  push:',main)

if __name__=='__main__':unittest.main(verbosity=2)
