# -*- coding: utf-8 -*-
"""Po instalacji: statyczny test połączenia modułów w źródłach."""
import ast
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent

class CombinedUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=(ROOT/'app.py').read_text(encoding='utf-8')

    def test_compile(self):
        ast.parse(self.source,filename='app.py')

    def test_modules_connected(self):
        for marker in (
            'class Handler(DocumentHubMixin, InboxMixin, BaseHTTPRequestHandler):',
            'ensure_inbox_schema(con)',
            'ensure_document_hub_schema(con)',
            'docs=case_document_rows(con,cid)',
            'if path == "/powers": return self.powers_page(qs)',
            'if path == "/inbox": return self.inbox_page()',
            'def about_page(self):',
            'href=\'/document/{did}/links\'',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker,self.source)

    def test_neutral_placeholders(self):
        for marker in ('np. Klient A','np. pilne, do analizy, termin','Fikcyjne dane demonstracyjne'):
            with self.subTest(marker=marker): self.assertIn(marker,self.source)

    def test_no_old_personal_demo(self):
        # Zachowujemy informację o autorze, ale nie dane podmiotów z przykładowych spraw.
        head=self.source.split('def seed_demo(con: sqlite3.Connection) -> None:',1)[1].split('def esc(s) -> str:',1)[0]
        self.assertIn('fikcyjne',head.lower())
        self.assertIn('Przykładowa sprawa',head)


if __name__=='__main__':
    unittest.main()
