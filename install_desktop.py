# -*- coding: utf-8 -*-
"""RK KANCELARIA 0.2.0-dev2 — instalator komponentów Desktop.

Środowisko .venv jest przechowywane bezpośrednio w folderze programu — tak jak
w działających wydaniach 0.15. Dane są wyznaczane centralnie przez rk_paths.py;
domyślny tryb Installed nadal używa %LOCALAPPDATA%\\RK_KANCELARIA\\Dane.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
import venv
from pathlib import Path

from rk_paths import resolve_runtime_paths

BASE_DIR = Path(__file__).resolve().parent
VENV_DIR = BASE_DIR / '.venv'
RUNTIME_PATHS = resolve_runtime_paths(__file__)
DATA_DIR = RUNTIME_PATHS.data_dir
LOG_PATH = DATA_DIR / 'instalacja_desktop.log'


def log(msg=''):
    line = str(msg)
    print(line, flush=True)
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open('a', encoding='utf-8') as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {line}\n")
    except Exception:
        pass


def run(cmd, timeout=1800):
    cmd = [str(x) for x in cmd]
    log('> ' + ' '.join(f'"{x}"' if ' ' in x else x for x in cmd))
    try:
        # Celowo bez cwd=. Wszystkie ścieżki są absolutne, więc błędny katalog
        # roboczy nie może wywołać WinError 267.
        cp = subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout)
        if cp.stdout:
            for line in cp.stdout.splitlines():
                log(line)
        return cp.returncode
    except Exception as exc:
        log(f'BŁĄD uruchamiania polecenia: {type(exc).__name__}: {exc}')
        log(traceback.format_exc())
        return 99


def venv_python() -> Path:
    return VENV_DIR / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def check_base_python():
    if sys.version_info < (3, 10):
        raise RuntimeError(f'Wymagany jest Python 3.10 lub nowszy. Wykryto: {sys.version.split()[0]}')
    if sys.version_info >= (3, 15):
        raise RuntimeError(f'W tej wersji obsługiwany jest Python 3.10-3.14. Wykryto: {sys.version.split()[0]}')
    if os.name == 'nt' and platform.architecture()[0] != '64bit':
        raise RuntimeError('Tryb Desktop wymaga 64-bitowego Pythona.')


def create_or_repair_venv() -> Path:
    py = venv_python()
    if py.is_file():
        rc = run([py, '--version'], timeout=30)
        if rc == 0:
            return py
        broken = BASE_DIR / ('.venv_uszkodzony_' + time.strftime('%Y%m%d_%H%M%S'))
        log(f'Uszkodzone .venv — przenoszę do: {broken.name}')
        try:
            VENV_DIR.rename(broken)
        except Exception:
            shutil.rmtree(VENV_DIR, ignore_errors=True)
    log(f'Tworzenie lokalnego środowiska: {VENV_DIR}')
    venv.EnvBuilder(with_pip=True, clear=False, symlinks=False).create(str(VENV_DIR))
    if not py.is_file():
        raise RuntimeError(f'Nie udało się utworzyć interpretera: {py}')
    return py


def install_requirements(py: Path):
    reqs = [BASE_DIR/'requirements.txt', BASE_DIR/'requirements_desktop.txt']
    for req in reqs:
        if not req.is_file():
            raise RuntimeError(f'Brak pliku zależności: {req.name}')
    rc = run([py, '-m', 'pip', 'install', '--disable-pip-version-check', '--prefer-binary',
              '-r', reqs[0], '-r', reqs[1]])
    if rc != 0:
        raise RuntimeError(f'Instalacja bibliotek zakończyła się kodem {rc}.')


def verify(py: Path):
    code = ("import sys; import PySide6, fitz, pypdf, cryptography, openpyxl; "
            "from PySide6.QtWebEngineWidgets import QWebEngineView; "
            "print('PYTHON',sys.version.split()[0]); print('PYSIDE6',PySide6.__version__); print('IMPORTY OK')")
    if run([py, '-c', code], timeout=120) != 0:
        raise RuntimeError('Test bibliotek Desktop nie przeszedł.')
    if run([py, BASE_DIR/'desktop.py', '--self-test'], timeout=120) != 0:
        raise RuntimeError('Bezpieczny self-test programu nie przeszedł.')


def main():
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        LOG_PATH.write_text('RK KANCELARIA 0.2.0-dev2 — instalacja Desktop\n', encoding='utf-8')
    except Exception:
        pass
    log('================================================')
    log(' RK KANCELARIA 0.2.0-dev2 — INSTALACJA DESKTOP')
    log('================================================')
    log(f'Python instalatora: {sys.executable}')
    log(f'Wersja Pythona: {sys.version.split()[0]} | {platform.architecture()[0]}')
    log(f'Folder programu: {BASE_DIR}')
    log(f'Lokalne .venv: {VENV_DIR}')
    log(f'Tryb danych: {RUNTIME_PATHS.mode}')
    log(f'Dane użytkownika: {DATA_DIR}')
    try:
        check_base_python()
        py = create_or_repair_venv()
        install_requirements(py)
        verify(py)
        log('')
        log('GOTOWE. Tryb Desktop działa z lokalnego .venv.')
        return 0
    except Exception as exc:
        log('')
        log('INSTALACJA NIE POWIODŁA SIĘ: ' + str(exc))
        log(traceback.format_exc())
        log(f'Log: {LOG_PATH}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
