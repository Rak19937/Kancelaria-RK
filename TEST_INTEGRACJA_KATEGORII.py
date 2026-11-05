# -*- coding: utf-8 -*-
"""Kontrola wszystkich kotwic integracji katalogu i jej idempotencji."""
from pathlib import Path
import ast
import unittest
from unittest.mock import patch
import ZASTOSUJ_KATEGORIE as z


def fixture_from_installer():
    tree=ast.parse(Path(z.__file__).read_text(encoding='utf-8'))
    fun=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='apply_app')
    chunks={}
    direct=[]
    # Kod źródłowy stosuje statyczne fragmenty — budujemy minimalną
    # makietę oddającą zakresy metod; ten test nie zastępuje testu realnego repo.
    for stmt in fun.body:
        if not isinstance(stmt,ast.Assign) or not isinstance(stmt.value,ast.Call):continue
        call=stmt.value
        if not isinstance(call.func,ast.Name):continue
        if call.func.id=='once':
            arg=call.args[1]
            try:old=ast.literal_eval(arg)
            except Exception:continue
            direct.append(old)
        if call.func.id=='patch_method':
            start,end=map(ast.literal_eval,call.args[1:3])
            transforms=ast.literal_eval(call.args[3])
            chunks[start]=(end,[a for a,_,__ in transforms])
    # Wstawiamy identyfikatory metod w kolejności definicji z oryginalnego app.py.
    method_order=[
        '    def cases(self, qs, closed_only=False):',
        '    def case_new(self):',
        '    def case_create(self, f):',
        '    def case_edit(self,cid):',
        '    def case_update(self,cid,f):',
        '    def case_delete_confirm(self,cid,message',
        '    def case_workspace(self, cid, qs=None):',
        '    def case_view_simple(self, cid, qs=None):',
    ]
    # Pierwszy z fragmentów końcowych musi być widoczny.
    out='VERSION = "0.3.7-dev1"\nSCHEMA_VERSION = 328\n'
    for needle in direct:
        if needle not in out:out+=needle+'\n'
    for start in method_order:
        out+=start+'\n'
        if start in chunks:
            out+='\n'.join(chunks[start][1])+'\n'
    return out

class PatcherTests(unittest.TestCase):
    def test_expected_anchors_and_idempotence(self):
        src=fixture_from_installer()
        with patch.object(z,'compile',lambda *args:None,create=True):
            updated=z.apply_app(src)
            self.assertIn('SCHEMA_VERSION = 329',updated)
            self.assertIn('ensure_case_categories_schema(con)',updated)
            self.assertIn('category_filter_control',updated)
            self.assertIn('category_form(con,cid)',updated)
            self.assertEqual(updated,z.apply_app(updated))

    def test_unknown_version_rejected(self):
        with self.assertRaises(RuntimeError):z.apply_app('VERSION = "0.3.5-dev1"')

if __name__=='__main__':unittest.main(verbosity=2)
