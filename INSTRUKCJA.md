# RK KANCELARIA 0.3.10 — poprawka obsługi przycisku w skrzynce wpływu

## Ustalenia

W aktualnym kodzie przycisk **Odczytaj i przygotuj propozycje** wywołuje POST `/inbox/upload`, a serwer wykonuje ekstrakcję tekstu i OCR **w tym samym żądaniu** przed przejściem do kolejnego ekranu. Ponieważ nie ma wskaźnika zajętości, użytkownik może odnieść wrażenie, że nic się nie dzieje. W szczególności OCR skanowanego PDF może długo działać (domyślny limit 300 stron, wywołanie Tesseracta z limitem 120 s na stronę). Bez konkretnego pliku i logu nie można wykluczyć innej usterki.

**Zakres tej poprawki:** widoczny stan „Trwa odczytywanie”, sygnał przy długiej pracy, sprawdzenie obecności i rozmiaru pliku przed wysłaniem, ochrona przed wielokrotnym kliknięciem, nadal standardowy POST. **Nie przyspiesza OCR, nie dodaje kolejki w tle i nie gwarantuje, że każdy plik uda się odczytać.**

## Gdzie wrzucić na GitHub

Repozytorium: `Rak19937/Kancelaria-RK`, gałąź `main`.

1. `ZASTOSUJ_SKRZYNKA_FIX.py` → **katalog główny repozytorium** (obok `app.py`).
2. `TEST_INBOX_FIX_0310.py` → **katalog główny repozytorium**.
3. `.github/workflows/main.yml` → **podmień plik o tej samej ścieżce**.

**Wgrywaj w tej kolejności.** Najpierw skrypt, potem test, a workflow na końcu. Po ostatnim commicie GitHub Actions rozpocznie kompilację.

Workflow uruchomi skrypt w trybie `--dry-run`, następnie zastosuje zmianę, uruchomi istniejące testy i nowy test, zapisze zmienione źródła do `main` oraz zbuduje Portable EXE. Skrypt tworzy kopie oryginalnych plików w `.rk_inbox_fix_backup_0310` w katalogu repozytorium. Na ponownym uruchomieniu widzi znacznik poprawki i nie modyfikuje jej drugi raz.

**Nie wgrywaj ani nie commituj katalogu `Data`, dokumentów, prawdziwych danych osobowych czy kopii bezpieczeństwa.**

## Jak sprawdzić po pobraniu nowego Portable

1. Uruchom **nowo wygenerowany EXE** w bezpiecznej kopii aplikacji, na kopii danych.
2. Wejdź w **Skrzynka wpływu** i wybierz mały plik tekstowy `.txt` z fikcyjną treścią, np. `Sąd zobowiązuje do złożenia dokumentów w terminie 7 dni`.
3. Kliknij **Odczytaj i przygotuj propozycje**. Przycisk powinien pokazać **Trwa odczytywanie…**, a następnie powinien otworzyć się ekran **Sprawdź pismo przed przyjęciem**.
4. Powtórz próbę na skanie PDF. Jeśli `.txt` działa, a skan PDF długo czeka, problem leży zapewne w wolnym OCR lub konkretnym pliku, nie w obsłudze kliknięcia.

Jeśli nadal nie ma przekierowania, sprawdź lokalne pliki:
- Portable: `Data/rk_kancelaria_bledy.log` i `Data/rk_kancelaria_wolne_operacje.log` obok EXE;
- wersja zainstalowana: katalog danych RK KANCELARIA pod `%LOCALAPPDATA%`.

Dla bezpieczeństwa udostępniaj tylko **fragment logu bez danych klientów**. Nie wysyłaj rzeczywistych pism sądowych do publicznego repozytorium.

## Kontrole wykonane przy tworzeniu

- Testy poprawki na syntetycznych źródłach: 5/5 zaliczonych.
- Składnia Python i JavaScript poprawna; workflow ma poprawną składnię YAML.
- Wstępnie sprawdzone kotwice i SHA plików z repozytorium `main` 0.3.10-dev1.
- **Nie wykonano pełnych testów oryginalnego repozytorium ani testu Qt Desktop z prawdziwym plikiem.** Te kontrole powinny przejść w nowej kompilacji i w użytkowym teście na kopii danych.
