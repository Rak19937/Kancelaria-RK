"""Krótko żyjące transakcje SQLite. Bez globalnego stanu aplikacji."""
from __future__ import annotations
import sqlite3
from contextlib import contextmanager

@contextmanager
def db_connection(db_path, data_dir):
    """Transakcyjne, krótko żyjące połączenie SQLite."""
    data_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, timeout=15, cached_statements=256)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA busy_timeout = 15000")
        con.execute("PRAGMA synchronous = NORMAL")
        con.execute("PRAGMA temp_store = MEMORY")
        con.execute("PRAGMA cache_size = -32768")
        con.execute("PRAGMA mmap_size = 134217728")
        yield con
        con.commit()
    except Exception:
        try: con.rollback()
        except Exception: pass
        raise
    finally:
        try: con.close()
        except Exception: pass
