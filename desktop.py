# -*- coding: utf-8 -*-
"""RK KANCELARIA 0.2.0-dev3 — natywne okno Desktop na Qt WebEngine.

Frontend HTML/CSS/JS i backend Python/SQLite pozostają bez zmian architektonicznych.
Qt zapewnia własne okno aplikacji; nie uruchamia Edge/Chrome jako zwykłej przeglądarki.
"""
from __future__ import annotations

import os
import sys
import sqlite3
import shutil
import uuid
import threading
import time
import traceback
from pathlib import Path
from urllib.request import urlopen

from rk_paths import resolve_runtime_paths, installed_data_dir

# Desktop zawsze działa na lokalnym backendzie i we własnym oknie Qt.
os.environ['SPRAWNIK_OPEN_BROWSER'] = '0'
os.environ['SPRAWNIK_AUTO_SHUTDOWN'] = '0'
os.environ['SPRAWNIK_HOST'] = '127.0.0.1'
os.environ['RK_KANCELARIA_DESKTOP'] = '1'
os.environ['RK_KANCELARIA_DESKTOP_ENGINE'] = 'qtwebengine'

# Domyślnie korzystamy z akceleracji GPU. Awaryjny launcher --safe-gpu
# wyłącza ją tylko na komputerach ze sterownikiem sprawiającym problemy.
if '--safe-gpu' in sys.argv:
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu --disable-extensions --disable-background-networking'
else:
    os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-extensions --disable-background-networking')

# Self-test 0.2 NIGDY nie dotyka właściwej bazy użytkownika.
# Nie korzystamy z systemowego TEMP/TMP (na Windows może być ustawiony na
# nieistniejący katalog i powodować WinError 267). Test tworzy własny,
# jednoznaczny katalog pod LOCALAPPDATA/RK_KANCELARIA/Testy.
_SELFTEST_DIR = None
if '--self-test' in sys.argv:
    _root = Path(os.getenv('LOCALAPPDATA') or os.getenv('APPDATA') or str(Path.home())) / 'RK_KANCELARIA' / 'Testy'
    _root.mkdir(parents=True, exist_ok=True)
    _SELFTEST_DIR = _root / ('selftest_' + uuid.uuid4().hex)
    _SELFTEST_DIR.mkdir(parents=True, exist_ok=False)
    os.environ['SPRAWNIK_DATA_DIR'] = str(_SELFTEST_DIR)
    test_db = _SELFTEST_DIR / 'sprawnik.sqlite3'
    with sqlite3.connect(test_db) as con:
        con.execute('PRAGMA user_version=0')

# Synchronizacja Installed <-> Portable jest wykonywana wyłącznie, gdy istnieje
# para zapisana w .rk_sync_state.json albo gdy Portable widzi istniejącą bazę Installed.
# Dzięki temu podłączenie Portable do obcego komputera nie tworzy tam danych bez pytania.
def _early_message_box(title: str, text: str, error: bool = False) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
        root=tk.Tk(); root.withdraw()
        (messagebox.showerror if error else messagebox.showinfo)(title,text)
        root.destroy()
    except Exception:
        pass


_PRE_RUNTIME = resolve_runtime_paths(__file__)
_AUTO_SYNC_FLAG = _PRE_RUNTIME.app_dir / 'auto_sync.flag'


def _sync_peer_for_runtime():
    if not _AUTO_SYNC_FLAG.is_file() or _PRE_RUNTIME.mode == 'custom':
        return None
    try:
        import rk_sync
        here = _PRE_RUNTIME.data_dir
        state = rk_sync.read_state(here)
        if _PRE_RUNTIME.mode == 'portable':
            peer = installed_data_dir()
            # Pierwsze automatyczne parowanie tylko z istniejącą instalacją.
            if not (peer / 'sprawnik.sqlite3').is_file() and not state.get('pair_id'):
                return None
            return peer
        peer_hint = str(state.get('peer_hint') or '').strip()
        if peer_hint:
            peer = Path(peer_hint).expanduser()
            if peer.exists():
                return peer.resolve()
    except Exception:
        return None
    return None


def _prestart_sync() -> bool:
    peer = _sync_peer_for_runtime()
    if peer is None:
        return True
    try:
        import rk_sync
        if _PRE_RUNTIME.mode == 'portable':
            inst, port = peer, _PRE_RUNTIME.data_dir
        else:
            inst, port = _PRE_RUNTIME.data_dir, peer
        rk_sync.sync(inst, port, 'auto')
        return True
    except Exception as exc:
        try:
            import rk_sync
            if isinstance(exc, rk_sync.SyncConflict):
                # Konflikt wymaga jawnego wyboru; synchronizator robi backup celu.
                rk_sync.run_gui(inst, port)
                return rk_sync.status(inst, port).get('same', False)
        except Exception:
            pass
        _early_message_box('RK KANCELARIA — synchronizacja',
                    'Nie można bezpiecznie zsynchronizować danych przed uruchomieniem.\n\n'
                    + str(exc) + '\n\nUruchom SYNCHRONIZUJ.bat albo zamknij drugą kopię programu.', True)
        return False


def _postclose_sync() -> None:
    peer = _sync_peer_for_runtime()
    if peer is None:
        return
    try:
        import rk_sync
        if _PRE_RUNTIME.mode == 'portable':
            inst, port = peer, _PRE_RUNTIME.data_dir
        else:
            inst, port = _PRE_RUNTIME.data_dir, peer
        result = rk_sync.sync(inst, port, 'auto')
        log('Synchronizacja po zamknięciu: ' + result.message)
    except Exception as exc:
        log('Synchronizacja po zamknięciu — wymaga ręcznej obsługi: ' + repr(exc))
        message_box('RK KANCELARIA — synchronizacja',
                    'Program został zamknięty, ale nie udało się automatycznie zsynchronizować danych.\n\n'
                    + str(exc) + '\n\nDane lokalne są zachowane. Uruchom SYNCHRONIZUJ.bat.', True)


# Pre-sync musi nastąpić przed importem app.py, zanim backend otworzy bazę.
if '--self-test' not in sys.argv and not _prestart_sync():
    raise SystemExit(4)

import app  # noqa: E402

LOG_PATH = app.DATA_DIR / 'rk_kancelaria_desktop.log'


def log(message: str) -> None:
    try:
        app.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open('a', encoding='utf-8') as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    except Exception:
        pass


def message_box(title: str, text: str, error: bool = False) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
        root=tk.Tk(); root.withdraw()
        (messagebox.showerror if error else messagebox.showinfo)(title,text)
        root.destroy()
    except Exception:
        pass


def prepare_backend():
    # Usuń znacznik z poprzedniego uruchomienia. W trybie Qt jest on używany
    # przez przycisk „Zamknij program” na ekranie logowania.
    try: app.DESKTOP_EXIT_FLAG.unlink(missing_ok=True)
    except OSError: pass
    restore_msg=app.apply_pending_restore_if_any()
    recovery_msg=app.recover_database_if_needed()
    if restore_msg: log(restore_msg)
    if recovery_msg: log(recovery_msg)
    app.init_db(); app.purge_old_trash(); app.ensure_daily_backup()
    try: app.VERSION_MARKER.write_text(app.VERSION,encoding='utf-8')
    except OSError: pass
    server=app.AppServer(('127.0.0.1',0),app.Handler)
    port=server.server_address[1]; url=f'http://127.0.0.1:{port}/'
    thread=threading.Thread(target=server.serve_forever,name='rk-http',daemon=True); thread.start()
    deadline=time.time()+10; last=None
    while time.time()<deadline:
        try:
            with urlopen(url,timeout=.8) as r:
                if r.status in (200,302,303): return server,thread,url
        except Exception as exc:
            last=exc; time.sleep(.08)
    try: server.shutdown(); server.server_close()
    except Exception: pass
    raise RuntimeError(f'Backend nie wystartował: {last}')


def stop_backend(server) -> None:
    try: server.shutdown()
    except Exception: pass
    try: server.server_close()
    except Exception: pass


def self_test() -> int:
    server=None
    try:
        server,_thread,url=prepare_backend()
        with urlopen(url,timeout=3) as r:
            data=r.read(8192); ok=r.status==200 and b'RK KANCELARIA' in data
        try:
            import PySide6  # noqa
            qt='OK'
        except Exception as exc:
            qt=f'BRAK: {exc}'
        print('SELFTEST OK' if ok else 'SELFTEST FAIL'); print('Qt:',qt)
        return 0 if ok else 2
    except Exception:
        traceback.print_exc(); return 1
    finally:
        if server is not None: stop_backend(server)
        if _SELFTEST_DIR is not None:
            try: shutil.rmtree(_SELFTEST_DIR, ignore_errors=True)
            except Exception: pass


def main() -> int:
    if '--self-test' in sys.argv: return self_test()
    try:
        from PySide6.QtCore import QTimer, QUrl, Qt
        from PySide6.QtGui import QIcon, QDesktopServices
        from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except Exception as exc:
        message_box('RK KANCELARIA — brak komponentu Desktop',
                    'Nie znaleziono PySide6 / Qt WebEngine.\n\nUruchom najpierw INSTALUJ_TRYB_DESKTOP.bat.\n\n'+str(exc),True)
        log('Brak PySide6: '+repr(exc)); return 2

    server=None
    app_lock_acquired=False
    try:
        import rk_sync
        rk_sync.acquire_app_lock(app.DATA_DIR, app.APP_MODE); app_lock_acquired=True
        server,_thread,url=prepare_backend(); log(f'Start Desktop Qt: {url} | tryb={app.APP_MODE} | dane={app.DATA_DIR}')
        qtapp=QApplication(sys.argv); qtapp.setApplicationName('RK KANCELARIA'); qtapp.setOrganizationName('RK KANCELARIA')
        icon_path=app.BASE_DIR/'assets'/'rk_kancelaria.ico'
        if not icon_path.exists(): icon_path=app.BASE_DIR/'assets'/'rk_kancelaria_logo.png'
        icon=QIcon(str(icon_path)) if icon_path.exists() else QIcon()
        if not icon.isNull(): qtapp.setWindowIcon(icon)

        class LocalPage(QWebEnginePage):
            def acceptNavigationRequest(self, target, nav_type, is_main_frame):
                # Interfejs aplikacji pozostaje na lokalnym backendzie. Linki zewnętrzne
                # otwieramy w systemie, aby obca strona nigdy nie zastąpiła RK KANCELARIA.
                if target.scheme() in ('http','https') and target.host() not in ('127.0.0.1','localhost'):
                    QDesktopServices.openUrl(target); return False
                return super().acceptNavigationRequest(target,nav_type,is_main_frame)

        class MainWindow(QMainWindow):
            def __init__(self):
                super().__init__(); self._closing=False
                self.setWindowTitle(f'{app.APP_NAME} {app.VERSION}' + (' — Portable' if app.APP_MODE == 'portable' else ''))
                if not icon.isNull(): self.setWindowIcon(icon)
                self.resize(1480,920); self.setMinimumSize(1024,680)
                self.view=QWebEngineView(self)
                # Profil off-the-record: brak starego cache/cookies między uruchomieniami.
                self.profile=QWebEngineProfile(self)
                self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
                self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
                self.page=LocalPage(self.profile,self.view); self.view.setPage(self.page)
                st=self.view.settings(); st.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled,True); st.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled,True); st.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled,True)
                self.profile.downloadRequested.connect(self.on_download)
                self.view.renderProcessTerminated.connect(self.render_terminated)
                # Przycisk „Zamknij program” działa przez lokalny znacznik. Dzięki
                # temu backend nie próbuje ubijać procesu GUI z wątku HTTP.
                self.exit_timer=QTimer(self); self.exit_timer.setInterval(300); self.exit_timer.timeout.connect(self.check_exit_request); self.exit_timer.start()
                self.setCentralWidget(self.view); self.view.setUrl(QUrl(url)); self.showMaximized()

            def check_exit_request(self):
                try:
                    if app.DESKTOP_EXIT_FLAG.exists():
                        app.DESKTOP_EXIT_FLAG.unlink(missing_ok=True)
                        self.close()
                except Exception as exc:
                    log('Błąd obsługi żądania zamknięcia: '+repr(exc))

            def on_download(self, download):
                try:
                    suggested=download.suggestedFileName() or 'dokument'
                    default_dir=Path.home()/'Downloads'; default_dir.mkdir(parents=True,exist_ok=True)
                    path,_=QFileDialog.getSaveFileName(self,'Zapisz dokument',str(default_dir/suggested))
                    if not path:
                        download.cancel(); return
                    dest=Path(path); download.setDownloadDirectory(str(dest.parent)); download.setDownloadFileName(dest.name); download.accept()
                except Exception as exc:
                    log('Błąd pobierania: '+repr(exc)); QMessageBox.warning(self,'RK KANCELARIA','Nie udało się rozpocząć pobierania.\n'+str(exc))

            def render_terminated(self,status,code):
                log(f'Proces renderujący Qt zakończył się: status={status}, code={code}')
                QMessageBox.warning(self,'RK KANCELARIA','Moduł wyświetlania został zrestartowany. Dane w bazie nie zostały utracone.\nWidok zostanie przeładowany.')
                QTimer.singleShot(300,self.view.reload)

            def closeEvent(self,event):
                if self._closing:
                    event.accept(); return
                self._closing=True; event.ignore()
                # Najpierw poproś frontend o wysłanie ostatniego autosave; nie blokuj wątku GUI.
                try: self.page.runJavaScript("try{if(window.rkFlushAutosave)window.rkFlushAutosave();}catch(e){}")
                except Exception: pass
                QTimer.singleShot(450,self.close)

        win=MainWindow(); rc=qtapp.exec()
        # GUI już nie działa; dopiero teraz bezpiecznie zatrzymujemy backend i robimy backup.
        time.sleep(.15)
        try:
            when,path=app.create_shutdown_backup(); log(f'Backup przy zamykaniu: {when} {path}')
        except Exception as exc: log('Backup przy zamykaniu — błąd: '+repr(exc))
        stop_backend(server); server=None; log('Zamknięto Desktop Qt.')
        try:
            import rk_sync
            rk_sync.release_app_lock(app.DATA_DIR); app_lock_acquired=False
        except Exception: pass
        _postclose_sync()
        return int(rc)
    except Exception as exc:
        details=''.join(traceback.format_exception(type(exc),exc,exc.__traceback__)); log(details)
        if server is not None:
            try: app.create_shutdown_backup()
            except Exception: pass
            stop_backend(server)
        if app_lock_acquired:
            try:
                import rk_sync
                rk_sync.release_app_lock(app.DATA_DIR)
            except Exception: pass
        message_box('RK KANCELARIA — błąd uruchamiania',f'Nie udało się uruchomić aplikacji.\n\n{exc}\n\nLog: {LOG_PATH}',True)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
