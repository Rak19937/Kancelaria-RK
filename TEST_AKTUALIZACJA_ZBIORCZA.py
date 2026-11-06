# -*- coding: utf-8 -*-
"""Integracja modułów 0.4-dev2, z uwzględnieniem wyniesionego schematu SQLite."""
import ast
from pathlib import Path
import unittest
from rk_routes import GET_ROUTES

ROOT = Path(__file__).resolve().parent


class CombinedUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'app.py').read_text(encoding='utf-8')
        cls.schema = (ROOT / 'rk_core/schema.py').read_text(encoding='utf-8')
        cls.tree = ast.parse(cls.source, filename='app.py')

    def test_compile(self):
        ast.parse(self.source, filename='app.py')
        ast.parse(self.schema, filename='rk_core/schema.py')

    def test_handler_has_all_modules(self):
        handlers = [n for n in ast.walk(self.tree) if isinstance(n, ast.ClassDef) and n.name == 'Handler']
        self.assertEqual(len(handlers), 1)
        bases = [x.id for x in handlers[0].bases if isinstance(x, ast.Name)]
        for name in ('ActionCenterMixin', 'DocumentHubMixin', 'InboxMixin', 'BaseHTTPRequestHandler'):
            with self.subTest(module=name):
                self.assertIn(name, bases)

    def test_modules_connected(self):
        # Schemat ma własny moduł, a app.py jawnie wstrzykuje do niego zależności.
        for marker in (
            'ensure_inbox_schema(con)',
            'ensure_document_hub_schema(con)',
            'ensure_action_center_schema(con)',
        ):
            with self.subTest(schema_marker=marker):
                self.assertIn(marker, self.schema)
        for marker in (
            'from rk_core.schema import initialize_database',
            'initialize_database(db, schema_version=SCHEMA_VERSION,',
            'ensure_inbox_schema=ensure_inbox_schema',
            'ensure_document_hub_schema=ensure_document_hub_schema',
            'ensure_action_center_schema=ensure_action_center_schema',
            'docs=case_document_rows(con,cid)',
            'def about_page(self):',
            "href='/document/{did}/links'",
        ):
            with self.subTest(app_marker=marker):
                self.assertIn(marker, self.source)
        self.assertEqual(GET_ROUTES['/powers'], ('powers_page', 'q'))
        self.assertEqual(GET_ROUTES['/inbox'], ('inbox_page', ''))
        self.assertEqual(GET_ROUTES['/workflow'], ('action_center_page', ''))

    def test_neutral_placeholders(self):
        for marker in ('np. Klient A', 'np. pilne, do analizy, termin', 'Fikcyjne dane demonstracyjne'):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.source)

    def test_no_old_personal_demo(self):
        head = self.source.split('def seed_demo(con: sqlite3.Connection) -> None:', 1)[1].split('def esc(s) -> str:', 1)[0]
        self.assertIn('fikcyjne', head.lower())
        self.assertIn('Przykładowa sprawa', head)


if __name__ == '__main__':
    unittest.main(verbosity=2)
