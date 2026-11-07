# -*- mode: python ; coding: utf-8 -*-
"""Transparent Windows folder build with version information and no UPX packing."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

base = Path(SPECPATH)
icon = base / 'assets' / 'rk_kancelaria.ico'

# Keep the full folder build; do not hide executable dependencies in a one-file bundle.
datas = [
    (str(base / 'assets'), 'assets'),
    (str(base / 'README_TRUE_PORTABLE.txt'), '.'),
]

for pkg in ('reportlab', 'openpyxl', 'tzdata'):
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
        'rk_smart', 'rk_cloud',
        'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebChannel', 'fitz', 'pypdf', 'openpyxl',
        'cryptography', 'tzdata', 'reportlab',
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='RK KANCELARIA', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    icon=str(icon), version=str(base / 'rk_windows_version.txt'),
    contents_directory='_internal',
)
coll = COLLECT(
    exe, a.binaries, a.datas, strip=False, upx=False,
    upx_exclude=[], name='RK KANCELARIA PORTABLE',
)
