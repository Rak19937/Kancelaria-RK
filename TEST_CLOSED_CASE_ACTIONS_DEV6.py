#!/usr/bin/env python3
from __future__ import annotations

import http.cookiejar
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="rk_closed_dev6_") as tmp:
        env=os.environ.copy()
        env.update({
            "SPRAWNIK_DATA_DIR":tmp,
            "SPRAWNIK_PORT":"18767",
            "SPRAWNIK_OPEN_BROWSER":"0",
            "SPRAWNIK_AUTO_SHUTDOWN":"0",
            "RK_KANCELARIA_SEED_DEMO":"0",
        })
        proc=subprocess.Popen([sys.executable,str(ROOT / "app.py")],cwd=ROOT,env=env,
                              stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
        try:
            base="http://127.0.0.1:18767"
            for _ in range(80):
                try:
                    urllib.request.urlopen(base + "/assets/rk_app.css",timeout=2).read()
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise AssertionError("Serwer testowy nie wystartował")

            jar=http.cookiejar.CookieJar()
            opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            setup=urllib.parse.urlencode({
                "username":"admin","author_name":"Administrator","function":"Administrator",
                "password":"testowe123","password2":"testowe123",
            }).encode()
            opener.open(urllib.request.Request(base + "/setup",data=setup),timeout=10).read()

            db_path=Path(tmp) / "sprawnik.sqlite3"
            with sqlite3.connect(db_path) as con:
                cid=con.execute("INSERT INTO cases(title,signature,status,closed_edit_unlocked) VALUES('Sprawa zakończona','I C 10/26','closed',0)").lastrowid
                con.execute("INSERT INTO documents(case_id,title,doc_type,description,doc_status) VALUES(?,?,?,?,?)",(cid,'Dokument rozwijany','Postanowienie','Pełny opis dokumentu','Aktywny'))
                con.commit()

            archive=opener.open(base + "/cases/closed",timeout=10).read().decode("utf-8")
            assert "Sprawa zakończona" in archive
            assert f"/case/{cid}/edit" in archive
            assert f"/case/{cid}/reopen" in archive
            assert f"/case/{cid}/delete" in archive

            edit=opener.open(base + f"/case/{cid}/edit",timeout=10).read().decode("utf-8")
            assert "Edytuj sprawę" in edit and "Sprawa tylko do odczytu" not in edit

            documents=opener.open(base + f"/case/{cid}?tab=documents",timeout=10).read().decode("utf-8")
            assert "document-disclosure" in documents
            assert "Rodzaj dokumentu:" in documents and "Postanowienie" in documents
            assert "Opis:" in documents and "Pełny opis dokumentu" in documents

            update=urllib.parse.urlencode({
                "signature":"I C 10/26","internal_signature":"","client":"",
                "title":"Sprawa zakończona — poprawiona","court":"","department":"",
                "category":"","subject":"Test","status":"closed","waiting_for":"",
                "next_step":"","next_date":"","notes":"","lead_user_id":"","tags":"",
            }).encode()
            opener.open(urllib.request.Request(base + f"/case/{cid}/update",data=update),timeout=10).read()
            with sqlite3.connect(db_path) as con:
                assert con.execute("SELECT title FROM cases WHERE id=?",(cid,)).fetchone()[0].endswith("poprawiona")

            opener.open(urllib.request.Request(base + f"/case/{cid}/reopen",data=b""),timeout=10).read()
            with sqlite3.connect(db_path) as con:
                status=con.execute("SELECT status FROM cases WHERE id=?",(cid,)).fetchone()[0]
                audit_count=con.execute("SELECT COUNT(*) FROM audit_log WHERE case_id=? AND action='Przywrócono sprawę do aktywnych'",(cid,)).fetchone()[0]
            assert status == "active" and audit_count == 1

            active=opener.open(base + "/cases",timeout=10).read().decode("utf-8")
            assert "Sprawa zakończona — poprawiona" in active
        finally:
            proc.terminate()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill()
        if proc.returncode not in (0,1,-15):
            raise AssertionError(proc.stderr.read() if proc.stderr else f"Kod serwera: {proc.returncode}")

    print("TEST_CLOSED_CASE_ACTIONS_DEV6: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
