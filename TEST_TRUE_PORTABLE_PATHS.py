from pathlib import Path
import sys
import tempfile

from rk_paths import resolve_runtime_paths

old_frozen = getattr(sys, 'frozen', None)
old_exe = sys.executable
try:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        fake = root / 'RK KANCELARIA.exe'
        fake.write_bytes(b'')
        (root / 'portable.flag').write_text('portable', encoding='utf-8')
        sys.frozen = True
        sys.executable = str(fake)
        r = resolve_runtime_paths(root / '_internal' / 'app.py')
        assert r.app_dir == root.resolve(), (r.app_dir, root)
        assert r.mode == 'portable', r.mode
        assert r.data_dir == (root / 'Data').resolve(), r.data_dir
        print('OK: frozen portable paths ->', r.data_dir)
finally:
    sys.executable = old_exe
    if old_frozen is None:
        try: del sys.frozen
        except AttributeError: pass
    else:
        sys.frozen = old_frozen
