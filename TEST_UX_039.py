#!/usr/bin/env python3
"""Testy funkcji UX instalowanych w repozytorium; bez danych klienta."""
import sqlite3
import unittest
from pathlib import Path

from rk_ux import doc_workspace_panel, timeline_category

ROOT = Path(__file__).resolve().parent


class UXRuntimeTests(unittest.TestCase):
    def test_timeline_categories(self):
        expected = {
            'document-received': 'documents',
            'document-delivered': 'documents',
            'correspondence': 'correspondence',
            'task': 'tasks',
            'appointment': 'tasks',
            'process': 'events',
        }
        for key, value in expected.items():
            self.assertEqual(timeline_category(key), value)

    def test_document_panel_escapes_and_links(self):
        con = sqlite3.connect(':memory:')
        con.row_factory = sqlite3.Row
        con.execute('CREATE TABLE tasks(id INTEGER,case_id INTEGER,title TEXT,due_date TEXT,status TEXT,priority TEXT)')
        con.execute("INSERT INTO tasks VALUES(12,4,'<script>alert(1)</script>','2026-12-01','open','high')")
        doc = {'id': 9, 'case_id': 4, 'title': '<img src=x onerror=alert(1)>'}
        panel = doc_workspace_panel(con, doc)
        self.assertNotIn('<script>', panel)
        self.assertNotIn('<img src=x', panel)
        self.assertIn('/task/12/edit', panel)
        self.assertIn('name="return_to" value="/document/9/open"', panel)
        self.assertIn('name="case_id" value="4"', panel)
        self.assertNotIn('/task/13/edit', panel)
        readonly = doc_workspace_panel(con, doc, readonly=True)
        self.assertNotIn('action="/task/create"', readonly)
        con.close()

    def test_shortcut_in_new_package(self):
        text = (ROOT/'assets/rk_ux.js').read_text(encoding='utf-8')
        self.assertIn('Ctrl+F — otwórz', text)
        self.assertIn("e.key.toLowerCase()==='f'", text)
        self.assertIn('!e.altKey && !e.shiftKey', text)
        self.assertNotIn('Ctrl+K', text)
        self.assertNotIn("e.key.toLowerCase()==='k'", text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
