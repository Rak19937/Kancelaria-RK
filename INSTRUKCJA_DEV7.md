# RK KANCELARIA — dev7: stabilizacja podstaw (etap 1 z 8)

Paczka jest aktualizacją **źródeł na GitHubie**, a nie gotowym instalatorem Windows.
Wymaga repozytorium `Rak19937/Kancelaria-RK` na bazie `0.4.0-dev5 + UX6`.

## Wgrywanie

1. **Rozpakuj** ZIP na komputerze. Nie wgrywaj archiwum ZIP zamiast plików — GitHub go sam nie rozpakowuje.
2. Do **głównego katalogu** repozytorium wrzuć trzy pliki:
   - `rk_dev7_stability.py` — walidacja i bezpieczne usuwanie;
   - `ZASTOSUJ_DEV7.py` — aktualizator źródeł;
   - `TEST_RK_DEV7.py` — 22 testy kontrolne.
3. Jako **ostatni krok** zastąp plik `.github/workflows/aktualizacja-dev5.yml` nowym plikiem o tej samej nazwie. Pozostaw `.github/workflows/main.yml` bez zmian. Zatwierdź na gałęzi `main`.
4. Otwórz **GitHub → Actions → „RK KANCELARIA - DEV7: stabilizacja podstaw i Windows Portable”**.
5. Po zielonym wyniku pobierz artefakt `RK-KANCELARIA-DEV7-STABILITY-PORTABLE`, rozpakuj go w **nowym** katalogu i uruchom na **kopii** danych testowych.

Gdy trzy pliki Python są wgrywane osobno, stary workflow UX6 może uruchomić się jeszcze raz. Nie jest to wynik testu dev7. Docelowy workflow ma w nazwie „DEV7”.

## Ważne zasady bezpieczeństwa

- Nie przenoś katalogu `Data/` do repozytorium.
- Zanim przetestujesz usuwanie sprawy, skopiuj całą swoją bazę i katalog dokumentów. **Do prób użyj wyłącznie kopii.**
- Aktualizator źródeł nie zmienia rzeczywistej bazy. Zapisuje oryginalne źródła w `.rk_backup_before_dev7` (katalog zostaje na runnerze; nie jest publikowany).
- Przy usuwaniu sprawy najpierw wykonywany jest test w SQLite SAVEPOINT, a przed ostatecznym skasowaniem weryfikowany jest ZIP snapshotu, jego manifest i sumy kontrolne.
- Jeżeli program zgłosi blokującą zależność, **nie wyłączaj kluczy obcych SQLite** i nie kasuj powiązanych rekordów na ślepo.
- Limit gotowego archiwum snapshotu: **512 MB**, odpowiadający obecnemu ograniczeniu funkcji Recovery. Jeżeli kopia jest większa, trwałe usuwanie zostanie bezpiecznie zatrzymane.

## Gdy workflow jest czerwony

Otwórz nieudany krok zadania `full-dev5-repair`. Dodatkowe raporty są w artefakcie `RK-KANCELARIA-DEV7-TESTY`. Nie korzystaj z nieprzetestowanego pliku EXE.

## Zakres

To jest pierwszy etap stabilizacji (dev7). Nie zamyka pozostałych siedmiu etapów: przepływu dokumentów, spójności zadań i kalendarza, pełnego testu wszystkich formularzy, integralności synchronizacji i pilotażu na danych testowych.
