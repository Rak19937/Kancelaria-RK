# -*- coding: utf-8 -*-
"""RK KANCELARIA 0.15.0 - tworzenie skrótu Windows do wersji Desktop.

Najpierw tworzy poprawny plik RK KANCELARIA.lnk w katalogu aplikacji.
Następnie próbuje skopiować go na Pulpit. Jeśli Windows zwróci Access Denied
(np. Controlled Folder Access / OneDrive), pozostawia gotowy skrót w katalogu
aplikacji i otwiera ten katalog, aby użytkownik mógł przeciągnąć skrót ręcznie.
"""
import ctypes
import os
import shutil
import subprocess
import sys
import uuid
from ctypes import wintypes

if os.name != "nt":
    print("Ten skrypt działa tylko w Windows.")
    raise SystemExit(1)

HRESULT = ctypes.c_long
ULONG = ctypes.c_ulong
LPVOID = ctypes.c_void_p
CLSCTX_INPROC_SERVER = 0x1
SW_SHOWNORMAL = 1

class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def guid(value: str) -> GUID:
    u = uuid.UUID(value)
    g = GUID()
    g.Data1 = u.time_low
    g.Data2 = u.time_mid
    g.Data3 = u.time_hi_version
    for i, b in enumerate(u.bytes[8:]):
        g.Data4[i] = b
    return g


def failed(hr):
    return hr < 0


def check(hr, what):
    if failed(hr):
        raise OSError(f"{what} nie powiodło się (HRESULT 0x{hr & 0xffffffff:08X})")


ole32 = ctypes.OleDLL("ole32")
shell32 = ctypes.WinDLL("shell32")
ole32.CoInitialize.argtypes = [LPVOID]
ole32.CoInitialize.restype = HRESULT
ole32.CoUninitialize.argtypes = []
ole32.CoUninitialize.restype = None
ole32.CoCreateInstance.argtypes = [
    ctypes.POINTER(GUID), LPVOID, wintypes.DWORD,
    ctypes.POINTER(GUID), ctypes.POINTER(LPVOID)
]
ole32.CoCreateInstance.restype = HRESULT
ole32.CoTaskMemFree.argtypes = [LPVOID]
ole32.CoTaskMemFree.restype = None
shell32.SHGetKnownFolderPath.argtypes = [
    ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
    ctypes.POINTER(ctypes.c_wchar_p)
]
shell32.SHGetKnownFolderPath.restype = HRESULT

CLSID_ShellLink = guid("00021401-0000-0000-C000-000000000046")
IID_IShellLinkW = guid("000214F9-0000-0000-C000-000000000046")
IID_IPersistFile = guid("0000010B-0000-0000-C000-000000000046")
FOLDERID_Desktop = guid("B4BFCC3A-DB2C-424C-B029-7FE99A87C641")


def method(obj, index, restype, *argtypes):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(LPVOID))).contents
    fn_addr = vtbl[index]
    prototype = ctypes.WINFUNCTYPE(restype, LPVOID, *argtypes)
    return prototype(fn_addr)


def release(obj):
    if obj:
        method(obj, 2, ULONG)(obj)


def desktop_path():
    p = ctypes.c_wchar_p()
    hr = shell32.SHGetKnownFolderPath(ctypes.byref(FOLDERID_Desktop), 0, None, ctypes.byref(p))
    check(hr, "Wykrycie folderu Pulpit")
    try:
        return p.value
    finally:
        ole32.CoTaskMemFree(ctypes.cast(p, LPVOID))


def create_shortcut_at(shortcut_path: str) -> str:
    base = os.path.dirname(os.path.abspath(__file__))
    launcher = os.path.join(base, "RK_KANCELARIA_DESKTOP.pyw")
    icon = os.path.join(base, "assets", "rk_kancelaria.ico")

    if not os.path.isfile(launcher):
        raise FileNotFoundError(f"Brak launchera Desktop: {launcher}")
    if not os.path.isfile(icon):
        raise FileNotFoundError(f"Brak ikonki: {icon}")

    # Skrót uruchamia pythonw.exe bez cmd.exe, więc po kliknięciu nie pojawia się
    # konsola. PySide6 tworzy normalne okno RK KANCELARIA.
    python_exe = os.path.abspath(sys.executable)
    candidate = os.path.join(os.path.dirname(python_exe), "pythonw.exe")
    cmd = candidate if os.path.isfile(candidate) else python_exe
    arguments = f'"{launcher}"'

    shell_link = LPVOID()
    persist = LPVOID()
    hr_init = ole32.CoInitialize(None)
    if failed(hr_init) and (hr_init & 0xffffffff) != 0x80010106:  # RPC_E_CHANGED_MODE
        check(hr_init, "CoInitialize")
    try:
        check(
            ole32.CoCreateInstance(
                ctypes.byref(CLSID_ShellLink), None, CLSCTX_INPROC_SERVER,
                ctypes.byref(IID_IShellLinkW), ctypes.byref(shell_link)
            ),
            "Utworzenie obiektu skrótu",
        )
        check(method(shell_link, 20, HRESULT, wintypes.LPCWSTR)(shell_link, cmd), "Ustawienie programu docelowego")
        check(method(shell_link, 11, HRESULT, wintypes.LPCWSTR)(shell_link, arguments), "Ustawienie argumentów")
        check(method(shell_link, 9, HRESULT, wintypes.LPCWSTR)(shell_link, base), "Ustawienie katalogu roboczego")
        check(method(shell_link, 7, HRESULT, wintypes.LPCWSTR)(shell_link, "RK KANCELARIA"), "Ustawienie opisu")
        check(method(shell_link, 15, HRESULT, ctypes.c_int)(shell_link, SW_SHOWNORMAL), "Ustawienie trybu okna")
        check(method(shell_link, 17, HRESULT, wintypes.LPCWSTR, ctypes.c_int)(shell_link, icon, 0), "Ustawienie ikonki")

        qi = method(shell_link, 0, HRESULT, ctypes.POINTER(GUID), ctypes.POINTER(LPVOID))
        check(qi(shell_link, ctypes.byref(IID_IPersistFile), ctypes.byref(persist)), "Uzyskanie IPersistFile")
        save = method(persist, 6, HRESULT, wintypes.LPCWSTR, wintypes.BOOL)
        check(save(persist, shortcut_path, True), "Zapis skrótu")

        if not os.path.isfile(shortcut_path):
            raise OSError(f"Windows nie utworzył pliku: {shortcut_path}")
        return shortcut_path
    finally:
        release(persist)
        release(shell_link)
        if not failed(hr_init):
            ole32.CoUninitialize()


def open_folder_select(path: str):
    try:
        subprocess.Popen(["explorer.exe", f'/select,"{path}"'])
    except Exception:
        try:
            os.startfile(os.path.dirname(path))
        except Exception:
            pass


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    local_shortcut = os.path.join(base, "RK KANCELARIA.lnk")

    # Kluczowa zmiana 0.12.3: tworzymy skrót najpierw tam, gdzie program ma zapis.
    create_shortcut_at(local_shortcut)
    print("OK: utworzono gotowy skrót w folderze programu:")
    print(local_shortcut)

    # Dopiero potem próbujemy zwykłego skopiowania na Pulpit.
    try:
        desktop = desktop_path()
        desktop_shortcut = os.path.join(desktop, "RK KANCELARIA.lnk")
        shutil.copy2(local_shortcut, desktop_shortcut)
        print("OK: skrót skopiowano również na Pulpit:")
        print(desktop_shortcut)
        return 0
    except PermissionError as exc:
        print()
        print("WINDOWS ZABLOKOWAŁ AUTOMATYCZNY ZAPIS NA PULPICIE (Access Denied).")
        print("To ograniczenie zabezpieczeń Windows, nie błąd ikonki.")
        print("Gotowy skrót z ikoną został utworzony w folderze programu.")
        print("Przeciągnij plik 'RK KANCELARIA.lnk' na Pulpit ręcznie.")
        print(f"Szczegóły: {exc}")
        open_folder_select(local_shortcut)
        return 2
    except OSError as exc:
        # Także Controlled Folder Access może ujawnić się jako zwykły OSError.
        winerror = getattr(exc, "winerror", None)
        if winerror == 5 or "0x80070005" in str(exc):
            print()
            print("WINDOWS ZABLOKOWAŁ AUTOMATYCZNY ZAPIS NA PULPICIE (0x80070005 / Access Denied).")
            print("Gotowy skrót z ikoną znajduje się w folderze programu.")
            print("Przeciągnij plik 'RK KANCELARIA.lnk' na Pulpit ręcznie.")
            open_folder_select(local_shortcut)
            return 2
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("BŁĄD:", exc)
        raise SystemExit(1)
