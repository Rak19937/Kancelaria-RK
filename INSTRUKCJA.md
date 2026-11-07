# RK KANCELARIA — ZBIORCZY PATCH 0.4.0-dev2 (2026-11-06)

Jedna paczka naprawcza oparta na **main**, commit `554ee81408dece74454bd194dc3550b03ff0b4d7`.

## Wgrywanie

1. Otwórz repozytorium `Rak19937/Kancelaria-RK` na gałęzi `main`.
2. Rozpakuj ZIP i dodaj do repozytorium **wszystkie pliki z paczki**, zachowując ścieżki. Pięć skryptów `.py` należy do katalogu głównego; plik `main.yml` musi trafić **wyłącznie** do `.github/workflows/main.yml` (zastąp dotychczasowy).
3. Najlepiej wykonaj **jeden commit**. Nie wgrywaj starej kopii `main.yml` z głównego katalogu.
4. Wejdź w **Actions → Build RK KANCELARIA Windows Portable**. Kontroluj najnowszy run dla commita.
5. Zapisz niezależną kopię dotychczasowego katalogu `Data` przed testem nowego EXE. Sam patch w GitHub CI nie odczytuje ani nie zmienia prywatnej bazy danych.

## Jak działa paczka

- Zachowuje już obecny `ZASTOSUJ_040_DEV2.py`; NIE wymaga ponownego wgrywania starego instalatora.
- Po instalacji dev2 uruchamia `PATCH_RK_040_DEV2_ALL.py` (dry-run → zastosowanie → weryfikacja) w katalogu roboczym Actions. Patch jest idempotentny, sprawdza kotwice i tworzy kopię zmienianych źródeł. Nie dotyka `Data`.
- Naprawia dwa testy Windows, które nie zamykały uchwytów SQLite.
- W `app.py` zabezpiecza przywracanie zestawu baza+dokumenty+projekty w oparciu o backup i dziennik awaryjny. W przypadku błędu podmiany przywracany jest kompletny poprzedni stan; przy awarii zasilania dziennik blokuje niebezpieczny start.
- Nie pozwala eksportować pełnego snapshotu, jeśli czyszczenie sesji i tokenów zakończy się błędem.
- Nie przekazuje tokena Cloud przez przekierowania HTTP.
- Przed buildem przeprowadza skan składni tekstowych plików źródłowych i uruchamia WSZYSTKIE `TEST_*.py` po kolei. Nie zatrzymuje diagnostyki na pierwszym nieudanym teście. Na nieudanym runie pobierz artefakt `RK-KANCELARIA-RAPORT-TESTY-040-DEV2` (pełne logi, JSON).
- Kod zostaje automatycznie zapisany na `main` dopiero po pomyślnym zbudowaniu i self-teście EXE.

## Granice weryfikacji

W środowisku przygotowania patcha uruchomiono lokalnie 5 testów patcha, 7 testów mechanizmów dev2 i 2 testy migratora. **Nie uruchomiono tutaj pełnego Windows EXE ani nie przeprowadzono testów na prawdziwej bazie kancelaryjnej.** Automatyczny skan kodu nie zastępuje testów manualnych, kontroli uprawnień w LAN lub audytu bezpieczeństwa. W przypadku niepowodzenia sprawdź raport i logi ze WSZYSTKICH testów zamiast podmieniać kod na ślepo.

## Bezpieczeństwo danych

Przed testami na rzeczywistych aktach zachowaj osobną kopię folderu Portable i jego `Data`. Nie testuj synchronizacji Installed/Portable ani przywracania snapshotów na jedynej kopii produkcyjnej. Przekazywanie danych kancelarii przez LAN wymaga szyfrowania transportu (HTTPS albo VPN).
