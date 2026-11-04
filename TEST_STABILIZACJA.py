# -*- coding: utf-8 -*-
"""Statyczny test spięcia modułów po wykonaniu aktualizacji (bez danych użytkownika)."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class StabilitySmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = (ROOT / 'app.py').read_text(encoding='utf-8')

    def test_source_compiles(self):
        ast.parse(self.src, filename='app.py')

    def test_inbox_wired(self):
        # Przy rozszerzaniu Handler o nowe moduły nie zakładaj konkretnej
        # kolejności klas bazowych ani liczby mixinów. Weryfikuj strukturę AST.
        tree = ast.parse(self.src, filename='app.py')
        handlers = [node for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == 'Handler']
        self.assertEqual(len(handlers), 1, 'Oczekiwano jednej klasy Handler')
        bases = {base.id for base in handlers[0].bases if isinstance(base, ast.Name)}
        for required_base in ('DocumentHubMixin', 'InboxMixin', 'BaseHTTPRequestHandler'):
            with self.subTest(handler_base=required_base):
                self.assertIn(required_base, bases)

        for marker in (
            'from rk_inbox import InboxMixin, ensure_inbox_schema',
            'ensure_inbox_schema(con)',
            '("/inbox", "✉", "Skrzynka wpływu", "inbox")',
            'if path == "/inbox": return self.inbox_page()',
            'if path == "/inbox/upload": return self.inbox_upload(fields, files)',
            'self.inbox_approve(', 'self.inbox_discard(',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.src)

    def test_about_and_license(self):
        for marker in ('def about_page(self):',
                       '("/about", "ⓘ", "O programie", "about")',
                       'if path == "/about": return self.about_page()'):
            self.assertIn(marker, self.src)
        self.assertTrue((ROOT / 'LICENSE.txt').is_file())


if __name__ == '__main__':
    unittest.main()
