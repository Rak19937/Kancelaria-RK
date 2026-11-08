# -*- coding: utf-8 -*-
"""SHA256 manifest for full RK snapshots (legacy snapshots remain importable)."""
from __future__ import annotations
import hashlib
import re
import zipfile
from pathlib import Path


def sha256_path(path: Path) -> str:
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_snapshot_manifest(z: zipfile.ZipFile, meta: dict, allow_legacy: bool = False) -> int:
    """Verify all archive members, disallow unexpected/omitted manifest entries.

    Prevent excessive decompression work on untrusted input. ZIP CRC alone is not
    an integrity policy. Returns number of checked members (zero for legacy ZIP).
    """
    members=[info.filename for info in z.infolist() if not info.is_dir()]
    if len(members)!=len(set(members)):
        raise ValueError('Snapshot zawiera zduplikowane nazwy plików')
    expected=set(members)-{'snapshot.json'}
    manifest=meta.get('file_sha256')
    if manifest is None:
        if allow_legacy:
            return 0
        raise ValueError('Snapshot nie zawiera manifestu sum kontrolnych SHA-256')
    if not isinstance(manifest,dict) or set(manifest)!=expected:
        raise ValueError('Niekompletny manifest SHA-256 w snapshot')
    if len(expected)>25000:
        raise ValueError('Zbyt wiele plików w snapshot')
    total=0
    for info in z.infolist():
        if info.is_dir():continue
        if info.file_size<0 or info.file_size>1024*1024*1024:
            raise ValueError('Plik snapshot przekracza limit 1 GB')
        total+=info.file_size
        if total>2*1024*1024*1024:
            raise ValueError('Snapshot po rozpakowaniu przekracza limit 2 GB')
    for name in sorted(expected):
        expected_hash=manifest[name]
        if not isinstance(expected_hash,str) or not re.fullmatch(r'[0-9a-f]{64}',expected_hash):
            raise ValueError('Niepoprawna suma kontrolna SHA-256 w snapshot')
        digest=hashlib.sha256()
        with z.open(name,'r') as source:
            for chunk in iter(lambda:source.read(1024*1024),b''):
                digest.update(chunk)
        if digest.hexdigest()!=expected_hash:
            raise ValueError('Niezgodna suma kontrolna pliku w snapshot: '+name[:150])
    return len(expected)
