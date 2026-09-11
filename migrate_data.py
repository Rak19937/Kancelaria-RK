# -*- coding: utf-8 -*-
"""Jednorazowa/bezpieczna aktualizacja bieżącej bazy do schematu RK KANCELARIA 0.2."""
from __future__ import annotations
import sys
import traceback
import app


def main() -> int:
    print(f"RK KANCELARIA {app.VERSION} — migracja danych")
    print(f"Tryb: {app.APP_MODE}")
    print(f"Dane: {app.DATA_DIR}")
    try:
        app.DATA_DIR.mkdir(parents=True, exist_ok=True)
        if app.DB_PATH.exists():
            ok, why = app.sqlite_integrity(app.DB_PATH)
            if not ok:
                print(f"Baza wymaga recovery: {why}")
                msg = app.recover_database_if_needed()
                if msg: print(msg)
            msg = app.backup_before_version_upgrade()
            if msg: print(msg)
        app.init_db()
        ok, why = app.sqlite_integrity(app.DB_PATH)
        if not ok:
            raise RuntimeError(f"Baza po migracji nie przeszła kontroli integralności: {why}")
        with app.db() as con:
            schema = int(con.execute("PRAGMA user_version").fetchone()[0])
        if schema != app.SCHEMA_VERSION:
            raise RuntimeError(f"Nieprawidłowa wersja schematu po migracji: {schema}")
        try:
            app.VERSION_MARKER.write_text(app.VERSION, encoding="utf-8")
        except OSError:
            pass
        print(f"OK — schema={schema}")
        return 0
    except Exception as exc:
        print("BŁĄD MIGRACJI:", exc)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
