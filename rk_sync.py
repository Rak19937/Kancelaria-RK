# -*- coding: utf-8 -*-
"""Bezpieczna synchronizacja RK KANCELARIA Installed <-> Portable.

Model synchronizacji 0.2.0-dev3:
- jedna wspólna historia danych,
- automatyczny kierunek, gdy od ostatniej synchronizacji zmieniła się tylko jedna strona,
- konflikt, gdy obie strony zmieniły się niezależnie,
- pełny backup strony nadpisywanej przed każdą synchronizacją,
- SQLite kopiowany przez API backup (WAL-safe),
- dokumenty i projekty pism synchronizowane razem z bazą,
- lokalne sekrety DPAPI nie są przenoszone między komputerami.

To NIE jest jeszcze scalanie rekord-po-rekordzie. Przy równoległych zmianach użytkownik
musi wybrać, która kompletna wersja ma zwyciężyć. Dzięki temu 0.2 nie może cicho
zgubić części danych.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from rk_paths import installed_data_dir, resolve_runtime_paths

SCHEMA_VERSION = 210
SYNC_FORMAT = 2
MANAGED_DIRS = ("dokumenty", "projekty_pism")
LOCAL_SETTING_KEYS = {"backup_key_dpapi", "backup_key_verifier"}
IGNORE_TABLES = {"user_sessions", "user_case_recent"}
IGNORE_TABLE_PREFIXES = ("document_fts",)
STATE_NAME = ".rk_sync_state.json"
LOCK_NAME = ".rk_app_running.json"
BACKUP_DIR_NAME = "backup_synchronizacji"
SYNC_BACKUP_RETENTION = 10


class SyncError(RuntimeError):
    pass


class SyncConflict(SyncError):
    pass


@dataclass
class Snapshot:
    data_dir: Path
    fingerprint: str
    db_fingerprint: str
    files_fingerprint: str
    meaningful: bool
    db_exists: bool
    user_version: int


@dataclass
class SyncResult:
    status: str
    message: str
    direction: str = ""
    backup_path: str = ""
    fingerprint: str = ""


def _norm_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def portable_data_dir(base_dir: str | Path | None = None) -> Path:
    base = _norm_path(base_dir or Path(__file__).resolve().parent)
    return base / "Data"


def state_path(data_dir: Path) -> Path:
    return data_dir / STATE_NAME


def lock_path(data_dir: Path) -> Path:
    return data_dir / LOCK_NAME


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        if os.name == "nt":
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def active_lock(data_dir: Path) -> dict | None:
    p = lock_path(data_dir)
    if not p.is_file():
        return None
    try:
        info = json.loads(p.read_text(encoding="utf-8"))
        pid = int(info.get("pid") or 0)
        if _pid_alive(pid):
            return info
    except Exception:
        pass
    # Stary/uszkodzony lock nie może blokować programu na zawsze.
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass
    return None


def acquire_app_lock(data_dir: str | Path, mode: str) -> Path:
    data = _norm_path(data_dir)
    data.mkdir(parents=True, exist_ok=True)
    existing = active_lock(data)
    if existing:
        raise SyncError(f"RK KANCELARIA jest już uruchomiona dla danych: {data} (PID {existing.get('pid')}).")
    p = lock_path(data)
    payload = {
        "pid": os.getpid(),
        "mode": mode,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "host": os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "",
    }
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    return p


def release_app_lock(data_dir: str | Path) -> None:
    try:
        p = lock_path(_norm_path(data_dir))
        if p.is_file():
            try:
                info = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                info = {}
            if not info or int(info.get("pid") or 0) == os.getpid():
                p.unlink(missing_ok=True)
    except Exception:
        pass


def _sqlite_integrity(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return True, "brak bazy"
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10)
        try:
            row = con.execute("PRAGMA quick_check").fetchone()
            ok = bool(row and str(row[0]).lower() == "ok")
            return ok, str(row[0] if row else "brak wyniku")
        finally:
            con.close()
    except Exception as exc:
        return False, str(exc)


def _sqlite_backup(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp_" + uuid.uuid4().hex)
    try:
        src_con = sqlite3.connect(src, timeout=30)
        dst_con = sqlite3.connect(tmp, timeout=30)
        try:
            src_con.backup(dst_con)
            dst_con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            dst_con.close()
            src_con.close()
        ok, why = _sqlite_integrity(tmp)
        if not ok:
            raise SyncError(f"Kopia SQLite nie przeszła kontroli integralności: {why}")
        os.replace(tmp, dst)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _canonical_value(value):
    if value is None or isinstance(value, (int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"__blob__": base64.b64encode(value).decode("ascii")}
    return str(value)


def _db_fingerprint(db_path: Path) -> tuple[str, int, bool]:
    if not db_path.is_file():
        return hashlib.sha256(b"NO_DB").hexdigest(), 0, False
    ok, why = _sqlite_integrity(db_path)
    if not ok:
        raise SyncError(f"Baza {db_path} jest uszkodzona: {why}")
    h = hashlib.sha256()
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=20)
    con.row_factory = sqlite3.Row
    try:
        user_version = int(con.execute("PRAGMA user_version").fetchone()[0])
        if user_version > SCHEMA_VERSION:
            raise SyncError(
                f"Baza ma nowszy schemat ({user_version}) niż synchronizator ({SCHEMA_VERSION}). "
                "Najpierw zaktualizuj program."
            )
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        # sqlite_sequence ma znaczenie dla przyszłych AUTOINCREMENT, więc dodajemy je osobno.
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'").fetchone():
            tables.append("sqlite_sequence")
        meaningful = False
        for table in sorted(set(tables)):
            if table in IGNORE_TABLES or any(table.startswith(p) for p in IGNORE_TABLE_PREFIXES):
                continue
            qtable = '"' + table.replace('"', '""') + '"'
            cols = [r[1] for r in con.execute(f"PRAGMA table_info({qtable})")]
            if not cols:
                continue
            h.update(("TABLE:" + table + "\n").encode("utf-8"))
            select_cols = ",".join('"' + c.replace('"', '""') + '"' for c in cols)
            try:
                rows = con.execute(f"SELECT {select_cols} FROM {qtable} ORDER BY rowid")
            except sqlite3.DatabaseError:
                order = ",".join('"' + c.replace('"', '""') + '"' for c in cols)
                rows = con.execute(f"SELECT {select_cols} FROM {qtable} ORDER BY {order}")
            count = 0
            for row in rows:
                obj = {c: _canonical_value(row[c]) for c in cols}
                if table == "app_settings" and obj.get("key") in LOCAL_SETTING_KEYS:
                    continue
                h.update(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
                h.update(b"\n")
                count += 1
            if table in {"cases", "documents", "tasks", "events", "entities", "users", "writing_projects"} and count:
                meaningful = True
        return h.hexdigest(), user_version, meaningful
    finally:
        con.close()


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _files_fingerprint(data_dir: Path) -> tuple[str, bool]:
    h = hashlib.sha256()
    meaningful = False
    for dirname in MANAGED_DIRS:
        root = data_dir / dirname
        h.update(("DIR:" + dirname + "\n").encode("utf-8"))
        if not root.is_dir():
            continue
        for p in sorted((x for x in root.rglob("*") if x.is_file()), key=lambda x: x.relative_to(root).as_posix().lower()):
            rel = p.relative_to(root).as_posix()
            h.update(rel.encode("utf-8", errors="surrogatepass"))
            h.update(b"\0")
            h.update(str(p.stat().st_size).encode("ascii"))
            h.update(b"\0")
            h.update(_file_sha256(p).encode("ascii"))
            h.update(b"\n")
            meaningful = True
    return h.hexdigest(), meaningful


def snapshot(data_dir: str | Path) -> Snapshot:
    data = _norm_path(data_dir)
    db_hash, user_version, db_meaningful = _db_fingerprint(data / "sprawnik.sqlite3")
    files_hash, files_meaningful = _files_fingerprint(data)
    total = hashlib.sha256((db_hash + ":" + files_hash).encode("ascii")).hexdigest()
    return Snapshot(data, total, db_hash, files_hash, db_meaningful or files_meaningful,
                    (data / "sprawnik.sqlite3").is_file(), user_version)


def read_state(data_dir: str | Path) -> dict:
    p = state_path(_norm_path(data_dir))
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def write_state(data_dir: str | Path, pair_id: str, fingerprint: str, peer: str | Path) -> None:
    data = _norm_path(data_dir)
    data.mkdir(parents=True, exist_ok=True)
    p = state_path(data)
    payload = {
        "format": SYNC_FORMAT,
        "pair_id": pair_id,
        "last_common_fingerprint": fingerprint,
        "peer_hint": str(_norm_path(peer)),
        "synced_at": datetime.now().isoformat(timespec="seconds"),
    }
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _common_baseline(a: dict, b: dict) -> tuple[str | None, str]:
    aid, bid = str(a.get("pair_id") or ""), str(b.get("pair_id") or "")
    afp, bfp = str(a.get("last_common_fingerprint") or ""), str(b.get("last_common_fingerprint") or "")
    if aid and aid == bid and afp and afp == bfp:
        return afp, aid
    # Stan tylko po jednej stronie jest przydatny po np. ręcznym skopiowaniu katalogu.
    if aid and afp and not bid:
        return afp, aid
    if bid and bfp and not aid:
        return bfp, bid
    return None, aid or bid or uuid.uuid4().hex


def _local_settings(db_path: Path) -> dict[str, str]:
    if not db_path.is_file():
        return {}
    try:
        con = sqlite3.connect(db_path, timeout=10)
        try:
            if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_settings'").fetchone():
                return {}
            q = "SELECT key,value FROM app_settings WHERE key IN (%s)" % ",".join("?" * len(LOCAL_SETTING_KEYS))
            return {str(k): str(v) for k, v in con.execute(q, tuple(sorted(LOCAL_SETTING_KEYS)))}
        finally:
            con.close()
    except Exception:
        return {}


def _apply_local_settings(db_path: Path, values: dict[str, str]) -> None:
    if not db_path.is_file():
        return
    con = sqlite3.connect(db_path, timeout=10)
    try:
        # Klucz DPAPI jest lokalny dla konta Windows. Najpierw usuń wartość
        # pochodzącą ze źródła, a dopiero potem przywróć lokalną wartość celu.
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_settings'").fetchone():
            for key in LOCAL_SETTING_KEYS:
                con.execute("DELETE FROM app_settings WHERE key=?", (key,))
            for key, value in values.items():
                con.execute(
                    "INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP",
                    (key, value),
                )
        # Sesje są lokalne i nie powinny być przenoszone między komputerami.
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_sessions'").fetchone():
            con.execute("DELETE FROM user_sessions")
        con.commit()
    finally:
        con.close()


def _copytree(src: Path, dst: Path) -> None:
    if not src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        return
    shutil.copytree(src, dst, copy_function=shutil.copy2, dirs_exist_ok=False)


def backup_destination(data_dir: Path, label: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = data_dir / BACKUP_DIR_NAME / f"{stamp}_{label}_{uuid.uuid4().hex[:6]}"
    root.mkdir(parents=True, exist_ok=False)
    dbp = data_dir / "sprawnik.sqlite3"
    if dbp.is_file():
        _sqlite_backup(dbp, root / "sprawnik.sqlite3")
    for dirname in MANAGED_DIRS:
        src = data_dir / dirname
        if src.is_dir():
            _copytree(src, root / dirname)
    meta = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_data_dir": str(data_dir),
        "label": label,
    }
    (root / "backup_info.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    # Pełne backupy zawierają także dokumenty, więc ograniczamy ich liczbę.
    try:
        parent = data_dir / BACKUP_DIR_NAME
        old = sorted((x for x in parent.iterdir() if x.is_dir()), key=lambda x: x.stat().st_mtime, reverse=True)
        for stale in old[SYNC_BACKUP_RETENTION:]:
            shutil.rmtree(stale, ignore_errors=True)
    except Exception:
        pass
    return root


def _replace_dir(staged: Path, destination: Path) -> None:
    old = destination.with_name(destination.name + ".old_sync_" + uuid.uuid4().hex[:8])
    if destination.exists():
        os.replace(destination, old)
    try:
        os.replace(staged, destination)
        if old.exists():
            shutil.rmtree(old, ignore_errors=True)
    except Exception:
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        if old.exists():
            os.replace(old, destination)
        raise


def copy_full_state(source: Path, destination: Path, label: str) -> Path:
    source = _norm_path(source)
    destination = _norm_path(destination)
    if source == destination:
        raise SyncError("Źródło i cel synchronizacji są tym samym katalogiem.")
    if active_lock(source):
        raise SyncError(f"Źródłowa RK KANCELARIA jest uruchomiona: {source}")
    if active_lock(destination):
        raise SyncError(f"Docelowa RK KANCELARIA jest uruchomiona: {destination}")

    src_db = source / "sprawnik.sqlite3"
    if not src_db.is_file():
        raise SyncError(f"Brak źródłowej bazy: {src_db}")
    ok, why = _sqlite_integrity(src_db)
    if not ok:
        raise SyncError(f"Źródłowa baza jest uszkodzona: {why}")
    src_ver = sqlite3.connect(src_db).execute("PRAGMA user_version").fetchone()[0]
    if int(src_ver) > SCHEMA_VERSION:
        raise SyncError(f"Źródłowa baza ma nieobsługiwany nowszy schemat {src_ver}.")

    destination.mkdir(parents=True, exist_ok=True)
    backup = backup_destination(destination, label)
    local_settings = _local_settings(destination / "sprawnik.sqlite3")
    stage_root = destination / (".sync_stage_" + uuid.uuid4().hex)
    stage_root.mkdir(parents=True, exist_ok=False)
    try:
        stage_db = stage_root / "sprawnik.sqlite3"
        _sqlite_backup(src_db, stage_db)
        _apply_local_settings(stage_db, local_settings)
        for dirname in MANAGED_DIRS:
            _copytree(source / dirname, stage_root / dirname)

        # DB najpierw zapisujemy jako plik tymczasowy w tym samym katalogu docelowym.
        dest_db = destination / "sprawnik.sqlite3"
        db_tmp = destination / (".sprawnik_sync_" + uuid.uuid4().hex + ".sqlite3")
        shutil.copy2(stage_db, db_tmp)
        os.replace(db_tmp, dest_db)

        # Katalogi zarządzane zastępujemy w całości, aby propagować także usunięcia.
        for dirname in MANAGED_DIRS:
            staged_dir = stage_root / dirname
            dest_dir = destination / dirname
            _replace_dir(staged_dir, dest_dir)
        ok2, why2 = _sqlite_integrity(dest_db)
        if not ok2:
            raise SyncError(f"Baza po synchronizacji nie przeszła kontroli: {why2}")
        return backup
    except Exception:
        # Backup pozostaje nienaruszony. Nie próbujemy automatycznie przywracać częściowo
        # skopiowanego zestawu, bo backup jest czytelnym punktem odzyskiwania.
        raise
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def _check_pair_paths(installed: Path, portable: Path) -> None:
    if installed == portable:
        raise SyncError("Installed i Portable wskazują ten sam katalog danych.")
    for label, path in (("Installed", installed), ("Portable", portable)):
        lock = active_lock(path)
        if lock:
            raise SyncError(
                f"{label} jest teraz uruchomiona (PID {lock.get('pid')}). Zamknij ją przed synchronizacją."
            )


def sync(installed: str | Path, portable: str | Path, prefer: str = "auto") -> SyncResult:
    inst = _norm_path(installed)
    port = _norm_path(portable)
    _check_pair_paths(inst, port)
    si, sp = snapshot(inst), snapshot(port)
    sti, stp = read_state(inst), read_state(port)
    baseline, pair_id = _common_baseline(sti, stp)

    if si.fingerprint == sp.fingerprint:
        write_state(inst, pair_id, si.fingerprint, port)
        write_state(port, pair_id, si.fingerprint, inst)
        return SyncResult("ok", "Installed i Portable są już zgodne.", fingerprint=si.fingerprint)

    direction = ""
    if prefer in {"installed", "portable"}:
        direction = prefer
    elif baseline:
        i_changed = si.fingerprint != baseline
        p_changed = sp.fingerprint != baseline
        if i_changed and not p_changed:
            direction = "installed"
        elif p_changed and not i_changed:
            direction = "portable"
        elif not i_changed and not p_changed:
            # Różnica może pochodzić wyłącznie z lokalnych danych ignorowanych przez fingerprint.
            write_state(inst, pair_id, si.fingerprint, port)
            write_state(port, pair_id, si.fingerprint, inst)
            return SyncResult("ok", "Brak zmian kancelaryjnych wymagających synchronizacji.", fingerprint=si.fingerprint)
        else:
            raise SyncConflict("Zmiany istnieją jednocześnie w Installed i Portable.")
    else:
        if si.meaningful and not sp.meaningful:
            direction = "installed"
        elif sp.meaningful and not si.meaningful:
            direction = "portable"
        else:
            raise SyncConflict(
                "To pierwsza synchronizacja, a obie strony zawierają różne dane. Wybierz źródło ręcznie."
            )

    if direction == "installed":
        backup = copy_full_state(inst, port, "przed_nadpisaniem_portable")
        after_i, after_p = snapshot(inst), snapshot(port)
    else:
        backup = copy_full_state(port, inst, "przed_nadpisaniem_installed")
        after_i, after_p = snapshot(inst), snapshot(port)
    if after_i.fingerprint != after_p.fingerprint:
        raise SyncError("Kontrola po synchronizacji wykazała różnicę danych. Backup został zachowany.")
    write_state(inst, pair_id, after_i.fingerprint, port)
    write_state(port, pair_id, after_i.fingerprint, inst)
    arrow = "Installed → Portable" if direction == "installed" else "Portable → Installed"
    return SyncResult("synced", f"Synchronizacja zakończona: {arrow}.", arrow, str(backup), after_i.fingerprint)


def status(installed: str | Path, portable: str | Path) -> dict:
    inst, port = _norm_path(installed), _norm_path(portable)
    si, sp = snapshot(inst), snapshot(port)
    base, pair = _common_baseline(read_state(inst), read_state(port))
    return {
        "installed": str(inst), "portable": str(port),
        "installed_fingerprint": si.fingerprint, "portable_fingerprint": sp.fingerprint,
        "installed_schema": si.user_version, "portable_schema": sp.user_version,
        "installed_meaningful": si.meaningful, "portable_meaningful": sp.meaningful,
        "same": si.fingerprint == sp.fingerprint,
        "baseline": base or "", "pair_id": pair,
        "installed_running": bool(active_lock(inst)), "portable_running": bool(active_lock(port)),
    }


def _human_status(info: dict) -> str:
    return (
        f"Installed: {info['installed']}\n"
        f"Portable:  {info['portable']}\n\n"
        f"Schemat Installed: {info['installed_schema']}\n"
        f"Schemat Portable: {info['portable_schema']}\n"
        f"Zgodne dane: {'TAK' if info['same'] else 'NIE'}\n"
        f"Installed uruchomiona: {'TAK' if info['installed_running'] else 'NIE'}\n"
        f"Portable uruchomiona: {'TAK' if info['portable_running'] else 'NIE'}"
    )


def run_gui(installed: Path, portable: Path) -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.title("RK KANCELARIA — synchronizacja Installed ↔ Portable")
    root.geometry("790x530")
    root.minsize(720, 470)
    frm = tk.Frame(root, padx=18, pady=16); frm.pack(fill="both", expand=True)
    tk.Label(frm, text="RK KANCELARIA — SYNCHRONIZACJA", font=("Segoe UI", 15, "bold")).pack(anchor="w")
    tk.Label(frm, text="Synchronizacja bazy, dokumentów i projektów pism. Obie aplikacje muszą być zamknięte.",
             font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 14))

    inst_var, port_var = tk.StringVar(value=str(installed)), tk.StringVar(value=str(portable))
    for label, var, choose in (
        ("Installed — katalog danych", inst_var, None),
        ("Portable — katalog Data", port_var, True),
    ):
        row=tk.Frame(frm); row.pack(fill="x", pady=5)
        tk.Label(row,text=label,width=26,anchor="w").pack(side="left")
        tk.Entry(row,textvariable=var).pack(side="left",fill="x",expand=True,padx=(0,7))
        if choose:
            def pick(v=var):
                d=filedialog.askdirectory(initialdir=v.get() or str(Path.home()))
                if d: v.set(d)
            tk.Button(row,text="Wybierz…",command=pick).pack(side="left")

    text=tk.Text(frm,height=12,wrap="word",font=("Consolas",9)); text.pack(fill="both",expand=True,pady=14)
    text.configure(state="disabled")
    def set_text(s):
        text.configure(state="normal"); text.delete("1.0","end"); text.insert("1.0",s); text.configure(state="disabled")
    def refresh():
        try: set_text(_human_status(status(inst_var.get(),port_var.get())))
        except Exception as exc: set_text("BŁĄD: "+str(exc))
    def do(prefer="auto"):
        try:
            r=sync(inst_var.get(),port_var.get(),prefer)
            messagebox.showinfo("RK KANCELARIA", r.message + (f"\n\nBackup: {r.backup_path}" if r.backup_path else ""))
        except SyncConflict as exc:
            ans=messagebox.askyesnocancel(
                "Konflikt synchronizacji",
                str(exc)+"\n\nTAK = zachowaj INSTALLED i nadpisz Portable\nNIE = zachowaj PORTABLE i nadpisz Installed\nANULUJ = nic nie zmieniaj\n\nPrzed nadpisaniem powstanie pełny backup celu."
            )
            if ans is None: return
            try:
                pref="installed" if ans else "portable"
                r=sync(inst_var.get(),port_var.get(),pref)
                messagebox.showinfo("RK KANCELARIA", r.message+f"\n\nBackup: {r.backup_path}")
            except Exception as e2: messagebox.showerror("RK KANCELARIA — błąd",str(e2))
        except Exception as exc: messagebox.showerror("RK KANCELARIA — błąd",str(exc))
        refresh()
    buttons=tk.Frame(frm); buttons.pack(fill="x")
    tk.Button(buttons,text="Odśwież",command=refresh).pack(side="left")
    tk.Button(buttons,text="Synchronizuj automatycznie",command=lambda:do("auto"),font=("Segoe UI",9,"bold")).pack(side="left",padx=8)
    tk.Button(buttons,text="Installed → Portable",command=lambda:do("installed")).pack(side="left",padx=4)
    tk.Button(buttons,text="Portable → Installed",command=lambda:do("portable")).pack(side="left",padx=4)
    tk.Button(buttons,text="Zamknij",command=root.destroy).pack(side="right")
    refresh(); root.mainloop(); return 0


def _default_portable_for_this_copy() -> Path:
    runtime = resolve_runtime_paths(__file__)
    if runtime.mode == "portable":
        return runtime.data_dir
    st = read_state(installed_data_dir())
    peer = str(st.get("peer_hint") or "").strip()
    if peer:
        try:
            return Path(peer).expanduser().resolve()
        except Exception:
            pass
    return portable_data_dir()


def main(argv: list[str] | None = None) -> int:
    ap=argparse.ArgumentParser(description="RK KANCELARIA Installed <-> Portable sync")
    ap.add_argument("--installed-data", default=str(installed_data_dir()))
    ap.add_argument("--portable-data", default=str(_default_portable_for_this_copy()))
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--gui", action="store_true")
    ap.add_argument("--prefer", choices=("auto","installed","portable"), default="auto")
    args=ap.parse_args(argv)
    inst,port=_norm_path(args.installed_data),_norm_path(args.portable_data)
    if args.gui:
        return run_gui(inst,port)
    if args.status:
        print(json.dumps(status(inst,port),ensure_ascii=False,indent=2)); return 0
    try:
        r=sync(inst,port,args.prefer); print(r.message)
        if r.backup_path: print("Backup:",r.backup_path)
        return 0
    except SyncConflict as exc:
        print("KONFLIKT:",exc,file=sys.stderr); return 3
    except Exception as exc:
        print("BŁĄD:",exc,file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
