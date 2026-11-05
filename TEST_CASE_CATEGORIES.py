# -*- coding: utf-8 -*-
"""Testy katalogu kategorii spraw, 0.3.7-dev1, SQLite in-memory."""
import sqlite3
import unittest
import contextlib
from types import SimpleNamespace
from unittest.mock import patch
import rk_case_categories as cat
from rk_case_categories import (
    ensure_case_categories_schema, category_names, category_selector,
    selected_category_ids, save_case_categories, category_case_map,
    render_case_categories, ensure_legacy_category, CaseCategoriesMixin,
)


class CategoryTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
          CREATE TABLE cases(id INTEGER PRIMARY KEY, title TEXT, category TEXT);
          INSERT INTO cases VALUES(1,'Sprawa A','cywilna'),(2,'Sprawa B','karna, rodzinna'),(3,'Sprawa C','');
        ''')
        ensure_case_categories_schema(self.db)

    def tearDown(self):self.db.close()

    @contextlib.contextmanager
    def transaction(self):
        yield self.db
        self.db.commit()

    def test_migrate_old_values_and_seed_defaults(self):
        self.assertEqual(category_names(self.db,1),['Sprawa cywilna'])
        self.assertEqual(category_names(self.db,2),['Sprawa karna','Sprawa rodzinna'])
        self.assertEqual(category_names(self.db,3),[])
        count_before=self.db.execute('SELECT COUNT(*) FROM case_category_assignments').fetchone()[0]
        ensure_case_categories_schema(self.db)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM case_category_assignments').fetchone()[0],count_before)

    def test_multi_and_new_category_on_create(self):
        ids={x['name']:x['id'] for x in self.db.execute('SELECT * FROM case_category_catalog')}
        fields={'_categories_form':'1','case_cat_'+str(ids['Sprawa karna']):'1',
                'case_cat_'+str(ids['Sprawa rodzinna']):'1','new_category_name':'Sprawa skarbowa'}
        old,new=save_case_categories(self.db,3,fields)
        self.assertEqual(old,[])
        self.assertEqual(new,['Sprawa karna','Sprawa rodzinna','Sprawa skarbowa'])
        self.assertEqual(category_names(self.db,3),new)
        self.assertIn(self.db.execute('SELECT category FROM cases WHERE id=3').fetchone()[0],new)

    def test_edit_keeps_multiple_and_can_clear(self):
        ids={x['name']:x['id'] for x in self.db.execute('SELECT * FROM case_category_catalog')}
        save_case_categories(self.db,1,{'_categories_form':'1',f"case_cat_{ids['Sprawa cywilna']}":'1', f"case_cat_{ids['Sprawa karna']}":'1'})
        self.assertEqual(len(category_names(self.db,1)),2)
        save_case_categories(self.db,1,{'_categories_form':'1'})
        self.assertEqual(category_names(self.db,1),[])
        self.assertEqual(self.db.execute('SELECT category FROM cases WHERE id=1').fetchone()[0],'')

    def test_stale_legacy_form_does_not_overwrite_assignments(self):
        before=category_names(self.db,2)
        self.assertIsNone(save_case_categories(self.db,2,{'category':'inne'}))
        ensure_case_categories_schema(self.db)
        self.assertEqual(category_names(self.db,2),before)

    def test_invalid_ids_rejected_transactionally(self):
        before=category_names(self.db,1)
        for fields in [
            {'_categories_form':'1','case_cat_9999':'1'},
            {'_categories_form':'1','case_cat_1; DROP TABLE cases':'1'},
            {'_categories_form':'1','new_category_name':'z'*91},
        ]:
            with self.assertRaises(ValueError):save_case_categories(self.db,1,fields)
            self.assertEqual(category_names(self.db,1),before)

    def test_html_is_escaped(self):
        self.db.execute("INSERT INTO case_category_catalog(name) VALUES('<script>alert(1)</script>')")
        html=category_selector(self.db)
        self.assertIn('&lt;script&gt;',html)
        self.assertNotIn('<script>',html)
        self.assertIn('type="checkbox"',html)
        self.assertIn('case-categories',html)

    def test_filter_map_and_links(self):
        m=category_case_map(self.db,[1,2,3])
        self.assertEqual([x[1] for x in m[2]],['Sprawa karna','Sprawa rodzinna'])
        self.assertIn('/cases?category_id=',render_case_categories(m[2]))

    def test_legacy_sidecase_autotag(self):
        ensure_legacy_category(self.db,3,'administracyjna')
        self.assertEqual(category_names(self.db,3),['Sprawa administracyjna'])

    def test_category_rename_keeps_assignment_and_updates_legacy(self):
        class Handler(CaseCategoriesMixin):
            def redirect(self,path):self.last_redirect=path
            def send_error(self,*args):raise AssertionError(str(args))
        h=Handler()
        ctx=SimpleNamespace(db=self.transaction)
        with patch.object(cat,'_app',lambda _:ctx):
            cid=self.db.execute("SELECT id FROM case_category_catalog WHERE name='Sprawa cywilna'").fetchone()[0]
            h.category_rename(cid,{'name':'Sprawa ogólnocywilna'})
        self.assertEqual(category_names(self.db,1),['Sprawa ogólnocywilna'])
        self.assertEqual(self.db.execute('SELECT category FROM cases WHERE id=1').fetchone()[0],'Sprawa ogólnocywilna')

    def test_delete_case_cascades_joins(self):
        self.db.execute('DELETE FROM cases WHERE id=2')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM case_category_assignments WHERE case_id=2').fetchone()[0],0)


if __name__=='__main__':unittest.main(verbosity=2)
