#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP E2E: setup, CSRF rejection, async upload, review and access control."""
from __future__ import annotations
import http.cookiejar
import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def request(opener,url,data=None,headers=None):
    req=urllib.request.Request(url,data=data,headers=headers or {})
    try:
        with opener.open(req,timeout=15) as response:
            return response.status,response.read().decode('utf-8','replace'),response.geturl()
    except urllib.error.HTTPError as exc:
        return exc.code,exc.read().decode('utf-8','replace'),exc.geturl()


def upload_bytes(token):
    boundary='rk-inbox-boundary-040dev2'
    payload=(f'--{boundary}\r\nContent-Disposition: form-data; name="_rk_csrf"\r\n\r\n{token}\r\n'
             f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="test-legal.txt"\r\n'
             'Content-Type: text/plain; charset=utf-8\r\n\r\n'
             'Sygn. I C 123/26. Sąd zobowiązuje stronę do złożenia stanowiska w terminie 14 dni.\r\n'
             f'--{boundary}--\r\n').encode('utf-8')
    return payload,f'multipart/form-data; boundary={boundary}'


def main():
    with tempfile.TemporaryDirectory(prefix='rk_dev2_e2e_') as tmp:
        with socket.socket() as sk:
            sk.bind(('127.0.0.1',0));port=sk.getsockname()[1]
        env=os.environ.copy()
        env.update({'SPRAWNIK_DATA_DIR':tmp,'SPRAWNIK_PORT':str(port),
                    'SPRAWNIK_HOST':'127.0.0.1','SPRAWNIK_OPEN_BROWSER':'0',
                    'SPRAWNIK_AUTO_SHUTDOWN':'0','RK_KANCELARIA_SEED_DEMO':'0'})
        proc=subprocess.Popen([sys.executable,str(ROOT/'app.py')],cwd=ROOT,env=env,
                              stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
        try:
            base=f'http://127.0.0.1:{port}'
            jar=http.cookiejar.CookieJar()
            opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            for _ in range(80):
                try:
                    code,_,_=request(opener,base+'/setup')
                    if code==200:break
                except (OSError,TimeoutError):pass
                if proc.poll() is not None:
                    raise AssertionError('Serwer zakończył się przed uruchomieniem: '+proc.stderr.read()[-3000:])
                time.sleep(.15)
            else:raise AssertionError('Serwer testowy nie uruchomił się.')
            setup=urllib.parse.urlencode({'username':'testadmin','author_name':'Tester',
                'password':'testowy123456','password2':'testowy123456','function':'test'}).encode()
            code,_,_=request(opener,base+'/setup',setup)
            assert code==200, ('setup',code)
            code,html,_=request(opener,base+'/inbox')
            assert code==200,('inbox',code,html[:400])
            match=re.search(r'<meta name="rk-csrf-token" content="([a-f0-9]{64})">',html)
            assert match, 'Missing CSRF meta token in authenticated HTML.'
            token=match.group(1)
            assert 'name="_rk_csrf"' in html
            code,_,_=request(opener,base+'/inbox/upload',urllib.parse.urlencode({}).encode())
            assert code==403, 'POST without CSRF should be rejected.'
            code,_,_=request(opener,base+'/inbox/upload',urllib.parse.urlencode({'_rk_csrf':token}).encode(),
                             {'Origin':'https://evil.example'})
            assert code==403, 'Cross-origin POST should be rejected.'
            raw,ctype=upload_bytes(token)
            code,html,landed=request(opener,base+'/inbox/upload',raw,
                {'Content-Type':ctype,'Origin':base})
            assert code==200 and '/inbox/' in landed,('upload',code,landed,html[:500])
            for _ in range(40):
                code,html,_=request(opener,landed)
                assert code==200,('review',code,html[:800])
                if "name='verified'" in html:break
                time.sleep(.2)
            else:raise AssertionError('Asynchroniczny OCR nie otworzył weryfikacji (40 prób).')
            with sqlite3.connect(Path(tmp)/'sprawnik.sqlite3') as con:
                state=con.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
                assert state==0,'Dodano dokument bez ręcznego zatwierdzenia!'
                proposals=con.execute('SELECT suggestions_json FROM inbox_items LIMIT 1').fetchone()[0]
                assert '14 dni' in proposals,proposals[:600]
            # Role checks: standard user may view the app, but cannot download
            # raw SQLite or change a closed case security lock.
            make_user=urllib.parse.urlencode({'username':'testuser','author_name':'User',
                'password':'testpass123456','role':'user','_rk_csrf':token}).encode()
            code,_,_=request(opener,base+'/admin/user/create',make_user,{'Origin':base})
            assert code==200,('create user',code)
            other=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            login=urllib.parse.urlencode({'username':'testuser','password':'testpass123456'}).encode()
            code,_,_=request(other,base+'/login',login,{'Origin':base})
            assert code==200,('login user',code)
            code,_,_=request(other,base+'/backup')
            assert code==403,'Zwykły użytkownik uzyskał dostęp do surowej bazy danych!'
            code,user_html,_=request(other,base+'/inbox')
            assert code==200
            u_token=re.search(r'<meta name="rk-csrf-token" content="([a-f0-9]{64})">',user_html).group(1)
            code,_,_=request(other,base+'/case/1/unlock',urllib.parse.urlencode({'_rk_csrf':u_token}).encode(),{'Origin':base})
            assert code==403,'Zwykły użytkownik odblokował sprawę!'
            print('TEST_UI_HTTP_040_DEV2: OK (HTTP setup, CSRF, OCR, role permissions, manual review)')
        finally:
            proc.terminate()
            try:proc.wait(timeout=8)
            except subprocess.TimeoutExpired:proc.kill()

if __name__=='__main__':main()
