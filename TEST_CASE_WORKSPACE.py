#!/usr/bin/env python3
"""Szybki, samodzielny test schematu i snapshotu CASE WORKSPACE."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rk_case_workspace_") as tmp:
        os.environ["SPRAWNIK_DATA_DIR"] = tmp
        os.environ["SPRAWNIK_AUTO_SHUTDOWN"] = "0"
        os.environ["RK_KANCELARIA_SEED_DEMO"] = "0"
        import app

        app.init_db()
        with app.db() as con:
            cur=con.execute("INSERT INTO cases(title,subject) VALUES('Test CASE WORKSPACE','Test migracji')")
            cid=cur.lastrowid
            con.execute("INSERT INTO case_strategy(case_id,main_goal) VALUES(?,?)",(cid,'Wygrana'))
            cur=con.execute("INSERT INTO case_assertions(case_id,statement) VALUES(?,?)",(cid,'Fakt testowy'))
            aid=cur.lastrowid
            con.execute("INSERT INTO case_evidence(assertion_id,title) VALUES(?,?)",(aid,'Dowód testowy'))
            con.execute("INSERT INTO case_claims(case_id,title,principal_cents) VALUES(?,?,?)",(cid,'Roszczenie',2_750_057))
            folder=app.FILES_DIR/f"sprawa_{cid}"; folder.mkdir(parents=True,exist_ok=True)
            stored='test.txt'; (folder/stored).write_text('RK',encoding='utf-8')
            cur=con.execute("INSERT INTO documents(case_id,title,stored_name,original_name) VALUES(?,?,?,?)",(cid,'Dokument',stored,stored))
            did=cur.lastrowid
            con.execute("INSERT INTO document_events(document_id,case_id,event_date,title) VALUES(?,?,?,?)",(did,cid,'2026-09-16','Zdarzenie'))
            assert app.save_document_file_version(con,did,'Tester')
            con.execute(f"PRAGMA user_version={app.SCHEMA_VERSION}")

        with sqlite3.connect(app.DB_PATH) as con:
            assert con.execute('PRAGMA user_version').fetchone()[0] == app.SCHEMA_VERSION
            assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert con.execute('SELECT principal_cents FROM case_claims').fetchone()[0] == 2_750_057

        raw,_=app.create_data_snapshot_zip()
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            meta=json.loads(z.read('snapshot.json'))
            assert meta['schema_version'] == app.SCHEMA_VERSION
            names=set(z.namelist())
            assert f'dokumenty/sprawa_{cid}/{stored}' in names
            assert any(x.startswith(f'dokumenty/sprawa_{cid}/wersje_dokumentu_{did}/') for x in names)

        assert app.money_to_cents('27 500,57') == 2_750_057
        assert '27 500,57' in app.fmt_money(2_750_057)
        print(f'OK: CASE WORKSPACE schema {app.SCHEMA_VERSION}, kwoty, wersje dokumentów i snapshot')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
