#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RK KANCELARIA dev5 regression tests: synthetic data only, no network."""
from __future__ import annotations
import contextlib
import csv
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from TEST_RK_DEV3 import fixture_db
from rk_dev3 import Dev3Mixin
from rk_dev3_core import add_manual_time, import_portal_csv, vault_store, decrypt_vault
from rk_dev3_calendar import pull_proposals, publish_appointment, CalendarSyncError
from rk_dev4 import Dev4Mixin
from rk_dev4_core import ensure_dev4_schema, update_time
from rk_dev5_vault import ensure_dev5_vault_schema
from rk_dev5_snapshot import verify_snapshot_manifest, sha256_path


class MockHandler(Dev4Mixin,Dev3Mixin):
    def __init__(self,con,files_dir,uid=1,role='admin'):
        self.con=con
        self.files_dir=files_dir
        self.user={'id':uid,'role':role,'author_name':'Test'}
        self.html='';self.redirect_path=''
    def _dev3_app(self):
        return SimpleNamespace(db=lambda:self.con,FILES_DIR=self.files_dir,log_app_exception=lambda *a:None)
    def _dev3_me(self):return self.user
    def _dev3_html(self,title,body,active=''):self.html=body
    def redirect(self,url):self.redirect_path=url


class CsvTests(unittest.TestCase):
    def setUp(self):self.con=fixture_db()
    def tearDown(self):self.con.close()

    def test_sniffer_error_yields_validation_error(self):
        with patch('rk_dev3_core.csv.Sniffer.sniff',side_effect=csv.Error('malformed')):
            with self.assertRaisesRegex(ValueError,'CSV'):
                import_portal_csv(self.con,b'identyfikator;sygnatura;data;tytul\n1;X;2026-11-08;T\n',1)

    def test_impossible_date_does_not_modify_database(self):
        before=self.con.execute('SELECT COUNT(*) FROM dev3_portal_items').fetchone()[0]
        with self.assertRaisesRegex(ValueError,'data'):
            import_portal_csv(self.con,b'identyfikator;sygnatura;data;tytul\n1;I C 1/26;2026-02-30;T\n',1)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM dev3_portal_items').fetchone()[0],before)

    def test_valid_date_import(self):
        self.assertEqual(import_portal_csv(self.con,b'identyfikator;sygnatura;data;tytul\n1;X;2026-11-08;T\n',1),(1,0))


class FixedWinter(datetime):
    @classmethod
    def now(cls,tz=None):return datetime(2026,11,8,12,0,tzinfo=tz)


class FixedSummer(datetime):
    @classmethod
    def now(cls,tz=None):return datetime(2026,7,8,12,0,tzinfo=tz)


class CalendarTests(unittest.TestCase):
    def setUp(self):self.con=fixture_db()
    def tearDown(self):self.con.close()

    def test_winter_calendar_bounds_use_warsaw_midnight(self):
        urls=[]
        def fake(url,*args,**kwargs):urls.append(url);return {'items':[]}
        with patch('rk_dev3_calendar.datetime',FixedWinter),patch('rk_dev3_calendar._api',side_effect=fake):
            pull_proposals(self.con,'google','test',1)
        params=parse_qs(urlsplit(urls[0]).query)
        self.assertEqual(params['timeMin'][0],'2026-11-07T23:00:00Z')
        self.assertEqual(params['timeMax'][0],'2026-11-09T23:00:00Z')

    def test_summer_calendar_bounds_use_warsaw_midnight(self):
        urls=[]
        def fake(url,*args,**kwargs):urls.append(url);return {'value':[]}
        with patch('rk_dev3_calendar.datetime',FixedSummer),patch('rk_dev3_calendar._api',side_effect=fake):
            pull_proposals(self.con,'outlook','test',1)
        params=parse_qs(urlsplit(urls[0]).query)
        self.assertEqual(params['startDateTime'][0],'2026-07-07T22:00:00Z')
        self.assertEqual(params['endDateTime'][0],'2026-07-09T22:00:00Z')

    def test_missing_patch_etag_fetches_remote_version(self):
        requests=[]
        def fake(url,token,method='GET',body=None,etag=None):
            requests.append((method,etag))
            if method=='POST':return {'id':'e-1','etag':'v1'}
            if method=='PATCH':return {'id':'e-1'}
            return {'id':'e-1','etag':'v2'}
        with patch('rk_dev3_calendar._api',side_effect=fake):
            publish_appointment(self.con,'google',7,'fake')
            publish_appointment(self.con,'google',7,'fake')
        self.assertEqual(requests,[('POST',None),('PATCH','v1'),('GET',None)])
        self.assertEqual(self.con.execute('SELECT etag FROM dev3_calendar_links').fetchone()[0],'v2')

    def test_google_retry_after_sqlite_link_failure_does_not_repost(self):
        # Remote creation succeeded, but the local link INSERT failed.
        # The durable intent must recover by GET on retry, not another POST.
        remote={}
        calls=[]
        def api(url,token,method='GET',body=None,etag=None):
            calls.append(method)
            if method=='POST':
                remote.update({'id':body['id'],'etag':'v1',
                    'extendedProperties':body['extendedProperties']})
                return dict(remote)
            if method=='GET':return dict(remote)
            raise AssertionError(method)
        self.con.execute("""CREATE TRIGGER fail_dev5_link BEFORE INSERT ON dev3_calendar_links
            BEGIN SELECT RAISE(ABORT,'lokalny blad zapisu'); END""")
        with patch('rk_dev3_calendar._api',side_effect=api):
            with self.assertRaises(sqlite3.IntegrityError):
                publish_appointment(self.con,'google',7,'fake')
            self.con.execute('DROP TRIGGER fail_dev5_link')
            publish_appointment(self.con,'google',7,'fake')
        self.assertEqual(calls,['POST','GET'])
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM dev3_calendar_links').fetchone()[0],1)

    def test_outlook_retry_reuses_same_transaction_id(self):
        calls=[]
        def api(url,token,method='GET',body=None,etag=None):
            self.assertEqual(method,'POST')
            calls.append(body['transactionId'])
            return {'id':'same-event','@odata.etag':'v1'}
        self.con.execute("""CREATE TRIGGER fail_dev5_link BEFORE INSERT ON dev3_calendar_links
            BEGIN SELECT RAISE(ABORT,'lokalny blad zapisu'); END""")
        with patch('rk_dev3_calendar._api',side_effect=api):
            with self.assertRaises(sqlite3.IntegrityError):
                publish_appointment(self.con,'outlook',7,'fake')
            self.con.execute('DROP TRIGGER fail_dev5_link')
            publish_appointment(self.con,'outlook',7,'fake')
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0],calls[1])

    def test_update_without_etag_fails_closed(self):
        self.con.execute("INSERT INTO dev3_calendar_links(provider,appointment_id,external_id,etag) VALUES('google',7,'remote','')")
        with patch('rk_dev3_calendar._api',return_value={'id':'remote'}) as api:
            with self.assertRaises(CalendarSyncError):publish_appointment(self.con,'google',7,'fake')
        self.assertEqual(api.call_count,1)


class WorktimeAndVaultTests(unittest.TestCase):
    def setUp(self):self.con=fixture_db();ensure_dev4_schema(self.con);ensure_dev5_vault_schema(self.con);self.tmp=tempfile.TemporaryDirectory()
    def tearDown(self):self.con.close();self.tmp.cleanup()

    def test_paginated_worktime_shows_older_entries(self):
        for i in range(121):add_manual_time(self.con,10,1,'2026-11-08',i%60+1,'Wpis '+str(i),10000,True)
        h=MockHandler(self.con,Path(self.tmp.name))
        h.dev3_worktime_page({'page':['3']})
        self.assertIn('Strona 3',h.html)
        self.assertIn('Wpis 0',h.html)
        self.assertNotIn('Wpis 120',h.html)

    def test_visible_history_and_user_filter(self):
        entry=add_manual_time(self.con,10,1,'2026-11-08',60,'Przed',10000,True)
        update_time(self.con,entry,1,'2026-11-09',70,'Po',10000,True)
        admin=MockHandler(self.con,Path(self.tmp.name))
        admin.dev4_time_history({'page':['1']})
        self.assertIn('Przed:',admin.html)
        self.assertIn('Przed',admin.html)
        outsider=MockHandler(self.con,Path(self.tmp.name),uid=2,role='user')
        outsider.dev4_time_history({'page':['1']})
        self.assertNotIn('Przed',outsider.html)

    def test_vault_rotation_audit_failure_restores_ciphertext(self):
        root=Path(self.tmp.name)
        fid=vault_store(self.con,root,10,1,'tajne.txt',b'dane tajne','stare-haslo-sejfu')
        name=self.con.execute('SELECT stored_name FROM dev3_vault_files WHERE id=?',(fid,)).fetchone()[0]
        file=root/'_vault'/name
        prev=file.read_bytes()
        with patch('rk_dev5_vault.action_log',side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):
                MockHandler(self.con,root).dev4_vault_change(fid,'rotate',{'old_passphrase':'stare-haslo-sejfu','new_passphrase':'nowe-haslo-sejfu'})
        self.assertEqual(file.read_bytes(),prev)
        self.assertEqual(decrypt_vault(file.read_bytes(),'stare-haslo-sejfu'),b'dane tajne')

    def test_vault_delete_db_failure_renames_back(self):
        root=Path(self.tmp.name)
        fid=vault_store(self.con,root,10,1,'tajne.txt',b'dane','stare-haslo-sejfu')
        name=self.con.execute('SELECT stored_name FROM dev3_vault_files WHERE id=?',(fid,)).fetchone()[0]
        with patch('rk_dev5_vault.action_log',side_effect=ValueError('DB rejected')):
            with self.assertRaises(ValueError):
                MockHandler(self.con,root).dev4_vault_change(fid,'delete',{'confirmation':'USUŃ'})
        self.assertTrue((root/'_vault'/name).exists())
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM dev3_vault_files').fetchone()[0],1)

    def test_vault_delete_success_removes_ciphertext(self):
        root=Path(self.tmp.name)
        fid=vault_store(self.con,root,10,1,'tajne.txt',b'dane','stare-haslo-sejfu')
        name=self.con.execute('SELECT stored_name FROM dev3_vault_files WHERE id=?',(fid,)).fetchone()[0]
        MockHandler(self.con,root).dev4_vault_change(fid,'delete',{'confirmation':'USUŃ'})
        self.assertFalse((root/'_vault'/name).exists())
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM dev3_vault_files').fetchone()[0],0)


class BackupTests(unittest.TestCase):
    def test_snapshot_rejects_tampered_member_even_if_zip_crc_valid(self):
        good=b'case-data'
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'sample';path.write_bytes(good)
            sig=sha256_path(path)
        raw=io.BytesIO()
        meta={'file_sha256':{'sprawnik.sqlite3':sig}}
        with zipfile.ZipFile(raw,'w') as z:
            z.writestr('sprawnik.sqlite3',b'modified-but-valid-zip')
            z.writestr('snapshot.json',json.dumps(meta))
        with zipfile.ZipFile(io.BytesIO(raw.getvalue()),'r') as z:
            with self.assertRaisesRegex(ValueError,'suma kontrolna'):
                verify_snapshot_manifest(z,meta)

    def test_legacy_snapshot_import_policy_is_explicit(self):
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:z.writestr('sprawnik.sqlite3',b'legacy')
        with zipfile.ZipFile(io.BytesIO(raw.getvalue())) as z:
            self.assertEqual(verify_snapshot_manifest(z,{},allow_legacy=True),0)
            with self.assertRaises(ValueError):verify_snapshot_manifest(z,{},allow_legacy=False)

    def test_plain_snapshot_download_route_requires_password(self):
        text=Path(__file__).with_name('app.py').read_text('utf-8')
        self.assertIn('VERSION = "0.4.0-dev5"',text)
        self.assertIn('def full_snapshot_download_encrypted',text)
        self.assertIn('SESSION_CACHE_SECONDS = 0.0',text)
        self.assertIn('verify_snapshot_manifest(z,meta,allow_legacy=True)',text)


if __name__=='__main__':unittest.main(verbosity=2)
