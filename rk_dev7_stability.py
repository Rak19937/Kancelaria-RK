# -*- coding: utf-8 -*-
"""RK KANCELARIA: etap 1 stabilizacji prywatnej (DEV7).

Narzędzia bez HTTP i bez operacji na rzeczywistych danych. Operacja usuwania
najpierw wykonywana jest testowo w SQLite SAVEPOINT, a następnie wycofywana.
Snapshot jest sprawdzany strumieniowo, zanim zmienimy bazę.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import hashlib
import json
import re
import sqlite3
import zipfile

MAX_RESTORABLE_ZIP = 512 * 1024 * 1024  # zgodne z schedule_data_snapshot_restore


class Dev7SafetyError(ValueError):
    """Komunikat do wyświetlenia administratorowi, bez danych wrażliwych."""


def check_case_form(fields, valid_statuses, *, new=False):
    """Waliduje dane przed zapisem; nie modyfikuje oryginalnego formularza."""
    title = str(fields.get('title') or '').strip()
    if not title:
        raise Dev7SafetyError('Podaj nazwę sprawy. Zmian nie zapisano.')
    if len(title) > 500:
        raise Dev7SafetyError('Nazwa sprawy nie może mieć ponad 500 znaków.')
    if new and not str(fields.get('subject') or '').strip():
        raise Dev7SafetyError('Podaj przedmiot sprawy. Zmian nie zapisano.')
    status = str(fields.get('status') or '').strip()
    if status not in valid_statuses:
        raise Dev7SafetyError('Nieznany status sprawy. Odśwież formularz i spróbuj ponownie.')
    value = str(fields.get('next_date') or '').strip()
    if value:
        try:
            d = date.fromisoformat(value)
        except (ValueError, TypeError) as exc:
            raise Dev7SafetyError('Najbliższa data ma nieprawidłowy format. Wymagany RRRR-MM-DD.') from exc
        if d.isoformat() != value:
            raise Dev7SafetyError('Najbliższa data musi mieć format RRRR-MM-DD.')
    return True


def _blocked_case_references(con, case_id):
    """Nazwy tabel ograniczające usunięcie — diagnostyka, bez zmian w DB."""
    found=[]
    for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',table):continue
        for fk in con.execute(f'PRAGMA foreign_key_list("{table}")'):
            if fk[2] != 'cases' or str(fk[6]).upper() not in ('RESTRICT','NO ACTION'):continue
            column=str(fk[3])
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',column):continue
            count=con.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{column}"=?',(case_id,)).fetchone()[0]
            if count:found.append(f'{table} ({count})')
    return ', '.join(found[:8])


def preflight_case_delete(con, case_id, delete_callback):
    """Próba skasowania w SAVEPOINT: zawsze rollback, nawet przy błędzie.

    Kontrola FK wymaga włączonej ochrony SQLite. Żadne dane nie pozostaną
    usunięte po preflight, nawet gdy wyzwalacz odrzuci operację.
    """
    enabled = con.execute('PRAGMA foreign_keys').fetchone()
    if not enabled or int(enabled[0]) != 1:
        raise Dev7SafetyError('Ochrona powiązań SQLite jest wyłączona — usuwanie wstrzymano.')
    if not con.execute('SELECT 1 FROM cases WHERE id=?', (case_id,)).fetchone():
        raise Dev7SafetyError('Nie znaleziono wskazanej sprawy.')

    con.execute('SAVEPOINT rk_dev7_case_preflight')
    err = None
    try:
        delete_callback(con, case_id)
        if con.execute('SELECT 1 FROM cases WHERE id=?', (case_id,)).fetchone():
            raise Dev7SafetyError('Próbne usunięcie nie usunęło sprawy.')
        violations = con.execute('PRAGMA foreign_key_check').fetchmany(3)
        if violations:
            tables = ', '.join(sorted({str(x[0]) for x in violations}))
            raise Dev7SafetyError(f'Kontrola powiązań bazy wykryła problem w: {tables}.')
    except (sqlite3.Error, ValueError) as exc:
        err = exc
    finally:
        try:
            con.execute('ROLLBACK TO SAVEPOINT rk_dev7_case_preflight')
            con.execute('RELEASE SAVEPOINT rk_dev7_case_preflight')
        except sqlite3.Error as exc:
            raise Dev7SafetyError('Nie udało się bezpiecznie wycofać próby usunięcia. Przerwij operację.') from exc
    if err:
        if isinstance(err, Dev7SafetyError):
            raise err
        details = _blocked_case_references(con, case_id)
        msg = ('Powiązania wymagają ręcznej kontroli: ' + details if details
               else 'Próbne usunięcie ujawniło blokującą zależność bazy: ' + str(err))
        raise Dev7SafetyError(msg) from err
    return True


def verify_backup_snapshot(path, original_zip):
    """Sprawdza zapis, format, manifest i SHA-256 bez rozpakowywania archiwum.

    Weryfikujemy też zgodność z limitem aktualnej procedury Recovery. Kiedy
    program nie potrafi odtworzyć kopii, blokujemy nieodwracalne usunięcie.
    """
    p = Path(path)
    if len(original_zip) > MAX_RESTORABLE_ZIP:
        raise Dev7SafetyError('Snapshot przekracza limit przywracania 512 MB; nie usuwaj sprawy.')
    if not p.is_file() or p.stat().st_size != len(original_zip):
        raise Dev7SafetyError('Kopia bezpieczeństwa nie została zapisana w całości.')
    source_digest = hashlib.sha256(original_zip).digest()
    stored_digest = hashlib.sha256()
    with p.open('rb') as inp:
        for data in iter(lambda: inp.read(1024 * 1024), b''):
            stored_digest.update(data)
    if source_digest != stored_digest.digest():
        raise Dev7SafetyError('Kopia bezpieczeństwa różni się od danych źródłowych.')
    try:
        with zipfile.ZipFile(p, 'r') as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise Dev7SafetyError('Snapshot zawiera powielone ścieżki plików.')
            if not {'snapshot.json', 'sprawnik.sqlite3'}.issubset(names):
                raise Dev7SafetyError('W snapshocie brakuje metadanych lub bazy danych.')
            manifest = json.loads(archive.read('snapshot.json').decode('utf-8'))
            if manifest.get('format') != 'RK-KANCELARIA-DATA-SNAPSHOT':
                raise Dev7SafetyError('Nierozpoznany format kopii bezpieczeństwa.')
            hashes = manifest.get('file_sha256')
            if not isinstance(hashes, dict) or set(hashes) != set(names) - {'snapshot.json'}:
                raise Dev7SafetyError('Lista plików snapshotu jest niekompletna.')
            if archive.getinfo('sprawnik.sqlite3').file_size > 1024 * 1024 * 1024:
                raise Dev7SafetyError('Baza przekracza limit przywracania 1 GB.')
            for name in hashes:
                if name.startswith('/') or '..' in Path(name).parts or '\\' in name:
                    raise Dev7SafetyError('Nieprawidłowa ścieżka w archiwum.')
                sha = hashlib.sha256()
                with archive.open(name) as reader:
                    for block in iter(lambda: reader.read(1024 * 1024), b''):
                        sha.update(block)
                if sha.hexdigest() != hashes[name]:
                    raise Dev7SafetyError('Błędna suma kontrolna pliku w archiwum: ' + name)
    except (zipfile.BadZipFile, OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise Dev7SafetyError('Snapshot jest nieczytelny lub uszkodzony. Sprawa nie została usunięta.') from exc
    return True


def assert_deleted_case_integrity(con, case_id):
    """Wywołaj wewnątrz tego samego bloku transakcyjnego co DELETE."""
    if con.execute('SELECT 1 FROM cases WHERE id=?', (case_id,)).fetchone():
        raise Dev7SafetyError('Sprawa wciąż istnieje — wycofano transakcję.')
    bad = con.execute('PRAGMA foreign_key_check').fetchmany(3)
    if bad:
        raise Dev7SafetyError('Spójność powiązań bazy nie przeszła kontroli — wycofano transakcję.')
    return True
