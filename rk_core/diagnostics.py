"""Lokalne logowanie problemów; nie wysyła żadnych danych do sieci."""
from __future__ import annotations
import traceback
from pathlib import Path
from datetime import datetime


def write_exception(error_log: Path, path: str, exc: Exception) -> None:
    try:
        error_log.parent.mkdir(parents=True, exist_ok=True)
        with error_log.open('a', encoding='utf-8') as f:
            f.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] {path}\n")
            traceback.print_exc(file=f)
    except Exception:
        pass


def write_slow_request(perf_log: Path, path: str, elapsed: float) -> None:
    if elapsed < 0.75: return
    try:
        perf_log.parent.mkdir(parents=True, exist_ok=True)
        with perf_log.open('a', encoding='utf-8') as f:
            f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {elapsed*1000:.0f} ms | {path}\n")
    except Exception:
        pass
