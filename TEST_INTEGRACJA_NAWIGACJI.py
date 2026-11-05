import ast,unittest
from unittest.mock import patch
import ZASTOSUJ_NAWIGACJE as up

class IntegratorTests(unittest.TestCase):
    def test_all_expected_anchors_transform_idempotent(self):
        from pathlib import Path
        tree=ast.parse(Path(up.__file__).read_text(encoding='utf8'))
        fun=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='apply_app')
        vals=[]; variables={}
        for stmt in fun.body:
            if (isinstance(stmt,ast.Assign) and len(stmt.targets)==1 and isinstance(stmt.targets[0],ast.Name)):
                try:variables[stmt.targets[0].id]=ast.literal_eval(stmt.value)
                except Exception:pass
            if isinstance(stmt,ast.Assign) and isinstance(stmt.value,ast.Call) and isinstance(stmt.value.func,ast.Name) and stmt.value.func.id=='once':
                arg=stmt.value.args[1]
                if isinstance(arg,ast.Name):old=variables[arg.id]
                else:old=ast.literal_eval(arg)
                # The noop once repeats the same literal with identical replacement.
                if old not in vals:vals.append(old)
        s=('from rk_correspondence import CorrespondenceMixin, ensure_correspondence_schema\n'
           'VERSION = "0.3.5-dev1"\nSCHEMA_VERSION = 326\n')
        s+='\n'.join(x for x in vals if x not in s)
        with patch.object(up,'compile',lambda *args:None):
            new=up.apply_app(s)
        self.assertIn('VERSION = "0.3.6-dev1"',new)
        self.assertIn('case_deadline_rows(tasks,alerts,c,fmt_date',new)
        self.assertIn('clear_case_next_date',new)
        self.assertIn('return self.redirect(safe_back(',new)
        with patch.object(up,'compile',lambda *args:None):
            self.assertEqual(new,up.apply_app(new))

if __name__=='__main__':unittest.main(verbosity=2)
