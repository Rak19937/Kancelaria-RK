# -*- coding: utf-8 -*-
"""Test integracji modułów, niewrażliwy na kolejność klas mixin Handler."""
import ast
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent


class CombinedUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=(ROOT/'app.py').read_text(encoding='utf-8')
        cls.tree=ast.parse(cls.source,filename='app.py')

    def test_compile(self):
        ast.parse(self.source,filename='app.py')

    def test_handler_has_all_modules(self):
        handlers=[n for n in ast.walk(self.tree) if isinstance(n,ast.ClassDef) and n.name=='Handler']
        self.assertEqual(len(handlers),1)
        bases=[x.id for x in handlers[0].bases if isinstance(x,ast.Name)]
        for name in ('ActionCenterMixin','DocumentHubMixin','InboxMixin','BaseHTTPRequestHandler'):
            with self.subTest(module=name):self.assertIn(name,bases)

    def test_modules_connected(self):
        for marker in (
            'ensure_inbox_schema(con)',
            'ensure_document_hub_schema(con)',
            'ensure_action_center_schema(con)',
            'docs=case_document_rows(con,cid)',
            'if path == "/powers": return self.powers_page(qs)',
            'if path == "/inbox": return self.inbox_page()',
            'if path == "/workflow": return self.action_center_page()',
            'def about_page(self):',
            "href='/document/{did}/links'",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker,self.source)

    def test_neutral_placeholders(self):
        for marker in ('np. Klient A','np. pilne, do analizy, termin','Fikcyjne dane demonstracyjne'):
            with self.subTest(marker=marker):self.assertIn(marker,self.source)

    def test_no_old_personal_demo(self):
        head=self.source.split('def seed_demo(con: sqlite3.Connection) -> None:',1)[1].split('def esc(s) -> str:',1)[0]
        self.assertIn('fikcyjne',head.lower())
        self.assertIn('Przykładowa sprawa',head)


if __name__=='__main__':
    unittest.main(verbosity=2)
