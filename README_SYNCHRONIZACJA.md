# RK KANCELARIA 0.2.0-dev2 — Installed ↔ Portable

## Co jest synchronizowane

- `sprawnik.sqlite3` — baza kancelarii,
- `dokumenty\` — dokumenty podpięte do spraw,
- `projekty_pism\` — pliki projektów pism.

Backupy, logi, cache/OCR i lokalny klucz DPAPI nie są przenoszone jako dane wspólne.
Sesje logowania są lokalne i po skopiowaniu bazy są czyszczone po stronie docelowej.

## Zasada bezpieczeństwa

Synchronizator zapisuje ostatni wspólny stan obu kopii.

1. Zmiana tylko w Installed → Installed jest kopiowana do Portable.
2. Zmiana tylko w Portable → Portable jest kopiowana do Installed.
3. Zmiany po obu stronach → **konflikt**. Program nie nadpisuje niczego bez wyboru użytkownika.
4. Przed każdym nadpisaniem powstaje pełna kopia celu w `backup_synchronizacji\`.
5. Synchronizacja jest blokowana, gdy którakolwiek kopia RK KANCELARIA jest uruchomiona.

## Automatyczna synchronizacja

Jeżeli obok programu znajduje się `auto_sync.flag`:

- przed startem RK KANCELARIA próbuje zsynchronizować dane,
- po prawidłowym zamknięciu ponawia synchronizację,
- przy konflikcie otwiera synchronizator i wymaga wyboru.

Portable automatycznie wykrywa Installed w `%LOCALAPPDATA%\RK_KANCELARIA\Dane`.
Installed zapamiętuje ścieżkę sparowanej kopii Portable po pierwszej synchronizacji.

## Ręczna synchronizacja

Uruchom `SYNCHRONIZUJ.bat` lub `SYNCHRONIZUJ.vbs` przy zamkniętych obu aplikacjach.

To wydanie synchronizuje **pełny stan**. Nie scala jeszcze dwóch niezależnie zmienionych baz rekord-po-rekordzie. To celowy mechanizm ochronny wersji 0.2.
