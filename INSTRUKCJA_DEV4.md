# RK KANCELARIA 0.4.0-dev4 R1 — naprawy stabilności i poprawności danych

**Baza wejściowa:** aktualne źródła `0.4.0-dev3 R2`, GitHub `Rak19937/Kancelaria-RK`, main `76142c0e9ac3898ab8b86caea0c11ee55c624788` (8.11.2026).

## Instalacja

1. Zrób pełną **zewnętrzną** kopię dotychczasowego katalogu `Data` i zachowaj stare Portable w innym katalogu. Nie aktualizuj programu bez kopii.
2. Rozpakuj ZIP i **prześlij pliki z zachowaniem katalogów do głównego katalogu repozytorium GitHub**. Nadpisz istniejące trzy moduły `rk_dev3*.py` i `.github/workflows/main.yml`. Nie wysyłaj folderu `Data`.
3. Zatwierdź wszystkie dodane/zmienione pliki **jednym commitem**.
4. GitHub Actions zastosuje `ZASTOSUJ_040_DEV4.py`, wykona testy, zbuduje EXE na Windows i dołączy `RK-KANCELARIA-WINDOWS-PORTABLE` do zakończonego przebiegu.
5. Nie instaluj/przenoś danych produkcyjnych do EXE przed sprawdzeniem, że kompilacja jest zielona. Testuj na **kopii** danych.

Instalator posiada opcje `--dry-run`, `--verify`, sam tworzy `.rk_backup_before_040_dev4`, nie dotyka `Data` i odmawia nieznanego wariantu kodu. Nowy numer schematu SQLite: **332**. Powrót do starego EXE na bazie po migracji wymaga przywrócenia **poprzedniej kopii `Data`**.

## Zmiany w R1

- Kalkulator terminów: dodałem ustawowo wolny **24 grudnia**.
- Pełny snapshot: **przerywa zapis z błędem**, jeżeli plik dokumentu nie może wejść do ZIP (zamiast ignorować błąd).
- Test kompletności snapshotu obejmuje też **zaszyfrowane dokumenty sejfu** (obecność plików).
- Usunięcie konta: pliki sejfu tego użytkownika zostają przekazane administratorowi usuwającemu konto.
- Usunięcie sprawy: po bezpiecznym snapshocie i zatwierdzeniu usunięcia rekordu czyści należące do niej pliki sejfu; nie kasuje całego katalogu `_vault`.
- Stoper: rozlicza daty wg `Europe/Warsaw`, dzieli pomiary przekraczające dobę, sprawdza zmianę zegara i chroni przed przypadkowym pomiarem ponad 31 dni.
- Ewidencja czasu: **Popraw**, **Anuluj wpis** z zachowaniem historii i wykluczeniem anulowanego wpisu z CSV.
- Sejf: zmiana hasła pliku (po podaniu starego), świadome usuwanie pliku z potwierdzeniem, dodatkowy audyt uprawnień.
- Portal Informacyjny: ponowny import aktualizuje **nieweryfikowane** wpisy CSV; zatwierdzone rekordy pozostają niezmienione.
- Kalendarz: użytkownik podaje długość eksportowanego wydarzenia (1–1440 min); zbyt duży import (>5 stron wyników) zgłasza błąd zamiast milcząco pomijać wydarzenia.
- Dodano odrębny dziennik działań dev4 i testy regresji. Uaktualniono wersję EXE do `0.4.0.4`.

## WAŻNE: rzeczy jeszcze NIE naprawione i ograniczenia

Ta aktualizacja jest **R1**, nie całkowitym zamknięciem wcześniejszych 27 uwag. Szczególnie:

- Brakuje pełnego, wszechstronnego **ACL dla wszystkich ekranów, wyszukiwarek, dokumentów i eksportów**. Nie używać jednego wdrożenia dla niezależnych kancelarii.
- Lokalny ZIP snapshotu **nie jest automatycznie szyfrowany**. Należy chronić foldery danych i kopie przed dostępem osób trzecich. Nie wysyłać ich do niezaufanych usług.
- Nadanie uprawnień w sejfie nadal **nie przekazuje klucza do pliku**; użytkownik musi znać hasło. Nie ma bezpiecznej funkcji odzyskania zapomnianego hasła ani wersjonowania zaszyfrowanych plików.
- Google / Outlook nadal **nie są pełną dwukierunkową synchronizacją**, OAuth wymaga ręcznej konfiguracji, zmiany i usunięcia nie są automatycznie propagowane. Limit stron jest teraz jawnie wykrywany, ale nie usunięty.
- Portal Informacyjny nadal działa przez CSV; brak autoryzowanego automatycznego API i załączników.
- Pozostają zadania UX/CRM: paginacja ewidencji, pełne rozliczenia, integracja etapów spraw, testy na komputerach z Avastem.
- Nie wykonano rzeczywistego buildu Windows po dev4 w środowisku tego przygotowania. GitHub Actions będzie jego pierwszą weryfikacją.

## Kontrole przed wdrożeniem do pracy

1. Załóż sprawę testową, uruchom stoper przez północ i sprawdź datę oraz sumę minut.
2. Popraw czas, następnie anuluj wpis i porównaj CSV z historią korekt.
3. Wgraj plik do sejfu, zmień hasło, spróbuj otworzyć starym i nowym hasłem; sprawdź usuwanie.
4. Wykonaj snapshot, test odtworzenia i sprawdź czy `_vault` jest w archiwum.
5. Spróbuj usunąć testowego użytkownika będącego właścicielem pliku sejfu; sprawdź dostęp administratora.
6. Sprawdź termin od 17.12.2026 + 7 dni kalendarzowych (powinien wskazać 28.12.2026 według ogólnej reguły przesunięcia).
7. Przetestuj budowanie Portable i wpływ na antywirusy bez wyłączania ochrony.

Dokumentację należy zachować razem z paczką. Program nadal jest w wersji **rozwojowej** — ręczna weryfikacja terminów procesowych jest konieczna.
