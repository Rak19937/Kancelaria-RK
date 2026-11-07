# Raport lokalnej weryfikacji RK KANCELARIA 0.4.0-dev3

## Zrealizowane sprawdzenia

- 12 testów modułów: SQLite, etapów spraw, czasu, stawki, eksportu bez wykonywania formuł CSV, szyfrowania i integralności sejfu, uprawnień, importu sądowego, importu wydarzeń, obsługi czasu Warszawa/UTC, publikowania Google i Microsoft Graph bez ujawniania tytułu sprawy.
- 2 testy migratora na syntetycznym repozytorium: idempotencja, dry-run, weryfikacja, odmowa nieznanej wersji, zachowanie bajtów testowej bazy danych.
- Weryfikacja składni Pythona nowych źródeł i parsowanie YAML workflow.

## Nadal do zweryfikowania w GitHub Actions / Windows

- Cała istniejąca kolekcja `TEST_*.py` na aktualnym repozytorium po rzeczywistym zastosowaniu migratora.
- Pełny build Windows Portable i self-test EXE.
- Ekrany w PySide6/QtWebEngine, zachowanie hover i klawiatury oraz płynność animacji.
- Integracje OAuth na testowych kontach i różne strefy czasowe.
- Oddzielenie uprawnień do wszystkich **istniejących** dokumentów w standardowym archiwum (nieobjęte tym patchem).
- API Portalu Informacyjnego w rzeczywistej autoryzowanej konfiguracji (nieobjęte tym patchem).

## Zgodność baz

Migracja dodaje wyłącznie tabele `dev3_*` oraz podnosi `PRAGMA user_version` 330 → 331. Nie przenosi plików z dotychczasowego katalogu dokumentów. Obsługa starszej wersji programu na już zaktualizowanej bazie nie jest gwarantowana; nie zastępuje to backupu.
