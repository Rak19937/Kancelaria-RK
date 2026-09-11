# -*- coding: utf-8 -*-
"""Klient RK KANCELARIA Cloud Bridge.

Synchronizacja DEV8 jest celowo wersjonowana i konfliktowa: zdalny snapshot ma numer
wersji, a wysyłka wymaga zgodności z numerem widzianym przez klienta. Dzięki temu
równoległa praca na dwóch urządzeniach nie może cicho nadpisać nowszych danych.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


class CloudError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class CloudMeta:
    office_id: str
    version: int
    sha256: str = ''
    updated_at: str = ''
    size: int = 0
    exists: bool = False


def _base(url: str) -> str:
    value=(url or '').strip().rstrip('/')
    if not value:
        raise CloudError('Nie skonfigurowano adresu serwera Cloud.')
    parsed=urllib.parse.urlparse(value)
    if parsed.scheme not in {'http','https'} or not parsed.netloc:
        raise CloudError('Adres Cloud musi zaczynać się od http:// lub https://.')
    return value


def _headers(token: str, extra: dict[str,str] | None=None) -> dict[str,str]:
    h={'User-Agent':'RK-KANCELARIA-DEV8','Accept':'application/json'}
    if token:
        h['Authorization']='Bearer '+token
    if extra: h.update(extra)
    return h


def _request(req: urllib.request.Request, timeout: int=45) -> tuple[bytes,dict[str,str],int]:
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:
            return r.read(),dict(r.headers.items()),int(r.status)
    except urllib.error.HTTPError as exc:
        raw=exc.read()
        try:
            obj=json.loads(raw.decode('utf-8','replace')); msg=obj.get('error') or obj.get('message') or str(exc)
        except Exception:
            msg=raw.decode('utf-8','replace').strip() or str(exc)
        raise CloudError(msg,int(exc.code)) from exc
    except urllib.error.URLError as exc:
        raise CloudError(f'Brak połączenia z serwerem Cloud: {exc.reason}') from exc


def health(url: str, token: str='') -> dict:
    req=urllib.request.Request(_base(url)+'/health',headers=_headers(token))
    raw,_,_=_request(req,15)
    try: return json.loads(raw.decode('utf-8'))
    except Exception: return {'ok':True,'raw':raw.decode('utf-8','replace')}


def get_meta(url: str, office_id: str, token: str) -> CloudMeta:
    oid=urllib.parse.quote((office_id or 'default').strip(),safe='')
    req=urllib.request.Request(f'{_base(url)}/api/v1/offices/{oid}/meta',headers=_headers(token))
    try:
        raw,_,_=_request(req,20)
    except CloudError as exc:
        if exc.status==404:
            return CloudMeta(office_id=office_id or 'default',version=0,exists=False)
        raise
    obj=json.loads(raw.decode('utf-8'))
    return CloudMeta(
        office_id=str(obj.get('office_id') or office_id or 'default'),
        version=int(obj.get('version') or 0),
        sha256=str(obj.get('sha256') or ''),
        updated_at=str(obj.get('updated_at') or ''),
        size=int(obj.get('size') or 0),
        exists=bool(obj.get('exists',True)),
    )


def push_snapshot(url: str, office_id: str, token: str, payload: bytes, base_version: int) -> CloudMeta:
    oid=urllib.parse.quote((office_id or 'default').strip(),safe='')
    req=urllib.request.Request(
        f'{_base(url)}/api/v1/offices/{oid}/snapshot',data=payload,method='PUT',
        headers=_headers(token,{
            'Content-Type':'application/zip',
            'Content-Length':str(len(payload)),
            'X-RK-Base-Version':str(int(base_version)),
        })
    )
    raw,_,_=_request(req,180)
    obj=json.loads(raw.decode('utf-8'))
    return CloudMeta(
        office_id=str(obj.get('office_id') or office_id), version=int(obj.get('version') or 0),
        sha256=str(obj.get('sha256') or ''), updated_at=str(obj.get('updated_at') or ''),
        size=int(obj.get('size') or len(payload)), exists=True,
    )


def pull_snapshot(url: str, office_id: str, token: str) -> tuple[bytes,CloudMeta]:
    oid=urllib.parse.quote((office_id or 'default').strip(),safe='')
    req=urllib.request.Request(f'{_base(url)}/api/v1/offices/{oid}/snapshot',headers=_headers(token,{'Accept':'application/zip'}))
    raw,headers,_=_request(req,180)
    return raw,CloudMeta(
        office_id=office_id or 'default', version=int(headers.get('X-RK-Version','0') or 0),
        sha256=headers.get('X-RK-SHA256',''), updated_at=headers.get('X-RK-Updated-At',''),
        size=len(raw), exists=True,
    )
