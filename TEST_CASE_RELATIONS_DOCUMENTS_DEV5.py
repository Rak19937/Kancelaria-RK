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
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def multipart(fields: dict[str, str], files: list[tuple[str, str, bytes]]) -> tuple[bytes, str]:
    boundary = "----RKTest" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode("utf-8"), b"\r\n",
        ])
    for name, filename, data in files:
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: application/octet-stream\r\n\r\n", data, b"\r\n",
        ])
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def main() -> int:
    source=(ROOT / "app.py").read_text(encoding="utf-8")
    assert "('relations','Powiązania'" in source
    assert 'name="attachments[]" multiple' in source
    assert "backup_przed_usunieciem_sprawy" in source

    with tempfile.TemporaryDirectory(prefix="rk_dev5_") as tmp:
        env=os.environ.copy()
        env.update({
            "SPRAWNIK_DATA_DIR":tmp,
            "SPRAWNIK_PORT":"18766",
            "SPRAWNIK_OPEN_BROWSER":"0",
            "SPRAWNIK_AUTO_SHUTDOWN":"0",
            "RK_KANCELARIA_SEED_DEMO":"0",
        })
        proc=subprocess.Popen([sys.executable,str(ROOT / "app.py")],cwd=ROOT,env=env,
                              stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
        try:
            base="http://127.0.0.1:18766"
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
                first=con.execute("INSERT INTO cases(title,signature,status) VALUES('Sprawa główna','I C 1/26','active')").lastrowid
                duplicate=con.execute("INSERT INTO cases(title,signature,status) VALUES('Duplikat sprawy','I C 1/26','closed')").lastrowid
                folder=Path(tmp) / "dokumenty" / f"sprawa_{first}"
                folder.mkdir(parents=True,exist_ok=True)
                (folder / "pismo.txt").write_bytes(b"pismo glowne")
                did=con.execute("INSERT INTO documents(case_id,title,doc_type,stored_name,original_name,file_hash) VALUES(?,?,?,?,?,?)",
                                (first,"Pismo testowe","Pismo procesowe","pismo.txt","pismo.txt","stary-hash")).lastrowid
                con.commit()

            relation_data=urllib.parse.urlencode({
                "target_case_id":str(duplicate),"relation_type":"main_related","note":"duplikat / sprawa powiązana",
                "return_to":f"/case/{first}?tab=relations",
            }).encode()
            relation_html=opener.open(urllib.request.Request(base + f"/case/{first}/relation",data=relation_data),timeout=10).read().decode("utf-8")
            assert "Powiązane sprawy" in relation_html and "Duplikat sprawy" in relation_html
            with sqlite3.connect(db_path) as con:
                assert con.execute("SELECT COUNT(*) FROM case_relations WHERE source_case_id=?",(first,)).fetchone()[0] == 1

            fields={
                "case_id":str(first),"return_to":f"/case/{first}?tab=documents",
                "doc_date":"2026-09-17","received_date":"","delivered_date":"",
                "doc_type":"Pismo procesowe","doc_status":"Aktywny","sender":"Sąd",
                "document_author":"Karina","tags":"test","linked_task_id":"",
                "title":"Pismo testowe po edycji","description":"dodano brakujący załącznik",
            }
            body,content_type=multipart(fields,[("attachments[]","zalacznik-a.txt",b"zalacznik A"),("attachments[]","zalacznik-b.txt",b"zalacznik B")])
            req=urllib.request.Request(base + f"/document/{did}/update",data=body,headers={"Content-Type":content_type})
            result=opener.open(req,timeout=15).read().decode("utf-8")
            assert "Dokumenty" in result
            with sqlite3.connect(db_path) as con:
                children=con.execute("SELECT title,original_name FROM documents WHERE parent_document_id=? ORDER BY attachment_order",(did,)).fetchall()
                assert [x[1] for x in children] == ["zalacznik-a.txt","zalacznik-b.txt"]

            # Podmiana pliku głównego ma zachować faktycznie poprzedni plik,
            # a nie omyłkowo nową wersję pod starą etykietą.
            replace_body,replace_type=multipart(fields,[("file","pismo-nowe.txt",b"nowa wersja")])
            replace_req=urllib.request.Request(base + f"/document/{did}/update",data=replace_body,headers={"Content-Type":replace_type})
            opener.open(replace_req,timeout=15).read()
            with sqlite3.connect(db_path) as con:
                version=con.execute("SELECT stored_name,original_name FROM document_versions WHERE document_id=? ORDER BY version_no DESC LIMIT 1",(did,)).fetchone()
                current=con.execute("SELECT original_name FROM documents WHERE id=?",(did,)).fetchone()[0]
            assert version and version[1] == "pismo.txt" and current == "pismo-nowe.txt"
            assert ((Path(tmp) / "dokumenty" / f"sprawa_{first}" / version[0]).read_bytes() == b"pismo glowne")

            edit_html=opener.open(base + f"/document/{did}/edit",timeout=10).read().decode("utf-8")
            assert "Dodaj kolejne załączniki" in edit_html and "zalacznik-a.txt" in edit_html

            confirm_html=opener.open(base + f"/case/{duplicate}/delete",timeout=10).read().decode("utf-8")
            assert "Usuń duplikat sprawy" in confirm_html and "USUŃ" in confirm_html
            delete_data=urllib.parse.urlencode({"confirmation":"USUŃ","acknowledge":"1"}).encode()
            opener.open(urllib.request.Request(base + f"/case/{duplicate}/delete",data=delete_data),timeout=30).read()
            with sqlite3.connect(db_path) as con:
                assert con.execute("SELECT COUNT(*) FROM cases WHERE id=?",(duplicate,)).fetchone()[0] == 0
            snapshots=list((Path(tmp) / "backup_przed_usunieciem_sprawy").glob("*.zip"))
            assert snapshots and snapshots[0].stat().st_size > 0
        finally:
            proc.terminate()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill()
        if proc.returncode not in (0,1,-15):
            raise AssertionError(proc.stderr.read() if proc.stderr else f"Kod serwera: {proc.returncode}")

    print("TEST_CASE_RELATIONS_DOCUMENTS_DEV5: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
