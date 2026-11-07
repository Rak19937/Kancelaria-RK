# RK KANCELARIA 0.4.0-dev2 — audyt i ujednolicona poprawka

Baza przeglądu: repozytorium `Rak19937/Kancelaria-RK`, `main` commit `554ee81408dece74454bd194dc3550b03ff0b4d7`.

## Zakres

W drzewie GitHub rozpoznano **158 plików**, w tym **95 plików Python** oraz 4 binarne zasoby (logo/ikona/dane OCR). Przegląd manualny objął kod bazodanowy, synchronizację, tworzenie i odtwarzanie snapshotów, Cloud, kolejkę OCR, HTTP/CSRF, moduły spraw/dokumentów, testy, instalatory i GitHub Actions. Pełny statyczny skan pozostałych tekstowych źródeł jest wykonywany przez `AUDYT_I_TESTY_RK_040_DEV2.py` podczas Actions i udostępniany w JSON.

## Wykryte lub potwierdzone zagadnienia

- Ostatni run `42236830744`: WinError 32 podczas sprzątania testowej bazy SQLite (`TEST_STABILIZACJA_040_DEV2.py`); analogiczny wzorzec w `TEST_UI_HTTP_040_DEV2.py`.
- Aktualne `main` zawiera nadal aplikację `0.4.0-dev1`; `0.4.0-dev2` był nakładany podczas CI. Kolejne hotfixy testów zderzały się z kotwicami migratora. Zbiorczy workflow porządkuje te kroki.
- `apply_pending_restore_if_any` nie wymieniał bazy i drzew dokumentów w jednej odzyskiwalnej operacji — ryzyko niespójności na przerwanej kopii.
- `create_data_snapshot_zip` w przypadku błędu oczyszczania sekretów tylko logował ostrzeżenie i kontynuował — ryzyko nieumyślnego eksportu tokenów Cloud.
- Klient Cloud korzystał z automatycznych redirectów `urllib`; nie powinien przenosić `Authorization` w niekontrolowanym przekierowaniu.
- CI commitowało źródła po testach źródłowych, ale **przed** buildem i self-testem gotowego EXE — możliwość pozostawienia na `main` wersji, która nie buduje się na Windows.
- CI kończyło zbiorczą diagnostykę na pierwszej porażce, powodując sekwencję pojedynczych hotfixów.
- W repo istnieją dwa pliki `main.yml`; rzeczywisty workflow to `.github/workflows/main.yml`, a kopia w root nie uruchamia się w GitHub Actions.
- `app.py` nadal pozostaje rozbudowanym monolitem; ten patch nie deklaruje zakończenia pełnej refaktoryzacji ani usunięcia wszystkich możliwych usterek funkcjonalnych.

## Walidacja przed dostarczeniem

- Nowy patch źródeł: 5 testów jednostkowych/integracyjnych na syntetycznych bazach — OK.
- Nowe mechanizmy dev2: 7 testów jednostkowych z domknięciem połączeń SQLite — OK lokalnie.
- Migrator `ZASTOSUJ_040_DEV2.py`: 2 testy syntetyczne — OK.
- Składnia plików Python w paczce i parsowanie YAML workflow — OK.
- Pełne testy źródeł repozytorium, Windows Portable i testy graficznego interfejsu — **do potwierdzenia w GitHub Actions / na Windows**.

## Wynik i ograniczenia

**Paczka jest przygotowana i przetestowana na izolowanych danych.** Nie potwierdzono jeszcze zielonego buildu z najnowszymi zmianami; dopiero końcowy wynik Actions pozwala go potwierdzić. Audyt statyczny nie gwarantuje braku wszystkich błędów, szczególnie w obsłudze realnych skanów, jakości OCR, wydajności dużych baz i integracji Qt/WebEngine.
