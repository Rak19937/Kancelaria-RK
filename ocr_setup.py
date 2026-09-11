# -*- coding: utf-8 -*-
"""Instalator/diagnostyka OCR dla RK KANCELARIA.

Windows: instaluje Tesseract 5 przez Windows Package Manager (winget), a modele
polski/angielski trzyma w katalogu danych RK KANCELARIA, dzięki czemu aplikacja
nie zależy od konfiguracji PATH ani od języków zaznaczonych w instalatorze.
"""
from __future__ import annotations
import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import app

MODEL_URLS = {
    'pol': 'https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/pol.traineddata',
    'eng': 'https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata',
}


def print_line(msg=''):
    print(msg, flush=True)


def run(cmd, timeout=900):
    print_line('> ' + ' '.join(str(x) for x in cmd))
    return subprocess.run(cmd, timeout=timeout, check=False)


def install_engine_windows() -> bool:
    if app.find_tesseract():
        return True
    winget = shutil.which('winget')
    if not winget:
        print_line('BŁĄD: nie znaleziono winget (Windows Package Manager).')
        print_line('Zaktualizuj "Instalator aplikacji" z Microsoft Store lub zainstaluj Tesseract ręcznie.')
        return False
    packages = ['tesseract-ocr.tesseract', 'UB-Mannheim.TesseractOCR']
    for package in packages:
        print_line(f'Instalowanie silnika OCR: {package} ...')
        cp = run([
            winget, 'install', '--id', package, '--exact', '--silent',
            '--accept-package-agreements', '--accept-source-agreements',
            '--disable-interactivity'
        ])
        if cp.returncode == 0 and app.find_tesseract():
            return True
        # winget może zwrócić niezerowy kod, gdy pakiet już istnieje; sprawdź ścieżki ponownie
        if app.find_tesseract():
            return True
    return bool(app.find_tesseract())


def copy_existing_model(lang: str, dest: Path) -> bool:
    bundled=app.BASE_DIR/'assets'/'ocr'/'tessdata'/f'{lang}.traineddata'
    try:
        if bundled.is_file() and bundled.stat().st_size > 100000:
            shutil.copy2(bundled,dest)
            print_line(f'Model {lang}: skopiowany z paczki RK KANCELARIA.')
            return True
    except OSError:
        pass
    cmd = app.find_tesseract()
    candidates=[]
    if cmd:
        tdir=Path(cmd).parent/'tessdata'
        candidates.append(tdir/f'{lang}.traineddata')
    for root in [Path(os.getenv('PROGRAMFILES','C:/Program Files'))/'Tesseract-OCR'/'tessdata',
                 Path(os.getenv('PROGRAMFILES(X86)','C:/Program Files (x86)'))/'Tesseract-OCR'/'tessdata']:
        candidates.append(root/f'{lang}.traineddata')
    for src in candidates:
        try:
            if src.is_file() and src.stat().st_size > 100000:
                shutil.copy2(src,dest)
                return True
        except OSError:
            pass
    return False


def download_model(lang: str) -> bool:
    app.OCR_TESSDATA_DIR.mkdir(parents=True,exist_ok=True)
    dest=app.OCR_TESSDATA_DIR/f'{lang}.traineddata'
    if dest.is_file() and dest.stat().st_size > 100000:
        return True
    if copy_existing_model(lang,dest):
        return True
    url=MODEL_URLS[lang]
    tmp=dest.with_suffix('.download')
    print_line(f'Pobieranie modelu OCR {lang} ...')
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'RK-KANCELARIA/0.13.1'})
        with urllib.request.urlopen(req,timeout=60) as src, tmp.open('wb') as out:
            while True:
                chunk=src.read(1024*1024)
                if not chunk: break
                out.write(chunk)
        if tmp.stat().st_size < 100000:
            raise RuntimeError('pobrany plik jest zbyt mały')
        os.replace(tmp,dest)
        return True
    except Exception as exc:
        print_line(f'BŁĄD pobierania modelu {lang}: {exc}')
        try: tmp.unlink(missing_ok=True)
        except Exception: pass
        return False


def install_python_components() -> bool:
    # PyMuPDF jest potrzebny do renderowania stron PDF na potrzeby OCR/podglądu.
    mods=[]
    try: import fitz  # noqa
    except Exception: mods.append('pymupdf>=1.24,<2')
    try: import pypdf  # noqa
    except Exception: mods.append('pypdf>=5,<7')
    if not mods: return True
    print_line('Instalowanie komponentów Python OCR/PDF ...')
    cp=run([sys.executable,'-m','pip','install','--disable-pip-version-check',*mods])
    return cp.returncode==0


def check() -> int:
    cmd=app.find_tesseract()
    print_line('=== RK KANCELARIA — DIAGNOSTYKA OCR ===')
    print_line(f'Tesseract: {cmd or "BRAK"}')
    if cmd:
        try:
            cp=subprocess.run([cmd,'--version'],capture_output=True,text=True,timeout=10)
            first=(cp.stdout or cp.stderr or '').splitlines()[:1]
            if first: print_line('Wersja: '+first[0])
        except Exception as exc: print_line(f'Błąd uruchomienia: {exc}')
        print_line('Języki widoczne przez RK: '+', '.join(sorted(app.tesseract_languages(cmd))) )
    for lang in ('pol','eng'):
        p=app.OCR_TESSDATA_DIR/f'{lang}.traineddata'
        print_line(f'Model {lang}: {"OK" if p.is_file() and p.stat().st_size>100000 else "BRAK"} ({p})')
    try:
        import fitz
        print_line('PyMuPDF: OK')
    except Exception:
        print_line('PyMuPDF: BRAK')
    ok=bool(cmd) and all((app.OCR_TESSDATA_DIR/f'{x}.traineddata').is_file() for x in ('pol','eng'))
    print_line('STATUS: '+('OCR GOTOWY' if ok else 'OCR WYMAGA INSTALACJI/NAPRAWY'))
    return 0 if ok else 2


def install() -> int:
    print_line('=== RK KANCELARIA — INSTALACJA PEŁNEGO OCR ===')
    app.OCR_TESSDATA_DIR.mkdir(parents=True,exist_ok=True)
    pyok=install_python_components()
    if os.name=='nt': engine=install_engine_windows()
    else:
        engine=bool(app.find_tesseract())
        if not engine:
            print_line('Na Linux/macOS zainstaluj pakiet tesseract-ocr z systemowego managera pakietów.')
    models=all(download_model(x) for x in ('pol','eng'))
    print_line('')
    rc=check()
    if pyok and engine and models and rc==0:
        print_line('\nOCR został poprawnie zainstalowany. W RK KANCELARIA uruchom „Przebuduj indeks + OCR” dla już istniejących skanów.')
        return 0
    print_line('\nNie wszystkie składniki udało się zainstalować. Sprawdź komunikaty powyżej.')
    return 1


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--check',action='store_true')
    ap.add_argument('--interactive',action='store_true')
    args=ap.parse_args()
    rc=check() if args.check else install()
    if args.interactive:
        try: input('\nNaciśnij Enter, aby zamknąć to okno...')
        except EOFError: pass
    return rc

if __name__=='__main__':
    raise SystemExit(main())
