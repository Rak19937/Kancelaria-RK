# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

base = Path(SPECPATH)
icon = base / 'assets' / 'rk_kancelaria.ico'

datas = [
    (str(base / 'assets'), 'assets'),
    (str(base / 'README_TRUE_PORTABLE.txt'), '.'),
]

# Dodatkowe dane bibliotek, które bywają ładowane dynamicznie.
for pkg in ('reportlab', 'openpyxl'):
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass

a = Analysis(
    [str(base / 'RK_KANCELARIA_DESKTOP.pyw')],
    pathex=[str(base)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'rk_smart',
        'rk_cloud',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebChannel',
        'fitz',
        'pypdf',
        'openpyxl',
        'cryptography',
        'reportlab',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RK KANCELARIA',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(icon),
    contents_directory='_internal',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='RK KANCELARIA PORTABLE',
)
