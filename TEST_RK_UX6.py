# -*- coding: utf-8 -*-
"""UX6 regression tests: synthetic SQLite only, no real client data/network."""
from __future__ import annotations
import sqlite3
import tempfile
import unittest
from pathlib import Path
from rk_ux6 import (ensure_ux6_schema, checked_name, save_choice,
                    choice_exists, delete_case_dependencies, Ux6Mixin)
from ZASTOSUJ_UX6 import replace_once


def fixture():
    con=sqlite3.connect(':memory:');con.row_factory=sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.executescript('''
      CREATE TABLE cases(id INTEGER PRIMARY KEY,title TEXT,status TEXT);
      CREATE TABLE documents(id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL
           REFERENCES cases(id) ON DELETE CASCADE, title TEXT);
      CREATE TABLE dev4_case_marker(id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL
           REFERENCES cases(id) ON DELETE NO ACTION, content TEXT);
      INSERT INTO cases VALUES(1,'Przykładowa sprawa','closed');
      INSERT INTO cases VALUES(2,'Sprawa obok','active');
      INSERT INTO documents VALUES(1,1,'Pismo');
      INSERT INTO dev4_case_marker VALUES(1,1,'Test');
      INSERT INTO dev4_case_marker VALUES(2,2,'Zachowaj');
    ''')
    ensure_ux6_schema(con);return con


class SchemaAndChoices(unittest.TestCase):
    def setUp(self):self.con=fixture()
    def tearDown(self):self.con.close()
    def test_schema_idempotent(self):
        ensure_ux6_schema(self.con)
        self.assertEqual(self.con.execute("SELECT name FROM sqlite_master WHERE name='ux6_case_phases'").fetchone()[0],'ux6_case_phases')
    def test_choices_are_persistent_and_case_insensitive(self):
        save_choice(self.con,'phase','Mediacja');save_choice(self.con,'phase','mediacja')
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM ux6_custom_choices').fetchone()[0],1)
    def test_reject_unknown_kind(self):
        with self.assertRaises(ValueError):save_choice(self.con,'role','administrator')
    def test_reject_empty_and_overlong(self):
        with self.assertRaises(ValueError):checked_name('   ')
        with self.assertRaises(ValueError):checked_name('a'*101)
    def test_reject_control_characters(self):
        with self.assertRaises(ValueError):checked_name('A\x00B')
    def test_normalize_spaces(self):self.assertEqual(checked_name('  Proces   sądowy  '),'Proces sądowy')
    def test_phase_multiple_concurrently(self):
        self.con.executemany('INSERT INTO ux6_case_phases(case_id,label) VALUES(?,?)',[(1,'Proces'),(1,'Mediacja')])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM ux6_case_phases WHERE case_id=1 AND state='active'").fetchone()[0],2)
    def test_phase_fk_cascade(self):
        self.con.execute('INSERT INTO ux6_case_phases(case_id,label) VALUES(1,\'Mediacja\')')
        delete_case_dependencies(self.con,1)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM ux6_case_phases').fetchone()[0],0)
    def test_custom_lookup(self):
        save_choice(self.con,'task_type','Wezwanie do ugody')
        class Context:
            def __enter__(self):return con
            def __exit__(self,*args):return False
        con=self.con
        self.assertTrue(choice_exists(lambda:Context(),'task_type','Wezwanie do ugody'))
        self.assertFalse(choice_exists(lambda:Context(),'status','admin'))


class DeleteSafety(unittest.TestCase):
    def setUp(self):self.con=fixture()
    def tearDown(self):self.con.close()
    def test_removes_only_target_case_and_children(self):
        delete_case_dependencies(self.con,1)
        self.assertEqual([r[0] for r in self.con.execute('SELECT id FROM cases')],[2])
        self.assertEqual([r[0] for r in self.con.execute('SELECT id FROM dev4_case_marker')],[2])
    def test_restrict_unknown_case_relation_fails_closed(self):
        self.con.execute('CREATE TABLE shared_external(k INTEGER, case_id INTEGER REFERENCES cases(id) ON DELETE RESTRICT)')
        self.con.execute('INSERT INTO shared_external VALUES(1,1)')
        with self.assertRaises(sqlite3.IntegrityError):
            with self.con:
                delete_case_dependencies(self.con,1)
        self.assertIsNotNone(self.con.execute('SELECT * FROM cases WHERE id=1').fetchone())
        self.assertIsNotNone(self.con.execute('SELECT * FROM documents WHERE id=1').fetchone())
    def test_never_deletes_unrelated_case(self):
        delete_case_dependencies(self.con,1)
        self.assertEqual(self.con.execute('SELECT title FROM cases WHERE id=2').fetchone()[0],'Sprawa obok')


class PatchGuards(unittest.TestCase):
    def test_patch_refuses_ambiguous_anchor(self):
        with self.assertRaises(RuntimeError):replace_once('xxx xxx','xxx','yyy','demo')
    def test_patch_idempotent_anchor(self):
        self.assertEqual(replace_once('hello world','hello','goodbye','demo'),'goodbye world')
        self.assertEqual(replace_once('goodbye world','hello','goodbye','demo'),'goodbye world')
    def test_requested_files_present(self):
        root=Path(__file__).parent
        for n in ('rk_ux6.py','ZASTOSUJ_UX6.py','assets/rk_ux6.css','assets/rk_ux6.js'):
            self.assertTrue((root/n).is_file(),n)

if __name__=='__main__':unittest.main(verbosity=2)
