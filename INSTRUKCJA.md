# RK KANCELARIA 0.3.10 — poprawka instalatora skrzynki wpływu (GitHub Actions)

## Co się stało?

GitHub Actions, uruchomienie #42202006608, przeszło instalację 0.3.10, ale etap „Popraw widoczność odczytu w skrzynce wpływu” zakończył się komunikatem `rk_inbox.py: niezgodna wersja źródła`.

GitHub potwierdza, że blob `rk_inbox.py` na `main` odpowiada dokładnie wartości oczekiwanej przez instalator. Najbardziej prawdopodobną przyczyną jest transformacja zakończeń linii LF → CRLF podczas checkoutu Windows. Poprzedni instalator porównywał bezpośrednio bajty.

## Co wrzucić na GitHub?

Zastąp **tylko jeden** plik w katalogu głównym repozytorium:

`ZASTOSUJ_SKRZYNKA_FIX.py`

Adres: https://github.com/Rak19937/Kancelaria-RK/blob/main/ZASTOSUJ_SKRZYNKA_FIX.py

1. Na GitHub otwórz link i kliknij ołówek (Edit this file).
2. Zastąp zawartość zawartością pliku z tej paczki i wybierz Commit changes.
3. Poczekaj na automatyczne uruchomienie workflow i sprawdź jego wynik.

Nie trzeba ruszać `.github/workflows/main.yml`, `rk_inbox.py` ani katalogu `Data`.

## Zakres techniczny

- `baseline_matches()` uznaje plik za zgodny, jeśli hash Git blob pasuje bezpośrednio lub po konwersji samych końców linii CRLF → LF.
- Każda inna zmiana źródła powoduje zatrzymanie instalacji przed zapisem.
- Nie zmienia kodu aplikacji, schematu bazy ani przechowywanych akt; zmienia tylko sposób sprawdzania zgodności przez instalator.
- Wykonane lokalnie: 5 testów regresyjnych oryginalnego instalatora + testy akceptacji CRLF, odmowy przy rzeczywistej zmianie, kopii i ponownego uruchomienia.

**Uwaga:** naprawia blokadę kompilacji, nie dowodzi jeszcze, że OCR zadziała z konkretnym plikiem. Po zielonym buildzie sprawdź funkcjonalność w nowym Portable na pliku testowym. Jeśli nadal nie przechodzi, zbadaj log `Data/rk_kancelaria_bledy.log` (bez danych klientów).
