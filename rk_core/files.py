"""Zapis plików przez plik tymczasowy i os.replace."""
from __future__ import annotations
import os
import uuid
from pathlib import Path

def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_name(path.name+f'.tmp_{uuid.uuid4().hex}')
    try:
        with tmp.open('wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        try: tmp.unlink(missing_ok=True)
        except OSError: pass
