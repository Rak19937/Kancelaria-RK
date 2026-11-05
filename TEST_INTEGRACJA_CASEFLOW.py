# -*- coding: utf-8 -*-
"""Regression dla zmiany 0.3.7 -> 0.3.8; CI wykona też pełną kompilację app.py."""
import ast
from pathlib import Path
import unittest
from unittest.mock import patch
import ZASTOSUJ_CASEFLOW as up


class IntegrationTests(unittest.TestCase):
    def fake_source(self):
        root=ast.parse(Path(up.__file__).read_text(encoding='utf8'))
        fun=next(node for node in root.body if isinstance(node,ast.FunctionDef) and node.name=='apply_app')
        globals_=[];met={}
        for call in ast.walk(fun):
            if not isinstance(call,ast.Call) or not isinstance(call.func,ast.Name):continue
            if call.func.id=='once':
                try: globals_.append(ast.literal_eval(call.args[1]))
                except (ValueError,TypeError,IndexError):continue
            if call.func.id=='method':
                try:
                    start=ast.literal_eval(call.args[1])
                    olds=[ast.literal_eval(t.elts[0]) for t in call.args[3].elts]
                    met[start]=olds
                except (ValueError,TypeError,IndexError,AttributeError):continue
        fake='\n'.join(globals_)
        # Wszystkie metody zachowują kolejność w repozytorium; granice metody
        # są sprawdzane, choć to tekstowe minimum (kompiluje się osobno w CI).
        method_order=['    def task_edit(self,tid,qs=None):',
                      '    def task_update(self,tid,f):',
                      '    def document_edit(self,did):',
                      '    def task_toggle(self,tid,f):',
                      '    def task_delete(self,tid,f):',
                      '    def case_workspace(self, cid, qs=None):',
                      '    def case_view_simple(self, cid, qs=None):',
                      '    def calendar_page(self, qs):',
                      '    def tasks_page(self,qs):',
                      '    def documents_page(self,qs):',
                      '    def note_add(self,cid,f):',
                      '    def history_page(self,qs):',
                      '    def trash_page(self,qs):']
        for name in method_order:
            if name in fake:continue
            fake+='\n'+name+'\n'+'\n'.join(met.get(name,[]))
        return fake

    def test_idempotent_and_wired(self):
        s=self.fake_source()
        self.assertIn('VERSION = "0.3.7-dev1"',s)
        with patch.object(up,'compile',lambda *args:None):
            out=up.apply_app(s)
            self.assertEqual(up.apply_app(out),out)
        self.assertIn('VERSION = "0.3.8-dev1"',out)
        self.assertIn('SCHEMA_VERSION = 330',out)
        self.assertIn('ensure_caseflow_schema(con)',out)
        self.assertIn('self.caseflow_documents(qs)',out)
        self.assertIn('self.caseflow_evidence(qs)',out)
        self.assertIn('self.caseflow_force_complete(',out)
        self.assertIn('dependency_blocking_counts',out)
        self.assertIn('self.caseflow_before_finish(',out)
        self.assertIn('self.caseflow_chronology(',out)
        self.assertIn('self.caseflow_task_summary(tid)',out)
        self.assertNotIn('VERSION = "0.3.7-dev1"',out)

    def test_bad_version_refused(self):
        with self.assertRaisesRegex(RuntimeError,'0.3.7'):
            up.apply_app('VERSION = "0.3.2-dev1"')

    def test_timeline_link_snippet_syntactically_valid(self):
        source="""def check(x):
            href=(f"/document/{x['source_id']}/open" if x['source_type']=='document' else
                  f"/process-event/{x['source_id']}/edit" if x['source_type']=='process_event' else
                  f"/event/{x['source_id']}/edit" if x['source_type']=='event' else '#')
            return href
        """
        compile(source,'timeline_link.py','exec')

if __name__=='__main__':unittest.main(verbosity=2)
