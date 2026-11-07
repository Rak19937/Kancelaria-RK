#!/usr/bin/env python3
"""Check portable package checksums without changing the app or Data."""
from __future__ import annotations
import hashlib
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def verify(folder: Path) -> int:
    manifest = folder / 'SHA256SUMS.txt'
    if not manifest.is_file():
        print('Brak SHA256SUMS.txt; nie mozna potwierdzic integralnosci.')
        return 2
    count = 0
    for n, line in enumerate(manifest.read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        try:
            digest, rel = line.split('  ', 1)
        except ValueError:
            print(f'Nieprawidlowy wiersz {n}')
            return 2
        target = folder / rel
        if not target.is_file() or not target.resolve().is_relative_to(folder.resolve()):
            print(f'Brak pliku lub niedozwolona sciezka: {rel}')
            return 1
        if sha256(target).lower() != digest.lower():
            print(f'BLAD SUMY: {rel}')
            return 1
        count += 1
    if count == 0:
        print('Pusta lista sum SHA-256')
        return 2
    print(f'OK: zweryfikowano {count} plikow paczki.')
    print('UWAGA: suma kontrolna potwierdza integralnosc względem manifestu,')
    print('ale nie tozsamosc wydawcy. Do tego sluzy podpis Authenticode.')
    return 0


if __name__ == '__main__':
    raise SystemExit(verify(Path(sys.argv[1] if len(sys.argv) > 1 else '.')))
