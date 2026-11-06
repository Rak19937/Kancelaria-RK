# -*- coding: utf-8 -*-
"""Regresja po refaktoryzacji: rzeczywiste połączenie komponentów, a nie lokalizacja kodu."""
import ast
import unittest
from pathlib import Path
from rk_navigation import NAV_SECTIONS
from rk_routes import GET_ROUTES

ROOT = Path(__file__).resolve().parent


class StabilitySmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = (ROOT / 'app.py').read_text(encoding='utf-8')
        cls.schema = (ROOT / 'rk_core/schema.py').read_text(encoding='utf-8')

    def test_source_compiles(self):
        ast.parse(self.src, filename='app.py')
        ast.parse(self.schema, filename='rk_core/schema.py')

    def test_inbox_wired(self):
        tree = ast.parse(self.src, filename='app.py')
        handlers = [node for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == 'Handler']
        self.assertEqual(len(handlers), 1, 'Oczekiwano jednej klasy Handler')
        bases = {base.id for base in handlers[0].bases if isinstance(base, ast.Name)}
        for required in ('DocumentHubMixin', 'InboxMixin', 'BaseHTTPRequestHandler'):
            with self.subTest(handler_base=required):
                self.assertIn(required, bases)

        for marker in (
            'from rk_inbox import InboxMixin, ensure_inbox_schema',
            'from rk_core.schema import initialize_database',
            'initialize_database(db, schema_version=SCHEMA_VERSION,',
            'ensure_inbox_schema=ensure_inbox_schema',
            'if path == "/inbox/upload": return self.inbox_upload(fields, files)',
            'self.inbox_approve(', 'self.inbox_discard(',
        ):
            with self.subTest(app_marker=marker):
                self.assertIn(marker, self.src)
        for marker in ('def initialize_database(', 'ensure_inbox_schema(con)',
                       'ensure_document_hub_schema(con)', 'ensure_action_center_schema(con)'):
            with self.subTest(schema_marker=marker):
                self.assertIn(marker, self.schema)

        items = [item for section, links in NAV_SECTIONS for item in links]
        self.assertIn(('/inbox', '✉', 'Skrzynka wpływu', 'inbox'), items)
        self.assertEqual(GET_ROUTES['/inbox'], ('inbox_page', ''))

    def test_about_and_license(self):
        self.assertIn('def about_page(self):', self.src)
        items = [item for section, links in NAV_SECTIONS for item in links]
        self.assertIn(('/about', 'ⓘ', 'O programie', 'about'), items)
        self.assertEqual(GET_ROUTES['/about'], ('about_page', ''))
        self.assertTrue((ROOT / 'LICENSE.txt').is_file())


if __name__ == '__main__':
    unittest.main(verbosity=2)
