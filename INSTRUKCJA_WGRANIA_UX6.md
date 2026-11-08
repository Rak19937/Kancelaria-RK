# RK KANCELARIA — aktualizacja UX6 dla dev5

Wersja bazowa: **0.4.0-dev5**. Poprawki są dodatkiem do tej wersji.

## Wgrywanie do repozytorium GitHub

1. Rozpakuj archiwum ZIP **na komputerze** — GitHub nie rozpakowuje przesłanych plików ZIP automatycznie.
2. W katalogu głównym repozytorium `Rak19937/Kancelaria-RK` prześlij trzy pliki: `rk_ux6.py`, `ZASTOSUJ_UX6.py`, `TEST_RK_UX6.py`.
3. W katalogu `assets` prześlij `rk_ux6.css` i `rk_ux6.js`.
4. W katalogu `.github/workflows` zastąp plik `aktualizacja-dev5.yml` tym z paczki. **Nie usuwaj** `main.yml`.
5. Wszystkie zmiany zatwierdź na gałęzi `main` (Commit changes). Aktualizacja uruchomi się automatycznie w GitHub Actions pod nazwą `RK KANCELARIA - DEV5 UX6: poprawki funkcji i Windows Portable`.
6. Po zielonym przebiegu otwórz uruchomienie Actions i pobierz artefakt `RK-KANCELARIA-DEV5-UX6-PORTABLE`. Jest to nowa aplikacja Windows Portable, a nie ZIP źródeł.

**Uwaga:** Samo wgranie ZIP-a do repozytorium nie zastosuje kodu. Należy rozpakować i umieścić pliki w podanych lokalizacjach. Pliki `.py` są zapisywane do repozytorium automatycznie przez workflow dopiero po pomyślnych testach. Akcja nie modyfikuje żadnych danych klienta przechowywanych w katalogu `Data`.

## Wprowadzane zmiany

- Usuwanie spraw: wymóg uprawnień administratora jest pokazany wprost; zapis pełnej kopii jest sprawdzany **przed** usunięciem; integralność bazy jest zachowana, a nierozwiązane więzy obce blokują operację z czytelnym komunikatem zamiast półusunięcia.
- Skrzynka wpływu: propozycje czynności są widoczne jako duże, rozwijane karty z większą czcionką i pełnymi polami do edycji.
- Równoległe etapy: link `Etapy równoległe` w edycji sprawy oraz na ekranie etapu głównego. Równocześnie może trwać proces sądowy, mediacja i inne czynności.
- Własne nazwy: `＋ DODAJ WŁASNE…` w listach rodzajów dokumentu, zadania, alertu i zdarzenia; wpis jest przechowywany w bazie. Użytkownik może również bezpośrednio wpisywać niestandardową nazwę równoległego etapu.
- Boczne menu: wyśrodkowane ikonki przy złożonym pasku.
- Kalendarz: redukcja powtarzających się wpisów w widoku miesiąca **bez kasowania danych**, aktywne odsyłacze do dodatkowych pozycji i edycja wszystkich wpisów z widoku danego dnia.

## Zabezpieczenia i ograniczenia

- Nie wszystkie listy mogą dopuszczać własne wpisy. **Role użytkowników, identyfikatory spraw i dokumentów, statusy systemowe** pozostają kontrolowane, ponieważ dowolny tekst mógłby unieważnić reguły dostępu, powiązania bazy lub raporty.
- Użytkownik musi samodzielnie zweryfikować terminy procesowe; program ich nie oblicza i nie zatwierdza w imieniu prawnika.
- Dodatkowe etapy oraz edycja wpisów globalnego kalendarza są na razie dostępne administratorowi. Rozszerzenie ich na zwykłe konta wymaga polityki dostępu per sprawa.
- Nie ma gwarancji naprawienia błędu usuwania w każdej historycznej bazie. Jeżeli pozostaje niestandardowa zależność, program powinien **nie usuwać** sprawy, zachować snapshot i pokazać przyczynę. Nie należy wyłączać `PRAGMA foreign_keys`.
- Po zielonych automatycznych testach należy ręcznie sprawdzić funkcje na kopii danych w Windows. Nie uruchamiać destrukcyjnych testów na jedynej bazie produkcyjnej.

### Rezerwowa kopia kodu i cofnięcie

Instalator zapisuje oryginalne `app.py`, `rk_dev3.py` i `rk_inbox.py` w `.rk_backup_before_ux6` na środowisku kompilacji. Jeżeli testy nie przejdą, workflow nie zatwierdzi zmodyfikowanych źródeł. Nigdy nie kasuj oryginalnego katalogu `Data` tylko po to, by podmienić program. Przed testowaniem destrukcyjnego usuwania wykonaj dodatkową kopię danych.
