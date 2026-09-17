#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RK KANCELARIA 0.3.0-dev4 — UI & PERFORMANCE.

Czytelny widok sprawy dla laika, globalna linia czasu, kalendarz i alerty,
relacje „co z czego wynika”, generowane podsumowania oraz lokalna biblioteka prawa.
Dane i funkcje DEV9 pozostają zgodne w widoku zaawansowanym.
"""
from __future__ import annotations

import base64
import calendar as pycalendar
import contextlib
import hmac
import html
import hashlib
import secrets
import io
import json
import mimetypes
import queue
import os
import re
import shutil
import sqlite3
import subprocess
import socket
import struct
import sys
import threading
import time
import webbrowser
import zipfile
import tempfile
import uuid
import ctypes
from ctypes import wintypes
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from email.parser import BytesParser
from email.policy import default as email_policy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
from http.cookies import SimpleCookie

from rk_paths import resolve_runtime_paths, installed_data_dir
from rk_smart import (
    ACTIONABLE_ALERT_TYPES, ALERT_PRIORITIES, ALERT_TYPES, LAW_REGISTRY, RELATION_TYPES as SMART_RELATION_TYPES,
    add_custom_eli_act, auto_create_structural_links, build_unified_timeline,
    derive_case_auto_tags, ensure_smart_schema, extract_explicit_deadline_suggestions,
    generate_case_summary, reconcile_task_alerts, search_law, sync_alert_task, sync_task_alert,
    update_law_from_eli, upcoming_alerts,
)

APP_NAME = "RK KANCELARIA"
DESKTOP_MODE = os.getenv("RK_KANCELARIA_DESKTOP", "0").strip().lower() in {"1", "true", "yes", "tak"}
APP_AUTHOR = "ROBERT KŁOSOWSKI"
VERSION = "0.3.0-dev5"
SCHEMA_VERSION = 322
BASE_DIR = Path(__file__).resolve().parent
RUNTIME_PATHS = resolve_runtime_paths(__file__)
APP_MODE = RUNTIME_PATHS.mode

# Konfiguracja sieciowa nadal może pochodzić ze zmiennych środowiskowych.
HOST = os.getenv("SPRAWNIK_HOST", "127.0.0.1").strip() or "127.0.0.1"
try:
    PORT = int(os.getenv("SPRAWNIK_PORT", "8765"))
except ValueError:
    PORT = 8765

DATA_DIR = RUNTIME_PATHS.data_dir
DB_PATH = RUNTIME_PATHS.db_path
FILES_DIR = RUNTIME_PATHS.files_dir
MIGRATION_LOG = RUNTIME_PATHS.migration_log
VERSION_MARKER = RUNTIME_PATHS.version_marker
BACKUPS_DIR = RUNTIME_PATHS.backups_dir
DAILY_BACKUPS_DIR = RUNTIME_PATHS.daily_backups_dir
CLOSE_BACKUPS_DIR = RUNTIME_PATHS.close_backups_dir
RECOVERY_DIR = RUNTIME_PATHS.recovery_dir
PENDING_RESTORE_DIR = RUNTIME_PATHS.pending_restore_dir
PENDING_RESTORE_DB = PENDING_RESTORE_DIR / "sprawnik_restore.sqlite3"
PENDING_RESTORE_MARKER = PENDING_RESTORE_DIR / "restore.json"
PENDING_IMPORT_DOCS = PENDING_RESTORE_DIR / "import_dokumenty"
PENDING_IMPORT_DRAFTS = PENDING_RESTORE_DIR / "import_projekty_pism"
PRE_IMPORT_BACKUPS_DIR = DATA_DIR / "backup_przed_importem"
BACKUP_KEY_FILE = RUNTIME_PATHS.backup_key_file
TRASH_RETENTION_DAYS = 30
# Ochrona przed przypadkowym wczytaniem wieluset MB/GB do pamięci przez pojedynczy formularz.
MAX_POST_BYTES = 256 * 1024 * 1024
ERROR_LOG = RUNTIME_PATHS.error_log
PERF_LOG = RUNTIME_PATHS.perf_log
DRAFTS_DIR = RUNTIME_PATHS.drafts_dir
OCR_DIR = RUNTIME_PATHS.ocr_dir
OCR_TESSDATA_DIR = OCR_DIR / "tessdata"
OCR_SETUP_SCRIPT = BASE_DIR / "ocr_setup.py"
DESKTOP_EXIT_FLAG = RUNTIME_PATHS.desktop_exit_flag

_INDEX_QUEUE: "queue.Queue[tuple[int,bool]]" = queue.Queue()
_INDEX_WORKER_STARTED = False
_INDEX_WORKER_LOCK = threading.Lock()
_ASSET_CACHE: dict[str, tuple[int, int, bytes, str, str]] = {}
_ASSET_CACHE_LOCK = threading.Lock()


def _looks_like_sqlite(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size < 100:
            return False
        with path.open("rb") as f:
            return f.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def _legacy_candidates() -> list[Path]:
    """Znajdź stare bazy z wcześniejszych wersji, bez skanowania całego dysku."""
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(path: Path):
        try:
            rp = path.expanduser().resolve()
        except OSError:
            return
        key = str(rp).lower() if os.name == "nt" else str(rp)
        if key in seen or rp == DB_PATH:
            return
        seen.add(key)
        if _looks_like_sqlite(rp):
            candidates.append(rp)

    # Najważniejszy przypadek: aktualizacja przez podmianę app.py w starym folderze.
    add(RUNTIME_PATHS.app_dir / "sprawnik.sqlite3")

    # Stara wersja Installed -> %LOCALAPPDATA%\RK_KANCELARIA\Dane\sprawnik.sqlite3.
    # W trybie Installed będzie to DB_PATH i zostanie automatycznie pominięta przez add().
    try:
        add(installed_data_dir() / "sprawnik.sqlite3")
    except Exception:
        pass

    # Poprzednie paczki rozpakowane obok bieżącej wersji.
    parents = {RUNTIME_PATHS.app_dir.parent}
    for root in (Path.home() / "Downloads", Path.home() / "Desktop", Path.home() / "Documents"):
        if root.exists():
            parents.add(root)
    patterns = ("RK_KANCELARIA_v*", "RK KANCELARIA*", "sprawnik_v*", "Sprawnik*")
    for parent in parents:
        try:
            for pat in patterns:
                for folder in parent.glob(pat):
                    if folder.is_dir():
                        add(folder / "sprawnik.sqlite3")
        except OSError:
            pass
    return candidates


def _db_score(path: Path) -> tuple[int, float]:
    """Preferuj rzeczywiście używaną bazę, a następnie najnowszą modyfikację."""
    score = 0
    try:
        uri = f"file:{path.as_posix()}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=2)
        try:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            weights = {
                "users": 1000,
                "documents": 120,
                "case_notes": 30,
                "case_relations": 20,
                "cases": 10,
                "tasks": 4,
                "events": 4,
                "parties": 2,
            }
            for table, weight in weights.items():
                if table in tables:
                    try:
                        score += int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) * weight
                    except sqlite3.DatabaseError:
                        pass
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return (-1, 0.0)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (score, mtime)



def _database_summary(path: Path) -> dict:
    """Lekki opis bazy używany do bezpiecznego porównania przed importem."""
    out = {"ok": False, "reason": "", "core_records": 0, "latest_activity": "", "counts": {}, "version": ""}
    ok, reason = sqlite_integrity(path)
    out["ok"], out["reason"] = ok, reason
    if not ok:
        return out
    try:
        uri = f"file:{path.as_posix()}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        try:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            core_tables = ("cases", "tasks", "documents", "events", "case_notes", "writing_projects")
            for table in core_tables:
                if table in tables:
                    try:
                        out["counts"][table] = int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                    except sqlite3.DatabaseError:
                        out["counts"][table] = 0
            out["core_records"] = sum(out["counts"].values())
            latest = []
            candidates = (
                ("audit_log", "created_at"),
                ("immutable_audit", "created_at"),
                ("cases", "updated_at"),
                ("documents", "created_at"),
                ("tasks", "created_at"),
                ("events", "created_at"),
                ("case_notes", "created_at"),
                ("writing_projects", "updated_at"),
            )
            for table, col in candidates:
                if table not in tables:
                    continue
                try:
                    cols = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
                    if col in cols:
                        val = con.execute(f"SELECT MAX({col}) FROM {table}").fetchone()[0]
                        if val:
                            latest.append(str(val))
                except sqlite3.DatabaseError:
                    pass
            out["latest_activity"] = max(latest) if latest else ""
        finally:
            con.close()
    except Exception as exc:
        out["ok"] = False
        out["reason"] = str(exc)
        return out
    try:
        marker = path.parent / ".wersja_programu"
        out["version"] = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
    except OSError:
        pass
    return out


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _tree_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def installed_import_source() -> tuple[Path, Path] | None:
    """Zwróć katalog i bazę starego Installed, jeśli jest to inne źródło niż bieżące Data."""
    try:
        src_dir = installed_data_dir()
        src_db = src_dir / "sprawnik.sqlite3"
        if src_dir.resolve() == DATA_DIR.resolve():
            return None
        if _looks_like_sqlite(src_db):
            return src_dir, src_db
    except Exception:
        return None
    return None


def _backup_current_data_before_import() -> Path | None:
    """Pełna lokalna siatka bezpieczeństwa: baza + dokumenty + projekty pism."""
    if not DB_PATH.exists() and not FILES_DIR.exists() and not DRAFTS_DIR.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = PRE_IMPORT_BACKUPS_DIR / f"import_{stamp}"
    root.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists() and _looks_like_sqlite(DB_PATH):
        _sqlite_backup(DB_PATH, root / "sprawnik.sqlite3")
    if FILES_DIR.exists():
        shutil.copytree(FILES_DIR, root / "dokumenty", dirs_exist_ok=True, copy_function=shutil.copy2)
    if DRAFTS_DIR.exists():
        shutil.copytree(DRAFTS_DIR, root / "projekty_pism", dirs_exist_ok=True, copy_function=shutil.copy2)
    if VERSION_MARKER.exists():
        try:
            shutil.copy2(VERSION_MARKER, root / ".wersja_programu")
        except OSError:
            pass
    # Nie pozwalaj, aby jednorazowe kopie po importach rosły bez końca.
    try:
        old = sorted([x for x in PRE_IMPORT_BACKUPS_DIR.glob("import_*") if x.is_dir()], key=lambda x: x.stat().st_mtime, reverse=True)
        for folder in old[3:]:
            shutil.rmtree(folder, ignore_errors=True)
    except OSError:
        pass
    return root


def schedule_installed_import() -> tuple[bool, str]:
    """Przygotuj bezpieczny import Installed -> bieżący Portable. Podmiana bazy następuje po restarcie."""
    src = installed_import_source()
    if not src:
        return False, "Nie znaleziono osobnej bazy wersji Installed."
    src_dir, src_db = src
    src_summary = _database_summary(src_db)
    if not src_summary["ok"]:
        return False, f"Baza źródłowa nie przeszła kontroli SQLite: {src_summary['reason']}"
    dst_summary = _database_summary(DB_PATH) if DB_PATH.exists() else {"ok": False, "core_records": 0, "latest_activity": "", "counts": {}, "version": ""}

    # Jeżeli pliki są identyczne, nie planuj bezsensownej podmiany.
    try:
        if DB_PATH.exists() and DB_PATH.stat().st_size == src_db.stat().st_size and _file_sha256(DB_PATH) == _file_sha256(src_db):
            return False, "Bieżąca baza i baza Installed są identyczne — import nie jest potrzebny."
    except OSError:
        pass

    # Twarda ochrona przed nadpisaniem aktywniejszej/nowszej bazy starszym źródłem.
    if dst_summary.get("ok") and int(dst_summary.get("core_records") or 0) > 0:
        src_latest = str(src_summary.get("latest_activity") or "")
        dst_latest = str(dst_summary.get("latest_activity") or "")
        src_core = int(src_summary.get("core_records") or 0)
        dst_core = int(dst_summary.get("core_records") or 0)
        if dst_latest and src_latest and dst_latest > src_latest:
            return False, ("Import zablokowany: bieżąca baza zawiera nowszą aktywność niż baza Installed "
                           f"({dst_latest} > {src_latest}). Najpierw wykonaj ręczne porównanie/synchronizację.")
        if dst_core > src_core and (not src_latest or not dst_latest or dst_latest >= src_latest):
            return False, ("Import zablokowany: bieżąca baza zawiera więcej danych roboczych niż źródło Installed "
                           f"({dst_core} > {src_core}). Program nie nadpisze jej automatycznie starszą/mniejszą bazą.")

    # Oszacuj miejsce na kopię bezpieczeństwa + staging importu.
    current_payload = (DB_PATH.stat().st_size if DB_PATH.exists() else 0) + _tree_size(FILES_DIR) + _tree_size(DRAFTS_DIR)
    source_payload = src_db.stat().st_size + _tree_size(src_dir / "dokumenty") + _tree_size(src_dir / "projekty_pism")
    try:
        free = shutil.disk_usage(DATA_DIR).free
        needed = int((current_payload + source_payload) * 1.15) + 50 * 1024 * 1024
        if free < needed:
            return False, f"Za mało wolnego miejsca na bezpieczny import. Potrzeba ok. {needed/1024/1024:.0f} MB wolnego miejsca."
    except OSError:
        pass

    try:
        backup_dir = _backup_current_data_before_import()
        PENDING_RESTORE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = PENDING_RESTORE_DB.with_suffix(".sqlite3.tmp")
        _sqlite_backup(src_db, tmp)
        ok, why = sqlite_integrity(tmp)
        if not ok:
            tmp.unlink(missing_ok=True)
            return False, f"Migawka importu nie przeszła kontroli SQLite: {why}"
        os.replace(tmp, PENDING_RESTORE_DB)

        for staging in (PENDING_IMPORT_DOCS, PENDING_IMPORT_DRAFTS):
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        if (src_dir / "dokumenty").is_dir():
            shutil.copytree(src_dir / "dokumenty", PENDING_IMPORT_DOCS, copy_function=shutil.copy2)
        if (src_dir / "projekty_pism").is_dir():
            shutil.copytree(src_dir / "projekty_pism", PENDING_IMPORT_DRAFTS, copy_function=shutil.copy2)

        meta = {
            "kind": "installed_import",
            "source": str(src_dir),
            "source_version": src_summary.get("version", ""),
            "source_core_records": src_summary.get("core_records", 0),
            "source_latest_activity": src_summary.get("latest_activity", ""),
            "backup_dir": str(backup_dir) if backup_dir else "",
            "scheduled_at": datetime.now().isoformat(timespec="seconds"),
        }
        PENDING_RESTORE_MARKER.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return True, ("Import został zweryfikowany i przygotowany. Zamknij RK KANCELARIA i uruchom ponownie. "
                      "Przy starcie baza Installed zostanie zaimportowana, schemat zaktualizowany, a dokumenty przełączone na importowany zestaw.")
    except Exception as exc:
        log_event(f"Planowanie importu Installed: {exc}", "ERROR")
        return False, f"Nie udało się przygotować importu: {exc}"


def _sqlite_backup(src: Path, dst: Path) -> None:
    """Kopia SQLite przez API backup, aby uwzględnić również dane z WAL."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".migracja_tmp")
    if tmp.exists():
        tmp.unlink()
    src_con = sqlite3.connect(str(src), timeout=10)
    dst_con = sqlite3.connect(str(tmp), timeout=10)
    try:
        src_con.backup(dst_con)
    finally:
        dst_con.close()
        src_con.close()
    os.replace(tmp, dst)


def migrate_legacy_data_if_needed() -> str:
    """Jednorazowo przenieś starą bazę i dokumenty do stałego katalogu danych."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        return ""
    # Jeżeli istnieją kopie bezpieczeństwa w stałym katalogu danych, nie wybieraj
    # automatycznie starszej bazy z Downloads/Desktop. Recovery po imporcie modułu
    # ma pierwszeństwo i odtworzy najnowszą zweryfikowaną kopię.
    for bdir in (DATA_DIR / "backup_przy_zamykaniu", DATA_DIR / "backup_codzienny", DATA_DIR / "backup_przed_aktualizacja"):
        try:
            if bdir.exists() and any(bdir.glob('*.sqlite3*')):
                return ""
        except OSError:
            pass

    candidates = _legacy_candidates()
    if not candidates:
        return ""
    candidates.sort(key=_db_score, reverse=True)
    source = candidates[0]
    try:
        _sqlite_backup(source, DB_PATH)
        src_docs = source.parent / "dokumenty"
        if src_docs.is_dir():
            shutil.copytree(src_docs, FILES_DIR, dirs_exist_ok=True, copy_function=shutil.copy2)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = f"{stamp} | automatyczna migracja z: {source} -> {DB_PATH}"
        MIGRATION_LOG.write_text(msg + "\n", encoding="utf-8")
        return msg
    except Exception as exc:
        try:
            MIGRATION_LOG.write_text(f"BŁĄD migracji z {source}: {exc}\n", encoding="utf-8")
        except OSError:
            pass
        return f"BŁĄD migracji danych: {exc}"


MIGRATION_MESSAGE = migrate_legacy_data_if_needed()
DATA_DIR.mkdir(parents=True, exist_ok=True)
FILES_DIR.mkdir(parents=True, exist_ok=True)
DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
OCR_TESSDATA_DIR.mkdir(parents=True, exist_ok=True)


def backup_before_version_upgrade() -> str:
    """Przed pierwszym uruchomieniem nowej wersji zachowaj kopię bazy."""
    if not DB_PATH.exists() or not _looks_like_sqlite(DB_PATH):
        return ""
    try:
        previous = VERSION_MARKER.read_text(encoding="utf-8").strip() if VERSION_MARKER.exists() else ""
    except OSError:
        previous = ""
    if previous == VERSION:
        return ""
    try:
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        from_ver = previous.replace("/", "_").replace("\\", "_") or "starsza_wersja"
        dest = BACKUPS_DIR / f"baza_przed_v{VERSION}_z_{from_ver}_{stamp}.sqlite3"
        _sqlite_backup(DB_PATH, dest)
        return f"Backup przed aktualizacją: {dest}"
    except Exception as exc:
        return f"UWAGA: nie udało się utworzyć backupu przed aktualizacją: {exc}"


PRE_UPGRADE_BACKUP_MESSAGE = backup_before_version_upgrade()
OPEN_BROWSER = os.getenv("SPRAWNIK_OPEN_BROWSER", "1").strip().lower() not in {"0", "false", "no", "nie"}
# Logowanie jest realizowane przez konta zapisane w bazie programu.
# Zmienne SPRAWNIK_USER / SPRAWNIK_PASSWORD z poprzednich wersji nie są już używane.
SESSION_COOKIE = "rk_kancelaria_session"
PASSWORD_ITERATIONS = 260_000
SESSION_HOURS = max(1, int(os.getenv("RK_SESSION_HOURS", "12")))
_REQUEST_CONTEXT = threading.local()
_SESSION_CACHE: dict[str, tuple[float, dict]] = {}
_SESSION_TOUCH: dict[str, float] = {}
_SESSION_CACHE_LOCK = threading.Lock()
SESSION_CACHE_SECONDS = 8.0
SESSION_TOUCH_SECONDS = 180.0

LOCAL_MODE = HOST in {"127.0.0.1", "localhost", "::1"}
_auto_env = os.getenv("SPRAWNIK_AUTO_SHUTDOWN")
if _auto_env is None:
    AUTO_SHUTDOWN = LOCAL_MODE
else:
    AUTO_SHUTDOWN = _auto_env.strip().lower() not in {"0", "false", "no", "nie"}
try:
    AUTO_SHUTDOWN_GRACE = max(0.25, float(os.getenv("SPRAWNIK_AUTO_SHUTDOWN_GRACE", "0.7")))
except ValueError:
    AUTO_SHUTDOWN_GRACE = 0.7
try:
    CLIENT_STALE_SECONDS = max(10, int(os.getenv("SPRAWNIK_CLIENT_STALE_SECONDS", "25")))
except ValueError:
    CLIENT_STALE_SECONDS = 25
_CLIENT_LOCK = threading.Lock()
_CLIENT_TABS: dict[str, float] = {}
_CLIENT_SEEN = False
_CLIENT_EMPTY_SINCE: float | None = None

def client_heartbeat(tab_id: str) -> None:
    global _CLIENT_SEEN, _CLIENT_EMPTY_SINCE
    if not tab_id:
        return
    now = time.monotonic()
    with _CLIENT_LOCK:
        _CLIENT_SEEN = True
        _CLIENT_TABS[tab_id[:120]] = now
        _CLIENT_EMPTY_SINCE = None

def client_closing(tab_id: str) -> None:
    global _CLIENT_EMPTY_SINCE
    if not tab_id:
        return
    now = time.monotonic()
    with _CLIENT_LOCK:
        _CLIENT_TABS.pop(tab_id[:120], None)
        if not _CLIENT_TABS:
            _CLIENT_EMPTY_SINCE = now

class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def auto_shutdown_monitor(server: ThreadingHTTPServer) -> None:
    global _CLIENT_EMPTY_SINCE
    if not AUTO_SHUTDOWN:
        return
    while True:
        time.sleep(0.5)
        now = time.monotonic()
        with _CLIENT_LOCK:
            stale = [k for k, v in _CLIENT_TABS.items() if now - v > CLIENT_STALE_SECONDS]
            for k in stale:
                _CLIENT_TABS.pop(k, None)
            if _CLIENT_SEEN and not _CLIENT_TABS and _CLIENT_EMPTY_SINCE is None:
                _CLIENT_EMPTY_SINCE = now
            empty_since = _CLIENT_EMPTY_SINCE
        if _CLIENT_SEEN and empty_since is not None and now - empty_since >= AUTO_SHUTDOWN_GRACE:
            print("\nBrak otwartych kart RK KANCELARIA — automatyczne zamknięcie programu.")
            threading.Thread(target=server.shutdown, daemon=True).start()
            return

STATUS_LABELS = {
    "active": "W toku",
    "waiting": "Oczekiwanie",
    "todo": "Do wykonania",
    "suspended": "W zawieszeniu",
    "closed": "Zakończona",
}
STATUS_BADGES = {
    "active": "blue",
    "waiting": "amber",
    "todo": "red",
    "suspended": "gray",
    "closed": "green",
}
DOC_TYPES = ["Pismo procesowe", "Wniosek", "Apelacja", "Zażalenie", "Odpowiedź", "Postanowienie", "Wyrok", "Uzasadnienie", "Opinia biegłego", "Dowód", "Korespondencja", "Załącznik", "Inne"]
PLEADING_DOC_TYPES = {"Pismo procesowe", "Wniosek", "Apelacja", "Zażalenie", "Odpowiedź"}
DOC_STATUSES = ["Aktywny", "Roboczy", "Draft", "Do podpisu", "Podpisany", "Wysłany", "Złożone", "Złożony", "Doręczone", "Doręczony", "Oczekiwanie na odpowiedź", "Archiwalne", "Archiwalny"]
EVENT_TYPES = ["Czynność", "Rozprawa", "Posiedzenie", "Mediacja", "Orzeczenie", "Wpływ pisma", "Wysłanie pisma", "Doręczenie", "Telefon", "Notatka"]

RELATION_TYPES = {
    "appeal": ("II instancja", "I instancja"),
    "appeal_reverse": ("I instancja", "II instancja"),
    "complaint": ("Postępowanie zażaleniowe", "Sprawa, z której wniesiono zażalenie"),
    "complaint_reverse": ("Sprawa, z której wniesiono zażalenie", "Postępowanie zażaleniowe"),
    "main_related": ("Sprawa podrzędna / powiązana", "Sprawa główna / nadrzędna"),
    "evidence": ("Powiązana dowodowo", "Powiązana dowodowo"),
    "execution": ("Egzekucja", "Sprawa będąca podstawą egzekucji"),
    "related": ("Sprawa powiązana", "Sprawa powiązana"),
    "other": ("Inne powiązanie", "Inne powiązanie"),
}


@contextlib.contextmanager
def db():
    """Transakcyjne, krótko żyjące połączenie SQLite."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=15, cached_statements=256)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA busy_timeout = 15000")
        con.execute("PRAGMA synchronous = NORMAL")
        con.execute("PRAGMA temp_store = MEMORY")
        con.execute("PRAGMA cache_size = -32768")
        con.execute("PRAGMA mmap_size = 134217728")
        yield con
        con.commit()
    except Exception:
        try: con.rollback()
        except Exception: pass
        raise
    finally:
        try: con.close()
        except Exception: pass


def row_get(row, key: str, default=''):
    """Bezpieczny odczyt rekordów ze starszych schematów bazy."""
    if row is None:
        return default
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def log_app_exception(path: str, exc: Exception) -> None:
    """Zapisuje pełny traceback lokalnie; nie wysyła żadnych danych na zewnątrz."""
    try:
        import traceback
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with ERROR_LOG.open('a', encoding='utf-8') as f:
            f.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] {path}\n")
            traceback.print_exc(file=f)
    except Exception:
        pass

def log_slow_request(path: str, elapsed: float) -> None:
    """Zapisuj tylko realnie wolne żądania; log nie rośnie przy normalnej pracy."""
    if elapsed < 0.75:
        return
    try:
        DATA_DIR.mkdir(parents=True,exist_ok=True)
        with PERF_LOG.open('a',encoding='utf-8') as f:
            f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {elapsed*1000:.0f} ms | {path}\n")
    except Exception:
        pass



def log_event(message: str, level: str = "INFO") -> None:
    """Lekki dziennik techniczny bez treści dokumentów i formularzy."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if ERROR_LOG.exists() and ERROR_LOG.stat().st_size > 5 * 1024 * 1024:
            old = ERROR_LOG.with_suffix('.log.1')
            try: old.unlink(missing_ok=True)
            except OSError: pass
            try: os.replace(ERROR_LOG, old)
            except OSError: pass
        with ERROR_LOG.open('a', encoding='utf-8') as f:
            f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {level}: {message}\n")
    except Exception:
        pass


def sqlite_integrity(path: Path) -> tuple[bool, str]:
    if not path.exists(): return False, 'brak pliku'
    if not _looks_like_sqlite(path): return False, 'nieprawidłowy nagłówek SQLite'
    try:
        con=sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
        try:
            row=con.execute('PRAGMA quick_check').fetchone(); msg=str(row[0] if row else '')
            return msg.lower()=='ok', (msg or 'brak wyniku quick_check')
        finally: con.close()
    except Exception as exc:
        return False,str(exc)


def _backup_candidates_plain() -> list[Path]:
    out=[]
    for folder in (CLOSE_BACKUPS_DIR, DAILY_BACKUPS_DIR, BACKUPS_DIR):
        if folder.exists():
            try: out.extend(list(folder.glob('*.sqlite3'))+list(folder.glob('*.sqlite3.rkenc')))
            except OSError: pass
    return sorted(out,key=lambda x:x.stat().st_mtime if x.exists() else 0,reverse=True)


def recover_database_if_needed() -> str:
    """Zachowaj uszkodzoną bazę i odtwórz najnowszą poprawną kopię."""
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    def restore_candidate(cand: Path) -> bool:
        try:
            if cand.name.endswith('.rkenc'):
                secret=backup_secret_standalone()
                if not secret: return False
                RECOVERY_DIR.mkdir(parents=True,exist_ok=True)
                tmp=RECOVERY_DIR/f'.decrypt_{uuid.uuid4().hex}.sqlite3'
                atomic_write_bytes(tmp,decrypted_blob(cand.read_bytes(),secret))
                ok,_=sqlite_integrity(tmp)
                if not ok: tmp.unlink(missing_ok=True); return False
                os.replace(tmp,DB_PATH); return True
            ok,_=sqlite_integrity(cand)
            if not ok: return False
            _sqlite_backup(cand,DB_PATH); return True
        except Exception as exc:
            log_event(f'Recovery candidate {cand.name}: {exc}','ERROR'); return False
    if DB_PATH.exists():
        ok,reason=sqlite_integrity(DB_PATH)
        if ok: return ''
        RECOVERY_DIR.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now().strftime('%Y%m%d_%H%M%S'); damaged=RECOVERY_DIR/f'sprawnik_uszkodzona_{stamp}.sqlite3'
        try: shutil.copy2(DB_PATH,damaged)
        except Exception as exc: log_event(f'Nie udało się zachować uszkodzonej bazy: {exc}','ERROR')
        for cand in _backup_candidates_plain():
            if restore_candidate(cand):
                msg=f'Automatyczne recovery: {reason}; użyto {cand.name}; uszkodzoną kopię zachowano jako {damaged.name}'
                log_event(msg,'WARNING'); return msg
        raise RuntimeError(f'Baza danych jest uszkodzona ({reason}). Zachowano kopię w {RECOVERY_DIR}. Brak możliwego do odtworzenia backupu.')
    for cand in _backup_candidates_plain():
        if restore_candidate(cand):
            msg=f'Odtworzono brakującą bazę z kopii {cand.name}'; log_event(msg,'WARNING'); return msg
    # Pierwsze uruchomienie może legalnie nie mieć bazy. Jeżeli jednak katalog
    # wygląda na wcześniej używany (znacznik wersji albo fizyczne dokumenty),
    # nie twórz po cichu pustej bazy — użytkownik mógłby uznać, że dane zniknęły.
    used_before=VERSION_MARKER.exists()
    if not used_before and FILES_DIR.exists():
        try: used_before=any(x.is_file() for x in FILES_DIR.rglob('*'))
        except OSError: used_before=False
    if used_before:
        msg='Brakuje głównego pliku bazy danych, a katalog danych był wcześniej używany. Nie utworzono pustej bazy. Przywróć kopię bezpieczeństwa lub sprawdź katalog recovery.'
        log_event(msg,'ERROR')
        raise RuntimeError(msg)
    return ''

def create_shutdown_backup(retention: int = 30) -> tuple[str,str]:
    try:
        if not DB_PATH.exists(): return '—',''
        ok,why=sqlite_integrity(DB_PATH)
        if not ok: return 'błąd',f'Nie wykonano kopii: {why}'
        CLOSE_BACKUPS_DIR.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        plain=CLOSE_BACKUPS_DIR/f'.tmp_close_{stamp}.sqlite3'; _sqlite_backup(DB_PATH,plain)
        try:
            with db() as con: secret=backup_secret(con)
        except Exception:
            secret=backup_secret_standalone()
        if secret:
            dest=CLOSE_BACKUPS_DIR/f'rk_kancelaria_close_{stamp}.sqlite3.rkenc'
            atomic_write_bytes(dest,encrypted_blob(plain.read_bytes(),secret)); plain.unlink(missing_ok=True)
        else:
            dest=CLOSE_BACKUPS_DIR/f'rk_kancelaria_close_{stamp}.sqlite3'; os.replace(plain,dest)
        files=sorted(list(CLOSE_BACKUPS_DIR.glob('rk_kancelaria_close_*.sqlite3'))+list(CLOSE_BACKUPS_DIR.glob('rk_kancelaria_close_*.sqlite3.rkenc')),key=lambda x:x.stat().st_mtime,reverse=True)
        for old in files[max(2,int(retention)):]:
            try: old.unlink()
            except OSError: pass
        return datetime.fromtimestamp(dest.stat().st_mtime).strftime('%d.%m.%Y %H:%M'),str(dest)
    except Exception as exc:
        log_event(f'Backup przy zamykaniu: {exc}','ERROR'); return 'błąd',str(exc)

def _allowed_backup_by_token(token: str) -> Path | None:
    name=Path(unquote(token or '')).name
    if not name: return None
    for folder in (CLOSE_BACKUPS_DIR,DAILY_BACKUPS_DIR,BACKUPS_DIR):
        p=folder/name
        try:
            if p.is_file() and p.resolve().parent==folder.resolve(): return p
        except OSError: pass
    return None


def schedule_backup_restore(backup_path: Path) -> tuple[bool,str]:
    try:
        PENDING_RESTORE_DIR.mkdir(parents=True,exist_ok=True); raw=backup_path.read_bytes()
        if backup_path.name.endswith('.rkenc'):
            with db() as con: secret=backup_secret(con)
            if not secret: return False,'Backup jest zaszyfrowany, ale bieżący klucz nie jest dostępny.'
            raw=decrypted_blob(raw,secret)
        tmp=PENDING_RESTORE_DB.with_suffix('.sqlite3.tmp'); tmp.write_bytes(raw)
        ok,why=sqlite_integrity(tmp)
        if not ok: tmp.unlink(missing_ok=True); return False,f'Wybrana kopia nie przeszła kontroli SQLite: {why}'
        os.replace(tmp,PENDING_RESTORE_DB)
        PENDING_RESTORE_MARKER.write_text(json.dumps({'source':backup_path.name,'scheduled_at':datetime.now().isoformat(timespec='seconds')},ensure_ascii=False),encoding='utf-8')
        return True,'Kopia została zweryfikowana. Zostanie przywrócona przy następnym uruchomieniu RK KANCELARIA.'
    except Exception as exc:
        log_event(f'Planowanie restore {backup_path}: {exc}','ERROR'); return False,str(exc)


def apply_pending_restore_if_any() -> str:
    if not PENDING_RESTORE_MARKER.exists() or not PENDING_RESTORE_DB.exists(): return ''
    try: meta=json.loads(PENDING_RESTORE_MARKER.read_text(encoding='utf-8'))
    except Exception: meta={}
    ok,why=sqlite_integrity(PENDING_RESTORE_DB)
    if not ok: log_event(f'Odrzucono pending restore: {why}','ERROR'); return f'Nie przywrócono kopii: {why}'
    RECOVERY_DIR.mkdir(parents=True,exist_ok=True)
    if DB_PATH.exists() and _looks_like_sqlite(DB_PATH):
        safety=RECOVERY_DIR/f"baza_przed_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sqlite3"; _sqlite_backup(DB_PATH,safety)
    os.replace(PENDING_RESTORE_DB,DB_PATH)

    kind=meta.get('kind','backup_restore')
    if kind in {'installed_import','cloud_snapshot','data_snapshot'}:
        try:
            if PENDING_IMPORT_DOCS.exists():
                if FILES_DIR.exists(): shutil.rmtree(FILES_DIR,ignore_errors=True)
                shutil.copytree(PENDING_IMPORT_DOCS,FILES_DIR,copy_function=shutil.copy2)
            else:
                FILES_DIR.mkdir(parents=True,exist_ok=True)
            if PENDING_IMPORT_DRAFTS.exists():
                if DRAFTS_DIR.exists(): shutil.rmtree(DRAFTS_DIR,ignore_errors=True)
                shutil.copytree(PENDING_IMPORT_DRAFTS,DRAFTS_DIR,copy_function=shutil.copy2)
            else:
                DRAFTS_DIR.mkdir(parents=True,exist_ok=True)
        finally:
            shutil.rmtree(PENDING_IMPORT_DOCS,ignore_errors=True)
            shutil.rmtree(PENDING_IMPORT_DRAFTS,ignore_errors=True)
        if kind=='cloud_snapshot':
            try:
                rawcon=sqlite3.connect(DB_PATH)
                rawcon.execute("CREATE TABLE IF NOT EXISTS app_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
                for key,value in {
                    'cloud_last_version':str(meta.get('cloud_version') or 0),
                    'cloud_last_sync':datetime.now().isoformat(timespec='seconds')
                }.items():
                    rawcon.execute("INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP",(key,value))
                rawcon.commit(); rawcon.close()
            except Exception as exc:
                log_event(f'Nie udało się zapisać stanu Cloud po restore: {exc}','ERROR')
            msg=f"Pobrano stan Cloud v{meta.get('cloud_version','?')}: {meta.get('source','serwer Cloud')}"
        elif kind=='data_snapshot':
            msg=f"Przywrócono pełny snapshot: {meta.get('source','wybrany plik')}"
        else:
            msg=f"Zaimportowano dane z Installed: {meta.get('source','stara instalacja')}"
    else:
        msg=f"Przywrócono backup: {meta.get('source','wybrana kopia')}"
    PENDING_RESTORE_MARKER.unlink(missing_ok=True)
    log_event(msg,'WARNING'); return msg


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_name(path.name+f'.tmp_{uuid.uuid4().hex}')
    try:
        with tmp.open('wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        try: tmp.unlink(missing_ok=True)
        except OSError: pass


def init_db() -> None:
    with db() as con:
        try:
            con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signature TEXT DEFAULT '',
                internal_signature TEXT DEFAULT '',
                client TEXT DEFAULT '',
                title TEXT NOT NULL,
                court TEXT DEFAULT '',
                department TEXT DEFAULT '',
                category TEXT DEFAULT '',
                subject TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                next_step TEXT DEFAULT '',
                next_date TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS parties (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                role TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                event_date TEXT DEFAULT '',
                event_type TEXT DEFAULT 'Czynność',
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS process_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                event_date TEXT DEFAULT '',
                event_type TEXT DEFAULT 'Inna czynność',
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                court TEXT DEFAULT '',
                signature TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'done',
                document_id INTEGER,
                next_date TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                due_date TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                priority TEXT NOT NULL DEFAULT 'normal',
                depends_on TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                doc_date TEXT DEFAULT '',
                received_date TEXT DEFAULT '',
                doc_type TEXT DEFAULT 'Inne',
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                stored_name TEXT DEFAULT '',
                original_name TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS case_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                target_case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                relation_type TEXT NOT NULL DEFAULT 'related',
                note TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK (source_case_id <> target_case_id)
            );
            CREATE TABLE IF NOT EXISTS case_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                note TEXT NOT NULL,
                author TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS case_external_signatures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                label TEXT NOT NULL,
                signature TEXT NOT NULL,
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE
            );
            CREATE TABLE IF NOT EXISTS case_tags (
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                PRIMARY KEY(case_id, tag_id)
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                author_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                function TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS user_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS user_case_pins (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(user_id,case_id)
            );
            CREATE TABLE IF NOT EXISTS user_case_recent (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(user_id,case_id)
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER,
                entity_type TEXT NOT NULL DEFAULT '',
                entity_id INTEGER,
                action TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                author TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS recycle_bin (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id INTEGER,
                case_id INTEGER,
                label TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL,
                deleted_by TEXT NOT NULL DEFAULT '',
                deleted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS immutable_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER,
                entity_type TEXT NOT NULL DEFAULT '',
                entity_id INTEGER,
                action TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                author TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                user_id INTEGER,
                remote_addr TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL DEFAULT 'person',
                display_name TEXT NOT NULL,
                first_name TEXT DEFAULT '',
                last_name TEXT DEFAULT '',
                company_name TEXT DEFAULT '',
                pesel TEXT DEFAULT '',
                nip TEXT DEFAULT '',
                krs TEXT DEFAULT '',
                email TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                address TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS case_entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE RESTRICT,
                role TEXT NOT NULL DEFAULT 'Uczestnik',
                notes TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS checklist_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS checklist_template_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER NOT NULL REFERENCES checklist_templates(id) ON DELETE CASCADE,
                label TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS case_checklist_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                label TEXT NOT NULL,
                is_done INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                template_id INTEGER,
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS writing_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER REFERENCES cases(id) ON DELETE SET NULL,
                title TEXT NOT NULL,
                doc_type TEXT DEFAULT 'Pismo procesowe',
                status TEXT NOT NULL DEFAULT 'Roboczy',
                due_date TEXT DEFAULT '',
                content TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                stored_name TEXT DEFAULT '',
                original_name TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                updated_by TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_cases_signature ON cases(signature);
            CREATE INDEX IF NOT EXISTS idx_cases_title ON cases(title);
            CREATE INDEX IF NOT EXISTS idx_events_case ON events(case_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_case ON tasks(case_id);
            CREATE INDEX IF NOT EXISTS idx_process_events_case ON process_events(case_id,event_date);
            CREATE INDEX IF NOT EXISTS idx_docs_case ON documents(case_id);
            CREATE INDEX IF NOT EXISTS idx_parties_case ON parties(case_id);
            CREATE INDEX IF NOT EXISTS idx_notes_case ON case_notes(case_id);
            CREATE INDEX IF NOT EXISTS idx_extsig_case ON case_external_signatures(case_id);
            CREATE INDEX IF NOT EXISTS idx_extsig_signature ON case_external_signatures(signature);
            CREATE INDEX IF NOT EXISTS idx_extsig_label ON case_external_signatures(label);
            CREATE INDEX IF NOT EXISTS idx_rel_source ON case_relations(source_case_id);
            CREATE INDEX IF NOT EXISTS idx_rel_target ON case_relations(target_case_id);
            CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);
            CREATE INDEX IF NOT EXISTS idx_case_tags_case ON case_tags(case_id);
            CREATE INDEX IF NOT EXISTS idx_case_tags_tag ON case_tags(tag_id);
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_expires ON user_sessions(expires_at);
            CREATE INDEX IF NOT EXISTS idx_writing_projects_case ON writing_projects(case_id);
            CREATE INDEX IF NOT EXISTS idx_writing_projects_status ON writing_projects(status);
            """
        )

        def ensure_columns(table: str, columns: dict[str, str]):
            existing = {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
            for col, ddl in columns.items():
                if col not in existing:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

        ensure_columns("cases", {
            "internal_signature": "TEXT DEFAULT ''",
            "client": "TEXT DEFAULT ''",
            "created_by": "TEXT DEFAULT ''",
            "updated_by": "TEXT DEFAULT ''",
            "waiting_for": "TEXT DEFAULT ''",
            "lead_user_id": "INTEGER",
        })
        ensure_columns("parties", {"created_by": "TEXT DEFAULT ''", "updated_by": "TEXT DEFAULT ''", "created_at": "TEXT DEFAULT ''"})
        ensure_columns("events", {"created_by": "TEXT DEFAULT ''", "updated_by": "TEXT DEFAULT ''"})
        ensure_columns("process_events", {
            "event_date": "TEXT DEFAULT ''", "event_type": "TEXT DEFAULT 'Inna czynność'",
            "title": "TEXT DEFAULT ''", "description": "TEXT DEFAULT ''", "court": "TEXT DEFAULT ''",
            "signature": "TEXT DEFAULT ''", "status": "TEXT NOT NULL DEFAULT 'done'", "document_id": "INTEGER",
            "next_date": "TEXT DEFAULT ''", "created_by": "TEXT DEFAULT ''", "updated_by": "TEXT DEFAULT ''",
            "created_at": "TEXT DEFAULT ''", "updated_at": "TEXT DEFAULT ''"
        })
        ensure_columns("tasks", {
            "created_by": "TEXT DEFAULT ''", "updated_by": "TEXT DEFAULT ''", "assigned_user_id": "INTEGER",
            "deadline_base_date": "TEXT DEFAULT ''", "deadline_days": "INTEGER", "deadline_rule": "TEXT DEFAULT ''",
            "deadline_source": "TEXT DEFAULT ''", "deadline_manual": "INTEGER NOT NULL DEFAULT 0",
            "completed_at": "TEXT DEFAULT ''", "completed_by": "TEXT DEFAULT ''",
            "task_type": "TEXT DEFAULT 'Zadanie'"
        })
        ensure_columns("documents", {
            "received_date": "TEXT DEFAULT ''", "delivered_date": "TEXT DEFAULT ''",
            "sender": "TEXT DEFAULT ''", "document_author": "TEXT DEFAULT ''", "tags": "TEXT DEFAULT ''",
            "linked_task_id": "INTEGER", "created_by": "TEXT DEFAULT ''", "updated_by": "TEXT DEFAULT ''",
            "file_hash": "TEXT DEFAULT ''", "extracted_text": "TEXT DEFAULT ''", "indexed_at": "TEXT DEFAULT ''",
            "doc_status": "TEXT DEFAULT 'Aktywny'", "ocr_used": "INTEGER NOT NULL DEFAULT 0",
            "ocr_status": "TEXT DEFAULT ''", "ocr_language": "TEXT DEFAULT ''",
            "parent_document_id": "INTEGER", "attachment_order": "INTEGER NOT NULL DEFAULT 0"
        })
        ensure_columns("cases", {"closed_edit_unlocked": "INTEGER NOT NULL DEFAULT 0"})
        ensure_columns("parties", {"entity_id": "INTEGER"})
        ensure_columns("case_relations", {"note": "TEXT DEFAULT ''", "created_by": "TEXT DEFAULT ''", "updated_by": "TEXT DEFAULT ''"})
        ensure_columns("case_notes", {"author": "TEXT DEFAULT ''", "created_at": "TEXT DEFAULT ''"})
        ensure_columns("users", {"function": "TEXT NOT NULL DEFAULT ''"})
        ensure_columns("case_checklist_items", {"completed_at": "TEXT DEFAULT ''", "completed_by": "TEXT DEFAULT ''"})

        con.execute("""CREATE TABLE IF NOT EXISTS saved_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            target TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id,name)
        )""")

        con.execute("""CREATE TABLE IF NOT EXISTS draft_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            doc_type TEXT NOT NULL DEFAULT 'Pismo procesowe',
            content TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            created_by TEXT DEFAULT '',
            updated_by TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS draft_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES writing_projects(id) ON DELETE CASCADE,
            version_no INTEGER NOT NULL,
            title TEXT NOT NULL,
            doc_type TEXT DEFAULT '',
            status TEXT DEFAULT '',
            due_date TEXT DEFAULT '',
            content TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            stored_name TEXT DEFAULT '',
            original_name TEXT DEFAULT '',
            change_note TEXT DEFAULT '',
            created_by TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(project_id,version_no)
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS system_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            check_type TEXT NOT NULL,
            result TEXT NOT NULL,
            details TEXT DEFAULT '',
            created_by TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_draft_versions_project ON draft_versions(project_id,version_no DESC)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_documents_linked_task ON documents(linked_task_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_documents_delivered ON documents(delivered_date)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_documents_parent ON documents(parent_document_id,attachment_order,id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_tasks_type ON tasks(task_type,status,due_date)")

        # HOTFIX 0.12.13: wersja 0.13 używała w audit_log nazw actor/details,
        # podczas gdy stabilna gałąź 0.12 używa author/description. Ponieważ DATA_DIR
        # jest wspólny dla wersji, po powrocie z 0.13 część spraw z historią zmian
        # kończyła się błędem sqlite3.Row: "No item with that key".
        ensure_columns("audit_log", {
            "case_id": "INTEGER",
            "entity_type": "TEXT NOT NULL DEFAULT ''",
            "entity_id": "INTEGER",
            "action": "TEXT NOT NULL DEFAULT ''",
            "description": "TEXT NOT NULL DEFAULT ''",
            "author": "TEXT NOT NULL DEFAULT ''",
            "created_at": "TEXT DEFAULT ''",
        })
        audit_cols = {r[1] for r in con.execute("PRAGMA table_info(audit_log)").fetchall()}
        if "details" in audit_cols:
            con.execute("UPDATE audit_log SET description=COALESCE(NULLIF(description,''),details,'') WHERE COALESCE(description,'')='' AND COALESCE(details,'')<>''")
        if "actor" in audit_cols:
            con.execute("UPDATE audit_log SET author=COALESCE(NULLIF(author,''),actor,'') WHERE COALESCE(author,'')='' AND COALESCE(actor,'')<>''")

        # Usuń wyłącznie historyczne triggery pozostawione przez eksperymentalną 0.13.
        # Stabilna gałąź zapisuje audyt jawnie w kodzie i nie potrzebuje tych triggerów;
        # ich pozostawienie powodowałoby podwójne wpisy historii.
        for legacy_trigger in (
            "audit_cases_u", "audit_tasks_i", "audit_tasks_u", "audit_tasks_d",
            "audit_docs_i", "audit_docs_u", "audit_events_i", "audit_notes_i"
        ):
            con.execute(f"DROP TRIGGER IF EXISTS {legacy_trigger}")
        con.execute("CREATE INDEX IF NOT EXISTS idx_cases_internal_signature ON cases(internal_signature)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_cases_client ON cases(client)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_cases_lead_user ON cases(lead_user_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_tasks_assigned_user ON tasks(assigned_user_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_recent_user ON user_case_recent(user_id, opened_at)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_log(case_id, created_at)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_trash_deleted ON recycle_bin(deleted_at)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_immutable_audit_case ON immutable_audit(case_id, created_at)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(display_name)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_entities_pesel ON entities(pesel)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_entities_nip ON entities(nip)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_entities_krs ON entities(krs)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_case_entities_case ON case_entities(case_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_case_entities_entity ON case_entities(entity_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_checklist_case ON case_checklist_items(case_id,sort_order)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_doc_hash ON documents(file_hash)")
        try:
            con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS document_fts USING fts5(document_id UNINDEXED, case_id UNINDEXED, title, filename, body)")
        except sqlite3.DatabaseError:
            pass

        con.execute("CREATE INDEX IF NOT EXISTS idx_cases_status_nextdate ON cases(status,next_date)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_cases_nextdate ON cases(next_date,id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status_due_case ON tasks(status,due_date,case_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_date_case ON events(event_date,case_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_process_events_date_case ON process_events(event_date,case_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_process_events_nextdate_case ON process_events(next_date,case_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_docs_status_case ON documents(doc_status,case_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_writing_projects_status_due ON writing_projects(status,due_date,updated_at)")

        # Warstwa 0.3: czytelny widok sprawy, alerty, relacje i lokalna biblioteka prawa.
        # CREATE IF NOT EXISTS + INSERT OR IGNORE zachowują pełną zgodność z danymi DEV9.
        ensure_smart_schema(con)
        # Scala stare osobne monity/alerty i zadania. Operacja jest idempotentna.
        reconcile_task_alerts(con)

        # Jawny numer wersji schematu przygotowuje bezpieczne migracje.
        con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

        # 0.15.x automatycznie wstawiała do każdej pustej instalacji prywatny zestaw
        # danych demonstracyjnych. W 0.2 demo jest wyłącznie jawnie opt-in.
        count = con.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        seed_requested = os.getenv("RK_KANCELARIA_SEED_DEMO", "0").strip().lower() in {"1", "true", "yes", "tak"}
        if count == 0 and seed_requested:
            seed_demo(con)


def password_hash(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    if salt_hex:
        salt = bytes.fromhex(salt_hex)
    else:
        salt = secrets.token_bytes(16)
        salt_hex = salt.hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return digest.hex(), salt_hex


def verify_password(password: str, expected_hash: str, salt_hex: str) -> bool:
    try:
        actual, _ = password_hash(password, salt_hex)
        return hmac.compare_digest(actual, expected_hash)
    except Exception:
        return False


def user_count() -> int:
    with db() as con:
        return con.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def normalize_username(value: str) -> str:
    """Pozwala na spacje w loginie, ale usuwa spacje skrajne i normalizuje wielokrotne odstępy."""
    value = (value or '').strip()
    value = re.sub(r"\s+", " ", value)
    return value[:80]


def valid_username(value: str) -> bool:
    value = normalize_username(value)
    if not (3 <= len(value) <= 80):
        return False
    if not any(ch.isalnum() for ch in value):
        return False
    return all(ch.isalnum() or ch in " ._@-" for ch in value)


def make_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires = datetime.fromtimestamp(time.time() + SESSION_HOURS * 3600).strftime("%Y-%m-%d %H:%M:%S")
    with db() as con:
        con.execute("DELETE FROM user_sessions WHERE expires_at < datetime('now','localtime')")
        con.execute("INSERT INTO user_sessions(token_hash,user_id,expires_at) VALUES(?,?,?)", (token_hash, user_id, expires))
    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE.pop(token_hash, None)
        _SESSION_TOUCH[token_hash] = time.monotonic()
    return token


def session_user(token: str):
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = time.monotonic()
    with _SESSION_CACHE_LOCK:
        cached = _SESSION_CACHE.get(token_hash)
        if cached and now - cached[0] < SESSION_CACHE_SECONDS:
            return cached[1]
    with db() as con:
        row = con.execute("""SELECT u.* FROM user_sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=? AND s.expires_at >= datetime('now','localtime') AND u.is_active=1""", (token_hash,)).fetchone()
        if row:
            user = dict(row)
            do_touch = False
            with _SESSION_CACHE_LOCK:
                last_touch = _SESSION_TOUCH.get(token_hash, 0.0)
                if now - last_touch >= SESSION_TOUCH_SECONDS:
                    _SESSION_TOUCH[token_hash] = now
                    do_touch = True
            if do_touch:
                con.execute("UPDATE user_sessions SET last_seen=CURRENT_TIMESTAMP WHERE token_hash=?", (token_hash,))
        else:
            user = None
            con.execute("DELETE FROM user_sessions WHERE token_hash=?", (token_hash,))
    with _SESSION_CACHE_LOCK:
        if user:
            _SESSION_CACHE[token_hash] = (now, user)
        else:
            _SESSION_CACHE.pop(token_hash, None)
            _SESSION_TOUCH.pop(token_hash, None)
    return user


def destroy_session(token: str) -> None:
    if not token:
        return
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with db() as con:
        con.execute("DELETE FROM user_sessions WHERE token_hash=?", (token_hash,))
    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE.pop(token_hash, None)
        _SESSION_TOUCH.pop(token_hash, None)


def current_request_user():
    return getattr(_REQUEST_CONTEXT, "user", None)


def client_presence_script() -> str:
    """Skrypt obecności karty oparty o WebSocket.

    Zamknięcie karty automatycznie zrywa WebSocket, co serwer wykrywa natychmiast.
    pagehide pozostaje szybką ścieżką i miejscem końcowego autosave formularzy.
    """
    if not AUTO_SHUTDOWN:
        return ""
    return r"""
(function(){
  let tabId=sessionStorage.getItem('sprawnik_tab_id');
  if(!tabId){tabId=(crypto.randomUUID?crypto.randomUUID():String(Date.now())+'-'+Math.random());sessionStorage.setItem('sprawnik_tab_id',tabId);}
  let ws=null;
  try{
    const proto=(location.protocol==='https:'?'wss://':'ws://');
    ws=new WebSocket(proto+location.host+'/system/ws?tab='+encodeURIComponent(tabId));
  }catch(e){}
  function heartbeat(){fetch('/system/heartbeat?tab='+encodeURIComponent(tabId),{method:'GET',cache:'no-store',credentials:'same-origin'}).catch(()=>{});}
  heartbeat();
  const hb=setInterval(heartbeat,8000);
  window.addEventListener('pagehide',()=>{
    clearInterval(hb);
    try{navigator.sendBeacon('/system/closing?tab='+encodeURIComponent(tabId),'');}catch(e){}
    try{if(ws && ws.readyState<2) ws.close(1000,'karta zamknieta');}catch(e){}
  });
})();
"""


def auth_layout(title: str, body: str) -> str:
    return f"""<!doctype html><html lang='pl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
    <title>{esc(title)} – {APP_NAME}</title><link rel='icon' type='image/x-icon' href='/assets/rk_kancelaria.ico'>
    <style>body{{margin:0;font-family:Inter,system-ui,-apple-system,'Segoe UI',sans-serif;background:linear-gradient(145deg,#061a2b,#0a3932);min-height:100vh;display:grid;place-items:center;color:#142720}}.box{{width:min(440px,calc(100% - 32px));background:#fff;border-radius:16px;padding:28px;box-shadow:0 20px 60px rgba(0,0,0,.32);border:1px solid #d6b46a}}.brand{{text-align:center;margin-bottom:22px}}.brand img{{width:86px;height:86px;border-radius:18px;border:1px solid #d6b46a}}h1{{margin:12px 0 4px;color:#0a3932;font-family:Georgia,serif}}.sub{{color:#677b75;font-size:14px;margin-bottom:20px}}label{{display:block;font-size:12px;font-weight:700;margin:12px 0 5px;color:#405b54}}input{{width:100%;box-sizing:border-box;padding:11px;border:1px solid #cad8d2;border-radius:8px;font:inherit}}button{{width:100%;margin-top:18px;padding:11px;border:0;border-radius:8px;background:linear-gradient(135deg,#0d5b4b,#083d35);color:white;font-weight:750;cursor:pointer}}.error{{padding:10px 12px;border-radius:8px;background:#fee2e2;color:#991b1b;margin-bottom:12px}}.note{{padding:10px 12px;border-radius:8px;background:#f7edcf;color:#76591f;margin-bottom:12px;font-size:13px}}.author{{text-align:center;color:#8b7a50;font-size:11px;margin-top:20px;letter-spacing:.04em}}</style></head><body><div class='box'><div class='brand'><img src='/assets/rk_kancelaria_logo.png' alt='RK'><h1>{APP_NAME}</h1><div class='sub'>Baza spraw · v{VERSION}</div></div>{body}<div class='author'>AUTOR PROGRAMU · {APP_AUTHOR}</div></div><script>{client_presence_script()}</script></body></html>"""

def seed_demo(con: sqlite3.Connection) -> None:
    cases = [
        ("III Ca 1054/26", "Ochrona przed przemocą – Aśka / Michał Sobol", "Sąd Okręgowy w Katowicach", "", "rodzinna / przemoc domowa", "Środki ochrony przed przemocą domową", "waiting", "Wniosek o uzasadnienie postanowienia; następnie analiza apelacji i uzasadnienia", "2026-09-07", "02.09.2026 SO zmienił postanowienie SR i zastosował środki ochronne."),
        ("III Nsm 284/25", "Sprawa rodzinna dotycząca Alicji", "Sąd Rejonowy w Tychach", "III Wydział Rodzinny i Nieletnich", "rodzinna", "Miejsce zamieszkania, kontakty, władza rodzicielska", "suspended", "Po uzasadnieniu III Ca 1054/26 – przedłożyć postanowienie wraz z uzasadnieniem", "", "Draft pisma w zawieszeniu do czasu uzyskania uzasadnienia SO."),
        ("", "Alimenty Alicji", "", "III RC", "alimenty", "Alimenty na rzecz Alicji", "waiting", "Przedłożyć postanowienie III Ca 1054/26 z uzasadnieniem; czekać na SO ws. zabezpieczenia i wezwanie do PIT", "", "Pismo w zawieszeniu. Oczekiwanie na rozstrzygnięcie II instancji w przedmiocie zabezpieczenia oraz wezwanie do przedłożenia PIT."),
        ("III RC 181/26", "Alimenty Kariny", "Sąd Rejonowy w Tychach", "III Wydział Rodzinny i Nieletnich", "alimenty", "Alimenty pełnoletniego dziecka", "waiting", "Oczekiwanie na postanowienie SO rozpoznające zażalenie na zabezpieczenie", "", "Postanowienie II instancji może pojawić się w najbliższych dniach."),
        ("", "Cecylia Kłosowska przeciwko Michałowi Sobolowi – zapłata", "", "", "cywilna", "Zapłata za bezumowne korzystanie z lokalu i opłaty", "active", "Ustalić, czy odbędzie się kolejna mediacja; przygotować się do rozprawy", "2026-09-30", "Roszczenie główne ok. 27 500,57 zł + odsetki. Mediacja 25.08.2026; możliwy kolejny termin 14–15.09.2026."),
        ("", "Zachowek po babci", "", "", "cywilna / spadkowa", "Zachowek", "waiting", "Czekać na dalszy ruch sądu po opinii biegłego", "", "21.08.2026 wpłynęła opinia biegłego wraz z aktami."),
        ("", "Sprawa karna – podsłuch / art. 267 k.k.", "", "", "karna", "Podejrzenie czynu z art. 267 § 3 i § 4 k.k.", "waiting", "Oczekiwanie na dalsze czynności Policji / prokuratury", "", "Postępowanie przygotowawcze w toku."),
    ]
    ids = []
    for c in cases:
        cur = con.execute(
            "INSERT INTO cases(signature,title,court,department,category,subject,status,next_step,next_date,notes) VALUES(?,?,?,?,?,?,?,?,?,?)", c
        )
        ids.append(cur.lastrowid)

    # parties
    parties = [
        (ids[0], "Aśka", "wnioskodawczyni", ""), (ids[0], "Michał Sobol", "uczestnik", ""),
        (ids[1], "Alicja", "małoletnia", ""), (ids[1], "Aśka", "matka", ""), (ids[1], "Michał Sobol", "ojciec", ""),
        (ids[2], "Alicja", "uprawniona", ""), (ids[2], "Michał Sobol", "zobowiązany / strona", ""),
        (ids[3], "Karina", "powódka", ""),
        (ids[4], "Cecylia Kłosowska", "powódka", ""), (ids[4], "Michał Sobol", "pozwany", ""),
    ]
    con.executemany("INSERT INTO parties(case_id,name,role,notes) VALUES(?,?,?,?)", parties)

    events = [
        (ids[0], "2026-09-02", "Orzeczenie", "Postanowienie Sądu Okręgowego", "Zmiana postanowienia SR i zastosowanie środków ochronnych."),
        (ids[0], "2026-09-07", "Wysłanie pisma", "Plan: wniosek o uzasadnienie", "Wniosek o sporządzenie i doręczenie uzasadnienia postanowienia SO."),
        (ids[4], "2026-08-25", "Mediacja", "Pierwsza mediacja", "Propozycja pozwanego ok. 1 000 zł."),
        (ids[4], "2026-09-30", "Rozprawa", "Rozprawa", "Najbliższy znany termin rozprawy."),
        (ids[5], "2026-08-21", "Wpływ pisma", "Wpływ opinii biegłego", "Opinia biegłego wpłynęła wraz z aktami."),
    ]
    con.executemany("INSERT INTO events(case_id,event_date,event_type,title,description) VALUES(?,?,?,?,?)", events)

    tasks = [
        (ids[0], "Wysłać wniosek o uzasadnienie", "2026-09-07", "open", "high", "", ""),
        (ids[0], "Po uzasadnieniu: analiza apelacja → orzeczenie → uzasadnienie", "", "open", "high", "Doręczenie uzasadnienia", "Wypisać mocne i słabe strony oraz które zarzuty apelacji zostały uwzględnione."),
        (ids[1], "Przedłożyć postanowienie SO wraz z uzasadnieniem", "", "open", "high", "Doręczenie uzasadnienia III Ca 1054/26", "Pismo pozostaje w zawieszeniu."),
        (ids[2], "Przedłożyć postanowienie SO wraz z uzasadnieniem", "", "open", "high", "Doręczenie uzasadnienia III Ca 1054/26", ""),
        (ids[2], "Sprawdzić rozstrzygnięcie SO ws. zabezpieczenia", "", "open", "normal", "", ""),
        (ids[2], "Sprawdzić wezwanie do przedłożenia PIT", "", "open", "normal", "", ""),
        (ids[3], "Sprawdzić postanowienie SO ws. naszego zażalenia", "", "open", "high", "", ""),
        (ids[4], "Potwierdzić, czy odbędzie się druga mediacja", "2026-09-10", "open", "normal", "", "Potencjalne terminy 14–15.09.2026."),
        (ids[4], "Przygotować się do rozprawy", "2026-09-30", "open", "high", "", ""),
    ]
    con.executemany("INSERT INTO tasks(case_id,title,due_date,status,priority,depends_on,notes) VALUES(?,?,?,?,?,?,?)", tasks)


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def fmt_date(s: str) -> str:
    if not s:
        return "—"
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%d.%m.%Y")
    except Exception:
        return esc(s)


def money_to_cents(value) -> int:
    """Kwoty przechowujemy jako całkowitą liczbę groszy, bez błędów float."""
    raw = str(value or '').strip().replace('\u00a0', '').replace(' ', '').replace(',', '.')
    if not raw:
        return 0
    try:
        amount = Decimal(raw).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return 0
    return int(amount * 100)


def fmt_money(cents, currency: str = 'PLN') -> str:
    try:
        amount = Decimal(int(cents or 0)) / Decimal(100)
    except (TypeError, ValueError, InvalidOperation):
        amount = Decimal(0)
    rendered = f"{amount:,.2f}".replace(',', ' ').replace('.', ',')
    return f"{rendered} {esc(currency or 'PLN')}"


def money_input(cents) -> str:
    try:
        return f"{Decimal(int(cents or 0)) / Decimal(100):.2f}"
    except (TypeError, ValueError, InvalidOperation):
        return '0.00'



def _easter_sunday(year: int) -> date:
    """Meeus/Jones/Butcher algorithm for Gregorian Easter."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def polish_statutory_holidays(year: int) -> set[date]:
    easter = _easter_sunday(year)
    return {
        date(year,1,1), date(year,1,6),
        easter, easter + timedelta(days=1),
        date(year,5,1), date(year,5,3),
        easter + timedelta(days=49),  # Zielone Świątki
        easter + timedelta(days=60),  # Boże Ciało
        date(year,8,15), date(year,11,1), date(year,11,11),
        date(year,12,25), date(year,12,26),
    }


def _is_non_working_endpoint(d: date) -> bool:
    return d.weekday() >= 5 or d in polish_statutory_holidays(d.year)


def calculate_deadline(base_date: str, days: int, rule: str = 'calendar') -> tuple[str, str]:
    """Pomocniczy kalkulator terminów. Dzień początkowy nie jest liczony.

    calendar: dodaje dni kalendarzowe, a koniec przypadający w sobotę/niedzielę/święto
    przesuwa na najbliższy następny dzień roboczy.
    business: liczy wyłącznie dni robocze (pon-pt bez ustawowych świąt).
    """
    try:
        start = datetime.strptime(base_date, '%Y-%m-%d').date()
    except Exception:
        raise ValueError('Nieprawidłowa data początkowa.')
    if days < 0 or days > 3650:
        raise ValueError('Liczba dni musi mieścić się w zakresie 0–3650.')
    rule = (rule or 'calendar').strip().lower()
    if rule not in {'calendar','business'}:
        rule = 'calendar'
    if rule == 'business':
        d = start
        remaining = days
        while remaining:
            d += timedelta(days=1)
            if d.weekday() < 5 and d not in polish_statutory_holidays(d.year):
                remaining -= 1
        label = 'dni robocze'
    else:
        d = start + timedelta(days=days)
        label = 'dni kalendarzowe'
        while _is_non_working_endpoint(d):
            d += timedelta(days=1)
    return d.isoformat(), label


def safe_filename(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^\w.()\-ąćęłńóśźżĄĆĘŁŃÓŚŹŻ ]+", "_", name, flags=re.UNICODE).strip()
    return name[:180] or "dokument"


def parse_tags(raw: str) -> list[str]:
    out=[]
    seen=set()
    for part in re.split(r"[,;]", raw or ""):
        tag=part.strip()
        if not tag:
            continue
        key=tag.casefold()
        if key not in seen:
            seen.add(key)
            out.append(tag[:80])
    return out


def set_case_tags(con: sqlite3.Connection, case_id: int, raw: str) -> None:
    con.execute("DELETE FROM case_tags WHERE case_id=?", (case_id,))
    for name in parse_tags(raw):
        row=con.execute("SELECT id FROM tags WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        tag_id=row[0] if row else con.execute("INSERT INTO tags(name) VALUES(?)", (name,)).lastrowid
        con.execute("INSERT OR IGNORE INTO case_tags(case_id,tag_id) VALUES(?,?)", (case_id,tag_id))
    con.execute("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM case_tags)")




def _change_value(value, limit: int = 140) -> str:
    if value is None or str(value) == '':
        return '—'
    text = str(value).replace('\r', ' ').replace('\n', ' ↵ ').strip()
    if len(text) > limit:
        text = text[:limit-1] + '…'
    return f'„{text}”'


def describe_changes(old, new_values: dict, labels: dict[str, str], *, compact_fields: set[str] | None = None) -> str:
    """Czytelny diff do historii zmian. Jedna linia = jedno pole, co ułatwia scalanie autosave."""
    if not old:
        return ''
    compact_fields = compact_fields or set()
    lines = []
    for field, label in labels.items():
        try:
            before = row_get(old, field, '')
        except Exception:
            before = ''
        after = new_values.get(field, '')
        if str(before or '') == str(after or ''):
            continue
        if field in compact_fields:
            btxt = str(before or '')
            atxt = str(after or '')
            lines.append(f"• {label}: zmieniono ({len(btxt)} → {len(atxt)} znaków)")
        else:
            lines.append(f"• {label}: {_change_value(before)} → {_change_value(after)}")
    return '\n'.join(lines)


def _merge_audit_descriptions(previous: str, current: str) -> str:
    """Scal autosave: zachowaj pierwotne 'przed' i najnowsze 'po' dla każdego pola."""
    previous = (previous or '').strip()
    current = (current or '').strip()
    if not previous:
        return current
    if not current or current == previous:
        return previous
    lines = []
    by_label: dict[str, int] = {}
    change_re = re.compile(r'^• ([^:]+): (.+?) → (.+)$')

    def add(line: str):
        line = line.strip()
        if not line:
            return
        m = change_re.match(line)
        if not m:
            if line not in lines:
                lines.append(line)
            return
        label, before, after = m.groups()
        if label in by_label:
            idx = by_label[label]
            old_match = change_re.match(lines[idx])
            original_before = old_match.group(2) if old_match else before
            lines[idx] = f"• {label}: {original_before} → {after}"
        else:
            by_label[label] = len(lines)
            lines.append(line)

    for line in previous.splitlines():
        add(line)
    for line in current.splitlines():
        add(line)
    return '\n'.join(lines)


def audit_target_html(row) -> str:
    """Odnośnik z historii bezpośrednio do zmienionego elementu, gdy ma sens."""
    et = str(row_get(row, 'entity_type', '') or '')
    try:
        eid = int(row_get(row, 'entity_id', 0) or 0)
    except Exception:
        eid = 0
    try:
        cid = int(row_get(row, 'case_id', 0) or 0)
    except Exception:
        cid = 0
    action = str(row_get(row, 'action', '') or '')
    if not eid or 'Usunięto' in action:
        return ''
    if et == 'document':
        return f"<a class='btn small' href='/document/{eid}/open'>Otwórz dokument</a>"
    if et == 'writing_project':
        return f"<a class='btn small' href='/draft/{eid}'>Otwórz projekt pisma</a>"
    if et == 'task':
        return f"<a class='btn small' href='/task/{eid}/edit'>Otwórz zadanie</a>"
    if et == 'process_event' and cid:
        return f"<a class='btn small' href='/case/{cid}/history#process'>Otwórz historię procesu</a>"
    if et == 'case' and cid:
        return f"<a class='btn small' href='/case/{cid}'>Otwórz sprawę</a>"
    if cid:
        return f"<a class='btn small' href='/case/{cid}'>Otwórz sprawę</a>"
    return ''


def audit_description_html(value: str) -> str:
    return esc(value or '').replace('\n', '<br>')


def full_sqlite_integrity(path: Path) -> tuple[bool, str]:
    """Pełniejsza kontrola niż quick_check; używana ręcznie z ekranu Recovery."""
    if not path.exists():
        return False, 'brak pliku'
    if not _looks_like_sqlite(path):
        return False, 'nieprawidłowy nagłówek SQLite'
    try:
        con=sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30)
        try:
            rows=con.execute('PRAGMA integrity_check').fetchall()
            messages=[str(r[0]) for r in rows]
            ok=(len(messages)==1 and messages[0].lower()=='ok')
            return ok, ('ok' if ok else '; '.join(messages[:25]))
        finally:
            con.close()
    except Exception as exc:
        return False, str(exc)


def draft_template_context(con: sqlite3.Connection, case_id: int | None, author: str='') -> dict[str,str]:
    ctx={
        'DATA': date.today().strftime('%d.%m.%Y'),
        'PEŁNOMOCNIK': author or APP_AUTHOR,
        'SĄD':'', 'SYGNATURA':'', 'SYGNATURA_WEWNĘTRZNA':'', 'KLIENT':'',
        'TYTUŁ_SPRAWY':'', 'PRZEDMIOT':'', 'STRONY':'', 'UCZESTNICY':''
    }
    if not case_id:
        return ctx
    c=con.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
    if not c:
        return ctx
    parties=con.execute('SELECT name,role FROM parties WHERE case_id=? ORDER BY id',(case_id,)).fetchall()
    party_text='; '.join((f"{x['name']} ({x['role']})" if x['role'] else x['name']) for x in parties)
    ctx.update({
        'SĄD': (c['court'] or '') + ((' · '+c['department']) if c['department'] else ''),
        'SYGNATURA': primary_signature_text(case_id,c['signature'],c['internal_signature']),
        'SYGNATURA_WEWNĘTRZNA': c['internal_signature'] or '',
        'KLIENT': c['client'] or '',
        'TYTUŁ_SPRAWY': c['title'] or '',
        'PRZEDMIOT': c['subject'] or '',
        'STRONY': party_text,
        'UCZESTNICY': party_text,
    })
    return ctx


def fill_draft_template(content: str, context: dict[str,str]) -> str:
    text=content or ''
    for key,value in context.items():
        text=text.replace('{{'+key+'}}', value or '')
    return text


def save_draft_version(con: sqlite3.Connection, project_id: int, author: str, change_note: str='') -> int | None:
    d=con.execute('SELECT * FROM writing_projects WHERE id=?',(project_id,)).fetchone()
    if not d:
        return None
    n=int(con.execute('SELECT COALESCE(MAX(version_no),0)+1 FROM draft_versions WHERE project_id=?',(project_id,)).fetchone()[0])
    version_stored=''
    if d['stored_name']:
        src=DRAFTS_DIR/d['stored_name']
        if src.is_file():
            vdir=DRAFTS_DIR/f'wersje_{project_id}'; vdir.mkdir(parents=True,exist_ok=True)
            vname=f"v{n:03d}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{safe_filename(d['original_name'] or src.name)}"
            dst=vdir/vname
            try:
                shutil.copy2(src,dst); version_stored=f'wersje_{project_id}/{vname}'
            except Exception:
                version_stored=''
    cur=con.execute("INSERT INTO draft_versions(project_id,version_no,title,doc_type,status,due_date,content,notes,stored_name,original_name,change_note,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (project_id,n,d['title'],d['doc_type'],d['status'],d['due_date'],d['content'],d['notes'],version_stored,d['original_name'],change_note,author))
    return cur.lastrowid


def save_document_file_version(con: sqlite3.Connection, document_id: int, author: str) -> int | None:
    """Zachowaj poprzedni plik przed podmianą; metadane nie wskazują na usunięty plik."""
    d=con.execute('SELECT * FROM documents WHERE id=?',(document_id,)).fetchone()
    if not d or not d['stored_name']:
        return None
    src=FILES_DIR/f"sprawa_{d['case_id']}"/d['stored_name']
    if not src.is_file():
        return None
    n=int(con.execute('SELECT COALESCE(MAX(version_no),0)+1 FROM document_versions WHERE document_id=?',(document_id,)).fetchone()[0])
    version_dir=FILES_DIR/f"sprawa_{d['case_id']}"/f"wersje_dokumentu_{document_id}"
    version_dir.mkdir(parents=True,exist_ok=True)
    original=safe_filename(d['original_name'] or src.name)
    vname=f"v{n:03d}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{original}"
    dst=version_dir/vname
    shutil.copy2(src,dst)
    stored=f"wersje_dokumentu_{document_id}/{vname}"
    cur=con.execute("""INSERT INTO document_versions(document_id,version_no,stored_name,original_name,file_hash,title,description,created_by)
                       VALUES(?,?,?,?,?,?,?,?)""",(document_id,n,stored,d['original_name'],d['file_hash'],d['title'],d['description'],author))
    return cur.lastrowid


def create_data_snapshot_zip() -> tuple[bytes,str]:
    """Pełny przenośny snapshot: baza + dokumenty + projekty. Nie zawiera sekretów DPAPI."""
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    tmp=DATA_DIR/f'.snapshot_{uuid.uuid4().hex}.sqlite3'
    try:
        _sqlite_backup(DB_PATH,tmp)
        # Pełny snapshot nie przenosi lokalnych sesji ani sekretów urządzenia.
        try:
            sc=sqlite3.connect(tmp)
            sc.execute("DELETE FROM user_sessions")
            sc.execute("DELETE FROM app_settings WHERE key IN ('backup_key_dpapi','backup_key_verifier','cloud_token')")
            sc.commit(); sc.close()
        except Exception as exc:
            log_event(f'Nie udało się oczyścić lokalnych sekretów w snapshot: {exc}','WARNING')
        ok,why=sqlite_integrity(tmp)
        if not ok:
            raise RuntimeError(f'Kopia bazy nie przeszła quick_check: {why}')
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            z.write(tmp,'sprawnik.sqlite3')
            meta={
                'format':'RK-KANCELARIA-DATA-SNAPSHOT','version':1,'app_version':VERSION,
                'schema_version':SCHEMA_VERSION,'created_at':datetime.now().isoformat(timespec='seconds')
            }
            z.writestr('snapshot.json',json.dumps(meta,ensure_ascii=False,indent=2))
            for root,prefix in ((FILES_DIR,'dokumenty'),(DRAFTS_DIR,'projekty_pism')):
                if root.exists():
                    for fp in root.rglob('*'):
                        if fp.is_file():
                            try: z.write(fp,f"{prefix}/{fp.relative_to(root).as_posix()}")
                            except OSError: pass
        return out.getvalue(),f'RK_KANCELARIA_snapshot_{stamp}.zip'
    finally:
        try: tmp.unlink(missing_ok=True)
        except OSError: pass


def cloud_config(con: sqlite3.Connection) -> dict[str,str]:
    return {
        'url':(os.getenv('RK_CLOUD_URL','').strip() or settings_get(con,'cloud_url','')),
        'office_id':(os.getenv('RK_CLOUD_OFFICE_ID','').strip() or settings_get(con,'cloud_office_id','default')),
        'token':(os.getenv('RK_CLOUD_TOKEN','').strip() or settings_get(con,'cloud_token','')),
        'last_sync':settings_get(con,'cloud_last_sync',''),
        'last_version':settings_get(con,'cloud_last_version','0'),
    }



def schedule_data_snapshot_restore(raw: bytes, source: str='snapshot', cloud_version: int=0) -> tuple[bool,str]:
    """Zweryfikuj pełny snapshot i przygotuj bezpieczne przełączenie po restarcie."""
    try:
        z=zipfile.ZipFile(io.BytesIO(raw),'r')
        names=set(z.namelist())
        if 'snapshot.json' not in names or 'sprawnik.sqlite3' not in names:
            return False,'Snapshot nie zawiera snapshot.json i sprawnik.sqlite3.'
        meta=json.loads(z.read('snapshot.json').decode('utf-8'))
        if meta.get('format')!='RK-KANCELARIA-DATA-SNAPSHOT':
            return False,'Nieprawidłowy format snapshotu RK KANCELARIA.'
        try: source_schema=int(meta.get('schema_version') or 0)
        except Exception: source_schema=0
        if source_schema>SCHEMA_VERSION:
            return False,f'Snapshot korzysta z nowszego schematu ({source_schema}) niż ta aplikacja ({SCHEMA_VERSION}). Najpierw zaktualizuj RK KANCELARIA.'
        PENDING_RESTORE_DIR.mkdir(parents=True,exist_ok=True)
        tmp=PENDING_RESTORE_DB.with_suffix('.sqlite3.tmp')
        atomic_write_bytes(tmp,z.read('sprawnik.sqlite3'))
        ok,why=sqlite_integrity(tmp)
        if not ok:
            tmp.unlink(missing_ok=True); return False,f'Baza ze snapshotu nie przeszła quick_check: {why}'
        os.replace(tmp,PENDING_RESTORE_DB)
        shutil.rmtree(PENDING_IMPORT_DOCS,ignore_errors=True); shutil.rmtree(PENDING_IMPORT_DRAFTS,ignore_errors=True)
        PENDING_IMPORT_DOCS.mkdir(parents=True,exist_ok=True); PENDING_IMPORT_DRAFTS.mkdir(parents=True,exist_ok=True)
        total_unpacked=0
        max_unpacked=2*1024*1024*1024
        for info in z.infolist():
            name=info.filename.replace('\\','/')
            if info.is_dir(): continue
            if name.startswith('dokumenty/'):
                rel=name[len('dokumenty/'):]
                root=PENDING_IMPORT_DOCS
            elif name.startswith('projekty_pism/'):
                rel=name[len('projekty_pism/'):]
                root=PENDING_IMPORT_DRAFTS
            else:
                continue
            parts=[x for x in Path(rel).parts if x not in {'','.','..'}]
            if not parts or any('/' in x or '\\' in x for x in parts): continue
            total_unpacked += int(info.file_size or 0)
            if total_unpacked>max_unpacked:
                raise ValueError('Snapshot po rozpakowaniu przekracza limit bezpieczeństwa 2 GB.')
            dest=root.joinpath(*parts)
            dest.parent.mkdir(parents=True,exist_ok=True)
            atomic_write_bytes(dest,z.read(info))
        marker={
            'kind':'cloud_snapshot' if cloud_version else 'data_snapshot',
            'source':source,'scheduled_at':datetime.now().isoformat(timespec='seconds'),
            'cloud_version':int(cloud_version or 0), 'schema_version':source_schema,
        }
        PENDING_RESTORE_MARKER.write_text(json.dumps(marker,ensure_ascii=False),encoding='utf-8')
        return True,'Snapshot został zweryfikowany. Przełączenie bazy, dokumentów i projektów nastąpi po ponownym uruchomieniu RK KANCELARIA.'
    except Exception as exc:
        log_event(f'Planowanie snapshot restore: {exc}','ERROR')
        try: PENDING_RESTORE_DB.unlink(missing_ok=True)
        except Exception: pass
        shutil.rmtree(PENDING_IMPORT_DOCS,ignore_errors=True); shutil.rmtree(PENDING_IMPORT_DRAFTS,ignore_errors=True)
        return False,str(exc)

def immutable_audit(con: sqlite3.Connection, case_id: int | None, entity_type: str, entity_id: int | None,
                    action: str, description: str, author: str) -> None:
    """Append-only technical log. Application code has no delete/update path for this table."""
    u=current_request_user()
    username=(u['username'] if u else '') if u is not None else ''
    uid=(u['id'] if u else None) if u is not None else None
    remote=getattr(_REQUEST_CONTEXT,'remote_addr','') or ''
    con.execute("INSERT INTO immutable_audit(case_id,entity_type,entity_id,action,description,author,username,user_id,remote_addr) VALUES(?,?,?,?,?,?,?,?,?)",
                (case_id,entity_type[:80],entity_id,action[:120],description[:2000],(author or '')[:120],str(username)[:120],uid,str(remote)[:120]))


def audit(con: sqlite3.Connection, case_id: int | None, entity_type: str, entity_id: int | None,
          action: str, description: str, author: str) -> None:
    """Readable activity history + immutable technical audit.

    Ordinary history coalesces repeated autosave entries. Technical audit is always append-only.
    """
    author=(author or '').strip()
    immutable_audit(con,case_id,entity_type,entity_id,action,description,author)
    now=datetime.now()
    last=con.execute("SELECT id,created_at,description FROM audit_log WHERE case_id IS ? AND entity_type=? AND entity_id IS ? AND action=? AND author=? ORDER BY id DESC LIMIT 1",
                     (case_id,entity_type,entity_id,action,author)).fetchone()
    if last:
        try:
            last_dt=datetime.strptime(last['created_at'][:19],'%Y-%m-%d %H:%M:%S')
            if (now-last_dt).total_seconds() <= 45:
                merged=_merge_audit_descriptions(last['description'] or '',description)
                con.execute("UPDATE audit_log SET description=?,created_at=CURRENT_TIMESTAMP WHERE id=?",(merged[:1800],last['id']))
                return
        except Exception:
            pass
    con.execute("INSERT INTO audit_log(case_id,entity_type,entity_id,action,description,author) VALUES(?,?,?,?,?,?)",
                (case_id,entity_type,entity_id,action[:80],description[:1800],author[:120]))


def case_read_only(con: sqlite3.Connection, case_id: int) -> bool:
    r=con.execute("SELECT status,closed_edit_unlocked FROM cases WHERE id=?",(case_id,)).fetchone()
    return bool(r and r['status']=='closed' and not int(r['closed_edit_unlocked'] or 0))


def entity_display(row) -> str:
    if not row: return ''
    return (row['display_name'] or row['company_name'] or ((row['first_name'] or '')+' '+(row['last_name'] or '')).strip()).strip()


def conflict_rows(con: sqlite3.Connection, entity_id: int, intended_role: str, exclude_case_id: int|None=None):
    intended=(intended_role or '').casefold()
    opposite_terms=('przeciwn','pozw','oskarż','uczestnik przeciwny','zobowiąz') if ('klient' in intended or 'wnioskod' in intended or 'powód' in intended) else ('klient','powód','wnioskod','reprezent')
    rows=con.execute("""SELECT ce.*,c.title,c.signature,c.internal_signature,c.status
        FROM case_entities ce JOIN cases c ON c.id=ce.case_id
        WHERE ce.entity_id=? AND (? IS NULL OR ce.case_id<>?) ORDER BY c.status='closed',c.id DESC""",
        (entity_id,exclude_case_id,exclude_case_id)).fetchall()
    conflicts=[]
    for r in rows:
        role=(r['role'] or '').casefold()
        if any(term in role for term in opposite_terms): conflicts.append(r)
    return conflicts


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_tesseract() -> str:
    """Znajdź lokalny silnik Tesseract. Można wymusić ścieżkę przez RK_TESSERACT_CMD."""
    env=(os.getenv('RK_TESSERACT_CMD','') or '').strip()
    candidates=[]
    if env: candidates.append(env)
    found=shutil.which('tesseract')
    if found: candidates.append(found)
    if os.name=='nt':
        pf=os.getenv('PROGRAMFILES','C:/Program Files')
        pfx86=os.getenv('PROGRAMFILES(X86)','C:/Program Files (x86)')
        local=os.getenv('LOCALAPPDATA','')
        candidates += [
            str(OCR_DIR/'Tesseract-OCR'/'tesseract.exe'),
            str(OCR_DIR/'tesseract.exe'),
            str(Path(pf)/'Tesseract-OCR'/'tesseract.exe'),
            str(Path(pfx86)/'Tesseract-OCR'/'tesseract.exe'),
            str(Path(local)/'Programs'/'Tesseract-OCR'/'tesseract.exe') if local else '',
        ]
    for c in candidates:
        if c and Path(c).is_file(): return str(Path(c))
    return ''


def tesseract_languages(cmd: str) -> set[str]:
    if not cmd: return set()
    try:
        args=[cmd,'--list-langs']
        if OCR_TESSDATA_DIR.is_dir() and any(OCR_TESSDATA_DIR.glob('*.traineddata')):
            args += ['--tessdata-dir', str(OCR_TESSDATA_DIR)]
        cp=subprocess.run(args,capture_output=True,text=True,timeout=8,creationflags=(subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0))
        return {x.strip() for x in (cp.stdout or '').splitlines() if x.strip() and not x.lower().startswith('list of available')}
    except Exception:
        return set()


def ocr_language_for(cmd: str) -> str:
    requested=(os.getenv('RK_OCR_LANG','pol+eng') or 'pol+eng').strip()
    available=tesseract_languages(cmd)
    if not available: return requested
    wanted=[x for x in requested.split('+') if x in available]
    if wanted: return '+'.join(wanted)
    if 'pol' in available: return 'pol'
    if 'eng' in available: return 'eng'
    return sorted(available)[0] if available else requested


def _run_tesseract_on_file(cmd: str, image_path: Path, lang: str) -> str:
    args=[cmd,str(image_path),'stdout','-l',lang,'--psm','6']
    if OCR_TESSDATA_DIR.is_dir() and any(OCR_TESSDATA_DIR.glob('*.traineddata')):
        args += ['--tessdata-dir', str(OCR_TESSDATA_DIR)]
    try:
        cp=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='ignore',timeout=120,creationflags=(subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0))
        return cp.stdout or '' if cp.returncode==0 else ''
    except Exception:
        return ''


def extract_document_text(filename: str, data: bytes, force_ocr: bool=False) -> tuple[str,int,str,str]:
    """Zwraca: tekst, ocr_used(0/1), ocr_status, ocr_language.

    OCR uruchamia się automatycznie tylko dla skanów/obrazów bez sensownej warstwy tekstowej.
    Nie OCR-ujemy DOCX z poprawnym tekstem.
    """
    ext=Path(filename or '').suffix.lower()
    tcmd=find_tesseract(); lang=ocr_language_for(tcmd) if tcmd else ''
    min_text=max(10,int(os.getenv('RK_OCR_MIN_TEXT','40') or 40))
    max_pages=max(1,int(os.getenv('RK_OCR_MAX_PAGES','300') or 300))
    dpi=max(120,min(350,int(os.getenv('RK_OCR_DPI','200') or 200)))
    try:
        if ext=='.docx':
            with zipfile.ZipFile(io.BytesIO(data),'r') as z:
                xml=z.read('word/document.xml')
            root=ET.fromstring(xml); texts=[]
            for el in root.iter():
                if el.tag.endswith('}t') and el.text: texts.append(el.text)
                elif el.tag.endswith('}tab'): texts.append('\t')
                elif el.tag.endswith('}br'): texts.append('\n')
            return (' '.join(texts),0,'tekst','')
        if ext=='.pdf':
            page_text=[]
            try:
                from pypdf import PdfReader
            except Exception:
                try: from PyPDF2 import PdfReader
                except Exception: PdfReader=None
            reader=PdfReader(io.BytesIO(data)) if PdfReader else None
            if reader:
                for page in reader.pages[:max_pages]:
                    try: page_text.append(page.extract_text() or '')
                    except Exception: page_text.append('')
            combined='\n'.join(page_text)
            needs_ocr=force_ocr or not combined.strip() or sum(len(x.strip()) for x in page_text)<min_text*max(1,len(page_text))
            if not needs_ocr:
                return (combined,0,'tekst','')
            if not tcmd:
                return (combined,0,'ocr_brak_silnika','')
            try:
                import fitz
            except Exception:
                return (combined,0,'ocr_brak_pymupdf',lang)
            doc=fitz.open(stream=data,filetype='pdf'); out=[]; used=False
            total=min(len(doc),max_pages)
            for i in range(total):
                existing=page_text[i] if i<len(page_text) else ''
                if not force_ocr and len(existing.strip())>=min_text:
                    out.append(existing); continue
                page=doc.load_page(i)
                pix=page.get_pixmap(matrix=fitz.Matrix(dpi/72,dpi/72),alpha=False)
                with tempfile.NamedTemporaryFile(suffix='.png',delete=False) as tf: img=Path(tf.name)
                try:
                    pix.save(str(img)); ocr=_run_tesseract_on_file(tcmd,img,lang); out.append(ocr or existing); used=used or bool(ocr.strip())
                finally:
                    try: img.unlink()
                    except OSError: pass
            if len(doc)>max_pages: out.append(f'\n[OCR ograniczony do pierwszych {max_pages} stron]')
            return ('\n'.join(out),1 if used else 0,'ocr_ok' if used else 'ocr_brak_tekstu',lang)
        if ext in {'.png','.jpg','.jpeg','.tif','.tiff','.bmp','.webp'}:
            if not tcmd: return ('',0,'ocr_brak_silnika','')
            with tempfile.NamedTemporaryFile(suffix=ext or '.png',delete=False) as tf:
                tf.write(data); img=Path(tf.name)
            try: text=_run_tesseract_on_file(tcmd,img,lang)
            finally:
                try: img.unlink()
                except OSError: pass
            return (text,1 if text.strip() else 0,'ocr_ok' if text.strip() else 'ocr_brak_tekstu',lang)
        if ext in {'.xlsx','.xlsm'}:
            try:
                import openpyxl
                wb=openpyxl.load_workbook(io.BytesIO(data),read_only=True,data_only=True)
                parts=[]
                for ws in wb.worksheets[:12]:
                    parts.append(f'### Arkusz: {ws.title}')
                    for n,row in enumerate(ws.iter_rows(values_only=True),1):
                        vals=['' if v is None else str(v) for v in row[:40]]
                        if any(v.strip() for v in vals): parts.append('\t'.join(vals))
                        if n>=500: parts.append('[podgląd ograniczony do 500 wierszy arkusza]'); break
                wb.close(); return ('\n'.join(parts),0,'tekst','')
            except Exception:
                return ('',0,'blad_podgladu_xlsx','')
        if ext in {'.txt','.md','.csv','.log','.rtf'}:
            for enc in ('utf-8','cp1250','latin-1'):
                try: return (data.decode(enc),0,'tekst','')
                except Exception: pass
    except Exception:
        return ('',0,'blad_indeksowania',lang)
    return ('',0,'nieobslugiwany_format','')


def update_document_index(con: sqlite3.Connection, document_id: int, data: bytes|None=None, force_ocr: bool=False) -> None:
    d=con.execute("SELECT * FROM documents WHERE id=?",(document_id,)).fetchone()
    if not d: return
    if data is None and d['stored_name']:
        p=FILES_DIR/f"sprawa_{d['case_id']}"/d['stored_name']
        try: data=p.read_bytes()
        except OSError: data=b''
    data=data or b''
    file_hash=sha256_bytes(data) if data else (d['file_hash'] or '')
    if data:
        text,ocr_used,ocr_status,ocr_lang=extract_document_text(d['original_name'] or d['stored_name'],data,force_ocr=force_ocr)
    else:
        text=d['extracted_text'] or ''; ocr_used=d['ocr_used'] or 0; ocr_status=d['ocr_status'] or ''; ocr_lang=d['ocr_language'] or ''
    con.execute("UPDATE documents SET file_hash=?,extracted_text=?,indexed_at=CURRENT_TIMESTAMP,ocr_used=?,ocr_status=?,ocr_language=? WHERE id=?",(file_hash,text[:5_000_000],ocr_used,ocr_status,ocr_lang,document_id))
    try:
        con.execute("DELETE FROM document_fts WHERE document_id=?",(document_id,))
        con.execute("INSERT INTO document_fts(document_id,case_id,title,filename,body) VALUES(?,?,?,?,?)",(document_id,d['case_id'],d['title'],d['original_name'],text[:5_000_000]))
    except sqlite3.DatabaseError:
        pass


def _document_index_worker() -> None:
    while True:
        document_id, force_ocr = _INDEX_QUEUE.get()
        try:
            with db() as con:
                update_document_index(con, document_id, force_ocr=force_ocr)
        except Exception as exc:
            try:
                with db() as con:
                    con.execute("UPDATE documents SET ocr_status='blad_indeksowania',indexed_at=CURRENT_TIMESTAMP WHERE id=?",(document_id,))
            except Exception:
                pass
            log_app_exception(f'background-index/{document_id}', exc)
        finally:
            _INDEX_QUEUE.task_done()


def ensure_index_worker() -> None:
    global _INDEX_WORKER_STARTED
    if _INDEX_WORKER_STARTED:
        return
    with _INDEX_WORKER_LOCK:
        if _INDEX_WORKER_STARTED:
            return
        threading.Thread(target=_document_index_worker,name='rk-document-index',daemon=True).start()
        _INDEX_WORKER_STARTED=True


def enqueue_document_index(document_id: int, force_ocr: bool=False) -> None:
    try:
        with db() as con:
            con.execute("UPDATE documents SET ocr_status='kolejka' WHERE id=?",(document_id,))
    except Exception:
        pass
    ensure_index_worker()
    _INDEX_QUEUE.put((int(document_id),bool(force_ocr)))


def index_pending_documents(limit: int=500) -> tuple[int,int]:
    done=failed=0
    with db() as con:
        rows=con.execute("SELECT id FROM documents WHERE stored_name<>'' AND (indexed_at='' OR indexed_at IS NULL OR file_hash='') ORDER BY id LIMIT ?",(limit,)).fetchall()
        for r in rows:
            try: update_document_index(con,r['id']); done+=1
            except Exception: failed+=1
    return done,failed


def fulltext_document_search(con: sqlite3.Connection, query: str, limit: int=100):
    q=(query or '').strip()
    if not q: return []
    try:
        # Quote individual terms to keep user input safe for FTS syntax.
        terms=[x for x in re.findall(r'[\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ.-]+',q) if x]
        fts=' AND '.join('"'+x.replace('"','')+'"' for x in terms) or '"'+q.replace('"','')+'"'
        return con.execute("""SELECT d.*,c.title case_title,c.signature,c.internal_signature,
               snippet(document_fts,4,'⟦','⟧',' … ',18) hit_snippet
               FROM document_fts JOIN documents d ON d.id=document_fts.document_id JOIN cases c ON c.id=d.case_id
               WHERE document_fts MATCH ? ORDER BY rank LIMIT ?""",(fts,limit)).fetchall()
    except sqlite3.DatabaseError:
        like=f"%{q}%"
        return con.execute("""SELECT d.*,c.title case_title,c.signature,c.internal_signature,
               substr(d.extracted_text,max(1,instr(lower(d.extracted_text),lower(?))-120),360) hit_snippet
               FROM documents d JOIN cases c ON c.id=d.case_id WHERE d.extracted_text LIKE ? OR d.title LIKE ? OR d.original_name LIKE ? LIMIT ?""",(q,like,like,like,limit)).fetchall()


def settings_get(con: sqlite3.Connection,key: str,default: str='') -> str:
    r=con.execute("SELECT value FROM app_settings WHERE key=?",(key,)).fetchone()
    return r['value'] if r else default


def settings_set(con: sqlite3.Connection,key: str,value: str) -> None:
    con.execute("INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP",(key,value))


def _dpapi_protect(data: bytes) -> bytes:
    if os.name!='nt': return b''
    class DATA_BLOB(ctypes.Structure): _fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_byte))]
    buf=ctypes.create_string_buffer(data); inb=DATA_BLOB(len(data),ctypes.cast(buf,ctypes.POINTER(ctypes.c_byte))); outb=DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(inb),'RK KANCELARIA',None,None,None,0,ctypes.byref(outb)): return b''
    try: return ctypes.string_at(outb.pbData,outb.cbData)
    finally: ctypes.windll.kernel32.LocalFree(outb.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    if os.name!='nt': return b''
    class DATA_BLOB(ctypes.Structure): _fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_byte))]
    buf=ctypes.create_string_buffer(data); inb=DATA_BLOB(len(data),ctypes.cast(buf,ctypes.POINTER(ctypes.c_byte))); outb=DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(inb),None,None,None,None,0,ctypes.byref(outb)): return b''
    try: return ctypes.string_at(outb.pbData,outb.cbData)
    finally: ctypes.windll.kernel32.LocalFree(outb.pbData)


def backup_secret_standalone() -> str:
    env=os.getenv('RK_BACKUP_KEY','').strip()
    if env: return env
    if os.name=='nt' and BACKUP_KEY_FILE.is_file():
        try: return _dpapi_unprotect(BACKUP_KEY_FILE.read_bytes()).decode('utf-8')
        except Exception: return ''
    return ''


def backup_secret(con: sqlite3.Connection) -> str:
    env=os.getenv('RK_BACKUP_KEY','').strip()
    if env: return env
    blob=settings_get(con,'backup_key_dpapi','')
    if blob and os.name=='nt':
        try:
            protected=base64.b64decode(blob)
            # Kopia DPAPI poza samą bazą pozwala odszyfrować backup także wtedy,
            # gdy aktywna baza ulegnie uszkodzeniu. Plik jest związany z kontem Windows.
            try:
                if not BACKUP_KEY_FILE.exists(): atomic_write_bytes(BACKUP_KEY_FILE,protected)
            except Exception: pass
            return _dpapi_unprotect(protected).decode('utf-8')
        except Exception: return backup_secret_standalone()
    return backup_secret_standalone()


def save_backup_secret(con: sqlite3.Connection, secret: str) -> bool:
    secret=(secret or '').strip()
    if not secret: return False
    verifier=hashlib.sha256(('RK-KANCELARIA:'+secret).encode()).hexdigest()
    settings_set(con,'backup_key_verifier',verifier)
    if os.name=='nt':
        protected=_dpapi_protect(secret.encode('utf-8'))
        if not protected: return False
        settings_set(con,'backup_key_dpapi',base64.b64encode(protected).decode())
        try: atomic_write_bytes(BACKUP_KEY_FILE,protected)
        except Exception: pass
        return True
    # Na serwerach Unix klucz powinien być dostarczony przez RK_BACKUP_KEY.
    return bool(os.getenv('RK_BACKUP_KEY','').strip())


def encrypted_blob(data: bytes, secret: str) -> bytes:
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except Exception as exc:
        raise RuntimeError('Brak biblioteki cryptography. Uruchom: pip install cryptography') from exc
    salt=secrets.token_bytes(16)
    kdf=PBKDF2HMAC(algorithm=hashes.SHA256(),length=32,salt=salt,iterations=390000)
    key=base64.urlsafe_b64encode(kdf.derive(secret.encode('utf-8')))
    return b'RKENC1'+salt+Fernet(key).encrypt(data)


def decrypted_blob(data: bytes, secret: str) -> bytes:
    if not data.startswith(b'RKENC1') or len(data)<23: raise ValueError('Nieprawidłowy zaszyfrowany plik RK KANCELARIA')
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except Exception as exc: raise RuntimeError('Brak biblioteki cryptography') from exc
    salt=data[6:22]; token=data[22:]
    kdf=PBKDF2HMAC(algorithm=hashes.SHA256(),length=32,salt=salt,iterations=390000)
    key=base64.urlsafe_b64encode(kdf.derive(secret.encode('utf-8')))
    return Fernet(key).decrypt(token)


def export_case_package(case_id: int) -> tuple[bytes,str]:
    with db() as con:
        c=con.execute('SELECT * FROM cases WHERE id=?',(case_id,)).fetchone()
        if not c: raise ValueError('Nie znaleziono sprawy')
        tables={}
        tables['parties']=[dict(x) for x in con.execute('SELECT * FROM parties WHERE case_id=? ORDER BY id',(case_id,))]
        tables['events']=[dict(x) for x in con.execute('SELECT * FROM events WHERE case_id=? ORDER BY id',(case_id,))]
        tables['process_events']=[dict(x) for x in con.execute('SELECT * FROM process_events WHERE case_id=? ORDER BY id',(case_id,))]
        tables['tasks']=[dict(x) for x in con.execute('SELECT * FROM tasks WHERE case_id=? ORDER BY id',(case_id,))]
        tables['documents']=[dict(x) for x in con.execute('SELECT * FROM documents WHERE case_id=? ORDER BY id',(case_id,))]
        tables['notes']=[dict(x) for x in con.execute('SELECT * FROM case_notes WHERE case_id=? ORDER BY id',(case_id,))]
        tables['external_signatures']=[dict(x) for x in con.execute('SELECT * FROM case_external_signatures WHERE case_id=? ORDER BY id',(case_id,))]
        tables['tags']=[x['name'] for x in con.execute('SELECT t.name FROM case_tags ct JOIN tags t ON t.id=ct.tag_id WHERE ct.case_id=?',(case_id,))]
        tables['case_entities']=[dict(x) for x in con.execute('SELECT ce.*,e.entity_type,e.display_name,e.first_name,e.last_name,e.company_name,e.pesel,e.nip,e.krs,e.email,e.phone,e.address,e.notes entity_notes FROM case_entities ce JOIN entities e ON e.id=ce.entity_id WHERE ce.case_id=? ORDER BY ce.id',(case_id,))]
        tables['checklist']=[dict(x) for x in con.execute('SELECT * FROM case_checklist_items WHERE case_id=? ORDER BY sort_order,id',(case_id,))]
        tables['writing_projects']=[dict(x) for x in con.execute('SELECT * FROM writing_projects WHERE case_id=? ORDER BY id',(case_id,))]
        tables['draft_versions']=[dict(x) for x in con.execute('SELECT dv.* FROM draft_versions dv JOIN writing_projects w ON w.id=dv.project_id WHERE w.case_id=? ORDER BY dv.project_id,dv.version_no',(case_id,))]
        tables['strategy']=[dict(x) for x in con.execute('SELECT * FROM case_strategy WHERE case_id=?',(case_id,))]
        tables['assertions']=[dict(x) for x in con.execute('SELECT * FROM case_assertions WHERE case_id=? ORDER BY id',(case_id,))]
        tables['evidence']=[dict(x) for x in con.execute('SELECT e.* FROM case_evidence e JOIN case_assertions a ON a.id=e.assertion_id WHERE a.case_id=? ORDER BY e.id',(case_id,))]
        tables['claims']=[dict(x) for x in con.execute('SELECT * FROM case_claims WHERE case_id=? ORDER BY id',(case_id,))]
        tables['document_events']=[dict(x) for x in con.execute('SELECT * FROM document_events WHERE case_id=? ORDER BY id',(case_id,))]
        tables['document_versions']=[dict(x) for x in con.execute('SELECT dv.* FROM document_versions dv JOIN documents d ON d.id=dv.document_id WHERE d.case_id=? ORDER BY dv.document_id,dv.version_no',(case_id,))]
        # Powiązania są eksportowane jako odwołania do sygnatur/nazw drugiej sprawy.
        # Przy imporcie odtwarzamy je tylko wtedy, gdy druga sprawa już istnieje w docelowej bazie.
        rels=[]
        for x in con.execute('''SELECT r.*,
                    sc.signature source_signature,sc.internal_signature source_internal,sc.title source_title,
                    tc.signature target_signature,tc.internal_signature target_internal,tc.title target_title
                FROM case_relations r
                JOIN cases sc ON sc.id=r.source_case_id
                JOIN cases tc ON tc.id=r.target_case_id
                WHERE r.source_case_id=? OR r.target_case_id=? ORDER BY r.id''',(case_id,case_id)):
            if x['source_case_id']==case_id:
                rels.append({'direction':'out','relation_type':x['relation_type'],'note':x['note'],
                             'other_signature':x['target_signature'],'other_internal_signature':x['target_internal'],'other_title':x['target_title']})
            else:
                rels.append({'direction':'in','relation_type':x['relation_type'],'note':x['note'],
                             'other_signature':x['source_signature'],'other_internal_signature':x['source_internal'],'other_title':x['source_title']})
        tables['relations']=rels
        manifest={'format':'RK-KANCELARIA-CASE','version':4,'exported_at':datetime.now().isoformat(timespec='seconds'),'case':dict(c),'tables':tables}
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('case.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        for d in tables['documents']:
            if d.get('stored_name'):
                fp=FILES_DIR/f"sprawa_{case_id}"/d['stored_name']
                if fp.is_file(): z.write(fp,f"files/{d['id']}/{safe_filename(d.get('original_name') or d['stored_name'])}")
        for w in tables.get('writing_projects',[]):
            if w.get('stored_name'):
                fp=DRAFTS_DIR/w['stored_name']
                if fp.is_file(): z.write(fp,f"drafts/{w['id']}/{safe_filename(w.get('original_name') or w['stored_name'])}")
        for v in tables.get('draft_versions',[]):
            if v.get('stored_name'):
                fp=DRAFTS_DIR/v['stored_name']
                if fp.is_file(): z.write(fp,f"draft_versions/{v['project_id']}/{v['id']}/{safe_filename(v.get('original_name') or fp.name)}")
        for v in tables.get('document_versions',[]):
            if v.get('stored_name'):
                fp=FILES_DIR/f"sprawa_{case_id}"/v['stored_name']
                if fp.is_file(): z.write(fp,f"document_versions/{v['document_id']}/{v['id']}/{safe_filename(v.get('original_name') or fp.name)}")
    sig=(c['internal_signature'] or c['signature'] or str(case_id)).replace('/','_').replace('\\','_')
    return out.getvalue(),f"RK_sprawa_{safe_filename(sig)}.rkcase.zip"


def row_payload(row: sqlite3.Row) -> str:
    return json.dumps({k: row[k] for k in row.keys()}, ensure_ascii=False, default=str)


TRASH_TABLES = {
    'task': ('tasks','Zadanie'),
    'event': ('events','Zdarzenie'),
    'process_event': ('process_events','Zdarzenie procesowe'),
    'party': ('parties','Osoba / uczestnik'),
    'document': ('documents','Dokument'),
    'note': ('case_notes','Notatka'),
    'external_signature': ('case_external_signatures','Dodatkowa sygnatura'),
    'relation': ('case_relations','Powiązanie'),
}


def move_to_trash(con: sqlite3.Connection, entity_type: str, entity_id: int, author: str) -> int | None:
    meta=TRASH_TABLES.get(entity_type)
    if not meta: return None
    table,_=meta
    row=con.execute(f"SELECT * FROM {table} WHERE id=?",(entity_id,)).fetchone()
    if not row: return None
    keys=set(row.keys())
    case_id=None
    if 'case_id' in keys:
        case_id=row['case_id']
    elif entity_type=='relation':
        case_id=row['source_case_id']
    label=''
    for col in ('title','name','note','signature'):
        if col in keys and row[col]:
            label=str(row[col])[:240]; break
    cur=con.execute("INSERT INTO recycle_bin(entity_type,entity_id,case_id,label,payload_json,deleted_by) VALUES(?,?,?,?,?,?)",
                    (entity_type,entity_id,case_id,label,row_payload(row),author[:120]))
    con.execute(f"DELETE FROM {table} WHERE id=?",(entity_id,))
    audit(con,case_id,entity_type,entity_id,'Usunięto do kosza',label or meta[1],author)
    return cur.lastrowid


def restore_from_trash(con: sqlite3.Connection, trash_id: int, author: str) -> tuple[bool,int|None]:
    tr=con.execute("SELECT * FROM recycle_bin WHERE id=?",(trash_id,)).fetchone()
    if not tr: return False,None
    meta=TRASH_TABLES.get(tr['entity_type'])
    if not meta: return False,tr['case_id']
    table,_=meta
    payload=json.loads(tr['payload_json'])
    cols={r['name'] for r in con.execute(f"PRAGMA table_info({table})")}
    data={k:v for k,v in payload.items() if k in cols}
    # Jeśli stary id jest już zajęty, SQLite nada nowy.
    if 'id' in data and con.execute(f"SELECT 1 FROM {table} WHERE id=?",(data['id'],)).fetchone():
        data.pop('id',None)
    names=list(data)
    vals=[data[k] for k in names]
    ph=','.join('?' for _ in names)
    con.execute(f"INSERT INTO {table}({','.join(names)}) VALUES({ph})",vals)
    con.execute("DELETE FROM recycle_bin WHERE id=?",(trash_id,))
    audit(con,tr['case_id'],tr['entity_type'],payload.get('id'),'Przywrócono z kosza',tr['label'],author)
    return True,tr['case_id']


def purge_old_trash() -> None:
    """Usuń z kosza rekordy starsze niż 30 dni. Pliki dokumentów kasuj dopiero wtedy."""
    try:
        with db() as con:
            rows=con.execute("SELECT * FROM recycle_bin WHERE deleted_at < datetime('now', ?)",(f'-{TRASH_RETENTION_DAYS} days',)).fetchall()
            for tr in rows:
                if tr['entity_type']=='document':
                    try:
                        payload=json.loads(tr['payload_json'])
                        if payload.get('stored_name') and payload.get('case_id'):
                            p=FILES_DIR/f"sprawa_{payload['case_id']}"/payload['stored_name']
                            p.unlink(missing_ok=True)
                    except Exception:
                        pass
                con.execute("DELETE FROM recycle_bin WHERE id=?",(tr['id'],))
    except Exception:
        pass


def ensure_daily_backup() -> tuple[str,str]:
    """Jedna automatyczna kopia SQLite dziennie, zachowujemy 30 najnowszych.

    Jeśli skonfigurowano klucz szyfrowania, kopia jest zapisywana jako .rkenc.
    """
    try:
        if not DB_PATH.exists() or not _looks_like_sqlite(DB_PATH): return '—',''
        DAILY_BACKUPS_DIR.mkdir(parents=True,exist_ok=True); today=date.today().strftime('%Y%m%d')
        existing=sorted(list(DAILY_BACKUPS_DIR.glob(f'rk_kancelaria_{today}_*.sqlite3'))+list(DAILY_BACKUPS_DIR.glob(f'rk_kancelaria_{today}_*.sqlite3.rkenc')))
        if existing: p=existing[-1]
        else:
            stamp=datetime.now().strftime('%H%M%S'); tmp=DAILY_BACKUPS_DIR/f'.tmp_{today}_{stamp}.sqlite3'; _sqlite_backup(DB_PATH,tmp)
            with db() as con: secret=backup_secret(con)
            if secret:
                try:
                    enc=encrypted_blob(tmp.read_bytes(),secret); p=DAILY_BACKUPS_DIR/f'rk_kancelaria_{today}_{stamp}.sqlite3.rkenc'; p.write_bytes(enc); tmp.unlink(missing_ok=True)
                except Exception:
                    p=DAILY_BACKUPS_DIR/f'rk_kancelaria_{today}_{stamp}.sqlite3'; os.replace(tmp,p)
            else:
                p=DAILY_BACKUPS_DIR/f'rk_kancelaria_{today}_{stamp}.sqlite3'; os.replace(tmp,p)
        all_files=sorted(list(DAILY_BACKUPS_DIR.glob('rk_kancelaria_*.sqlite3'))+list(DAILY_BACKUPS_DIR.glob('rk_kancelaria_*.sqlite3.rkenc')),key=lambda x:x.stat().st_mtime,reverse=True)
        for old in all_files[30:]:
            try: old.unlink()
            except OSError: pass
        ts=datetime.fromtimestamp(p.stat().st_mtime).strftime('%d.%m.%Y %H:%M')
        return ts,str(p)
    except Exception as e: return 'błąd',str(e)


def user_display_name(row) -> str:
    if not row: return '—'
    fn=(row['function'] or '').strip() if 'function' in row.keys() else ''
    return f"{row['author_name']} — {fn}" if fn else row['author_name']


def case_lead_html(con: sqlite3.Connection, lead_user_id) -> str:
    if not lead_user_id: return '—'
    u=con.execute("SELECT * FROM users WHERE id=?",(lead_user_id,)).fetchone()
    return user_display_name(u) if u else 'konto usunięte'


def record_recent_case(user_id: int | None, case_id: int) -> None:
    if not user_id: return
    with db() as con:
        con.execute("INSERT INTO user_case_recent(user_id,case_id,opened_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(user_id,case_id) DO UPDATE SET opened_at=CURRENT_TIMESTAMP",(user_id,case_id))
        # zachowaj maks. 30 ostatnich na użytkownika
        con.execute("DELETE FROM user_case_recent WHERE user_id=? AND case_id NOT IN (SELECT case_id FROM user_case_recent WHERE user_id=? ORDER BY opened_at DESC LIMIT 30)",(user_id,user_id))


def is_case_pinned(user_id: int | None, case_id: int) -> bool:
    if not user_id: return False
    with db() as con:
        return bool(con.execute("SELECT 1 FROM user_case_pins WHERE user_id=? AND case_id=?",(user_id,case_id)).fetchone())

def layout(title: str, body: str, active: str = "") -> str:
    user = current_request_user()
    nav_sections = [
        ("PRACA", [
            ("/", "⌂", "Pulpit", "dashboard"),
            ("/today", "◷", "Dzisiaj", "today"),
            ("/calendar", "▦", "Kalendarz", "calendar"),
            ("/cases", "§", "Sprawy", "cases"),
            ("/cases?mine=1", "◎", "Moje sprawy", "my_cases"),
            ("/tasks", "✓", "Zadania", "tasks"),
            ("/documents", "▤", "Dokumenty", "documents"),
            ("/drafts", "✎", "Pisma", "drafts"),
        ]),
        ("WIĘCEJ", [
            ("/cases/closed", "□", "Sprawy zakończone", "closed_cases"),
            ("/entities", "♙", "Kartoteka podmiotów", "entities"),
            ("/checklists", "☑", "Checklisty", "checklists"),
            ("/views", "☆", "Moje widoki", "views"),
            ("/tags", "#", "Tagi", "tags"),
            ("/law", "¶", "Prawo", "law"),
            ("/search", "⌕", "Wyszukiwarka", "search"),
        ]),
        ("SYSTEM", [
            ("/history", "↺", "Historia zmian", "history"),
            ("/trash", "⌫", "Kosz", "trash"),
            ("/backups", "⛁", "Kopie bezpieczeństwa", "backups"),
        ]),
    ]
    if user and user['role'] == 'admin':
        nav_sections[-1][1].append(("/audit", "≡", "Dziennik audytowy", "audit"))
        nav_sections[-1][1].append(("/security", "◇", "Bezpieczeństwo", "security"))
        nav_sections[-1][1].append(("/recovery", "↥", "Recovery", "recovery"))
        nav_sections[-1][1].append(("/cloud", "☁", "Cloud / PWA", "cloud"))
        nav_sections[-1][1].append(("/admin/users", "♟", "Użytkownicy", "users"))
    nav_parts=[]
    for section,items in nav_sections:
        links="".join(f'<a class="nav-link {"active" if active==key else ""}" href="{href}"><span class="nav-icon">{icon}</span><span>{label}</span></a>' for href,icon,label,key in items)
        if section=='SYSTEM':
            opened=' open' if any(active==x[3] for x in items) else ''
            nav_parts.append(f'<details class="nav-system"{opened}><summary><span>USTAWIENIA I SYSTEM</span><span class="nav-system-arrow">›</span></summary><div class="nav-system-links">{links}</div></details>')
        else:
            nav_parts.append(f'<div class="nav-section"><div class="nav-section-title">{esc(section)}</div>{links}</div>')
    nav_html=''.join(nav_parts)
    if user:
        role = "Administrator" if user['role']=='admin' else "Użytkownik"
        func = f"<div class='small' style='color:#d7c48a;margin-top:3px'>{esc(user['function'])}</div>" if user['function'] else ''
        user_box = f"<div class='author-box'><div style='color:#f1d89a;font-weight:800'>{esc(user['author_name'])}</div>{func}<div class='small' style='color:#9bb1aa;margin:4px 0 9px'>@{esc(user['username'])} · {role}</div><a class='btn small' style='width:100%;text-align:center;margin-bottom:6px' href='/account'>Moje konto</a><form method='post' action='/logout'><button class='btn small' style='width:100%'>Wyloguj</button></form></div>"
    else:
        user_box = ""
    startup_notice = ""
    msgs = [m for m in (MIGRATION_MESSAGE, PRE_UPGRADE_BACKUP_MESSAGE) if m]
    if msgs:
        startup_notice = "<div class='notice'><b>Aktualizacja danych:</b><br>" + "<br>".join(esc(m) for m in msgs) + "</div>"
    return f"""<!doctype html>
<html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} – {APP_NAME}</title>
<link rel="icon" type="image/x-icon" href="/assets/rk_kancelaria.ico">
<link rel="manifest" href="/manifest.webmanifest"><meta name="theme-color" content="#082b36"><meta name="apple-mobile-web-app-capable" content="yes">
<link rel="stylesheet" href="/assets/rk_app.css?v={VERSION}">
</head><body data-auto-shutdown="{'1' if AUTO_SHUTDOWN else '0'}"><div class="app"><aside class="sidebar"><div class="brand"><img src="/assets/rk_kancelaria_logo.png" alt="RK"><div class="brand-title">RK KANCELARIA<small>Baza spraw · v{VERSION}</small></div></div>{nav_html}
{user_box}
<div class='sidebar-tools'><button type='button' class='sidebar-mini-btn' data-compact-toggle title='Przełącz gęstość interfejsu'>↔ Tryb kompaktowy</button></div><div class='shortcut-help'><span class='kbd'>Ctrl+K</span> szukaj · <span class='kbd'>Ctrl+J</span> dodaj · <span class='kbd'>Ctrl+N</span> sprawa</div>
<div class="program-author">AUTOR PROGRAMU<b>{APP_AUTHOR}</b></div>
</aside><main class="main">{startup_notice}{body}</main></div><a class="global-add" href="/quick-add" title="Dodaj czynność" aria-label="Dodaj czynność">＋</a><div id="autosaveStatus" class="autosave-status"></div>
<script src="/assets/rk_app.js?v={VERSION}" defer></script></body></html>"""


def writing_tabs(active: str) -> str:
    """Jeden moduł Pisma z dwoma widokami, bez dublowania pozycji w menu."""
    return (
        "<nav class='module-tabs' aria-label='Widoki modułu Pisma'>"
        f"<a class='module-tab {'active' if active == 'projects' else ''}' href='/drafts'>Projekty</a>"
        f"<a class='module-tab {'active' if active == 'templates' else ''}' href='/drafts?view=templates'>Szablony</a>"
        "</nav>"
    )

def badge(status: str) -> str:
    return f'<span class="badge {STATUS_BADGES.get(status,"gray")}">{esc(STATUS_LABELS.get(status,status))}</span>'


def display_case_signature(case_id: int, court_signature: str = '', internal_signature: str = '') -> tuple[str, str]:
    """Zwraca główną sygnaturę do wyświetlenia i jej typ.

    Kolejność głównej sygnatury: sygnatura sądowa -> pierwsza dodatkowa
    sygnatura innego organu -> "Bez sygnatury".

    Sygnatura wewnętrzna nie zastępuje głównej sygnatury. Jest pokazywana
    osobno i stale w interfejsie.
    """
    court_signature = (court_signature or '').strip()
    if court_signature:
        return court_signature, 'Sygnatura sądowa'
    cache=getattr(_REQUEST_CONTEXT,'signature_cache',None)
    if cache is not None and case_id in cache:
        return cache[case_id]
    result=('Bez sygnatury','')
    try:
        with db() as con:
            row = con.execute(
                "SELECT label,signature FROM case_external_signatures WHERE case_id=? AND TRIM(signature)<>'' ORDER BY id LIMIT 1",
                (case_id,)
            ).fetchone()
        if row and (row['signature'] or '').strip():
            result=(row['signature'].strip(), (row['label'] or 'Sygnatura innego organu').strip())
    except Exception:
        pass
    if cache is not None:
        cache[case_id]=result
    return result


def internal_signature_text(value: str) -> str:
    value = (value or '').strip()
    return f"Sygnatura wewnętrzna: {value or '—'}"


def display_signature_meta(case_id: int, court_signature: str = '', internal_signature: str = '') -> tuple[str, str]:
    # Zawsze zwracamy także etykietę rodzaju, aby interfejs mógł wyświetlić
    # np. „Sygnatura sądowa: III ...” albo „Sygnatura prokuratury: ...”.
    return display_case_signature(case_id, court_signature, internal_signature)


def primary_signature_text(case_id: int, court_signature: str = '', internal_signature: str = '') -> str:
    value, kind = display_case_signature(case_id, court_signature, internal_signature)
    if value == 'Bez sygnatury':
        return value
    return f"{kind or 'Sygnatura'}: {value}"

def load_external_signature_map(con: sqlite3.Connection, case_ids) -> dict[int, tuple[str,str]]:
    """Jedno zbiorcze zapytanie zamiast N+1 połączeń SQLite na listach spraw."""
    ids=[]
    seen=set()
    for raw in case_ids:
        try: cid=int(raw)
        except (TypeError,ValueError): continue
        if cid and cid not in seen:
            ids.append(cid); seen.add(cid)
    out: dict[int, tuple[str,str]] = {}
    for pos in range(0,len(ids),500):
        chunk=ids[pos:pos+500]
        if not chunk: continue
        ph=','.join('?' for _ in chunk)
        rows=con.execute(f"SELECT case_id,label,signature,id FROM case_external_signatures WHERE case_id IN ({ph}) AND TRIM(signature)<>'' ORDER BY case_id,id",chunk).fetchall()
        for r in rows:
            if r['case_id'] not in out:
                out[r['case_id']]=((r['label'] or 'Sygnatura innego organu').strip(),(r['signature'] or '').strip())
    return out

def primary_signature_fast(case_id: int, court_signature: str = '', external_map: dict[int,tuple[str,str]]|None=None) -> str:
    court=(court_signature or '').strip()
    if court:
        return f"Sygnatura sądowa: {court}"
    if external_map is not None:
        item=external_map.get(int(case_id))
        if item and item[1]:
            return f"{item[0] or 'Sygnatura'}: {item[1]}"
        return 'Bez sygnatury'
    return primary_signature_text(case_id,court_signature,'')



def parse_multipart(headers, body: bytes):
    ctype = headers.get("Content-Type", "")
    synthetic = (f"Content-Type: {ctype}\r\nMIME-Version: 1.0\r\n\r\n").encode() + body
    msg = BytesParser(policy=email_policy).parsebytes(synthetic)
    fields: dict[str, str] = {}
    files: dict[str, object] = {}
    if not msg.is_multipart():
        return fields, files
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if not name:
            continue
        if filename:
            item = (filename, payload, part.get_content_type())
            # Pola zakończone [] mogą zawierać wiele plików (np. załączniki do pisma).
            if name.endswith("[]"):
                files.setdefault(name, [])
                files[name].append(item)
            else:
                files[name] = item
        else:
            charset = part.get_content_charset() or "utf-8"
            try: fields[name] = payload.decode(charset)
            except Exception: fields[name] = payload.decode("utf-8", "replace")
    return fields, files



def find_pdf_font() -> str | None:
    candidates = [
        os.getenv("SPRAWNIK_PDF_FONT", ""),
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for x in candidates:
        if x and Path(x).exists():
            return str(Path(x))
    return None


def build_case_pdf(case_id: int, sections: set[str]) -> tuple[bytes, str]:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    except Exception as e:
        raise RuntimeError("Eksport PDF wymaga biblioteki reportlab. Uruchom ponownie start_windows.bat albo wykonaj: python -m pip install reportlab") from e

    with db() as con:
        c=con.execute("SELECT * FROM cases WHERE id=?",(case_id,)).fetchone()
        if not c: raise ValueError("Nie znaleziono sprawy")
        lead_user=con.execute("SELECT * FROM users WHERE id=?",(c['lead_user_id'],)).fetchone() if c['lead_user_id'] else None
        parties=con.execute("SELECT * FROM parties WHERE case_id=? ORDER BY id",(case_id,)).fetchall()
        events=con.execute("SELECT * FROM events WHERE case_id=? ORDER BY event_date,id",(case_id,)).fetchall()
        tasks=con.execute("SELECT * FROM tasks WHERE case_id=? ORDER BY status,CASE WHEN due_date='' THEN 1 ELSE 0 END,due_date,id",(case_id,)).fetchall()
        docs=con.execute("SELECT * FROM documents WHERE case_id=? ORDER BY doc_date,id",(case_id,)).fetchall()
        notes=con.execute("SELECT * FROM case_notes WHERE case_id=? ORDER BY created_at,id",(case_id,)).fetchall()
        tags=[r['name'] for r in con.execute("SELECT t.name FROM case_tags ct JOIN tags t ON t.id=ct.tag_id WHERE ct.case_id=? ORDER BY t.name",(case_id,)).fetchall()]
        external_signatures=con.execute("SELECT label,signature FROM case_external_signatures WHERE case_id=? ORDER BY label COLLATE NOCASE,id",(case_id,)).fetchall()
        rels=con.execute("""SELECT r.*,s.signature ss,s.title st,t.signature ts,t.title tt FROM case_relations r JOIN cases s ON s.id=r.source_case_id JOIN cases t ON t.id=r.target_case_id WHERE r.source_case_id=? OR r.target_case_id=? ORDER BY r.id""",(case_id,case_id)).fetchall()

    buf=io.BytesIO()
    pdf_sig, pdf_sig_kind = display_case_signature(case_id, c['signature'], c['internal_signature'])
    doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=16*mm,leftMargin=16*mm,topMargin=16*mm,bottomMargin=16*mm,title=f"Wyciąg ze sprawy {pdf_sig if pdf_sig != 'Bez sygnatury' else c['title']}")
    styles=getSampleStyleSheet()
    font_name='Helvetica'
    font_path=find_pdf_font()
    if font_path:
        try:
            pdfmetrics.registerFont(TTFont('SprawnikFont',font_path)); font_name='SprawnikFont'
        except Exception:
            pass
    normal=ParagraphStyle('SprawnikNormal',parent=styles['BodyText'],fontName=font_name,fontSize=9.5,leading=12,spaceAfter=4)
    small=ParagraphStyle('SprawnikSmall',parent=normal,fontSize=8,leading=10,textColor=colors.HexColor('#5c6674'))
    h1=ParagraphStyle('SprawnikH1',parent=styles['Heading1'],fontName=font_name,fontSize=18,leading=22,spaceAfter=8)
    h2=ParagraphStyle('SprawnikH2',parent=styles['Heading2'],fontName=font_name,fontSize=12.5,leading=15,spaceBefore=10,spaceAfter=6)
    center=ParagraphStyle('SprawnikCenter',parent=small,alignment=TA_CENTER)
    def P(x,style=normal):
        return Paragraph(esc(x).replace('\n','<br/>'),style)
    def author_line(created_by='', updated_by=''):
        bits=[]
        if created_by: bits.append('autor: '+created_by)
        if updated_by and updated_by!=created_by: bits.append('ostatnia zmiana: '+updated_by)
        return ' · '.join(bits)
    pdf_primary=(f"{pdf_sig_kind}: {pdf_sig}" if pdf_sig!='Bez sygnatury' else c['title'])
    pdf_sub=internal_signature_text(c['internal_signature'])+' · '+c['title']
    story=[P('RK KANCELARIA — WYCIĄG ZE SPRAWY',center),P(pdf_primary,h1),P(pdf_sub,small),Spacer(1,4)]
    if 'overview' in sections:
        rows=[['Sygnatura sądowa',c['signature'] or '—'],['Sygnatura wewnętrzna',c['internal_signature'] or '—']]
        rows += [[r['label'],r['signature']] for r in external_signatures]
        rows += [['Klient / zlecający',c['client'] or '—'],['Prowadzący',user_display_name(lead_user) if lead_user else '—'],['Status',STATUS_LABELS.get(c['status'],c['status'])],['Czekamy na',c['waiting_for'] or '—'],['Sąd',(c['court'] or '—')+((' · '+c['department']) if c['department'] else '')],['Kategoria',c['category'] or '—'],['Przedmiot',c['subject'] or '—'],['Tagi',', '.join(tags) or '—'],['Najbliższa data',fmt_date(c['next_date'])],['Następny krok',c['next_step'] or '—'],['Notatka główna',c['notes'] or '—'],['Autor / zmiana',author_line(c['created_by'],c['updated_by']) or '—']]
        tbl=Table([[P(a,small),P(b)] for a,b in rows],colWidths=[42*mm,130*mm]); tbl.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),0.25,colors.HexColor('#d9dee7')),('BACKGROUND',(0,0),(0,-1),colors.HexColor('#f4f6f9')),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)])); story += [P('Dane sprawy',h2),tbl]
    if 'parties' in sections:
        story.append(P('Strony / uczestnicy',h2))
        data=[[P('Osoba',small),P('Rola',small),P('Notatka',small),P('Autor',small)]]+[[P(r['name']),P(r['role']),P(r['notes']),P(author_line(r['created_by'],r['updated_by']) or '—',small)] for r in parties]
        tbl=Table(data,colWidths=[45*mm,35*mm,65*mm,27*mm],repeatRows=1); tbl.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.25,colors.HexColor('#d9dee7')),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef2f7')),('VALIGN',(0,0),(-1,-1),'TOP')])); story.append(tbl)
    if 'relations' in sections:
        story.append(P('Powiązane sprawy',h2))
        for r in rels:
            labels=RELATION_TYPES.get(r['relation_type'],(r['relation_type'],r['relation_type']))
            if r['source_case_id']==case_id:
                label=labels[0]; other_sig=primary_signature_text(r['target_case_id'], r['ts'], '') ; other=other_sig if other_sig!='Bez sygnatury' else r['tt']
            else:
                label=labels[1]; other_sig=primary_signature_text(r['source_case_id'], r['ss'], '') ; other=other_sig if other_sig!='Bez sygnatury' else r['st']
            story.append(P(f"• {label}: {other}"));
            if r['note']: story.append(P(r['note'],small))
            if r['created_by'] or r['updated_by']: story.append(P(author_line(r['created_by'],r['updated_by']),small))
    if 'events' in sections:
        story.append(P('Oś czasu',h2))
        for r in events:
            story.append(P(f"{fmt_date(r['event_date'])} — {r['event_type']} — {r['title']}"))
            if r['description']: story.append(P(r['description'],small))
            if r['created_by'] or r['updated_by']: story.append(P(author_line(r['created_by'],r['updated_by']),small))
    if 'tasks' in sections:
        story.append(P('Zadania',h2))
        for r in tasks:
            status='wykonane' if r['status']=='done' else 'otwarte'; due=fmt_date(r['due_date'])
            story.append(P(f"• {r['title']} — {status} — termin: {due}"))
            extra=[]
            if r['depends_on']: extra.append('zależność: '+r['depends_on'])
            if r['notes']: extra.append(r['notes'])
            if extra: story.append(P(' · '.join(extra),small))
            if r['created_by'] or r['updated_by']: story.append(P(author_line(r['created_by'],r['updated_by']),small))
    if 'documents' in sections:
        story.append(P('Dokumenty',h2))
        data=[[P('Data dokumentu',small),P('Wpływ',small),P('Rodzaj',small),P('Dokument',small),P('Autor',small)]]
        for r in docs:
            desc=r['title']+((' — '+r['description']) if r['description'] else '')+((' ['+r['original_name']+']') if r['original_name'] else '')
            data.append([P(fmt_date(r['doc_date'])),P(fmt_date(r['received_date'])),P(r['doc_type']),P(desc),P(author_line(r['created_by'],r['updated_by']) or '—',small)])
        tbl=Table(data,colWidths=[25*mm,25*mm,30*mm,68*mm,24*mm],repeatRows=1); tbl.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.25,colors.HexColor('#d9dee7')),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef2f7')),('VALIGN',(0,0),(-1,-1),'TOP')])); story.append(tbl)
    if 'notes' in sections:
        story.append(P('Notatki chronologiczne',h2))
        for r in notes:
            story.append(P(r['note']))
            story.append(P(f"{r['created_at']}"+((' · '+r['author']) if r['author'] else ''),small))
    story += [Spacer(1,10),P('Wygenerowano: '+datetime.now().strftime('%d.%m.%Y %H:%M'),center)]
    doc.build(story)
    filename=safe_filename(f"wyciag_{(pdf_sig if pdf_sig!='Bez sygnatury' else c['title']).replace('/', '_').replace('\\', '_')}.pdf")
    return buf.getvalue(), filename

def document_managed_path(row) -> Path | None:
    if not row: return None
    stored=(row_get(row,'stored_name','') or '').strip(); cid=row_get(row,'case_id',None)
    if not stored or not cid or Path(stored).name!=stored: return None
    folder=(FILES_DIR/f"sprawa_{int(cid)}").resolve()
    try:
        p=(folder/stored).resolve()
        return p if p.parent==folder else None
    except OSError: return None


def document_state(row) -> tuple[str,Path|None,str]:
    p=document_managed_path(row)
    if p is None: return 'missing',None,'Brak poprawnej ścieżki pliku.'
    try:
        if not p.exists(): return 'missing',p,'Plik nie istnieje w katalogu dokumentów.'
        if not p.is_file(): return 'invalid',p,'Ścieżka dokumentu nie wskazuje pliku.'
        if p.stat().st_size==0: return 'invalid',p,'Plik ma rozmiar 0 bajtów.'
        return 'ok',p,''
    except OSError as exc: return 'error',p,str(exc)


def open_in_default_app(path: Path) -> tuple[bool,str]:
    try:
        if os.name=='nt': os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform=='darwin': subprocess.Popen(['open',str(path)])
        else: subprocess.Popen(['xdg-open',str(path)])
        return True,''
    except Exception as exc: return False,str(exc)


def open_containing_folder(path: Path) -> tuple[bool,str]:
    try:
        if os.name=='nt': subprocess.Popen(['explorer.exe','/select,',str(path)],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        elif sys.platform=='darwin': subprocess.Popen(['open','-R',str(path)])
        else: subprocess.Popen(['xdg-open',str(path.parent)])
        return True,''
    except Exception as exc: return False,str(exc)


class Handler(BaseHTTPRequestHandler):
    server_version = f"{APP_NAME}/{VERSION}"

    def handle_one_request(self):
        started=time.perf_counter()
        try:
            return super().handle_one_request()
        finally:
            try: log_slow_request(getattr(self,'path','(brak ścieżki)'),time.perf_counter()-started)
            except Exception: pass

    def log_message(self, format, *args):
        # mniej hałaśliwy terminal
        return

    def is_authorized(self) -> bool:
        user = session_user(self.cookie_value(SESSION_COOKIE))
        _REQUEST_CONTEXT.user = user
        return bool(user)

    def require_auth(self) -> bool:
        if user_count() == 0:
            self.redirect('/setup')
            return False
        if self.is_authorized():
            return True
        self.redirect('/login')
        return False

    def require_admin(self) -> bool:
        user = current_request_user()
        if not user or user['role'] != 'admin':
            self.send_html(layout('Brak dostępu', "<div class='card'><h1>Brak dostępu</h1><p>Ta część programu jest dostępna tylko dla administratora.</p><a class='btn' href='/'>Wróć</a></div>"), 403)
            return False
        return True

    def send_html(self, content: str, status=200):
        data = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers(); self.wfile.write(data)

    def redirect(self, url: str):
        if getattr(self, '_autosave_mode', False) or self.headers.get('X-Sprawnik-Autosave') == '1':
            self.send_response(204); self.end_headers(); return
        self.send_response(303); self.send_header("Location", url); self.end_headers()

    def send_no_content(self):
        self.send_response(204); self.send_header('Cache-Control','no-store'); self.end_headers()

    def send_asset(self, name: str):
        safe = Path(name).name
        # Wszystkie zasoby interfejsu mają jedno źródło. Dawne duplikaty z
        # katalogu głównego powodowały rozjazdy stylów między ekranami.
        path = BASE_DIR / 'assets' / safe
        if not path.is_file():
            return self.send_error(404)
        stat = path.stat()
        cache_key = str(path)
        with _ASSET_CACHE_LOCK:
            cached = _ASSET_CACHE.get(cache_key)
            if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
                _, _, data, ctype, etag = cached
            else:
                data = path.read_bytes()
                ctype = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
                etag = '"' + hashlib.sha256(data).hexdigest()[:20] + '"'
                _ASSET_CACHE[cache_key] = (stat.st_mtime_ns, stat.st_size, data, ctype, etag)
        if self.headers.get('If-None-Match') == etag:
            self.send_response(304)
            self.send_header('ETag', etag)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('ETag', etag)
        if safe == 'service-worker.js':
            self.send_header('Cache-Control','no-cache, no-store, must-revalidate')
            self.send_header('Service-Worker-Allowed','/')
        else:
            self.send_header('Cache-Control', 'public, max-age=86400')
        self.end_headers(); self.wfile.write(data)

    def read_post(self):
        raw_length = self.headers.get("Content-Length", "0") or "0"
        try:
            length = int(raw_length)
        except (TypeError, ValueError):
            raise ValueError("Nieprawidłowy nagłówek Content-Length.")
        if length < 0:
            raise ValueError("Nieprawidłowy rozmiar żądania.")
        if length > MAX_POST_BYTES:
            raise OverflowError(f"Przesyłany formularz jest zbyt duży. Maksymalny rozmiar to {MAX_POST_BYTES // 1024 // 1024} MB.")
        body = self.rfile.read(length)
        if len(body) != length:
            raise ValueError("Przesyłanie zostało przerwane przed odebraniem całego formularza.")
        ctype = self.headers.get("Content-Type", "")
        if ctype.startswith("multipart/form-data"):
            return parse_multipart(self.headers, body)
        fields = {k: v[-1] for k,v in parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).items()}
        return fields, {}

    def cookie_value(self, name: str) -> str:
        raw=self.headers.get('Cookie','')
        try:
            c=SimpleCookie(); c.load(raw)
            return unquote(c[name].value) if name in c else ''
        except Exception:
            return ''

    def current_author(self, fields=None) -> str:
        user = current_request_user()
        return (user['author_name'] if user else '')[:120]

    def set_session_cookie(self, token: str):
        self.send_header('Set-Cookie', f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_HOURS*3600}")

    def clear_session_cookie(self):
        self.send_header('Set-Cookie', f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")

    def websocket_presence(self, tab_id: str):
        """Minimalny WebSocket służący wyłącznie do wykrywania obecności karty."""
        tab_id = (tab_id or '')[:120]
        key = (self.headers.get('Sec-WebSocket-Key') or '').strip()
        upgrade = (self.headers.get('Upgrade') or '').lower()
        if not tab_id or upgrade != 'websocket' or not key:
            return self.send_error(400, 'Nieprawidłowe połączenie WebSocket')
        guid = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
        accept = base64.b64encode(hashlib.sha1((key + guid).encode('ascii')).digest()).decode('ascii')
        self.send_response(101, 'Switching Protocols')
        self.send_header('Upgrade', 'websocket')
        self.send_header('Connection', 'Upgrade')
        self.send_header('Sec-WebSocket-Accept', accept)
        self.end_headers()
        self.close_connection = True
        client_heartbeat(tab_id)
        sock = self.connection
        old_timeout = sock.gettimeout()
        try:
            sock.settimeout(0.25)
            while True:
                try:
                    first = sock.recv(2)
                except socket.timeout:
                    client_heartbeat(tab_id)
                    continue
                if not first or len(first) < 2:
                    break
                b1, b2 = first[0], first[1]
                opcode = b1 & 0x0F
                masked = bool(b2 & 0x80)
                length = b2 & 0x7F
                if length == 126:
                    raw = self._recv_exact(sock, 2)
                    if raw is None: break
                    length = struct.unpack('!H', raw)[0]
                elif length == 127:
                    raw = self._recv_exact(sock, 8)
                    if raw is None: break
                    length = struct.unpack('!Q', raw)[0]
                mask = self._recv_exact(sock, 4) if masked else b''
                if masked and mask is None: break
                payload = self._recv_exact(sock, length) if length else b''
                if payload is None: break
                if masked and mask:
                    payload = bytes(ch ^ mask[i % 4] for i, ch in enumerate(payload))
                if opcode == 0x8:  # CLOSE
                    try: sock.sendall(b'\x88\x00')
                    except OSError: pass
                    break
                if opcode == 0x9:  # PING -> PONG
                    try:
                        plen = len(payload)
                        if plen < 126:
                            sock.sendall(bytes([0x8A, plen]) + payload)
                    except OSError:
                        break
                client_heartbeat(tab_id)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            pass
        finally:
            try: sock.settimeout(old_timeout)
            except OSError: pass
            client_closing(tab_id)

    @staticmethod
    def _recv_exact(sock, count: int):
        data = bytearray()
        while len(data) < count:
            try:
                chunk = sock.recv(count - len(data))
            except socket.timeout:
                continue
            except OSError:
                return None
            if not chunk:
                return None
            data.extend(chunk)
        return bytes(data)

    def mutation_case_id(self,path,fields):
        m=re.fullmatch(r"/case/(\d+)/(?:update|delete|party|event|task|document|relation|external-signature|note|next-action|process-event|next-action/complete|smart-link|law-link|strategy|assertion|claim|document-event)",path)
        if m: return int(m.group(1))
        if path in {'/task/create','/deadline/create','/quick/event','/quick/note','/quick/document','/alert/create'}:
            try: return int(fields.get('case_id','0') or 0) or None
            except (TypeError,ValueError): return None
        mm=re.fullmatch(r"/assertion/(\d+)/evidence",path)
        if mm:
            with db() as con:
                r=con.execute('SELECT case_id cid FROM case_assertions WHERE id=?',(int(mm.group(1)),)).fetchone()
            return int(r['cid']) if r else None
        mm=re.fullmatch(r"/evidence/(\d+)/delete",path)
        if mm:
            with db() as con:
                r=con.execute('SELECT a.case_id cid FROM case_evidence e JOIN case_assertions a ON a.id=e.assertion_id WHERE e.id=?',(int(mm.group(1)),)).fetchone()
            return int(r['cid']) if r else None
        mm=re.fullmatch(r"/document/(\d+)/version/(\d+)/restore",path)
        if mm:
            with db() as con:
                r=con.execute('SELECT case_id cid FROM documents WHERE id=?',(int(mm.group(1)),)).fetchone()
            return int(r['cid']) if r else None
        mapping=[('party','parties','case_id'),('event','events','case_id'),('process-event','process_events','case_id'),('task','tasks','case_id'),('document','documents','case_id'),('external-signature','case_external_signatures','case_id'),('note','case_notes','case_id'),('case-entity','case_entities','case_id'),('checklist/item','case_checklist_items','case_id'),('smart-link','smart_links','case_id'),('alert','alerts','case_id'),('law-case-link','law_case_links','case_id'),('deadline-suggestion','deadline_suggestions','case_id'),('assertion','case_assertions','case_id'),('claim','case_claims','case_id'),('document-event','document_events','case_id')]
        for prefix,table,col in mapping:
            mm=re.fullmatch(rf"/{re.escape(prefix)}/(\d+)/(?:update|delete|toggle|accept)",path)
            if mm:
                with db() as con:
                    r=con.execute(f"SELECT {col} cid FROM {table} WHERE id=?",(int(mm.group(1)),)).fetchone()
                return int(r['cid']) if r else None
        mm=re.fullmatch(r"/relation/(\d+)/(?:update|delete)",path)
        if mm:
            with db() as con:
                r=con.execute('SELECT source_case_id cid FROM case_relations WHERE id=?',(int(mm.group(1)),)).fetchone()
            return int(r['cid']) if r else None
        return None

    def do_GET(self):
        _REQUEST_CONTEXT.remote_addr = self.client_address[0] if self.client_address else ''
        _REQUEST_CONTEXT.signature_cache = {}
        u = urlparse(self.path)
        path, qs = u.path, parse_qs(u.query)
        if path.startswith('/assets/'):
            return self.send_asset(path.split('/')[-1])
        if path == '/manifest.webmanifest': return self.send_asset('manifest.webmanifest')
        if path == '/service-worker.js': return self.send_asset('service-worker.js')
        if path == "/system/heartbeat":
            client_heartbeat((qs.get("tab") or [""])[0]); return self.send_no_content()
        if path == "/system/ws":
            return self.websocket_presence((qs.get("tab") or [""])[0])
        if path == '/setup': return self.setup_page()
        if path == '/login': return self.login_page(qs)
        if not self.require_auth():
            return
        try:
            if path == '/onboarding': return self.onboarding_page()
            if path == '/account': return self.account_page()
            if path == '/admin/users': return self.users_page()
            if path == '/admin/user/new': return self.user_new_page()
            if re.fullmatch(r"/admin/user/\d+/edit", path): return self.user_edit_page(int(path.split('/')[3]))
            if path == "/": return self.dashboard()
            if path == "/today": return self.today_page(qs)
            if path == "/calendar": return self.calendar_page(qs)
            if path == "/law": return self.law_page(qs)
            if re.fullmatch(r"/law/[A-Za-z0-9_-]+", path): return self.law_page(qs, path.split("/")[2].upper())
            if path == "/quick-add": return self.quick_add_page(qs)
            if path == "/deadline": return self.deadline_page(qs)
            if path == "/cases": return self.cases(qs, closed_only=False)
            if path == "/cases/closed": return self.cases(qs, closed_only=True)
            if path == "/case/new": return self.case_new()
            if path == "/entities": return self.entities_page(qs)
            if path == "/entity/new": return self.entity_new_page()
            if re.fullmatch(r"/entity/\d+", path): return self.entity_view(int(path.split("/")[2]))
            if re.fullmatch(r"/entity/\d+/edit", path): return self.entity_edit_page(int(path.split("/")[2]))
            if path == "/checklists": return self.checklists_page()
            if path == "/audit": return self.immutable_audit_page(qs)
            if path == "/security": return self.security_page()
            if path == "/recovery": return self.recovery_page()
            if path == "/cloud": return self.cloud_page()
            if path == "/case/import": return self.case_import_page()
            if re.fullmatch(r"/case/\d+/export/package", path): return self.case_export_package(int(path.split("/")[2]))
            if path == "/trash": return self.trash_page(qs)
            if path == "/history": return self.history_page(qs)
            if path == "/backups": return self.backups_page()
            if re.fullmatch(r"/case/\d+/history", path): return self.case_history_page(int(path.split("/")[2]))
            if re.fullmatch(r"/process-event/\d+/edit", path): return self.process_event_edit(int(path.split("/")[2]))
            if re.fullmatch(r"/case/\d+", path): return self.case_view(int(path.split("/")[-1]), qs)
            if re.fullmatch(r"/case/\d+/edit", path): return self.case_edit(int(path.split("/")[-2]))
            if re.fullmatch(r"/case/\d+/delete", path): return self.case_delete_confirm(int(path.split("/")[-2]))
            if re.fullmatch(r"/case/\d+/export", path): return self.case_export_page(int(path.split("/")[-2]))
            if re.fullmatch(r"/case/\d+/export/pdf", path): return self.case_export_pdf(int(path.split("/")[-3]), qs, None)
            if re.fullmatch(r"/party/\d+/edit", path): return self.party_edit(int(path.split("/")[2]))
            if re.fullmatch(r"/event/\d+/edit", path): return self.event_edit(int(path.split("/")[2]))
            if re.fullmatch(r"/task/\d+/edit", path): return self.task_edit(int(path.split("/")[2]), qs)
            if re.fullmatch(r"/document/\d+/edit", path): return self.document_edit(int(path.split("/")[2]))
            if re.fullmatch(r"/relation/\d+/edit", path): return self.relation_edit(int(path.split("/")[2]))
            if re.fullmatch(r"/external-signature/\d+/edit", path): return self.external_signature_edit(int(path.split("/")[2]))
            if path == "/tasks": return self.tasks_page(qs)
            if path == "/views": return self.saved_views_page()
            if path == "/drafts":
                if (qs.get('view') or ['projects'])[0] == 'templates':
                    return self.draft_templates_page()
                return self.drafts_page(qs)
            if path == "/draft/new": return self.draft_new_page(qs)
            if path == "/draft/templates": return self.redirect('/drafts?view=templates')
            if re.fullmatch(r"/draft/\d+", path): return self.draft_view(int(path.split("/")[2]))
            if re.fullmatch(r"/draft/\d+/edit", path): return self.draft_edit_page(int(path.split("/")[2]))
            if re.fullmatch(r"/draft/\d+/download", path): return self.draft_download(int(path.split("/")[2]))
            if path == "/documents": return self.documents_page(qs)
            if path == "/tags": return self.tags_page(qs)
            if path == "/search": return self.search_page(qs)
            if path == "/backup": return self.backup()
            if path == "/backup/snapshot": return self.full_snapshot_download()
            if re.fullmatch(r"/document/\d+/open", path): return self.document_view(int(path.split("/")[2]), qs)
            if re.fullmatch(r"/document/\d+/download", path): return self.document_file(int(path.split("/")[2]), download=True)
            if re.fullmatch(r"/document/\d+/file", path): return self.document_file(int(path.split("/")[2]), download=False)
            if re.fullmatch(r"/document/\d+/page/\d+", path): return self.document_pdf_page(int(path.split("/")[2]), int(path.split("/")[4]))
            self.send_error(404)
        except Exception as e:
            log_app_exception(path, e)
            self.send_html(layout("Nie udało się wykonać operacji", f'<div class="card friendly-error"><div class="friendly-error-icon">!</div><h1>Coś poszło nie tak</h1><p>Nie udało się otworzyć tej części programu. Twoje zapisane dane nie zostały usunięte.</p><p><a class="btn primary" href="/">Wróć do pulpitu</a></p><details><summary>Pokaż szczegóły techniczne</summary><pre>{esc(str(e))}</pre><div class="small muted">Log: {esc(str(ERROR_LOG))}</div></details></div>'), 500)

    def do_POST(self):
        _REQUEST_CONTEXT.remote_addr = self.client_address[0] if self.client_address else ''
        _REQUEST_CONTEXT.signature_cache = {}
        u = urlparse(self.path); path = u.path
        try:
            fields, files = self.read_post()
        except OverflowError as exc:
            log_event(f"Odrzucono zbyt duże żądanie {path}: {exc}", "WARNING")
            return self.send_html(auth_layout('Plik jest zbyt duży', f"<div class='error'><b>Nie odebrano pliku.</b><br>{esc(str(exc))}</div>"), 413)
        except Exception as exc:
            log_app_exception(path + '/read-post', exc)
            return self.send_html(auth_layout('Błąd formularza', f"<div class='error'><b>Nie udało się odczytać przesłanych danych.</b><br>{esc(str(exc))}</div>"), 400)
        if path == "/system/closing":
            client_closing((parse_qs(u.query).get("tab") or [""])[0]); return self.send_no_content()
        if path == '/setup': return self.setup_create(fields)
        if path == '/login': return self.login_submit(fields)
        if path == '/desktop/quit' and DESKTOP_MODE:
            try:
                DESKTOP_EXIT_FLAG.parent.mkdir(parents=True, exist_ok=True)
                DESKTOP_EXIT_FLAG.write_text(str(time.time()), encoding='utf-8')
            except Exception as exc:
                log_app_exception('/desktop/quit', exc)
            return self.send_html(auth_layout('Zamykanie', "<div class='note'><b>RK KANCELARIA jest zamykana…</b></div>"))
        if not self.require_auth():
            return
        self._autosave_mode = fields.get("_autosave", "") == "1" or self.headers.get("X-Sprawnik-Autosave") == "1"
        # Zakończone sprawy są domyślnie tylko do odczytu. Usunięcie ma osobne,
        # administracyjne potwierdzenie i dlatego nie może utknąć na tej blokadzie.
        if not re.fullmatch(r"/case/\d+/(?:unlock|lock|pin|duplicate|delete)", path):
            cid_ro=self.mutation_case_id(path,fields)
            if cid_ro:
                with db() as con: ro=case_read_only(con,cid_ro)
                if ro:
                    return self.send_html(layout('Sprawa tylko do odczytu',f"<div class='readonly-banner'><b>Sprawa jest zakończona i zablokowana.</b> Administrator może ją odblokować z karty sprawy. <a class='btn' href='/case/{cid_ro}'>Wróć</a></div>",'cases'),403)
        try:
            if path == '/logout': return self.logout_submit()
            if path == '/account/update': return self.account_update(fields)
            if path == '/account/password': return self.account_password(fields)
            if path == '/admin/user/create': return self.user_create(fields)
            if re.fullmatch(r"/admin/user/\d+/update", path): return self.user_update(int(path.split('/')[3]), fields)
            if re.fullmatch(r"/admin/user/\d+/password", path): return self.user_password_reset(int(path.split('/')[3]), fields)
            if re.fullmatch(r"/admin/user/\d+/delete", path): return self.user_delete(int(path.split('/')[3]), fields)
            if path == "/entity/create": return self.entity_create(fields)
            if re.fullmatch(r"/entity/\d+/update", path): return self.entity_update(int(path.split('/')[2]), fields)
            if re.fullmatch(r"/case/\d+/entity", path): return self.case_entity_add(int(path.split('/')[2]), fields)
            if re.fullmatch(r"/case-entity/\d+/delete", path): return self.case_entity_delete(int(path.split('/')[2]), fields)
            if path == "/checklist/template/create": return self.checklist_template_create(fields)
            if re.fullmatch(r"/checklist/template/\d+/delete", path): return self.checklist_template_delete(int(path.split('/')[3]), fields)
            if re.fullmatch(r"/case/\d+/checklist/apply", path): return self.case_checklist_apply(int(path.split('/')[2]), fields)
            if re.fullmatch(r"/case/\d+/checklist/add", path): return self.case_checklist_add(int(path.split('/')[2]), fields)
            if re.fullmatch(r"/checklist/item/\d+/toggle", path): return self.checklist_item_toggle(int(path.split('/')[3]), fields)
            if re.fullmatch(r"/checklist/item/\d+/delete", path): return self.checklist_item_delete(int(path.split('/')[3]), fields)
            if re.fullmatch(r"/case/\d+/unlock", path): return self.case_unlock(int(path.split('/')[2]), fields)
            if re.fullmatch(r"/case/\d+/lock", path): return self.case_lock(int(path.split('/')[2]), fields)
            if path == "/admin/reindex-documents": return self.reindex_documents(fields)
            if path == "/security/ocr/install": return self.ocr_install_start(fields)
            if path == "/security/key": return self.security_key_update(fields)
            if path == "/backup/encrypted": return self.encrypted_backup(fields)
            if path == "/backup/manual": return self.manual_backup_now(fields)
            if path == "/recovery/check": return self.recovery_check(fields)
            if path == "/recovery/test-restore": return self.recovery_test_restore(fields)
            if path == "/recovery/snapshot-import": return self.full_snapshot_import(fields, files)
            if path == "/cloud/config": return self.cloud_config_update(fields)
            if path == "/cloud/check": return self.cloud_check(fields)
            if path == "/cloud/push": return self.cloud_push(fields)
            if path == "/cloud/pull": return self.cloud_pull(fields)
            if path == "/backups/restore": return self.backup_restore_schedule(fields)
            if path == "/data/import-installed": return self.data_import_installed(fields)
            if re.fullmatch(r"/document/\d+/relocate", path): return self.document_relocate(int(path.split("/")[2]), fields, files)
            if re.fullmatch(r"/document/\d+/open-default", path): return self.document_open_default(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/document/\d+/open-folder", path): return self.document_open_folder(int(path.split("/")[2]), fields)
            if path == "/case/import": return self.case_import(fields, files)
            if path == "/draft/create": return self.draft_create(fields, files)
            if path == "/draft/template/create": return self.draft_template_create(fields)
            if re.fullmatch(r"/draft/template/\d+/delete", path): return self.draft_template_delete(int(path.split("/")[3]), fields)
            if path == "/draft/from-template": return self.draft_from_template(fields)
            if re.fullmatch(r"/draft/\d+/version/\d+/restore", path): return self.draft_version_restore(int(path.split("/")[2]), int(path.split("/")[4]), fields)
            if re.fullmatch(r"/draft/\d+/update", path): return self.draft_update(int(path.split("/")[2]), fields, files)
            if re.fullmatch(r"/draft/\d+/archive", path): return self.draft_archive(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/draft/\d+/to-document", path): return self.draft_to_document(int(path.split("/")[2]), fields)
            if path == "/alert/create": return self.alert_create(fields)
            if re.fullmatch(r"/alert/\d+/toggle", path): return self.alert_toggle(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/alert/\d+/delete", path): return self.alert_delete(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/case/\d+/smart-link", path): return self.smart_link_add(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/smart-link/\d+/delete", path): return self.smart_link_delete(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/law/[A-Za-z0-9_-]+/update", path): return self.law_update(path.split("/")[2].upper(), fields)
            if path == "/law/add-eli": return self.law_add_eli(fields)
            if re.fullmatch(r"/case/\d+/law-link", path): return self.case_law_link_add(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/case/\d+/strategy", path): return self.case_strategy_update(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/case/\d+/assertion", path): return self.case_assertion_add(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/assertion/\d+/update", path): return self.case_assertion_update(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/assertion/\d+/delete", path): return self.case_assertion_delete(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/assertion/\d+/evidence", path): return self.case_evidence_add(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/evidence/\d+/delete", path): return self.case_evidence_delete(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/case/\d+/claim", path): return self.case_claim_add(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/claim/\d+/update", path): return self.case_claim_update(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/claim/\d+/delete", path): return self.case_claim_delete(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/case/\d+/document-event", path): return self.document_event_add(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/document-event/\d+/delete", path): return self.document_event_delete(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/law-case-link/\d+/delete", path): return self.case_law_link_delete(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/document/\d+/suggest-deadlines", path): return self.document_deadline_suggest(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/deadline-suggestion/\d+/accept", path): return self.deadline_suggestion_accept(int(path.split("/")[2]), fields)
            if path == "/case/create": return self.case_create(fields)
            if path == "/task/create": return self.task_add_global(fields)
            if path == "/view/save": return self.saved_view_save(fields)
            if re.fullmatch(r"/view/\d+/delete", path): return self.saved_view_delete(int(path.split('/')[2]), fields)
            if path == "/deadline/create": return self.deadline_create(fields)
            if path == "/quick/event": return self.quick_event_add(fields)
            if path == "/quick/note": return self.quick_note_add(fields)
            if path == "/quick/document": return self.quick_document_add(fields, files)
            if re.fullmatch(r"/case/\d+/update", path): return self.case_update(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/case/\d+/next-action", path): return self.case_next_action(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/case/\d+/next-action/complete", path): return self.case_next_action_complete(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/case/\d+/process-event", path): return self.process_event_add(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/case/\d+/delete", path): return self.case_delete(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/case/\d+/pin", path): return self.case_pin_toggle(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/case/\d+/duplicate", path): return self.case_duplicate(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/case/\d+/party", path): return self.party_add(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/case/\d+/event", path): return self.event_add(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/case/\d+/task", path): return self.task_add(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/case/\d+/document", path): return self.document_add(int(path.split("/")[2]), fields, files)
            if re.fullmatch(r"/case/\d+/relation", path): return self.relation_add(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/case/\d+/external-signature", path): return self.external_signature_add(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/case/\d+/note", path): return self.note_add(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/note/\d+/delete", path): return self.note_delete(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/case/\d+/export/pdf", path): return self.case_export_pdf(int(path.split("/")[2]), {}, fields)
            if re.fullmatch(r"/party/\d+/update", path): return self.party_update(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/event/\d+/update", path): return self.event_update(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/process-event/\d+/update", path): return self.process_event_update(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/process-event/\d+/toggle", path): return self.process_event_toggle(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/process-event/\d+/delete", path): return self.process_event_delete(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/task/\d+/update", path): return self.task_update(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/document/\d+/update", path): return self.document_update(int(path.split("/")[2]), fields, files)
            if re.fullmatch(r"/document/\d+/version/\d+/restore", path): return self.document_version_restore(int(path.split("/")[2]),int(path.split("/")[4]),fields)
            if re.fullmatch(r"/relation/\d+/update", path): return self.relation_update(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/external-signature/\d+/update", path): return self.external_signature_update(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/task/\d+/toggle", path): return self.task_toggle(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/task/\d+/delete", path): return self.task_delete(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/event/\d+/delete", path): return self.event_delete(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/document/\d+/delete", path): return self.document_delete(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/party/\d+/delete", path): return self.party_delete(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/relation/\d+/delete", path): return self.relation_delete(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/external-signature/\d+/delete", path): return self.external_signature_delete(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/trash/\d+/restore", path): return self.trash_restore(int(path.split("/")[2]), fields)
            if re.fullmatch(r"/trash/\d+/purge", path): return self.trash_purge(int(path.split("/")[2]), fields)
            self.send_error(404)
        except Exception as e:
            log_app_exception(path, e)
            self.send_html(layout("Nie udało się wykonać operacji", f'<div class="card friendly-error"><div class="friendly-error-icon">!</div><h1>Coś poszło nie tak</h1><p>Nie udało się otworzyć tej części programu. Twoje zapisane dane nie zostały usunięte.</p><p><a class="btn primary" href="/">Wróć do pulpitu</a></p><details><summary>Pokaż szczegóły techniczne</summary><pre>{esc(str(e))}</pre><div class="small muted">Log: {esc(str(ERROR_LOG))}</div></details></div>'), 500)

    def setup_page(self, error=''):
        if user_count() > 0:
            return self.redirect('/login')
        err = f"<div class='error'>{esc(error)}</div>" if error else "<div class='note'>Pierwsze uruchomienie: utwórz konto administratora. Będzie ono zarządzać pozostałymi kontami.</div>"
        body=f"""{err}<form method='post' action='/setup'><label>Login administratora</label><input name='username' autocomplete='username' required><label>Autor wpisów / imię i nazwisko</label><input name='author_name' value='{APP_AUTHOR}' required><label>Funkcja</label><input name='function' placeholder='np. Adwokat, Aplikant, Asystent, Prawnik'><label>Hasło</label><input type='password' name='password' autocomplete='new-password' minlength='8' required><label>Powtórz hasło</label><input type='password' name='password2' autocomplete='new-password' minlength='8' required><button>Utwórz konto administratora</button></form>"""
        self.send_html(auth_layout('Pierwsza konfiguracja',body))

    def setup_create(self, f):
        if user_count() > 0:
            return self.redirect('/login')
        username=normalize_username(f.get('username','') or '')
        author=(f.get('author_name','') or '').strip()[:120]
        function=(f.get('function','') or '').strip()[:120]
        pw=f.get('password','') or ''; pw2=f.get('password2','') or ''
        if not valid_username(username): return self.setup_page('Login musi mieć 3–80 znaków. Może zawierać litery (także polskie), cyfry, spacje, kropkę, _, @ lub -.')
        if not author: return self.setup_page('Podaj autora wpisów.')
        if len(pw)<8: return self.setup_page('Hasło musi mieć co najmniej 8 znaków.')
        if pw!=pw2: return self.setup_page('Hasła nie są identyczne.')
        ph,salt=password_hash(pw)
        with db() as con:
            cur=con.execute("INSERT INTO users(username,author_name,password_hash,password_salt,role,function,is_active) VALUES(?,?,?,?, 'admin',?,1)",(username,author,ph,salt,function))
            uid=cur.lastrowid
        token=make_session(uid)
        self.send_response(303); self.send_header('Location','/onboarding'); self.set_session_cookie(token); self.end_headers()

    def onboarding_page(self):
        with db() as con:
            case_count=con.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
            task_count=con.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            doc_count=con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        case_state='done' if case_count else 'current'
        work_state='done' if (task_count or doc_count) else ('current' if case_count else '')
        body=f"""<div class='onboarding-wrap'><div class='onboarding-hero'><div class='eyebrow'>WITAJ W RK KANCELARIA</div><h1>Trzy kroki i możesz pracować</h1><p>Nie musisz poznawać całego programu. Zacznij od sprawy, a reszta pojawi się wtedy, kiedy będzie potrzebna.</p></div><div class='onboarding-steps'><div class='onboarding-step done'><span>1</span><div><b>Konto gotowe</b><small>Jesteś zalogowany. Program zapisuje autora każdej czynności.</small></div><strong>✓</strong></div><div class='onboarding-step {case_state}'><span>2</span><div><b>Dodaj pierwszą sprawę</b><small>Wystarczy nazwa i jedno zdanie: czego dotyczy sprawa.</small></div><a class='btn primary' href='/case/new'>{'Dodaj sprawę' if not case_count else 'Sprawy'}</a></div><div class='onboarding-step {work_state}'><span>3</span><div><b>Dodaj zadanie albo dokument</b><small>To wystarczy, aby zacząć korzystać z pulpitu i historii sprawy.</small></div><a class='btn' href='/quick-add'>Szybko dodaj</a></div></div><div class='onboarding-footer'><a class='btn primary' href='/'>Przejdź do pulpitu</a><span class='small muted'>Zaawansowane funkcje znajdziesz później w sekcji System.</span></div></div>"""
        self.send_html(layout('Pierwsze kroki',body,'dashboard'))

    def login_page(self, qs=None, error=''):
        if user_count()==0: return self.redirect('/setup')
        if self.is_authorized(): return self.redirect('/')
        qerr=(qs or {}).get('error',[''])[0] if qs else ''
        msg=error or ('Nieprawidłowy login lub hasło.' if qerr else '')
        err=f"<div class='error'>{esc(msg)}</div>" if msg else ''
        close_btn = ""
        if DESKTOP_MODE:
            close_btn = """<form method='post' action='/desktop/quit'><button type='submit' style='margin-top:10px;background:#fff;color:#7d2828;border:1px solid #d9b6b6'>Zamknij program</button></form>"""
        body=f"""{err}<form method='post' action='/login'><label>Login</label><input name='username' autocomplete='username' autofocus required><label>Hasło</label><input type='password' name='password' autocomplete='current-password' required><button>Zaloguj</button></form>{close_btn}"""
        self.send_html(auth_layout('Logowanie',body))

    def login_submit(self, f):
        username=normalize_username(f.get('username','') or ''); pw=f.get('password','') or ''
        with db() as con:
            u=con.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE AND is_active=1",(username,)).fetchone()
        if not u or not verify_password(pw,u['password_hash'],u['password_salt']):
            return self.login_page(error='Nieprawidłowy login lub hasło albo konto jest nieaktywne.')
        token=make_session(u['id'])
        self.send_response(303); self.send_header('Location','/'); self.set_session_cookie(token); self.end_headers()

    def logout_submit(self):
        token=self.cookie_value(SESSION_COOKIE); destroy_session(token)
        self.send_response(303); self.send_header('Location','/login'); self.clear_session_cookie(); self.end_headers()

    def account_page(self, message=''):
        u=current_request_user()
        notice=f"<div class='notice'>{esc(message)}</div>" if message else ''
        role='Administrator' if u['role']=='admin' else 'Użytkownik'
        body=f"""<div class='topbar'><div><h1>Moje konto</h1><div class='sub'>Edytuj własny login, autora wpisów, funkcję i hasło.</div></div><a class='btn' href='/'>Wróć</a></div>{notice}<div class='grid'><div class='card span6'><h2>Dane konta</h2><form method='post' action='/account/update' class='form-grid'><div class='full'><label>Login</label><input name='username' value='{esc(u['username'])}' required><div class='small muted'>Login może zawierać spacje, np. „Robert Kłosowski”.</div></div><div class='full'><label>Autor wpisów</label><input name='author_name' value='{esc(u['author_name'])}' required></div><div class='full'><label>Funkcja</label><input name='function' value='{esc(u['function'])}' placeholder='np. Adwokat, Aplikant, Asystent, Prawnik'></div><div class='full'><label>Uprawnienia</label><input value='{role}' disabled></div><div class='full'><button class='btn primary'>Zapisz moje dane</button></div></form><p class='small muted'>Zmiana autora wpływa tylko na nowe wpisy. Dotychczasowe rekordy zachowują autora zapisanego w chwili ich utworzenia lub modyfikacji.</p></div><div class='card span6'><h2>Zmień hasło</h2><form method='post' action='/account/password'><label>Obecne hasło</label><input type='password' name='current_password' required><label>Nowe hasło</label><input type='password' name='new_password' minlength='8' required><label>Powtórz nowe hasło</label><input type='password' name='new_password2' minlength='8' required><button class='btn primary' style='margin-top:12px'>Zmień hasło</button></form></div></div>"""
        self.send_html(layout('Moje konto',body))

    def account_update(self, f):
        u=current_request_user()
        username=normalize_username(f.get('username','') or '')
        author=(f.get('author_name','') or '').strip()[:120]
        function=(f.get('function','') or '').strip()[:120]
        if not valid_username(username):
            return self.account_page('Nieprawidłowy login. Dozwolone są litery, cyfry, spacje oraz . _ @ -.')
        if not author:
            return self.account_page('Podaj autora wpisów.')
        try:
            with db() as con:
                con.execute("UPDATE users SET username=?,author_name=?,function=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(username,author,function,u['id']))
        except sqlite3.IntegrityError:
            return self.account_page('Taki login już istnieje.')
        # Odśwież dane użytkownika w kontekście bieżącego żądania.
        with db() as con:
            _REQUEST_CONTEXT.user=con.execute("SELECT * FROM users WHERE id=?",(u['id'],)).fetchone()
        return self.account_page('Dane konta zostały zmienione.')

    def account_password(self, f):
        u=current_request_user(); cur=f.get('current_password','') or ''; new=f.get('new_password','') or ''; new2=f.get('new_password2','') or ''
        if not verify_password(cur,u['password_hash'],u['password_salt']): return self.account_page('Obecne hasło jest nieprawidłowe.')
        if len(new)<8: return self.account_page('Nowe hasło musi mieć co najmniej 8 znaków.')
        if new!=new2: return self.account_page('Nowe hasła nie są identyczne.')
        ph,salt=password_hash(new)
        with db() as con: con.execute("UPDATE users SET password_hash=?,password_salt=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(ph,salt,u['id']))
        return self.account_page('Hasło zostało zmienione.')

    def users_page(self, message=''):
        if not self.require_admin(): return
        with db() as con: rows=con.execute("SELECT * FROM users ORDER BY is_active DESC, role='admin' DESC, author_name COLLATE NOCASE").fetchall()
        trs=[]
        for r in rows:
            role='Administrator' if r['role']=='admin' else 'Użytkownik'; active='Aktywne' if r['is_active'] else 'Nieaktywne'
            trs.append(f"<tr><td><b>{esc(r['author_name'])}</b><div class='small muted'>@{esc(r['username'])}</div></td><td>{esc(r['function']) or '—'}</td><td>{role}</td><td>{active}</td><td>{esc(r['created_at'])}</td><td><a class='btn small' href='/admin/user/{r['id']}/edit'>Edytuj</a></td></tr>")
        notice=f"<div class='notice'>{esc(message)}</div>" if message else ''
        body=f"""<div class='topbar'><div><h1>Użytkownicy</h1><div class='sub'>Konta, funkcje, uprawnienia i autorzy wpisów.</div></div><a class='btn primary' href='/admin/user/new'>+ Nowe konto</a></div>{notice}<div class='card'><table><tr><th>Konto / autor</th><th>Funkcja</th><th>Uprawnienia</th><th>Status</th><th>Utworzono</th><th></th></tr>{''.join(trs)}</table></div>"""
        self.send_html(layout('Użytkownicy',body,'users'))

    def user_new_page(self, error=''):
        if not self.require_admin(): return
        err=f"<div class='notice' style='background:#fee2e2;color:#991b1b;border-color:#fecaca'>{esc(error)}</div>" if error else ''
        body=f"""<div class='topbar'><div><h1>Nowe konto</h1><div class='sub'>Autor wszystkich nowych wpisów będzie automatycznie pobierany z tego konta.</div></div><a class='btn' href='/admin/users'>Anuluj</a></div>{err}<div class='card'><form method='post' action='/admin/user/create' class='form-grid'><div><label>Login *</label><input name='username' required></div><div><label>Autor wpisów *</label><input name='author_name' placeholder='Imię i nazwisko' required></div><div><label>Funkcja</label><input name='function' placeholder='np. Adwokat, Aplikant, Asystent, Prawnik'></div><div><label>Uprawnienia</label><select name='role'><option value='user'>Użytkownik</option><option value='admin'>Administrator</option></select></div><div><label>Hasło startowe *</label><input type='password' name='password' minlength='8' required></div><div class='full'><button class='btn primary'>Utwórz konto</button></div></form></div>"""
        self.send_html(layout('Nowe konto',body,'users'))

    def user_create(self, f):
        if not self.require_admin(): return
        username=normalize_username(f.get('username','') or ''); author=(f.get('author_name','') or '').strip()[:120]; function=(f.get('function','') or '').strip()[:120]; role=f.get('role','user'); pw=f.get('password','') or ''
        if role not in {'admin','user'}: role='user'
        if not valid_username(username): return self.user_new_page('Nieprawidłowy login. Dozwolone są litery, cyfry, spacje oraz . _ @ -.')
        if not author: return self.user_new_page('Podaj autora wpisów.')
        if len(pw)<8: return self.user_new_page('Hasło musi mieć co najmniej 8 znaków.')
        ph,salt=password_hash(pw)
        try:
            with db() as con: con.execute("INSERT INTO users(username,author_name,password_hash,password_salt,role,function,is_active) VALUES(?,?,?,?,?,?,1)",(username,author,ph,salt,role,function))
        except sqlite3.IntegrityError: return self.user_new_page('Taki login już istnieje.')
        return self.redirect('/admin/users')

    def user_edit_page(self, uid, message=''):
        if not self.require_admin(): return
        with db() as con: u=con.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
        if not u: return self.send_error(404)
        me=current_request_user()
        notice=f"<div class='notice'>{esc(message)}</div>" if message else ''
        role_opts=f"<option value='user' {'selected' if u['role']=='user' else ''}>Użytkownik</option><option value='admin' {'selected' if u['role']=='admin' else ''}>Administrator</option>"
        checked='checked' if u['is_active'] else ''
        if uid==me['id']:
            delete_html="<div class='notice'>Nie można usunąć konta, na którym jesteś aktualnie zalogowany.</div>"
        else:
            delete_html=f"""<form method='post' action='/admin/user/{uid}/delete' onsubmit="return confirm('Usunąć konto {esc(u['username'])}? Dane wprowadzone przez to konto NIE zostaną usunięte, a autorzy historycznych wpisów zostaną zachowani.');"><button class='btn danger'>Usuń konto</button></form><p class='small muted'>Usunięcie konta usuwa wyłącznie możliwość logowania i jego sesje. Sprawy, zadania, dokumenty, zdarzenia, relacje i zapisani autorzy pozostają bez zmian.</p>"""
        body=f"""<div class='topbar'><div><h1>Edytuj konto</h1><div class='sub'>@{esc(u['username'])}</div></div><a class='btn' href='/admin/users'>Wróć</a></div>{notice}<div class='grid'><div class='card span7'><h2>Dane konta</h2><form method='post' action='/admin/user/{uid}/update' class='form-grid'><div><label>Login</label><input name='username' value='{esc(u['username'])}' required><div class='small muted'>Login może zawierać spacje.</div></div><div><label>Autor wpisów</label><input name='author_name' value='{esc(u['author_name'])}' required></div><div><label>Funkcja</label><input name='function' value='{esc(u['function'])}' placeholder='np. Adwokat, Aplikant, Asystent, Prawnik'></div><div><label>Uprawnienia</label><select name='role'>{role_opts}</select></div><div><label>Status</label><label style='font-size:14px;font-weight:500'><input style='width:auto' type='checkbox' name='is_active' value='1' {checked}> Konto aktywne</label></div><div class='full'><button class='btn primary'>Zapisz konto</button></div></form></div><div class='card span5'><h2>Reset hasła</h2><form method='post' action='/admin/user/{uid}/password'><label>Nowe hasło</label><input type='password' name='password' minlength='8' required><label>Powtórz hasło</label><input type='password' name='password2' minlength='8' required><button class='btn' style='margin-top:12px'>Ustaw nowe hasło</button></form><p class='small muted'>Po resecie istniejące sesje tego konta zostaną wylogowane.</p><hr style='border:0;border-top:1px solid #e5ece8;margin:22px 0'><h2>Usuń konto</h2>{delete_html}</div></div>"""
        self.send_html(layout('Edytuj konto',body,'users'))

    def user_update(self, uid, f):
        if not self.require_admin(): return
        me=current_request_user(); username=normalize_username(f.get('username','') or ''); author=(f.get('author_name','') or '').strip()[:120]; function=(f.get('function','') or '').strip()[:120]; role=f.get('role','user'); active=1 if f.get('is_active') else 0
        if not valid_username(username) or not author: return self.user_edit_page(uid,'Nieprawidłowe dane konta. Login może zawierać także spacje.')
        if role not in {'admin','user'}: role='user'
        if uid==me['id'] and (role!='admin' or not active): return self.user_edit_page(uid,'Nie możesz odebrać sobie uprawnień administratora ani wyłączyć własnego aktywnego konta.')
        try:
            with db() as con:
                con.execute("UPDATE users SET username=?,author_name=?,function=?,role=?,is_active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(username,author,function,role,active,uid))
                if not active:
                    con.execute("DELETE FROM user_sessions WHERE user_id=?",(uid,))
        except sqlite3.IntegrityError: return self.user_edit_page(uid,'Taki login już istnieje.')
        return self.redirect(f'/admin/user/{uid}/edit')

    def user_password_reset(self, uid, f):
        if not self.require_admin(): return
        pw=f.get('password','') or ''; pw2=f.get('password2','') or ''
        if len(pw)<8: return self.user_edit_page(uid,'Hasło musi mieć co najmniej 8 znaków.')
        if pw!=pw2: return self.user_edit_page(uid,'Hasła nie są identyczne.')
        ph,salt=password_hash(pw)
        with db() as con:
            con.execute("UPDATE users SET password_hash=?,password_salt=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(ph,salt,uid))
            con.execute("DELETE FROM user_sessions WHERE user_id=?",(uid,))
        return self.redirect('/admin/users')

    def user_delete(self, uid, f):
        if not self.require_admin(): return
        me=current_request_user()
        if uid==me['id']:
            return self.user_edit_page(uid,'Nie możesz usunąć konta, na którym jesteś aktualnie zalogowany.')
        with db() as con:
            u=con.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
            if not u:
                return self.send_error(404)
            if u['role']=='admin' and u['is_active']:
                active_admins=con.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1").fetchone()[0]
                if active_admins<=1:
                    return self.user_edit_page(uid,'Nie można usunąć ostatniego aktywnego administratora.')
            # Dane merytoryczne nie mają klucza obcego do konta. Autorzy są zapisani
            # tekstowo przy rekordach, więc usunięcie konta nie usuwa ani nie zmienia historii.
            con.execute("DELETE FROM users WHERE id=?",(uid,))
        return self.users_page(f"Konto „{u['username']}” zostało usunięte. Wszystkie dane i historyczne informacje o autorach zostały zachowane.")

    def today_page(self, qs):
        today = date.today().isoformat()
        week_end = (date.today() + timedelta(days=7)).isoformat()
        u=current_request_user(); uid=u['id'] if u else 0
        with db() as con:
            tasks=con.execute("""SELECT t.*,c.title case_title,c.signature,c.internal_signature,
                                 u.author_name assigned_name,u.function assigned_function
                                 FROM tasks t JOIN cases c ON c.id=t.case_id
                                 LEFT JOIN users u ON u.id=t.assigned_user_id
                                 WHERE t.status='open' AND c.status<>'closed'
                                 AND t.due_date<>'' AND t.due_date<=?
                                 ORDER BY t.due_date,CASE t.priority WHEN 'high' THEN 0 ELSE 1 END,t.id""",(today,)).fetchall()
            next_cases=con.execute("""SELECT * FROM cases WHERE status<>'closed' AND next_date<>'' AND next_date BETWEEN ? AND ?
                                      ORDER BY next_date,title LIMIT 40""",(today,week_end)).fetchall()
            waiting=con.execute("""SELECT * FROM cases WHERE status<>'closed' AND waiting_for<>'' ORDER BY updated_at DESC LIMIT 20""").fetchall()
            sign_docs=con.execute("""SELECT d.*,c.title case_title,c.signature,c.internal_signature FROM documents d
                                     JOIN cases c ON c.id=d.case_id WHERE c.status<>'closed' AND d.doc_status='Do podpisu'
                                     ORDER BY d.created_at DESC LIMIT 20""").fetchall()
            sign_drafts=con.execute("""SELECT w.*,c.title case_title,c.signature,c.internal_signature FROM writing_projects w
                                       JOIN cases c ON c.id=w.case_id WHERE c.status<>'closed' AND w.status='Do podpisu'
                                       ORDER BY w.updated_at DESC LIMIT 20""").fetchall()
            ids=[r['case_id'] for r in tasks]+[r['id'] for r in next_cases]+[r['id'] for r in waiting]+[r['case_id'] for r in sign_docs]+[r['case_id'] for r in sign_drafts]
            sig_map=load_external_signature_map(con,ids)
        task_rows=[]
        for r in tasks:
            label=primary_signature_fast(r['case_id'],r['signature'],sig_map)
            when="dzisiaj" if r['due_date']==today else "PO TERMINIE"
            cls='today' if r['due_date']==today else 'danger'
            assigned=''
            if r['assigned_name']:
                assigned=f"<div class='small muted'>Wykonawca: {esc(r['assigned_name'])}{' — '+esc(r['assigned_function']) if r['assigned_function'] else ''}</div>"
            meta=''
            if row_get(r,'deadline_base_date',''):
                meta=f"<div class='small deadline-meta'>wyliczono od {fmt_date(r['deadline_base_date'])} · {esc(str(row_get(r,'deadline_days','')))} dni · {esc(row_get(r,'deadline_rule',''))}</div>"
            task_rows.append(f"<tr><td><span class='due-chip {cls}'>{when}</span><b>{fmt_date(r['due_date'])}</b></td><td><a class='case-link' href='/case/{r['case_id']}'>{esc(label)}</a><div class='small muted'>{esc(r['case_title'])}</div></td><td><b>{esc(r['title'])}</b>{assigned}{meta}</td><td><a class='btn small' href='/task/{r['id']}/edit?return_to=%2Ftoday'>Edytuj</a></td></tr>")
        case_rows=[]
        for r in next_cases:
            label=primary_signature_fast(r['id'],r['signature'],sig_map)
            case_rows.append(f"<tr><td>{fmt_date(r['next_date'])}</td><td><a class='case-link' href='/case/{r['id']}'>{esc(label)}</a><div class='small muted'>{esc(r['title'])}</div></td><td>{esc(r['next_step']) or '—'}</td></tr>")
        waiting_html=''.join(f"<div class='work-item'><a class='case-link' href='/case/{r['id']}'>{esc(primary_signature_fast(r['id'],r['signature'],sig_map))}</a><b>{esc(r['waiting_for'])}</b><div class='small muted'>{esc(r['title'])}</div></div>" for r in waiting) or '<div class="empty">Brak spraw oznaczonych „czekamy na”.</div>'
        sign_parts=[]
        for r in sign_docs:
            label=primary_signature_fast(r['case_id'],r['signature'],sig_map)
            sign_parts.append(f"<div class='work-item'><span class='pill'>Dokument</span><a class='case-link' href='/document/{r['id']}/open'>{esc(r['title'])}</a><div class='small muted'>{esc(label)} · {esc(r['case_title'])}</div></div>")
        for r in sign_drafts:
            label=primary_signature_fast(r['case_id'],r['signature'],sig_map)
            sign_parts.append(f"<div class='work-item'><span class='pill'>Projekt pisma</span><a class='case-link' href='/draft/{r['id']}'>{esc(r['title'])}</a><div class='small muted'>{esc(label)} · {esc(r['case_title'])}</div></div>")
        body=f"""<div class='topbar'><div><h1>Dzisiaj</h1><div class='sub'>Jedna kolejka pracy: zaległe i dzisiejsze zadania, najbliższe ruchy oraz rzeczy do podpisu.</div></div><div><a class='btn primary' href='/quick-add'>+ Dodaj czynność</a> <a class='btn' href='/tasks?mine=1'>Moje zadania</a></div></div>
        <div class='grid'>
          <div class='card span12'><div class='section-head'><div><h2>Zadania wymagające działania</h2><div class='small muted'>Po terminie i z terminem na dzisiaj.</div></div><a class='btn small' href='/tasks?filter=overdue'>Wszystkie zaległe</a></div><div class='table-scroll'><table><tr><th>Termin</th><th>Sprawa</th><th>Czynność</th><th></th></tr>{''.join(task_rows) or '<tr><td colspan=4>Na dziś nie ma zaległych ani dzisiejszych zadań.</td></tr>'}</table></div></div>
          <div class='card span7'><div class='section-head'><h2>Następne ruchy — 7 dni</h2><a class='btn small' href='/cases?focus=7d'>Sprawy</a></div><table><tr><th>Data</th><th>Sprawa</th><th>Następny krok</th></tr>{''.join(case_rows) or '<tr><td colspan=3>Brak wskazanych ruchów w najbliższych 7 dniach.</td></tr>'}</table></div>
          <div class='card span5'><h2>Do podpisu</h2>{''.join(sign_parts) or '<div class="empty">Brak dokumentów i projektów do podpisu.</div>'}</div>
          <div class='card span12'><div class='section-head'><div><h2>Czekamy na</h2><div class='small muted'>Sprawy, w których następny ruch zależy od sądu, klienta, organu lub przeciwnika.</div></div><a class='btn small' href='/cases?focus=waiting'>Pokaż sprawy</a></div><div class='work-grid'>{waiting_html}</div></div>
        </div>"""
        self.send_html(layout('Dzisiaj',body,'today'))

    def _quick_case_and_user_options(self):
        with db() as con:
            cases=con.execute("SELECT id,signature,internal_signature,title FROM cases WHERE status<>'closed' OR closed_edit_unlocked=1 ORDER BY signature='',signature,title").fetchall()
            users=con.execute("SELECT id,author_name,function FROM users WHERE is_active=1 ORDER BY author_name").fetchall()
            sig_map=load_external_signature_map(con,[r['id'] for r in cases])
        case_opts=[]
        for c in cases:
            sig=primary_signature_fast(c['id'],c['signature'],sig_map)
            prefix='' if sig=='Bez sygnatury' else sig+' — '
            case_opts.append(f"<option value='{c['id']}'>{esc(prefix+c['title'])} · {esc(internal_signature_text(c['internal_signature']))}</option>")
        user_opts='<option value="">— nie przypisano —</option>'+''.join(f"<option value='{x['id']}'>{esc(user_display_name(x))}</option>" for x in users)
        return ''.join(case_opts),user_opts

    def quick_add_page(self,qs):
        case_opts,user_opts=self._quick_case_and_user_options()
        event_opts=''.join(f"<option>{esc(x)}</option>" for x in EVENT_TYPES)
        doc_opts=''.join(f"<option>{esc(x)}</option>" for x in DOC_TYPES)
        doc_status_opts=''.join(f"<option>{esc(x)}</option>" for x in DOC_STATUSES)
        done=(qs.get('done') or [''])[0]
        notice=f"<div class='notice'>Dodano: <b>{esc(done)}</b>.</div>" if done else ''
        if not case_opts:
            return self.send_html(layout('Dodaj czynność',"<div class='card'><h1>Dodaj czynność</h1><p>Najpierw utwórz aktywną sprawę.</p><a class='btn primary' href='/case/new'>+ Nowa sprawa</a></div>"))
        body=f"""<div class='topbar'><div><h1>+ Dodaj czynność</h1><div class='sub'>Szybkie dodawanie z dowolnego miejsca w programie.</div></div><div><a class='btn' href='/case/new'>+ Sprawa</a> <a class='btn' href='/draft/new'>+ Projekt pisma</a></div></div>{notice}
        <div class='quick-add-grid'>
          <div class='card quick-add-card'><h2>Zadanie / monit</h2><form method='post' action='/task/create' class='form-grid'><input type='hidden' name='return_to' value='/quick-add?done=zadanie'><div class='full'><label>Sprawa *</label><select name='case_id' required><option value=''>— wybierz —</option>{case_opts}</select></div><div><label>Rodzaj</label><select name='task_type'><option>Zadanie</option><option>Monit</option><option>Termin procesowy</option><option>Płatność</option></select></div><div><label>Termin</label><input type='date' name='due_date'></div><div class='full'><label>Co trzeba zrobić? *</label><input name='title' required></div><div><label>Priorytet</label><select name='priority'><option value='normal'>Normalny</option><option value='high'>Wysoki</option></select></div><div><label>Wykonawca</label><select name='assigned_user_id'>{user_opts}</select></div><div class='full'><label>Czekamy na / zależność</label><input name='depends_on'></div><div class='full'><button class='btn primary'>Dodaj</button></div></form></div>
          <div class='card quick-add-card' id='deadline'><h2>Termin procesowy</h2><div class='small muted' style='margin-bottom:10px'>Pomocnicze wyliczenie — dzień początkowy nie jest liczony; końcowa sobota/niedziela/święto jest przesuwana. Zawsze zweryfikuj podstawę prawną.</div><form method='post' action='/deadline/create' class='form-grid'><input type='hidden' name='return_to' value='/today'><div class='full'><label>Sprawa *</label><select name='case_id' required><option value=''>— wybierz —</option>{case_opts}</select></div><div class='full'><label>Czynność *</label><input name='title' required placeholder='np. Wnieść odpowiedź na zażalenie'></div><div><label>Data początkowa *</label><input type='date' name='base_date' required></div><div><label>Liczba dni *</label><input type='number' min='0' max='3650' name='days' required value='7'></div><div><label>Sposób liczenia</label><select name='rule'><option value='calendar'>Dni kalendarzowe / procesowe</option><option value='business'>Dni robocze</option></select></div><div><label>Priorytet</label><select name='priority'><option value='high'>Wysoki</option><option value='normal'>Normalny</option></select></div><div class='full'><label>Podstawa / źródło terminu</label><input name='source' placeholder='np. doręczenie 11.09.2026, art. ...'></div><div class='full'><label>Wykonawca</label><select name='assigned_user_id'>{user_opts}</select></div><div class='full'><button class='btn primary'>Wylicz i dodaj termin</button></div></form></div>
          <div class='card quick-add-card'><h2>Zdarzenie na osi czasu</h2><form method='post' action='/quick/event' class='form-grid'><input type='hidden' name='return_to' value='/quick-add?done=zdarzenie'><div class='full'><label>Sprawa *</label><select name='case_id' required><option value=''>— wybierz —</option>{case_opts}</select></div><div><label>Data</label><input type='date' name='event_date' value='{date.today().isoformat()}'></div><div><label>Typ</label><select name='event_type'>{event_opts}</select></div><div class='full'><label>Tytuł *</label><input name='title' required></div><div class='full'><label>Opis</label><textarea name='description'></textarea></div><div class='full'><button class='btn primary'>Dodaj zdarzenie</button></div></form></div>
          <div class='card quick-add-card'><h2>Notatka</h2><form method='post' action='/quick/note' class='form-grid'><input type='hidden' name='return_to' value='/quick-add?done=notatka'><div class='full'><label>Sprawa *</label><select name='case_id' required><option value=''>— wybierz —</option>{case_opts}</select></div><div class='full'><label>Treść *</label><textarea name='note' required></textarea></div><div class='full'><button class='btn primary'>Dodaj notatkę</button></div></form></div>
          <div class='card quick-add-card'><h2>Dokument / pismo</h2><form method='post' enctype='multipart/form-data' action='/quick/document' class='form-grid'><input type='hidden' name='return_to' value='/quick-add?done=dokument'><div class='full'><label>Sprawa *</label><select name='case_id' required><option value=''>— wybierz —</option>{case_opts}</select></div><div><label>Data dokumentu</label><input type='date' name='doc_date'></div><div><label>Data wpływu</label><input type='date' name='received_date'></div><div><label>Data doręczenia</label><input type='date' name='delivered_date'></div><div><label>Rodzaj</label><select name='doc_type'>{doc_opts}</select></div><div><label>Status</label><select name='doc_status'>{doc_status_opts}</select></div><div><label>Nadawca</label><input name='sender'></div><div><label>Autor dokumentu</label><input name='document_author'></div><div><label>Tagi</label><input name='tags' placeholder='np. pilne, dowód'></div><div class='full'><label>Tytuł *</label><input name='title' required></div><div class='full'><label>Opis</label><input name='description'></div><div class='full'><label>Pismo / dokument główny</label><input type='file' name='file'></div><div class='full'><label>Załączniki do pisma</label><input type='file' name='attachments[]' multiple><div class='small muted'>Możesz zaznaczyć kilka plików. Zostaną zapisane pod pismem jako jego załączniki.</div></div><div class='full'><button class='btn primary'>Dodaj dokument</button></div></form></div>
        </div>"""
        self.send_html(layout('Dodaj czynność',body))

    def deadline_page(self,qs):
        self.redirect('/quick-add#deadline')


    def deadline_create(self,f):
        try: cid=int(f.get('case_id','0') or 0)
        except ValueError: cid=0
        title=(f.get('title') or '').strip()
        if not cid or not title: return self.redirect('/quick-add#deadline')
        try: days=int(f.get('days','0') or 0)
        except ValueError: days=-1
        try:
            due_date,rule_label=calculate_deadline(f.get('base_date',''),days,f.get('rule','calendar'))
        except ValueError as exc:
            return self.send_html(layout('Błąd terminu',f"<div class='card'><h1>Nie udało się wyliczyć terminu</h1><p>{esc(exc)}</p><a class='btn' href='/quick-add#deadline'>Wróć</a></div>"),400)
        try: assigned=int(f.get('assigned_user_id','') or 0) or None
        except ValueError: assigned=None
        a=self.current_author(f); source=(f.get('source') or '').strip(); priority=f.get('priority','high')
        with db() as con:
            if not con.execute('SELECT 1 FROM cases WHERE id=?',(cid,)).fetchone(): return self.send_error(404)
            if case_read_only(con,cid): return self.send_error(403,'Sprawa zakończona jest tylko do odczytu.')
            cur=con.execute("""INSERT INTO tasks(case_id,title,due_date,status,priority,assigned_user_id,depends_on,notes,task_type,
                              created_by,updated_by,deadline_base_date,deadline_days,deadline_rule,deadline_source,deadline_manual)
                              VALUES(?,?,?,'open',?,?,?,?,?,?,?,?,?,?,?,0)""",
                            (cid,title,due_date,priority,assigned,'',source,'Termin procesowy',a,a,
                             f.get('base_date',''),days,rule_label,source))
            sync_task_alert(con,cur.lastrowid,a)
            details=(f"Czynność: {_change_value(title)}\nData początkowa: {_change_value(f.get('base_date',''))}\n"
                     f"Reguła: {_change_value(str(days)+' '+rule_label)}\nWyliczony termin: {_change_value(due_date)}")
            if source: details += f"\nPodstawa / źródło: {_change_value(source)}"
            audit(con,cid,'task',cur.lastrowid,'Dodano termin procesowy',details,a)
        target=(f.get('return_to','') or '').strip()
        self.redirect(target if target.startswith('/') else '/today')

    def quick_event_add(self,f):
        try: cid=int(f.get('case_id','0') or 0)
        except ValueError: cid=0
        if not cid: return self.redirect('/quick-add')
        return self.event_add(cid,f)

    def quick_note_add(self,f):
        try: cid=int(f.get('case_id','0') or 0)
        except ValueError: cid=0
        if not cid: return self.redirect('/quick-add')
        return self.note_add(cid,f)

    def quick_document_add(self,f,files):
        try: cid=int(f.get('case_id','0') or 0)
        except ValueError: cid=0
        if not cid: return self.redirect('/quick-add')
        return self.document_add(cid,f,files)

    def case_next_action(self,cid,f):
        a=self.current_author(f)
        new={'next_step':(f.get('next_step') or '').strip(),'next_date':(f.get('next_date') or '').strip(),'waiting_for':(f.get('waiting_for') or '').strip()}
        with db() as con:
            old=con.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone()
            if not old: return self.send_error(404)
            if case_read_only(con,cid): return self.send_error(403,'Sprawa zakończona jest tylko do odczytu.')
            details=describe_changes(old,new,{'next_step':'Następny krok','next_date':'Data następnego ruchu','waiting_for':'Czekamy na'})
            con.execute("UPDATE cases SET next_step=?,next_date=?,waiting_for=?,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(new['next_step'],new['next_date'],new['waiting_for'],a,cid))
            if details: audit(con,cid,'case',cid,'Zmieniono następny ruch',details,a)
        self.redirect(f'/case/{cid}')

    def dashboard(self):
        today_obj = date.today()
        today = today_obj.isoformat()
        week_end = date.fromordinal(today_obj.toordinal()+7).isoformat()
        u=current_request_user(); uid=u['id'] if u else None
        backup_when,backup_path=ensure_daily_backup()
        notifications_html=self.dashboard_notifications()
        weekdays=['poniedziałek','wtorek','środa','czwartek','piątek','sobota','niedziela']
        months=['stycznia','lutego','marca','kwietnia','maja','czerwca','lipca','sierpnia','września','października','listopada','grudnia']
        today_label=f"{weekdays[today_obj.weekday()]}, {today_obj.day} {months[today_obj.month-1]} {today_obj.year}"
        display_name=(u['author_name'] or u['username'] or 'Użytkowniku').strip() if u else 'Użytkowniku'
        first_name=display_name.split()[0] if display_name else 'Użytkowniku'
        with db() as con:
            status_counts = {r['status']: r['cnt'] for r in con.execute("SELECT status,COUNT(*) cnt FROM cases GROUP BY status").fetchall()}; counts = {st: status_counts.get(st,0) for st in STATUS_LABELS}
            task_stats=con.execute("""SELECT
                SUM(CASE WHEN t.due_date=? THEN 1 ELSE 0 END) due_today,
                SUM(CASE WHEN t.due_date<>'' AND t.due_date<? THEN 1 ELSE 0 END) overdue,
                SUM(CASE WHEN t.due_date>? AND t.due_date<=? THEN 1 ELSE 0 END) next7,
                SUM(CASE WHEN t.priority='high' THEN 1 ELSE 0 END) high_priority
                FROM tasks t JOIN cases c ON c.id=t.case_id
                WHERE t.status='open' AND c.status<>'closed'""",(today,today,today,week_end)).fetchone()
            due_today=int(task_stats['due_today'] or 0); overdue_count=int(task_stats['overdue'] or 0); next7_count=int(task_stats['next7'] or 0); high_count=int(task_stats['high_priority'] or 0)
            dated = con.execute("""SELECT t.*,c.title case_title,c.signature,c.internal_signature FROM tasks t JOIN cases c ON c.id=t.case_id WHERE t.status='open' AND c.status<>'closed' AND t.due_date<>'' ORDER BY t.due_date,CASE t.priority WHEN 'high' THEN 0 ELSE 1 END,t.id LIMIT 15""").fetchall()
            undated = con.execute("""SELECT t.*,c.title case_title,c.signature,c.internal_signature FROM tasks t JOIN cases c ON c.id=t.case_id WHERE t.status='open' AND c.status<>'closed' AND t.due_date='' ORDER BY CASE t.priority WHEN 'high' THEN 0 ELSE 1 END,t.id LIMIT 10""").fetchall()
            upcoming = con.execute("SELECT * FROM cases WHERE status<>'closed' AND next_date<>'' AND next_date>=? ORDER BY next_date LIMIT 8", (today,)).fetchall()
            recent_events = con.execute("SELECT e.*, c.title case_title, c.signature FROM events e JOIN cases c ON c.id=e.case_id WHERE c.status<>'closed' ORDER BY e.event_date DESC, e.id DESC LIMIT 8").fetchall()
            pinned = con.execute("""SELECT c.* FROM user_case_pins p JOIN cases c ON c.id=p.case_id WHERE p.user_id=? AND c.status<>'closed' ORDER BY c.next_date='',c.next_date,c.title LIMIT 12""",(uid,)).fetchall() if uid else []
            recent_cases = con.execute("""SELECT c.*,r.opened_at FROM user_case_recent r JOIN cases c ON c.id=r.case_id WHERE r.user_id=? ORDER BY r.opened_at DESC LIMIT 8""",(uid,)).fetchall() if uid else []
            sig_ids=[r['id'] for r in pinned]+[r['id'] for r in recent_cases]+[r['case_id'] for r in dated]+[r['case_id'] for r in undated]+[r['id'] for r in upcoming]
            sig_map=load_external_signature_map(con,sig_ids)
        def case_mini(r, extra=''):
            sig=primary_signature_fast(r['id'],r['signature'],sig_map)
            return f"<div class='dash-case'><a href='/case/{r['id']}'>{esc(sig if sig!='Bez sygnatury' else r['title'])}</a><div class='small muted'>{esc(r['title'])}</div>{extra}</div>"
        pinned_html=''.join(case_mini(r, f"<div class='small dash-case-next'>{fmt_date(r['next_date'])} · {esc(r['next_step'])}</div>" if r['next_date'] or r['next_step'] else '') for r in pinned) or '<div class="empty">Brak przypiętych spraw. Otwórz sprawę i kliknij ☆ Przypnij.</div>'
        recent_cases_html=''.join(case_mini(r, f"<div class='small muted'>otwierano: {esc((r['opened_at'] or '')[:16])}</div>") for r in recent_cases) or '<div class="empty">Brak ostatnio otwieranych spraw.</div>'
        dated_parts=[]
        for r in dated:
            dep = f"<div class='small muted'>czekamy na: {esc(r['depends_on'])}</div>" if r['depends_on'] else ''
            cls = 'priority-high' if r['priority']=='high' else ''
            prio = 'Wysoki' if r['priority']=='high' else 'Normalny'
            label = primary_signature_fast(r['case_id'], r['signature'], sig_map)
            if r['due_date'] < today:
                due_chip="<span class='due-chip danger'>po terminie</span>"
            elif r['due_date'] == today:
                due_chip="<span class='due-chip today'>dzisiaj</span>"
            elif r['due_date'] <= week_end:
                due_chip="<span class='due-chip soon'>7 dni</span>"
            else:
                due_chip=''
            dated_parts.append(f"<tr><td class='nowrap'><b>{fmt_date(r['due_date'])}</b>{due_chip}</td><td><a class='case-link' href='/case/{r['case_id']}'>{esc(label)}</a><div class='small muted'>{esc(internal_signature_text(r['internal_signature']))}</div></td><td><b class='{cls}'>{esc(r['title'])}</b>{dep}</td><td>{prio}</td></tr>")
        dated_rows=''.join(dated_parts) or '<tr><td colspan=4>Brak czynności z przypisaną datą.</td></tr>'
        undated_parts=[]
        for r in undated:
            dep = f"<div class='small muted'>czekamy na: {esc(r['depends_on'])}</div>" if r['depends_on'] else ''
            prio = 'Wysoki' if r['priority']=='high' else 'Normalny'
            label = primary_signature_fast(r['case_id'], r['signature'], sig_map)
            undated_parts.append(f"<tr><td><a class='case-link' href='/case/{r['case_id']}'>{esc(label)}</a><div class='small muted'>{esc(internal_signature_text(r['internal_signature']))}</div></td><td><b>{esc(r['title'])}</b>{dep}</td><td>{prio}</td></tr>")
        undated_rows=''.join(undated_parts) or '<tr><td colspan=3>Brak czynności bez daty.</td></tr>'
        upcoming_parts=[]
        for r in upcoming:
            shown_sig = primary_signature_fast(r['id'], r['signature'], sig_map)
            upcoming_parts.append(f"<tr><td class='nowrap'>{fmt_date(r['next_date'])}</td><td><a class='case-link' href='/case/{r['id']}'>{esc(shown_sig)}</a><div class='small muted'>{esc(internal_signature_text(r['internal_signature']))}</div></td><td><div class='clamp-2' title='{esc(r['next_step'])}'>{esc(r['next_step'])}</div></td></tr>")
        upcoming_rows=''.join(upcoming_parts) or '<tr><td colspan=3>Brak terminów.</td></tr>'
        recent_parts=[]
        for r in recent_events:
            author = f"<div class='author'>autor: {esc(r['created_by'])}</div>" if r['created_by'] else ''
            recent_parts.append(f"<div class='event'><div class='event-date'>{fmt_date(r['event_date'])} · {esc(r['event_type'])}</div><div class='event-title'><a class='case-link' href='/case/{r['case_id']}'>{esc(r['title'])}</a></div><div class='event-desc'>{esc(r['case_title'])}</div>{author}</div>")
        recent_html=''.join(recent_parts) or '<div class="empty">Brak zdarzeń.</div>'
        body=f"""
        <section class="dashboard-hero">
          <div class="dashboard-hero-copy">
            <div class="dashboard-eyebrow">{esc(today_label)}</div>
            <h1>Dzień dobry, {esc(first_name)}</h1>
            <div class="dashboard-lead">Tu masz najważniejsze sprawy, terminy i czynności wymagające uwagi.</div>
            <div class="status-strip">
              <span><b>{counts['active']}</b> w toku</span><span><b>{counts['waiting']}</b> oczekuje</span><span><b>{counts['todo']}</b> do wykonania</span><span><b>{counts['suspended']}</b> zawieszonych</span>
            </div>
          </div>
          <div class="dashboard-hero-tools">
            <div class="live-clock-card" aria-label="Aktualny czas"><div class="live-clock-label">AKTUALNY CZAS</div><div id="liveClock" class="live-clock" data-live-clock>--:--:--</div><div id="liveClockDate" class="live-clock-date">{esc(today_label)}</div></div>
            <form class="searchbar dashboard-search" action="/search"><input name="q" data-global-search placeholder="Szukaj sprawy, klienta, sygnatury lub dokumentu…"><button class="btn primary">Szukaj</button></form>
            <div class="quick-actions"><a class="btn primary" href="/quick-add">+ Dodaj czynność</a><a class="btn" href="/today">Dzisiaj</a><a class="btn" href="/case/new">+ Nowa sprawa</a><a class="btn" href="/tasks">Zadania</a><a class="btn" href="/documents">Dokumenty</a><a class="btn" href="/draft/new">+ Projekt pisma</a></div>
          </div>
        </section>
        <div class="grid dashboard-metrics">
          <div class="card span3 metric-card metric-today"><div class="metric-kicker">DZISIAJ</div><div class="metric">{due_today}</div><div class="metric-label">czynności z terminem na dziś</div></div>
          <div class="card span3 metric-card metric-week"><div class="metric-kicker">7 DNI</div><div class="metric">{next7_count}</div><div class="metric-label">czynności w najbliższym tygodniu</div></div>
          <div class="card span3 metric-card {'metric-danger' if overdue_count else 'metric-ok'}"><div class="metric-kicker">PO TERMINIE</div><div class="metric">{overdue_count}</div><div class="metric-label">otwartych zaległych czynności</div></div>
          <div class="card span3 metric-card metric-priority"><div class="metric-kicker">PRIORYTET</div><div class="metric">{high_count}</div><div class="metric-label">zadań oznaczonych jako wysokie</div></div>
        </div>
        <div class="card attention-card"><div class="section-head"><div><div class="section-kicker">CENTRUM UWAGI</div><h2>Wymaga uwagi</h2><div class="small muted">Terminy, zaległości, brak aktywności i dokumenty do podpisu.</div></div><a class="btn small" href="/tasks">Przejdź do zadań</a></div><div class="notification-list">{notifications_html}</div></div>
        <div class="grid dashboard-body-grid">
          <div class="card span6"><div class='section-head'><div><div class='section-kicker'>NA WIERZCHU</div><h2>⭐ Przypięte sprawy</h2></div><a class='btn small' href='/cases'>Wszystkie</a></div><div class='dash-cases'>{pinned_html}</div></div>
          <div class="card span6"><div class='section-head'><div><div class='section-kicker'>SZYBKI POWRÓT</div><h2>Ostatnio otwierane</h2></div><a class='btn small' href='/cases'>Lista spraw</a></div><div class='dash-cases'>{recent_cases_html}</div></div>
          <div class="card span12"><div class="section-head"><div><div class='section-kicker'>TERMINARZ</div><h2>Najbliższe czynności</h2></div><a class="btn small" href="/tasks">Wszystkie zadania</a></div><div class='table-scroll'><table><tr><th>Data</th><th>Sprawa</th><th>Czynność</th><th>Priorytet</th></tr>{dated_rows}</table></div></div>
          <div class="card span7"><div class='section-kicker'>DO UŁOŻENIA</div><h2>Do zaplanowania / bez daty</h2><div class='table-scroll'><table><tr><th>Sprawa</th><th>Czynność</th><th>Priorytet</th></tr>{undated_rows}</table></div></div>
          <div class="card span5"><div class='section-kicker'>KALENDARZ SPRAW</div><h2>Najbliższe terminy spraw</h2><div class='table-scroll'><table><tr><th>Data</th><th>Sprawa</th><th>Następny krok</th></tr>{upcoming_rows}</table></div></div>
          <div class="card span12"><div class='section-kicker'>OSTATNIO</div><h2>Co ostatnio wydarzyło się w sprawach</h2><div class="timeline">{recent_html}</div></div>
          <div class="card span12 backup-card"><div class='section-head'><div><div class='section-kicker'>BEZPIECZEŃSTWO DANYCH</div><h2>Kopia bezpieczeństwa</h2><div class='small muted'>Automatyczna kopia SQLite raz dziennie; przechowywanych jest 30 ostatnich kopii.</div></div><a class='btn small' href='/backups'>Kopie</a></div><div class='backup-ok'>✓ Ostatnia kopia: {esc(backup_when)}</div></div>
        </div>"""
        self.send_html(layout("Pulpit", body, "dashboard"))

    def case_next_action_complete(self,cid,f):
        if not self.ensure_case_editable(cid): return
        a=self.current_author(f)
        with db() as con:
            c=con.execute("SELECT next_step,next_date,waiting_for FROM cases WHERE id=?",(cid,)).fetchone()
            if not c: return self.send_error(404)
            title=(c['next_step'] or '').strip()
            if title:
                desc=[]
                if c['next_date']: desc.append('termin: '+fmt_date(c['next_date']))
                if c['waiting_for']: desc.append('czekaliśmy na: '+c['waiting_for'])
                audit(con,cid,'case',cid,'Wykonano następny ruch',title+((' · '+' · '.join(desc)) if desc else ''),a)
                con.execute("UPDATE cases SET next_step='',next_date='',waiting_for='',updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(a,cid))
        self.redirect(f'/case/{cid}')

    def process_event_add(self,cid,f):
        if not self.ensure_case_editable(cid): return
        title=(f.get('title') or '').strip(); a=self.current_author(f)
        if not title: return self.redirect(f'/case/{cid}/history#process')
        status=f.get('status','done')
        if status not in {'done','planned','waiting'}: status='done'
        try: doc_id=int(f.get('document_id') or 0) or None
        except ValueError: doc_id=None
        with db() as con:
            cur=con.execute("""INSERT INTO process_events(case_id,event_date,event_type,title,description,court,signature,status,document_id,next_date,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",(cid,f.get('event_date',''),(f.get('event_type') or 'Inna czynność').strip(),title,(f.get('description') or '').strip(),(f.get('court') or '').strip(),(f.get('signature') or '').strip(),status,doc_id,f.get('next_date',''),a,a))
            details=f"{fmt_date(f.get('event_date',''))} · {(f.get('event_type') or 'Inna czynność').strip()} · {title}"
            audit(con,cid,'process_event',cur.lastrowid,'Dodano zdarzenie procesowe',details,a)
        self.redirect(f'/case/{cid}/history#process')

    def process_event_toggle(self,pid,f):
        a=self.current_author(f)
        with db() as con:
            r=con.execute("SELECT * FROM process_events WHERE id=?",(pid,)).fetchone()
            if not r: return self.send_error(404)
            cid=r['case_id']
            if case_read_only(con,cid): return self.redirect(f'/case/{cid}/history#process')
            new='planned' if r['status']=='done' else 'done'
            con.execute("UPDATE process_events SET status=?,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(new,a,pid))
            audit(con,cid,'process_event',pid,'Zdarzenie procesowe oznaczono jako wykonane' if new=='done' else 'Cofnięto wykonanie zdarzenia procesowego',r['title'],a)
        self.redirect(f'/case/{cid}/history#process')

    def process_event_delete(self,pid,f):
        a=self.current_author(f)
        with db() as con:
            r=con.execute("SELECT case_id FROM process_events WHERE id=?",(pid,)).fetchone()
            cid=r['case_id'] if r else 0
            if r and not case_read_only(con,cid): move_to_trash(con,'process_event',pid,a)
        self.redirect(f'/case/{cid}/history#process' if cid else '/cases')

    def process_event_edit(self,pid):
        with db() as con:
            r=con.execute("SELECT * FROM process_events WHERE id=?",(pid,)).fetchone()
            docs=con.execute("SELECT id,title,doc_date FROM documents WHERE case_id=? ORDER BY doc_date DESC,id DESC",(r['case_id'],)).fetchall() if r else []
        if not r: return self.send_error(404)
        status_opts=''.join(f"<option value='{x}' {'selected' if r['status']==x else ''}>{lbl}</option>" for x,lbl in [('done','Wykonane'),('planned','Planowane'),('waiting','Oczekuje')])
        doc_opts='<option value="">— bez dokumentu —</option>'+''.join(f"<option value='{d['id']}' {'selected' if r['document_id']==d['id'] else ''}>{esc(d['title'])} · {fmt_date(d['doc_date'])}</option>" for d in docs)
        types=['Pozew / wniosek','Pismo strony','Zarządzenie','Postanowienie','Wyrok','Rozprawa / posiedzenie','Przesłuchanie','Opinia biegłego','Mediacja','Doręczenie','Środek zaskarżenia','Inna czynność']
        type_opts=''.join(f"<option {'selected' if r['event_type']==x else ''}>{x}</option>" for x in types)
        body=f"""<div class='topbar'><div><h1>Edytuj zdarzenie procesowe</h1><div class='sub'>Zmieniaj wyłącznie opis przebiegu postępowania.</div></div><a class='btn' href='/case/{r['case_id']}/history#process'>Wróć</a></div><div class='card'><form method='post' action='/process-event/{pid}/update' class='form-grid'><div><label>Data</label><input type='date' name='event_date' value='{esc(r['event_date'])}'></div><div><label>Rodzaj</label><select name='event_type'>{type_opts}</select></div><div class='full'><label>Co wydarzyło się procesowo? *</label><input name='title' value='{esc(r['title'])}' required></div><div class='full'><label>Krótki opis</label><textarea name='description'>{esc(r['description'])}</textarea></div><div><label>Sąd / organ</label><input name='court' value='{esc(r['court'])}'></div><div><label>Sygnatura</label><input name='signature' value='{esc(r['signature'])}'></div><div><label>Status</label><select name='status'>{status_opts}</select></div><div><label>Następny termin</label><input type='date' name='next_date' value='{esc(r['next_date'])}'></div><div class='full'><label>Powiązany dokument</label><select name='document_id'>{doc_opts}</select></div><div class='full'><button class='btn primary'>Zapisz</button></div></form></div>"""
        self.send_html(layout('Zdarzenie procesowe',body,'cases'))

    def process_event_update(self,pid,f):
        a=self.current_author(f); title=(f.get('title') or '').strip()
        if not title: return self.process_event_edit(pid)
        status=f.get('status','done'); status=status if status in {'done','planned','waiting'} else 'done'
        try: doc_id=int(f.get('document_id') or 0) or None
        except ValueError: doc_id=None
        with db() as con:
            old=con.execute("SELECT * FROM process_events WHERE id=?",(pid,)).fetchone()
            if not old: return self.send_error(404)
            cid=old['case_id']
            if case_read_only(con,cid): return self.redirect(f'/case/{cid}/history#process')
            new={'event_date':f.get('event_date',''),'event_type':(f.get('event_type') or 'Inna czynność').strip(),'title':title,'description':(f.get('description') or '').strip(),'court':(f.get('court') or '').strip(),'signature':(f.get('signature') or '').strip(),'status':status,'next_date':f.get('next_date','')}
            details=describe_changes(old,new,{'event_date':'Data','event_type':'Rodzaj','title':'Zdarzenie','description':'Opis','court':'Sąd / organ','signature':'Sygnatura','status':'Status','next_date':'Następny termin'},compact_fields={'description'})
            con.execute("UPDATE process_events SET event_date=?,event_type=?,title=?,description=?,court=?,signature=?,status=?,document_id=?,next_date=?,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(new['event_date'],new['event_type'],title,new['description'],new['court'],new['signature'],status,doc_id,new['next_date'],a,pid))
            if details: audit(con,cid,'process_event',pid,'Zmieniono zdarzenie procesowe',details,a)
        self.redirect(f'/case/{cid}/history#process')

    def case_history_page(self,cid):
        with db() as con:
            c=con.execute("SELECT * FROM cases WHERE id=?",(cid,)).fetchone()
            if not c: return self.send_error(404)
            process=con.execute("SELECT p.*,d.title document_title FROM process_events p LEFT JOIN documents d ON d.id=p.document_id WHERE p.case_id=? ORDER BY CASE WHEN p.event_date='' THEN 1 ELSE 0 END,p.event_date DESC,p.id DESC",(cid,)).fetchall()
            activity=con.execute("SELECT * FROM audit_log WHERE case_id=? ORDER BY id DESC LIMIT 200",(cid,)).fetchall()
            docs=con.execute("SELECT id,title,doc_date FROM documents WHERE case_id=? ORDER BY doc_date DESC,id DESC",(cid,)).fetchall()
            readonly=case_read_only(con,cid)
        sig=primary_signature_text(cid,c['signature'],c['internal_signature'])
        def status_label(st): return {'done':'Wykonane','planned':'Planowane','waiting':'Oczekuje'}.get(st,st)
        process_parts=[]
        for r in process:
            doc=f"<a class='linked-chip' href='/document/{r['document_id']}/open'>▤ {esc(r['document_title'] or 'Dokument')}</a>" if r['document_id'] else ''
            meta=' · '.join(x for x in [esc(r['event_type']),esc(r['court']),esc(r['signature'])] if x)
            next_html=f"<div class='process-next'>Następny termin: <b>{fmt_date(r['next_date'])}</b></div>" if r['next_date'] else ''
            desc_html=f"<p>{esc(r['description'])}</p>" if r['description'] else ''
            if readonly:
                actions=''
            else:
                toggle_label='↩ Cofnij wykonanie' if r['status']=='done' else '✓ Oznacz jako wykonane'
                actions=f"""<div class='process-actions'><form method='post' action='/process-event/{r['id']}/toggle'><button class='btn small'>{toggle_label}</button></form><a class='btn small' href='/process-event/{r['id']}/edit'>Edytuj</a><form method='post' action='/process-event/{r['id']}/delete' onsubmit="return confirm('Przenieść zdarzenie procesowe do Kosza?');"><button class='btn small danger'>Do kosza</button></form></div>"""
            process_parts.append(f"""<article class='process-entry status-{esc(r['status'])}'><div class='process-date'>{fmt_date(r['event_date'])}</div><div class='process-dot'></div><div class='process-content'><div class='process-entry-head'><h3>{esc(r['title'])}</h3><span class='state-chip {esc(r['status'])}'>{status_label(r['status'])}</span></div><div class='small muted'>{meta or 'Czynność procesowa'}</div>{desc_html}{doc}{next_html}<div class='author'>{esc(r['created_by'])} · {esc(str(r['created_at'])[:16])}</div>{actions}</div></article>""")
        process_html=''.join(process_parts) or "<div class='empty'><b>Brak wpisów w historii procesu.</b><div class='small'>Dodaj pierwsze zdarzenie, np. wniesienie pozwu, rozprawę albo postanowienie.</div></div>"
        # Historia sprawy pokazuje zdarzenia użytkowe, a Historia zmian — pełny audyt.
        work_prefixes=('Dodano','Utworzono','Zadanie','Element checklisty','Wykonano','Złożono','Wysłano','Doręczono','Przywrócono','Zarchiwizowano','Zastosowano','Przypisano','Cofnięto wykonanie')
        activity_work=[r for r in activity if any(str(r['action'] or '').startswith(prefix) for prefix in work_prefixes)]
        def feed(rows,empty):
            parts=[]
            for r in rows:
                target=audit_target_html(r)
                parts.append(f"<div class='history-feed-item'><div class='history-feed-dot'></div><div><div class='history-feed-title'>{esc(r['action'])}</div><div class='small muted'>{audit_description_html(r['description'])}</div>{target}<div class='author'>{esc(str(r['created_at'])[:16])} · {esc(r['author']) or '—'}</div></div></div>")
            return ''.join(parts) or f'<div class="empty">{esc(empty)}</div>'
        activity_html=feed(activity_work,'Brak czynności w historii sprawy.')
        changes_html=feed(activity,'Brak zapisanych zmian danych.')
        doc_opts='<option value="">— bez dokumentu —</option>'+''.join(f"<option value='{d['id']}'>{esc(d['title'])} · {fmt_date(d['doc_date'])}</option>" for d in docs)
        types=['Pozew / wniosek','Pismo strony','Zarządzenie','Postanowienie','Wyrok','Rozprawa / posiedzenie','Przesłuchanie','Opinia biegłego','Mediacja','Doręczenie','Środek zaskarżenia','Inna czynność']
        type_opts=''.join(f'<option>{esc(x)}</option>' for x in types)
        add_form='' if readonly else f"""<details class='card add-panel' id='new-process-event'><summary><span class='add-panel-plus'>＋</span><span><b>Dodaj zdarzenie procesowe</b><small>Wpisz wyłącznie to, co wydarzyło się w postępowaniu.</small></span></summary><div class='add-panel-body'><form method='post' action='/case/{cid}/process-event' class='form-grid'><div><label>Data</label><input type='date' name='event_date' value='{date.today().isoformat()}'></div><div><label>Rodzaj</label><select name='event_type'>{type_opts}</select></div><div class='full'><label>Co wydarzyło się procesowo? *</label><input name='title' required placeholder='np. Sąd wydał postanowienie o dopuszczeniu dowodu z opinii biegłego'></div><div><label>Status</label><select name='status'><option value='done'>Wykonane / wydarzyło się</option><option value='planned'>Planowane</option><option value='waiting'>Oczekuje</option></select></div><div><label>Następny termin</label><input type='date' name='next_date'></div><details class='advanced-fields full'><summary>Więcej informacji</summary><div class='form-grid'><div><label>Sąd / organ</label><input name='court' value='{esc(c['court'])}'></div><div><label>Sygnatura</label><input name='signature' value='{esc(c['signature'])}'></div><div class='full'><label>Krótki opis</label><textarea name='description'></textarea></div><div class='full'><label>Powiązany dokument</label><select name='document_id'>{doc_opts}</select></div></div></details><div class='full'><button class='btn primary'>Dodaj do historii procesu</button></div></form></div></details>"""
        body=f"""<div class='topbar'><div><div class='eyebrow'>HISTORIA SPRAWY</div><h1>{esc(sig if sig!='Bez sygnatury' else c['title'])}</h1><div class='sub'><b>{esc(c['subject']) or esc(c['title'])}</b> · {esc(c['client']) or 'bez wskazanego klienta'}</div></div><div><button class='btn primary' type='button' data-open-details='new-process-event'>+ Zdarzenie procesowe</button> <a class='btn' href='/case/{cid}'>Wróć do sprawy</a></div></div><nav class='history-tabs'><a href='#process'>Historia procesu</a><a href='#activity'>Historia sprawy</a><a href='#changes'>Historia zmian</a></nav><section id='process' class='history-section'><div class='section-head'><div><h2>Historia procesu</h2><div class='small muted'>Tylko to, co wydarzyło się procesowo przed sądem lub organem.</div></div></div><div class='process-timeline'>{process_html}</div></section>{add_form}<section id='activity' class='history-section'><div class='section-head'><div><h2>Historia sprawy</h2><div class='small muted'>Praca kancelarii: dokumenty, zadania, notatki, pisma i wykonane czynności.</div></div></div><div class='history-feed'>{activity_html}</div></section><section id='changes' class='history-section'><div class='section-head'><div><h2>Historia zmian danych</h2><div class='small muted'>Pełny dziennik: kto, kiedy i co zmienił.</div></div><a class='btn small' href='/history?case_id={cid}'>Otwórz pełny dziennik</a></div><div class='history-feed'>{changes_html}</div></section>"""
        self.send_html(layout('Historia sprawy',body,'cases'))

    def cases(self, qs, closed_only=False):
        q=(qs.get('q') or [''])[0].strip()
        status=(qs.get('status') or [''])[0]
        tag=(qs.get('tag') or [''])[0].strip()
        mine=(qs.get('mine') or [''])[0]=='1'
        focus=(qs.get('focus') or [''])[0].strip().lower()
        if focus not in {'','waiting','no-next','7d'}: focus=''
        view=(qs.get('view') or ['compact'])[0].strip().lower()
        if view not in ('compact','detailed'): view='compact'
        u=current_request_user(); uid=u['id'] if u else 0
        base_path='/cases/closed' if closed_only else '/cases'
        active_key='closed_cases' if closed_only else ('my_cases' if mine else 'cases')
        sql="""SELECT DISTINCT c.*,u.author_name lead_name,u.function lead_function,
               CASE WHEN p.user_id IS NULL THEN 0 ELSE 1 END pinned
               FROM cases c LEFT JOIN users u ON u.id=c.lead_user_id
               LEFT JOIN user_case_pins p ON p.case_id=c.id AND p.user_id=? WHERE 1=1"""
        params=[uid]
        if closed_only:
            sql += " AND c.status='closed'"; status='closed'
        else:
            sql += " AND c.status<>'closed'"
        if mine:
            sql += " AND c.lead_user_id=?"; params.append(uid)
        if q:
            like=f"%{q}%"
            sql += " AND (c.signature LIKE ? OR c.internal_signature LIKE ? OR c.client LIKE ? OR c.title LIKE ? OR c.subject LIKE ? OR c.court LIKE ? OR c.category LIKE ? OR c.next_step LIKE ? OR c.waiting_for LIKE ? OR u.author_name LIKE ? OR EXISTS (SELECT 1 FROM case_tags ct JOIN tags tg ON tg.id=ct.tag_id WHERE ct.case_id=c.id AND tg.name LIKE ?) OR EXISTS (SELECT 1 FROM case_external_signatures es WHERE es.case_id=c.id AND (es.label LIKE ? OR es.signature LIKE ?)))"
            params += [like]*13
        if status and not closed_only:
            sql += " AND c.status=?"; params.append(status)
        if tag:
            sql += " AND EXISTS (SELECT 1 FROM case_tags ct JOIN tags tg ON tg.id=ct.tag_id WHERE ct.case_id=c.id AND tg.name=? COLLATE NOCASE)"; params.append(tag)
        if focus=='waiting': sql += " AND c.waiting_for<>''"
        elif focus=='no-next': sql += " AND (c.next_step='' OR c.next_date='')"
        elif focus=='7d':
            today=date.today().isoformat(); week_end=(date.today()+timedelta(days=7)).isoformat()
            sql += " AND c.next_date<>'' AND c.next_date BETWEEN ? AND ?"; params.extend([today,week_end])
        sql += " ORDER BY pinned DESC, CASE c.status WHEN 'todo' THEN 0 WHEN 'active' THEN 1 WHEN 'waiting' THEN 2 WHEN 'suspended' THEN 3 ELSE 4 END, c.next_date='' ASC, c.next_date, c.title"
        with db() as con:
            rows=con.execute(sql,params).fetchall()
            sig_map=load_external_signature_map(con,[r['id'] for r in rows if not (r['signature'] or '').strip()])
            tag_map={}
            row_ids={r['id'] for r in rows}
            for r in con.execute("SELECT ct.case_id,t.name FROM case_tags ct JOIN tags t ON t.id=ct.tag_id ORDER BY t.name"):
                if r['case_id'] in row_ids:
                    tag_map.setdefault(r['case_id'],[]).append(r['name'])
        def tags_for(cid,limit=3):
            tags=tag_map.get(cid,[]); visible=tags[:limit]; rest=tags[limit:]
            extra='&mine=1' if mine else ''
            html_tags=''.join(f"<a class='tag' href='{base_path}?tag={quote(t)}&view={view}{extra}'>{esc(t)}</a>" for t in visible)
            if rest:
                rest_html=''.join(f"<a class='tag' href='{base_path}?tag={quote(t)}&view={view}{extra}'>{esc(t)}</a>" for t in rest)
                html_tags += f"<details class='tag-more'><summary>+{len(rest)}</summary><div class='tag-more-panel'>{rest_html}</div></details>"
            return html_tags
        common=[]
        if q: common.append('q='+quote(q))
        if status and not closed_only: common.append('status='+quote(status))
        if tag: common.append('tag='+quote(tag))
        if mine: common.append('mine=1')
        if focus: common.append('focus='+quote(focus))
        def view_url(which): return base_path+'?'+'&'.join(common+['view='+which])
        clear_url=base_path+'?view='+view+('&mine=1' if mine else '')
        tag_clear=clear_url
        if view=='compact':
            cards=[]
            for r in rows:
                primary=primary_signature_fast(r['id'],r['signature'],sig_map)
                internal=f"<span class='case-internal'>{esc(internal_signature_text(r['internal_signature']))}</span>"
                client=f"<div class='case-client'>Klient: <b>{esc(r['client'])}</b></div>" if r['client'] else ''
                lead=''
                if r['lead_name']:
                    ld=r['lead_name']+((' — '+r['lead_function']) if r['lead_function'] else '')
                    lead=f"<span class='lead-chip'>Prowadzący: {esc(ld)}</span>"
                waiting=f"<span class='waiting-chip'>Czekamy na: {esc(r['waiting_for'])}</span>" if r['waiting_for'] else ''
                nxt=esc(r['next_step']) or '<span class="muted">Brak wskazanej następnej czynności</span>'
                dt=fmt_date(r['next_date']); dt='Bez terminu' if dt=='—' else dt
                pin='★' if r['pinned'] else '☆'; pincls='on' if r['pinned'] else ''
                cards.append(f"""<div class='case-compact-card'>
                  <div class='case-card-top'><div><a class='case-signature' href='/case/{r['id']}'>{esc(primary)}</a>{internal}</div><div class='case-control-bar'><form method='post' action='/case/{r['id']}/pin'><button class='pin-btn {pincls}' title='Przypnij / odepnij'>{pin}</button></form>{badge(r['status'])}</div></div>
                  <a class='case-card-title' href='/case/{r['id']}'>{esc(r['title'])}</a>{client}<div>{lead} {waiting}</div>
                  <div class='case-action'><span class='case-date'>{dt}</span><span class='case-arrow'>→</span><span class='case-next clamp-2' title='{esc(r['next_step'])}'>{nxt}</span></div>
                  <div class='case-footer'><div class='case-tags'>{tags_for(r['id']) or '<span class="small muted">bez tagów</span>'}</div><a class='btn small open-arrow' href='/case/{r['id']}' title='Otwórz sprawę'>›</a></div>
                </div>""")
            list_html='<div class="case-list">'+''.join(cards)+'</div>' if cards else '<div class="empty">Brak spraw.</div>'
        else:
            trs=[]
            for r in rows:
                primary=primary_signature_fast(r['id'],r['signature'],sig_map)
                meta=[]
                if r['client']: meta.append('Klient: '+esc(r['client']))
                if r['lead_name']: meta.append('Prowadzący: '+esc(r['lead_name']))
                if r['waiting_for']: meta.append('Czekamy na: '+esc(r['waiting_for']))
                if r['subject']: meta.append(esc(r['subject']))
                pin='★' if r['pinned'] else '☆'; pincls='on' if r['pinned'] else ''
                trs.append(f"<tr><td><form method='post' action='/case/{r['id']}/pin' style='display:inline'><button class='pin-btn {pincls}'>{pin}</button></form><a class='case-link' href='/case/{r['id']}'>{esc(primary)}</a><div class='small muted'>{esc(internal_signature_text(r['internal_signature']))}</div></td><td class='case-title-cell'><a class='case-link' href='/case/{r['id']}'>{esc(r['title'])}</a><div class='small muted'>{' · '.join(meta)}</div><div class='case-tags' style='margin-top:5px'>{tags_for(r['id'])}</div></td><td>{badge(r['status'])}</td><td>{fmt_date(r['next_date'])}</td><td class='next-cell'><div class='clamp-2'>{esc(r['next_step']) or '—'}</div></td><td><a class='btn small open-arrow' href='/case/{r['id']}'>›</a></td></tr>")
            list_html=f"<div class='card' style='padding:8px 14px'><table class='case-table'><tr><th>Sygnatura</th><th>Sprawa</th><th>Status</th><th>Termin</th><th>Następny krok</th><th></th></tr>{''.join(trs) or '<tr><td colspan=6>Brak spraw.</td></tr>'}</table></div>"
        active_statuses={k:v for k,v in STATUS_LABELS.items() if k!='closed'}
        opts=''.join(f"<option value='{k}' {'selected' if status==k else ''}>{v}</option>" for k,v in active_statuses.items())
        tag_note=f"<div class='notice'>Filtr tagu: <b>{esc(tag)}</b> · <a href='{tag_clear}'>pokaż wszystkie sprawy</a></div>" if tag else ''
        if closed_only: page_title='Sprawy zakończone'; page_sub=f'{len(rows)} zakończonych spraw · archiwum'
        elif mine: page_title='Moje sprawy'; page_sub=f'{len(rows)} spraw prowadzonych przez Ciebie'
        else: page_title='Sprawy'; page_sub=f"{len(rows)} aktywnych spraw · widok {'kompaktowy' if view=='compact' else 'szczegółowy'}"
        status_filter='' if closed_only else f"<div><label>Status</label><select name='status'><option value=''>Wszystkie aktywne</option>{opts}</select></div>"
        mine_hidden="<input type='hidden' name='mine' value='1'>" if mine else ''
        extra_action=("<a class='btn' href='/cases'>← Aktywne sprawy</a>" if closed_only else ("<a class='btn' href='/cases'>Wszystkie sprawy</a>" if mine else "<a class='btn' href='/cases?mine=1'>Moje sprawy</a> <a class='btn' href='/cases/closed'>Sprawy zakończone</a>"))
        new_button='' if closed_only else '<a class="btn primary" href="/case/new">+ Nowa sprawa</a>'
        save_view=self._save_view_form(self.path)
        focus_bar=''
        if not closed_only:
            suffix='&mine=1' if mine else ''
            def focus_link(key,label):
                active='primary' if focus==key else ''
                return f"<a class='btn small {active}' href='/cases?view={view}{suffix}{('&focus='+key) if key else ''}'>{label}</a>"
            focus_bar="<div class='quick-filter-bar'><span class='small muted'>Szybkie widoki:</span> "+''.join([focus_link('','Wszystkie'),focus_link('7d','Następne 7 dni'),focus_link('waiting','Czekamy na'),focus_link('no-next','Brak następnego ruchu')])+"</div>"
        body=f"""<div class='topbar'><div><h1>{page_title}</h1><div class='sub'>{page_sub}</div></div><div>{extra_action} {new_button}</div></div>{tag_note}{focus_bar}
        <details class='card filter-panel'><summary>Filtry spraw</summary><form class='form-grid' method='get' style='margin-top:12px'>{mine_hidden}<input type='hidden' name='view' value='{view}'>{f"<input type='hidden' name='focus' value='{esc(focus)}'>" if focus else ''}<div><label>Szukaj</label><input name='q' value='{esc(q)}' placeholder='Sygnatura, klient, prowadzący, oczekiwanie, tag…'></div>{status_filter}<div class='full'><button class='btn'>Filtruj</button> <a class='btn' href='{clear_url}'>Wyczyść</a> <a class='btn' href='/tags'>Tagi</a></div></form></details><br>
        <div class='cases-toolbar'><div class='small muted'>⭐ oznacza sprawę przypiętą do Twojego konta.</div><div class='view-switch'><a class='view-tab {'active' if view=='compact' else ''}' href='{view_url('compact')}'>Kompaktowy</a><a class='view-tab {'active' if view=='detailed' else ''}' href='{view_url('detailed')}'>Szczegółowy</a></div></div>{save_view}{list_html}"""
        self.send_html(layout(page_title,body,active_key))

    def case_new(self):
        opts=''.join(f"<option value='{k}'>{v}</option>" for k,v in STATUS_LABELS.items())
        with db() as con:
            users=con.execute("SELECT id,author_name,function FROM users WHERE is_active=1 ORDER BY author_name").fetchall()
            entities=con.execute("SELECT id,display_name,pesel,nip,krs FROM entities ORDER BY display_name COLLATE NOCASE").fetchall()
        lead_opts='<option value="">— nie przypisano —</option>'+''.join(f"<option value='{u['id']}'>{esc(user_display_name(u))}</option>" for u in users)
        entity_opts='<option value="">— wybierz z kartoteki —</option>'+''.join(f"<option value='{e['id']}'>{esc(entity_display(e))}{' · PESEL '+esc(e['pesel']) if e['pesel'] else ''}{' · NIP '+esc(e['nip']) if e['nip'] else ''}</option>" for e in entities)
        body=f"""<div class='topbar'><div><h1>Nowa sprawa</h1><div class='sub'>Na początek wystarczą podstawowe informacje. Resztę możesz uzupełnić później.</div></div><div><a class='btn' href='/case/import'>Importuj sprawę</a></div></div>
        <div class='card friendly-form'><form method='post' action='/case/create' class='form-grid'>
        <div class='full'><label>Nazwa sprawy * <span class='help-dot' title='Krótka nazwa robocza, np. Kłosowska przeciwko Sobol'>?</span></label><input name='title' required autofocus placeholder='np. Kłosowska przeciwko Sobol'></div>
        <div class='full important-field'><label>Czego dotyczy sprawa? / Przedmiot * <span class='help-dot' title='Jedno krótkie zdanie, po którym każdy od razu rozumie sprawę.'>?</span></label><input name='subject' required placeholder='np. zapłata za bezumowne korzystanie z lokalu'><div class='small muted'>To zdanie będzie widoczne na liście i w nagłówku sprawy.</div></div>
        <div><label>Klient — kartoteka</label><select name='client_entity_id'>{entity_opts}</select></div><div><label>Klient — wpis tekstowy</label><input name='client' placeholder='np. Cecylia Kłosowska'></div>
        <div class='full'><label>Co trzeba zrobić dalej?</label><input name='next_step' placeholder='np. przygotować odpowiedź na pozew'></div><div><label>Termin następnej czynności</label><input type='date' name='next_date'></div><div><label>Status</label><select name='status'>{opts}</select></div>
        <details class='advanced-fields full'><summary>Więcej informacji — sygnatury, sąd, prowadzący, druga strona…</summary><div class='form-grid'>
        <div><label>Sygnatura sądowa</label><input name='signature'></div><div><label>Sygnatura wewnętrzna</label><input name='internal_signature' placeholder='np. RK/ALI/001/26'></div>
        <div><label>Przeciwnik / druga strona — kartoteka</label><select name='opponent_entity_id'>{entity_opts}</select></div><div><label>Prowadzący sprawę</label><select name='lead_user_id'>{lead_opts}</select></div>
        <div class='full'><label>Czekamy na / powód oczekiwania</label><input name='waiting_for' placeholder='np. sąd, klient, przeciwnik, urząd'></div>
        <div><label>Sąd / organ</label><input name='court'></div><div><label>Wydział</label><input name='department'></div><div><label>Kategoria</label><input name='category' placeholder='np. cywilna, rodzinna, karna'></div>
        <div class='full'><label>Tagi</label><input name='tags' placeholder='np. Alicja, zabezpieczenie, pilne'><div class='small muted'>Oddzielaj przecinkiem lub średnikiem.</div></div>
        <div class='full'><label>Notatki</label><textarea name='notes'></textarea></div></div></details>
        <div class='full form-actions'><button class='btn primary'>Utwórz sprawę</button> <a class='btn' href='/cases'>Anuluj</a></div></form></div>"""
        self.send_html(layout('Nowa sprawa',body,'cases'))

    def case_create(self, f):
        if not f.get('title','').strip() or not f.get('subject','').strip(): return self.redirect('/case/new')
        try: client_eid=int(f.get('client_entity_id','') or 0) or None
        except ValueError: client_eid=None
        try: opponent_eid=int(f.get('opponent_entity_id','') or 0) or None
        except ValueError: opponent_eid=None
        if client_eid and opponent_eid and client_eid==opponent_eid:
            return self.send_html(layout('Konflikt',"<div class='conflict-box'><h1>Ta sama osoba nie może być jednocześnie klientem i przeciwnikiem</h1><a class='btn' href='/case/new'>Wróć</a></div>",'cases'),400)
        conflicts=[]
        with db() as con:
            if client_eid:
                e=con.execute('SELECT * FROM entities WHERE id=?',(client_eid,)).fetchone()
                if e:
                    for x in conflict_rows(con,client_eid,'Klient'): conflicts.append((entity_display(e),'Klient',x))
            if opponent_eid:
                e=con.execute('SELECT * FROM entities WHERE id=?',(opponent_eid,)).fetchone()
                if e:
                    for x in conflict_rows(con,opponent_eid,'Przeciwnik'): conflicts.append((entity_display(e),'Przeciwnik',x))
        if conflicts and not f.get('_confirm_conflict'):
            rows=''.join(f"<li><b>{esc(name)}</b> jako {esc(intended)} — występuje w sprawie <a href='/case/{r['case_id']}'>{esc(primary_signature_text(r['case_id'],r['signature'],r['internal_signature']))}</a> ({esc(r['title'])}) jako <b>{esc(r['role'])}</b></li>" for name,intended,r in conflicts)
            hidden=''.join(f"<input type='hidden' name='{esc(k)}' value='{esc(v)}'>" for k,v in f.items() if k!='_confirm_conflict')+"<input type='hidden' name='_confirm_conflict' value='1'>"
            body=f"""<div class='conflict-box'><h1>⚠ Możliwy konflikt interesów</h1><p>Program znalazł wcześniejsze występowanie podmiotów po przeciwnej stronie:</p><ul>{rows}</ul><p class='small'>To jest ostrzeżenie pomocnicze — ostateczna ocena konfliktu należy do kancelarii.</p><form method='post' action='/case/create'>{hidden}<button class='btn danger'>Potwierdzam — utwórz mimo ostrzeżenia</button> <a class='btn' href='/case/new'>Anuluj</a></form></div>"""
            return self.send_html(layout('Kontrola konfliktu interesów',body,'cases'))
        keys=['signature','internal_signature','client','title','court','department','category','subject','status','waiting_for','next_step','next_date','notes']
        author=self.current_author(f)
        try: lead=int(f.get('lead_user_id','') or 0) or None
        except ValueError: lead=None
        vals=[f.get(k,'').strip() for k in keys]
        with db() as con:
            if client_eid:
                e=con.execute('SELECT * FROM entities WHERE id=?',(client_eid,)).fetchone()
                if e: vals[2]=entity_display(e)
            cur=con.execute("INSERT INTO cases(signature,internal_signature,client,title,court,department,category,subject,status,waiting_for,next_step,next_date,notes,lead_user_id,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",tuple(vals)+(lead,author,author))
            cid=cur.lastrowid
            set_case_tags(con,cid,f.get('tags',''))
            if client_eid: con.execute("INSERT INTO case_entities(case_id,entity_id,role,created_by,updated_by) VALUES(?,?, 'Klient',?,?)",(cid,client_eid,author,author))
            if opponent_eid: con.execute("INSERT INTO case_entities(case_id,entity_id,role,created_by,updated_by) VALUES(?,?, 'Przeciwnik',?,?)",(cid,opponent_eid,author,author))
            # Automatycznie zastosuj pierwszy szablon pasujący dokładnie do kategorii.
            category=f.get('category','').strip()
            if category:
                t=con.execute("SELECT id FROM checklist_templates WHERE category=? COLLATE NOCASE ORDER BY id LIMIT 1",(category,)).fetchone()
                if t:
                    for i,r in enumerate(con.execute('SELECT * FROM checklist_template_items WHERE template_id=? ORDER BY sort_order,id',(t['id'],)).fetchall()):
                        con.execute('INSERT INTO case_checklist_items(case_id,label,sort_order,template_id,created_by,updated_by) VALUES(?,?,?,?,?,?)',(cid,r['label'],i,t['id'],author,author))
            audit(con,cid,'case',cid,'Utworzono sprawę',f.get('title','').strip(),author)
        self.redirect(f'/case/{cid}')

    def _smart_label_map(self, con, cid):
        out = {}
        for r in con.execute("SELECT id,title FROM documents WHERE case_id=? ORDER BY id", (cid,)).fetchall():
            out[("document", r['id'])] = f"Dokument: {r['title']}"
        for r in con.execute("SELECT id,title FROM tasks WHERE case_id=? ORDER BY id", (cid,)).fetchall():
            out[("task", r['id'])] = f"Zadanie: {r['title']}"
        for r in con.execute("SELECT id,title FROM process_events WHERE case_id=? ORDER BY id", (cid,)).fetchall():
            out[("process_event", r['id'])] = f"Proces: {r['title']}"
        for r in con.execute("SELECT id,title FROM events WHERE case_id=? ORDER BY id", (cid,)).fetchall():
            out[("event", r['id'])] = f"Czynność: {r['title']}"
        for r in con.execute("SELECT id,title FROM alerts WHERE case_id=? ORDER BY id", (cid,)).fetchall():
            out[("alert", r['id'])] = f"Alert: {r['title']}"
        return out

    @staticmethod
    def _case_tab_url(cid: int, tab: str) -> str:
        return f"/case/{cid}?tab={quote(tab)}"

    def case_strategy_update(self, cid, f):
        fields = (
            'main_goal','minimum_variant','opponent_position','our_arguments',
            'opponent_arguments','response_arguments','risks','hearing_plan',
            'motions_to_make','witness_questions','settlement_position','watchouts',
        )
        values = [(f.get(name) or '').strip() for name in fields]
        author = self.current_author(f)
        with db() as con:
            if not con.execute('SELECT 1 FROM cases WHERE id=?',(cid,)).fetchone():
                return self.send_error(404)
            old = con.execute('SELECT * FROM case_strategy WHERE case_id=?',(cid,)).fetchone()
            con.execute(
                f"""INSERT INTO case_strategy(case_id,{','.join(fields)},updated_by,updated_at)
                    VALUES(?,{','.join('?' for _ in fields)},?,CURRENT_TIMESTAMP)
                    ON CONFLICT(case_id) DO UPDATE SET
                    {','.join(name+'=excluded.'+name for name in fields)},updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP""",
                (cid,*values,author),
            )
            changed = describe_changes(old,dict(zip(fields,values)),{
                'main_goal':'Cel główny','minimum_variant':'Wariant minimum','opponent_position':'Stanowisko przeciwnika',
                'our_arguments':'Nasze argumenty','opponent_arguments':'Argumenty przeciwnika','response_arguments':'Odpowiedź',
                'risks':'Ryzyka','hearing_plan':'Plan rozprawy','motions_to_make':'Wnioski do zgłoszenia',
                'witness_questions':'Pytania do świadków','settlement_position':'Stanowisko ugodowe','watchouts':'Czego pilnować',
            },compact_fields=set(fields)) if old else 'Utworzono strategię sprawy'
            audit(con,cid,'case_strategy',cid,'Zapisano strategię sprawy',changed,author)
        self.redirect(self._case_tab_url(cid,'strategy'))

    def case_assertion_add(self, cid, f):
        statement = (f.get('statement') or '').strip()
        if not statement:
            return self.redirect(self._case_tab_url(cid,'evidence'))
        side = (f.get('side') or 'nasze').strip()
        status = (f.get('status') or 'do udowodnienia').strip()
        author = self.current_author(f)
        with db() as con:
            cur=con.execute("""INSERT INTO case_assertions(case_id,statement,side,status,legal_significance,notes,sort_order,created_by,updated_by)
                               VALUES(?,?,?,?,?,?,?,?,?)""",
                            (cid,statement,side,status,(f.get('legal_significance') or '').strip(),
                             (f.get('notes') or '').strip(),int(f.get('sort_order') or 0),author,author))
            audit(con,cid,'assertion',cur.lastrowid,'Dodano twierdzenie',statement,author)
        self.redirect(self._case_tab_url(cid,'evidence'))

    def case_assertion_update(self, assertion_id, f):
        author=self.current_author(f)
        with db() as con:
            old=con.execute('SELECT * FROM case_assertions WHERE id=?',(assertion_id,)).fetchone()
            if not old: return self.send_error(404)
            new={'statement':(f.get('statement') or '').strip(),'side':(f.get('side') or 'nasze').strip(),
                 'status':(f.get('status') or 'do udowodnienia').strip(),
                 'legal_significance':(f.get('legal_significance') or '').strip(),'notes':(f.get('notes') or '').strip()}
            con.execute("""UPDATE case_assertions SET statement=?,side=?,status=?,legal_significance=?,notes=?,updated_by=?,updated_at=CURRENT_TIMESTAMP
                           WHERE id=?""",(*new.values(),author,assertion_id))
            details=describe_changes(old,new,{'statement':'Twierdzenie','side':'Strona','status':'Status','legal_significance':'Znaczenie prawne','notes':'Notatki'},compact_fields={'statement','legal_significance','notes'})
            if details: audit(con,old['case_id'],'assertion',assertion_id,'Zmieniono twierdzenie',details,author)
            cid=old['case_id']
        self.redirect(self._case_tab_url(cid,'evidence'))

    def case_assertion_delete(self, assertion_id, f):
        author=self.current_author(f)
        with db() as con:
            row=con.execute('SELECT * FROM case_assertions WHERE id=?',(assertion_id,)).fetchone()
            if not row: return self.send_error(404)
            con.execute('UPDATE case_assertions SET is_archived=1,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(author,assertion_id))
            audit(con,row['case_id'],'assertion',assertion_id,'Zarchiwizowano twierdzenie',row['statement'],author)
            cid=row['case_id']
        self.redirect(self._case_tab_url(cid,'evidence'))

    def case_evidence_add(self, assertion_id, f):
        title=(f.get('title') or '').strip()
        if not title: return self.send_error(400,'Dowód wymaga nazwy.')
        author=self.current_author(f)
        try: document_id=int(f.get('document_id') or 0) or None
        except ValueError: document_id=None
        with db() as con:
            assertion=con.execute('SELECT * FROM case_assertions WHERE id=? AND is_archived=0',(assertion_id,)).fetchone()
            if not assertion: return self.send_error(404)
            if document_id and not con.execute('SELECT 1 FROM documents WHERE id=? AND case_id=?',(document_id,assertion['case_id'])).fetchone():
                document_id=None
            cur=con.execute("""INSERT INTO case_evidence(assertion_id,evidence_type,title,status,document_id,source_reference,notes,created_by)
                               VALUES(?,?,?,?,?,?,?,?)""",
                            (assertion_id,(f.get('evidence_type') or 'Dokument').strip(),title,
                             (f.get('status') or 'do przeprowadzenia').strip(),document_id,
                             (f.get('source_reference') or '').strip(),(f.get('notes') or '').strip(),author))
            audit(con,assertion['case_id'],'evidence',cur.lastrowid,'Dodano dowód',title,author)
            cid=assertion['case_id']
        self.redirect(self._case_tab_url(cid,'evidence'))

    def case_evidence_delete(self, evidence_id, f):
        author=self.current_author(f)
        with db() as con:
            row=con.execute("""SELECT e.*,a.case_id FROM case_evidence e JOIN case_assertions a ON a.id=e.assertion_id WHERE e.id=?""",(evidence_id,)).fetchone()
            if not row: return self.send_error(404)
            con.execute('UPDATE case_evidence SET is_archived=1 WHERE id=?',(evidence_id,))
            audit(con,row['case_id'],'evidence',evidence_id,'Zarchiwizowano dowód',row['title'],author)
            cid=row['case_id']
        self.redirect(self._case_tab_url(cid,'evidence'))

    @staticmethod
    def _claim_values(f):
        return {
            'claim_type':(f.get('claim_type') or 'Roszczenie główne').strip(),
            'title':(f.get('title') or '').strip(),
            'principal_cents':money_to_cents(f.get('principal')),
            'interest_cents':money_to_cents(f.get('interest')),
            'costs_cents':money_to_cents(f.get('costs')),
            'paid_cents':money_to_cents(f.get('paid')),
            'awarded_cents':money_to_cents(f.get('awarded')),
            'settlement_cents':money_to_cents(f.get('settlement')),
            'currency':(f.get('currency') or 'PLN').strip().upper()[:8],
            'status':(f.get('status') or 'dochodzone').strip(),
            'notes':(f.get('notes') or '').strip(),
        }

    def case_claim_add(self, cid, f):
        new=self._claim_values(f)
        if not new['title']: return self.redirect(self._case_tab_url(cid,'finances'))
        author=self.current_author(f)
        with db() as con:
            cols=list(new)
            cur=con.execute(f"INSERT INTO case_claims(case_id,{','.join(cols)},created_by,updated_by) VALUES(?,{','.join('?' for _ in cols)},?,?)",(cid,*[new[x] for x in cols],author,author))
            audit(con,cid,'claim',cur.lastrowid,'Dodano pozycję roszczenia',new['title'],author)
        self.redirect(self._case_tab_url(cid,'finances'))

    def case_claim_update(self, claim_id, f):
        new=self._claim_values(f); author=self.current_author(f)
        with db() as con:
            old=con.execute('SELECT * FROM case_claims WHERE id=?',(claim_id,)).fetchone()
            if not old: return self.send_error(404)
            cols=list(new)
            con.execute(f"UPDATE case_claims SET {','.join(x+'=?' for x in cols)},updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(*[new[x] for x in cols],author,claim_id))
            audit(con,old['case_id'],'claim',claim_id,'Zmieniono pozycję roszczenia',new['title'],author)
            cid=old['case_id']
        self.redirect(self._case_tab_url(cid,'finances'))

    def case_claim_delete(self, claim_id, f):
        author=self.current_author(f)
        with db() as con:
            row=con.execute('SELECT * FROM case_claims WHERE id=?',(claim_id,)).fetchone()
            if not row: return self.send_error(404)
            con.execute("UPDATE case_claims SET status='archiwalne',updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(author,claim_id))
            audit(con,row['case_id'],'claim',claim_id,'Zarchiwizowano pozycję roszczenia',row['title'],author)
            cid=row['case_id']
        self.redirect(self._case_tab_url(cid,'finances'))

    def document_event_add(self, cid, f):
        title=(f.get('title') or '').strip()
        try: document_id=int(f.get('document_id') or 0)
        except ValueError: document_id=0
        if not title or not document_id: return self.redirect(self._case_tab_url(cid,'history'))
        author=self.current_author(f)
        with db() as con:
            if not con.execute('SELECT 1 FROM documents WHERE id=? AND case_id=?',(document_id,cid)).fetchone():
                return self.send_error(400,'Dokument nie należy do tej sprawy.')
            cur=con.execute("""INSERT INTO document_events(document_id,case_id,event_date,event_type,title,description,created_by)
                               VALUES(?,?,?,?,?,?,?)""",(document_id,cid,(f.get('event_date') or '').strip(),
                               (f.get('event_type') or 'Dotyczy').strip(),title,(f.get('description') or '').strip(),author))
            audit(con,cid,'document_event',cur.lastrowid,'Dodano zdarzenie wynikające z dokumentu',title,author)
        self.redirect(self._case_tab_url(cid,'history'))

    def document_event_delete(self, event_id, f):
        author=self.current_author(f)
        with db() as con:
            row=con.execute('SELECT * FROM document_events WHERE id=?',(event_id,)).fetchone()
            if not row: return self.send_error(404)
            con.execute('UPDATE document_events SET is_archived=1 WHERE id=?',(event_id,))
            audit(con,row['case_id'],'document_event',event_id,'Zarchiwizowano zdarzenie dokumentu',row['title'],author)
            cid=row['case_id']
        self.redirect(self._case_tab_url(cid,'history'))

    def case_view(self, cid, qs=None):
        qs = qs or {}
        mode = (qs.get('mode') or ['simple'])[0].strip().lower()
        if mode == 'advanced':
            return self.case_view_advanced(cid)
        if mode == 'legacy':
            return self.case_view_simple(cid, qs)
        return self.case_workspace(cid, qs)


    def case_workspace(self, cid, qs=None):
        """Zakładkowy warsztat sprawy: jeden nagłówek, jeden kontekst pracy naraz."""
        qs = qs or {}
        valid_tabs = ('dashboard','history','documents','tasks','deadlines','evidence','strategy','hearing','finances','people','relations','notes')
        user = current_request_user(); uid = user['id'] if user else None
        requested = (qs.get('tab') or [''])[0].strip().lower()
        with db() as con:
            c=con.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone()
            if not c: return self.send_error(404)
            if uid:
                con.execute("""INSERT INTO user_case_recent(user_id,case_id,opened_at) VALUES(?,?,CURRENT_TIMESTAMP)
                               ON CONFLICT(user_id,case_id) DO UPDATE SET opened_at=CURRENT_TIMESTAMP""",(uid,cid))
            if requested in valid_tabs:
                tab=requested
                if uid:
                    con.execute("""INSERT INTO user_case_view_preferences(user_id,case_id,last_tab,updated_at)
                                   VALUES(?,?,?,CURRENT_TIMESTAMP)
                                   ON CONFLICT(user_id,case_id) DO UPDATE SET last_tab=excluded.last_tab,updated_at=CURRENT_TIMESTAMP""",(uid,cid,tab))
            else:
                pref=con.execute('SELECT last_tab FROM user_case_view_preferences WHERE user_id=? AND case_id=?',(uid,cid)).fetchone() if uid else None
                tab=(pref['last_tab'] if pref and pref['last_tab'] in valid_tabs else 'dashboard')
            derive_case_auto_tags(con,cid)
            summary=generate_case_summary(con,cid)
            parties=con.execute('SELECT * FROM parties WHERE case_id=? ORDER BY id',(cid,)).fetchall()
            entities=con.execute("""SELECT ce.*,e.display_name,e.pesel,e.nip,e.krs FROM case_entities ce
                                    JOIN entities e ON e.id=ce.entity_id WHERE ce.case_id=? ORDER BY ce.id""",(cid,)).fetchall()
            all_entities=con.execute('SELECT id,display_name,pesel,nip FROM entities ORDER BY display_name COLLATE NOCASE').fetchall()
            auto_tags=con.execute('SELECT tag,reason FROM case_auto_tags WHERE case_id=? ORDER BY tag',(cid,)).fetchall()
            manual_tags=con.execute("""SELECT t.name FROM case_tags ct JOIN tags t ON t.id=ct.tag_id
                                       WHERE ct.case_id=? ORDER BY t.name""",(cid,)).fetchall()
            timeline=build_unified_timeline(con,cid,250)
            tasks=con.execute("""SELECT t.*,u.author_name assigned_name,u.function assigned_function FROM tasks t
                                 LEFT JOIN users u ON u.id=t.assigned_user_id WHERE t.case_id=?
                                 ORDER BY t.status,CASE WHEN t.due_date='' THEN 1 ELSE 0 END,t.due_date,t.id""",(cid,)).fetchall()
            alerts=con.execute("SELECT * FROM alerts WHERE case_id=? AND status='open' ORDER BY alert_date,id",(cid,)).fetchall()
            docs=con.execute("""SELECT * FROM documents WHERE case_id=?
                                ORDER BY COALESCE(NULLIF(delivered_date,''),NULLIF(received_date,''),NULLIF(doc_date,''),created_at) DESC,id DESC""",(cid,)).fetchall()
            doc_events=con.execute("""SELECT de.*,d.title document_title FROM document_events de JOIN documents d ON d.id=de.document_id
                                      WHERE de.case_id=? AND de.is_archived=0 ORDER BY de.event_date DESC,de.id DESC""",(cid,)).fetchall()
            strategy=con.execute('SELECT * FROM case_strategy WHERE case_id=?',(cid,)).fetchone()
            assertions=con.execute('SELECT * FROM case_assertions WHERE case_id=? AND is_archived=0 ORDER BY sort_order,id',(cid,)).fetchall()
            evidence=con.execute("""SELECT e.*,d.title document_title FROM case_evidence e LEFT JOIN documents d ON d.id=e.document_id
                                    JOIN case_assertions a ON a.id=e.assertion_id WHERE a.case_id=? AND e.is_archived=0 ORDER BY e.id""",(cid,)).fetchall()
            claims=con.execute("SELECT * FROM case_claims WHERE case_id=? AND status<>'archiwalne' ORDER BY id",(cid,)).fetchall()
            notes=con.execute('SELECT * FROM case_notes WHERE case_id=? ORDER BY created_at DESC,id DESC',(cid,)).fetchall()
            process_events=con.execute("""SELECT * FROM process_events WHERE case_id=?
                                         ORDER BY COALESCE(NULLIF(event_date,''),'0000-00-00') DESC,id DESC""",(cid,)).fetchall()
            law_links=con.execute("""SELECT a.code,COALESCE(la.article_key,lcl.article_key_text) article_key,lcl.note
                                     FROM law_case_links lcl JOIN law_acts a ON a.id=lcl.act_id
                                     LEFT JOIN law_articles la ON la.id=lcl.article_id WHERE lcl.case_id=?
                                     ORDER BY a.code,la.sort_order""",(cid,)).fetchall()
            suggestions=con.execute("""SELECT ds.*,d.title document_title FROM deadline_suggestions ds LEFT JOIN documents d ON d.id=ds.document_id
                                       WHERE ds.case_id=? AND ds.status='open' ORDER BY ds.id DESC""",(cid,)).fetchall()
            users=con.execute('SELECT id,author_name,function FROM users WHERE is_active=1 ORDER BY author_name').fetchall()
            relation_count=int(con.execute('SELECT COUNT(*) FROM case_relations WHERE source_case_id=? OR target_case_id=?',(cid,cid)).fetchone()[0])
            relations=[]; relation_cases=[]
            if tab=='relations':
                relations=con.execute('''SELECT r.*,
                    sc.signature source_signature,sc.internal_signature source_internal,sc.title source_title,sc.status source_status,
                    tc.signature target_signature,tc.internal_signature target_internal,tc.title target_title,tc.status target_status
                    FROM case_relations r JOIN cases sc ON sc.id=r.source_case_id JOIN cases tc ON tc.id=r.target_case_id
                    WHERE r.source_case_id=? OR r.target_case_id=? ORDER BY r.created_at DESC,r.id DESC''',(cid,cid)).fetchall()
                relation_cases=con.execute('''SELECT id,signature,internal_signature,title,status FROM cases
                                              WHERE id<>? ORDER BY status='closed',signature='',signature,title COLLATE NOCASE''',(cid,)).fetchall()
            readonly=bool(c['status']=='closed' and not int(c['closed_edit_unlocked'] or 0))

        shown_sig,sig_kind=display_case_signature(cid,c['signature'],c['internal_signature'])
        primary=shown_sig if shown_sig!='Bez sygnatury' else (c['internal_signature'] or 'Bez sygnatury')
        shown_people=entities or parties
        party_line=' · '.join(f"{x['role']}: {x['display_name'] if 'display_name' in x.keys() else x['name']}" for x in shown_people) or 'Nie dodano stron'
        tags=''.join(f"<span class='smart-tag auto' title='{esc(x['reason'])}'>{esc(x['tag'])}</span>" for x in auto_tags)
        tags+=''.join(f"<span class='smart-tag'>{esc(x['name'])}</span>" for x in manual_tags)
        open_tasks=[x for x in tasks if x['status']!='done']
        next_task=next((x for x in open_tasks if x['due_date']),open_tasks[0] if open_tasks else None)
        last_item=timeline[0] if timeline else None
        next_dates=[]
        for x in open_tasks:
            if x['due_date']: next_dates.append((x['due_date'],row_get(x,'task_type','Zadanie'),x['title']))
        for x in alerts: next_dates.append((x['alert_date'],x['alert_type'],x['title']))
        if c['next_date']: next_dates.append((c['next_date'],'Następna czynność',c['next_step'] or c['title']))
        next_dates=sorted({(d,k,t) for d,k,t in next_dates if d})
        next_date=next_dates[0] if next_dates else None

        tab_meta=[
            ('dashboard','Pulpit',''),('history','Historia',str(len(timeline))),('documents','Dokumenty',str(len(docs))),
            ('tasks','Zadania',str(len(open_tasks))),('deadlines','Terminy',str(len(next_dates))),
            ('evidence','Dowody',str(len(assertions))),('strategy','Strategia',''),('hearing','Rozprawa',''),
            ('finances','Finanse',str(len(claims))),('people','Osoby',str(len(shown_people))),
            ('relations','Powiązania',str(relation_count)),('notes','Notatki',str(len(notes))),
        ]
        tab_nav=''.join(f"<a class='case-tab {'active' if tab==key else ''}' href='/case/{cid}?tab={key}'>{label}{f'<span>{count}</span>' if count else ''}</a>" for key,label,count in tab_meta)
        header=f"""<div class='case-workspace-sticky' id='rkCaseContext'>
          <div class='case-workspace-head'><div class='case-workspace-identity'><div class='case-workspace-sig'>{esc(primary)}</div>
          <div class='case-workspace-parties'>{esc(party_line)}</div><h1>{esc(c['title'])}</h1></div>
          <div class='case-workspace-actions'>{badge(c['status'])}<a class='btn small' href='/case/{cid}/edit'>Edytuj</a><a class='btn small' href='/case/{cid}/export'>Eksport</a>{("<a class='btn small danger' href='/case/"+str(cid)+"/delete'>Usuń duplikat</a>") if user and user['role']=='admin' else ''}<a class='btn small' href='/case/{cid}?mode=advanced'>Widok techniczny</a></div></div>
          <div class='case-workspace-meta'><span>{esc(c['court']) or 'Sąd/organ: —'}</span><span>{esc(c['category']) or 'Kategoria: —'}</span><div class='smart-tags'>{tags}</div></div>
          <nav class='case-tabs'>{tab_nav}</nav></div>"""
        readonly_html="<div class='readonly-banner'>Sprawa zakończona — widok tylko do odczytu.</div>" if readonly else ''
        ro_disabled=' disabled' if readonly else ''

        if tab=='dashboard':
            alert_count=len(alerts)+len(suggestions)
            risk=(strategy['risks'] if strategy else '') or 'Nie wpisano ryzyk.'
            content=f"""<section class='case-tab-content'><div class='workspace-kpi-grid'>
              <div class='workspace-kpi'><span>Stan sprawy</span><b>{esc(summary['stage'])}</b><small>{esc(summary['description'])}</small></div>
              <div class='workspace-kpi'><span>Następny termin</span><b>{fmt_date(next_date[0]) if next_date else 'Brak'}</b><small>{esc((next_date[1]+' · '+next_date[2]) if next_date else 'Nie wskazano daty')}</small></div>
              <div class='workspace-kpi'><span>Najbliższe zadanie</span><b>{esc(next_task['title']) if next_task else 'Brak'}</b><small>{fmt_date(next_task['due_date']) if next_task else 'Wszystko wykonane'}</small></div>
              <div class='workspace-kpi'><span>Alerty</span><b>{alert_count}</b><small>{'Wymagają sprawdzenia' if alert_count else 'Brak otwartych alertów'}</small></div>
            </div><div class='grid'>
              <div class='card span7'><div class='section-kicker'>CO TERAZ</div><h2>{esc(c['next_step']) or esc(summary['next'])}</h2><p class='muted'>{('Termin: '+fmt_date(c['next_date'])) if c['next_date'] else 'Bez wskazanej daty.'}</p>
              {'' if readonly else f'''<form method="post" action="/case/{cid}/next-action" class="form-grid"><input type="hidden" name="return_to" value="/case/{cid}?tab=dashboard"><div class="full"><label>Następny ruch</label><input name="next_step" value="{esc(c['next_step'])}"></div><div><label>Termin</label><input type="date" name="next_date" value="{esc(c['next_date'])}"></div><div><label>Czekamy na</label><input name="waiting_for" value="{esc(c['waiting_for'])}"></div><div class="full"><button class="btn primary">Zapisz</button></div></form>'''}</div>
              <div class='card span5'><div class='section-kicker'>RYZYKA</div><h2>Na co uważać</h2><div class='workspace-pre'>{esc(risk)}</div><a class='btn small' href='/case/{cid}?tab=strategy'>Otwórz strategię</a></div>
              <div class='card span12'><div class='section-head'><div><div class='section-kicker'>OSTATNIE</div><h2>{esc(last_item['title']) if last_item else 'Brak historii'}</h2></div><a class='btn small' href='/case/{cid}?tab=history'>Pełna historia</a></div><p class='muted'>{fmt_date(last_item['date']) if last_item else ''} {esc(last_item['description']) if last_item else 'Dodaj pierwszą czynność lub dokument.'}</p></div>
            </div></section>"""

        elif tab=='history':
            grouped={}
            for item in timeline: grouped.setdefault(item.get('date') or '',[]).append(item)
            timeline_parts=[]
            for d in sorted(grouped,reverse=True):
                rows=[]
                for x in grouped[d]:
                    href=f"/document/{x['source_id']}/open" if x['source_type']=='document' else '#'
                    rows.append(f"<a class='timeline-clean-row' href='{href}'><span class='timeline-clean-kind'>{esc(x['kind'])}</span><div><b>{esc(x['title'])}</b><small>{esc(x.get('description',''))}</small></div></a>")
                timeline_parts.append(f"<div class='timeline-day'><div class='timeline-day-date'>{fmt_date(d)}</div><div class='timeline-day-items'>{''.join(rows)}</div></div>")
            doc_opts=''.join(f"<option value='{x['id']}'>{esc(x['title'])}</option>" for x in docs if not row_get(x,'parent_document_id',None))
            add_forms='' if readonly else f"""<div class='grid workspace-add-grid'><details class='card span6 smart-add'><summary>+ Zdarzenie kancelarii</summary><form method='post' action='/case/{cid}/event' class='form-grid'><input type='hidden' name='return_to' value='/case/{cid}?tab=history'><div><label>Data</label><input type='date' name='event_date' value='{date.today().isoformat()}'></div><div><label>Typ</label><input name='event_type' value='Czynność'></div><div class='full'><label>Tytuł</label><input name='title' required></div><div class='full'><label>Opis</label><textarea name='description'></textarea></div><div class='full'><button class='btn primary'>Dodaj</button></div></form></details>
              <details class='card span6 smart-add'><summary>+ Zdarzenie wynikające z dokumentu</summary><form method='post' action='/case/{cid}/document-event' class='form-grid'><div class='full'><label>Dokument</label><select name='document_id' required><option value=''>— wybierz —</option>{doc_opts}</select></div><div><label>Data zdarzenia</label><input type='date' name='event_date'></div><div><label>Rodzaj</label><input name='event_type' placeholder='np. doręczenie, termin, rozprawa'></div><div class='full'><label>Co wynika z dokumentu?</label><input name='title' required></div><div class='full'><label>Opis</label><textarea name='description'></textarea></div><div class='full'><button class='btn primary'>Dodaj</button></div></form></details></div>"""
            content=f"<section class='case-tab-content'><div class='section-head'><div><h2>Historia sprawy</h2><div class='muted'>Kilka dat z jednego dokumentu może tworzyć kilka osobnych zdarzeń.</div></div><a class='btn' href='/case/{cid}/history'>Historia procesu i zmian</a></div>{add_forms}<div class='card'><div class='timeline-clean'>{''.join(timeline_parts) or '<div class="empty">Brak historii.</div>'}</div></div></section>"

        elif tab=='documents':
            rows=[]
            for d in docs:
                parent=' <span class="attachment-label">załącznik</span>' if row_get(d,'parent_document_id',None) else ''
                state=f"<span class='doc-status {'sign' if d['doc_status']=='Do podpisu' else ''}'>{esc(d['doc_status'])}</span>"
                rows.append(f"<tr><td>{fmt_date(d['doc_date'])}<div class='small muted'>wpływ {fmt_date(d['received_date'])} · doręczenie {fmt_date(d['delivered_date'])}</div></td><td><a class='case-link' href='/document/{d['id']}/open'>{esc(d['title'])}</a>{parent}<div class='small muted'>{esc(d['doc_type'])} · {esc(d['sender'])}</div></td><td>{state}</td><td><a class='btn small' href='/document/{d['id']}/edit'>Edytuj</a></td></tr>")
            add='' if readonly else f"""<details class='card smart-add'><summary>+ Dodaj dokument</summary><form method='post' enctype='multipart/form-data' action='/case/{cid}/document' class='form-grid'><input type='hidden' name='return_to' value='/case/{cid}?tab=documents'><div><label>Data dokumentu</label><input type='date' name='doc_date'></div><div><label>Data wpływu</label><input type='date' name='received_date'></div><div><label>Data doręczenia</label><input type='date' name='delivered_date'></div><div><label>Rodzaj</label><select name='doc_type'>{''.join(f'<option>{esc(x)}</option>' for x in DOC_TYPES)}</select></div><div class='full'><label>Tytuł</label><input name='title' required></div><div><label>Nadawca</label><input name='sender'></div><div><label>Status</label><select name='doc_status'>{''.join(f'<option>{esc(x)}</option>' for x in DOC_STATUSES)}</select></div><div class='full'><label>Opis</label><textarea name='description'></textarea></div><div class='full'><label>Plik</label><input type='file' name='file'></div><div class='full'><label>Załączniki</label><input type='file' name='attachments[]' multiple></div><div class='full'><button class='btn primary'>Dodaj dokument</button></div></form></details>"""
            content=f"<section class='case-tab-content'><div class='section-head'><div><h2>Dokumenty</h2><div class='muted'>Dokumenty i załączniki wyłącznie tej sprawy.</div></div><a class='btn' href='/documents?case_id={cid}'>Widok globalny</a></div>{add}<div class='card table-scroll'><table><tr><th>Daty</th><th>Dokument</th><th>Status</th><th></th></tr>{''.join(rows) or '<tr><td colspan=4>Brak dokumentów.</td></tr>'}</table></div></section>"

        elif tab=='tasks':
            task_rows=[]
            for t in tasks:
                done=t['status']=='done'; assignee=esc(t['assigned_name']) if t['assigned_name'] else '—'
                task_rows.append(f"<div class='workspace-task {'done' if done else ''}'><form method='post' action='/task/{t['id']}/toggle'><input type='hidden' name='case_id' value='{cid}'><input type='hidden' name='return_to' value='/case/{cid}?tab=tasks'><button class='task-check'>{'↩' if done else '✓'}</button></form><div><span class='mini-badge'>{esc(row_get(t,'task_type','Zadanie'))}</span> <b>{esc(t['title'])}</b><small>{fmt_date(t['due_date'])} · {assignee}{(' · '+esc(t['depends_on'])) if t['depends_on'] else ''}</small></div><a class='btn small' href='/task/{t['id']}/edit?return_to=%2Fcase%2F{cid}%3Ftab%3Dtasks'>Edytuj</a></div>")
            user_opts='<option value="">— bez przypisania —</option>'+''.join(f"<option value='{x['id']}'>{esc(user_display_name(x))}</option>" for x in users)
            add='' if readonly else f"""<details class='card smart-add'><summary>+ Dodaj zadanie</summary><form method='post' action='/case/{cid}/task' class='form-grid'><input type='hidden' name='return_to' value='/case/{cid}?tab=tasks'><div><label>Rodzaj</label><select name='task_type'>{''.join(f'<option>{x}</option>' for x in ['Zadanie','Monit','Termin procesowy','Płatność'])}</select></div><div><label>Termin</label><input type='date' name='due_date'></div><div class='full'><label>Co trzeba zrobić?</label><input name='title' required></div><div><label>Wykonawca</label><select name='assigned_user_id'>{user_opts}</select></div><div><label>Priorytet</label><select name='priority'><option value='normal'>Normalny</option><option value='high'>Wysoki</option></select></div><div class='full'><label>Zależność</label><input name='depends_on'></div><div class='full'><label>Notatka</label><textarea name='notes'></textarea></div><div class='full'><button class='btn primary'>Dodaj</button></div></form></details>"""
            content=f"<section class='case-tab-content'><div class='section-head'><div><h2>Zadania</h2><div class='muted'>Otwarte i wykonane czynności tej sprawy.</div></div></div>{add}<div class='card workspace-task-list'>{''.join(task_rows) or '<div class="empty">Brak zadań.</div>'}</div></section>"

        elif tab=='deadlines':
            deadline_rows=[]
            seen=set()
            for d,k,t in next_dates:
                key=(d,t)
                if key in seen: continue
                seen.add(key); deadline_rows.append(f"<tr><td><b>{fmt_date(d)}</b></td><td>{esc(k)}</td><td>{esc(t)}</td></tr>")
            suggestions_html=''.join(f"<div class='deadline-suggestion'><b>{esc(x['suggested_title'])}</b><div class='small'>{esc(x['source_text'])}</div><form method='post' action='/deadline-suggestion/{x['id']}/accept'><input type='hidden' name='return_to' value='/case/{cid}?tab=deadlines'><button class='btn primary small'>Zatwierdź</button></form></div>" for x in suggestions) or '<div class="empty">Brak sugestii.</div>'
            doc_scan=''.join(f"<form method='post' action='/document/{d['id']}/suggest-deadlines' class='doc-scan-row'><input type='hidden' name='return_to' value='/case/{cid}?tab=deadlines'><span><b>{esc(d['title'])}</b></span><button class='btn small'>Sprawdź treść</button></form>" for d in docs if not row_get(d,'parent_document_id',None))
            manual='' if readonly else f"""<details class='card smart-add'><summary>+ Wylicz termin procesowy</summary><form method='post' action='/deadline/create' class='form-grid'><input type='hidden' name='case_id' value='{cid}'><input type='hidden' name='return_to' value='/case/{cid}?tab=deadlines'><div class='full'><label>Czynność</label><input name='title' required></div><div><label>Data początkowa</label><input type='date' name='base_date' required></div><div><label>Liczba dni</label><input type='number' name='days' min='0' value='7' required></div><div><label>Sposób liczenia</label><select name='rule'><option value='calendar'>Kalendarzowe / procesowe</option><option value='business'>Robocze</option></select></div><div><label>Priorytet</label><select name='priority'><option value='high'>Wysoki</option><option value='normal'>Normalny</option></select></div><div class='full'><label>Podstawa / źródło</label><input name='source'></div><div class='full'><button class='btn primary'>Wylicz i dodaj</button></div></form></details>"""
            content=f"<section class='case-tab-content'><div class='section-head'><div><h2>Terminy</h2><div class='muted'>Terminy są zawsze zatwierdzane przez użytkownika.</div></div><a class='btn' href='/calendar?case_id={cid}'>Kalendarz sprawy</a></div>{manual}<div class='grid'><div class='card span7 table-scroll'><table><tr><th>Data</th><th>Rodzaj</th><th>Czynność</th></tr>{''.join(deadline_rows) or '<tr><td colspan=3>Brak terminów.</td></tr>'}</table></div><div class='card span5'><h2>Sugestie z dokumentów</h2>{suggestions_html}<details><summary>Sprawdź dokumenty</summary>{doc_scan or '<div class="empty">Brak dokumentów.</div>'}</details></div></div></section>"

        elif tab=='evidence':
            by_assertion={x['id']:[] for x in assertions}
            for e in evidence: by_assertion.setdefault(e['assertion_id'],[]).append(e)
            cards=[]
            for a in assertions:
                ev=[]
                for e in by_assertion.get(a['id'],[]):
                    link=f"<a href='/document/{e['document_id']}/open'>{esc(e['document_title'])}</a>" if e['document_id'] else esc(e['source_reference'])
                    delete='' if readonly else f"<form method='post' action='/evidence/{e['id']}/delete' onsubmit=\"return confirm('Archiwizować ten dowód?');\"><button class='btn small danger'>Archiwizuj</button></form>"
                    ev.append(f"<div class='evidence-row'><span class='evidence-status status-{esc(e['status']).replace(' ','-')}'>{esc(e['status'])}</span><div><b>{esc(e['title'])}</b><small>{esc(e['evidence_type'])}{(' · '+link) if link else ''}</small></div>{delete}</div>")
                doc_opts='<option value="">— bez dokumentu —</option>'+''.join(f"<option value='{d['id']}'>{esc(d['title'])}</option>" for d in docs)
                add_e='' if readonly else f"""<details class='smart-add'><summary>+ Dodaj dowód</summary><form method='post' action='/assertion/{a['id']}/evidence' class='form-grid'><div><label>Rodzaj</label><select name='evidence_type'><option>Dokument</option><option>Zeznania świadka</option><option>Opinia biegłego</option><option>Przesłuchanie strony</option><option>Inny</option></select></div><div><label>Status</label><select name='status'><option>do przeprowadzenia</option><option>przeprowadzony</option><option>kwestionowany</option><option>pominięty</option></select></div><div class='full'><label>Nazwa dowodu</label><input name='title' required></div><div class='full'><label>Dokument w programie</label><select name='document_id'>{doc_opts}</select></div><div><label>Inne źródło</label><input name='source_reference'></div><div><label>Notatka</label><input name='notes'></div><div class='full'><button class='btn primary'>Dodaj dowód</button></div></form></details>"""
                archive='' if readonly else f"<form method='post' action='/assertion/{a['id']}/delete' onsubmit=\"return confirm('Archiwizować twierdzenie wraz z mapą dowodów?');\"><button class='btn small danger'>Archiwizuj twierdzenie</button></form>"
                cards.append(f"<article class='assertion-card'><div class='assertion-head'><div><span class='mini-badge'>{esc(a['side'])}</span><span class='evidence-status'>{esc(a['status'])}</span><h3>{esc(a['statement'])}</h3><small>{esc(a['legal_significance'])}</small></div>{archive}</div><div class='evidence-list'>{''.join(ev) or '<div class="empty">Brak przypisanych dowodów.</div>'}</div>{add_e}</article>")
            add_a='' if readonly else f"""<details class='card smart-add'><summary>+ Dodaj twierdzenie</summary><form method='post' action='/case/{cid}/assertion' class='form-grid'><div><label>Strona</label><select name='side'><option value='nasze'>Nasze</option><option value='przeciwnika'>Przeciwnika</option><option value='bezsporne'>Bezsporne</option></select></div><div><label>Status</label><select name='status'><option>do udowodnienia</option><option>udowodnione</option><option>sporne</option><option>brak dowodu</option><option>dowód przeciwnika</option></select></div><div class='full'><label>Twierdzenie / fakt</label><textarea name='statement' required></textarea></div><div class='full'><label>Znaczenie prawne</label><input name='legal_significance'></div><div class='full'><button class='btn primary'>Dodaj twierdzenie</button></div></form></details>"""
            content=f"<section class='case-tab-content'><div class='section-head'><div><h2>Mapa twierdzeń i dowodów</h2><div class='muted'>Od faktu do dowodu — od razu widać luki.</div></div></div>{add_a}<div class='assertion-grid'>{''.join(cards) or '<div class="empty">Nie dodano jeszcze twierdzeń.</div>'}</div></section>"

        elif tab=='strategy':
            def sv(name): return esc(strategy[name] if strategy else '')
            form=f"""<form method='post' action='/case/{cid}/strategy' class='strategy-form' data-autosave='1'><div class='strategy-grid'>
              <div class='card'><label>Cel główny</label><textarea name='main_goal'>{sv('main_goal')}</textarea></div><div class='card'><label>Wariant minimum</label><textarea name='minimum_variant'>{sv('minimum_variant')}</textarea></div>
              <div class='card'><label>Stanowisko przeciwnika</label><textarea name='opponent_position'>{sv('opponent_position')}</textarea></div><div class='card'><label>Nasze argumenty</label><textarea name='our_arguments'>{sv('our_arguments')}</textarea></div>
              <div class='card'><label>Argumenty przeciwnika</label><textarea name='opponent_arguments'>{sv('opponent_arguments')}</textarea></div><div class='card'><label>Nasza odpowiedź</label><textarea name='response_arguments'>{sv('response_arguments')}</textarea></div>
              <div class='card risk-card'><label>Ryzyka</label><textarea name='risks'>{sv('risks')}</textarea></div><div class='card'><label>Plan na rozprawę</label><textarea name='hearing_plan'>{sv('hearing_plan')}</textarea></div>
              <div class='card'><label>Wnioski do zgłoszenia</label><textarea name='motions_to_make'>{sv('motions_to_make')}</textarea></div><div class='card'><label>Pytania do świadków / stron</label><textarea name='witness_questions'>{sv('witness_questions')}</textarea></div>
              <div class='card'><label>Stanowisko ugodowe</label><textarea name='settlement_position'>{sv('settlement_position')}</textarea></div><div class='card'><label>Czego pilnować</label><textarea name='watchouts'>{sv('watchouts')}</textarea></div>
              <div class='full'><button class='btn primary'{ro_disabled}>Zapisz strategię</button> <a class='btn' href='/case/{cid}?tab=hearing'>Wygeneruj kartę rozprawy</a></div></div></form>"""
            content=f"<section class='case-tab-content'><div class='section-head'><div><h2>Strategia sprawy</h2><div class='muted'>Plan pracy, nie zwykła notatka.</div></div></div>{form}</section>"

        elif tab=='hearing':
            strat=dict(strategy) if strategy else {}
            hearing_date=''
            hearing_title=''
            for p in sorted(process_events,key=lambda x:x['event_date'] or '9999-99-99'):
                low=(str(p['event_type'])+' '+str(p['title'])).lower()
                if p['event_date'] and p['event_date']>=date.today().isoformat() and ('rozpraw' in low or 'posiedzen' in low or 'mediac' in low):
                    hearing_date=p['event_date']; hearing_title=p['title']; break
            claim_total=sum(int(x['principal_cents'] or 0)+int(x['interest_cents'] or 0)+int(x['costs_cents'] or 0) for x in claims)
            key_evidence=''.join(f"<li><b>{esc(a['statement'])}</b> — {esc(a['status'])}</li>" for a in assertions[:8]) or '<li>Brak mapy dowodów.</li>'
            law=' · '.join(f"{x['code']}{(' art. '+str(x['article_key'])) if x['article_key'] else ''}" for x in law_links) or '—'
            def block(title,name,fallback='—'):
                return f"<section class='hearing-block'><h3>{title}</h3><div class='workspace-pre'>{esc(strat.get(name) or fallback)}</div></section>"
            content=f"""<section class='case-tab-content hearing-sheet'><div class='hearing-toolbar'><div><h2>Karta rozprawy</h2><div class='muted'>Jedna strona robocza generowana z danych sprawy.</div></div><button class='btn primary' type='button' onclick='window.print()'>Drukuj / PDF</button></div>
              <div class='hearing-title'><b>{esc(primary)}</b><h1>{esc(c['title'])}</h1><p>{esc(party_line)}</p><p><b>Termin:</b> {fmt_date(hearing_date)} {esc(hearing_title)}</p></div>
              <div class='hearing-columns'>{block('Cel główny','main_goal')}{block('Wariant minimum','minimum_variant')}{block('Plan na rozprawę','hearing_plan')}{block('Stanowisko ugodowe','settlement_position')}</div>
              <section class='hearing-block'><h3>Żądania / roszczenia</h3><p><b>Łącznie:</b> {fmt_money(claim_total)}</p><ul>{''.join(f'<li>{esc(x["title"])} — {fmt_money(x["principal_cents"],x["currency"])}</li>' for x in claims) or '<li>Brak rejestru roszczeń.</li>'}</ul></section>
              <section class='hearing-block'><h3>Kluczowe twierdzenia i dowody</h3><ul>{key_evidence}</ul></section>
              <div class='hearing-columns'>{block('Wnioski do zgłoszenia','motions_to_make')}{block('Pytania do świadków / stron','witness_questions')}{block('Ryzyka','risks')}{block('Czego pilnować','watchouts')}</div>
              <section class='hearing-block'><h3>Podstawy prawne</h3><p>{esc(law)}</p></section></section>"""

        elif tab=='finances':
            totals={k:sum(int(x[k] or 0) for x in claims) for k in ('principal_cents','interest_cents','costs_cents','paid_cents','awarded_cents','settlement_cents')}
            rows=[]
            for x in claims:
                rows.append(f"<details class='claim-row'><summary><span><b>{esc(x['title'])}</b><small>{esc(x['claim_type'])} · {esc(x['status'])}</small></span><strong>{fmt_money(x['principal_cents'],x['currency'])}</strong></summary><form method='post' action='/claim/{x['id']}/update' class='form-grid'><div><label>Tytuł</label><input name='title' value='{esc(x['title'])}'></div><div><label>Rodzaj</label><input name='claim_type' value='{esc(x['claim_type'])}'></div><div><label>Kwota główna</label><input name='principal' value='{money_input(x['principal_cents'])}'></div><div><label>Odsetki</label><input name='interest' value='{money_input(x['interest_cents'])}'></div><div><label>Koszty</label><input name='costs' value='{money_input(x['costs_cents'])}'></div><div><label>Spełniono</label><input name='paid' value='{money_input(x['paid_cents'])}'></div><div><label>Zasądzono</label><input name='awarded' value='{money_input(x['awarded_cents'])}'></div><div><label>Propozycja ugodowa</label><input name='settlement' value='{money_input(x['settlement_cents'])}'></div><div><label>Waluta</label><input name='currency' value='{esc(x['currency'])}'></div><div><label>Status</label><select name='status'>{''.join(f'<option {"selected" if x["status"]==s else ""}>{s}</option>' for s in ['dochodzone','częściowo spełnione','spełnione','zasądzone','oddalone'])}</select></div><div class='full'><label>Notatka</label><textarea name='notes'>{esc(x['notes'])}</textarea></div><div class='full'><button class='btn primary'>Zapisz</button> <button class='btn danger' formaction='/claim/{x['id']}/delete' onclick=\"return confirm('Archiwizować tę pozycję?');\">Archiwizuj</button></div></form></details>")
            add='' if readonly else f"""<details class='card smart-add'><summary>+ Dodaj roszczenie / propozycję</summary><form method='post' action='/case/{cid}/claim' class='form-grid'><div><label>Tytuł</label><input name='title' required></div><div><label>Rodzaj</label><select name='claim_type'><option>Roszczenie główne</option><option>Odsetki</option><option>Koszty</option><option>Propozycja ugodowa</option><option>Częściowe spełnienie</option></select></div><div><label>Kwota główna</label><input name='principal' inputmode='decimal'></div><div><label>Odsetki</label><input name='interest' inputmode='decimal'></div><div><label>Koszty</label><input name='costs' inputmode='decimal'></div><div><label>Spełniono</label><input name='paid' inputmode='decimal'></div><div><label>Zasądzono</label><input name='awarded' inputmode='decimal'></div><div><label>Propozycja ugodowa</label><input name='settlement' inputmode='decimal'></div><div><label>Waluta</label><input name='currency' value='PLN'></div><div><label>Status</label><select name='status'><option>dochodzone</option><option>częściowo spełnione</option><option>spełnione</option><option>zasądzone</option><option>oddalone</option></select></div><div class='full'><label>Notatka</label><textarea name='notes'></textarea></div><div class='full'><button class='btn primary'>Dodaj</button></div></form></details>"""
            content=f"<section class='case-tab-content'><div class='section-head'><div><h2>Roszczenia i finanse sprawy</h2><div class='muted'>Kwoty główne, odsetki, koszty, spełnienia, wyroki i ugody.</div></div></div><div class='workspace-kpi-grid money-grid'><div class='workspace-kpi'><span>Żądanie główne</span><b>{fmt_money(totals['principal_cents'])}</b></div><div class='workspace-kpi'><span>Odsetki i koszty</span><b>{fmt_money(totals['interest_cents']+totals['costs_cents'])}</b></div><div class='workspace-kpi'><span>Spełniono / zasądzono</span><b>{fmt_money(totals['paid_cents']+totals['awarded_cents'])}</b></div><div class='workspace-kpi'><span>Propozycje ugodowe</span><b>{fmt_money(totals['settlement_cents'])}</b></div></div>{add}<div class='claim-list'>{''.join(rows) or '<div class="empty">Brak pozycji finansowych.</div>'}</div></section>"

        elif tab=='people':
            rows=[]
            for x in entities:
                ids=' · '.join(v for v in (('PESEL '+x['pesel']) if x['pesel'] else '',('NIP '+x['nip']) if x['nip'] else '',('KRS '+x['krs']) if x['krs'] else '') if v)
                rows.append(f"<tr><td><a class='case-link' href='/entity/{x['entity_id']}'>{esc(x['display_name'])}</a><div class='small muted'>{esc(ids)}</div></td><td>{esc(x['role'])}</td><td>{esc(x['notes'])}</td></tr>")
            for x in parties:
                rows.append(f"<tr><td><b>{esc(x['name'])}</b><div class='small muted'>wpis tylko w tej sprawie</div></td><td>{esc(x['role'])}</td><td>{esc(x['notes'])}</td></tr>")
            entity_opts='<option value="">— wybierz z kartoteki —</option>'+''.join(f"<option value='{x['id']}'>{esc(x['display_name'])}</option>" for x in all_entities)
            add='' if readonly else f"""<div class='grid workspace-add-grid'><details class='card span6 smart-add'><summary>+ Przypisz z kartoteki</summary><form method='post' action='/case/{cid}/entity' class='form-grid'><div class='full'><label>Osoba / podmiot</label><select name='entity_id' required>{entity_opts}</select></div><div><label>Rola</label><input name='role' value='Uczestnik'></div><div><label>Notatka</label><input name='notes'></div><div class='full'><button class='btn primary'>Przypisz</button></div></form></details><details class='card span6 smart-add'><summary>+ Szybki wpis w sprawie</summary><form method='post' action='/case/{cid}/party' class='form-grid'><div><label>Imię / nazwa</label><input name='name' required></div><div><label>Rola</label><input name='role'></div><div class='full'><label>Notatka</label><input name='notes'></div><div class='full'><button class='btn primary'>Dodaj</button></div></form></details></div>"""
            content=f"<section class='case-tab-content'><div class='section-head'><div><h2>Osoby i podmioty</h2><div class='muted'>Wspólna kartoteka umożliwia kontrolę konfliktu interesów.</div></div><a class='btn' href='/entities'>Kartoteka</a></div>{add}<div class='card table-scroll'><table><tr><th>Osoba / podmiot</th><th>Rola</th><th>Notatka</th></tr>{''.join(rows) or '<tr><td colspan=3>Brak osób.</td></tr>'}</table></div></section>"

        elif tab=='relations':
            relation_rows=[]
            for r in relations:
                labels=RELATION_TYPES.get(r['relation_type'],(r['relation_type'],r['relation_type']))
                outgoing=r['source_case_id']==cid
                other_id=r['target_case_id'] if outgoing else r['source_case_id']
                other_sig=r['target_signature'] if outgoing else r['source_signature']
                other_internal=r['target_internal'] if outgoing else r['source_internal']
                other_title=r['target_title'] if outgoing else r['source_title']
                other_status=r['target_status'] if outgoing else r['source_status']
                label=labels[0] if outgoing else labels[1]
                case_label=other_sig or other_internal or other_title
                actions=''
                if not readonly:
                    actions=(f"<a class='btn small' href='/relation/{r['id']}/edit'>Edytuj</a> "
                             f"<form method='post' action='/relation/{r['id']}/delete' class='inline' onsubmit=\"return confirm('Usunąć to powiązanie?');\">"
                             f"<input type='hidden' name='case_id' value='{cid}'><input type='hidden' name='return_to' value='/case/{cid}?tab=relations'>"
                             f"<button class='btn small danger'>Usuń powiązanie</button></form>")
                relation_rows.append(f"<tr><td><span class='pill'>{esc(label)}</span></td><td><a class='case-link' href='/case/{other_id}'>{esc(case_label)}</a><div class='small muted'>{esc(other_title)} · {esc(STATUS_LABELS.get(other_status,other_status))}</div></td><td>{esc(r['note']) or '—'}</td><td class='nowrap'>{actions}</td></tr>")
            relation_options=[]
            for other in relation_cases:
                label=other['signature'] or other['internal_signature'] or other['title']
                relation_options.append(f"<option value='{other['id']}'>{esc(label)} — {esc(other['title'])} ({esc(STATUS_LABELS.get(other['status'],other['status']))})</option>")
            type_options=''.join(f"<option value='{esc(key)}'>{esc(labels[0])}</option>" for key,labels in RELATION_TYPES.items())
            if readonly:
                add=''
            elif relation_options:
                add=f"""<details class='card smart-add' open><summary>+ Połącz z inną sprawą</summary><form method='post' action='/case/{cid}/relation' class='form-grid'><input type='hidden' name='return_to' value='/case/{cid}?tab=relations'><div><label>Rodzaj powiązania</label><select name='relation_type'>{type_options}</select></div><div><label>Druga sprawa</label><select name='target_case_id' required>{''.join(relation_options)}</select></div><div class='full'><label>Notatka</label><input name='note' placeholder='np. apelacja od wyroku w tej sprawie'></div><div class='full'><button class='btn primary'>Połącz sprawy</button></div></form></details>"""
            else:
                add="<div class='card empty'>Nie ma jeszcze drugiej sprawy, z którą można utworzyć powiązanie.</div>"
            content=f"<section class='case-tab-content'><div class='section-head'><div><h2>Powiązane sprawy</h2><div class='muted'>Połącz instancje, egzekucję albo inne sprawy dotyczące tego samego klienta lub zdarzenia.</div></div></div>{add}<div class='card table-scroll'><table><tr><th>Relacja</th><th>Sprawa</th><th>Notatka</th><th></th></tr>{''.join(relation_rows) or '<tr><td colspan=4>Brak powiązanych spraw.</td></tr>'}</table></div></section>"

        else:  # notes
            note_rows=''.join(f"<article class='note-card'><div class='workspace-pre'>{esc(x['note'])}</div><small>{esc(x['created_at'])} · {esc(x['author'])}</small></article>" for x in notes) or '<div class="empty">Brak notatek.</div>'
            add='' if readonly else f"""<div class='card'><form method='post' action='/case/{cid}/note'><label>Nowa notatka</label><textarea name='note' required></textarea><button class='btn primary'>Dodaj notatkę</button></form></div>"""
            content=f"<section class='case-tab-content'><div class='section-head'><div><h2>Notatki</h2><div class='muted'>Chronologiczne notatki robocze sprawy.</div></div></div>{add}<div class='note-grid'>{note_rows}</div></section>"

        self.send_html(layout(primary,readonly_html+header+content,'cases'))


    def case_view_simple(self, cid, qs=None):
        qs = qs or {}
        u = current_request_user()
        uid = u['id'] if u else None
        with db() as con:
            c = con.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
            if not c:
                return self.send_error(404)
            if uid:
                con.execute("""INSERT INTO user_case_recent(user_id,case_id,opened_at) VALUES(?,?,CURRENT_TIMESTAMP)
                               ON CONFLICT(user_id,case_id) DO UPDATE SET opened_at=CURRENT_TIMESTAMP""", (uid, cid))
            derive_case_auto_tags(con, cid)
            auto_create_structural_links(con, cid)
            summary = generate_case_summary(con, cid)
            parties = con.execute("SELECT role,name FROM parties WHERE case_id=? ORDER BY id", (cid,)).fetchall()
            structured = con.execute("""SELECT ce.role,e.display_name name FROM case_entities ce
                                        JOIN entities e ON e.id=ce.entity_id WHERE ce.case_id=? ORDER BY ce.id""", (cid,)).fetchall()
            shown_parties = structured or parties
            auto_tags = con.execute("SELECT tag,reason FROM case_auto_tags WHERE case_id=? ORDER BY tag COLLATE NOCASE", (cid,)).fetchall()
            manual_tags = con.execute("""SELECT t.name FROM case_tags ct JOIN tags t ON t.id=ct.tag_id
                                         WHERE ct.case_id=? ORDER BY t.name COLLATE NOCASE""", (cid,)).fetchall()
            timeline = build_unified_timeline(con, cid, 60)
            links = con.execute("SELECT * FROM smart_links WHERE case_id=? ORDER BY auto_created,id DESC", (cid,)).fetchall()
            labels = self._smart_label_map(con, cid)
            open_tasks = con.execute("""SELECT t.*,u.author_name assigned_name,u.function assigned_function
                                        FROM tasks t LEFT JOIN users u ON u.id=t.assigned_user_id
                                        WHERE t.case_id=? AND t.status<>'done'
                                        ORDER BY CASE WHEN t.due_date='' THEN 1 ELSE 0 END,t.due_date,t.id""",(cid,)).fetchall()
            alerts = con.execute("""SELECT * FROM alerts WHERE case_id=? AND status='open'
                                    AND NOT (source_type='task' AND source_id IS NOT NULL)
                                    ORDER BY alert_date,id LIMIT 12""", (cid,)).fetchall()
            suggestions = con.execute("""SELECT ds.*,d.title document_title FROM deadline_suggestions ds
                                         LEFT JOIN documents d ON d.id=ds.document_id
                                         WHERE ds.case_id=? AND ds.status='open' ORDER BY ds.id DESC""", (cid,)).fetchall()
            docs = con.execute("""SELECT id,title,doc_type,received_date,delivered_date,extracted_text
                                  FROM documents WHERE case_id=? AND COALESCE(parent_document_id,0)=0
                                  ORDER BY id DESC LIMIT 12""", (cid,)).fetchall()
            law_links = con.execute("""SELECT lcl.id,a.code,a.short_title,COALESCE(la.article_key,lcl.article_key_text) article_key,la.heading,lcl.note
                                       FROM law_case_links lcl JOIN law_acts a ON a.id=lcl.act_id
                                       LEFT JOIN law_articles la ON la.id=lcl.article_id
                                       WHERE lcl.case_id=? ORDER BY a.code,la.sort_order""", (cid,)).fetchall()
            law_acts = con.execute("SELECT id,code,short_title FROM law_acts ORDER BY code").fetchall()
            users = con.execute("SELECT id,author_name,function FROM users WHERE is_active=1 ORDER BY author_name").fetchall()
            readonly = bool(c['status'] == 'closed' and not int(c['closed_edit_unlocked'] or 0))

        shown_sig, sig_kind = display_case_signature(cid, c['signature'], c['internal_signature'])
        primary = shown_sig if shown_sig != 'Bez sygnatury' else (c['internal_signature'] or 'Bez sygnatury')
        party_html = ''.join(
            f"<span class='case-party'><b>{esc(r['role'])}</b>{': ' if r['role'] else ''}{esc(r['name'])}</span>"
            for r in shown_parties
        ) or "<span class='muted'>Nie dodano stron</span>"
        tags_html = ''.join(f"<span class='smart-tag auto' title='{esc(r['reason'])}'>{esc(r['tag'])}</span>" for r in auto_tags)
        tags_html += ''.join(f"<span class='smart-tag'>{esc(r['name'])}</span>" for r in manual_tags)
        if not tags_html:
            tags_html = "<span class='muted'>Brak tagów</span>"

        nearest = []
        seen_nearest=set()
        def add_nearest(d, kind, title):
            d=str(d or '').strip(); title=str(title or '').strip(); kind=str(kind or '').strip()
            if not d or not title: return
            key=(d,re.sub(r"\W+","",title.lower()))
            if key in seen_nearest: return
            seen_nearest.add(key); nearest.append((d,kind,title))
        for t in open_tasks:
            if t['due_date']:
                add_nearest(t['due_date'], row_get(t,'task_type','Zadanie') or 'Zadanie', t['title'])
        for a in alerts:
            add_nearest(a['alert_date'], a['alert_type'], a['title'])
        # Ogólna „najbliższa data” jest fallbackiem. Nie pokazujemy jej drugi raz,
        # jeżeli tego samego dnia jest już konkretny termin/zadanie/alert.
        if c['next_date'] and not any(x[0]==c['next_date'] for x in nearest):
            add_nearest(c['next_date'], 'Termin', c['next_step'] or c['title'])
        nearest = sorted(nearest, key=lambda x: x[0])[:5]
        nearest_html = ''.join(
            f"<div class='smart-date-row {'urgent' if d and d <= date.today().isoformat() else ''}'><span>{fmt_date(d)}</span><div><b>{esc(kind)}</b><small>{esc(title)}</small></div></div>"
            for d, kind, title in nearest
        ) or "<div class='empty'>Brak najbliższych terminów.</div>"

        task_rows=[]
        for t in open_tasks:
            assigned=''
            if t['assigned_name']:
                assigned=f"<span class='task-assignee'>{esc(t['assigned_name'])}</span>"
            due=f"<span class='task-due'>{fmt_date(t['due_date'])}</span>" if t['due_date'] else "<span class='task-due muted'>bez terminu</span>"
            task_rows.append(
                f"<div class='simple-task-row'><form method='post' action='/task/{t['id']}/toggle'>"
                f"<input type='hidden' name='case_id' value='{cid}'><input type='hidden' name='return_to' value='/case/{cid}'>"
                f"<button class='task-check' title='Oznacz jako wykonane'>✓</button></form>"
                f"<div class='simple-task-main'><div><span class='mini-badge'>{esc(row_get(t,'task_type','Zadanie') or 'Zadanie')}</span> <b>{esc(t['title'])}</b></div>"
                f"<div class='simple-task-meta'>{due}{assigned}</div></div>"
                f"<a class='btn small' href='/task/{t['id']}/edit?return_to=%2Fcase%2F{cid}'>Edytuj</a></div>"
            )
        tasks_html=''.join(task_rows) or "<div class='empty'>Brak otwartych zadań.</div>"
        user_opts='<option value="">— bez przypisania —</option>'+''.join(
            f"<option value='{x['id']}'>{esc(user_display_name(x))}</option>" for x in users
        )
        task_type_opts=''.join(f"<option>{esc(x)}</option>" for x in ["Zadanie","Monit","Termin procesowy","Płatność"])
        work_form='' if readonly else f"""<details class='smart-add'><summary>+ Dodaj zadanie / monit</summary>
        <form method='post' action='/case/{cid}/task' class='form-grid'>
          <input type='hidden' name='return_to' value='/case/{cid}'>
          <div><label>Rodzaj</label><select name='task_type'>{task_type_opts}</select></div>
          <div><label>Termin / data</label><input type='date' name='due_date'></div>
          <div class='full'><label>Co trzeba zrobić?</label><input name='title' required></div>
          <div><label>Wykonawca</label><select name='assigned_user_id'>{user_opts}</select></div>
          <div><label>Priorytet</label><select name='priority'><option value='normal'>Normalny</option><option value='high'>Wysoki</option></select></div>
          <div class='full'><label>Notatka</label><input name='notes'></div>
          <div class='full'><button class='btn primary'>Dodaj</button></div>
        </form></details>"""

        # Czytelna historia grupowana według dnia. Zadania i alerty są poza historią.
        grouped={}
        for x in timeline:
            grouped.setdefault(x['date'] or '',[]).append(x)
        day_parts=[]
        for d in sorted(grouped.keys(), reverse=True):
            rows=[]
            for x in grouped[d]:
                desc=(x.get('description') or '').strip()
                if len(desc)>170: desc=desc[:167]+'…'
                desc_html=f"<small>{esc(desc)}</small>" if desc else ''
                att=''
                if int(x.get('attachment_count') or 0):
                    att=f"<span class='attachment-count'>📎 {int(x['attachment_count'])}</span>"
                href=f"/document/{x['source_id']}/open" if x['source_type']=='document' else f"/case/{cid}?mode=advanced"
                rows.append(f"<a class='timeline-clean-row' href='{href}'><span class='timeline-clean-kind'>{esc(x['kind'])}</span><div><b>{esc(x['title'])}</b>{desc_html}</div>{att}</a>")
            day_parts.append(f"<div class='timeline-day'><div class='timeline-day-date'>{fmt_date(d)}</div><div class='timeline-day-items'>{''.join(rows)}</div></div>")
        timeline_html=''.join(day_parts) or "<div class='empty'>Brak historii sprawy.</div>"

        relation_rows=[]
        for r in links:
            sl=labels.get((r['source_type'],r['source_id']),f"{r['source_type']} #{r['source_id']}")
            tl=labels.get((r['target_type'],r['target_id']),f"{r['target_type']} #{r['target_id']}")
            auto="<span class='mini-badge'>AUTO</span>" if r['auto_created'] else ''
            delete='' if readonly else f"<form method='post' action='/smart-link/{r['id']}/delete' class='inline'><input type='hidden' name='return_to' value='/case/{cid}#relations'><button class='btn small danger'>×</button></form>"
            relation_rows.append(f"<div class='smart-relation'><span>{esc(sl)}</span><b>{esc(r['relation_type'])}</b><span>{esc(tl)}</span>{auto}{delete}</div>")
        relations_html=''.join(relation_rows) or "<div class='empty'>Brak zapisanych powiązań.</div>"
        item_opts=''.join(f"<option value='{esc(t)}:{i}'>{esc(label)}</option>" for (t,i),label in sorted(labels.items(),key=lambda z:z[1].lower()))
        relation_type_opts=''.join(f"<option>{esc(x)}</option>" for x in SMART_RELATION_TYPES)
        relation_form='' if readonly else f"""<details class='smart-add'><summary>+ Dodaj powiązanie</summary><form method='post' action='/case/{cid}/smart-link' class='form-grid'><div><label>Z czego</label><select name='source' required><option value=''>— wybierz —</option>{item_opts}</select></div><div><label>Relacja</label><select name='relation_type'>{relation_type_opts}</select></div><div><label>Z czym</label><select name='target' required><option value=''>— wybierz —</option>{item_opts}</select></div><div class='full'><button class='btn primary'>Dodaj</button></div></form></details>"""

        suggestions_html=''.join(
            f"<div class='deadline-suggestion'><b>{esc(sg['suggested_title'])}</b><div class='small'>{esc(sg['source_text'])}</div><form method='post' action='/deadline-suggestion/{sg['id']}/accept'><input type='hidden' name='return_to' value='/case/{cid}#deadlines'><button class='btn primary small'>Zatwierdź</button></form></div>"
            for sg in suggestions
        ) or "<div class='empty'>Brak terminów do zatwierdzenia.</div>"
        doc_scan=''.join(
            f"<form method='post' action='/document/{d['id']}/suggest-deadlines' class='doc-scan-row'><input type='hidden' name='return_to' value='/case/{cid}#deadlines'><span><b>{esc(d['title'])}</b><small>{esc(d['doc_type'])}</small></span><button class='btn small'>Sprawdź</button></form>"
            for d in docs
        )
        law_html=''.join(
            f"<div class='law-link'><a href='/law/{esc(r['code'])}?q={quote(str(r['article_key'] or ''))}'><b>{esc(r['code'])}{(' · art. '+esc(r['article_key'])) if r['article_key'] else ''}</b></a><span>{esc(r['short_title'])}</span></div>"
            for r in law_links
        ) or "<div class='empty'>Brak przypiętych przepisów.</div>"
        law_act_opts=''.join(f"<option value='{esc(r['code'])}'>{esc(r['code'])} — {esc(r['short_title'])}</option>" for r in law_acts)
        law_form='' if readonly else f"""<details class='smart-add'><summary>+ Przypnij przepis</summary><form method='post' action='/case/{cid}/law-link' class='form-grid'><div><label>Akt</label><select name='code'>{law_act_opts}</select></div><div><label>Artykuł</label><input name='article_key' placeholder='np. 317'></div><div class='full'><button class='btn primary'>Przypnij</button></div></form></details>"""

        readonly_note="<div class='readonly-banner'>Sprawa zakończona — widok tylko do odczytu.</div>" if readonly else ''
        body=f"""{readonly_note}<div class='case-mode-switch'><a class='btn primary' href='/case/{cid}?mode=simple'>Widok prosty</a><a class='btn' href='/case/{cid}?mode=advanced'>Widok zaawansowany</a><a class='btn' href='/case/{cid}/edit'>Edytuj</a></div>
        <section class='smart-case-hero'>
          <div class='case-signature-label'>{esc(sig_kind or 'Sygnatura')}</div><h1>{esc(primary)}</h1>
          <div class='case-parties'>{party_html}</div>
          <h2>{esc(c['title'])}</h2><div class='case-subject'>{esc(c['subject']) or 'Brak opisu przedmiotu sprawy'}</div>
          <div class='smart-tags'>{tags_html}</div>
        </section>
        <div class='smart-summary-grid simple-three'>
          <div class='card smart-summary-card'><div class='section-kicker'>O SPRAWIE</div><p>{esc(summary['description'])}</p></div>
          <div class='card smart-summary-card'><div class='section-kicker'>ETAP</div><p>{esc(summary['stage'])}</p></div>
          <div class='card smart-summary-card'><div class='section-kicker'>NAJBLIŻSZE</div>{nearest_html}<a class='smart-more' href='/calendar?case_id={cid}'>Kalendarz →</a></div>
        </div>
        <section class='card simple-tasks-card'><div class='section-head'><div><div class='section-kicker'>DO ZROBIENIA</div><h2>Otwarte zadania</h2></div><a class='btn small' href='/tasks?show=open'>Wszystkie zadania</a></div>{tasks_html}{work_form}</section>
        <div class='smart-case-layout'>
          <section class='card smart-main'><div class='section-head'><div><div class='section-kicker'>HISTORIA SPRAWY</div><h2>Co już się wydarzyło</h2></div><a class='btn small' href='/case/{cid}?mode=advanced'>Pełna historia</a></div><div class='timeline-clean'>{timeline_html}</div></section>
          <aside class='smart-side compact-side'>
            <details class='card smart-collapsible' id='relations'><summary><b>Co z czego wynika</b><span>{len(links)}</span></summary><div class='smart-collapsible-body'>{relations_html}{relation_form}</div></details>
            <details class='card smart-collapsible' id='deadlines'><summary><b>Terminy z dokumentów</b><span>{len(suggestions)}</span></summary><div class='smart-collapsible-body'><div class='notice subtle'>Program tylko podpowiada jawny termin. Niczego nie tworzy bez zatwierdzenia.</div>{suggestions_html}<details><summary>Sprawdź dokumenty</summary>{doc_scan or '<div class="empty">Brak dokumentów.</div>'}</details></div></details>
            <details class='card smart-collapsible' id='law'><summary><b>Podstawy prawne</b><span>{len(law_links)}</span></summary><div class='smart-collapsible-body'><a class='btn small' href='/law?case_id={cid}'>Otwórz bibliotekę</a>{law_html}{law_form}</div></details>
          </aside>
        </div>"""
        self.send_html(layout(primary,body,'cases'))

    def calendar_page(self, qs):
        raw = (qs.get('month') or [date.today().strftime('%Y-%m')])[0]
        try:
            first = datetime.strptime(raw, '%Y-%m').date().replace(day=1)
        except ValueError:
            first = date.today().replace(day=1)
        prev = (first - timedelta(days=1)).replace(day=1)
        nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        days_in = pycalendar.monthrange(first.year, first.month)[1]
        last = first.replace(day=days_in)
        start = first - timedelta(days=first.weekday())
        end = last + timedelta(days=(6 - last.weekday()))
        case_filter = 0
        try:
            case_filter = int((qs.get('case_id') or ['0'])[0] or 0)
        except ValueError:
            pass
        with db() as con:
            params = [start.isoformat(), end.isoformat()] + ([case_filter] if case_filter else [])
            alerts = con.execute(
                f"SELECT a.*,c.title case_title,c.signature,c.internal_signature FROM alerts a LEFT JOIN cases c ON c.id=a.case_id WHERE a.status='open' AND a.alert_date BETWEEN ? AND ?{' AND a.case_id=?' if case_filter else ''}", params
            ).fetchall()
            tasks = con.execute(
                f"""SELECT t.*,c.title case_title,c.signature,c.internal_signature FROM tasks t
                     JOIN cases c ON c.id=t.case_id
                     WHERE t.status<>'done' AND t.due_date BETWEEN ? AND ?
                     AND NOT EXISTS (SELECT 1 FROM alerts ax WHERE ax.source_type='task' AND ax.source_id=t.id AND ax.status='open')
                     {' AND t.case_id=?' if case_filter else ''}""", params
            ).fetchall()
            process = con.execute(
                f"SELECT p.*,c.title case_title,c.signature,c.internal_signature FROM process_events p JOIN cases c ON c.id=p.case_id WHERE (p.event_date BETWEEN ? AND ? OR p.next_date BETWEEN ? AND ?){' AND p.case_id=?' if case_filter else ''}",
                [start.isoformat(),end.isoformat(),start.isoformat(),end.isoformat()] + ([case_filter] if case_filter else [])
            ).fetchall()
            work_events = con.execute(
                f"SELECT e.*,c.title case_title,c.signature,c.internal_signature FROM events e JOIN cases c ON c.id=e.case_id WHERE e.event_date BETWEEN ? AND ?{' AND e.case_id=?' if case_filter else ''}", params
            ).fetchall()
            case_dates = con.execute(
                f"SELECT id,next_date,title,signature,internal_signature,next_step FROM cases WHERE next_date BETWEEN ? AND ?{' AND id=?' if case_filter else ''}", params
            ).fetchall()
            cases = con.execute("SELECT id,title,signature,internal_signature FROM cases WHERE status<>'closed' ORDER BY signature='',signature,title").fetchall()
            users = con.execute("SELECT id,author_name,function FROM users WHERE is_active=1 ORDER BY author_name").fetchall()
        bydate = {}; seen_calendar=set()
        def add_item(d, kind, title, cid=0, priority='normal'):
            if not d: return
            norm=re.sub(r'\W+','',str(title or '').lower())
            key=(str(d),int(cid or 0),norm)
            if key in seen_calendar: return
            seen_calendar.add(key)
            bydate.setdefault(d, []).append((kind, title, cid, priority))
        for r in alerts:
            add_item(r['alert_date'], r['alert_type'], r['title'], r['case_id'] or 0, r['priority'])
        for r in tasks:
            add_item(r['due_date'], 'Zadanie', r['title'], r['case_id'], r['priority'])
        for r in process:
            if r['event_date']:
                add_item(r['event_date'], r['event_type'] or 'Proces', r['title'], r['case_id'], 'normal')
            if r['next_date'] and r['next_date'] != r['event_date']:
                add_item(r['next_date'], 'Następny termin', r['title'], r['case_id'], 'high')
        for r in work_events:
            add_item(r['event_date'], r['event_type'] or 'Czynność', r['title'], r['case_id'], 'normal')
        for r in case_dates:
            # Pole ogólne w sprawie jest tylko fallbackiem. Jeżeli tego dnia mamy już
            # konkretną rozprawę, zadanie, mediację itp., nie dokładamy drugiego wpisu.
            already=any(int(item[2] or 0)==int(r['id']) for item in bydate.get(r['next_date'],[]))
            if not already:
                add_item(r['next_date'], 'Termin', r['next_step'] or r['title'], r['id'], 'high')
        cells = []
        cur = start
        while cur <= end:
            items = bydate.get(cur.isoformat(), [])
            event_parts = []
            for kind, title, cid, pr in items[:5]:
                content = f"<b>{esc(kind)}</b><span>{esc(title)}</span>"
                event_parts.append(f"<a class='calendar-event p-{esc(pr)}' href='/case/{cid}'>{content}</a>" if cid else f"<div class='calendar-event p-{esc(pr)}'>{content}</div>")
            more = f"<div class='small muted'>+{len(items)-5} więcej</div>" if len(items) > 5 else ''
            cls = ' outside' if cur.month != first.month else ''
            cls += ' today' if cur == date.today() else ''
            cells.append(f"<div class='calendar-day{cls}'><div class='calendar-day-num'>{cur.day}</div>{''.join(event_parts)}{more}</div>")
            cur += timedelta(days=1)
        case_opts = '<option value="">Wszystkie sprawy</option>' + ''.join(
            f"<option value='{r['id']}' {'selected' if case_filter == r['id'] else ''}>{esc((r['signature'] or r['internal_signature'] or 'Bez sygnatury') + ' — ' + r['title'])}</option>" for r in cases
        )
        type_opts = ''.join(f"<option>{esc(x)}</option>" for x in ALERT_TYPES)
        prio_opts = ''.join(f"<option value='{x}'>{esc(x)}</option>" for x in ALERT_PRIORITIES)
        user_opts = '<option value="">— bez przypisania —</option>' + ''.join(
            f"<option value='{u['id']}'>{esc(user_display_name(u))}</option>" for u in users
        )
        cf = f"&case_id={case_filter}" if case_filter else ''
        body = f"""<div class='topbar'><div><h1>Kalendarz kancelarii</h1><div class='sub'>Rozprawy, terminy, zadania, monity i alerty w jednym miejscu.</div></div><div><a class='btn' href='/calendar?month={prev.strftime('%Y-%m')}{cf}'>←</a> <b class='calendar-month-title'>{first.strftime('%m.%Y')}</b> <a class='btn' href='/calendar?month={nxt.strftime('%Y-%m')}{cf}'>→</a></div></div>
        <div class='card'><form method='get' action='/calendar' class='form-grid compact-form'><input type='hidden' name='month' value='{first.strftime('%Y-%m')}'><div class='full'><label>Filtr sprawy</label><select name='case_id' onchange='this.form.submit()'>{case_opts}</select></div></form></div>
        <section class='calendar-board'><div class='calendar-weekdays'>{''.join(f'<div>{x}</div>' for x in ['Pon','Wt','Śr','Czw','Pt','Sob','Niedz'])}</div><div class='calendar-grid'>{''.join(cells)}</div></section>
        <div class='card'><h2>Dodaj wpis</h2><div class='small muted' style='margin-bottom:10px'>Monit, zadanie, termin procesowy i płatność utworzą automatycznie powiązane zadanie. Rozprawa, posiedzenie i mediacja pozostaną wpisem kalendarza.</div><form method='post' action='/alert/create' class='form-grid'><input type='hidden' name='return_to' value='/calendar?month={first.strftime('%Y-%m')}'><div><label>Sprawa</label><select name='case_id'>{case_opts}</select></div><div><label>Data *</label><input type='date' name='alert_date' required></div><div><label>Rodzaj</label><select name='alert_type'>{type_opts}</select></div><div><label>Priorytet</label><select name='priority'>{prio_opts}</select></div><div class='full'><label>Nazwa *</label><input name='title' required></div><div><label>Wykonawca</label><select name='assigned_user_id'>{user_opts}</select></div><div class='full'><label>Opis</label><textarea name='description'></textarea></div><div class='full'><button class='btn primary'>Dodaj</button></div></form></div>"""
        self.send_html(layout('Kalendarz', body, 'calendar'))

    def law_page(self, qs, code=''):
        code = (code or (qs.get('code') or [''])[0]).upper().strip()
        q = (qs.get('q') or [''])[0].strip()
        case_id = 0
        try:
            case_id = int((qs.get('case_id') or ['0'])[0] or 0)
        except ValueError:
            pass
        with db() as con:
            acts = con.execute("SELECT a.*,(SELECT COUNT(*) FROM law_articles la WHERE la.act_id=a.id) article_count FROM law_acts a ORDER BY a.code").fetchall()
            results = search_law(con, q, code, 120) if (q or code) else []
        card_parts=[]
        for a in acts:
            count=int(a['article_count'] or 0)
            empty_cls=' needs-download' if count==0 else ''
            status=(f"<span class='law-status'>{count} art. lokalnie</span>" if count else "<span class='law-status empty'>Nie pobrano tekstu</span>")
            open_btn=(f"<a class='btn small' href='/law/{esc(a['code'])}'>Otwórz</a> " if count else '')
            update_label='Pobierz z ELI' if count==0 else 'Aktualizuj z ELI'
            card_parts.append(f"<div class='law-card{empty_cls}'><div><b>{esc(a['code'])}</b><h3>{esc(a['short_title'])}</h3><div>{status}</div><div class='small muted'>{esc(a['display_address'])} · sprawdzono: {esc(a['last_checked_at'] or 'nigdy')}</div></div><div>{open_btn}<form method='post' action='/law/{esc(a['code'])}/update' class='inline'><input type='hidden' name='return_to' value='/law/{esc(a['code'])}'><button class='btn small primary'>{update_label}</button></form></div></div>")
        cards=''.join(card_parts)
        result_parts = []
        for r in results:
            link_form = ''
            if case_id:
                link_form = f"<form method='post' action='/case/{case_id}/law-link' class='inline'><input type='hidden' name='code' value='{esc(r['code'])}'><input type='hidden' name='article_key' value='{esc(r['article_key'])}'><input type='hidden' name='return_to' value='/law/{esc(r['code'])}?q={quote(q)}&case_id={case_id}'><button class='btn small primary'>Przypnij do sprawy</button></form>"
            result_parts.append(f"<article class='law-article'><div class='section-head'><div><span class='smart-tag'>{esc(r['code'])}</span><h3>{esc(r['heading'])}</h3></div>{link_form}</div><pre>{esc(r['body'])}</pre></article>")
        result_html = ''.join(result_parts) or ("<div class='empty'>Brak wyników. Jeśli akt ma 0 artykułów lokalnie, użyj „Aktualizuj z ELI”.</div>" if (q or code) else '')
        body = f"""<div class='topbar'><div><h1>Biblioteka prawa</h1><div class='sub'>Kliknij „Pobierz z ELI”. Program zapisze tekst lokalnie i potem możesz go przeszukiwać bez ponownego pobierania.</div></div></div>
        <div class='notice'><b>Ważne:</b> biblioteka nie ustala sama skutków procesowych ani terminów. Przepisy są materiałem pomocniczym; aktualność i właściwą podstawę prawną weryfikuje użytkownik.</div>
        <div class='law-grid'>{cards}</div>
        <div class='card'><form method='get' action='/law/{esc(code)}' class='form-grid'><input type='hidden' name='case_id' value='{case_id or ''}'><div class='full'><label>Szukaj w {esc(code or 'wszystkich aktach')}</label><input name='q' value='{esc(q)}' placeholder='np. 317 albo rygor natychmiastowej wykonalności'></div><div class='full'><button class='btn primary'>Szukaj</button></div></form></div>{result_html}
        <details class='card'><summary>+ Dodaj inny akt z ELI</summary><form method='post' action='/law/add-eli' class='form-grid'><div><label>Kod roboczy</label><input name='code' placeholder='np. UKSC' required></div><div><label>Rok Dz.U.</label><input type='number' name='year' required></div><div><label>Pozycja</label><input type='number' name='position' required></div><div class='full'><label>Nazwa</label><input name='short_title' required></div><div class='full'><button class='btn primary'>Pobierz z ELI</button></div></form></details>"""
        self.send_html(layout('Prawo', body, 'law'))


    def alert_create(self, f):
        title = (f.get('title') or '').strip()
        d = (f.get('alert_date') or '').strip()
        if not title or not d:
            return self.redirect(f.get('return_to') or '/calendar')
        try: cid = int(f.get('case_id') or 0) or None
        except ValueError: cid = None
        try: assigned = int(f.get('assigned_user_id') or 0) or None
        except ValueError: assigned = None
        a = self.current_author(f)
        typ = (f.get('alert_type') or 'Inne').strip()
        pr = (f.get('priority') or 'normal').strip()
        if typ not in ALERT_TYPES: typ = 'Inne'
        if pr not in ALERT_PRIORITIES: pr = 'normal'
        with db() as con:
            cur = con.execute("""INSERT INTO alerts(case_id,alert_date,alert_type,title,description,priority,status,
                                 assigned_user_id,created_by) VALUES(?,?,?,?,?,?,'open',?,?)""",
                              (cid,d,typ,title,(f.get('description') or '').strip(),pr,assigned,a))
            task_id = sync_alert_task(con,cur.lastrowid,a)
            if task_id:
                sync_task_alert(con,task_id,a)
            if cid:
                extra = "\nUtworzono powiązane zadanie." if task_id else ""
                audit(con,cid,'alert',cur.lastrowid,'Dodano alert',f"{typ}: {_change_value(title)}\nData: {_change_value(d)}{extra}",a)
        target = (f.get('return_to') or '/calendar').strip()
        self.redirect(target if target.startswith('/') else '/calendar')


    def alert_toggle(self, aid, f):
        a=self.current_author(f)
        with db() as con:
            r = con.execute("SELECT * FROM alerts WHERE id=?", (aid,)).fetchone()
            if not r:
                return self.send_error(404)
            status = 'done' if r['status'] == 'open' else 'open'
            con.execute("UPDATE alerts SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, aid))
            if r['source_type']=='task' and r['source_id']:
                completed_at='' if status=='open' else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                completed_by='' if status=='open' else a
                con.execute("UPDATE tasks SET status=?,completed_at=?,completed_by=?,updated_by=? WHERE id=?",
                            (status,completed_at,completed_by,a,r['source_id']))
        self.redirect(f.get('return_to') or '/calendar')

    def alert_delete(self, aid, f):
        a=self.current_author(f)
        with db() as con:
            r=con.execute("SELECT * FROM alerts WHERE id=?", (aid,)).fetchone()
            if r and r['source_type']=='task' and r['source_id']:
                # Zadanie i jego wpis w kalendarzu są jednym elementem roboczym.
                move_to_trash(con,'task',int(r['source_id']),a)
            con.execute("DELETE FROM alerts WHERE id=?", (aid,))
        self.redirect(f.get('return_to') or '/calendar')

    def smart_link_add(self, cid, f):
        def parse_item(v):
            t, raw = (v or '').split(':', 1)
            return t, int(raw)
        try:
            st, si = parse_item(f.get('source'))
            tt, ti = parse_item(f.get('target'))
        except Exception:
            return self.redirect(f'/case/{cid}#relations')
        if st == tt and si == ti:
            return self.redirect(f'/case/{cid}#relations')
        rel = (f.get('relation_type') or 'powiązane z').strip()
        rel = rel if rel in SMART_RELATION_TYPES else 'powiązane z'
        with db() as con:
            con.execute("INSERT OR IGNORE INTO smart_links(case_id,source_type,source_id,target_type,target_id,relation_type,note,auto_created,created_by) VALUES(?,?,?,?,?,?,?,?,?)", (cid, st, si, tt, ti, rel, (f.get('note') or '').strip(), 0, self.current_author(f)))
        self.redirect(f'/case/{cid}#relations')

    def smart_link_delete(self, lid, f):
        with db() as con:
            r = con.execute("SELECT case_id FROM smart_links WHERE id=?", (lid,)).fetchone()
            con.execute("DELETE FROM smart_links WHERE id=?", (lid,))
        self.redirect(f.get('return_to') or (f"/case/{r['case_id']}#relations" if r else '/cases'))

    def law_update(self, code, f):
        try:
            with db() as con:
                update_law_from_eli(con, code)
        except Exception as exc:
            return self.send_html(layout('Aktualizacja prawa', f"<div class='card friendly-error'><h1>Nie udało się zaktualizować {esc(code)}</h1><p>{esc(exc)}</p><p>Dotychczasowa lokalna wersja nie została usunięta.</p><a class='btn' href='/law/{esc(code)}'>Wróć</a></div>", 'law'), 502)
        target = (f.get('return_to') or f'/law/{code}').strip()
        self.redirect(target if target.startswith('/') else f'/law/{code}')

    def law_add_eli(self, f):
        try:
            code = (f.get('code') or '').strip().upper()
            year = int(f.get('year') or 0)
            pos = int(f.get('position') or 0)
            with db() as con:
                add_custom_eli_act(con, code, year, pos, (f.get('short_title') or '').strip(), self.current_author(f))
        except Exception as exc:
            return self.send_html(layout('Dodawanie aktu', f"<div class='card friendly-error'><h1>Nie udało się pobrać aktu</h1><p>{esc(exc)}</p><a class='btn' href='/law'>Wróć</a></div>", 'law'), 502)
        self.redirect(f'/law/{code}')

    def case_law_link_add(self, cid, f):
        code = (f.get('code') or '').strip().upper()
        key = (f.get('article_key') or '').strip().replace('art.', '').replace('Art.', '').strip().rstrip('.')
        with db() as con:
            act = con.execute("SELECT id FROM law_acts WHERE code=?", (code,)).fetchone()
            if not act:
                return self.redirect(f'/case/{cid}#law')
            article = con.execute("SELECT id FROM law_articles WHERE act_id=? AND article_key=?", (act['id'], key)).fetchone() if key else None
            con.execute("INSERT OR IGNORE INTO law_case_links(case_id,act_id,article_id,article_key_text,note,created_by) VALUES(?,?,?,?,?,?)", (cid, act['id'], article['id'] if article else None, key, (f.get('note') or '').strip(), self.current_author(f)))
        target = f.get('return_to') or f'/case/{cid}#law'
        self.redirect(target if target.startswith('/') else f'/case/{cid}#law')

    def case_law_link_delete(self, lid, f):
        with db() as con:
            r = con.execute("SELECT case_id FROM law_case_links WHERE id=?", (lid,)).fetchone()
            con.execute("DELETE FROM law_case_links WHERE id=?", (lid,))
        self.redirect(f.get('return_to') or (f"/case/{r['case_id']}#law" if r else '/cases'))

    def document_deadline_suggest(self, did, f):
        with db() as con:
            d = con.execute("SELECT * FROM documents WHERE id=?", (did,)).fetchone()
            if not d:
                return self.send_error(404)
            cid = d['case_id']
            text = str(row_get(d, 'extracted_text', '') or '')
        target = f.get('return_to') or f'/case/{cid}#deadlines'
        if not text:
            enqueue_document_index(did)
            return self.send_html(layout('Analiza terminu', f"<div class='card'><h1>Dokument jest indeksowany</h1><p>Najpierw program musi odczytać tekst dokumentu. Nie utworzono żadnego terminu automatycznie.</p><a class='btn primary' href='{esc(target)}'>Wróć do sprawy</a></div>", 'cases'))
        with db() as con:
            found = extract_explicit_deadline_suggestions(con, did)
        if not found:
            return self.send_html(layout('Analiza terminu', f"<div class='card'><h1>Nie wykryto jawnego terminu</h1><p>Program nie znalazł w odczytanej treści sformułowania typu „w terminie X dni”. Nie utworzono terminu i nie zastosowano żadnego domyślnego okresu.</p><a class='btn primary' href='{esc(target)}'>Wróć</a></div>", 'cases'))
        self.redirect(target)


    def deadline_suggestion_accept(self, sid, f):
        with db() as con:
            sg = con.execute("SELECT * FROM deadline_suggestions WHERE id=? AND status='open'", (sid,)).fetchone()
            if not sg:
                return self.send_error(404)
            if not sg['base_date'] or sg['days'] is None:
                return self.send_html(layout('Termin wymaga danych', "<div class='card'><h1>Brakuje daty początkowej</h1><p>Uzupełnij datę doręczenia/wpływu dokumentu przed utworzeniem terminu.</p></div>", 'cases'), 400)
            try:
                due, rule_label = calculate_deadline(sg['base_date'], int(sg['days']), sg['rule'])
            except ValueError as exc:
                return self.send_html(layout('Termin', f"<div class='card'><p>{esc(exc)}</p></div>", 'cases'), 400)
            a = self.current_author(f)
            source = f"Jawny termin z dokumentu: {sg['source_text']} — zatwierdzony przez użytkownika"
            cur = con.execute("""INSERT INTO tasks(case_id,title,due_date,status,priority,depends_on,notes,task_type,created_by,updated_by,
                               deadline_base_date,deadline_days,deadline_rule,deadline_source,deadline_manual)
                               VALUES(?,?,?,'open','high','',?,'Termin procesowy',?,?,?,?,?,?,0)""",
                              (sg['case_id'], sg['suggested_title'], due, source, a, a,
                               sg['base_date'], sg['days'], rule_label, source))
            sync_task_alert(con,cur.lastrowid,a)
            con.execute("UPDATE deadline_suggestions SET status='accepted' WHERE id=?", (sid,))
            con.execute("""INSERT OR IGNORE INTO smart_links(case_id,source_type,source_id,target_type,target_id,relation_type,note,auto_created,created_by)
                           VALUES(?,?,?,?,?,'uruchamia termin',?,0,?)""",
                        (sg['case_id'], 'document', sg['document_id'], 'task', cur.lastrowid, 'Termin zatwierdzony przez użytkownika', a))
            audit(con, sg['case_id'], 'task', cur.lastrowid, 'Zatwierdzono sugestię terminu',
                  f"Źródło: {_change_value(sg['source_text'])}\nTermin: {_change_value(due)}", a)
        target = f.get('return_to') or f"/case/{sg['case_id']}#deadlines"
        self.redirect(target if target.startswith('/') else f"/case/{sg['case_id']}#deadlines")

    def case_view_advanced(self, cid):
        u=current_request_user(); uid=u['id'] if u else None
        with db() as con:
            c=con.execute("SELECT * FROM cases WHERE id=?",(cid,)).fetchone()
            if not c: return self.send_error(404)
            if uid:
                con.execute("INSERT INTO user_case_recent(user_id,case_id,opened_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(user_id,case_id) DO UPDATE SET opened_at=CURRENT_TIMESTAMP",(uid,cid))
                con.execute("DELETE FROM user_case_recent WHERE user_id=? AND case_id NOT IN (SELECT case_id FROM user_case_recent WHERE user_id=? ORDER BY opened_at DESC LIMIT 30)",(uid,uid))
            parties=con.execute("SELECT * FROM parties WHERE case_id=? ORDER BY id",(cid,)).fetchall()
            events=con.execute("SELECT * FROM events WHERE case_id=? ORDER BY event_date DESC,id DESC",(cid,)).fetchall()
            tasks=con.execute("SELECT * FROM tasks WHERE case_id=? ORDER BY status,CASE WHEN due_date='' THEN 1 ELSE 0 END,due_date,id",(cid,)).fetchall()
            docs=con.execute("SELECT * FROM documents WHERE case_id=? ORDER BY CASE WHEN doc_date='' THEN 1 ELSE 0 END,doc_date DESC,id DESC",(cid,)).fetchall()
            notes=con.execute("SELECT * FROM case_notes WHERE case_id=? ORDER BY created_at DESC,id DESC",(cid,)).fetchall()
            drafts=con.execute("SELECT * FROM writing_projects WHERE case_id=? ORDER BY updated_at DESC,id DESC",(cid,)).fetchall()
            relations=con.execute("""SELECT r.*,s.signature source_signature,s.internal_signature source_internal,s.title source_title,t.signature target_signature,t.internal_signature target_internal,t.title target_title FROM case_relations r JOIN cases s ON s.id=r.source_case_id JOIN cases t ON t.id=r.target_case_id WHERE r.source_case_id=? OR r.target_case_id=? ORDER BY r.id""",(cid,cid)).fetchall()
            all_cases=con.execute("SELECT id,signature,internal_signature,title FROM cases WHERE id<>? ORDER BY signature='',signature,title",(cid,)).fetchall()
            case_tags=con.execute("SELECT t.name FROM case_tags ct JOIN tags t ON t.id=ct.tag_id WHERE ct.case_id=? ORDER BY t.name",(cid,)).fetchall()
            external_signatures=con.execute("SELECT * FROM case_external_signatures WHERE case_id=? ORDER BY label COLLATE NOCASE, id",(cid,)).fetchall()
            users=con.execute("SELECT id,author_name,function,is_active FROM users ORDER BY author_name").fetchall()
            history=con.execute("SELECT * FROM audit_log WHERE case_id=? ORDER BY id DESC LIMIT 30",(cid,)).fetchall()
            process_recent=con.execute("SELECT * FROM process_events WHERE case_id=? ORDER BY CASE WHEN event_date='' THEN 1 ELSE 0 END,event_date DESC,id DESC LIMIT 5",(cid,)).fetchall()
            lead_user=con.execute("SELECT * FROM users WHERE id=?",(c['lead_user_id'],)).fetchone() if c['lead_user_id'] else None
            pinned=bool(con.execute("SELECT 1 FROM user_case_pins WHERE user_id=? AND case_id=?",(uid,cid)).fetchone()) if uid else False
            structured_entities=con.execute("""SELECT ce.*,e.entity_type,e.display_name,e.pesel,e.nip,e.krs FROM case_entities ce JOIN entities e ON e.id=ce.entity_id WHERE ce.case_id=? ORDER BY ce.id""",(cid,)).fetchall()
            all_entities=con.execute("SELECT id,display_name,pesel,nip,krs FROM entities ORDER BY display_name COLLATE NOCASE").fetchall()
            checklist=con.execute("SELECT * FROM case_checklist_items WHERE case_id=? ORDER BY sort_order,id",(cid,)).fetchall()
            checklist_templates=con.execute("SELECT * FROM checklist_templates ORDER BY category,name").fetchall()
            readonly=bool(c['status']=='closed' and not int(c['closed_edit_unlocked'] or 0))
            sig_ids=[cid]+[x['id'] for x in all_cases]
            sig_ids += [x['source_case_id'] for x in relations] + [x['target_case_id'] for x in relations]
            case_sig_map=load_external_signature_map(con,sig_ids)
        user_map={x['id']:x for x in users}
        task_user_opts='<option value="">— nie przypisano —</option>'+''.join(f"<option value='{x['id']}'>{esc(user_display_name(x))}</option>" for x in users if x['is_active'])
        task_type_opts=''.join(f"<option>{esc(x)}</option>" for x in ["Zadanie","Monit","Termin procesowy","Płatność"])
        doc_task_opts='<option value="">— bez powiązanego zadania / terminu —</option>'+''.join(f"<option value='{x['id']}'>{esc(x['title'])}{(' · '+fmt_date(x['due_date'])) if x['due_date'] else ''}</option>" for x in tasks if x['status']!='done')
        doc_parent_opts='<option value="">— nowe pismo / dokument główny —</option>'+''.join(f"<option value='{x['id']}'>{esc(x['title'])}</option>" for x in docs if not row_get(x,'parent_document_id',None))
        entity_opts='<option value="">— wybierz podmiot —</option>'+''.join(f"<option value='{x['id']}'>{esc(x['display_name'])}{' · PESEL '+esc(x['pesel']) if x['pesel'] else ''}{' · NIP '+esc(x['nip']) if x['nip'] else ''}</option>" for x in all_entities)
        structured_parts=[]
        for x in structured_entities:
            ids=[]
            if x['pesel']: ids.append('PESEL '+x['pesel'])
            if x['nip']: ids.append('NIP '+x['nip'])
            if x['krs']: ids.append('KRS '+x['krs'])
            actions='' if readonly else f"<form method='post' action='/case-entity/{x['id']}/delete' style='display:inline' onsubmit=\"return confirm('Usunąć przypisanie podmiotu do tej sprawy?');\"><button class='btn small danger'>Usuń z tej sprawy</button></form>"
            structured_parts.append(f"<tr><td><a href='/entity/{x['entity_id']}'><b>{esc(x['display_name'])}</b></a><div class='small muted'>{esc(' · '.join(ids))}</div></td><td><span class='entity-role'>{esc(x['role'])}</span></td><td>{esc(x['notes']) or '—'}</td><td>{actions}</td></tr>")
        structured_html=''.join(structured_parts) or '<tr><td colspan=4>Brak podmiotów z kartoteki przypisanych do sprawy.</td></tr>'
        check_parts=[]
        for x in checklist:
            cls='done' if x['is_done'] else ''
            controls='' if readonly else f"<form method='post' action='/checklist/item/{x['id']}/toggle'><button class='btn small'>{'↩' if x['is_done'] else '✓'}</button></form><form method='post' action='/checklist/item/{x['id']}/delete' onsubmit=\"return confirm('Usunąć element checklisty?');\"><button class='btn small danger'>×</button></form>"
            check_parts.append(f"<div class='check-item {cls}'>{controls}<span>{esc(x['label'])}</span></div>")
        checklist_html=''.join(check_parts) or '<div class="empty">Brak checklisty dla tej sprawy.</div>'
        checklist_opts='<option value="">— wybierz szablon —</option>'+''.join(f"<option value='{x['id']}'>{esc(x['name'])}{' · '+esc(x['category']) if x['category'] else ''}</option>" for x in checklist_templates)
        ro_user=current_request_user(); ro_admin=bool(ro_user and ro_user['role']=='admin')
        readonly_banner=''
        if readonly:
            unlock=(f"<form method='post' action='/case/{cid}/unlock' style='display:inline'><button class='btn danger'>Odblokuj do edycji</button></form>" if ro_admin else '')
            readonly_banner=f"<div class='readonly-banner'><b>🔒 Sprawa zakończona — tryb tylko do odczytu.</b> Edycja jest zablokowana, aby nie zmienić przypadkowo akt archiwalnych. {unlock}</div>"
        elif c['status']=='closed' and ro_admin:
            readonly_banner=f"<div class='readonly-banner'><b>🔓 Zakończona sprawa jest czasowo odblokowana.</b> <form method='post' action='/case/{cid}/lock' style='display:inline'><button class='btn'>Zablokuj ponownie</button></form></div>"
        history_html=''.join(f"<div class='audit-row'><div><b>{esc(row_get(x,'action'))}</b></div><div class='small muted' style='margin:4px 0'>{audit_description_html(row_get(x,'description',row_get(x,'details','')))}</div><div style='margin:5px 0'>{audit_target_html(x)}</div><div class='author'>{esc(row_get(x,'created_at'))} · {esc(row_get(x,'author',row_get(x,'actor','')))}</div></div>" for x in history) or '<div class="empty">Brak historii zmian.</div>'
        lead_text=user_display_name(lead_user) if lead_user else '—'
        pin_char='★' if pinned else '☆'; pin_cls='on' if pinned else ''

        def who(r):
            bits=[]
            if 'created_by' in r.keys() and r['created_by']: bits.append('autor: '+esc(r['created_by']))
            if 'updated_by' in r.keys() and r['updated_by'] and r['updated_by']!=r['created_by']: bits.append('zmiana: '+esc(r['updated_by']))
            return ('<div class="author">'+' · '.join(bits)+'</div>') if bits else ''

        party_parts=[]
        for x in parties:
            party_parts.append(
                f"<tr><td><b>{esc(x['name'])}</b>{who(x)}</td><td>{esc(x['role'])}</td><td>{esc(x['notes'])}</td>"
                f"<td class='nowrap'><a class='btn small' href='/party/{x['id']}/edit'>Edytuj</a> "
                f"<form method='post' action='/party/{x['id']}/delete' style='display:inline' onsubmit=\"return confirm('Przenieść tę osobę do Kosza?')\">"
                f"<input type='hidden' name='case_id' value='{cid}'><button class='btn small danger'>Do kosza</button></form></td></tr>"
            )
        parties_html=''.join(party_parts) or '<tr><td colspan=4>Brak stron.</td></tr>'

        # Oś czasu 2.0: jeden chronologiczny strumień zdarzeń, dokumentów, zadań, notatek i projektów.
        timeline_items=[]
        for x in events:
            controls=(f"<div style='margin-top:6px'><a class='btn small' href='/event/{x['id']}/edit'>Edytuj</a> "
                      f"<form method='post' action='/event/{x['id']}/delete' style='display:inline' onsubmit=\"return confirm('Przenieść to zdarzenie do Kosza?')\"><input type='hidden' name='case_id' value='{cid}'><button class='btn small danger'>Do kosza</button></form></div>")
            html=(f"<div class='event timeline-item' data-kind='event'><div class='event-date'>{fmt_date(x['event_date'])} · {esc(x['event_type'])}</div>"
                  f"<div class='event-title'>{esc(x['title'])}</div><div class='event-desc'>{esc(x['description'])}</div>{who(x)}{controls}</div>")
            timeline_items.append(((x['event_date'] or str(row_get(x,'created_at',''))[:10]),str(row_get(x,'created_at','')),x['id'],'event',html))
        for x in docs:
            ddate=row_get(x,'delivered_date','') or x['received_date'] or x['doc_date'] or str(row_get(x,'created_at',''))[:10]
            phase='Doręczono' if row_get(x,'delivered_date','') else ('Wpłynął dokument' if x['received_date'] else 'Dokument')
            meta=[]
            if row_get(x,'sender',''): meta.append('nadawca: '+esc(row_get(x,'sender','')))
            if row_get(x,'tags',''): meta.append('tagi: '+esc(row_get(x,'tags','')))
            html=(f"<div class='event timeline-item timeline-document' data-kind='document'><div class='event-date'>{fmt_date(ddate)} · {phase} · {esc(x['doc_type'])}</div>"
                  f"<div class='event-title'><a href='/document/{x['id']}/open'>{esc(x['title'])}</a></div><div class='event-desc'>{esc(x['description'])}</div>"
                  f"<div class='small muted'>{' · '.join(meta)}{' · ' if meta else ''}status: {esc(x['doc_status'])}</div>{who(x)}</div>")
            timeline_items.append((ddate,str(row_get(x,'created_at','')),x['id'],'document',html))
        for x in tasks:
            tdate=x['due_date'] or str(row_get(x,'created_at',''))[:10]
            state='Wykonane' if x['status']=='done' else 'Zadanie / termin'
            html=(f"<div class='event timeline-item timeline-task' data-kind='task'><div class='event-date'>{fmt_date(tdate)} · {state}</div>"
                  f"<div class='event-title'><a href='/task/{x['id']}/edit'>{esc(x['title'])}</a></div><div class='event-desc'>{esc(x['notes'])}</div>{who(x)}</div>")
            timeline_items.append((tdate,str(row_get(x,'created_at','')),x['id'],'task',html))
        for x in notes:
            ndate=str(x['created_at'] or '')[:10]
            html=(f"<div class='event timeline-item timeline-note' data-kind='note'><div class='event-date'>{fmt_date(ndate)} · Notatka</div>"
                  f"<div class='event-desc' style='white-space:pre-wrap'>{esc(x['note'])}</div><div class='author'>{esc(x['author'])}</div></div>")
            timeline_items.append((ndate,str(x['created_at'] or ''),x['id'],'note',html))
        for x in drafts:
            pdate=str(x['updated_at'] or x['created_at'] or '')[:10]
            html=(f"<div class='event timeline-item timeline-draft' data-kind='draft'><div class='event-date'>{fmt_date(pdate)} · Projekt pisma · {esc(x['status'])}</div>"
                  f"<div class='event-title'><a href='/draft/{x['id']}'>{esc(x['title'])}</a></div><div class='event-desc'>{esc(x['doc_type'])}</div>{who(x)}</div>")
            timeline_items.append((pdate,str(x['updated_at'] or x['created_at'] or ''),x['id'],'draft',html))
        timeline_items.sort(key=lambda z:(z[0] or '',z[1] or '',z[2]),reverse=True)
        events_html=''.join(x[4] for x in timeline_items) or '<div class="empty">Brak wpisów na osi czasu.</div>'
        timeline_filters="""<div class='timeline-filters'><button type='button' class='btn small primary' data-timeline-filter='all'>Wszystko</button><button type='button' class='btn small' data-timeline-filter='event'>Zdarzenia</button><button type='button' class='btn small' data-timeline-filter='document'>Dokumenty</button><button type='button' class='btn small' data-timeline-filter='task'>Zadania</button><button type='button' class='btn small' data-timeline-filter='draft'>Projekty</button><button type='button' class='btn small' data-timeline-filter='note'>Notatki</button></div>"""

        open_task_parts=[]; done_task_parts=[]
        for x in tasks:
            done=x['status']=='done'
            pri='priority-high' if x['priority']=='high' and not done else ''
            dep=(' · zależność: '+esc(x['depends_on'])) if x['depends_on'] else ''
            note_html=f"<div class='small'>{esc(x['notes'])}</div>" if x['notes'] else ''
            au=user_map.get(x['assigned_user_id']) if x['assigned_user_id'] else None
            assigned_html=f"<div class='small lead-chip'>Wykonawca: {esc(user_display_name(au))}</div>" if au else ''
            deadline_html=''
            if row_get(x,'deadline_base_date',''):
                manual=' · ręcznie skorygowany' if int(row_get(x,'deadline_manual',0) or 0) else ''
                deadline_html=f"<div class='small deadline-meta'>Termin pomocniczo wyliczony: {fmt_date(x['deadline_base_date'])} + {esc(str(row_get(x,'deadline_days','')))} {esc(row_get(x,'deadline_rule',''))}{manual}</div>"
            type_badge=f"<span class='mini-badge'>{esc(row_get(x,'task_type','Zadanie') or 'Zadanie')}</span>"
            item=(
                f"<div class='task {'done compact-done' if done else ''}'><form method='post' action='/task/{x['id']}/toggle'><input type='hidden' name='case_id' value='{cid}'><input type='hidden' name='return_to' value='/case/{cid}?mode=advanced#case-tasks'><button class='task-check' title='{'Przywróć zadanie' if done else 'Oznacz jako wykonane'}'>{'↩' if done else '✓'}</button></form>"
                f"<div style='flex:1'><div>{type_badge} <span class='task-title {pri}'>{esc(x['title'])}</span></div><div class='small muted'>{fmt_date(x['due_date'])}{dep}</div>{assigned_html}{deadline_html}{note_html}{who(x)}"
                f"<div style='margin-top:6px'><a class='btn small' href='/task/{x['id']}/edit?return_to=%2Fcase%2F{cid}%3Fmode%3Dadvanced%23case-tasks'>Edytuj</a></div></div>"
                f"<form method='post' action='/task/{x['id']}/delete' onsubmit=\"return confirm('Przenieść zadanie do Kosza?')\"><input type='hidden' name='case_id' value='{cid}'><input type='hidden' name='return_to' value='/case/{cid}?mode=advanced#case-tasks'><button class='btn small danger'>×</button></form></div>"
            )
            (done_task_parts if done else open_task_parts).append(item)
        open_tasks_html=''.join(open_task_parts) or '<div class="empty">Brak otwartych zadań.</div>'
        done_tasks_html=(f"<details class='done-tasks-details'><summary>Wykonane ({len(done_task_parts)})</summary>{''.join(done_task_parts)}</details>" if done_task_parts else '')
        tasks_html=open_tasks_html+done_tasks_html

        def render_doc_row(x, child=False, parent_title=''):
            file_actions='—'
            if x['stored_name']:
                file_actions=f"<a class='btn small' href='/document/{x['id']}/open'>Otwórz</a> <a class='btn small' href='/document/{x['id']}/download'>Pobierz</a>"
            filename=esc(x['original_name']) if x['original_name'] else 'bez pliku'
            linked=''
            if row_get(x,'linked_task_id',None):
                lt=next((t for t in tasks if t['id']==row_get(x,'linked_task_id')),None)
                if lt:
                    linked=f"<div class='small linked-chip'>↳ zadanie/termin: <a href='/task/{lt['id']}/edit'>{esc(lt['title'])}</a></div>"
            metadata=[]
            if row_get(x,'sender',''): metadata.append('nadawca: '+esc(row_get(x,'sender','')))
            if row_get(x,'document_author',''): metadata.append('autor dokumentu: '+esc(row_get(x,'document_author','')))
            if row_get(x,'tags',''): metadata.append('tagi: '+esc(row_get(x,'tags','')))
            meta_html=("<div class='small muted'>"+' · '.join(metadata)+"</div>") if metadata else ''
            child_hint=(f"<div class='attachment-parent-hint'>Załącznik do: {esc(parent_title)}</div>" if child and parent_title else '')
            kind=("<span class='attachment-label'>↳ Załącznik</span>" if child else f"<span class='pill'>{esc(x['doc_type'])}</span>")
            row_cls=" class='attachment-row'" if child else " class='document-family'"
            title_prefix='📎 ' if child else ''
            return (
                f"<tr{row_cls}><td><b>{'załącznik:' if child else 'dokument:'}</b> {fmt_date(x['doc_date'])}<div class='small muted'><b>wpływ:</b> {fmt_date(x['received_date'])}</div><div class='small muted'><b>doręczenie:</b> {fmt_date(row_get(x,'delivered_date',''))}</div></td>"
                f"<td>{kind}<div><span class='doc-status {'sign' if x['doc_status']=='Do podpisu' else ''}'>{esc(x['doc_status'])}</span></div></td><td><b>{title_prefix}{esc(x['title'])}</b>{child_hint}<div class='small muted'>{esc(x['description'])}</div>{meta_html}{linked}<div class='small muted'>{filename}</div>{who(x)}</td>"
                f"<td>{file_actions}</td><td class='nowrap'><a class='btn small' href='/document/{x['id']}/edit'>Edytuj</a> "
                f"<form method='post' action='/document/{x['id']}/delete' style='display:inline' onsubmit=\"return confirm('Przenieść dokument do Kosza? Plik zostanie zachowany do czasu trwałego usunięcia z Kosza.')\"><input type='hidden' name='case_id' value='{cid}'><button class='btn small danger'>Do kosza</button></form></td></tr>"
            )

        children_by_parent={}
        roots=[]
        ids={x['id'] for x in docs}
        for x in docs:
            pid=int(row_get(x,'parent_document_id',0) or 0)
            if pid and pid in ids:
                children_by_parent.setdefault(pid,[]).append(x)
            else:
                roots.append(x)
        for arr in children_by_parent.values():
            arr.sort(key=lambda x:(int(row_get(x,'attachment_order',0) or 0),x['id']))
        doc_parts=[]
        for root in roots:
            doc_parts.append(render_doc_row(root))
            for child in children_by_parent.get(root['id'],[]):
                doc_parts.append(render_doc_row(child,True,root['title']))
        docs_html=''.join(doc_parts) or '<tr><td colspan=5>Brak dokumentów.</td></tr>'

        ext_sig_parts=[]
        for x in external_signatures:
            ext_sig_parts.append(
                f"<tr><td><b>{esc(x['label'])}</b></td><td><span class='case-link'>{esc(x['signature'])}</span>{who(x)}</td>"
                f"<td class='nowrap'><a class='btn small' href='/external-signature/{x['id']}/edit'>Edytuj</a> "
                f"<form method='post' action='/external-signature/{x['id']}/delete' style='display:inline' onsubmit=\"return confirm('Przenieść tę dodatkową sygnaturę do Kosza?')\"><input type='hidden' name='case_id' value='{cid}'><button class='btn small danger'>Do kosza</button></form></td></tr>"
            )
        external_signatures_html=''.join(ext_sig_parts) or '<tr><td colspan=3>Brak dodatkowych sygnatur.</td></tr>'

        rel_parts=[]; quick=[]
        for x in relations:
            labels=RELATION_TYPES.get(x['relation_type'],(x['relation_type'],x['relation_type']))
            if x['source_case_id']==cid:
                oid=x['target_case_id']; otitle=x['target_title']; lab=labels[0]
                shown = primary_signature_fast(oid, x['target_signature'], case_sig_map)
            else:
                oid=x['source_case_id']; otitle=x['source_title']; lab=labels[1]
                shown = primary_signature_fast(oid, x['source_signature'], case_sig_map)
            osig = shown if shown != 'Bez sygnatury' else ''
            shown=osig or otitle
            quick.append(f"<a class='btn small' href='/case/{oid}'>{esc(lab)} → {esc(shown)}</a>")
            subtitle=f"<div class='small muted'>{esc(otitle)}</div>" if osig else ''
            rel_parts.append(
                f"<tr><td><span class='pill'>{esc(lab)}</span></td><td><a class='case-link' href='/case/{oid}'>{esc(shown)}</a>{subtitle}</td><td>{esc(row_get(x,'note',row_get(x,'notes',''))) or '—'}{who(x)}</td>"
                f"<td class='nowrap'><a class='btn small' href='/relation/{x['id']}/edit'>Edytuj</a> <form method='post' action='/relation/{x['id']}/delete' style='display:inline' onsubmit=\"return confirm('Przenieść to powiązanie do Kosza?')\"><input type='hidden' name='case_id' value='{cid}'><button class='btn small danger'>Do kosza</button></form></td></tr>"
            )
        relations_html=''.join(rel_parts) or '<tr><td colspan=4>Brak powiązanych spraw.</td></tr>'
        quick_html=' '.join(quick) if quick else '<span class="muted small">Brak powiązanych spraw.</span>'

        relation_case_opt_parts=[]
        for x in all_cases:
            opt_primary = primary_signature_fast(x['id'], x['signature'], case_sig_map)
            opt_prefix = '' if opt_primary == 'Bez sygnatury' else opt_primary + ' — '
            internal_suffix = ' · ' + internal_signature_text(x['internal_signature'])
            relation_case_opt_parts.append(f"<option value='{x['id']}'>{esc(opt_prefix+x['title']+internal_suffix)}</option>")
        relation_case_opts=''.join(relation_case_opt_parts)
        relation_type_opts=''.join(f"<option value='{esc(k)}'>{esc(v[0])}</option>" for k,v in RELATION_TYPES.items())
        tags_html=''.join(f"<a class='tag' href='/cases?tag={quote(x['name'])}'>{esc(x['name'])}</a>" for x in case_tags) or '<span class="muted">—</span>'
        note_parts=[]
        for x in notes:
            auth=(' · autor: '+esc(x['author'])) if x['author'] else ''
            note_parts.append(f"<div style='padding:10px 0;border-bottom:1px solid #edf0f3'><div style='white-space:pre-wrap'>{esc(x['note'])}</div><div class='author'>{esc(x['created_at'])}{auth}</div><form method='post' action='/note/{x['id']}/delete' style='margin-top:5px' onsubmit=\"return confirm('Przenieść notatkę do Kosza?');\"><input type='hidden' name='case_id' value='{cid}'><button class='btn small danger'>Do kosza</button></form></div>")
        notes_html=''.join(note_parts) or '<div class="empty">Brak notatek chronologicznych.</div>'
        event_opts=''.join(f"<option>{esc(x)}</option>" for x in EVENT_TYPES)
        doc_opts=''.join(f"<option>{esc(x)}</option>" for x in DOC_TYPES)
        doc_status_opts=''.join(f"<option>{esc(x)}</option>" for x in DOC_STATUSES)
        case_auth=[]
        if c['created_by']: case_auth.append('utworzył: '+esc(c['created_by']))
        if c['updated_by']: case_auth.append('ostatnio zmienił: '+esc(c['updated_by']))
        case_auth_html=f"<div class='author'>{' · '.join(case_auth)}</div>" if case_auth else ''
        main_note=f"<div class='notice' style='margin-top:14px;white-space:pre-wrap'>{esc(c['notes'])}</div>" if c['notes'] else ''
        relation_form='<div class="empty">Najpierw dodaj drugą sprawę.</div>'
        if all_cases:
            relation_form=(f"<form method='post' action='/case/{cid}/relation' class='form-grid' style='margin-top:12px'><div><label>Rodzaj relacji</label><select name='relation_type'>{relation_type_opts}</select></div><div><label>Powiązana sprawa</label><select name='target_case_id' required>{relation_case_opts}</select></div><div class='full'><label>Notatka</label><input name='note'></div><div class='full'><button class='btn primary'>Dodaj powiązanie</button></div></form>")

        shown_sig, shown_kind = display_signature_meta(cid, c['signature'], c['internal_signature'])
        primary = primary_signature_fast(cid, c['signature'], case_sig_map)
        next_complete_html=(f"<form method='post' action='/case/{cid}/next-action/complete' class='inline-form'><button class='btn success' type='submit'>✓ Oznacz jako wykonane</button></form>" if (c['next_step'] and not readonly) else '')
        body=f"""
        <div class='case-hero'><div class='case-hero-main'><div class='eyebrow'>KARTA SPRAWY</div><h1>{esc(primary)}</h1><div class='case-subject'>{esc(c['subject']) or esc(c['title'])}</div><div class='case-hero-meta'>{esc(internal_signature_text(c['internal_signature']))} · {esc(c['title'])} · klient: <b>{esc(c['client']) or '—'}</b></div></div><div class='case-control-bar'>
          <form method='post' action='/case/{cid}/pin'><button class='pin-btn {pin_cls}' title='Przypnij / odepnij'>{pin_char}</button></form>{badge(c['status'])}
          <a class='btn' href='/case/{cid}/export'>PDF / wyciąg</a><a class='btn' href='/case/{cid}/export/package'>Eksport pełnej sprawy</a><a class='btn primary-soft' href='/case/{cid}/history'>Historia sprawy</a>{'' if readonly else f"<a class='btn' href='/draft/new?case_id={cid}'>+ Projekt pisma</a><a class='btn' href='/case/{cid}/edit'>Edytuj dane</a>"}
          <form method='post' action='/case/{cid}/duplicate' onsubmit="return confirm('Utworzyć nową sprawę na podstawie tej? Sygnatury, dokumenty i historia nie będą kopiowane.');"><button class='btn'>Duplikuj sprawę</button></form>
        </div></div><div class='case-nav-strip'><a href='#case-overview'>Pulpit sprawy</a><a href='/case/{cid}/history#process'>Historia procesu</a><a href='#documents'>Dokumenty</a><a href='#case-tasks'>Zadania</a><a href='#case-people'>Osoby</a><a href='#case-notes'>Notatki</a><a href='/case/{cid}/history#activity'>Historia sprawy</a></div><div id='rkCaseContext' data-case-id='{cid}'></div>{readonly_banner}
        <div class='case-summary-grid'>
          <div class='case-summary-item'><div class='k'>Klient</div><div class='v'>{esc(c['client']) or '—'}</div></div>
          <div class='case-summary-item'><div class='k'>Prowadzący</div><div class='v'>{esc(lead_text)}</div></div>
          <div class='case-summary-item'><div class='k'>Status</div><div class='v'>{esc(STATUS_LABELS.get(c['status'],c['status']))}</div></div>
          <div class='case-summary-item'><div class='k'>Czekamy na</div><div class='v'>{esc(c['waiting_for']) or '—'}</div></div>
          <div class='case-summary-item'><div class='k'>Najbliższa data</div><div class='v'>{fmt_date(c['next_date'])}</div></div>
          <div class='case-summary-item'><div class='k'>Następna czynność</div><div class='v' title='{esc(c['next_step'])}'>{esc(c['next_step']) or '—'}</div></div>
        </div>
        {'' if readonly else f"<div class='card next-action-card'><div class='section-head'><div><div class='section-kicker'>NASTĘPNY RUCH</div><h2>Co dalej w tej sprawie?</h2></div><a class='btn small' href='/deadline'>Kalkulator terminu</a></div><form method='post' action='/case/{cid}/next-action' class='form-grid'><div class='full'><label>Następna czynność</label><input name='next_step' value='{esc(c['next_step'])}' placeholder='np. złożyć odpowiedź na zażalenie'></div><div><label>Data / termin</label><input type='date' name='next_date' value='{esc(c['next_date'])}'></div><div><label>Czekamy na</label><input name='waiting_for' value='{esc(c['waiting_for'])}' placeholder='np. sąd / klient / organ'></div><div class='full'><button class='btn primary'>Zapisz następny ruch</button></div></form>{next_complete_html}</div>"}
        <div class='card' style='margin-bottom:16px'><b>Przejdź do spraw powiązanych:</b> <span style='margin-left:8px'>{quick_html}</span></div>
        <div class='grid' id='case-overview'>
          <div class='card span8'><h2>Najważniejsze informacje</h2><table><tr><th>Sygnatura sądowa</th><td>{esc(c['signature']) or '—'}</td></tr><tr><th>Sygnatura wewnętrzna</th><td>{esc(c['internal_signature']) or '—'}</td></tr><tr><th>Klient / zlecający</th><td><b>{esc(c['client']) or '—'}</b></td></tr><tr><th>Prowadzący</th><td>{esc(lead_text)}</td></tr><tr><th>Czekamy na</th><td>{esc(c['waiting_for']) or '—'}</td></tr><tr><th>Tagi</th><td>{tags_html}</td></tr><tr class='important-row'><th>Czego dotyczy sprawa?</th><td><b>{esc(c['subject']) or esc(c['title'])}</b></td></tr><tr><th>Sąd</th><td>{esc(c['court']) or '—'} {('· '+esc(c['department'])) if c['department'] else ''}</td></tr><tr><th>Kategoria</th><td>{esc(c['category']) or '—'}</td></tr><tr><th>Następny krok</th><td><b>{esc(c['next_step']) or '—'}</b></td></tr><tr><th>Najbliższa data</th><td>{fmt_date(c['next_date'])}</td></tr></table>{main_note}{case_auth_html}</div>
          <div class='card span12' id='case-people'><div class='section-head'><div><h2>Osoby i podmioty sprawy</h2><div class='small muted'>Strukturalna kartoteka osób i firm — wykorzystywana także do kontroli konfliktu interesów.</div></div><a class='btn small' href='/entities'>Kartoteka</a></div><table><tr><th>Podmiot</th><th>Rola</th><th>Notatka</th><th></th></tr>{structured_html}</table>{'' if readonly else f"<details><summary>+ Przypisz podmiot z kartoteki</summary><form method='post' action='/case/{cid}/entity' class='form-grid' style='margin-top:12px'><div><label>Podmiot</label><select name='entity_id' required>{entity_opts}</select></div><div><label>Rola</label><input name='role' required placeholder='np. Klient, Przeciwnik, Świadek'></div><div class='full'><label>Notatka</label><input name='notes'></div><div class='full'><button class='btn primary'>Sprawdź konflikt i przypisz</button></div></form></details>"}</div>
          <div class='card span4'><h2>Strony / uczestnicy — wpisy tekstowe</h2><table>{parties_html}</table>{'' if readonly else f"<details><summary>+ Dodaj wpis tekstowy</summary><form method='post' action='/case/{cid}/party' class='form-grid' style='margin-top:12px'><div><label>Imię i nazwisko</label><input name='name' required></div><div><label>Rola</label><input name='role'></div><div class='full'><label>Notatka</label><input name='notes'></div><div class='full'><button class='btn primary'>Dodaj</button></div></form></details>"}</div>
          <div class='card span12'><h2>Sygnatury innych organów</h2><div class='small muted' style='margin-bottom:10px'>Dodaj dowolną liczbę oznaczeń spoza sygnatury sądowej.</div><table><tr><th>Nazwa / organ</th><th>Sygnatura / numer</th><th></th></tr>{external_signatures_html}</table><details><summary>+ Dodaj dodatkową sygnaturę</summary><form method='post' action='/case/{cid}/external-signature' class='form-grid' style='margin-top:12px'><div><label>Nazwa pola *</label><input name='label' required placeholder='np. Sygnatura prokuratury'></div><div><label>Sygnatura / numer *</label><input name='signature' required></div><div class='full'><button class='btn primary'>Dodaj sygnaturę</button></div></form></details></div>
          <div class='card span12'><h2>Powiązane sprawy</h2><table><tr><th>Relacja</th><th>Sprawa</th><th>Notatka / autor</th><th></th></tr>{relations_html}</table><details><summary>+ Połącz z inną sprawą</summary>{relation_form}</details></div>
          <div class='card span12 process-preview-card'><div class='section-head'><div><div class='section-kicker'>PRZEBIEG POSTĘPOWANIA</div><h2>Historia procesu</h2><div class='small muted'>Najważniejsze zdarzenia procesowe — osobno od technicznej historii zmian.</div></div><a class='btn primary-soft' href='/case/{cid}/history#process'>Otwórz pełną historię procesu</a></div><div class='process-preview'>{''.join(f"<div class='process-preview-row'><span>{fmt_date(x['event_date'])}</span><b>{esc(x['title'])}</b><em>{'✓' if x['status']=='done' else '○'}</em></div>" for x in process_recent) or '<div class="empty">Brak wpisów procesowych. Dodaj je w Historii sprawy.</div>'}</div></div>
          <div class='card span7'><div class='section-head'><div><h2>Oś czasu pracy</h2><div class='small muted'>Codzienna praca kancelarii: dokumenty, zadania, notatki i projekty.</div></div></div>{timeline_filters}<div class='timeline'>{events_html}</div><details><summary>+ Dodaj zdarzenie</summary><form method='post' action='/case/{cid}/event' class='form-grid' style='margin-top:12px'><div><label>Data</label><input type='date' name='event_date' value='{date.today().isoformat()}'></div><div><label>Typ</label><select name='event_type'>{event_opts}</select></div><div class='full'><label>Tytuł</label><input name='title' required></div><div class='full'><label>Opis</label><textarea name='description'></textarea></div><div class='full'><button class='btn primary'>Dodaj</button></div></form></details></div>
          <details class='card span5 module-card' id='case-tasks'><summary class='module-summary'><span><b>Zadania</b><small>Domyślnie tylko otwarte; wykonane są schowane niżej</small></span><span class='module-open-label'>Otwórz</span></summary><div class='module-body'>{tasks_html}<details class='add-panel nested'><summary>+ Dodaj zadanie / monit</summary><form method='post' action='/case/{cid}/task' class='form-grid' style='margin-top:12px'><input type='hidden' name='return_to' value='/case/{cid}?mode=advanced#case-tasks'><div><label>Rodzaj</label><select name='task_type'>{task_type_opts}</select></div><div><label>Termin</label><input type='date' name='due_date'></div><div class='full'><label>Co trzeba zrobić?</label><input name='title' required></div><div><label>Priorytet</label><select name='priority'><option value='normal'>Normalny</option><option value='high'>Wysoki</option></select></div><div><label>Wykonawca</label><select name='assigned_user_id'>{task_user_opts}</select></div><div class='full'><label>Zależność / czekamy na</label><input name='depends_on'></div><div class='full'><label>Notatki</label><textarea name='notes'></textarea></div><div class='full'><button class='btn primary'>Dodaj</button></div></form></details></div></details>
          <div class='card span12'><div class='section-head'><div><h2>Kontrola kompletności</h2><div class='small muted'>Checklista sprawy — można zastosować szablon odpowiedni do kategorii albo dodawać własne elementy.</div></div><a class='btn small' href='/checklists'>Szablony</a></div>{checklist_html}{'' if readonly else f"<details class='add-panel nested'><summary>+ Dodaj / zastosuj checklistę</summary><div class='form-grid' style='margin-top:12px'><form method='post' action='/case/{cid}/checklist/apply'><label>Zastosuj szablon</label><select name='template_id' required>{checklist_opts}</select><button class='btn'>Zastosuj</button></form><form method='post' action='/case/{cid}/checklist/add'><label>Dodaj własny element</label><input name='label' required placeholder='np. Potwierdzenie opłaty'><button class='btn'>Dodaj</button></form></div></details>"}</div>
          <details class='card span12 module-card' id='documents'><summary class='module-summary'><span><b>Dokumenty</b><small>Dokumenty, pisma i załączniki tej sprawy</small></span><span class='module-open-label'>Otwórz</span></summary><div class='module-body'><div class='section-head'><div><h2>Dokumenty 2.0</h2><div class='small muted'>Metadane, status, doręczenie, tagi i powiązanie z terminem/zadaniem.</div></div><a class='btn small' href='/documents?q={quote(c['internal_signature'] or c['signature'] or c['title'])}'>Otwórz teczkę dokumentów</a></div><table><tr><th>Daty</th><th>Rodzaj</th><th>Dokument / autor</th><th>Plik</th><th></th></tr>{docs_html}</table>{'' if readonly else f"<details class='add-panel nested'><summary>+ Podepnij dokument</summary><form method='post' enctype='multipart/form-data' action='/case/{cid}/document' class='form-grid' style='margin-top:12px'><div><label>Data dokumentu</label><input type='date' name='doc_date'></div><div><label>Data wpływu</label><input type='date' name='received_date'></div><div><label>Data doręczenia</label><input type='date' name='delivered_date'></div><div><label>Rodzaj</label><select name='doc_type'>{doc_opts}</select></div><div><label>Status dokumentu</label><select name='doc_status'>{doc_status_opts}</select></div><div><label>Nadawca</label><input name='sender'></div><div><label>Autor dokumentu</label><input name='document_author'></div><div><label>Tagi</label><input name='tags' placeholder='np. dowód, odpowiedź, pilne'></div><div class='full'><label>Dodaj jako</label><select name='parent_document_id'>{doc_parent_opts}</select><div class='small muted'>Jeżeli wybierzesz istniejące pismo, nowy dokument stanie się jego załącznikiem.</div></div><div class='full'><label>Powiązane zadanie / termin</label><select name='linked_task_id'>{doc_task_opts}</select></div><div class='full'><label>Tytuł *</label><input id='newDocTitle' name='title' required></div><div class='full'><label>Opis</label><input name='description'></div><div class='full'><label>Pismo / dokument główny (opcjonalnie)</label><input type='file' name='file'><label style='font-weight:500'><input style='width:auto' type='checkbox' name='allow_duplicate' value='1'> Zezwól na identyczny plik, jeśli świadomie chcę duplikat</label></div><div class='full'><label>Załączniki do tego pisma</label><input type='file' name='attachments[]' multiple><div class='small muted'>Możesz wskazać kilka plików naraz. Program zapisze je pod dokumentem głównym.</div></div><div class='full'><button class='btn primary'>Dodaj dokument</button></div></form></details>"}</div></details>
          <details class='card span12 module-card' id='case-notes'><summary class='module-summary'><span><b>Notatki</b><small>Chronologiczne notatki kancelarii</small></span><span class='module-open-label'>Otwórz</span></summary><div class='module-body'>{notes_html}<details><summary>+ Dodaj notatkę</summary><form method='post' action='/case/{cid}/note' style='margin-top:12px'><label>Treść notatki</label><textarea name='note' required></textarea><button class='btn primary'>Dodaj notatkę</button></form></details></div></details>
          <div class='card span12'><div class='section-head'><div><h2>Historia zmian tej sprawy</h2><div class='small muted'>Kto, kiedy i co zmienił. Powtarzające się autosave są scalane.</div></div><a class='btn small' href='/history?case_id={cid}'>Pełna historia</a></div>{history_html}</div>
        </div>"""
        self.send_html(layout(primary if shown_sig != 'Bez sygnatury' else c['title'],body,'cases'))

    def case_edit(self,cid):
        with db() as con:
            c=con.execute("SELECT * FROM cases WHERE id=?",(cid,)).fetchone()
            if c and case_read_only(con,cid):
                return self.send_html(layout('Sprawa tylko do odczytu',f"<div class='readonly-banner'>Sprawa jest zakończona i zablokowana. <a class='btn' href='/case/{cid}'>Wróć</a></div>",'cases'),403)
            tags=', '.join(r['name'] for r in con.execute("SELECT t.name FROM case_tags ct JOIN tags t ON t.id=ct.tag_id WHERE ct.case_id=? ORDER BY t.name",(cid,)).fetchall()) if c else ''
            users=con.execute("SELECT id,author_name,function FROM users WHERE is_active=1 ORDER BY author_name").fetchall()
        if not c: return self.send_error(404)
        opts=''.join(f"<option value='{k}' {'selected' if c['status']==k else ''}>{v}</option>" for k,v in STATUS_LABELS.items())
        lead_opts='<option value="">— nie przypisano —</option>'+''.join(f"<option value='{u['id']}' {'selected' if c['lead_user_id']==u['id'] else ''}>{esc(user_display_name(u))}</option>" for u in users)
        body=f"""<div class='topbar'><div><h1>Edytuj sprawę</h1><div class='sub'>{esc(c['title'])}</div></div></div><div class='card'><form method='post' action='/case/{cid}/update' class='form-grid' data-autosave='1'>
        <div><label>Sygnatura sądowa</label><input name='signature' value='{esc(c['signature'])}'></div><div><label>Sygnatura wewnętrzna</label><input name='internal_signature' value='{esc(c['internal_signature'])}'></div>
        <div class='full'><label>Nazwa sprawy * <span class='help-dot' title='Krótka nazwa robocza sprawy'>?</span></label><input name='title' required value='{esc(c['title'])}'></div><div class='full'><label>Klient / zlecający</label><input name='client' value='{esc(c['client'])}'></div>
        <div><label>Prowadzący sprawę</label><select name='lead_user_id'>{lead_opts}</select></div><div><label>Status</label><select name='status'>{opts}</select></div>
        <div class='full'><label>Czekamy na / powód oczekiwania</label><input name='waiting_for' value='{esc(c['waiting_for'])}' placeholder='np. sąd, klient, przeciwnik, urząd'></div>
        <div><label>Sąd</label><input name='court' value='{esc(c['court'])}'></div><div><label>Wydział</label><input name='department' value='{esc(c['department'])}'></div><div><label>Kategoria</label><input name='category' value='{esc(c['category'])}'></div><div><label>Najbliższa data</label><input type='date' name='next_date' value='{esc(c['next_date'])}'></div>
        <div class='full'><label>Tagi</label><input name='tags' value='{esc(tags)}'></div><div class='full important-field'><label>Czego dotyczy sprawa? / Przedmiot <span class='help-dot' title='Opis widoczny na pulpicie i karcie sprawy'>?</span></label><input name='subject' value='{esc(c['subject'])}' placeholder='np. alimenty, zapłata, rozwód, odszkodowanie'></div><div class='full'><label>Następny krok</label><input name='next_step' value='{esc(c['next_step'])}'></div><div class='full'><label>Notatki</label><textarea name='notes'>{esc(c['notes'])}</textarea></div><div class='full'><button class='btn primary'>Zapisz</button> <a class='btn' href='/case/{cid}'>Wróć</a></div></form></div>
        <br><div class='card danger-zone'><h2>Usuwanie duplikatu</h2><p class='muted'>Całą sprawę może usunąć wyłącznie administrator. Przed operacją program automatycznie tworzy pełny snapshot danych.</p><a class='btn danger' href='/case/{cid}/delete'>Przejdź do bezpiecznego usuwania</a></div>"""
        self.send_html(layout('Edycja',body,'cases'))

    def case_update(self,cid,f):
        keys=['signature','internal_signature','client','title','court','department','category','subject','status','waiting_for','next_step','next_date','notes']
        vals=[f.get(k,'').strip() for k in keys]; author=self.current_author(f)
        try: lead=int(f.get('lead_user_id','') or 0) or None
        except ValueError: lead=None
        new_values=dict(zip(keys,vals))
        labels={
            'signature':'Sygnatura sądowa','internal_signature':'Sygnatura wewnętrzna','client':'Klient / zlecający',
            'title':'Nazwa sprawy','court':'Sąd','department':'Wydział','category':'Kategoria','subject':'Czego dotyczy sprawa',
            'status':'Status','waiting_for':'Czekamy na','next_step':'Następny krok','next_date':'Najbliższa data','notes':'Notatki'
        }
        with db() as con:
            old=con.execute("SELECT * FROM cases WHERE id=?",(cid,)).fetchone()
            if not old: return self.send_error(404)
            old_tags=[r['name'] for r in con.execute("SELECT t.name FROM case_tags ct JOIN tags t ON t.id=ct.tag_id WHERE ct.case_id=? ORDER BY t.name",(cid,)).fetchall()]
            new_tags=parse_tags(f.get('tags',''))
            details=describe_changes(old,new_values,labels,compact_fields={'notes'})
            if old['lead_user_id'] != lead:
                old_lead=con.execute("SELECT author_name,function FROM users WHERE id=?",(old['lead_user_id'],)).fetchone() if old['lead_user_id'] else None
                new_lead=con.execute("SELECT author_name,function FROM users WHERE id=?",(lead,)).fetchone() if lead else None
                line=f"• Prowadzący: {_change_value(user_display_name(old_lead) if old_lead else '—')} → {_change_value(user_display_name(new_lead) if new_lead else '—')}"
                details=(details+'\n'+line).strip()
            if old_tags != sorted(new_tags, key=str.casefold):
                line=f"• Tagi: {_change_value(', '.join(old_tags))} → {_change_value(', '.join(new_tags))}"
                details=(details+'\n'+line).strip()
            con.execute("UPDATE cases SET signature=?,internal_signature=?,client=?,title=?,court=?,department=?,category=?,subject=?,status=?,waiting_for=?,next_step=?,next_date=?,notes=?,lead_user_id=?,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(*vals,lead,author,cid))
            set_case_tags(con,cid,f.get('tags',''))
            if details:
                audit(con,cid,'case',cid,'Edytowano dane sprawy',details,author)
        self.redirect(f'/case/{cid}')

    def case_delete_confirm(self,cid,message=''):
        if not self.require_admin(): return
        with db() as con:
            c=con.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone()
            if not c: return self.send_error(404)
            counts={
                'Dokumenty':con.execute('SELECT COUNT(*) FROM documents WHERE case_id=?',(cid,)).fetchone()[0],
                'Zadania':con.execute('SELECT COUNT(*) FROM tasks WHERE case_id=?',(cid,)).fetchone()[0],
                'Historia i zdarzenia':con.execute('SELECT (SELECT COUNT(*) FROM events WHERE case_id=?)+(SELECT COUNT(*) FROM process_events WHERE case_id=?)',(cid,cid)).fetchone()[0],
                'Osoby / podmioty':con.execute('SELECT (SELECT COUNT(*) FROM parties WHERE case_id=?)+(SELECT COUNT(*) FROM case_entities WHERE case_id=?)',(cid,cid)).fetchone()[0],
                'Powiązania':con.execute('SELECT COUNT(*) FROM case_relations WHERE source_case_id=? OR target_case_id=?',(cid,cid)).fetchone()[0],
            }
        status=STATUS_LABELS.get(c['status'],c['status'])
        msg=f"<div class='error'>{esc(message)}</div>" if message else ''
        count_rows=''.join(f"<tr><th>{esc(label)}</th><td>{int(value)}</td></tr>" for label,value in counts.items())
        closed_note='' if c['status']=='closed' else "<div class='error'><b>Najpierw oznacz sprawę jako zakończoną.</b> Aktywnej sprawy nie można trwale usunąć.</div>"
        disabled=' disabled' if c['status']!='closed' else ''
        body=f"""<div class='topbar'><div><h1>Usuń duplikat sprawy</h1><div class='sub'>{esc(c['signature'] or c['internal_signature'] or c['title'])}</div></div><a class='btn' href='/case/{cid}'>← Wróć</a></div>{msg}{closed_note}
        <div class='grid'><div class='card span7 danger-zone'><h2>Operacja nieodwracalna</h2><p>Usunięta zostanie sprawa <b>{esc(c['title'])}</b> wraz z danymi przypisanymi wyłącznie do niej. Status: <b>{esc(status)}</b>.</p><p><b>Przed usunięciem program automatycznie zapisze pełny snapshot</b> bazy, dokumentów i projektów pism w katalogu danych programu.</p><form method='post' action='/case/{cid}/delete'><label>Wpisz dokładnie <b>USUŃ</b></label><input name='confirmation' autocomplete='off' required><label style='font-weight:500'><input style='width:auto' type='checkbox' name='acknowledge' value='1' required> Potwierdzam, że sprawdziłem/am, iż jest to duplikat.</label><button class='btn danger'{disabled}>Utwórz snapshot i usuń sprawę</button></form></div><div class='card span5'><h2>Zawartość sprawy</h2><table>{count_rows}</table><p class='small muted'>Powiązania z innymi sprawami zostaną usunięte. Wspólne rekordy osób w Kartotece pozostaną bez zmian.</p></div></div>"""
        self.send_html(layout('Bezpieczne usuwanie sprawy',body,'cases'))

    def case_delete(self,cid,f):
        if not self.require_admin(): return
        with db() as con:
            c=con.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone()
        if not c: return self.send_error(404)
        if c['status']!='closed':
            return self.case_delete_confirm(cid,'Aktywnej sprawy nie można trwale usunąć. Najpierw ustaw status „Zakończona”.')
        if (f.get('confirmation','') or '').strip()!='USUŃ' or f.get('acknowledge')!='1':
            return self.case_delete_confirm(cid,'Nie potwierdzono usunięcia. Wpisz dokładnie „USUŃ” i zaznacz pole potwierdzenia.')

        # Usunięcie całej sprawy omija zwykły Kosz, dlatego najpierw powstaje
        # kompletny, przenośny snapshot możliwy do odtworzenia z ekranu Recovery.
        raw,snapshot_name=create_data_snapshot_zip()
        backup_dir=DATA_DIR/'backup_przed_usunieciem_sprawy'
        backup_dir.mkdir(parents=True,exist_ok=True)
        backup_path=backup_dir/f"sprawa_{cid}_{snapshot_name}"
        atomic_write_bytes(backup_path,raw)

        author=self.current_author(f); folder=FILES_DIR/f"sprawa_{cid}"
        with db() as con:
            immutable_audit(con,None,'case',cid,'Trwale usunięto sprawę po wykonaniu snapshotu',
                            f"{c['title']} · kopia: {backup_path.name}",author)
            con.execute("DELETE FROM cases WHERE id=?",(cid,))
        if folder.exists():
            try: shutil.rmtree(folder)
            except Exception as exc: log_app_exception(f'/case/{cid}/delete-files',exc)
        self.redirect("/cases?deleted=1")

    def case_pin_toggle(self,cid,f):
        u=current_request_user()
        if not u: return self.redirect(f'/case/{cid}')
        with db() as con:
            if con.execute("SELECT 1 FROM user_case_pins WHERE user_id=? AND case_id=?",(u['id'],cid)).fetchone():
                con.execute("DELETE FROM user_case_pins WHERE user_id=? AND case_id=?",(u['id'],cid))
            else:
                con.execute("INSERT OR IGNORE INTO user_case_pins(user_id,case_id) VALUES(?,?)",(u['id'],cid))
        ref=self.headers.get('Referer','')
        self.redirect(urlparse(ref).path + (('?' + urlparse(ref).query) if urlparse(ref).query else '') if ref else f'/case/{cid}')

    def case_duplicate(self,cid,f):
        a=self.current_author(f)
        with db() as con:
            c=con.execute("SELECT * FROM cases WHERE id=?",(cid,)).fetchone()
            if not c: return self.send_error(404)
            title=(c['title']+' — kopia')[:300]
            cur=con.execute("""INSERT INTO cases(signature,internal_signature,client,title,court,department,category,subject,status,waiting_for,next_step,next_date,notes,lead_user_id,created_by,updated_by)
                VALUES('','',?,?,?,?,?,?, 'active','','','',?, ?,?,?)""",(c['client'],title,c['court'],c['department'],c['category'],c['subject'],c['notes'],c['lead_user_id'],a,a))
            new_id=cur.lastrowid
            for t in con.execute("SELECT tag_id FROM case_tags WHERE case_id=?",(cid,)).fetchall():
                con.execute("INSERT OR IGNORE INTO case_tags(case_id,tag_id) VALUES(?,?)",(new_id,t['tag_id']))
            audit(con,new_id,'case',new_id,'Utworzono przez duplikowanie',f"Na podstawie sprawy #{cid}: {c['title']}",a)
        self.redirect(f'/case/{new_id}/edit')

    def external_signature_add(self,cid,f):
        label=(f.get('label','') or '').strip()[:160]
        signature=(f.get('signature','') or '').strip()[:240]
        if not label or not signature:
            return self.redirect(f"/case/{cid}")
        author=self.current_author(f)
        with db() as con:
            if con.execute("SELECT 1 FROM cases WHERE id=?",(cid,)).fetchone():
                cur=con.execute("INSERT INTO case_external_signatures(case_id,label,signature,created_by,updated_by) VALUES(?,?,?,?,?)",(cid,label,signature,author,author))
                audit(con,cid,'external_signature',cur.lastrowid,'Dodano dodatkową sygnaturę',f"{label}: {signature}",author)
        self.redirect(f"/case/{cid}")

    def external_signature_edit(self,sid):
        with db() as con:
            x=con.execute("SELECT e.*,c.title case_title,c.signature case_signature,c.internal_signature case_internal FROM case_external_signatures e JOIN cases c ON c.id=e.case_id WHERE e.id=?",(sid,)).fetchone()
        if not x:
            return self.send_error(404)
        case_label=x['case_signature'] or x['case_internal'] or x['case_title']
        body=f'''<div class="topbar"><div><h1>Edytuj dodatkową sygnaturę</h1><div class="sub">{esc(case_label)} · {esc(x['case_title'])}</div></div><a class="btn" href="/case/{x['case_id']}">Wróć</a></div><div class="card"><form method="post" action="/external-signature/{sid}/update" class="form-grid" data-autosave="1"><input type="hidden" name="case_id" value="{x['case_id']}"><div><label>Nazwa pola</label><input name="label" required value="{esc(x['label'])}"></div><div><label>Sygnatura / numer</label><input name="signature" required value="{esc(x['signature'])}"></div><div class="full"><button class="btn primary">Zapisz</button></div></form></div>'''
        self.send_html(layout('Edytuj sygnaturę',body,'cases'))

    def external_signature_update(self,sid,f):
        try:
            cid=int(f.get('case_id','0') or 0)
        except ValueError:
            cid=0
        label=(f.get('label','') or '').strip()[:160]
        signature=(f.get('signature','') or '').strip()[:240]
        author=self.current_author(f)
        with db() as con:
            row=con.execute("SELECT * FROM case_external_signatures WHERE id=?",(sid,)).fetchone()
            if row:
                cid=row['case_id']
                if label and signature:
                    details=describe_changes(row,{'label':label,'signature':signature},{'label':'Nazwa pola','signature':'Sygnatura / numer'})
                    con.execute("UPDATE case_external_signatures SET label=?,signature=?,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(label,signature,author,sid))
                    if details: audit(con,cid,'external_signature',sid,'Edytowano dodatkową sygnaturę',details,author)
        self.redirect(f"/case/{cid}" if cid else '/cases')

    def external_signature_delete(self,sid,f):
        try: cid=int(f.get('case_id','0') or 0)
        except ValueError: cid=0
        a=self.current_author(f)
        with db() as con:
            row=con.execute("SELECT case_id FROM case_external_signatures WHERE id=?",(sid,)).fetchone(); cid=row['case_id'] if row else cid
            move_to_trash(con,'external_signature',sid,a)
        self.redirect(f"/case/{cid}" if cid else '/cases')

    def relation_add(self,cid,f):
        try: target=int(f.get('target_case_id','0') or 0)
        except ValueError: target=0
        rtype=f.get('relation_type','related'); rtype=rtype if rtype in RELATION_TYPES else 'related'
        return_to=(f.get('return_to','') or '').strip()
        fallback=f"/case/{cid}?tab=relations"
        if not target or target==cid: return self.redirect(return_to if return_to.startswith('/') else fallback)
        author=self.current_author(f)
        with db() as con:
            if con.execute("SELECT 1 FROM cases WHERE id=?",(target,)).fetchone():
                duplicate=con.execute('''SELECT id FROM case_relations WHERE relation_type=? AND
                    ((source_case_id=? AND target_case_id=?) OR (source_case_id=? AND target_case_id=?)) LIMIT 1''',
                    (rtype,cid,target,target,cid)).fetchone()
                if not duplicate:
                    cur=con.execute("INSERT INTO case_relations(source_case_id,target_case_id,relation_type,note,created_by,updated_by) VALUES(?,?,?,?,?,?)",(cid,target,rtype,f.get('note','').strip(),author,author))
                    audit(con,cid,'relation',cur.lastrowid,'Dodano powiązanie',RELATION_TYPES.get(rtype,(rtype,rtype))[0],author)
        self.redirect(return_to if return_to.startswith('/') else fallback)

    def relation_edit(self,rid):
        with db() as con:
            r=con.execute("SELECT * FROM case_relations WHERE id=?",(rid,)).fetchone()
            if not r:
                return self.send_error(404)
            cases=con.execute("SELECT id,signature,title FROM cases ORDER BY signature='',signature,title").fetchall()
        source_opts=''.join(
            f"<option value='{c['id']}' {'selected' if c['id']==r['source_case_id'] else ''}>{esc((c['signature']+' — ') if c['signature'] else '')}{esc(c['title'])}</option>"
            for c in cases if c['id']!=r['target_case_id']
        )
        target_opts=''.join(
            f"<option value='{c['id']}' {'selected' if c['id']==r['target_case_id'] else ''}>{esc((c['signature']+' — ') if c['signature'] else '')}{esc(c['title'])}</option>"
            for c in cases if c['id']!=r['source_case_id']
        )
        type_opts=''.join(
            f"<option value='{esc(k)}' {'selected' if k==r['relation_type'] else ''}>{esc(v[0])} → {esc(v[1])}</option>"
            for k,v in RELATION_TYPES.items()
        )
        body=f'''<div class="topbar"><div><h1>Edytuj powiązanie</h1><div class="sub">Relacja między dwiema sprawami</div></div></div>
        <div class="card"><form method="post" action="/relation/{rid}/update" class="form-grid" data-autosave="1">
        <div><label>Sprawa bazowa</label><select name="source_case_id" required>{source_opts}</select></div>
        <div><label>Sprawa powiązana</label><select name="target_case_id" required>{target_opts}</select></div>
        <div class="full"><label>Typ relacji</label><select name="relation_type">{type_opts}</select><div class="small muted">Dla relacji „II instancja” sprawa bazowa jest I instancją, a sprawa powiązana — II instancją.</div></div>
        <div class="full"><label>Notatka</label><textarea name="note">{esc(r['note'])}</textarea></div>
        <input type="hidden" name="return_to" value="/case/{r['source_case_id']}?tab=relations">
        <div class="full"><button class="btn primary">Zapisz zmiany</button> <a class="btn" href="/case/{r['source_case_id']}?tab=relations">Anuluj</a></div>
        </form></div>'''
        self.send_html(layout("Edycja powiązania",body,"cases"))

    def relation_update(self,rid,f):
        try: source=int(f.get('source_case_id','0') or 0); target=int(f.get('target_case_id','0') or 0)
        except ValueError: return self.redirect('/cases')
        rtype=f.get('relation_type','related'); rtype=rtype if rtype in RELATION_TYPES else 'related'; author=self.current_author(f)
        note=f.get('note','').strip()
        if source and target and source!=target:
            with db() as con:
                old=con.execute("SELECT * FROM case_relations WHERE id=?",(rid,)).fetchone()
                duplicate=con.execute('''SELECT id FROM case_relations WHERE id<>? AND relation_type=? AND
                    ((source_case_id=? AND target_case_id=?) OR (source_case_id=? AND target_case_id=?)) LIMIT 1''',
                    (rid,rtype,source,target,target,source)).fetchone()
                if old and not duplicate and con.execute("SELECT COUNT(*) FROM cases WHERE id IN (?,?)",(source,target)).fetchone()[0]==2:
                    def case_name(xid):
                        row=con.execute("SELECT signature,internal_signature,title FROM cases WHERE id=?",(xid,)).fetchone()
                        if not row: return f'#{xid}'
                        return primary_signature_text(xid,row['signature'],row['internal_signature']) if (row['signature'] or row['internal_signature']) else row['title']
                    detail_lines=[]
                    if old['source_case_id']!=source:
                        detail_lines.append(f"• Sprawa bazowa: {_change_value(case_name(old['source_case_id']))} → {_change_value(case_name(source))}")
                    if old['target_case_id']!=target:
                        detail_lines.append(f"• Sprawa powiązana: {_change_value(case_name(old['target_case_id']))} → {_change_value(case_name(target))}")
                    if old['relation_type']!=rtype:
                        old_type=RELATION_TYPES.get(old['relation_type'],(old['relation_type'],old['relation_type']))[0]
                        new_type=RELATION_TYPES.get(rtype,(rtype,rtype))[0]
                        detail_lines.append(f"• Typ relacji: {_change_value(old_type)} → {_change_value(new_type)}")
                    if (old['note'] or '')!=note:
                        detail_lines.append(f"• Notatka: {_change_value(old['note'])} → {_change_value(note)}")
                    con.execute("UPDATE case_relations SET source_case_id=?,target_case_id=?,relation_type=?,note=?,updated_by=? WHERE id=?",(source,target,rtype,note,author,rid))
                    if detail_lines: audit(con,source,'relation',rid,'Edytowano powiązanie','\n'.join(detail_lines),author)
        target_url=(f.get('return_to','') or '').strip()
        self.redirect(target_url if target_url.startswith('/') else (f"/case/{source}?tab=relations" if source else '/cases'))

    def relation_delete(self,rid,f):
        try: cid=int(f.get('case_id','0') or 0)
        except ValueError: cid=0
        a=self.current_author(f)
        with db() as con: move_to_trash(con,'relation',rid,a)
        target=(f.get('return_to','') or '').strip()
        self.redirect(target if target.startswith('/') else (f"/case/{cid}?tab=relations" if cid else '/cases'))

    def party_edit(self,pid):
        with db() as con:
            p=con.execute("SELECT p.*,c.signature,c.title case_title FROM parties p JOIN cases c ON c.id=p.case_id WHERE p.id=?",(pid,)).fetchone()
        if not p: return self.send_error(404)
        body=f'''<div class="topbar"><div><h1>Edytuj osobę</h1><div class="sub">{esc(p['signature'] or p['case_title'])}</div></div></div><div class="card"><form method="post" action="/party/{pid}/update" class="form-grid" data-autosave="1"><input type="hidden" name="case_id" value="{p['case_id']}"><div><label>Imię i nazwisko</label><input name="name" required value="{esc(p['name'])}"></div><div><label>Rola</label><input name="role" value="{esc(p['role'])}"></div><div class="full"><label>Notatka</label><textarea name="notes">{esc(p['notes'])}</textarea></div><div class="full"><button class="btn primary">Zapisz zmiany</button> <a class="btn" href="/case/{p['case_id']}">Anuluj</a></div></form></div>'''
        self.send_html(layout("Edycja osoby",body,"cases"))

    def party_update(self,pid,f):
        cid=int(f.get('case_id','0') or 0); a=self.current_author(f)
        new={'name':f.get('name','').strip(),'role':f.get('role','').strip(),'notes':f.get('notes','').strip()}
        with db() as con:
            old=con.execute("SELECT * FROM parties WHERE id=?",(pid,)).fetchone()
            if not old: return self.send_error(404)
            cid=old['case_id']
            details=describe_changes(old,new,{'name':'Imię i nazwisko','role':'Rola','notes':'Notatka'},compact_fields={'notes'})
            con.execute("UPDATE parties SET name=?,role=?,notes=?,updated_by=? WHERE id=?",(new['name'],new['role'],new['notes'],a,pid))
            if details: audit(con,cid,'party',pid,'Edytowano uczestnika',details,a)
        self.redirect(f"/case/{cid}")

    def event_edit(self,eid):
        with db() as con:
            e=con.execute("SELECT e.*,c.signature,c.title case_title FROM events e JOIN cases c ON c.id=e.case_id WHERE e.id=?",(eid,)).fetchone()
        if not e: return self.send_error(404)
        opts=''.join(f"<option value='{esc(x)}' {'selected' if e['event_type']==x else ''}>{esc(x)}</option>" for x in EVENT_TYPES)
        body=f'''<div class="topbar"><div><h1>Edytuj zdarzenie</h1><div class="sub">{esc(e['signature'] or e['case_title'])}</div></div></div><div class="card"><form method="post" action="/event/{eid}/update" class="form-grid" data-autosave="1"><input type="hidden" name="case_id" value="{e['case_id']}"><div><label>Data</label><input type="date" name="event_date" value="{esc(e['event_date'])}"></div><div><label>Typ</label><select name="event_type">{opts}</select></div><div class="full"><label>Tytuł</label><input name="title" required value="{esc(e['title'])}"></div><div class="full"><label>Opis</label><textarea name="description">{esc(e['description'])}</textarea></div><div class="full"><button class="btn primary">Zapisz zmiany</button> <a class="btn" href="/case/{e['case_id']}">Anuluj</a></div></form></div>'''
        self.send_html(layout("Edycja zdarzenia",body,"cases"))

    def event_update(self,eid,f):
        cid=int(f.get('case_id','0') or 0); a=self.current_author(f)
        new={'event_date':f.get('event_date',''),'event_type':f.get('event_type','Czynność'),'title':f.get('title','').strip(),'description':f.get('description','').strip()}
        with db() as con:
            old=con.execute("SELECT * FROM events WHERE id=?",(eid,)).fetchone()
            if not old: return self.send_error(404)
            cid=old['case_id']
            details=describe_changes(old,new,{'event_date':'Data','event_type':'Typ','title':'Tytuł','description':'Opis'},compact_fields={'description'})
            con.execute("UPDATE events SET event_date=?,event_type=?,title=?,description=?,updated_by=? WHERE id=?",(new['event_date'],new['event_type'],new['title'],new['description'],a,eid))
            if details: audit(con,cid,'event',eid,'Edytowano zdarzenie',details,a)
        self.redirect(f"/case/{cid}")

    def task_edit(self,tid,qs=None):
        qs=qs or {}
        return_to=(qs.get('return_to') or [''])[0].strip()
        with db() as con:
            t=con.execute("SELECT t.*,c.signature,c.title case_title FROM tasks t JOIN cases c ON c.id=t.case_id WHERE t.id=?",(tid,)).fetchone()
            users=con.execute("SELECT id,author_name,function FROM users WHERE is_active=1 ORDER BY author_name").fetchall()
        if not t: return self.send_error(404)
        prio='<option value="normal" {n}>Normalny</option><option value="high" {h}>Wysoki</option>'.format(n='selected' if t['priority']=='normal' else '',h='selected' if t['priority']=='high' else '')
        stat='<option value="open" {o}>Otwarte</option><option value="done" {d}>Wykonane</option>'.format(o='selected' if t['status']=='open' else '',d='selected' if t['status']=='done' else '')
        user_opts='<option value="">— nie przypisano —</option>'+''.join(f"<option value='{u['id']}' {'selected' if t['assigned_user_id']==u['id'] else ''}>{esc(user_display_name(u))}</option>" for u in users)
        type_opts=''.join(f"<option value='{esc(x)}' {'selected' if row_get(t,'task_type','Zadanie')==x else ''}>{esc(x)}</option>" for x in ["Zadanie","Monit","Termin procesowy","Płatność"])
        back_href=return_to if return_to.startswith('/') else f"/case/{t['case_id']}"
        deadline_info=''
        if row_get(t,'deadline_base_date',''):
            manual=' · <b>termin skorygowany ręcznie</b>' if int(row_get(t,'deadline_manual',0) or 0) else ''
            deadline_info=f"<div class='notice deadline-note'><b>Termin wyliczony pomocniczo:</b> od {fmt_date(t['deadline_base_date'])} + {esc(str(row_get(t,'deadline_days','')))} {esc(row_get(t,'deadline_rule',''))}. {esc(row_get(t,'deadline_source',''))}{manual}</div>"
        body=f'''<div class="topbar"><div><h1>Edytuj zadanie</h1><div class="sub">{esc(t['signature'] or t['case_title'])}</div></div></div>{deadline_info}<div class="card"><form method="post" action="/task/{tid}/update" class="form-grid" data-autosave="1"><input type="hidden" name="case_id" value="{t['case_id']}"><input type="hidden" name="return_to" value="{esc(return_to)}"><div><label>Rodzaj</label><select name="task_type">{type_opts}</select></div><div class="full"><label>Zadanie</label><input name="title" required value="{esc(t['title'])}"></div><div><label>Termin</label><input type="date" name="due_date" value="{esc(t['due_date'])}"><div class="small muted">Możesz ręcznie skorygować termin. Historia zachowa zmianę.</div></div><div><label>Priorytet</label><select name="priority">{prio}</select></div><div><label>Status</label><select name="status">{stat}</select></div><div><label>Wykonawca</label><select name="assigned_user_id">{user_opts}</select></div><div class="full"><label>Zależność / czekamy na</label><input name="depends_on" value="{esc(t['depends_on'])}"></div><div class="full"><label>Notatki</label><textarea name="notes">{esc(t['notes'])}</textarea></div><div class="full"><button class="btn primary">Zapisz zmiany</button> <a class="btn" href="{esc(back_href)}">Anuluj</a></div></form></div>'''
        self.send_html(layout('Edycja zadania',body,'tasks'))


    def task_update(self,tid,f):
        cid=int(f.get('case_id','0') or 0); a=self.current_author(f)
        try: assigned=int(f.get('assigned_user_id','') or 0) or None
        except ValueError: assigned=None
        task_type=(f.get('task_type') or 'Zadanie').strip()
        if task_type not in ACTIONABLE_ALERT_TYPES:
            task_type='Zadanie'
        new={
            'title':f.get('title','').strip(),'due_date':f.get('due_date',''),'status':f.get('status','open'),
            'priority':f.get('priority','normal'),'assigned_user_id':assigned,'depends_on':f.get('depends_on','').strip(),
            'notes':f.get('notes','').strip(),'task_type':task_type
        }
        with db() as con:
            old=con.execute("SELECT * FROM tasks WHERE id=?",(tid,)).fetchone()
            if not old: return self.send_error(404)
            cid=old['case_id']
            details=describe_changes(old,new,{
                'title':'Zadanie','task_type':'Rodzaj','due_date':'Termin','status':'Status','priority':'Priorytet',
                'depends_on':'Zależność / czekamy na','notes':'Notatki'
            },compact_fields={'notes'})
            if old['assigned_user_id'] != assigned:
                old_u=con.execute("SELECT author_name,function FROM users WHERE id=?",(old['assigned_user_id'],)).fetchone() if old['assigned_user_id'] else None
                new_u=con.execute("SELECT author_name,function FROM users WHERE id=?",(assigned,)).fetchone() if assigned else None
                line=f"• Wykonawca: {_change_value(user_display_name(old_u) if old_u else '—')} → {_change_value(user_display_name(new_u) if new_u else '—')}"
                details=(details+'\n'+line).strip()
            deadline_manual=int(row_get(old,'deadline_manual',0) or 0)
            if row_get(old,'deadline_base_date','') and old['due_date'] != new['due_date']:
                deadline_manual=1
                details=(details+'\n'+f"• Tryb terminu: {_change_value('wyliczony automatycznie')} → {_change_value('skorygowany ręcznie')}").strip()
            completed_at=row_get(old,'completed_at',''); completed_by=row_get(old,'completed_by','')
            if old['status']!='done' and new['status']=='done':
                completed_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'); completed_by=a
            elif old['status']=='done' and new['status']!='done':
                completed_at=''; completed_by=''
            con.execute("""UPDATE tasks SET title=?,due_date=?,status=?,priority=?,assigned_user_id=?,depends_on=?,notes=?,
                           task_type=?,updated_by=?,deadline_manual=?,completed_at=?,completed_by=? WHERE id=?""",
                        (new['title'],new['due_date'],new['status'],new['priority'],assigned,new['depends_on'],new['notes'],
                         task_type,a,deadline_manual,completed_at,completed_by,tid))
            sync_task_alert(con,tid,a)
            if details: audit(con,cid,'task',tid,'Edytowano zadanie',details,a)
        target=(f.get('return_to','') or '').strip()
        self.redirect(target if target.startswith('/') else f'/case/{cid}')

    def document_edit(self,did):
        with db() as con:
            d=con.execute("SELECT d.*,c.signature,c.title case_title FROM documents d JOIN cases c ON c.id=d.case_id WHERE d.id=?",(did,)).fetchone()
            if d and case_read_only(con,d['case_id']):
                return self.send_html(layout('Sprawa tylko do odczytu',f"<div class='readonly-banner'>Sprawa jest zakończona i zablokowana. <a class='btn' href='/case/{d['case_id']}'>Wróć</a></div>",'documents'),403)
            tasks=con.execute("SELECT id,title,due_date,status FROM tasks WHERE case_id=? ORDER BY status,CASE WHEN due_date='' THEN 1 ELSE 0 END,due_date,id",(d['case_id'],)).fetchall() if d else []
            versions=con.execute("SELECT * FROM document_versions WHERE document_id=? ORDER BY version_no DESC",(did,)).fetchall() if d else []
            children=con.execute("SELECT id,title,original_name FROM documents WHERE parent_document_id=? ORDER BY attachment_order,id",(did,)).fetchall() if d else []
        if not d: return self.send_error(404)
        opts=''.join(f"<option value='{esc(x)}' {'selected' if d['doc_type']==x else ''}>{esc(x)}</option>" for x in DOC_TYPES)
        status_opts=''.join(f"<option value='{esc(x)}' {'selected' if d['doc_status']==x else ''}>{esc(x)}</option>" for x in DOC_STATUSES)
        task_opts=['<option value="">— bez powiązanego zadania / terminu —</option>']
        for t in tasks:
            label=t['title']+((' · '+fmt_date(t['due_date'])) if t['due_date'] else '')
            task_opts.append(f"<option value='{t['id']}' {'selected' if row_get(d,'linked_task_id',None)==t['id'] else ''}>{esc(label)}</option>")
        current=f"Aktualny plik: <b>{esc(d['original_name'])}</b>" if d['stored_name'] else "Brak podpiętego pliku."
        idx=f"Zindeksowano: {esc(d['indexed_at'])}" if d['indexed_at'] else 'Treść nie była jeszcze indeksowana.'
        version_rows=''.join(f"<tr><td>v{x['version_no']}</td><td>{esc(str(x['created_at'])[:16])}</td><td>{esc(x['original_name'])}</td><td>{esc(x['created_by'])}</td><td><form method='post' action='/document/{did}/version/{x['id']}/restore' onsubmit=\"return confirm('Przywrócić tę wersję pliku? Bieżący plik zostanie wcześniej zachowany jako kolejna wersja.');\"><button class='btn small'>Przywróć</button></form></td></tr>" for x in versions)
        versions_card=f"<div class='card'><h2>Historia wersji pliku</h2><p class='small muted'>Poprzedni plik jest automatycznie zachowywany przed każdą podmianą.</p><table><tr><th>Wersja</th><th>Data</th><th>Plik</th><th>Autor</th><th></th></tr>{version_rows or '<tr><td colspan=5>Brak starszych wersji.</td></tr>'}</table></div>"
        attachment_rows=''.join(f"<div class='document-attachment-item'><span>📎 <a href='/document/{x['id']}/open'><b>{esc(x['title'])}</b></a><small class='muted'> · {esc(x['original_name'] or 'bez pliku')}</small></span><span><a class='btn small' href='/document/{x['id']}/edit'>Edytuj</a> <form class='inline' method='post' action='/document/{x['id']}/delete' onsubmit=\"return confirm('Przenieść ten załącznik do Kosza?');\"><input type='hidden' name='case_id' value='{d['case_id']}'><input type='hidden' name='return_to' value='/document/{did}/edit'><button class='btn small danger'>Do kosza</button></form></span></div>" for x in children)
        attachments_field='' if row_get(d,'parent_document_id',None) else f'''<div class="full"><label>Dodaj kolejne załączniki</label><input type="file" name="attachments[]" multiple><div class="small muted">Możesz wskazać kilka plików naraz. Zostaną dopisane pod tym dokumentem bez usuwania obecnych załączników.</div></div>'''
        attachment_content=attachment_rows or "<div class='empty'>Brak załączników. Dodaj je w formularzu powyżej.</div>"
        attachments_card='' if row_get(d,'parent_document_id',None) else f"<br><div class='card'><h2>Załączniki ({len(children)})</h2><div class='document-attachment-list'>{attachment_content}</div></div>"
        body=f'''<div class="topbar"><div><h1>Edytuj dokument</h1><div class="sub">{esc(d['signature'] or d['case_title'])}</div></div></div><div class="card"><form method="post" enctype="multipart/form-data" action="/document/{did}/update" class="form-grid"><input type="hidden" name="case_id" value="{d['case_id']}"><input type="hidden" name="return_to" value="/case/{d['case_id']}?tab=documents"><div><label>Data dokumentu</label><input type="date" name="doc_date" value="{esc(d['doc_date'])}"></div><div><label>Data wpływu</label><input type="date" name="received_date" value="{esc(d['received_date'])}"></div><div><label>Data doręczenia</label><input type="date" name="delivered_date" value="{esc(row_get(d,'delivered_date',''))}"></div><div><label>Rodzaj</label><select name="doc_type">{opts}</select></div><div><label>Status dokumentu</label><select name="doc_status">{status_opts}</select></div><div><label>Nadawca</label><input name="sender" value="{esc(row_get(d,'sender',''))}"></div><div><label>Autor dokumentu</label><input name="document_author" value="{esc(row_get(d,'document_author',''))}"></div><div><label>Tagi</label><input name="tags" value="{esc(row_get(d,'tags',''))}" placeholder="np. dowód, odpowiedź, pilne"></div><div class="full"><label>Powiązane zadanie / termin</label><select name="linked_task_id">{''.join(task_opts)}</select></div><div class="full"><label>Tytuł</label><input name="title" required value="{esc(d['title'])}"></div><div class="full"><label>Opis</label><textarea name="description">{esc(d['description'])}</textarea></div><div class="full"><label>Podmień / dodaj plik główny</label><input type="file" name="file"><div class="small muted">{current} Wybranie nowego pliku automatycznie zachowa poprzednią wersję. {idx}</div><label style="font-weight:500"><input style="width:auto" type="checkbox" name="allow_duplicate" value="1"> Zezwól na identyczny plik, jeśli świadomie chcę duplikat</label></div>{attachments_field}<div class="full"><button class="btn primary">Zapisz zmiany</button> <a class="btn" href="/case/{d['case_id']}?tab=documents">Anuluj</a></div></form></div>{attachments_card}<br>{versions_card}'''
        self.send_html(layout("Edycja dokumentu",body,"documents"))

    def document_update(self,did,f,files):
        a=self.current_author(f)
        title=(f.get('title','') or '').strip()
        if not title:
            return self.send_html(layout('Brak tytułu',f"<div class='error'>Tytuł dokumentu jest wymagany.</div><a class='btn' href='/document/{did}/edit'>Wróć</a>",'documents'),400)
        main_upload=files.get('file') if isinstance(files,dict) else None
        if isinstance(main_upload,list): main_upload=main_upload[0] if main_upload else None
        attachment_files=files.get('attachments[]',[]) if isinstance(files,dict) else []
        if isinstance(attachment_files,tuple): attachment_files=[attachment_files]
        attachment_files=[x for x in attachment_files if x and x[0]]
        indexed_ids=[]
        with db() as con:
            d=con.execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone()
            if not d: return self.send_error(404)
            if case_read_only(con,d['case_id']): return self.send_error(403,'Sprawa zakończona jest tylko do odczytu.')
            if row_get(d,'parent_document_id',None): attachment_files=[]
            cid=d['case_id']; stored=d['stored_name']; original=d['original_name']; newdata=None; oldstored=''
            if main_upload and main_upload[0]:
                original=safe_filename(main_upload[0]); newdata=main_upload[1]

            # Wszystkie konflikty sprawdzamy przed zapisaniem pierwszego pliku,
            # aby częściowo wykonana edycja nie zostawiła osieroconych załączników.
            upload_hashes=[]
            if newdata is not None: upload_hashes.append(('plik główny',sha256_bytes(newdata),did))
            upload_hashes.extend((safe_filename(x[0]),sha256_bytes(x[1]),None) for x in attachment_files)
            if not f.get('allow_duplicate'):
                seen=set()
                for label_text,file_hash,excluded_id in upload_hashes:
                    if file_hash in seen:
                        body=f"<div class='conflict-box'><h1>Powtórzony plik</h1><p>Plik <b>{esc(label_text)}</b> został wybrany więcej niż raz.</p><a class='btn' href='/document/{did}/edit'>Wróć</a></div>"
                        return self.send_html(layout('Wykryto duplikat',body,'documents'),409)
                    seen.add(file_hash)
                    sql="SELECT d.id,d.title,d.case_id,c.signature,c.internal_signature FROM documents d JOIN cases c ON c.id=d.case_id WHERE d.file_hash=?"
                    params=[file_hash]
                    if excluded_id: sql+=' AND d.id<>?'; params.append(excluded_id)
                    dup=con.execute(sql+' LIMIT 1',params).fetchone()
                    if dup:
                        case_label=primary_signature_text(dup['case_id'],dup['signature'],dup['internal_signature'])
                        body=f"<div class='conflict-box'><h1>Identyczny dokument już istnieje</h1><p>Plik <b>{esc(label_text)}</b> jest już zapisany jako <b>{esc(dup['title'])}</b> w sprawie <a href='/case/{dup['case_id']}'>{esc(case_label)}</a>.</p><p>Jeśli to celowe, wróć i zaznacz „Zezwól na identyczny plik”.</p><a class='btn' href='/document/{did}/edit'>Wróć</a></div>"
                        return self.send_html(layout('Wykryto duplikat',body,'documents'),409)

            folder=FILES_DIR/f"sprawa_{cid}"; folder.mkdir(parents=True,exist_ok=True)
            if newdata is not None:
                oldstored=stored
                newstored=f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{original}"
                atomic_write_bytes(folder/newstored,newdata); stored=newstored
            try: linked=int(f.get('linked_task_id') or 0) or None
            except Exception: linked=None
            if linked and not con.execute('SELECT 1 FROM tasks WHERE id=? AND case_id=?',(linked,cid)).fetchone(): linked=None
            new_values={
                'doc_date':f.get('doc_date',''),'received_date':f.get('received_date',''),'delivered_date':f.get('delivered_date',''),
                'doc_type':f.get('doc_type','Inne'),'doc_status':f.get('doc_status','Aktywny'),'title':title,
                'description':f.get('description','').strip(),'sender':f.get('sender','').strip(),
                'document_author':f.get('document_author','').strip(),'tags':f.get('tags','').strip(),'linked_task_id':linked
            }
            details=describe_changes(d,new_values,{
                'doc_date':'Data dokumentu','received_date':'Data wpływu','delivered_date':'Data doręczenia','doc_type':'Rodzaj',
                'doc_status':'Status dokumentu','title':'Tytuł','description':'Opis','sender':'Nadawca','document_author':'Autor dokumentu','tags':'Tagi'
            },compact_fields={'description'})
            if row_get(d,'linked_task_id',None) != linked:
                old_t=con.execute('SELECT title FROM tasks WHERE id=?',(row_get(d,'linked_task_id',None),)).fetchone() if row_get(d,'linked_task_id',None) else None
                new_t=con.execute('SELECT title FROM tasks WHERE id=?',(linked,)).fetchone() if linked else None
                details=(details+'\n'+f"• Powiązane zadanie / termin: {_change_value(old_t['title'] if old_t else '—')} → {_change_value(new_t['title'] if new_t else '—')}").strip()
            if newdata is not None:
                details=(details+'\n'+f"• Plik: {_change_value(d['original_name'])} → {_change_value(original)}").strip()
                save_document_file_version(con,did,a)
            con.execute("UPDATE documents SET doc_date=?,received_date=?,delivered_date=?,doc_type=?,doc_status=?,title=?,description=?,sender=?,document_author=?,tags=?,linked_task_id=?,stored_name=?,original_name=?,updated_by=? WHERE id=?",
                        (new_values['doc_date'],new_values['received_date'],new_values['delivered_date'],new_values['doc_type'],new_values['doc_status'],title,new_values['description'],new_values['sender'],new_values['document_author'],new_values['tags'],linked,stored,original,a,did))
            if newdata is not None:
                con.execute("UPDATE documents SET file_hash=?,extracted_text='',indexed_at='',ocr_status='kolejka' WHERE id=?",(sha256_bytes(newdata),did))
                indexed_ids.append(did)
                if oldstored:
                    try: (folder/oldstored).unlink(missing_ok=True)
                    except Exception: pass
            else:
                try:
                    cur=con.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone(); con.execute('DELETE FROM document_fts WHERE document_id=?',(did,)); con.execute('INSERT INTO document_fts(document_id,case_id,title,filename,body) VALUES(?,?,?,?,?)',(did,cid,cur['title'],cur['original_name'],cur['extracted_text']))
                except sqlite3.DatabaseError: pass

            next_order=int(con.execute('SELECT COALESCE(MAX(attachment_order),0)+1 FROM documents WHERE parent_document_id=?',(did,)).fetchone()[0])
            for offset,item in enumerate(attachment_files):
                aname=safe_filename(item[0]); adata=item[1]
                astored=f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{aname}"
                atomic_write_bytes(folder/astored,adata)
                atitle=Path(aname).stem or f"Załącznik {next_order+offset}"
                acur=con.execute('''INSERT INTO documents(case_id,doc_date,received_date,delivered_date,doc_type,doc_status,title,description,
                    sender,document_author,tags,linked_task_id,stored_name,original_name,parent_document_id,attachment_order,
                    created_by,updated_by,file_hash,ocr_status) VALUES(?,?,?,?,?,'Aktywny',?,'',?,?,?,?,?,?,?,?,?,?,?,'kolejka')''',
                    (cid,new_values['doc_date'],new_values['received_date'],new_values['delivered_date'],'Załącznik',atitle,
                     new_values['sender'],new_values['document_author'],'załącznik',linked,astored,aname,did,next_order+offset,a,a,sha256_bytes(adata)))
                indexed_ids.append(acur.lastrowid)
                audit(con,cid,'document',acur.lastrowid,'Dodano załącznik do dokumentu',f"Dokument: {_change_value(title)}\nPlik: {_change_value(aname)}",a)
            if attachment_files:
                details=(details+'\n'+f"• Dodano załączniki: {len(attachment_files)}").strip()
            if details:
                action='Edytowano pismo' if new_values['doc_type'] in PLEADING_DOC_TYPES else 'Edytowano dokument'
                audit(con,cid,'document',did,action,details,a)
        for indexed_id in indexed_ids: enqueue_document_index(indexed_id)
        target=(f.get('return_to','') or '').strip()
        self.redirect(target if target.startswith('/') else f"/case/{cid}")

    def document_version_restore(self,did,vid,f):
        author=self.current_author(f)
        with db() as con:
            d=con.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone()
            v=con.execute('SELECT * FROM document_versions WHERE id=? AND document_id=?',(vid,did)).fetchone()
            if not d or not v: return self.send_error(404)
            src=FILES_DIR/f"sprawa_{d['case_id']}"/v['stored_name']
            if not src.is_file(): return self.send_error(404,'Nie znaleziono pliku tej wersji.')
            save_document_file_version(con,did,author)
            restored_name=f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{safe_filename(v['original_name'] or src.name)}"
            dst=FILES_DIR/f"sprawa_{d['case_id']}"/restored_name
            shutil.copy2(src,dst)
            con.execute("""UPDATE documents SET stored_name=?,original_name=?,file_hash=?,title=?,description=?,
                           extracted_text='',indexed_at='',ocr_status='kolejka',updated_by=? WHERE id=?""",
                        (restored_name,v['original_name'],v['file_hash'],v['title'],v['description'],author,did))
            audit(con,d['case_id'],'document',did,'Przywrócono wersję pliku',f"Wersja v{v['version_no']}: {_change_value(v['original_name'])}",author)
            cid=d['case_id']
        enqueue_document_index(did)
        self.redirect(f'/document/{did}/edit')

    def party_add(self,cid,f):
        a=self.current_author(f); name=f.get('name','').strip()
        with db() as con:
            cur=con.execute("INSERT INTO parties(case_id,name,role,notes,created_by,updated_by) VALUES(?,?,?,?,?,?)",(cid,name,f.get('role','').strip(),f.get('notes','').strip(),a,a))
            audit(con,cid,'party',cur.lastrowid,'Dodano uczestnika',f"Imię i nazwisko: {_change_value(name)}\nRola: {_change_value(f.get('role','').strip())}",a)
        self.redirect(f'/case/{cid}')

    def event_add(self,cid,f):
        a=self.current_author(f); title=f.get('title','').strip()
        with db() as con:
            cur=con.execute("INSERT INTO events(case_id,event_date,event_type,title,description,created_by,updated_by) VALUES(?,?,?,?,?,?,?)",(cid,f.get('event_date',''),f.get('event_type','Czynność'),title,f.get('description','').strip(),a,a))
            audit(con,cid,'event',cur.lastrowid,'Dodano zdarzenie',f"Tytuł: {_change_value(title)}\nData: {_change_value(f.get('event_date',''))}\nTyp: {_change_value(f.get('event_type','Czynność'))}",a)
        target=(f.get('return_to','') or '').strip()
        self.redirect(target if target.startswith('/') else f'/case/{cid}')


    def task_add(self,cid,f):
        a=self.current_author(f); title=f.get('title','').strip()
        if not title:
            target=(f.get('return_to','') or '').strip()
            return self.redirect(target if target.startswith('/') else f'/case/{cid}')
        try: assigned=int(f.get('assigned_user_id','') or 0) or None
        except ValueError: assigned=None
        task_type=(f.get('task_type') or 'Zadanie').strip()
        if task_type not in ACTIONABLE_ALERT_TYPES:
            task_type='Zadanie'
        with db() as con:
            if not con.execute("SELECT 1 FROM cases WHERE id=?",(cid,)).fetchone(): return self.send_error(404)
            if case_read_only(con,cid): return self.send_error(403,'Sprawa zakończona jest tylko do odczytu.')
            cur=con.execute("""INSERT INTO tasks(case_id,title,due_date,status,priority,assigned_user_id,depends_on,notes,task_type,created_by,updated_by)
                               VALUES(?,?,?,'open',?,?,?,?,?,?,?)""",
                            (cid,title,f.get('due_date',''),f.get('priority','normal'),assigned,
                             f.get('depends_on','').strip(),f.get('notes','').strip(),task_type,a,a))
            sync_task_alert(con,cur.lastrowid,a)
            assigned_row=con.execute("SELECT author_name,function FROM users WHERE id=?",(assigned,)).fetchone() if assigned else None
            details=(f"Zadanie: {_change_value(title)}\n"
                     f"Rodzaj: {_change_value(task_type)}\n"
                     f"Termin: {_change_value(f.get('due_date',''))}\n"
                     f"Priorytet: {_change_value('Wysoki' if f.get('priority','normal')=='high' else 'Normalny')}\n"
                     f"Wykonawca: {_change_value(user_display_name(assigned_row) if assigned_row else '—')}")
            if f.get('depends_on','').strip(): details += f"\nZależność: {_change_value(f.get('depends_on','').strip())}"
            audit(con,cid,'task',cur.lastrowid,'Dodano zadanie',details,a)
        target=(f.get('return_to','') or '').strip()
        self.redirect(target if target.startswith('/') else f'/case/{cid}')

    def task_add_global(self,f):
        try: cid=int(f.get('case_id','0') or 0)
        except ValueError: cid=0
        if not cid: return self.redirect('/tasks')
        f=dict(f)
        if not (f.get('return_to','') or '').strip(): f['return_to']='/tasks'
        return self.task_add(cid,f)


    def document_add(self,cid,f,files):
        if not self.ensure_case_editable(cid): return
        title=f.get('title','').strip(); stored=''; original=''; a=self.current_author(f); data=None
        try: parent_id=int(f.get('parent_document_id') or 0) or None
        except Exception: parent_id=None

        if 'file' in files and isinstance(files['file'], tuple) and files['file'][0]:
            original=safe_filename(files['file'][0]); data=files['file'][1]
            h=sha256_bytes(data)
            with db() as con:
                dup=con.execute("""SELECT d.id,d.title,d.case_id,c.title case_title,c.signature,c.internal_signature
                                   FROM documents d JOIN cases c ON c.id=d.case_id WHERE d.file_hash=? LIMIT 1""",(h,)).fetchone()
            if dup and not f.get('allow_duplicate'):
                label=primary_signature_text(dup['case_id'],dup['signature'],dup['internal_signature'])
                body=f"<div class='conflict-box'><h1>Identyczny dokument już istnieje</h1><p>Ten sam plik jest już podpięty jako <b>{esc(dup['title'])}</b> w sprawie <a href='/case/{dup['case_id']}'>{esc(label)}</a>.</p><p>Jeśli to celowe, wróć i zaznacz „Zezwól na identyczny plik”.</p><a class='btn' href='/case/{cid}#documents'>Wróć do dokumentów</a></div>"
                return self.send_html(layout('Wykryto duplikat',body,'documents'),409)
            folder=FILES_DIR/f"sprawa_{cid}"; folder.mkdir(parents=True,exist_ok=True)
            stored=f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{original}"
            atomic_write_bytes(folder/stored,data)

        attachment_files=files.get('attachments[]',[]) if isinstance(files,dict) else []
        if isinstance(attachment_files,tuple):
            attachment_files=[attachment_files]

        indexed_ids=[]
        with db() as con:
            dtype=f.get('doc_type','Inne'); dstatus=f.get('doc_status','Aktywny')
            if parent_id: dtype='Załącznik'
            ddate=f.get('doc_date',''); rdate=f.get('received_date',''); delivered=f.get('delivered_date','')
            try: linked=int(f.get('linked_task_id') or 0) or None
            except Exception: linked=None
            if linked and not con.execute('SELECT 1 FROM tasks WHERE id=? AND case_id=?',(linked,cid)).fetchone(): linked=None
            if parent_id and not con.execute("SELECT 1 FROM documents WHERE id=? AND case_id=?",(parent_id,cid)).fetchone():
                parent_id=None
            cur=con.execute("""INSERT INTO documents(case_id,doc_date,received_date,delivered_date,doc_type,doc_status,title,description,
                               sender,document_author,tags,linked_task_id,stored_name,original_name,parent_document_id,attachment_order,
                               created_by,updated_by)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (cid,ddate,rdate,delivered,dtype,dstatus,title,f.get('description','').strip(),
                             f.get('sender','').strip(),f.get('document_author','').strip(),f.get('tags','').strip(),linked,
                             stored,original,parent_id,0,a,a))
            doc_id=cur.lastrowid
            if data is not None:
                con.execute("UPDATE documents SET file_hash=?,ocr_status='kolejka' WHERE id=?",(sha256_bytes(data),doc_id))
                indexed_ids.append(doc_id)

            # Pliki wybrane w polu „Załączniki do pisma” są automatycznie dziećmi dokumentu głównego.
            if not parent_id:
                folder=FILES_DIR/f"sprawa_{cid}"; folder.mkdir(parents=True,exist_ok=True)
                for order,item in enumerate(attachment_files,1):
                    if not item or not item[0]:
                        continue
                    aname=safe_filename(item[0]); adata=item[1]
                    astored=f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{aname}"
                    atomic_write_bytes(folder/astored,adata)
                    atitle=Path(aname).stem or f"Załącznik {order}"
                    acur=con.execute("""INSERT INTO documents(case_id,doc_date,received_date,delivered_date,doc_type,doc_status,title,description,
                                       sender,document_author,tags,linked_task_id,stored_name,original_name,parent_document_id,attachment_order,
                                       created_by,updated_by,file_hash,ocr_status)
                                       VALUES(?,?,?,?,?,'Aktywny',?,'',?,?,?,?,?,?,?,?,?,?,?,'kolejka')""",
                                    (cid,ddate,rdate,delivered,'Załącznik',atitle,f.get('sender','').strip(),
                                     f.get('document_author','').strip(),'załącznik',linked,astored,aname,doc_id,order,a,a,sha256_bytes(adata)))
                    indexed_ids.append(acur.lastrowid)

            details=(f"Tytuł: {_change_value(title)}\nRodzaj: {_change_value(dtype)}\nStatus: {_change_value(dstatus)}"
                     f"\nData dokumentu: {_change_value(ddate)}\nData wpływu: {_change_value(rdate)}\nData doręczenia: {_change_value(delivered)}")
            if parent_id:
                pdoc=con.execute("SELECT title FROM documents WHERE id=?",(parent_id,)).fetchone()
                details+=f"\nZałącznik do: {_change_value(pdoc['title'] if pdoc else parent_id)}"
            if attachment_files and not parent_id:
                details+=f"\nZałączniki: {len([x for x in attachment_files if x and x[0]])}"
            if original: details += f"\nPlik: {_change_value(original)}"
            action='Dodano pismo' if dtype in PLEADING_DOC_TYPES else ('Dodano załącznik' if parent_id else 'Dodano dokument')
            audit(con,cid,'document',doc_id,action,details,a)
        for iid in indexed_ids:
            enqueue_document_index(iid)
        target=(f.get('return_to','') or '').strip()
        self.redirect(target if target.startswith('/') else f'/case/{cid}')

    def task_toggle(self,tid,f):
        cid=int(f.get('case_id','0') or 0); a=self.current_author(f)
        with db() as con:
            r=con.execute("SELECT status,title,case_id FROM tasks WHERE id=?",(tid,)).fetchone()
            if r:
                cid=r['case_id']; new='done' if r['status']!='done' else 'open'
                completed_at='' if new=='open' else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                completed_by='' if new=='open' else a
                con.execute("UPDATE tasks SET status=?,updated_by=?,completed_at=?,completed_by=? WHERE id=?",(new,a,completed_at,completed_by,tid))
                sync_task_alert(con,tid,a)
                audit(con,cid,'task',tid,'Zadanie oznaczono jako wykonane' if new=='done' else 'Cofnięto wykonanie zadania',f"Zadanie: {_change_value(r['title'])}",a)
        target=(f.get('return_to','') or '').strip()
        self.redirect(target if target.startswith('/') else (f'/case/{cid}' if cid else '/tasks'))


    def task_delete(self,tid,f):
        cid=int(f.get('case_id','0') or 0); a=self.current_author(f)
        with db() as con:
            row=con.execute("SELECT case_id FROM tasks WHERE id=?",(tid,)).fetchone(); cid=row['case_id'] if row else cid
            con.execute("DELETE FROM alerts WHERE source_type='task' AND source_id=?",(tid,))
            move_to_trash(con,'task',tid,a)
        target=(f.get('return_to','') or '').strip()
        self.redirect(target if target.startswith('/') else (f'/case/{cid}' if cid else '/tasks'))

    def event_delete(self,eid,f):
        cid=int(f.get('case_id','0') or 0); a=self.current_author(f)
        with db() as con: move_to_trash(con,'event',eid,a)
        self.redirect(f'/case/{cid}')

    def party_delete(self,pid,f):
        cid=int(f.get('case_id','0') or 0); a=self.current_author(f)
        with db() as con: move_to_trash(con,'party',pid,a)
        self.redirect(f'/case/{cid}')


    def document_delete(self,did,f):
        cid=int(f.get('case_id','0') or 0); a=self.current_author(f)
        with db() as con:
            row=con.execute("SELECT case_id FROM documents WHERE id=?",(did,)).fetchone(); cid=row['case_id'] if row else cid
            children=con.execute("SELECT id FROM documents WHERE parent_document_id=? ORDER BY attachment_order,id",(did,)).fetchall()
            for ch in children:
                move_to_trash(con,'document',ch['id'],a)
            move_to_trash(con,'document',did,a)
        target=(f.get('return_to','') or '').strip()
        self.redirect(target if target.startswith('/') else f'/case/{cid}?tab=documents')

    def document_missing_page(self,d,message=''):
        did=d['id']; state,p,why=document_state(d)
        case_label=primary_signature_text(d['case_id'],row_get(d,'signature',''),row_get(d,'internal_signature',''))
        msg=f"<div class='error'>{esc(message)}</div>" if message else ''
        path_info=esc(str(p)) if p else '—'
        body=f"""<div class='topbar'><div><h1>Nie znaleziono pliku dokumentu</h1><div class='sub'>{esc(case_label)} · {esc(d['title'])}</div></div><a class='btn' href='/case/{d['case_id']}#documents'>← Wróć</a></div>{msg}
        <div class='card'><div class='error'><b>Dokument jest zapisany w bazie, ale pliku nie można otworzyć.</b><br>{esc(why)}</div>
        <p class='small muted'>Oczekiwana lokalizacja: {path_info}</p>
        <h2>Wskaż plik ponownie</h2><p>Wybierz właściwy plik. RK KANCELARIA skopiuje go z powrotem do bezpiecznego katalogu dokumentów i zachowa rekord sprawy.</p>
        <form method='post' enctype='multipart/form-data' action='/document/{did}/relocate'><input type='file' name='file' required><label style='font-weight:500'><input style='width:auto' type='checkbox' name='keep_original_name' value='1' checked> Zachowaj dotychczasową nazwę dokumentu w bazie</label><button class='btn primary'>Wskaż i przywróć plik</button></form></div>"""
        self.send_html(layout('Brak pliku dokumentu',body,'documents'),404)

    def _preview_text_now(self,d,p,ext):
        existing=(row_get(d,'extracted_text','') or '').strip()
        if existing: return existing,row_get(d,'ocr_status','') or 'indeks'
        if ext not in {'.docx','.xlsx','.xlsm','.txt','.md','.csv','.log','.rtf'}:
            return '',row_get(d,'ocr_status','') or 'brak indeksu'
        try:
            data=p.read_bytes(); text,used,status,lang=extract_document_text(d['original_name'] or p.name,data,force_ocr=False)
            if text:
                with db() as con:
                    con.execute("UPDATE documents SET extracted_text=?,indexed_at=CURRENT_TIMESTAMP,ocr_used=?,ocr_status=?,ocr_language=? WHERE id=?",(text[:5_000_000],used,status,lang,d['id']))
                    try:
                        con.execute('DELETE FROM document_fts WHERE document_id=?',(d['id'],))
                        con.execute('INSERT INTO document_fts(document_id,case_id,title,filename,body) VALUES(?,?,?,?,?)',(d['id'],d['case_id'],d['title'],d['original_name'],text[:5_000_000]))
                    except sqlite3.DatabaseError: pass
            return text,status
        except Exception as exc:
            log_app_exception(f'/document/{d["id"]}/preview-text',exc); return '',f'błąd podglądu: {exc}'

    def document_view(self,did,qs=None):
        with db() as con:
            d=con.execute("SELECT d.*,c.title case_title,c.signature,c.internal_signature,c.status case_status,c.closed_edit_unlocked FROM documents d JOIN cases c ON c.id=d.case_id WHERE d.id=?",(did,)).fetchone()
            parent=con.execute("SELECT id,title FROM documents WHERE id=?",(row_get(d,'parent_document_id',0),)).fetchone() if d and row_get(d,'parent_document_id',0) else None
            children=con.execute("SELECT id,title,original_name,stored_name FROM documents WHERE parent_document_id=? ORDER BY attachment_order,id",(did,)).fetchall() if d else []
        if not d: return self.send_error(404)
        state,p,why=document_state(d)
        if state!='ok' or not p: return self.document_missing_page(d,why)
        ext=Path(d['original_name'] or p.name).suffix.lower(); case_label=primary_signature_text(d['case_id'],d['signature'],d['internal_signature'])
        meta=f"{esc(d['doc_type'])} · status: {esc(d['doc_status'])} · data: {fmt_date(d['doc_date'])} · wpływ: {fmt_date(d['received_date'])} · doręczenie: {fmt_date(row_get(d,'delivered_date',''))}"; extra_meta=' · '.join(x for x in [f"nadawca: {esc(row_get(d,'sender',''))}" if row_get(d,'sender','') else '',f"autor: {esc(row_get(d,'document_author',''))}" if row_get(d,'document_author','') else '',f"tagi: {esc(row_get(d,'tags',''))}" if row_get(d,'tags','') else ''] if x); meta += ((' · '+extra_meta) if extra_meta else '')
        desktop_actions=''
        if DESKTOP_MODE and LOCAL_MODE:
            desktop_actions=f"<form method='post' action='/document/{did}/open-default' style='display:inline'><button class='btn'>Otwórz w programie domyślnym</button></form> <form method='post' action='/document/{did}/open-folder' style='display:inline'><button class='btn'>Otwórz folder dokumentu</button></form>"
        editable=not (d['case_status']=='closed' and not int(d['closed_edit_unlocked'] or 0))
        edit_action=f"<a class='btn' href='/document/{did}/edit'>Edytuj / dodaj załączniki</a>" if editable else ''
        toolbar=f"<a class='btn' href='/case/{d['case_id']}?tab=documents'>← Wróć do sprawy</a> <a class='btn' href='/documents'>Dokumenty</a> {edit_action} <a class='btn primary' href='/document/{did}/download'>Pobierz</a> {desktop_actions}"
        max_chars=160_000; bodytxt,status=self._preview_text_now(d,p,ext)
        def text_preview(label):
            if not bodytxt:
                return f"<div class='card'><h2>{esc(label)}</h2><p>Nie udało się przygotować podglądu tego formatu.</p><p class='small muted'>Stan indeksu/OCR: {esc(status)}. Oryginał pozostaje dostępny przez „Pobierz” lub „Otwórz w programie domyślnym”.</p></div>"
            shown=bodytxt[:max_chars]; tail=(f"<div class='notice' style='margin-top:12px'>Podgląd ograniczono do {max_chars:,} znaków dla stabilności. Oryginał nie został zmieniony.</div>" if len(bodytxt)>max_chars else '')
            return f"<div class='doc-text-preview'><div class='small muted' style='margin-bottom:12px'>{esc(label)}</div><pre style='white-space:pre-wrap;word-break:break-word;margin:0;font:15px/1.5 Georgia,serif'>{esc(shown)}</pre>{tail}</div>"
        if ext=='.pdf':
            try:
                import fitz
                doc=fitz.open(str(p)); pages=len(doc); doc.close()
                if pages<1: raise ValueError('PDF nie zawiera stron')
                preview=f"""<div class='card pdf-preview'><div class='case-control-bar' style='justify-content:center;margin-bottom:10px'>
                <button class='btn' type='button' onclick='rkPrevPage()'>‹ Poprzednia</button><label>Strona <input id='rkPdfPageInput' type='number' min='1' max='{pages}' value='1' style='width:76px;padding:6px'></label><span class='pill'>z {pages}</span><button class='btn' type='button' onclick='rkGoPage()'>Idź</button><button class='btn' type='button' onclick='rkNextPage()'>Następna ›</button>
                <button class='btn small' type='button' onclick='rkZoom(-.2)'>−</button><span id='rkZoomLabel' class='pill'>100%</span><button class='btn small' type='button' onclick='rkZoom(.2)'>+</button></div>
                <div style='text-align:center;overflow:auto;max-height:calc(100vh - 300px);background:#e7ece9;padding:12px;border-radius:8px'><img id='rkPdfPage' src='/document/{did}/page/1?zoom=1' style='max-width:none;width:auto;height:auto;box-shadow:0 3px 15px rgba(0,0,0,.18)' onerror="this.style.display='none';document.getElementById('rkPdfError').style.display='block'"></div>
                <div id='rkPdfError' class='error' style='display:none;margin-top:10px'>Nie udało się wyrenderować tej strony PDF. Dokument może być uszkodzony lub nietypowo zakodowany. Użyj „Pobierz” albo „Otwórz w programie domyślnym”.</div>
                <script>let rkPage=1,rkPages={pages},rkScale=1; function rkShow(){{let i=document.getElementById('rkPdfPageInput');rkPage=Math.max(1,Math.min(rkPages,parseInt(i.value||rkPage)));i.value=rkPage;let img=document.getElementById('rkPdfPage');img.style.display='inline-block';document.getElementById('rkPdfError').style.display='none';img.src='/document/{did}/page/'+rkPage+'?zoom='+rkScale.toFixed(1);document.getElementById('rkZoomLabel').textContent=Math.round(rkScale*100)+'%';}} function rkPrevPage(){{if(rkPage>1){{rkPage--;document.getElementById('rkPdfPageInput').value=rkPage;rkShow();}}}} function rkNextPage(){{if(rkPage<rkPages){{rkPage++;document.getElementById('rkPdfPageInput').value=rkPage;rkShow();}}}} function rkGoPage(){{rkShow();}} function rkZoom(d){{rkScale=Math.max(.6,Math.min(2.4,rkScale+d));rkShow();}}</script></div>"""
            except Exception as exc:
                log_app_exception(f'/document/{did}/pdf-open',exc); preview=f"<div class='error'><b>Nie można otworzyć PDF w podglądzie.</b><br>{esc(str(exc))}</div>"+text_preview('Tekst odzyskany z PDF / OCR')
        elif ext in {'.docx','.txt','.md','.csv','.log','.rtf'}: preview=text_preview('Podgląd tekstowy dokumentu')
        elif ext in {'.xlsx','.xlsm'}: preview=text_preview('Podgląd arkusza kalkulacyjnego (wartości komórek)')
        elif ext in {'.png','.jpg','.jpeg','.gif','.webp','.bmp','.tif','.tiff'}:
            try: size=p.stat().st_size
            except OSError: size=0
            preview=(f"<div class='doc-native-view' style='text-align:center;background:#eef1ef;padding:18px;overflow:auto;max-height:calc(100vh - 260px)'><img src='/document/{did}/file' alt='{esc(d['title'])}' style='max-width:100%;height:auto;box-shadow:0 4px 20px rgba(0,0,0,.18)'></div>" if size<=25*1024*1024 else f"<div class='notice'>Obraz ma {size/1024/1024:.1f} MB. Automatyczny podgląd wyłączono, aby nie zamrozić okna. Użyj „Otwórz w programie domyślnym” lub „Pobierz”.</div>")
        else: preview=text_preview(f'Format {ext or "bez rozszerzenia"} nie ma własnego stabilnego podglądu')
        family_html=''
        if parent:
            family_html=f"<div class='card document-family'><span class='attachment-label'>📎 Załącznik</span> do pisma: <a href='/document/{parent['id']}/open'><b>{esc(parent['title'])}</b></a></div>"
        elif children:
            attachment_rows=[]
            for ch in children:
                file_note=esc(ch['original_name'] or 'bez pliku')
                attachment_rows.append(f"<div class='document-attachment-item'><span>📎 <a href='/document/{ch['id']}/open'><b>{esc(ch['title'])}</b></a><small class='muted'> · {file_note}</small></span><a class='btn small' href='/document/{ch['id']}/open'>Otwórz</a></div>")
            family_html=f"<div class='card document-family'><h2>Załączniki ({len(children)})</h2><div class='document-attachment-list'>{''.join(attachment_rows)}</div></div>"
        body=f"<div class='topbar'><div><h1>{esc(d['title'])}</h1><div class='sub'>{esc(case_label)} · {meta}</div></div><div class='case-control-bar'>{toolbar}</div></div>{family_html}{preview}"
        extra_css="<style>.doc-native-view{border:1px solid var(--line);border-radius:10px;overflow:hidden;background:#fff}.doc-text-preview{background:#fff;border:1px solid var(--line);border-radius:10px;padding:28px;max-width:1200px;margin:0 auto;max-height:calc(100vh - 250px);overflow:auto;box-shadow:0 2px 10px rgba(0,0,0,.04)}.pdf-preview{min-height:420px}</style>"
        self.send_html(layout('Podgląd dokumentu',extra_css+body,'documents'))

    def document_file(self,did,download=False):
        with db() as con: d=con.execute("SELECT * FROM documents WHERE id=?",(did,)).fetchone()
        if not d: return self.send_error(404)
        state,p,why=document_state(d)
        if state!='ok' or not p:
            if download: return self.send_html(layout('Brak pliku',f"<div class='card'><h1>Nie można pobrać dokumentu</h1><p>{esc(why)}</p><a class='btn' href='/document/{did}/open'>Przejdź do naprawy pliku</a></div>",'documents'),404)
            return self.send_error(404,why)
        ctype=mimetypes.guess_type(d['original_name'] or p.name)[0] or 'application/octet-stream'
        try: size=p.stat().st_size
        except OSError: return self.send_error(404)
        self.send_response(200); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(size)); dispo='attachment' if download else 'inline'
        self.send_header('Content-Disposition',f"{dispo}; filename*=UTF-8''{quote(d['original_name'] or p.name)}"); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Cache-Control','private, max-age=60'); self.end_headers()
        try:
            with p.open('rb') as fh:
                while True:
                    chunk=fh.read(1024*1024)
                    if not chunk: break
                    self.wfile.write(chunk)
        except (BrokenPipeError,ConnectionResetError,OSError): pass

    def document_relocate(self,did,f,files):
        a=self.current_author(f)
        with db() as con: d=con.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone()
        if not d: return self.send_error(404)
        uploaded=files.get('file')
        if not uploaded or not uploaded[1]: return self.document_missing_page(d,'Nie wybrano pliku.')
        original=safe_filename(uploaded[0] or d['original_name'] or 'dokument'); data=uploaded[1]
        if not data: return self.document_missing_page(d,'Wybrany plik jest pusty.')
        folder=FILES_DIR/f"sprawa_{d['case_id']}"; folder.mkdir(parents=True,exist_ok=True); display_name=(d['original_name'] if f.get('keep_original_name') and d['original_name'] else original); stored=f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{original}"
        try: atomic_write_bytes(folder/stored,data)
        except Exception as exc: log_app_exception(f'/document/{did}/relocate',exc); return self.document_missing_page(d,f'Nie udało się zapisać pliku: {exc}')
        with db() as con:
            con.execute("UPDATE documents SET stored_name=?,original_name=?,file_hash=?,extracted_text='',indexed_at='',ocr_status='kolejka',updated_by=? WHERE id=?",(stored,display_name,sha256_bytes(data),a,did)); audit(con,d['case_id'],'document',did,'Przywrócono / wskazano plik dokumentu',display_name,a)
        enqueue_document_index(did); self.redirect(f'/document/{did}/open')

    def document_open_default(self,did,f):
        if not (DESKTOP_MODE and LOCAL_MODE): return self.send_html(layout('Funkcja lokalna',"<div class='card'><h1>Otwieranie lokalne niedostępne</h1><p>Ta funkcja działa tylko w aplikacji Desktop na komputerze, na którym znajdują się dokumenty.</p></div>",'documents'),409)
        with db() as con: d=con.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone()
        if not d: return self.send_error(404)
        state,p,why=document_state(d)
        if state!='ok' or not p: return self.document_missing_page(d,why)
        ok,msg=open_in_default_app(p)
        if not ok: return self.send_html(layout('Nie można otworzyć',f"<div class='card'><h1>Nie udało się otworzyć dokumentu</h1><p>{esc(msg)}</p><a class='btn' href='/document/{did}/open'>Wróć</a></div>",'documents'),500)
        self.redirect(f'/document/{did}/open')

    def document_open_folder(self,did,f):
        if not (DESKTOP_MODE and LOCAL_MODE): return self.send_html(layout('Funkcja lokalna',"<div class='card'><h1>Otwieranie folderu niedostępne</h1><p>Ta funkcja działa tylko lokalnie w Desktop.</p></div>",'documents'),409)
        with db() as con: d=con.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone()
        if not d: return self.send_error(404)
        state,p,why=document_state(d)
        if p is None: p=FILES_DIR/f"sprawa_{d['case_id']}"/safe_filename(d['original_name'] or 'dokument')
        target=p if p.exists() else p.parent
        try:
            if target.is_dir():
                if os.name=='nt': subprocess.Popen(['explorer.exe',str(target)],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)); ok,msg=True,''
                elif sys.platform=='darwin': subprocess.Popen(['open',str(target)]); ok,msg=True,''
                else: subprocess.Popen(['xdg-open',str(target)]); ok,msg=True,''
            else: ok,msg=open_containing_folder(target)
        except Exception as exc: ok,msg=False,str(exc)
        if not ok: return self.send_html(layout('Nie można otworzyć folderu',f"<div class='card'><h1>Nie udało się otworzyć folderu</h1><p>{esc(msg)}</p></div>",'documents'),500)
        self.redirect(f'/document/{did}/open')

    def saved_views_page(self):
        u=current_request_user(); uid=u['id'] if u else 0
        with db() as con:
            rows=con.execute("SELECT * FROM saved_views WHERE user_id=? ORDER BY created_at DESC,id DESC",(uid,)).fetchall()
        cards=[]
        for r in rows:
            cards.append(f"<div class='saved-view-card'><a class='case-link' href='{esc(r['target'])}'>{esc(r['name'])}</a><div class='small muted'>{esc(r['target'])}</div><form method='post' action='/view/{r['id']}/delete' onsubmit=\"return confirm('Usunąć zapisany widok?');\"><button class='btn small danger'>Usuń</button></form></div>")
        body=f"""<div class='topbar'><div><h1>Moje widoki</h1><div class='sub'>Zapisane filtry spraw i zadań. Każdy użytkownik ma własną listę.</div></div><div><a class='btn' href='/cases'>Sprawy</a> <a class='btn' href='/tasks'>Zadania</a></div></div><div class='saved-view-grid'>{''.join(cards) or '<div class="card empty">Nie masz jeszcze zapisanych widoków. Otwórz Sprawy albo Zadania, ustaw filtr i kliknij „Zapisz widok”.</div>'}</div>"""
        self.send_html(layout('Moje widoki',body,'views'))

    def saved_view_save(self,f):
        u=current_request_user(); uid=u['id'] if u else 0
        name=(f.get('name') or '').strip()[:80]
        target=(f.get('target') or '').strip()
        parsed=urlparse(target)
        allowed={'/cases','/cases/closed','/tasks','/documents','/drafts','/history','/today'}
        if not name or parsed.path not in allowed or not target.startswith('/'):
            return self.redirect('/views')
        with db() as con:
            con.execute("INSERT INTO saved_views(user_id,name,target) VALUES(?,?,?) ON CONFLICT(user_id,name) DO UPDATE SET target=excluded.target,created_at=CURRENT_TIMESTAMP",(uid,name,target))
        back=(f.get('return_to') or '').strip()
        self.redirect(back if back.startswith('/') else '/views')

    def saved_view_delete(self,vid,f):
        u=current_request_user(); uid=u['id'] if u else 0
        with db() as con:
            con.execute("DELETE FROM saved_views WHERE id=? AND user_id=?",(vid,uid))
        self.redirect('/views')

    def _save_view_form(self, target: str) -> str:
        parsed=urlparse(target)
        if parsed.path not in {'/cases','/cases/closed','/tasks','/documents','/drafts','/history','/today'}:
            return ''
        return f"<form method='post' action='/view/save' class='save-view-form'><input type='hidden' name='target' value='{esc(target)}'><input type='hidden' name='return_to' value='{esc(target)}'><input name='name' required maxlength='80' placeholder='Nazwa widoku'><button class='btn small'>☆ Zapisz widok</button></form>"

    def tasks_page(self,qs):
        show=(qs.get('show') or ['open'])[0]; mine=(qs.get('mine') or [''])[0]=='1'
        flt=(qs.get('filter') or [''])[0].strip().lower()
        if flt not in {'','overdue','today','7d','high','undated'}: flt=''
        u=current_request_user(); uid=u['id'] if u else 0
        current_return=f"/tasks?show={quote(show)}"+('&mine=1' if mine else '')+(('&filter='+quote(flt)) if flt else '')
        today=date.today().isoformat(); week_end=(date.today()+timedelta(days=7)).isoformat()
        with db() as con:
            sql="""SELECT t.*,c.title case_title,c.signature,c.internal_signature,u.author_name assigned_name,u.function assigned_function
                   FROM tasks t JOIN cases c ON c.id=t.case_id LEFT JOIN users u ON u.id=t.assigned_user_id WHERE 1=1"""; params=[]
            if show!='all': sql += " AND t.status='open'"
            if mine: sql += " AND t.assigned_user_id=?"; params.append(uid)
            if flt=='overdue': sql += " AND t.status='open' AND t.due_date<>'' AND t.due_date<?"; params.append(today)
            elif flt=='today': sql += " AND t.status='open' AND t.due_date=?"; params.append(today)
            elif flt=='7d': sql += " AND t.status='open' AND t.due_date>? AND t.due_date<=?"; params.extend([today,week_end])
            elif flt=='high': sql += " AND t.status='open' AND t.priority='high'"
            elif flt=='undated': sql += " AND t.status='open' AND t.due_date=''"
            sql += " ORDER BY t.status,CASE WHEN t.due_date='' THEN 1 ELSE 0 END,t.due_date,CASE t.priority WHEN 'high' THEN 0 ELSE 1 END"
            rows=con.execute(sql,params).fetchall()
            task_sig_map=load_external_signature_map(con,[r['case_id'] for r in rows])
            cases=con.execute("SELECT id,signature,internal_signature,title,status,closed_edit_unlocked FROM cases WHERE status<>'closed' OR closed_edit_unlocked=1 ORDER BY signature='',signature,title").fetchall()
            case_sig_map=load_external_signature_map(con,[r['id'] for r in cases])
            users=con.execute("SELECT id,author_name,function FROM users WHERE is_active=1 ORDER BY author_name").fetchall()
        parts=[]
        for r in rows:
            toggle='↩' if r['status']=='done' else '✓'; label=primary_signature_fast(r['case_id'],r['signature'],task_sig_map); cls='muted' if r['status']=='done' else ''
            dep=f"<div class='small muted'>zależność: {esc(r['depends_on'])}</div>" if r['depends_on'] else ''
            assigned='—'
            if r['assigned_name']: assigned=r['assigned_name']+((' — '+r['assigned_function']) if r['assigned_function'] else '')
            auth=[]
            if r['created_by']: auth.append('autor: '+esc(r['created_by']))
            if r['updated_by'] and r['updated_by']!=r['created_by']: auth.append('zmiana: '+esc(r['updated_by']))
            auth_html=f"<div class='author'>{' · '.join(auth)}</div>" if auth else ''
            prio='Wysoki' if r['priority']=='high' else 'Normalny'
            deadline_meta=''
            if row_get(r,'deadline_base_date',''):
                manual=' · ręcznie skorygowany' if int(row_get(r,'deadline_manual',0) or 0) else ''
                deadline_meta=f"<div class='small deadline-meta'>wyliczono: {fmt_date(r['deadline_base_date'])} + {esc(str(row_get(r,'deadline_days','')))} {esc(row_get(r,'deadline_rule',''))}{manual}</div>"
            edit_return=quote(current_return,safe='')
            parts.append(f"<tr><td><form method='post' action='/task/{r['id']}/toggle'><input type='hidden' name='case_id' value='{r['case_id']}'><input type='hidden' name='return_to' value='{esc(current_return)}'><button class='btn small'>{toggle}</button></form></td><td><a class='case-link' href='/case/{r['case_id']}'>{esc(label)}</a><div class='small muted'>{esc(internal_signature_text(r['internal_signature']))}</div></td><td class='{cls}'><span class='mini-badge'>{esc(row_get(r,'task_type','Zadanie') or 'Zadanie')}</span> <b>{esc(r['title'])}</b>{dep}{deadline_meta}{auth_html}</td><td>{fmt_date(r['due_date'])}</td><td>{esc(assigned)}</td><td>{prio}</td><td class='nowrap'><a class='btn small' href='/task/{r['id']}/edit?return_to={edit_return}'>Edytuj</a> <form style='display:inline' method='post' action='/task/{r['id']}/delete' onsubmit=\"return confirm('Przenieść zadanie do Kosza?');\"><input type='hidden' name='case_id' value='{r['case_id']}'><input type='hidden' name='return_to' value='{esc(current_return)}'><button class='btn small danger'>Do kosza</button></form></td></tr>")
        trs=''.join(parts) or '<tr><td colspan=7><div class="empty compact-empty"><b>Brak zadań do pokazania.</b><div class="small">Dodaj nowe zadanie przyciskiem u góry.</div></div></td></tr>'
        qp='&mine=1' if mine else ''; a1='primary' if show=='open' else ''; a2='primary' if show=='all' else ''
        mine_button="<a class='btn primary' href='/tasks?show=open&mine=1'>Moje zadania</a> <a class='btn' href='/tasks?show=open'>Wszystkie zadania</a>" if mine else "<a class='btn' href='/tasks?show=open&mine=1'>Moje zadania</a>"
        def filter_link(key,label):
            active='primary' if flt==key else ''
            q=f"/tasks?show=open"+('&mine=1' if mine else '')+(('&filter='+key) if key else '')
            return f"<a class='btn small {active}' href='{q}'>{label}</a>"
        filter_bar="<div class='quick-filter-bar'><span class='small muted'>Szybkie filtry:</span> "+''.join([filter_link('','Wszystkie otwarte'),filter_link('overdue','Po terminie'),filter_link('today','Dzisiaj'),filter_link('7d','7 dni'),filter_link('high','Wysoki priorytet'),filter_link('undated','Bez terminu')])+"</div>"
        case_opts=[]
        for c in cases:
            sig=primary_signature_fast(c['id'],c['signature'],case_sig_map)
            prefix='' if sig=='Bez sygnatury' else sig+' — '
            case_opts.append(f"<option value='{c['id']}'>{esc(prefix+c['title'])} · {esc(internal_signature_text(c['internal_signature']))}</option>")
        user_opts='<option value="">— nie przypisano —</option>'+''.join(f"<option value='{x['id']}'>{esc(user_display_name(x))}</option>" for x in users)
        create_form=(f"""<details class='card add-panel' id='new-task'><summary><span class='add-panel-plus'>＋</span><span><b>Dodaj zadanie</b><small>Formularz pokaże się dopiero tutaj.</small></span></summary><div class='add-panel-body'>
        <form method='post' action='/task/create' class='form-grid'><input type='hidden' name='return_to' value='/tasks'>
        <div class='full'><label>Sprawa *</label><select name='case_id' required><option value=''>— wybierz sprawę —</option>{''.join(case_opts)}</select></div>
        <div><label>Rodzaj</label><select name='task_type'><option>Zadanie</option><option>Monit</option><option>Termin procesowy</option><option>Płatność</option></select></div><div><label>Termin</label><input type='date' name='due_date'></div>
        <div class='full'><label>Co trzeba zrobić? *</label><input name='title' required placeholder='np. Przygotować odpowiedź na pismo'></div><div><label>Priorytet</label><select name='priority'><option value='normal'>Normalny</option><option value='high'>Wysoki</option></select></div>
        <div class='full'><label>Wykonawca</label><select name='assigned_user_id'>{user_opts}</select></div>
        <details class='advanced-fields full'><summary>Więcej opcji</summary><div class='form-grid'><div class='full'><label>Zależność / czekamy na</label><input name='depends_on'></div><div class='full'><label>Notatki</label><textarea name='notes'></textarea></div></div></details>
        <div class='full'><button class='btn primary'>Dodaj zadanie</button></div></form></div></details>""" if cases else "<div class='notice'>Najpierw dodaj aktywną sprawę, aby utworzyć zadanie.</div>")
        save_view=self._save_view_form(self.path)
        body=f"""<div class='topbar'><div><h1>{'Moje zadania' if mine else 'Zadania'}</h1><div class='sub'>Najpierw lista zadań. Formularz dodawania otwierasz tylko wtedy, kiedy go potrzebujesz.</div></div><div><button class='btn primary' type='button' data-open-details='new-task'>+ Dodaj zadanie</button> <a class='btn' href='/deadline'>+ Termin procesowy</a> {mine_button}</div></div>{filter_bar}{save_view}<div class='card content-first'><div class='section-head'><div><h2>{'Moje zadania' if mine else 'Lista zadań'}</h2><div class='small muted'>Kliknij ✓, aby oznaczyć jako wykonane. Wykonane zadania pozostają w historii.</div></div><div><a class='btn small {a1}' href='/tasks?show=open{qp}'>Otwarte</a> <a class='btn small {a2}' href='/tasks?show=all{qp}'>Wszystkie</a></div></div><div class='table-scroll'><table><tr><th>Stan</th><th>Sprawa</th><th>Zadanie</th><th>Termin</th><th>Wykonawca</th><th>Priorytet</th><th>Akcje</th></tr>{trs}</table></div></div><div class='module-spacer'></div>{create_form}"""
        self.send_html(layout('Zadania',body,'tasks'))

    def documents_page(self,qs):
        q=(qs.get('q') or [''])[0].strip(); dtype=(qs.get('type') or [''])[0].strip(); dstatus=(qs.get('status') or [''])[0].strip(); order=(qs.get('order') or ['desc'])[0].strip().lower()
        if order not in ('desc','asc'): order='desc'
        if dstatus and dstatus not in DOC_STATUSES: dstatus=''
        sql="SELECT d.*,c.title case_title,c.signature,c.internal_signature,c.client FROM documents d JOIN cases c ON c.id=d.case_id WHERE 1=1"; params=[]
        if q:
            like=f"%{q}%"; sql += " AND (d.title LIKE ? OR d.description LIKE ? OR d.original_name LIKE ? OR d.sender LIKE ? OR d.document_author LIKE ? OR d.tags LIKE ? OR c.signature LIKE ? OR c.internal_signature LIKE ? OR c.client LIKE ? OR c.title LIKE ? OR d.created_by LIKE ? OR d.updated_by LIKE ? OR EXISTS (SELECT 1 FROM case_external_signatures es WHERE es.case_id=c.id AND (es.label LIKE ? OR es.signature LIKE ?)))"; params += [like]*14
        if dtype: sql += " AND d.doc_type=?"; params.append(dtype)
        if dstatus: sql += " AND d.doc_status=?"; params.append(dstatus)
        direction='ASC' if order=='asc' else 'DESC'
        sql += f" ORDER BY c.title COLLATE NOCASE, CASE WHEN COALESCE(d.parent_document_id,0)=0 THEN COALESCE(NULLIF(d.doc_date,''),'0000-00-00') ELSE COALESCE((SELECT NULLIF(p.doc_date,'') FROM documents p WHERE p.id=d.parent_document_id),'0000-00-00') END {direction}, COALESCE(d.parent_document_id,d.id) {direction}, CASE WHEN COALESCE(d.parent_document_id,0)=0 THEN 0 ELSE 1 END, d.attachment_order, d.id"
        with db() as con:
            rows=con.execute(sql,params).fetchall()
            doc_sig_map=load_external_signature_map(con,[r['case_id'] for r in rows])
        opts=''.join(f"<option value='{esc(x)}' {'selected' if dtype==x else ''}>{esc(x)}</option>" for x in DOC_TYPES)
        status_filter_opts=''.join(f"<option value='{esc(x)}' {'selected' if dstatus==x else ''}>{esc(x)}</option>" for x in DOC_STATUSES)
        doc_form_opts=''.join(f"<option>{esc(x)}</option>" for x in DOC_TYPES)
        doc_status_form_opts=''.join(f"<option>{esc(x)}</option>" for x in DOC_STATUSES)
        grouped={}
        for r in rows: grouped.setdefault(r['case_id'],[]).append(r)
        def newest_key(item):
            cid,docs=item; dates=[d['doc_date'] for d in docs if d['doc_date']]; return (max(dates) if dates else '',docs[0]['case_title'].casefold())
        groups=sorted(grouped.items(),key=newest_key,reverse=True); auto_open=bool(q or dtype or dstatus); folders=[]
        for cid,docs in groups:
            first=docs[0]; primary=primary_signature_fast(cid,first['signature'],doc_sig_map); internal=internal_signature_text(first['internal_signature'])
            dates=[d['doc_date'] for d in docs if d['doc_date']]; latest=fmt_date(max(dates)) if dates else 'brak daty'; client=f"Klient: {esc(first['client'])}" if first['client'] else ''
            present_types=[]
            for d in docs:
                if d['doc_type'] not in present_types: present_types.append(d['doc_type'])
            type_buttons="<button class='btn small doc-type-filter active' type='button' onclick='filterDocs(\"docs-%s\",\"\",this)'>Wszystkie</button>"%cid
            type_buttons+=''.join(f"<button class='btn small doc-type-filter' type='button' onclick='filterDocs(\"docs-{cid}\",{esc(json.dumps(t))},this)'>{esc(t)}</button>" for t in present_types)
            years={}
            for d in docs:
                year=(d['doc_date'][:4] if d['doc_date'] and len(d['doc_date'])>=4 else 'Bez daty')
                years.setdefault(year,[]).append(d)
            year_keys=sorted(years,key=lambda y:('0000' if y=='Bez daty' else y),reverse=(order=='desc'))
            year_html=[]
            for year in year_keys:
                rows_html=[]
                for r in years[year]:
                    auth=[]
                    if r['created_by']: auth.append('autor: '+esc(r['created_by']))
                    if r['updated_by'] and r['updated_by']!=r['created_by']: auth.append('zmiana: '+esc(r['updated_by']))
                    auth_html=f"<div class='author'>{' · '.join(auth)}</div>" if auth else ''
                    file_actions=''
                    if r['stored_name']: file_actions=f"<a class='btn small' href='/document/{r['id']}/open'>Otwórz</a> <a class='btn small' href='/document/{r['id']}/download'>Pobierz</a>"
                    filename=esc(r['original_name']) if r['original_name'] else 'bez pliku'
                    ocr_info=("<div class='small muted'>OCR: "+esc(r['ocr_language'] or 'tak')+"</div>") if r['ocr_used'] else ("<div class='small muted'>OCR: silnik niedostępny</div>" if r['ocr_status']=='ocr_brak_silnika' else '')
                    sender_info=(f"<div class='small muted'>nadawca: {esc(row_get(r,'sender',''))}</div>" if row_get(r,'sender','') else '')
                    doc_author_info=(f"<div class='small muted'>autor dokumentu: {esc(row_get(r,'document_author',''))}</div>" if row_get(r,'document_author','') else '')
                    tags_info=(f"<div class='small'>tagi: {esc(row_get(r,'tags',''))}</div>" if row_get(r,'tags','') else '')
                    linked_id=int(row_get(r,'linked_task_id',0) or 0)
                    linked_info=(f"<div class='small'><a class='linked-chip' href='/task/{linked_id}/edit'>Powiązane zadanie #{linked_id}</a></div>" if linked_id else '')
                    is_attachment=bool(int(row_get(r,'parent_document_id',0) or 0))
                    row_class='doc-filter-row attachment-row' if is_attachment else 'doc-filter-row document-family'
                    kind_label=("<span class='attachment-label'>↳ Załącznik</span>" if is_attachment else f"<span class='pill'>{esc(r['doc_type'])}</span>")
                    title_prefix='📎 ' if is_attachment else ''
                    rows_html.append(f"""<tr class='{row_class}' data-doc-type='{esc(r['doc_type'])}'><td class='nowrap'><b>{fmt_date(r['doc_date'])}</b><div class='small muted'>wpływ: {fmt_date(r['received_date'])}</div><div class='small muted'>doręczenie: {fmt_date(row_get(r,'delivered_date',''))}</div></td><td>{kind_label}<div><span class='doc-status {'sign' if r['doc_status']=='Do podpisu' else ''}'>{esc(r['doc_status'])}</span></div></td><td><b>{title_prefix}{esc(r['title'])}</b><div class='small muted'>{esc(r['description'])}</div>{sender_info}{doc_author_info}{tags_info}{linked_info}<div class='small muted'>{filename}</div>{ocr_info}{auth_html}</td><td class='nowrap'>{file_actions} <a class='btn small' href='/document/{r['id']}/edit'>Edytuj</a> <form method='post' action='/document/{r['id']}/delete' style='display:inline' onsubmit="return confirm('Przenieść dokument do Kosza?');"><input type='hidden' name='case_id' value='{cid}'><button class='btn small danger'>Do kosza</button></form></td></tr>""")
                year_html.append(f"<details class='year-folder' {'open' if auto_open or year==year_keys[0] else ''}><summary>{esc(year)} — {len(years[year])} dokumentów</summary><div style='padding:0 8px 8px'><table><tr><th>Data / wpływ</th><th>Rodzaj</th><th>Dokument</th><th>Akcje</th></tr>{''.join(rows_html)}</table></div></details>")
            open_attr=' open' if auto_open else ''
            quick_form=f"""<details><summary>+ Szybko dodaj dokument</summary><form method='post' enctype='multipart/form-data' action='/case/{cid}/document' class='form-grid' style='margin-top:10px'><input type='hidden' name='return_to' value='/documents'><div><label>Data dokumentu</label><input type='date' name='doc_date'></div><div><label>Data wpływu</label><input type='date' name='received_date'></div><div><label>Data doręczenia</label><input type='date' name='delivered_date'></div><div><label>Rodzaj</label><select name='doc_type'>{doc_form_opts}</select></div><div><label>Status</label><select name='doc_status'>{doc_status_form_opts}</select></div><div><label>Nadawca</label><input name='sender'></div><div><label>Autor dokumentu</label><input name='document_author'></div><div><label>Tagi</label><input name='tags' placeholder='np. dowód, pilne'></div><div class='full'><label>Tytuł *</label><input name='title' required></div><div class='full'><label>Opis</label><input name='description'></div><div class='full'><label>Pismo / dokument główny</label><input type='file' name='file'><label style='font-weight:500'><input style='width:auto' type='checkbox' name='allow_duplicate' value='1'> Zezwól na identyczny plik</label></div><div class='full'><label>Załączniki do pisma</label><input type='file' name='attachments[]' multiple><div class='small muted'>Każdy plik zostanie zapisany jako załącznik tego dokumentu.</div></div><div class='full'><button class='btn primary'>Dodaj dokument</button></div></form></details>"""
            folders.append(f"""<details class='doc-case-folder'{open_attr} id='docs-{cid}'><summary><span class='doc-chevron'>›</span><div class='doc-folder-main'><div class='doc-folder-title'>{esc(primary)} · {esc(internal)} — {esc(first['case_title'])}</div><div class='doc-folder-sub'>{client or 'Kliknij, aby rozwinąć dokumenty sprawy'}</div></div><span class='doc-count'>{len(docs)} dok.</span><span class='doc-latest'>najnowszy: {latest}</span></summary><div class='doc-folder-body'><div class='doc-folder-actions'><a class='btn small' href='/case/{cid}'>Karta sprawy</a></div><div class='doc-type-toolbar'>{type_buttons}</div>{quick_form}{''.join(year_html)}</div></details>""")
        folders_html=''.join(folders) or '<div class="empty">Brak dokumentów.</div>'
        order_desc='primary' if order=='desc' else ''; order_asc='primary' if order=='asc' else ''; hidden_q=f"&q={quote(q)}" if q else ''; hidden_type=f"&type={quote(dtype)}" if dtype else ''; hidden_status=f"&status={quote(dstatus)}" if dstatus else ''
        script="""<script>function filterDocs(folderId,type,btn){const f=document.getElementById(folderId);if(!f)return;f.querySelectorAll('.doc-type-filter').forEach(x=>x.classList.remove('active'));btn.classList.add('active');f.querySelectorAll('.doc-filter-row').forEach(r=>{r.style.display=(!type||r.dataset.docType===type)?'':'none'});f.querySelectorAll('.year-folder').forEach(y=>{const visible=[...y.querySelectorAll('.doc-filter-row')].some(r=>r.style.display!=='none');y.style.display=visible?'':'none';});}</script>"""
        save_view=self._save_view_form(self.path)
        body=f"""<div class='topbar'><div><h1>Dokumenty</h1><div class='sub'>{len(groups)} teczek spraw · {len(rows)} dokumentów. Teczka → rok → dokument.</div></div><div><a class='btn primary' href='/quick-add'>+ Dokument</a> <a class='btn' href='/cases'>Wybierz sprawę</a></div></div><details class='card filter-panel'><summary>Filtry dokumentów</summary><form class='form-grid' method='get' style='margin-top:12px'><input type='hidden' name='order' value='{order}'><div><label>Szukaj</label><input name='q' value='{esc(q)}' placeholder='Tytuł, plik, sygnatura, autor…'></div><div><label>Rodzaj</label><select name='type'><option value=''>Wszystkie</option>{opts}</select></div><div><label>Status</label><select name='status'><option value=''>Wszystkie statusy</option>{status_filter_opts}</select></div><div class='full'><button class='btn'>Filtruj</button> <a class='btn' href='/documents'>Wyczyść</a> <a class='btn' href='/documents?status=Do%20podpisu'>Do podpisu</a></div></form></details>{save_view}<br><div class='doc-toolbar'><div class='small muted'>W każdej teczce możesz dodatkowo filtrować typ dokumentu bez przeładowania strony.</div><div class='doc-toolbar-actions'><a class='btn small {order_desc}' href='/documents?order=desc{hidden_q}{hidden_type}{hidden_status}'>Najnowsze najpierw</a><a class='btn small {order_asc}' href='/documents?order=asc{hidden_q}{hidden_type}{hidden_status}'>Najstarsze najpierw</a><button class='btn small' type='button' onclick="document.querySelectorAll('.doc-case-folder').forEach(x=>x.open=true)">Rozwiń wszystkie</button><button class='btn small' type='button' onclick="document.querySelectorAll('.doc-case-folder').forEach(x=>x.open=false)">Zwiń wszystkie</button></div></div><div class='doc-folders'>{folders_html}</div>{script}"""
        self.send_html(layout('Dokumenty',body,'documents'))

    def note_add(self,cid,f):
        note=f.get('note','').strip(); a=self.current_author(f)
        if note:
            with db() as con:
                cur=con.execute("INSERT INTO case_notes(case_id,note,author) VALUES(?,?,?)",(cid,note,a))
                audit(con,cid,'note',cur.lastrowid,'Dodano notatkę',note[:120],a)
        target=(f.get('return_to','') or '').strip()
        self.redirect(target if target.startswith('/') else f'/case/{cid}')

    def note_delete(self,nid,f):
        try: cid=int(f.get('case_id','0') or 0)
        except ValueError: cid=0
        a=self.current_author(f)
        with db() as con: move_to_trash(con,'note',nid,a)
        self.redirect(f'/case/{cid}')

    def history_page(self,qs):
        try: cid=int((qs.get('case_id') or ['0'])[0] or 0)
        except ValueError: cid=0
        q=(qs.get('q') or [''])[0].strip(); params=[]; sql="SELECT a.*,c.title case_title,c.signature,c.internal_signature FROM audit_log a LEFT JOIN cases c ON c.id=a.case_id WHERE 1=1"
        if cid: sql += " AND a.case_id=?"; params.append(cid)
        if q:
            like=f"%{q}%"; sql += " AND (a.action LIKE ? OR a.description LIKE ? OR a.author LIKE ? OR c.title LIKE ? OR c.signature LIKE ? OR c.internal_signature LIKE ?)"; params += [like]*6
        sql += " ORDER BY a.id DESC LIMIT 500"
        with db() as con: rows=con.execute(sql,params).fetchall()
        items=[]
        for r in rows:
            if r['case_id'] and r['case_title']:
                sig=primary_signature_text(r['case_id'],r['signature'],r['internal_signature']); case=f"<a class='case-link' href='/case/{r['case_id']}'>{esc(sig if sig!='Bez sygnatury' else r['case_title'])}</a>"
            else: case='—'
            target=audit_target_html(r)
            items.append(f"<tr><td class='nowrap'>{esc(r['created_at'])}</td><td>{case}</td><td><b>{esc(r['action'])}</b><div class='small muted' style='margin:4px 0'>{audit_description_html(r['description'])}</div>{target}</td><td>{esc(r['author']) or '—'}</td></tr>")
        body=f"""<div class='topbar'><div><h1>Historia zmian</h1><div class='sub'>Dziennik czynności: dokładnie co zmieniono, przez kogo i kiedy. Przy dokumentach, pismach i zadaniach dostępny jest bezpośredni odnośnik.</div></div></div><div class='card'><form class='searchbar'><input name='q' value='{esc(q)}' placeholder='Autor, czynność, sprawa…'>{f"<input type='hidden' name='case_id' value='{cid}'>" if cid else ''}<button class='btn'>Filtruj</button></form></div><br><div class='card'><table><tr><th>Data</th><th>Sprawa</th><th>Zmiana</th><th>Autor</th></tr>{''.join(items) or '<tr><td colspan=4>Brak wpisów.</td></tr>'}</table></div>"""
        self.send_html(layout('Historia zmian',body,'history'))

    def trash_page(self,qs):
        purge_old_trash()
        with db() as con:
            rows=con.execute("SELECT r.*,c.title case_title,c.signature,c.internal_signature FROM recycle_bin r LEFT JOIN cases c ON c.id=r.case_id ORDER BY r.deleted_at DESC LIMIT 1000").fetchall()
        items=[]
        labels={k:v[1] for k,v in TRASH_TABLES.items()}
        for r in rows:
            case='—'
            if r['case_id'] and r['case_title']:
                sig=primary_signature_text(r['case_id'],r['signature'],r['internal_signature']); case=f"<a class='case-link' href='/case/{r['case_id']}'>{esc(sig if sig!='Bez sygnatury' else r['case_title'])}</a>"
            items.append(f"<tr><td><span class='pill'>{esc(labels.get(r['entity_type'],r['entity_type']))}</span></td><td><b>{esc(r['label']) or '—'}</b><div class='trash-age'>usunięto: {esc(r['deleted_at'])} · przez: {esc(r['deleted_by'])}</div></td><td>{case}</td><td class='nowrap'><form method='post' action='/trash/{r['id']}/restore' style='display:inline'><button class='btn small primary'>Przywróć</button></form> <form method='post' action='/trash/{r['id']}/purge' style='display:inline' onsubmit=\"return confirm('Usunąć trwale? Tej operacji nie można cofnąć.');\"><button class='btn small danger'>Usuń trwale</button></form></td></tr>")
        body=f"""<div class='topbar'><div><h1>Kosz</h1><div class='sub'>Usunięte zadania, dokumenty i wpisy można przywrócić. Elementy starsze niż {TRASH_RETENTION_DAYS} dni są automatycznie czyszczone.</div></div></div><div class='card'><table><tr><th>Typ</th><th>Element</th><th>Sprawa</th><th>Akcje</th></tr>{''.join(items) or '<tr><td colspan=4>Kosz jest pusty.</td></tr>'}</table></div>"""
        self.send_html(layout('Kosz',body,'trash'))

    def trash_restore(self,trash_id,f):
        a=self.current_author(f)
        with db() as con: ok,cid=restore_from_trash(con,trash_id,a)
        self.redirect(f'/case/{cid}' if ok and cid else '/trash')

    def trash_purge(self,trash_id,f):
        with db() as con:
            tr=con.execute("SELECT * FROM recycle_bin WHERE id=?",(trash_id,)).fetchone()
            if tr:
                if tr['entity_type']=='document':
                    try:
                        payload=json.loads(tr['payload_json']); stored=payload.get('stored_name'); cid=payload.get('case_id')
                        if stored and cid: (FILES_DIR/f"sprawa_{cid}"/stored).unlink(missing_ok=True)
                    except Exception: pass
                con.execute("DELETE FROM recycle_bin WHERE id=?",(trash_id,))
        self.redirect('/trash')

    def backups_page(self,message=''):
        when,path=ensure_daily_backup(); groups=[('Dzienne',DAILY_BACKUPS_DIR),('Przy zamykaniu',CLOSE_BACKUPS_DIR),('Przed aktualizacją',BACKUPS_DIR)]; rows=[]
        for label,folder in groups:
            folder.mkdir(parents=True,exist_ok=True)
            files=sorted(list(folder.glob('*.sqlite3'))+list(folder.glob('*.sqlite3.rkenc')),key=lambda x:x.stat().st_mtime,reverse=True)[:30]
            for x in files:
                restore=(f"<form method='post' action='/backups/restore' style='display:inline' onsubmit=\"return confirm('Przygotować przywrócenie tej kopii? Bieżąca baza zostanie wcześniej zabezpieczona, a właściwe przywrócenie nastąpi po ponownym uruchomieniu.');\"><input type='hidden' name='backup' value='{esc(x.name)}'><button class='btn small'>Przywróć</button></form>" if current_request_user() and current_request_user()['role']=='admin' else '')
                rows.append(f"<tr><td>{esc(label)}</td><td>{esc(datetime.fromtimestamp(x.stat().st_mtime).strftime('%d.%m.%Y %H:%M'))}</td><td>{esc(x.name)}{' 🔒' if x.name.endswith('.rkenc') else ''}</td><td>{x.stat().st_size/1024:.1f} KB</td><td>{restore}</td></tr>")
        msg=f"<div class='notice'>{esc(message)}</div>" if message else ''
        pending=''
        if PENDING_RESTORE_MARKER.exists():
            try: pmeta=json.loads(PENDING_RESTORE_MARKER.read_text(encoding='utf-8'))
            except Exception: pmeta={}
            if pmeta.get('kind')=='installed_import':
                pending="<div class='notice'><b>Import danych Installed jest przygotowany.</b> Zamknij RK KANCELARIA i uruchom ją ponownie. Baza i dokumenty zostaną przełączone dopiero przy starcie, po wykonaniu kopii bezpieczeństwa.</div>"
            else:
                pending="<div class='notice'><b>Przywrócenie jest zaplanowane.</b> Zamknij RK KANCELARIA i uruchom ją ponownie. Przed podmianą zostanie zachowana dodatkowa kopia bieżącej bazy.</div>"

        db_ok,db_reason=sqlite_integrity(DB_PATH)
        db_state=(f"<span class='backup-ok'>✓ Baza SQLite: {esc(db_reason)}</span>" if db_ok else f"<span class='conflict-warning'>⚠ Baza SQLite: {esc(db_reason)}</span>")
        import_card=''
        src=installed_import_source()
        if src:
            src_dir,src_db=src; ss=_database_summary(src_db); ds=_database_summary(DB_PATH) if DB_PATH.exists() else {'core_records':0,'latest_activity':'','version':''}
            counts=ss.get('counts',{})
            summary=(f"{counts.get('cases',0)} spraw · {counts.get('documents',0)} dokumentów · {counts.get('tasks',0)} zadań")
            admin=bool(current_request_user() and current_request_user()['role']=='admin')
            button=("<form method='post' action='/data/import-installed' onsubmit=\"return confirm('Przygotować import danych ze starej wersji Installed? Bieżąca baza i dokumenty zostaną wcześniej skopiowane do backup_przed_importem. Właściwa podmiana nastąpi dopiero po restarcie.');\"><button class='btn primary'>Importuj dane z Installed</button></form>" if admin and not PENDING_RESTORE_MARKER.exists() else '')
            import_card=f"""<div class='card'><div class='section-head'><div><h2>Import ze starej RK KANCELARIA (Installed)</h2><div class='small muted'>Program wykrył osobny katalog danych: {esc(str(src_dir))}</div></div></div><p><b>Źródło:</b> {esc(summary)}<br><b>Wersja źródła:</b> {esc(ss.get('version') or 'nieoznaczona')}<br><b>Ostatnia aktywność:</b> {esc(ss.get('latest_activity') or 'brak danych')}<br><b>Bieżąca baza:</b> {int(ds.get('core_records') or 0)} elementów roboczych · ostatnia aktywność {esc(ds.get('latest_activity') or '—')}</p><p class='small muted'>Import jest chroniony: źródło przechodzi quick_check, przed importem powstaje kopia bazy, dokumentów i projektów pism, a program blokuje automatyczne nadpisanie bazy zawierającej nowszą aktywność.</p>{button}</div><br>"""
        elif APP_MODE=='portable':
            import_card="<div class='card'><h2>Import ze starej wersji</h2><div class='small muted'>Nie znaleziono osobnej bazy Installed w standardowym katalogu %LOCALAPPDATA%\\RK_KANCELARIA\\Dane.</div></div><br>"

        body=f"""<div class='topbar'><div><h1>Kopie bezpieczeństwa</h1><div class='sub'>Kopie dzienne + kopie przy zamykaniu. Przywracanie i import są wykonywane bezpiecznie po restarcie.</div></div><div><a class='btn' href='/recovery'>Recovery</a> <a class='btn' href='/security'>Szyfrowanie</a> <a class='btn primary' href='/backup/snapshot'>Pełny snapshot</a></div></div>{msg}{pending}<div class='notice'><b>Ostatnia automatyczna kopia dzienna:</b> {esc(when)}<br><span class='small'>{esc(path)}</span><br>{db_state}</div>{import_card}<div class='card'><table><tr><th>Rodzaj</th><th>Data</th><th>Plik</th><th>Rozmiar</th><th></th></tr>{''.join(rows) or '<tr><td colspan=5>Brak kopii.</td></tr>'}</table></div>"""
        self.send_html(layout('Kopie bezpieczeństwa',body,'backups'))

    def data_import_installed(self,f):
        if not self.require_admin(): return
        ok,msg=schedule_installed_import()
        if ok:
            log_event('Użytkownik przygotował import danych z wersji Installed','WARNING')
        return self.backups_page(msg)

    def backup_restore_schedule(self,f):
        if not self.require_admin(): return
        p=_allowed_backup_by_token(f.get('backup',''))
        if not p: return self.backups_page('Nie znaleziono wskazanej kopii lub ścieżka jest niedozwolona.')
        create_shutdown_backup(retention=30); ok,msg=schedule_backup_restore(p)
        if ok:
            try:
                with db() as con: immutable_audit(con,None,'backup',None,'Zaplanowano przywrócenie backupu',p.name,self.current_author(f))
            except Exception: pass
        return self.backups_page(msg)

    def recovery_page(self,message=''):
        if not self.require_admin(): return
        quick_ok,quick_reason=sqlite_integrity(DB_PATH)
        with db() as con:
            last=con.execute("SELECT * FROM system_checks WHERE check_type='integrity' ORDER BY id DESC LIMIT 1").fetchone()
        backups=sum(1 for folder in (DAILY_BACKUPS_DIR,CLOSE_BACKUPS_DIR,BACKUPS_DIR) for _ in folder.glob('*.sqlite3*'))
        last_html=(f"<b>Ostatnia pełna kontrola:</b> {esc(last['created_at'])} · {esc(last['result'])}<br><span class='small'>{esc(last['details'])}</span>" if last else "Pełna kontrola integralności nie była jeszcze uruchamiana.")
        msg=f"<div class='notice'>{esc(message)}</div>" if message else ''
        state=(f"<span class='backup-ok'>✓ quick_check: {esc(quick_reason)}</span>" if quick_ok else f"<span class='conflict-warning'>⚠ quick_check: {esc(quick_reason)}</span>")
        body=f"""<div class='topbar'><div><h1>Recovery i integralność</h1><div class='sub'>Kontrola bazy, ręczne kopie i pełny przenośny snapshot danych.</div></div><a class='btn' href='/backups'>← Kopie bezpieczeństwa</a></div>{msg}
        <div class='grid'><div class='card span6'><h2>Stan bazy</h2><p>{state}</p><p>{last_html}</p><form method='post' action='/recovery/check'><button class='btn primary'>Uruchom pełny integrity_check</button></form><p class='small muted'>Pełny test jest dokładniejszy niż codzienny quick_check i może potrwać dłużej przy dużej bazie.</p></div>
        <div class='card span6'><h2>Kopia ratunkowa</h2><p><b>Znalezione kopie:</b> {backups}</p><form method='post' action='/backup/manual' style='margin-bottom:8px'><button class='btn'>Wykonaj backup teraz</button></form><form method='post' action='/recovery/test-restore' style='display:inline'><button class='btn'>Przetestuj odtworzenie</button></form> <a class='btn primary' href='/backup/snapshot'>Pobierz pełny snapshot</a><p class='small muted'>Test tworzy pełny snapshot, odtwarza jego bazę w katalogu tymczasowym i sprawdza obecność wszystkich plików dokumentów. Nie zmienia bieżących danych.</p><hr><form method='post' enctype='multipart/form-data' action='/recovery/snapshot-import' onsubmit="return confirm('Przygotować przywrócenie pełnego snapshotu? Bieżący stan zostanie zabezpieczony, a przełączenie nastąpi po restarcie.');"><label>Przywróć pełny snapshot</label><input type='file' name='snapshot' accept='.zip' required><button class='btn'>Zweryfikuj i przygotuj restore</button></form></div></div>
        <br><div class='card'><h2>Tryb ratunkowy</h2><p>Przy starcie RK KANCELARIA sprawdza bazę i zachowuje kopie przed operacjami przywracania/importu. Uszkodzonego pliku nie nadpisujemy „w ciemno”. Przywrócenie backupu jest planowane i wykonywane dopiero po restarcie programu.</p><p><b>Katalog Recovery:</b><br><code>{esc(str(RECOVERY_DIR))}</code></p></div>"""
        self.send_html(layout('Recovery',body,'recovery'))

    def recovery_check(self,f):
        if not self.require_admin(): return
        ok,details=full_sqlite_integrity(DB_PATH); result='OK' if ok else 'BŁĄD'
        with db() as con:
            con.execute("INSERT INTO system_checks(check_type,result,details,created_by) VALUES('integrity',?,?,?)",(result,details,self.current_author(f)))
            immutable_audit(con,None,'system_check',None,'Pełna kontrola integralności SQLite',f'{result}: {details}',self.current_author(f))
        return self.recovery_page(f'Pełna kontrola zakończona: {result} — {details}')

    def recovery_test_restore(self,f):
        if not self.require_admin(): return
        author=self.current_author(f)
        try:
            raw,name=create_data_snapshot_zip()
            with zipfile.ZipFile(io.BytesIO(raw),'r') as z, tempfile.TemporaryDirectory(prefix='rk_restore_test_') as td:
                names=set(z.namelist())
                db_copy=Path(td)/'sprawnik.sqlite3'
                atomic_write_bytes(db_copy,z.read('sprawnik.sqlite3'))
                ok,details=full_sqlite_integrity(db_copy)
                if not ok: raise RuntimeError(details)
                test_con=sqlite3.connect(db_copy); test_con.row_factory=sqlite3.Row
                try:
                    counts={t:int(test_con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]) for t in ('cases','documents','tasks','case_assertions','case_claims')}
                    missing=[]
                    for d in test_con.execute("SELECT case_id,stored_name FROM documents WHERE stored_name<>''"):
                        expected=f"dokumenty/sprawa_{d['case_id']}/{d['stored_name']}"
                        if expected not in names: missing.append(expected)
                finally:
                    test_con.close()
                if missing: raise RuntimeError(f'brakuje {len(missing)} plików dokumentów; pierwszy: {missing[0]}')
                details=' · '.join(f'{k}: {v}' for k,v in counts.items())+f' · pliki dokumentów: komplet · {name}'
                result='OK'
        except Exception as exc:
            result='BŁĄD'; details=str(exc)
        with db() as con:
            con.execute("INSERT INTO system_checks(check_type,result,details,created_by) VALUES('restore_test',?,?,?)",(result,details,author))
            immutable_audit(con,None,'system_check',None,'Test odtworzenia pełnego snapshotu',f'{result}: {details}',author)
        return self.recovery_page(f'Test odtworzenia: {result} — {details}')

    def manual_backup_now(self,f):
        if not self.require_admin(): return
        when,path=create_shutdown_backup(retention=30)
        try:
            with db() as con: immutable_audit(con,None,'backup',None,'Wykonano ręczny backup',str(path),self.current_author(f))
        except Exception: pass
        return self.recovery_page(f'Backup wykonany: {when} · {path}')

    def full_snapshot_download(self):
        if not self.require_admin(): return
        data,name=create_data_snapshot_zip()
        try:
            with db() as con: immutable_audit(con,None,'snapshot',None,'Pobrano pełny snapshot danych',f'{name} · {len(data)} B',self.current_author())
        except Exception: pass
        self.send_response(200); self.send_header('Content-Type','application/zip'); self.send_header('Content-Disposition',f"attachment; filename*=UTF-8''{quote(name)}"); self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(data)

    def full_snapshot_import(self,f,files):
        if not self.require_admin(): return
        uploaded=files.get('snapshot')
        if not uploaded or not uploaded[1]: return self.recovery_page('Wybierz plik snapshot ZIP.')
        create_shutdown_backup(retention=30)
        ok,msg=schedule_data_snapshot_restore(uploaded[1],uploaded[0] or 'snapshot',0)
        if ok:
            try:
                with db() as con: immutable_audit(con,None,'snapshot',None,'Zaplanowano przywrócenie pełnego snapshotu',uploaded[0] or 'snapshot',self.current_author(f))
            except Exception: pass
        return self.recovery_page(msg)

    def cloud_page(self,message=''):
        if not self.require_admin(): return
        with db() as con: cfg=cloud_config(con)
        remote='Nie sprawdzano serwera.'; remote_class='small muted'
        if cfg['url'] and cfg['token']:
            try:
                from rk_cloud import get_meta
                m=get_meta(cfg['url'],cfg['office_id'],cfg['token'])
                remote=(f"Serwer: v{m.version} · {m.size/1024/1024:.1f} MB · {m.updated_at or '—'}" if m.exists else 'Serwer nie ma jeszcze snapshotu tej kancelarii.')
                remote_class='backup-ok'
            except Exception as exc:
                remote=f'Nie udało się odczytać serwera: {exc}'; remote_class='conflict-warning'
        token_hint=('••••••••'+cfg['token'][-4:] if cfg['token'] else 'nie ustawiono')
        msg=f"<div class='notice'>{esc(message)}</div>" if message else ''
        pending=''
        if PENDING_RESTORE_MARKER.exists():
            try: pm=json.loads(PENDING_RESTORE_MARKER.read_text(encoding='utf-8'))
            except Exception: pm={}
            if pm.get('kind')=='cloud_snapshot': pending="<div class='notice'><b>Pobranie z Cloud jest przygotowane.</b> Zamknij i ponownie uruchom RK KANCELARIA, aby bezpiecznie przełączyć bazę i pliki.</div>"
        body=f"""<div class='topbar'><div><h1>Cloud i urządzenia</h1><div class='sub'>Wersjonowana synchronizacja pełnego stanu + fundament pracy Windows / telefon / tablet.</div></div><a class='btn' href='/recovery'>Recovery</a></div>{msg}{pending}
        <div class='grid'><div class='card span6'><h2>Konfiguracja Cloud Bridge</h2><form method='post' action='/cloud/config'><label>Adres HTTPS serwera</label><input name='url' value='{esc(cfg['url'])}' placeholder='https://cloud.twojakancelaria.pl'><label>ID kancelarii</label><input name='office_id' value='{esc(cfg['office_id'])}' required><label>Token dostępu</label><input type='password' name='token' placeholder='{esc(token_hint)}'><div class='small muted'>Pozostaw token pusty, aby zachować obecny. W produkcji używaj HTTPS/VPN; nie wystawiaj lokalnego HTTP do Internetu.</div><button class='btn primary'>Zapisz konfigurację</button></form></div>
        <div class='card span6'><h2>Stan synchronizacji</h2><p><b>Lokalnie zapamiętana wersja:</b> v{esc(cfg['last_version'])}<br><b>Ostatnia synchronizacja:</b> {esc(cfg['last_sync'] or '—')}</p><p class='{remote_class}'>{esc(remote)}</p><div class='case-control-bar'><form method='post' action='/cloud/check'><button class='btn'>Sprawdź połączenie</button></form><form method='post' action='/cloud/push' onsubmit="return confirm('Wysłać pełny aktualny snapshot do Cloud? Wersja serwera musi zgadzać się z wersją ostatnio widzianą przez ten komputer.');"><button class='btn primary'>Wyślij do Cloud</button></form></div><br><form method='post' action='/cloud/pull' onsubmit="return confirm('Pobrać stan z Cloud? Bieżący lokalny stan zostanie najpierw zabezpieczony, a podmiana nastąpi dopiero po ponownym uruchomieniu.');"><button class='btn'>Pobierz z Cloud</button></form></div></div>
        <br><div class='card'><h2>Telefon / tablet / PWA</h2><p>DEV8 jest przygotowany jako PWA: po wystawieniu tej samej aplikacji przez bezpieczny HTTPS możesz dodać RK KANCELARIA do ekranu głównego telefonu/tabletu. Service Worker buforuje wyłącznie statyczny interfejs — dane spraw i dokumenty nie są utrwalane offline w pamięci przeglądarki.</p><p class='small muted'>Cloud Bridge używa PostgreSQL jako magazynu wersjonowanych snapshotów z kontrolą konfliktu. Nie udaje scalania rekord-po-rekordzie: jeśli dwa urządzenia zmienią dane niezależnie, program blokuje ciche nadpisanie i wymaga świadomego rozstrzygnięcia.</p></div>"""
        self.send_html(layout('Cloud',body,'cloud'))

    def cloud_config_update(self,f):
        if not self.require_admin(): return
        url=(f.get('url','') or '').strip().rstrip('/')
        office=(f.get('office_id','') or 'default').strip()[:180]
        token=(f.get('token','') or '').strip()
        if url and not re.match(r'^https?://',url,re.I): return self.cloud_page('Adres Cloud musi zaczynać się od http:// lub https://.')
        with db() as con:
            settings_set(con,'cloud_url',url); settings_set(con,'cloud_office_id',office)
            if token: settings_set(con,'cloud_token',token)
            immutable_audit(con,None,'cloud',None,'Zmieniono konfigurację Cloud',f'URL: {url or "—"}\nKancelaria: {office}',self.current_author(f))
        return self.cloud_page('Konfiguracja Cloud została zapisana.')

    def cloud_check(self,f):
        if not self.require_admin(): return
        with db() as con: cfg=cloud_config(con)
        try:
            from rk_cloud import health,get_meta
            h=health(cfg['url'],cfg['token']); m=get_meta(cfg['url'],cfg['office_id'],cfg['token'])
            text=f"Połączenie działa. {h.get('service','RK Cloud')} · zdalna wersja v{m.version if m.exists else 0}."
        except Exception as exc: text=f'Błąd połączenia: {exc}'
        return self.cloud_page(text)

    def cloud_push(self,f):
        if not self.require_admin(): return
        with db() as con: cfg=cloud_config(con)
        try:
            from rk_cloud import get_meta,push_snapshot
            remote=get_meta(cfg['url'],cfg['office_id'],cfg['token'])
            remembered=int(cfg['last_version'] or 0)
            if remote.version!=remembered:
                return self.cloud_page(f'Konflikt Cloud: serwer ma v{remote.version}, a ten komputer pamięta v{remembered}. Nie wysłano danych. Najpierw sprawdź/pobierz nowszy stan albo rozwiąż konflikt świadomie.')
            data,name=create_data_snapshot_zip()
            result=push_snapshot(cfg['url'],cfg['office_id'],cfg['token'],data,remote.version)
            now=datetime.now().isoformat(timespec='seconds')
            with db() as con:
                settings_set(con,'cloud_last_version',str(result.version)); settings_set(con,'cloud_last_sync',now); settings_set(con,'cloud_last_sha256',result.sha256)
                immutable_audit(con,None,'cloud',None,'Wysłano snapshot do Cloud',f'{name}\nWersja: {result.version}\nSHA-256: {result.sha256}',self.current_author(f))
            return self.cloud_page(f'Wysłano pełny stan do Cloud jako wersję v{result.version}.')
        except Exception as exc:
            return self.cloud_page(f'Nie wysłano danych: {exc}')

    def cloud_pull(self,f):
        if not self.require_admin(): return
        with db() as con: cfg=cloud_config(con)
        try:
            from rk_cloud import pull_snapshot
            raw,meta=pull_snapshot(cfg['url'],cfg['office_id'],cfg['token'])
            create_shutdown_backup(retention=30)
            ok,msg=schedule_data_snapshot_restore(raw,f"Cloud {cfg['office_id']}",meta.version)
            if ok:
                with db() as con: immutable_audit(con,None,'cloud',None,'Zaplanowano pobranie snapshotu z Cloud',f'Wersja: {meta.version}\nSHA-256: {meta.sha256}',self.current_author(f))
            return self.cloud_page(msg)
        except Exception as exc:
            return self.cloud_page(f'Nie pobrano danych: {exc}')


    def tags_page(self,qs):
        q=(qs.get('q') or [''])[0].strip(); like=f"%{q}%"
        with db() as con:
            if q:
                rows=con.execute("SELECT t.name,COUNT(ct.case_id) cnt FROM tags t LEFT JOIN case_tags ct ON ct.tag_id=t.id WHERE t.name LIKE ? GROUP BY t.id,t.name ORDER BY t.name",(like,)).fetchall()
            else:
                rows=con.execute("SELECT t.name,COUNT(ct.case_id) cnt FROM tags t LEFT JOIN case_tags ct ON ct.tag_id=t.id GROUP BY t.id,t.name ORDER BY t.name").fetchall()
        items=''.join(f"<tr><td><a class='tag' href='/cases?tag={quote(r['name'])}'>{esc(r['name'])}</a></td><td>{r['cnt']}</td><td><a class='btn small' href='/cases?tag={quote(r['name'])}'>Pokaż sprawy</a></td></tr>" for r in rows) or '<tr><td colspan=3>Brak tagów.</td></tr>'
        body=f"""<div class='topbar'><div><h1>Tagi</h1><div class='sub'>Wyszukuj tagi i przechodź do wszystkich spraw oznaczonych danym tagiem.</div></div></div><div class='card'><form class='searchbar'><input name='q' value='{esc(q)}' placeholder='np. Alicja, zabezpieczenie, Sobol'><button class='btn primary'>Szukaj tagu</button></form></div><br><div class='card'><table><tr><th>Tag</th><th>Liczba spraw</th><th></th></tr>{items}</table></div>"""
        self.send_html(layout('Tagi',body,'tags'))

    def case_export_page(self,cid):
        with db() as con: c=con.execute("SELECT * FROM cases WHERE id=?",(cid,)).fetchone()
        if not c: return self.send_error(404)
        shown_sig, shown_kind = display_signature_meta(cid, c['signature'], c['internal_signature'])
        primary = primary_signature_text(cid, c['signature'], c['internal_signature'])
        body=f"""<div class='topbar'><div><h1>Wyciąg PDF</h1><div class='sub'>{esc(primary)} · {esc(internal_signature_text(c['internal_signature']))} · {esc(c['title'])}</div></div><a class='btn' href='/case/{cid}'>Wróć do sprawy</a></div>
        <div class='grid'><div class='card span6'><h2>Pełny wyciąg</h2><p class='muted'>Dane sprawy, strony, powiązania, oś czasu, zadania, dokumenty i notatki.</p><a class='btn primary' href='/case/{cid}/export/pdf?full=1'>Pobierz pełny PDF</a></div>
        <div class='card span6'><h2>Wyciąg fragmentaryczny</h2><form method='post' action='/case/{cid}/export/pdf'><div class='checkgrid'>
        <label><input type='checkbox' name='overview' value='1' checked> Dane sprawy</label><label><input type='checkbox' name='parties' value='1'> Strony / uczestnicy</label><label><input type='checkbox' name='relations' value='1'> Powiązane sprawy</label><label><input type='checkbox' name='events' value='1' checked> Oś czasu</label><label><input type='checkbox' name='tasks' value='1' checked> Zadania</label><label><input type='checkbox' name='documents' value='1' checked> Dokumenty</label><label><input type='checkbox' name='notes' value='1'> Notatki chronologiczne</label></div><button class='btn primary' style='margin-top:15px'>Generuj i pobierz PDF</button></form></div></div>"""
        self.send_html(layout('Eksport PDF',body,'cases'))

    def case_export_pdf(self,cid,qs,fields):
        all_sections={'overview','parties','relations','events','tasks','documents','notes'}
        if (qs.get('full') or [''])[0]=='1': sections=all_sections
        else:
            f=fields or {}; sections={x for x in all_sections if f.get(x)}
            if not sections: sections={'overview'}
        data,name=build_case_pdf(cid,sections)
        self.send_response(200); self.send_header('Content-Type','application/pdf'); self.send_header('Content-Length',str(len(data))); self.send_header('Content-Disposition',f"attachment; filename*=UTF-8''{quote(name)}"); self.end_headers(); self.wfile.write(data)

    def search_page(self,qs):
        q=(qs.get('q') or [''])[0].strip(); results=[]; text_hits=[]
        if q:
            like=f"%{q}%"
            with db() as con:
                case_matches=con.execute("""SELECT DISTINCT c.* FROM cases c WHERE c.signature LIKE ? OR c.internal_signature LIKE ? OR c.client LIKE ? OR c.title LIKE ? OR c.subject LIKE ? OR c.notes LIKE ? OR c.next_step LIKE ? OR c.waiting_for LIKE ? OR c.created_by LIKE ? OR c.updated_by LIKE ? OR EXISTS (SELECT 1 FROM users u WHERE u.id=c.lead_user_id AND (u.author_name LIKE ? OR u.function LIKE ?)) OR EXISTS (SELECT 1 FROM case_tags ct JOIN tags t ON t.id=ct.tag_id WHERE ct.case_id=c.id AND t.name LIKE ?) OR EXISTS (SELECT 1 FROM case_external_signatures es WHERE es.case_id=c.id AND (es.label LIKE ? OR es.signature LIKE ?)) OR EXISTS (SELECT 1 FROM case_entities ce JOIN entities e ON e.id=ce.entity_id WHERE ce.case_id=c.id AND (e.display_name LIKE ? OR e.pesel LIKE ? OR e.nip LIKE ? OR e.krs LIKE ? OR ce.role LIKE ?))""",(like,)*20).fetchall()
                for r in case_matches:
                    primary=primary_signature_text(r['id'],r['signature'],r['internal_signature'])
                    desc=internal_signature_text(r['internal_signature'])+' · '+(r['subject'] or '')
                    results.append(('Sprawa',r['id'],primary if primary!='Bez sygnatury' else r['title'],desc))
                results += [('Podmiot',None,r['display_name'],f"PESEL {r['pesel']} · NIP {r['nip']} · KRS {r['krs']} · {r['email']}") for r in con.execute("SELECT * FROM entities WHERE display_name LIKE ? OR first_name LIKE ? OR last_name LIKE ? OR company_name LIKE ? OR pesel LIKE ? OR nip LIKE ? OR krs LIKE ? OR email LIKE ? OR phone LIKE ?",(like,)*9)]
                results += [('Dodatkowa sygnatura',r['case_id'],f"{r['label']}: {r['signature']}",f"autor: {r['created_by']}") for r in con.execute("SELECT * FROM case_external_signatures WHERE label LIKE ? OR signature LIKE ? OR created_by LIKE ? OR updated_by LIKE ?",(like,)*4)]
                results += [('Strona',r['case_id'],r['name'],f"{r['role']} · {r['case_title']} · autor: {r['created_by']}") for r in con.execute("SELECT p.*,c.title case_title FROM parties p JOIN cases c ON c.id=p.case_id WHERE p.name LIKE ? OR p.role LIKE ? OR p.notes LIKE ? OR p.created_by LIKE ? OR p.updated_by LIKE ?",(like,)*5)]
                results += [('Zdarzenie',r['case_id'],r['title'],f"{fmt_date(r['event_date'])} · {r['description']} · autor: {r['created_by']}") for r in con.execute("SELECT * FROM events WHERE title LIKE ? OR description LIKE ? OR event_type LIKE ? OR created_by LIKE ? OR updated_by LIKE ?",(like,)*5)]
                results += [('Zadanie',r['case_id'],r['title'],f"{fmt_date(r['due_date'])} · {r['depends_on']} · autor: {r['created_by']}") for r in con.execute("SELECT t.* FROM tasks t WHERE t.title LIKE ? OR t.notes LIKE ? OR t.depends_on LIKE ? OR t.created_by LIKE ? OR t.updated_by LIKE ? OR EXISTS (SELECT 1 FROM users u WHERE u.id=t.assigned_user_id AND (u.author_name LIKE ? OR u.function LIKE ?))",(like,)*7)]
                results += [('Dokument',r['case_id'],r['title'],f"{r['doc_type']} · {r['doc_status']} · dokument: {fmt_date(r['doc_date'])} · wpływ: {fmt_date(r['received_date'])}") for r in con.execute("SELECT * FROM documents WHERE title LIKE ? OR description LIKE ? OR original_name LIKE ? OR doc_type LIKE ? OR doc_status LIKE ? OR doc_date LIKE ? OR received_date LIKE ? OR created_by LIKE ? OR updated_by LIKE ?",(like,)*9)]
                results += [('Notatka',r['case_id'],r['note'][:100],f"{r['created_at']} · autor: {r['author']}") for r in con.execute("SELECT * FROM case_notes WHERE note LIKE ? OR author LIKE ?",(like,like))]
                for r in con.execute("SELECT w.*,c.title case_title FROM writing_projects w LEFT JOIN cases c ON c.id=w.case_id WHERE w.title LIKE ? OR w.content LIKE ? OR w.notes LIKE ? OR w.original_name LIKE ? OR w.doc_type LIKE ? OR w.status LIKE ?",(like,)*6):
                    results.append(('Projekt pisma',r['case_id'],r['title'],f"{r['status']} · {r['doc_type']} · {r['case_title'] or 'bez sprawy'} · autor: {r['created_by']}"))
                text_hits=fulltext_document_search(con,q,100)
        item_parts=[]
        for kind,cid,title,desc in results:
            if kind=='Podmiot':
                with db() as con: er=con.execute('SELECT id FROM entities WHERE display_name=? COLLATE NOCASE LIMIT 1',(title,)).fetchone()
                href=f"/entity/{er['id']}" if er else '/entities'
            else: href=f"/case/{cid}" if cid else '#'
            item_parts.append(f"<tr><td><span class='pill'>{esc(kind)}</span></td><td><a class='case-link' href='{href}'>{esc(title)}</a><div class='small muted'>{esc(desc)}</div></td></tr>")
        items=''.join(item_parts) if q else ''
        if q and not results: items='<tr><td colspan=2>Brak wyników w metadanych.</td></tr>'
        hit_parts=[]
        for r in text_hits:
            sn=esc(r['hit_snippet'] or '')
            sn=sn.replace('⟦','<mark>').replace('⟧','</mark>')
            label=primary_signature_text(r['case_id'],r['signature'],r['internal_signature'])
            ocrbadge=" <span class='pill'>OCR</span>" if r['ocr_used'] else ''
            hit_parts.append(f"<div class='entity-card'><div class='small muted'>{esc(label)} · {esc(r['original_name'] or r['doc_type'])}{ocrbadge}</div><h3 style='margin:5px 0'><a href='/document/{r['id']}/open'>{esc(r['title'])}</a></h3><div class='search-snippet'>{sn or '<span class=\"muted\">Znaleziono w indeksie dokumentu.</span>'}</div><div style='margin-top:8px'><a class='btn small' href='/case/{r['case_id']}#documents'>Otwórz sprawę</a> <a class='btn small' href='/document/{r['id']}/open'>Otwórz dokument</a></div></div>")
        reindex_msg="<div class='notice'>Dokumenty dodano do kolejki indeksowania/OCR. Możesz dalej pracować; wyniki pojawią się po przetworzeniu.</div>" if (qs.get('reindexed') or [''])[0]=='1' else ''
        admin=current_request_user() and current_request_user()['role']=='admin'
        reindex_button="<form method='post' action='/admin/reindex-documents' style='display:inline'><button class='btn small'>Przebuduj indeks dokumentów</button></form>" if admin else ''
        body=f"""<div class='topbar'><div><h1>Wyszukiwarka</h1><div class='sub'>Przeszukuje metadane oraz treść PDF/DOCX/TXT i skanów. Skanowane PDF-y oraz obrazy są automatycznie OCR-owane, jeśli lokalny silnik Tesseract jest dostępny.</div></div>{reindex_button}</div>{reindex_msg}<div class='card'><form class='searchbar' method='get'><input id='globalSearchInput' data-global-search autofocus name='q' value='{esc(q)}' placeholder='np. art. 109 kro, nazwisko, fraza z pisma…'><button class='btn primary'>Szukaj</button></form></div>{f'<br><div class="card"><h2>Wyniki w danych: {len(results)}</h2><table>{items}</table></div>' if q else ''}{f'<br><div class="card"><h2>Wyniki w treści dokumentów: {len(text_hits)}</h2><div class="entity-grid">{"".join(hit_parts) or "<div class=\"empty\">Brak trafień w treści zindeksowanych dokumentów.</div>"}</div></div>' if q else ''}"""
        self.send_html(layout('Wyszukiwarka',body,'search'))

    def ensure_case_editable(self,cid):
        with db() as con:
            ro=case_read_only(con,cid)
        if ro:
            self.send_html(layout('Sprawa tylko do odczytu',f"<div class='card'><h1>Sprawa zakończona — tylko do odczytu</h1><p>Ta sprawa jest zablokowana przed przypadkową edycją. Administrator może ją odblokować z karty sprawy.</p><a class='btn' href='/case/{cid}'>Wróć</a></div>",'cases'),403)
            return False
        return True

    def immutable_audit_page(self,qs):
        if not self.require_admin(): return
        q=(qs.get('q') or [''])[0].strip(); case_id=(qs.get('case_id') or [''])[0].strip(); params=[]
        sql="""SELECT a.*,c.title case_title,c.signature,c.internal_signature FROM immutable_audit a LEFT JOIN cases c ON c.id=a.case_id WHERE 1=1"""
        if q:
            like=f"%{q}%"; sql += " AND (a.action LIKE ? OR a.description LIKE ? OR a.author LIKE ? OR a.username LIKE ? OR a.remote_addr LIKE ? OR c.title LIKE ? OR c.signature LIKE ? OR c.internal_signature LIKE ?)"; params += [like]*8
        if case_id.isdigit(): sql += " AND a.case_id=?"; params.append(int(case_id))
        sql += " ORDER BY a.id DESC LIMIT 1000"
        with db() as con: rows=con.execute(sql,params).fetchall()
        trs=[]
        for r in rows:
            case='—'
            if r['case_id']:
                label=primary_signature_text(r['case_id'],r['signature'],r['internal_signature']) if r['case_title'] else f"Sprawa #{r['case_id']}"
                case=f"<a class='case-link' href='/case/{r['case_id']}'>{esc(label)}</a>"
            trs.append(f"<tr><td class='nowrap'>{esc(r['created_at'])}</td><td>{esc(r['author'])}<div class='small muted'>@{esc(r['username'])} · {esc(r['remote_addr'])}</div></td><td>{case}</td><td><b>{esc(r['action'])}</b><div class='audit-tech'>{esc(r['entity_type'])} #{esc(r['entity_id'])}</div></td><td>{esc(r['description'])}</td></tr>")
        body=f"""<div class='topbar'><div><h1>Dziennik audytowy</h1><div class='sub'>Nieusuwalny techniczny log. Każda operacja dopisuje nowy rekord; aplikacja nie udostępnia edycji ani kasowania tego dziennika.</div></div></div><div class='card'><form class='searchbar'><input name='q' value='{esc(q)}' placeholder='czynność, użytkownik, sygnatura, adres IP…'><button class='btn primary'>Filtruj</button></form></div><br><div class='card'><table><tr><th>Data</th><th>Użytkownik</th><th>Sprawa</th><th>Operacja</th><th>Szczegóły</th></tr>{''.join(trs) or '<tr><td colspan=5>Brak wpisów.</td></tr>'}</table></div>"""
        self.send_html(layout('Dziennik audytowy',body,'audit'))

    def entities_page(self,qs):
        q=(qs.get('q') or [''])[0].strip(); params=[]; sql="SELECT * FROM entities WHERE 1=1"
        if q:
            like=f"%{q}%"; sql += " AND (display_name LIKE ? OR first_name LIKE ? OR last_name LIKE ? OR company_name LIKE ? OR pesel LIKE ? OR nip LIKE ? OR krs LIKE ? OR email LIKE ? OR phone LIKE ? OR address LIKE ?)"; params += [like]*10
        sql += " ORDER BY display_name COLLATE NOCASE LIMIT 1000"
        with db() as con:
            rows=con.execute(sql,params).fetchall()
            counts={r['entity_id']:r['cnt'] for r in con.execute("SELECT entity_id,COUNT(*) cnt FROM case_entities GROUP BY entity_id").fetchall()}
        cards=[]
        for r in rows:
            ids=[]
            if r['pesel']: ids.append('PESEL '+r['pesel'])
            if r['nip']: ids.append('NIP '+r['nip'])
            if r['krs']: ids.append('KRS '+r['krs'])
            typ='Osoba' if r['entity_type']=='person' else 'Firma / podmiot'
            cards.append(f"<div class='entity-card'><div class='small muted'>{typ} · {counts.get(r['id'],0)} spraw</div><h3 style='margin:5px 0'><a href='/entity/{r['id']}'>{esc(entity_display(r))}</a></h3><div class='small'>{esc(' · '.join(ids))}</div><div class='small muted'>{esc(r['email'])} {esc(r['phone'])}</div></div>")
        body=f"""<div class='topbar'><div><h1>Kartoteka podmiotów</h1><div class='sub'>Osoby i firmy są zapisane raz, a następnie przypinane do dowolnej liczby spraw z różnymi rolami.</div></div><a class='btn primary' href='/entity/new'>+ Nowy podmiot</a></div><div class='card'><form class='searchbar'><input name='q' value='{esc(q)}' placeholder='nazwisko, nazwa, PESEL, NIP, KRS, e-mail…'><button class='btn'>Szukaj</button></form></div><br><div class='entity-grid'>{''.join(cards) or '<div class="empty">Brak podmiotów.</div>'}</div>"""
        self.send_html(layout('Kartoteka podmiotów',body,'entities'))

    def entity_form(self,row=None,error=''):
        r=row or {}; get=lambda k: (r[k] if hasattr(r,'keys') and k in r.keys() else r.get(k,'')) if r else ''
        eid=get('id'); action=f'/entity/{eid}/update' if eid else '/entity/create'; title='Edytuj podmiot' if eid else 'Nowy podmiot'
        typ=get('entity_type') or 'person'; err=f"<div class='error'>{esc(error)}</div>" if error else ''
        body=f"""<div class='topbar'><div><h1>{title}</h1><div class='sub'>Dane identyfikacyjne i kontaktowe wykorzystywane w wielu sprawach.</div></div></div>{err}<div class='card'><form method='post' action='{action}' class='form-grid' {'data-autosave="1"' if eid else ''}><div><label>Typ</label><select name='entity_type'><option value='person' {'selected' if typ=='person' else ''}>Osoba</option><option value='company' {'selected' if typ=='company' else ''}>Firma / podmiot</option></select></div><div><label>Nazwa wyświetlana *</label><input name='display_name' required value='{esc(get('display_name'))}'></div><div><label>Imię</label><input name='first_name' value='{esc(get('first_name'))}'></div><div><label>Nazwisko</label><input name='last_name' value='{esc(get('last_name'))}'></div><div class='full'><label>Nazwa firmy / instytucji</label><input name='company_name' value='{esc(get('company_name'))}'></div><div><label>PESEL</label><input name='pesel' value='{esc(get('pesel'))}'></div><div><label>NIP</label><input name='nip' value='{esc(get('nip'))}'></div><div><label>KRS</label><input name='krs' value='{esc(get('krs'))}'></div><div><label>E-mail</label><input name='email' value='{esc(get('email'))}'></div><div><label>Telefon</label><input name='phone' value='{esc(get('phone'))}'></div><div class='full'><label>Adres</label><input name='address' value='{esc(get('address'))}'></div><div class='full'><label>Notatki</label><textarea name='notes'>{esc(get('notes'))}</textarea></div><div class='full'><button class='btn primary'>{'Zapisz' if eid else 'Utwórz'}</button> <a class='btn' href='/entities'>Wróć</a></div></form></div>"""
        self.send_html(layout(title,body,'entities'))

    def entity_new_page(self): return self.entity_form()

    def entity_create(self,f):
        name=(f.get('display_name','') or '').strip()
        if not name: return self.entity_form(None,'Nazwa wyświetlana jest wymagana.')
        a=self.current_author(f); vals=[(f.get(k,'') or '').strip() for k in ('entity_type','display_name','first_name','last_name','company_name','pesel','nip','krs','email','phone','address','notes')]
        with db() as con:
            # twarde identyfikatory nie powinny występować dwukrotnie
            for col,val in [('pesel',vals[5]),('nip',vals[6]),('krs',vals[7])]:
                if val and con.execute(f"SELECT 1 FROM entities WHERE {col}=?",(val,)).fetchone(): return self.entity_form(None,f'Podmiot z takim {col.upper()} już istnieje.')
            cur=con.execute("INSERT INTO entities(entity_type,display_name,first_name,last_name,company_name,pesel,nip,krs,email,phone,address,notes,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",tuple(vals)+(a,a))
            audit(con,None,'entity',cur.lastrowid,'Utworzono podmiot',name,a)
        self.redirect(f'/entity/{cur.lastrowid}')

    def entity_edit_page(self,eid):
        with db() as con: r=con.execute('SELECT * FROM entities WHERE id=?',(eid,)).fetchone()
        if not r: return self.send_error(404)
        return self.entity_form(r)

    def entity_update(self,eid,f):
        name=(f.get('display_name','') or '').strip(); a=self.current_author(f)
        if not name: return self.entity_edit_page(eid)
        vals=[(f.get(k,'') or '').strip() for k in ('entity_type','display_name','first_name','last_name','company_name','pesel','nip','krs','email','phone','address','notes')]
        with db() as con:
            con.execute("UPDATE entities SET entity_type=?,display_name=?,first_name=?,last_name=?,company_name=?,pesel=?,nip=?,krs=?,email=?,phone=?,address=?,notes=?,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",tuple(vals)+(a,eid))
            audit(con,None,'entity',eid,'Edytowano podmiot',name,a)
        self.redirect(f'/entity/{eid}')

    def entity_view(self,eid):
        with db() as con:
            e=con.execute('SELECT * FROM entities WHERE id=?',(eid,)).fetchone()
            links=con.execute("SELECT ce.*,c.title,c.signature,c.internal_signature,c.status FROM case_entities ce JOIN cases c ON c.id=ce.case_id WHERE ce.entity_id=? ORDER BY c.status='closed',c.id DESC",(eid,)).fetchall()
        if not e: return self.send_error(404)
        rows=''.join(f"<tr><td><a class='case-link' href='/case/{x['case_id']}'>{esc(primary_signature_text(x['case_id'],x['signature'],x['internal_signature']))}</a><div class='small'>{esc(x['title'])}</div></td><td>{esc(x['role'])}</td><td>{badge(x['status'])}</td></tr>" for x in links) or '<tr><td colspan=3>Podmiot nie jest jeszcze przypisany do spraw.</td></tr>'
        body=f"""<div class='topbar'><div><h1>{esc(entity_display(e))}</h1><div class='sub'>{'Osoba' if e['entity_type']=='person' else 'Firma / podmiot'}</div></div><a class='btn primary' href='/entity/{eid}/edit'>Edytuj</a></div><div class='grid'><div class='card span5'><h2>Dane</h2><table><tr><th>PESEL</th><td>{esc(e['pesel']) or '—'}</td></tr><tr><th>NIP</th><td>{esc(e['nip']) or '—'}</td></tr><tr><th>KRS</th><td>{esc(e['krs']) or '—'}</td></tr><tr><th>E-mail</th><td>{esc(e['email']) or '—'}</td></tr><tr><th>Telefon</th><td>{esc(e['phone']) or '—'}</td></tr><tr><th>Adres</th><td>{esc(e['address']) or '—'}</td></tr><tr><th>Notatki</th><td>{esc(e['notes']) or '—'}</td></tr></table></div><div class='card span7'><h2>Występowanie w sprawach</h2><table><tr><th>Sprawa</th><th>Rola</th><th>Status</th></tr>{rows}</table></div></div>"""
        self.send_html(layout(entity_display(e),body,'entities'))

    def case_entity_add(self,cid,f):
        if not self.ensure_case_editable(cid): return
        try: eid=int(f.get('entity_id','') or 0)
        except ValueError: eid=0
        role=(f.get('role','') or 'Uczestnik').strip()[:120]; a=self.current_author(f)
        if not eid: return self.redirect(f'/case/{cid}')
        with db() as con:
            e=con.execute('SELECT * FROM entities WHERE id=?',(eid,)).fetchone()
            if not e: return self.redirect(f'/case/{cid}')
            conflicts=conflict_rows(con,eid,role,cid)
            if conflicts and not f.get('_confirm_conflict'):
                rows=''.join(f"<li><a href='/case/{x['case_id']}'>{esc(primary_signature_text(x['case_id'],x['signature'],x['internal_signature']))}</a> — {esc(x['title'])} · rola: <b>{esc(x['role'])}</b></li>" for x in conflicts)
                hidden=f"<input type='hidden' name='entity_id' value='{eid}'><input type='hidden' name='role' value='{esc(role)}'><input type='hidden' name='_confirm_conflict' value='1'>"
                body=f"<div class='conflict-box'><h1>Możliwy konflikt interesów</h1><p><b>{esc(entity_display(e))}</b> występuje już po przeciwnej stronie w innych sprawach:</p><ul>{rows}</ul><form method='post' action='/case/{cid}/entity'>{hidden}<button class='btn danger'>Mimo to przypisz</button> <a class='btn' href='/case/{cid}'>Anuluj</a></form></div>"
                return self.send_html(layout('Kontrola konfliktu',body,'cases'))
            cur=con.execute("INSERT INTO case_entities(case_id,entity_id,role,notes,created_by,updated_by) VALUES(?,?,?,?,?,?)",(cid,eid,role,(f.get('notes','') or '').strip(),a,a))
            if 'klient' in role.casefold(): con.execute("UPDATE cases SET client=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(entity_display(e),cid))
            audit(con,cid,'case_entity',cur.lastrowid,'Przypisano podmiot',f"{entity_display(e)} — {role}",a)
        self.redirect(f'/case/{cid}')

    def case_entity_delete(self,link_id,f):
        a=self.current_author(f)
        with db() as con:
            r=con.execute("SELECT ce.*,e.display_name FROM case_entities ce JOIN entities e ON e.id=ce.entity_id WHERE ce.id=?",(link_id,)).fetchone()
            if not r: return self.redirect('/cases')
            cid=r['case_id']
            if case_read_only(con,cid): return self.send_html(layout('Tylko do odczytu',f"<div class='card'>Sprawa jest zablokowana. <a href='/case/{cid}'>Wróć</a></div>"),403)
            con.execute('DELETE FROM case_entities WHERE id=?',(link_id,)); audit(con,cid,'case_entity',link_id,'Usunięto przypisanie podmiotu',r['display_name'],a)
        self.redirect(f'/case/{cid}')

    def checklists_page(self):
        with db() as con:
            templates=con.execute('SELECT * FROM checklist_templates ORDER BY category,name').fetchall()
            items={}
            for r in con.execute('SELECT * FROM checklist_template_items ORDER BY template_id,sort_order,id'): items.setdefault(r['template_id'],[]).append(r)
        cards=[]
        for t in templates:
            li=''.join(f"<li>{esc(i['label'])}</li>" for i in items.get(t['id'],[]))
            cards.append(f"<div class='entity-card'><div class='small muted'>Kategoria: {esc(t['category']) or 'dowolna'}</div><h3>{esc(t['name'])}</h3><ol>{li}</ol><form method='post' action='/checklist/template/{t['id']}/delete' onsubmit=\"return confirm('Usunąć szablon? Checklisty już zastosowane w sprawach pozostaną.');\"><button class='btn small danger'>Usuń szablon</button></form></div>")
        body=f"""<div class='topbar'><div><h1>Checklisty kompletności</h1><div class='sub'>Najpierw dostępne checklisty. Nowy szablon dodajesz dopiero po kliknięciu.</div></div><button class='btn primary' type='button' data-open-details='new-checklist-template'>+ Nowy szablon</button></div><div class='card'><div class='section-head'><div><h2>Szablony</h2><div class='small muted'>Gotowe zestawy czynności do zastosowania w sprawie.</div></div></div><div class='entity-grid'>{''.join(cards) or '<div class="empty">Nie ma jeszcze szablonów checklist. <button class="btn small" type="button" data-open-details="new-checklist-template">Dodaj pierwszy</button></div>'}</div></div><div class='module-spacer'></div><details class='card add-panel' id='new-checklist-template'><summary><span class='add-panel-plus'>＋</span><span><b>Dodaj szablon checklisty</b><small>Formularz jest schowany, dopóki go nie potrzebujesz.</small></span></summary><div class='add-panel-body'><form method='post' action='/checklist/template/create'><label>Nazwa</label><input name='name' required placeholder='np. Sprawa cywilna — start'><label>Kategoria sprawy</label><input name='category' placeholder='np. cywilna'><label>Elementy — po jednym w wierszu</label><textarea name='items' rows='10' placeholder='Pełnomocnictwo\nOpłata skarbowa\nUmowa z klientem\nDokumenty źródłowe'></textarea><button class='btn primary'>Utwórz szablon</button></form></div></details>"""
        self.send_html(layout('Checklisty',body,'checklists'))

    def checklist_template_create(self,f):
        name=(f.get('name','') or '').strip(); cat=(f.get('category','') or '').strip(); a=self.current_author(f); lines=[x.strip() for x in (f.get('items','') or '').splitlines() if x.strip()]
        if not name or not lines: return self.redirect('/checklists')
        with db() as con:
            cur=con.execute('INSERT INTO checklist_templates(name,category,created_by) VALUES(?,?,?)',(name,cat,a))
            for i,label in enumerate(lines): con.execute('INSERT INTO checklist_template_items(template_id,label,sort_order) VALUES(?,?,?)',(cur.lastrowid,label[:300],i))
            audit(con,None,'checklist_template',cur.lastrowid,'Utworzono szablon checklisty',name,a)
        self.redirect('/checklists')

    def checklist_template_delete(self,tid,f):
        a=self.current_author(f)
        with db() as con:
            r=con.execute('SELECT name FROM checklist_templates WHERE id=?',(tid,)).fetchone(); con.execute('DELETE FROM checklist_templates WHERE id=?',(tid,))
            if r: audit(con,None,'checklist_template',tid,'Usunięto szablon checklisty',r['name'],a)
        self.redirect('/checklists')

    def case_checklist_apply(self,cid,f):
        if not self.ensure_case_editable(cid): return
        try: tid=int(f.get('template_id','') or 0)
        except ValueError: tid=0
        a=self.current_author(f)
        with db() as con:
            rows=con.execute('SELECT * FROM checklist_template_items WHERE template_id=? ORDER BY sort_order,id',(tid,)).fetchall()
            mx=con.execute('SELECT COALESCE(MAX(sort_order),-1) FROM case_checklist_items WHERE case_id=?',(cid,)).fetchone()[0]
            for j,r in enumerate(rows,1): con.execute('INSERT INTO case_checklist_items(case_id,label,sort_order,template_id,created_by,updated_by) VALUES(?,?,?,?,?,?)',(cid,r['label'],mx+j,tid,a,a))
            if rows: audit(con,cid,'checklist',tid,'Zastosowano szablon checklisty',f'{len(rows)} elementów',a)
        self.redirect(f'/case/{cid}')

    def case_checklist_add(self,cid,f):
        if not self.ensure_case_editable(cid): return
        label=(f.get('label','') or '').strip(); a=self.current_author(f)
        if label:
            with db() as con:
                n=con.execute('SELECT COALESCE(MAX(sort_order),-1)+1 FROM case_checklist_items WHERE case_id=?',(cid,)).fetchone()[0]
                cur=con.execute('INSERT INTO case_checklist_items(case_id,label,sort_order,created_by,updated_by) VALUES(?,?,?,?,?)',(cid,label,n,a,a)); audit(con,cid,'checklist_item',cur.lastrowid,'Dodano element checklisty',label,a)
        self.redirect(f'/case/{cid}')

    def checklist_item_toggle(self,iid,f):
        a=self.current_author(f)
        with db() as con:
            r=con.execute('SELECT * FROM case_checklist_items WHERE id=?',(iid,)).fetchone()
            if not r: return self.redirect('/cases')
            cid=r['case_id']
            if case_read_only(con,cid): return self.redirect(f'/case/{cid}')
            new=0 if r['is_done'] else 1; completed_at='' if not new else datetime.now().strftime('%Y-%m-%d %H:%M:%S'); completed_by='' if not new else a; con.execute('UPDATE case_checklist_items SET is_done=?,updated_by=?,updated_at=CURRENT_TIMESTAMP,completed_at=?,completed_by=? WHERE id=?',(new,a,completed_at,completed_by,iid)); audit(con,cid,'checklist_item',iid,'Element checklisty wykonany' if new else 'Cofnięto wykonanie elementu checklisty',r['label'],a)
        self.redirect(f'/case/{cid}')

    def checklist_item_delete(self,iid,f):
        a=self.current_author(f)
        with db() as con:
            r=con.execute('SELECT * FROM case_checklist_items WHERE id=?',(iid,)).fetchone()
            if not r: return self.redirect('/cases')
            cid=r['case_id']
            if case_read_only(con,cid): return self.redirect(f'/case/{cid}')
            con.execute('DELETE FROM case_checklist_items WHERE id=?',(iid,)); audit(con,cid,'checklist_item',iid,'Usunięto element checklisty',r['label'],a)
        self.redirect(f'/case/{cid}')

    def case_unlock(self,cid,f):
        if not self.require_admin(): return
        a=self.current_author(f)
        with db() as con: con.execute('UPDATE cases SET closed_edit_unlocked=1 WHERE id=?',(cid,)); audit(con,cid,'case',cid,'Odblokowano zakończoną sprawę do edycji','Tryb tylko do odczytu wyłączony przez administratora',a)
        self.redirect(f'/case/{cid}')

    def case_lock(self,cid,f):
        if not self.require_admin(): return
        a=self.current_author(f)
        with db() as con: con.execute('UPDATE cases SET closed_edit_unlocked=0 WHERE id=?',(cid,)); audit(con,cid,'case',cid,'Zablokowano zakończoną sprawę','Tryb tylko do odczytu włączony',a)
        self.redirect(f'/case/{cid}')

    def ocr_install_start(self,f):
        if not self.require_admin(): return
        if os.name!='nt': return self.security_page('Automatyczna instalacja OCR jest przygotowana dla Windows. Na serwerze Linux zainstaluj tesseract-ocr + język polski z repozytorium systemu.')
        if not OCR_SETUP_SCRIPT.exists(): return self.security_page('Brakuje pliku ocr_setup.py w katalogu programu.')
        try:
            flags=getattr(subprocess,'CREATE_NEW_CONSOLE',0)
            subprocess.Popen([sys.executable,str(OCR_SETUP_SCRIPT),'--interactive'],cwd=str(BASE_DIR),creationflags=flags)
            with db() as con:
                immutable_audit(con,None,'ocr',None,'Uruchomiono instalator OCR','Tesseract + modele pol/eng',self.current_author(f))
        except Exception as exc:
            return self.security_page(f'Nie udało się uruchomić instalatora OCR: {exc}')
        return self.security_page('Instalator OCR został uruchomiony w osobnym oknie. Po jego zakończeniu wróć tutaj i użyj „Przebuduj indeks + OCR”.')

    def document_pdf_page(self,did,page_no):
        """Render jednej strony PDF do PNG z limitem pamięci i skalą."""
        with db() as con: d=con.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone()
        if not d: return self.send_error(404)
        state,p,why=document_state(d)
        if state!='ok' or not p or Path(d['original_name'] or p.name).suffix.lower()!='.pdf': return self.send_error(404)
        try:
            q=parse_qs(urlparse(self.path).query); zoom=float((q.get('zoom') or ['1'])[0]); zoom=max(.6,min(2.4,zoom))
        except Exception: zoom=1.0
        try:
            import fitz
            doc=fitz.open(str(p))
            if len(doc)<1: raise ValueError('PDF nie zawiera stron')
            idx=max(0,min(int(page_no)-1,len(doc)-1)); page=doc.load_page(idx); scale=(130/72)*zoom
            est=(page.rect.width*scale)*(page.rect.height*scale)
            if est>12_000_000: scale*=(12_000_000/est)**0.5
            pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False); data=pix.tobytes('png'); doc.close()
        except Exception as exc:
            log_app_exception(f'/document/{did}/page/{page_no}',exc); return self.send_error(422,'Nie udało się wyrenderować strony PDF.')
        self.send_response(200); self.send_header('Content-Type','image/png'); self.send_header('Cache-Control','private, max-age=120'); self.send_header('Content-Length',str(len(data))); self.end_headers()
        try: self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError,OSError): pass

    def draft_case_options(self, selected=None):
        with db() as con:
            rows=con.execute("SELECT id,signature,internal_signature,title FROM cases ORDER BY status='closed', title COLLATE NOCASE").fetchall()
        opts=["<option value=''>— bez przypisanej sprawy —</option>"]
        for c in rows:
            label=(c['signature'] or c['internal_signature'] or c['title'])+' — '+c['title']
            opts.append(f"<option value='{c['id']}' {'selected' if selected==c['id'] else ''}>{esc(label)}</option>")
        return ''.join(opts)

    def drafts_page(self,qs):
        q=(qs.get('q') or [''])[0].strip(); status=(qs.get('status') or [''])[0].strip(); mine=(qs.get('mine') or [''])[0]=='1'; u=current_request_user()
        sql="""SELECT w.*,c.title case_title,c.signature,c.internal_signature FROM writing_projects w LEFT JOIN cases c ON c.id=w.case_id WHERE 1=1"""; params=[]
        if q:
            like=f'%{q}%'; sql+=' AND (w.title LIKE ? OR w.content LIKE ? OR w.notes LIKE ? OR w.original_name LIKE ? OR c.title LIKE ? OR c.signature LIKE ? OR c.internal_signature LIKE ?)'; params += [like]*7
        if status: sql+=' AND w.status=?'; params.append(status)
        if mine and u: sql+=' AND (w.created_by=? OR w.updated_by=?)'; params += [u['author_name'],u['author_name']]
        sql+=' ORDER BY CASE w.status WHEN \'Do podpisu\' THEN 0 WHEN \'Do weryfikacji\' THEN 1 WHEN \'Roboczy\' THEN 2 WHEN \'Gotowy\' THEN 3 ELSE 4 END, COALESCE(NULLIF(w.due_date,\'\'),\'9999-12-31\'), w.updated_at DESC'
        with db() as con: rows=con.execute(sql,params).fetchall()
        cards=[]
        for r in rows:
            case_label=(r['signature'] or r['internal_signature'] or r['case_title'] or 'Bez sprawy')
            file_info=f"<div class='small muted'>Plik: {esc(r['original_name'])}</div>" if r['original_name'] else ''
            due=f"<span class='pill'>Termin: {fmt_date(r['due_date'])}</span>" if r['due_date'] else ''
            cards.append(f"<div class='entity-card'><div class='case-control-bar'><span class='pill'>{esc(r['status'])}</span>{due}</div><h3 style='margin:8px 0 4px'><a class='case-link' href='/draft/{r['id']}'>{esc(r['title'])}</a></h3><div class='small muted'>{esc(case_label)} · {esc(r['doc_type'])}</div>{file_info}<div class='small muted' style='margin-top:7px'>Autor: {esc(r['created_by'])} · zmiana: {esc(str(r['updated_at'])[:16])}</div></div>")
        status_opts="<option value=''>Wszystkie statusy</option>"+''.join(f"<option {'selected' if status==x else ''}>{x}</option>" for x in ['Roboczy','Do weryfikacji','Do podpisu','Gotowy','Złożony','Archiwalny'])
        body=f"""<div class='topbar'><div><h1>Pisma</h1><div class='sub'>Projekty, ich wersje i szablony w jednym module.</div></div><a class='btn primary' href='/draft/new'>+ Nowy projekt</a></div>{writing_tabs('projects')}<div class='card'><form method='get' class='searchbar'><input name='q' value='{esc(q)}' placeholder='Szukaj projektu, treści lub sprawy…'><select name='status'>{status_opts}</select><label style='white-space:nowrap'><input type='checkbox' style='width:auto' name='mine' value='1' {'checked' if mine else ''}> Moje</label><button class='btn'>Filtruj</button></form></div><br><div class='entity-grid'>{''.join(cards) if cards else '<div class="card empty">Brak projektów pism.</div>'}</div>"""
        self.send_html(layout('Pisma',body,'drafts'))

    def draft_new_page(self,qs=None,message=''):
        case_id=int(((qs or {}).get('case_id') or ['0'])[0] or 0) or None
        msg=f"<div class='notice'>{esc(message)}</div>" if message else ''
        body=f"""<div class='topbar'><div><h1>Nowy projekt pisma</h1><div class='sub'>Projekt może być przypisany do sprawy albo istnieć niezależnie.</div></div><div><a class='btn' href='/drafts?view=templates'>Użyj szablonu</a> <a class='btn' href='/drafts'>Wróć</a></div></div>{msg}<div class='card'><form method='post' enctype='multipart/form-data' action='/draft/create' class='form-grid'><div class='full'><label>Tytuł *</label><input name='title' required></div><div><label>Sprawa</label><select name='case_id'>{self.draft_case_options(case_id)}</select></div><div><label>Rodzaj pisma</label><input name='doc_type' value='Pismo procesowe'></div><div><label>Status</label><select name='status'>{''.join(f'<option>{x}</option>' for x in ['Roboczy','Do weryfikacji','Do podpisu','Gotowy','Złożony','Archiwalny'])}</select></div><div><label>Termin</label><input type='date' name='due_date'></div><div class='full'><label>Treść / roboczy tekst</label><textarea name='content' style='min-height:260px'></textarea></div><div class='full'><label>Notatki</label><textarea name='notes'></textarea></div><div class='full'><label>Plik roboczy (opcjonalnie)</label><input type='file' name='file'></div><div class='full'><button class='btn primary'>Utwórz projekt</button></div></form></div>"""
        self.send_html(layout('Nowy projekt pisma',body,'drafts'))

    def draft_create(self,f,files):
        title=(f.get('title') or '').strip(); a=self.current_author(f)
        if not title: return self.draft_new_page({},'Podaj tytuł projektu.')
        cid=int(f.get('case_id') or 0) or None; stored=original=''
        if files.get('file') and files['file'][1]:
            original=safe_filename(files['file'][0]); data=files['file'][1]; DRAFTS_DIR.mkdir(parents=True,exist_ok=True); stored=f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{original}"; atomic_write_bytes(DRAFTS_DIR/stored,data)
        status=f.get('status','Roboczy') if f.get('status','Roboczy') in {'Roboczy','Do weryfikacji','Do podpisu','Gotowy','Złożony','Archiwalny'} else 'Roboczy'
        with db() as con:
            cur=con.execute("INSERT INTO writing_projects(case_id,title,doc_type,status,due_date,content,notes,stored_name,original_name,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(cid,title,(f.get('doc_type') or 'Pismo procesowe').strip(),status,f.get('due_date',''),f.get('content',''),f.get('notes',''),stored,original,a,a))
            audit(con,cid,'writing_project',cur.lastrowid,'Utworzono projekt pisma',f"Tytuł: {_change_value(title)}\nRodzaj: {_change_value((f.get('doc_type') or 'Pismo procesowe').strip())}\nStatus: {_change_value(status)}\nTermin: {_change_value(f.get('due_date',''))}",a)
            save_draft_version(con,cur.lastrowid,a,'Utworzenie projektu')
        self.redirect(f'/draft/{cur.lastrowid}')

    def draft_view(self,did,message=''):
        with db() as con:
            d=con.execute("SELECT w.*,c.title case_title,c.signature,c.internal_signature FROM writing_projects w LEFT JOIN cases c ON c.id=w.case_id WHERE w.id=?",(did,)).fetchone()
            versions=con.execute("SELECT * FROM draft_versions WHERE project_id=? ORDER BY version_no DESC LIMIT 50",(did,)).fetchall() if d else []
        if not d: return self.send_error(404)
        msg=f"<div class='notice'>{esc(message)}</div>" if message else ''
        case_html=f"<a href='/case/{d['case_id']}'>{esc(d['signature'] or d['internal_signature'] or d['case_title'])}</a>" if d['case_id'] else '—'
        file_buttons=f"<a class='btn' href='/draft/{did}/download'>Pobierz plik</a>" if d['stored_name'] else ''
        to_doc=f"<form method='post' action='/draft/{did}/to-document' style='display:inline'><button class='btn primary'>Dodaj do dokumentów sprawy</button></form>" if d['case_id'] else ''
        content=f"<pre class='doc-text-preview' style='white-space:pre-wrap'>{esc(d['content'])}</pre>" if d['content'] else "<div class='empty'>Brak treści roboczej w programie.</div>"
        version_rows=[]
        for v in versions:
            file_label=f" · plik: {esc(v['original_name'])}" if v['original_name'] else ''
            restore=f"<form method='post' action='/draft/{did}/version/{v['id']}/restore' style='display:inline' onsubmit=\"return confirm('Przywrócić tę wersję jako bieżącą? Bieżący stan zostanie zachowany w historii.');\"><button class='btn small'>Przywróć</button></form>"
            version_rows.append(f"<tr><td>v{v['version_no']}</td><td>{esc(str(v['created_at'])[:16])}</td><td>{esc(v['created_by'])}</td><td>{esc(v['change_note'])}{file_label}</td><td>{restore}</td></tr>")
        versions_html=''.join(version_rows) or '<tr><td colspan=5>Brak zapisanych wersji.</td></tr>'
        body=f"""<div class='topbar'><div><h1>{esc(d['title'])}</h1><div class='sub'>{case_html} · {esc(d['doc_type'])} · {esc(d['status'])}</div></div><div><a class='btn' href='/draft/{did}/edit'>Edytuj</a> {file_buttons} {to_doc}</div></div>{msg}<div class='grid'><div class='card span8'><h2>Treść projektu</h2>{content}</div><div class='card span4'><h2>Informacje</h2><p><b>Status:</b> {esc(d['status'])}<br><b>Termin:</b> {fmt_date(d['due_date']) if d['due_date'] else '—'}<br><b>Plik:</b> {esc(d['original_name']) or '—'}<br><b>Autor:</b> {esc(d['created_by'])}<br><b>Ostatnia zmiana:</b> {esc(str(d['updated_at'])[:16])}</p><h3>Notatki</h3><div style='white-space:pre-wrap'>{esc(d['notes']) or '—'}</div><hr><form method='post' action='/draft/{did}/archive'><button class='btn'>Archiwizuj projekt</button></form></div><div class='card span12'><div class='section-head'><div><h2>Historia wersji</h2><div class='small muted'>Każdy zapis tworzy wersję tekstu i kopię pliku roboczego, jeśli plik istnieje.</div></div></div><table><tr><th>Wersja</th><th>Data</th><th>Autor</th><th>Opis</th><th></th></tr>{versions_html}</table></div></div>"""
        self.send_html(layout('Projekt pisma',body,'drafts'))

    def draft_edit_page(self,did,message=''):
        with db() as con: d=con.execute('SELECT * FROM writing_projects WHERE id=?',(did,)).fetchone()
        if not d: return self.send_error(404)
        status_opts=''.join(f"<option {'selected' if d['status']==x else ''}>{x}</option>" for x in ['Roboczy','Do weryfikacji','Do podpisu','Gotowy','Złożony','Archiwalny'])
        msg=f"<div class='notice'>{esc(message)}</div>" if message else ''
        body=f"""<div class='topbar'><div><h1>Edytuj projekt pisma</h1></div><a class='btn' href='/draft/{did}'>Wróć</a></div>{msg}<div class='card'><form method='post' enctype='multipart/form-data' action='/draft/{did}/update' class='form-grid'><div class='full'><label>Tytuł *</label><input name='title' value='{esc(d['title'])}' required></div><div><label>Sprawa</label><select name='case_id'>{self.draft_case_options(d['case_id'])}</select></div><div><label>Rodzaj</label><input name='doc_type' value='{esc(d['doc_type'])}'></div><div><label>Status</label><select name='status'>{status_opts}</select></div><div><label>Termin</label><input type='date' name='due_date' value='{esc(d['due_date'])}'></div><div class='full'><label>Treść / roboczy tekst</label><textarea name='content' style='min-height:300px'>{esc(d['content'])}</textarea></div><div class='full'><label>Notatki</label><textarea name='notes'>{esc(d['notes'])}</textarea></div><div class='full'><label>Podmień / dodaj plik</label><input type='file' name='file'><div class='small muted'>Aktualny: {esc(d['original_name']) or 'brak'}. Poprzedni plik pozostanie w historii wersji.</div></div><div class='full'><button class='btn primary'>Zapisz projekt i utwórz wersję</button></div></form></div>"""
        self.send_html(layout('Edytuj projekt',body,'drafts'))

    def draft_update(self,did,f,files):
        a=self.current_author(f); title=(f.get('title') or '').strip()
        if not title: return self.draft_edit_page(did,'Podaj tytuł projektu.')
        with db() as con:
            old=con.execute('SELECT * FROM writing_projects WHERE id=?',(did,)).fetchone()
            if old and not con.execute('SELECT 1 FROM draft_versions WHERE project_id=? LIMIT 1',(did,)).fetchone():
                save_draft_version(con,did,a,'Stan początkowy przed pierwszą zmianą w DEV8')
        if not old: return self.send_error(404)
        stored,original=old['stored_name'],old['original_name']; replaced_file=False
        if files.get('file') and files['file'][1]:
            original=safe_filename(files['file'][0]); data=files['file'][1]; DRAFTS_DIR.mkdir(parents=True,exist_ok=True); newstored=f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{original}"; atomic_write_bytes(DRAFTS_DIR/newstored,data)
            stored=newstored; replaced_file=True
        cid=int(f.get('case_id') or 0) or None; status=f.get('status','Roboczy')
        if status not in {'Roboczy','Do weryfikacji','Do podpisu','Gotowy','Złożony','Archiwalny'}: status='Roboczy'
        newvals={'title':title,'doc_type':(f.get('doc_type') or 'Pismo procesowe').strip(),'status':status,'due_date':f.get('due_date',''),'content':f.get('content',''),'notes':f.get('notes','')}
        details=describe_changes(old,newvals,{'title':'Tytuł','doc_type':'Rodzaj','status':'Status','due_date':'Termin','content':'Treść projektu','notes':'Notatki'},compact_fields={'content','notes'})
        if old['case_id'] != cid:
            details=(details+'\n'+f"• Przypisana sprawa: {_change_value(old['case_id'] or '—')} → {_change_value(cid or '—')}").strip()
        if replaced_file:
            details=(details+'\n'+f"• Plik: {_change_value(old['original_name'])} → {_change_value(original)}").strip()
        with db() as con:
            con.execute("UPDATE writing_projects SET case_id=?,title=?,doc_type=?,status=?,due_date=?,content=?,notes=?,stored_name=?,original_name=?,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(cid,title,newvals['doc_type'],status,newvals['due_date'],newvals['content'],newvals['notes'],stored,original,a,did))
            if details: audit(con,cid,'writing_project',did,'Edytowano projekt pisma',details,a)
            save_draft_version(con,did,a,'Zapis projektu')
        self.redirect(f'/draft/{did}')

    def draft_templates_page(self,message=''):
        with db() as con:
            rows=con.execute("SELECT * FROM draft_templates ORDER BY name COLLATE NOCASE").fetchall()
            cases=con.execute("SELECT id,signature,internal_signature,title FROM cases WHERE status<>'closed' ORDER BY title COLLATE NOCASE").fetchall()
        msg=f"<div class='notice'>{esc(message)}</div>" if message else ''
        case_opts='<option value="">— wybierz sprawę —</option>'+''.join(f"<option value='{c['id']}'>{esc((c['signature'] or c['internal_signature'] or c['title'])+' — '+c['title'])}</option>" for c in cases)
        cards=[]
        for t in rows:
            create=f"<form method='post' action='/draft/from-template' class='form-grid'><input type='hidden' name='template_id' value='{t['id']}'><div class='full'><label>Sprawa</label><select name='case_id' required>{case_opts}</select></div><div class='full'><button class='btn primary'>Utwórz projekt z szablonu</button></div></form>"
            delete=f"<form method='post' action='/draft/template/{t['id']}/delete' onsubmit=\"return confirm('Usunąć szablon? Istniejące projekty pozostaną.');\"><button class='btn small danger'>Usuń</button></form>"
            preview=esc((t['content'] or '')[:500])
            cards.append(f"<div class='entity-card'><div class='case-control-bar'><span class='pill'>{esc(t['doc_type'])}</span>{delete}</div><h3>{esc(t['name'])}</h3><pre class='template-preview'>{preview}</pre>{create}</div>")
        placeholders='{{SĄD}}, {{SYGNATURA}}, {{SYGNATURA_WEWNĘTRZNA}}, {{KLIENT}}, {{TYTUŁ_SPRAWY}}, {{PRZEDMIOT}}, {{STRONY}}, {{DATA}}, {{PEŁNOMOCNIK}}'
        cards_html=''.join(cards) or '<div class="empty">Brak szablonów.</div>'
        body=f"""<div class='topbar'><div><h1>Pisma</h1><div class='sub'>Projekty, ich wersje i szablony w jednym module.</div></div><button class='btn primary' type='button' data-open-details='new-draft-template'>+ Nowy szablon</button></div>{writing_tabs('templates')}{msg}<div class='card'><h2>Szablony</h2><div class='small muted' style='margin-bottom:12px'>Wybierz szablon, aby od razu utworzyć z niego projekt przypisany do sprawy.</div><div class='entity-grid'>{cards_html}</div></div><div class='module-spacer'></div><details class='card add-panel' id='new-draft-template'><summary><span class='add-panel-plus'>＋</span><span><b>Dodaj szablon pisma</b><small>Zaawansowane pola są widoczne dopiero po otwarciu.</small></span></summary><div class='add-panel-body'><form method='post' action='/draft/template/create'><label>Nazwa *</label><input name='name' required><label>Rodzaj pisma</label><input name='doc_type' value='Pismo procesowe'><label>Treść szablonu</label><textarea name='content' rows='18' placeholder='np. {{SĄD}}&#10;Sygn. {{SYGNATURA}}&#10;&#10;...'></textarea><div class='small muted'>Dostępne pola: {esc(placeholders)}</div><details class='advanced-fields'><summary>Więcej opcji</summary><label>Notatki</label><textarea name='notes'></textarea></details><button class='btn primary'>Zapisz szablon</button></form></div></details>"""
        self.send_html(layout('Pisma · Szablony',body,'drafts'))

    def draft_template_create(self,f):
        name=(f.get('name') or '').strip(); a=self.current_author(f)
        if not name: return self.draft_templates_page('Podaj nazwę szablonu.')
        try:
            with db() as con:
                cur=con.execute("INSERT INTO draft_templates(name,doc_type,content,notes,created_by,updated_by) VALUES(?,?,?,?,?,?)",(name,(f.get('doc_type') or 'Pismo procesowe').strip(),f.get('content',''),f.get('notes',''),a,a))
                immutable_audit(con,None,'draft_template',cur.lastrowid,'Dodano szablon pisma',name,a)
        except sqlite3.IntegrityError:
            return self.draft_templates_page('Szablon o tej nazwie już istnieje.')
        self.redirect('/drafts?view=templates')

    def draft_template_delete(self,tid,f):
        a=self.current_author(f)
        with db() as con:
            t=con.execute('SELECT * FROM draft_templates WHERE id=?',(tid,)).fetchone()
            if t:
                con.execute('DELETE FROM draft_templates WHERE id=?',(tid,)); immutable_audit(con,None,'draft_template',tid,'Usunięto szablon pisma',t['name'],a)
        self.redirect('/drafts?view=templates')

    def draft_from_template(self,f):
        a=self.current_author(f)
        try: tid=int(f.get('template_id') or 0); cid=int(f.get('case_id') or 0)
        except Exception: return self.draft_templates_page('Nieprawidłowy wybór szablonu lub sprawy.')
        with db() as con:
            t=con.execute('SELECT * FROM draft_templates WHERE id=?',(tid,)).fetchone(); c=con.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone()
            if not t or not c: return self.draft_templates_page('Nie znaleziono szablonu lub sprawy.')
            content=fill_draft_template(t['content'],draft_template_context(con,cid,a))
            title=f"{t['name']} — {c['title']}"
            cur=con.execute("INSERT INTO writing_projects(case_id,title,doc_type,status,due_date,content,notes,stored_name,original_name,created_by,updated_by) VALUES(?,?,?,'Roboczy','',?,?, '', '', ?,?)",(cid,title,t['doc_type'],content,t['notes'],a,a))
            save_draft_version(con,cur.lastrowid,a,f"Utworzono z szablonu: {t['name']}")
            audit(con,cid,'writing_project',cur.lastrowid,'Utworzono projekt z szablonu',f"Szablon: {_change_value(t['name'])}\nTytuł: {_change_value(title)}",a)
        self.redirect(f'/draft/{cur.lastrowid}')

    def draft_version_restore(self,did,vid,f):
        a=self.current_author(f)
        with db() as con:
            d=con.execute('SELECT * FROM writing_projects WHERE id=?',(did,)).fetchone(); v=con.execute('SELECT * FROM draft_versions WHERE id=? AND project_id=?',(vid,did)).fetchone()
            if not d or not v: return self.send_error(404)
            save_draft_version(con,did,a,'Stan przed przywróceniem starszej wersji')
            stored=d['stored_name']; original=d['original_name']
            if v['stored_name']:
                src=DRAFTS_DIR/v['stored_name']
                if src.is_file():
                    newname=f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{safe_filename(v['original_name'] or src.name)}"; shutil.copy2(src,DRAFTS_DIR/newname); stored=newname; original=v['original_name']
            con.execute("UPDATE writing_projects SET title=?,doc_type=?,status=?,due_date=?,content=?,notes=?,stored_name=?,original_name=?,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(v['title'],v['doc_type'],v['status'],v['due_date'],v['content'],v['notes'],stored,original,a,did))
            save_draft_version(con,did,a,f"Przywrócono wersję v{v['version_no']}")
            audit(con,d['case_id'],'writing_project',did,'Przywrócono wersję projektu',f"Wersja: v{v['version_no']}",a)
        self.redirect(f'/draft/{did}')

    def draft_download(self,did):
        with db() as con: d=con.execute('SELECT * FROM writing_projects WHERE id=?',(did,)).fetchone()
        if not d or not d['stored_name']: return self.send_error(404)
        p=DRAFTS_DIR/d['stored_name']
        if not p.exists(): return self.send_error(404)
        ctype=mimetypes.guess_type(d['original_name'])[0] or 'application/octet-stream'; size=p.stat().st_size
        self.send_response(200); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(size)); self.send_header('Content-Disposition',f"attachment; filename*=UTF-8''{quote(d['original_name'] or p.name)}"); self.end_headers()
        with p.open('rb') as fh:
            while True:
                chunk=fh.read(1024*1024)
                if not chunk: break
                self.wfile.write(chunk)

    def draft_archive(self,did,f):
        a=self.current_author(f)
        with db() as con:
            d=con.execute('SELECT * FROM writing_projects WHERE id=?',(did,)).fetchone()
            if not d: return self.send_error(404)
            con.execute("UPDATE writing_projects SET status='Archiwalny',updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(a,did)); audit(con,d['case_id'],'writing_project',did,'Zarchiwizowano projekt pisma',d['title'],a)
        self.redirect(f'/draft/{did}')

    def draft_to_document(self,did,f):
        a=self.current_author(f)
        with db() as con: d=con.execute('SELECT * FROM writing_projects WHERE id=?',(did,)).fetchone()
        if not d or not d['case_id']: return self.send_error(400)
        cid=d['case_id']
        with db() as con:
            if case_read_only(con,cid):
                return self.send_html(layout('Sprawa tylko do odczytu',f"<div class='readonly-banner'>Nie można dodać projektu jako dokumentu do zablokowanej sprawy zakończonej. <a class='btn' href='/draft/{did}'>Wróć</a></div>",'drafts'),403)
        folder=FILES_DIR/f'sprawa_{cid}'; folder.mkdir(parents=True,exist_ok=True)
        if d['stored_name'] and (DRAFTS_DIR/d['stored_name']).exists():
            original=d['original_name']; data=(DRAFTS_DIR/d['stored_name']).read_bytes()
        else:
            original=safe_filename((d['title'] or 'projekt')+'.txt'); data=(d['content'] or '').encode('utf-8')
        stored=f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{original}"; atomic_write_bytes(folder/stored,data)
        with db() as con:
            cur=con.execute("INSERT INTO documents(case_id,doc_date,received_date,doc_type,doc_status,title,description,stored_name,original_name,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(cid,date.today().isoformat(),'',d['doc_type'] or 'Pismo procesowe','Do podpisu',d['title'],d['notes'] or '',stored,original,a,a)); doc_id=cur.lastrowid; con.execute("UPDATE documents SET file_hash=?,ocr_status='kolejka' WHERE id=?",(sha256_bytes(data),doc_id)); audit(con,cid,'document',doc_id,'Dodano pismo z projektu',f"Tytuł: {_change_value(d['title'])}\nProjekt źródłowy: #{did}\nPlik: {_change_value(original)}\nStatus: {_change_value('Do podpisu')}",a)
            con.execute("UPDATE writing_projects SET status='Do podpisu',updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(a,did))
        enqueue_document_index(doc_id)
        self.redirect(f'/document/{doc_id}/open')

    def reindex_documents(self,f):
        if not self.require_admin(): return
        with db() as con:
            rows=con.execute("SELECT id FROM documents WHERE stored_name<>'' ORDER BY id").fetchall()
            immutable_audit(con,None,'document_index',None,'Dodano dokumenty do kolejki indeksowania + OCR',f'Elementów: {len(rows)}',self.current_author(f))
        for r in rows: enqueue_document_index(r['id'],force_ocr=True)
        self.redirect('/search?reindexed=1')

    def security_page(self,message=''):
        if not self.require_admin(): return
        with db() as con:
            configured=bool(backup_secret(con)); dpapi=bool(settings_get(con,'backup_key_dpapi','')); verifier=bool(settings_get(con,'backup_key_verifier',''))
        try: import cryptography; crypto='Dostępna'
        except Exception: crypto='BRAK — zainstaluj: pip install cryptography'
        tcmd=find_tesseract(); ocr_lang=ocr_language_for(tcmd) if tcmd else '';
        try:
            import fitz; pymu='Dostępny'
        except Exception:
            pymu='BRAK — pip install pymupdf'
        ocr_state=(f'Dostępny · {tcmd} · język {ocr_lang}' if tcmd else 'BRAK Tesseract — uruchom instalator OCR'); ocr_queue=_INDEX_QUEUE.qsize()
        msg=f"<div class='notice'>{esc(message)}</div>" if message else ''
        status='Skonfigurowany' if configured else 'Nie skonfigurowany'
        body=f"""<div class='topbar'><div><h1>Bezpieczeństwo</h1><div class='sub'>Klucz szyfrowania backupów i stan ochrony danych.</div></div></div>{msg}<div class='grid'><div class='card span6 security-card'><h2>Szyfrowanie backupów</h2><p><b>Status klucza:</b> {status}<br><b>Biblioteka cryptography:</b> {esc(crypto)}</p><p class='small muted'>Windows: klucz jest chroniony przez DPAPI bieżącego konta Windows. Serwer Linux/macOS: ustaw zmienną środowiskową RK_BACKUP_KEY. Klucz nie jest zapisywany jawnym tekstem w bazie.</p><form method='post' action='/security/key'><label>Nowy klucz administracyjny / hasło</label><input type='password' name='secret' minlength='12' required autocomplete='new-password'><label>Powtórz</label><input type='password' name='secret2' minlength='12' required><button class='btn primary'>Ustaw klucz</button></form></div><div class='card span6'><h2>Zaszyfrowany backup teraz</h2><p>Tworzy zaszyfrowaną kopię bazy SQLite do pobrania. Odszyfrowanie wymaga klucza.</p><form method='post' action='/backup/encrypted'><button class='btn primary'>Pobierz zaszyfrowany backup</button></form><hr><h2>OCR i indeks dokumentów</h2><p><b>Tesseract:</b> {esc(ocr_state)}<br><b>Renderowanie PDF (PyMuPDF):</b> {esc(pymu)}<br><b>Kolejka OCR:</b> {ocr_queue}</p><p class='small muted'>RK KANCELARIA może zainstalować silnik Tesseract oraz modele polski + angielski. Instalator korzysta z Windows Package Manager i zapisuje modele językowe w katalogu danych programu.</p><form method='post' action='/security/ocr/install' style='margin-bottom:8px'><button class='btn primary'>Zainstaluj / napraw silnik OCR</button></form><form method='post' action='/admin/reindex-documents'><input type='hidden' name='force_all' value='1'><button class='btn'>Przebuduj indeks + OCR</button></form></div></div>"""
        self.send_html(layout('Bezpieczeństwo',body,'security'))

    def security_key_update(self,f):
        if not self.require_admin(): return
        s1=f.get('secret','') or ''; s2=f.get('secret2','') or ''
        if len(s1)<12 or s1!=s2: return self.security_page('Klucz musi mieć co najmniej 12 znaków, a oba pola muszą być identyczne.')
        with db() as con:
            ok=save_backup_secret(con,s1); immutable_audit(con,None,'security',None,'Zmieniono klucz szyfrowania backupów','DPAPI/zmienna środowiskowa',self.current_author(f))
        return self.security_page('Klucz zapisano bezpiecznie.' if ok else 'Nie udało się zapisać klucza automatycznie. Na Linux/macOS ustaw RK_BACKUP_KEY w środowisku serwera.')

    def encrypted_backup(self,f):
        if not self.require_admin(): return
        with db() as con: secret=backup_secret(con)
        if not secret: return self.security_page('Najpierw ustaw klucz szyfrowania backupów.')
        tmp=DATA_DIR/f'.backup_{uuid.uuid4().hex}.sqlite3'
        try:
            _sqlite_backup(DB_PATH,tmp); raw=tmp.read_bytes(); data=encrypted_blob(raw,secret); name=f"rk_kancelaria_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sqlite3.rkenc"
            with db() as con: immutable_audit(con,None,'backup',None,'Pobrano zaszyfrowany backup',name,self.current_author(f))
            self.send_response(200); self.send_header('Content-Type','application/octet-stream'); self.send_header('Content-Disposition',f'attachment; filename="{name}"'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
        finally:
            try: tmp.unlink(missing_ok=True)
            except Exception: pass

    def case_export_package(self,cid):
        data,name=export_case_package(cid)
        with db() as con: immutable_audit(con,cid,'case_package',cid,'Wyeksportowano pakiet sprawy',name,self.current_author())
        self.send_response(200); self.send_header('Content-Type','application/zip'); self.send_header('Content-Disposition',f"attachment; filename*=UTF-8''{quote(name)}"); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)

    def case_import_page(self,message=''):
        msg=f"<div class='notice'>{esc(message)}</div>" if message else ''
        body=f"""<div class='topbar'><div><h1>Import sprawy</h1><div class='sub'>Import pełnego pakietu .rkcase.zip wyeksportowanego z RK KANCELARIA. Import tworzy nową sprawę i nie nadpisuje istniejącej.</div></div></div>{msg}<div class='card'><form method='post' enctype='multipart/form-data' action='/case/import'><label>Pakiet sprawy</label><input type='file' name='package' accept='.zip,.rkcase.zip' required><button class='btn primary'>Importuj</button></form></div>"""
        self.send_html(layout('Import sprawy',body,'cases'))

    def case_import(self,f,files):
        if 'package' not in files or not files['package'][1]: return self.case_import_page('Wybierz plik pakietu.')
        raw=files['package'][1]; a=self.current_author(f)
        try:
            z=zipfile.ZipFile(io.BytesIO(raw),'r'); manifest=json.loads(z.read('case.json').decode('utf-8'))
            if manifest.get('format')!='RK-KANCELARIA-CASE': raise ValueError('To nie jest pakiet RK KANCELARIA')
            src=manifest['case']; tables=manifest.get('tables',{})
        except Exception as e: return self.case_import_page(f'Błędny pakiet: {e}')
        imported_index_ids=[]
        with db() as con:
            cols={r['name'] for r in con.execute('PRAGMA table_info(cases)')}; skip={'id','created_at','updated_at'}; data={k:v for k,v in src.items() if k in cols and k not in skip}
            data['title']=(data.get('title') or 'Zaimportowana sprawa')+' — import'; data['created_by']=a; data['updated_by']=a; data['closed_edit_unlocked']=0
            # Id użytkownika prowadzącego jest lokalny dla danej instalacji — nie przenosimy go między komputerami.
            if 'lead_user_id' in data: data['lead_user_id']=None
            names=list(data); cur=con.execute(f"INSERT INTO cases({','.join(names)}) VALUES({','.join('?' for _ in names)})",[data[x] for x in names]); cid=cur.lastrowid
            if tables.get('tags'): set_case_tags(con,cid,','.join(tables['tags']))
            def ins_rows(table,rows,excluded=()):
                actual={x['name'] for x in con.execute(f'PRAGMA table_info({table})')}
                for rr in rows or []:
                    d={k:v for k,v in rr.items() if k in actual and k not in {'id','case_id','created_at'}|set(excluded)}; d['case_id']=cid
                    if 'created_by' in actual: d['created_by']=a
                    if 'updated_by' in actual: d['updated_by']=a
                    ns=list(d); con.execute(f"INSERT INTO {table}({','.join(ns)}) VALUES({','.join('?' for _ in ns)})",[d[x] for x in ns])
            ins_rows('parties',tables.get('parties',[]),('entity_id',)); ins_rows('events',tables.get('events',[])); ins_rows('process_events',tables.get('process_events',[]),('document_id',)); ins_rows('tasks',tables.get('tasks',[]),('assigned_user_id',)); ins_rows('case_notes',tables.get('notes',[]),('author',)); ins_rows('case_external_signatures',tables.get('external_signatures',[])); ins_rows('case_checklist_items',tables.get('checklist',[]),('template_id',))
            # structured entities: reuse by PESEL/NIP/KRS, otherwise display name
            for ce in tables.get('case_entities',[]):
                ent=None
                for col in ('pesel','nip','krs'):
                    if ce.get(col): ent=con.execute(f'SELECT * FROM entities WHERE {col}=?',(ce[col],)).fetchone();
                    if ent: break
                if not ent and ce.get('display_name'): ent=con.execute('SELECT * FROM entities WHERE display_name=? COLLATE NOCASE',(ce['display_name'],)).fetchone()
                if ent: eid=ent['id']
                else:
                    cur2=con.execute("INSERT INTO entities(entity_type,display_name,first_name,last_name,company_name,pesel,nip,krs,email,phone,address,notes,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(ce.get('entity_type','person'),ce.get('display_name',''),ce.get('first_name',''),ce.get('last_name',''),ce.get('company_name',''),ce.get('pesel',''),ce.get('nip',''),ce.get('krs',''),ce.get('email',''),ce.get('phone',''),ce.get('address',''),ce.get('entity_notes',''),a,a)); eid=cur2.lastrowid
                con.execute('INSERT INTO case_entities(case_id,entity_id,role,notes,created_by,updated_by) VALUES(?,?,?,?,?,?)',(cid,eid,ce.get('role','Uczestnik'),ce.get('notes',''),a,a))
            # Powiązania z innymi sprawami — odtwórz tylko, gdy druga sprawa jest już w tej bazie.
            for rel in tables.get('relations',[]):
                other=None
                other_internal=(rel.get('other_internal_signature') or '').strip()
                other_signature=(rel.get('other_signature') or '').strip()
                if other_internal:
                    other=con.execute('SELECT id FROM cases WHERE internal_signature=? ORDER BY id LIMIT 1',(other_internal,)).fetchone()
                if not other and other_signature:
                    other=con.execute('SELECT id FROM cases WHERE signature=? ORDER BY id LIMIT 1',(other_signature,)).fetchone()
                if not other: continue
                oid=other['id']
                source,target=(cid,oid) if rel.get('direction')!='in' else (oid,cid)
                exists=con.execute('SELECT 1 FROM case_relations WHERE source_case_id=? AND target_case_id=? AND relation_type=?',(source,target,rel.get('relation_type','powiązana'))).fetchone()
                if not exists:
                    con.execute('INSERT INTO case_relations(source_case_id,target_case_id,relation_type,note,created_by,updated_by) VALUES(?,?,?,?,?,?)',
                                (source,target,rel.get('relation_type','powiązana'),rel.get('note',''),a,a))
            # documents and physical files
            doc_id_map={}
            for d in tables.get('documents',[]):
                oldid=d.get('id'); original=safe_filename(d.get('original_name') or d.get('stored_name') or 'dokument'); filedata=b''
                prefix=f'files/{oldid}/'
                matches=[n for n in z.namelist() if n.startswith(prefix) and not n.endswith('/')]
                if matches: filedata=z.read(matches[0])
                stored=''
                if filedata:
                    folder=FILES_DIR/f'sprawa_{cid}'; folder.mkdir(parents=True,exist_ok=True); stored=f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{original}"; atomic_write_bytes(folder/stored,filedata)
                parent_old=int(d.get('parent_document_id') or 0)
                curd=con.execute("""INSERT INTO documents(case_id,doc_date,received_date,delivered_date,doc_type,doc_status,title,description,
                                  sender,document_author,tags,linked_task_id,stored_name,original_name,parent_document_id,attachment_order,
                                  created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                 (cid,d.get('doc_date',''),d.get('received_date',''),d.get('delivered_date',''),d.get('doc_type','Inne'),
                                  d.get('doc_status','Aktywny'),d.get('title','Dokument'),d.get('description',''),d.get('sender',''),
                                  d.get('document_author',''),d.get('tags',''),None,stored,original if filedata else '',
                                  doc_id_map.get(parent_old),int(d.get('attachment_order') or 0),a,a))
                if oldid is not None: doc_id_map[int(oldid)]=curd.lastrowid
                if filedata:
                    con.execute("UPDATE documents SET file_hash=?,ocr_status='kolejka' WHERE id=?",(sha256_bytes(filedata),curd.lastrowid)); imported_index_ids.append(curd.lastrowid)
            # Warsztat sprawy 0.3.0-dev3. Wszystkie odwołania do lokalnych ID są mapowane.
            if tables.get('strategy'):
                s=tables['strategy'][0]; fields=('main_goal','minimum_variant','opponent_position','our_arguments','opponent_arguments','response_arguments','risks','hearing_plan','motions_to_make','witness_questions','settlement_position','watchouts')
                con.execute(f"INSERT INTO case_strategy(case_id,{','.join(fields)},updated_by) VALUES(?,{','.join('?' for _ in fields)},?)",(cid,*[s.get(x,'') for x in fields],a))
            assertion_id_map={}
            for ar in tables.get('assertions',[]):
                curar=con.execute("""INSERT INTO case_assertions(case_id,statement,side,status,legal_significance,notes,sort_order,is_archived,created_by,updated_by)
                                    VALUES(?,?,?,?,?,?,?,?,?,?)""",(cid,ar.get('statement',''),ar.get('side','nasze'),ar.get('status','do udowodnienia'),ar.get('legal_significance',''),ar.get('notes',''),int(ar.get('sort_order') or 0),int(ar.get('is_archived') or 0),a,a))
                if ar.get('id') is not None: assertion_id_map[int(ar['id'])]=curar.lastrowid
            for ev in tables.get('evidence',[]):
                aid=assertion_id_map.get(int(ev.get('assertion_id') or 0));
                if not aid: continue
                did=doc_id_map.get(int(ev.get('document_id') or 0))
                con.execute("""INSERT INTO case_evidence(assertion_id,evidence_type,title,status,document_id,source_reference,notes,is_archived,created_by)
                               VALUES(?,?,?,?,?,?,?,?,?)""",(aid,ev.get('evidence_type','Dokument'),ev.get('title','Dowód'),ev.get('status','do przeprowadzenia'),did,ev.get('source_reference',''),ev.get('notes',''),int(ev.get('is_archived') or 0),a))
            ins_rows('case_claims',tables.get('claims',[]))
            for de in tables.get('document_events',[]):
                did=doc_id_map.get(int(de.get('document_id') or 0))
                if not did: continue
                con.execute("""INSERT INTO document_events(document_id,case_id,event_date,event_type,title,description,is_archived,created_by)
                               VALUES(?,?,?,?,?,?,?,?)""",(did,cid,de.get('event_date',''),de.get('event_type','Dotyczy'),de.get('title','Zdarzenie'),de.get('description',''),int(de.get('is_archived') or 0),a))
            for dv in tables.get('document_versions',[]):
                olddid=int(dv.get('document_id') or 0); newdid=doc_id_map.get(olddid)
                if not newdid: continue
                oldvid=int(dv.get('id') or 0); original=safe_filename(dv.get('original_name') or 'wersja'); vstored=''
                prefix=f'document_versions/{olddid}/{oldvid}/'; matches=[n for n in z.namelist() if n.startswith(prefix) and not n.endswith('/')]
                if matches:
                    filedata=z.read(matches[0]); vdir=FILES_DIR/f'sprawa_{cid}'/f'wersje_dokumentu_{newdid}'; vdir.mkdir(parents=True,exist_ok=True)
                    vname=f"v{int(dv.get('version_no') or 1):03d}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{original}"; atomic_write_bytes(vdir/vname,filedata); vstored=f'wersje_dokumentu_{newdid}/{vname}'
                con.execute("""INSERT OR IGNORE INTO document_versions(document_id,version_no,stored_name,original_name,file_hash,title,description,created_by,created_at)
                               VALUES(?,?,?,?,?,?,?,?,COALESCE(?,CURRENT_TIMESTAMP))""",(newdid,int(dv.get('version_no') or 1),vstored,original if vstored else '',dv.get('file_hash',''),dv.get('title',''),dv.get('description',''),a,dv.get('created_at')))
            # Projekty pism + historia ich wersji. Stare ID są mapowane na nowe ID w docelowej bazie.
            draft_id_map={}
            for w in tables.get('writing_projects',[]):
                oldid=w.get('id'); original=safe_filename(w.get('original_name') or w.get('stored_name') or 'projekt'); stored=''
                prefix=f'drafts/{oldid}/'; matches=[n for n in z.namelist() if n.startswith(prefix) and not n.endswith('/')]
                if matches:
                    filedata=z.read(matches[0]); DRAFTS_DIR.mkdir(parents=True,exist_ok=True); stored=f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{original}"; atomic_write_bytes(DRAFTS_DIR/stored,filedata)
                curw=con.execute("INSERT INTO writing_projects(case_id,title,doc_type,status,due_date,content,notes,stored_name,original_name,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(cid,w.get('title','Projekt pisma'),w.get('doc_type','Pismo procesowe'),w.get('status','Roboczy'),w.get('due_date',''),w.get('content',''),w.get('notes',''),stored,original if stored else '',a,a))
                if oldid is not None: draft_id_map[int(oldid)]=curw.lastrowid
            for v in tables.get('draft_versions',[]):
                try: oldpid=int(v.get('project_id') or 0); oldvid=int(v.get('id') or 0)
                except Exception: continue
                newpid=draft_id_map.get(oldpid)
                if not newpid: continue
                original=safe_filename(v.get('original_name') or 'wersja'); vstored=''
                prefix=f'draft_versions/{oldpid}/{oldvid}/'; matches=[n for n in z.namelist() if n.startswith(prefix) and not n.endswith('/')]
                if matches:
                    filedata=z.read(matches[0]); vdir=DRAFTS_DIR/f'wersje_{newpid}'; vdir.mkdir(parents=True,exist_ok=True); vname=f"v{int(v.get('version_no') or 0):03d}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{original}"; atomic_write_bytes(vdir/vname,filedata); vstored=f'wersje_{newpid}/{vname}'
                con.execute("INSERT OR IGNORE INTO draft_versions(project_id,version_no,title,doc_type,status,due_date,content,notes,stored_name,original_name,change_note,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,COALESCE(?,CURRENT_TIMESTAMP))",(newpid,int(v.get('version_no') or 1),v.get('title',''),v.get('doc_type',''),v.get('status','Roboczy'),v.get('due_date',''),v.get('content',''),v.get('notes',''),vstored,original if vstored else '',v.get('change_note',''),a,v.get('created_at')))
            audit(con,cid,'case',cid,'Zaimportowano sprawę',files['package'][0],a)
        for doc_id in imported_index_ids:
            enqueue_document_index(doc_id)
        self.redirect(f'/case/{cid}')

    def dashboard_notifications(self):
        today=date.today(); soon=(today.fromordinal(today.toordinal()+3)).isoformat(); today_s=today.isoformat()
        notices=[]
        with db() as con:
            overdue=con.execute("SELECT t.*,c.title,c.signature,c.internal_signature FROM tasks t JOIN cases c ON c.id=t.case_id WHERE t.status='open' AND c.status<>'closed' AND t.due_date<>'' AND t.due_date<? ORDER BY t.due_date LIMIT 15",(today_s,)).fetchall()
            due=con.execute("SELECT t.*,c.title,c.signature,c.internal_signature FROM tasks t JOIN cases c ON c.id=t.case_id WHERE t.status='open' AND c.status<>'closed' AND t.due_date BETWEEN ? AND ? ORDER BY t.due_date LIMIT 15",(today_s,soon)).fetchall()
            sign=con.execute("SELECT d.*,c.title,c.signature,c.internal_signature FROM documents d JOIN cases c ON c.id=d.case_id WHERE d.doc_status='Do podpisu' AND c.status<>'closed' ORDER BY d.id DESC LIMIT 15").fetchall()
            draft_sign=con.execute("SELECT w.*,c.title case_title,c.signature,c.internal_signature FROM writing_projects w JOIN cases c ON c.id=w.case_id WHERE w.status='Do podpisu' AND c.status<>'closed' ORDER BY w.updated_at DESC LIMIT 15").fetchall()
            draft_due=con.execute("SELECT w.*,c.title case_title,c.signature,c.internal_signature FROM writing_projects w JOIN cases c ON c.id=w.case_id WHERE w.status NOT IN ('Archiwalny','Złożony') AND c.status<>'closed' AND w.due_date<>'' AND w.due_date BETWEEN ? AND ? ORDER BY w.due_date LIMIT 15",(today_s,soon)).fetchall()
            stale=con.execute("""SELECT c.*,COALESCE(MAX(a.created_at),c.updated_at,c.created_at) last_activity
                FROM cases c LEFT JOIN immutable_audit a ON a.case_id=c.id
                WHERE c.status<>'closed'
                GROUP BY c.id
                HAVING datetime(COALESCE(MAX(a.created_at),c.updated_at,c.created_at)) < datetime('now','-30 days')
                ORDER BY last_activity LIMIT 15""").fetchall()
            smart_alerts=con.execute("SELECT a.*,c.title case_title FROM alerts a LEFT JOIN cases c ON c.id=a.case_id WHERE a.status='open' AND a.alert_date<=? AND NOT (a.source_type='task' AND a.source_id IS NOT NULL) ORDER BY a.alert_date,CASE a.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2 END LIMIT 20",(soon,)).fetchall()
        for r in overdue: notices.append(('danger',f"Zadanie po terminie: {r['title']}",r['case_id'],f"termin {fmt_date(r['due_date'])}"))
        for r in due: notices.append(('',f"Termin w ciągu 3 dni: {r['title']}",r['case_id'],fmt_date(r['due_date'])))
        for r in sign: notices.append(('',f"Dokument do podpisu: {r['title']}",r['case_id'],r['original_name'] or r['doc_type']))
        for r in draft_sign: notices.append(('',f"Projekt pisma do podpisu: {r['title']}",r['case_id'],r['doc_type'] or 'Projekt pisma'))
        for r in draft_due: notices.append(('',f"Termin projektu pisma: {r['title']}",r['case_id'],fmt_date(r['due_date'])))
        for r in stale: notices.append(('',f"Brak aktywności od ponad 30 dni: {r['title']}",r['id'],str(r['last_activity'])[:10]))
        for r in smart_alerts:
            if r['case_id']:
                cls='danger' if r['priority']=='critical' or r['alert_date']<today_s else ''
                notices.append((cls,f"{r['alert_type']}: {r['title']}",r['case_id'],fmt_date(r['alert_date'])))
        if not notices: return "<div class='notification ok'><b>Brak pilnych powiadomień.</b></div>"
        return ''.join(f"<div class='notification {cls}'><a class='case-link' href='/case/{cid}'><b>{esc(title)}</b></a><div class='small muted'>{esc(desc)}</div></div>" for cls,title,cid,desc in notices[:30])


    def backup(self):
        if not DB_PATH.exists(): init_db()
        # Nie czytamy samego pliku .sqlite3, bo aktywne dane mogą być jeszcze w WAL.
        # SQLite backup API tworzy spójną migawkę.
        with tempfile.TemporaryDirectory(prefix='rk_backup_') as td:
            tmp=Path(td)/'backup.sqlite3'; _sqlite_backup(DB_PATH,tmp); data=tmp.read_bytes()
        name=f"rk_kancelaria_backup_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.sqlite3"
        self.send_response(200); self.send_header('Content-Type','application/octet-stream'); self.send_header('Content-Disposition',f'attachment; filename="{name}"'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)


def main():
    apply_pending_restore_if_any()
    recover_database_if_needed()
    init_db()
    purge_old_trash()
    ensure_daily_backup()
    # STABLE: ciężkie indeksowanie/OCR nie uruchamia się automatycznie przy starcie.
    # Nowe dokumenty nadal są indeksowane podczas dodawania, a administrator może
    # ręcznie przebudować indeks z poziomu Bezpieczeństwo / Wyszukiwarka.
    try:
        VERSION_MARKER.write_text(VERSION, encoding="utf-8")
    except OSError:
        pass
    port=PORT
    while True:
        try:
            server=AppServer((HOST,port),Handler); break
        except OSError:
            if os.getenv("SPRAWNIK_PORT"):
                raise
            port += 1
    browser_host = "127.0.0.1" if HOST in {"0.0.0.0", "::", ""} else HOST
    url=f"http://{browser_host}:{port}/"
    mode = "serwer/LAN" if not LOCAL_MODE else "lokalnie"
    print(f"\n{APP_NAME} {VERSION} działa ({mode}) pod adresem: {url}")
    if HOST in {"0.0.0.0", "::"}:
        print(f"Nasłuch: {HOST}:{port} — inni użytkownicy w LAN łączą się przez adres IP tego komputera/serwera.")
    print(f"Baza: {DB_PATH}")
    print(f"Dokumenty: {FILES_DIR}")
    if MIGRATION_MESSAGE:
        print(MIGRATION_MESSAGE)
    if PRE_UPGRADE_BACKUP_MESSAGE:
        print(PRE_UPGRADE_BACKUP_MESSAGE)
    print("Logowanie: konta użytkowników w bazie RK KANCELARIA")
    print("Przy pierwszym uruchomieniu aplikacja poprosi o utworzenie konta administratora.")
    print("Auto-zamykanie po zamknięciu kart: " + (f"włączone (WebSocket karty + ~{AUTO_SHUTDOWN_GRACE:g}s bufora; autosave zachowany)" if AUTO_SHUTDOWN else "wyłączone"))
    print("Aby zakończyć ręcznie: Ctrl+C\n")
    if OPEN_BROWSER:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    if AUTO_SHUTDOWN:
        threading.Thread(target=auto_shutdown_monitor, args=(server,), daemon=True).start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        try: create_shutdown_backup()
        except Exception as exc: log_event(f'Backup przy zamykaniu main: {exc}','ERROR')
        server.server_close(); print("\nZamknięto RK KANCELARIA.")

if __name__ == '__main__': main()
