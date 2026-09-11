# -*- coding: utf-8 -*-
"""Bezpieczna diagnostyka fundamentu 0.2 — bez używania właściwej bazy."""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

from rk_paths import resolve_runtime_paths

BASE_DIR = Path(__file__).resolve().parent


def main() -> int:
    print('RK KANCELARIA 0.2.0-dev2 — DIAGNOSTYKA')
    paths = resolve_runtime_paths(BASE_DIR)
    print('Tryb:', paths.mode)
    print('Katalog programu:', paths.app_dir)
    print('Katalog danych:', paths.data_dir)
    print('Baza:', paths.db_path)

    probe_root = BASE_DIR / '_diagnostyka_tmp'
    shutil.rmtree(probe_root, ignore_errors=True)
    probe_root.mkdir(parents=True, exist_ok=False)
    try:
        db = probe_root / 'probe.sqlite3'
        with sqlite3.connect(db) as con:
            con.execute('CREATE TABLE test(id INTEGER PRIMARY KEY, value TEXT NOT NULL)')
            con.execute('INSERT INTO test(value) VALUES(?)', ('ąęćłńóśźż',))
            value = con.execute('SELECT value FROM test').fetchone()[0]
        assert value == 'ąęćłńóśźż'
        print('[OK] SQLite zapis/odczyt + polskie znaki')

        old = os.environ.get('SPRAWNIK_DATA_DIR')
        os.environ['SPRAWNIK_DATA_DIR'] = str(probe_root / 'custom')
        custom = resolve_runtime_paths(BASE_DIR)
        assert custom.mode == 'custom' and custom.data_dir == (probe_root / 'custom').resolve()
        print('[OK] SPRAWNIK_DATA_DIR ma najwyższy priorytet')
        if old is None:
            os.environ.pop('SPRAWNIK_DATA_DIR', None)
        else:
            os.environ['SPRAWNIK_DATA_DIR'] = old

        print('DIAGNOSTYKA OK')
        return 0
    finally:
        shutil.rmtree(probe_root, ignore_errors=True)


if __name__ == '__main__':
    raise SystemExit(main())
