# -*- coding: utf-8 -*-
"""Centralna konfiguracja ścieżek RK KANCELARIA 0.2.

Ten moduł nie otwiera bazy i nie tworzy katalogów. Jego jedynym zadaniem jest
wyznaczenie stabilnych ścieżek dla trybu Installed, Portable lub jawnie
wskazanego katalogu danych.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


_TRUE = {"1", "true", "yes", "tak", "portable"}


def _normalized(value: str | None) -> str:
    return (value or "").strip().lower()


def application_dir(module_file: str | Path) -> Path:
    """Katalog programu widziany przez użytkownika.

    Przy zwykłym uruchomieniu jest to katalog źródeł. Po przyszłym spakowaniu
    do EXE będzie to katalog zawierający plik wykonywalny, a nie katalog TEMP
    używany przez bundler.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(module_file).resolve().parent


def installed_data_dir() -> Path:
    if os.name == "nt":
        root = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or str(Path.home())
        return (Path(root) / "RK_KANCELARIA" / "Dane").resolve()
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / "RK_KANCELARIA" / "Dane").resolve()
    xdg = os.getenv("XDG_DATA_HOME", "").strip()
    if xdg:
        return (Path(xdg).expanduser() / "RK_KANCELARIA" / "Dane").resolve()
    return (Path.home() / ".local" / "share" / "RK_KANCELARIA" / "Dane").resolve()


def detect_mode(app_dir: Path) -> str:
    """Zwraca: installed, portable albo custom.

    SPRAWNIK_DATA_DIR ma najwyższy priorytet i oznacza jawny/custom katalog
    danych (ważne dla serwera LAN i self-testów). Następnie honorowany jest
    RK_KANCELARIA_MODE, a na końcu znacznik portable.flag obok programu.
    """
    if os.getenv("SPRAWNIK_DATA_DIR", "").strip():
        return "custom"

    forced = _normalized(os.getenv("RK_KANCELARIA_MODE"))
    if forced in {"portable", "installed"}:
        return forced
    if forced and forced not in {"auto", "default"}:
        raise ValueError("RK_KANCELARIA_MODE musi mieć wartość installed, portable albo auto")

    portable_env = _normalized(os.getenv("RK_KANCELARIA_PORTABLE"))
    if portable_env in _TRUE:
        return "portable"
    if (app_dir / "portable.flag").is_file():
        return "portable"
    return "installed"


@dataclass(frozen=True)
class RuntimePaths:
    app_dir: Path
    mode: str
    data_dir: Path
    db_path: Path
    files_dir: Path
    drafts_dir: Path
    ocr_dir: Path
    backups_dir: Path
    daily_backups_dir: Path
    close_backups_dir: Path
    recovery_dir: Path
    pending_restore_dir: Path
    backup_key_file: Path
    migration_log: Path
    version_marker: Path
    error_log: Path
    perf_log: Path
    desktop_exit_flag: Path

    @property
    def is_portable(self) -> bool:
        return self.mode == "portable"


def resolve_runtime_paths(module_file_or_dir: str | Path) -> RuntimePaths:
    raw = Path(module_file_or_dir)
    app_dir = raw.resolve() if raw.is_dir() else application_dir(raw)
    mode = detect_mode(app_dir)

    explicit = os.getenv("SPRAWNIK_DATA_DIR", "").strip()
    if explicit:
        data_dir = Path(explicit).expanduser().resolve()
    elif mode == "portable":
        data_dir = (app_dir / "Data").resolve()
    else:
        data_dir = installed_data_dir()

    pending = data_dir / "pending_restore"
    return RuntimePaths(
        app_dir=app_dir,
        mode=mode,
        data_dir=data_dir,
        db_path=data_dir / "sprawnik.sqlite3",
        files_dir=data_dir / "dokumenty",
        drafts_dir=data_dir / "projekty_pism",
        ocr_dir=data_dir / "OCR",
        backups_dir=data_dir / "backup_przed_aktualizacja",
        daily_backups_dir=data_dir / "backup_codzienny",
        close_backups_dir=data_dir / "backup_przy_zamykaniu",
        recovery_dir=data_dir / "recovery",
        pending_restore_dir=pending,
        backup_key_file=data_dir / ".backup_key.dpapi",
        migration_log=data_dir / "migracja_danych.log",
        version_marker=data_dir / ".wersja_programu",
        error_log=data_dir / "rk_kancelaria_bledy.log",
        perf_log=data_dir / "rk_kancelaria_wolne_operacje.log",
        desktop_exit_flag=Path(os.getenv("RK_DESKTOP_EXIT_FLAG", str(data_dir / ".desktop_exit"))),
    )
