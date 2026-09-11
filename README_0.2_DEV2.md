# RK KANCELARIA 0.2.0-dev2 — Installed + Portable Sync

Wydanie rozwija stabilną 0.15.2 bez zmiany istniejącego frontendu i podstawowego modelu pracy.

## Najważniejsze zmiany

- dwa tryby danych: Installed i Portable,
- automatyczna i ręczna synchronizacja Installed ↔ Portable,
- synchronizacja SQLite przez backup API, zgodna z WAL,
- synchronizacja dokumentów i projektów pism,
- kontrola SHA-256 plików i logiczny fingerprint danych SQLite,
- pełny backup strony nadpisywanej przed synchronizacją,
- wykrywanie konfliktu, gdy obie kopie zmieniono niezależnie,
- blokada synchronizacji przy uruchomionej aplikacji,
- migracja baz 0.15.x do schematu 210,
- lokalne klucze DPAPI i sesje logowania nie są przenoszone między komputerami,
- Installed aktualizuje kod bez kasowania `%LOCALAPPDATA%\RK_KANCELARIA\Dane`,
- Portable przechowuje dane w `Data\` obok programu.

Szczegóły: `README_SYNCHRONIZACJA.md`.
