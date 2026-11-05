# RK KANCELARIA 0.3.7-dev1 — aktualizacja zbiorcza

**Ta paczka zastępuje poprzednią paczkę 0.3.7.** Nie trzeba jej wgrywać osobno. Zawiera jednocześnie:

1. Wiele niezależnych terminów ustalonych w jednej sprawie, datę, godzinę, miejsce i usuwanie/przywracanie;
2. Mój kalendarz, dostępny również po kliknięciu zegara na pulpicie;
3. Przypisanie jednego zadania lub terminu kilku użytkownikom;
4. Sprawy poboczne z powiązaniem ze sprawą główną i wymaganym dokumentem;
5. Klikalne nazwy i nawigację kontekstową;
6. Otwarty katalog kategorii spraw, wiele kategorii dla jednej sprawy, dodawanie własnych kategorii i filtr na liście spraw.

## Wgrywanie do GitHub

Otwórz repozytorium `Rak19937/Kancelaria-RK`. Wgraj następujące **siedem plików .py** do katalogu głównego, bez zmiany ich nazw:

- `rk_workspace_plus.py`
- `ZASTOSUJ_WORKSPACE_PLUS.py`
- `TEST_WORKSPACE_PLUS.py`
- `rk_case_categories.py`
- `ZASTOSUJ_KATEGORIE.py`
- `TEST_CASE_CATEGORIES.py`
- `TEST_INTEGRACJA_KATEGORII.py`

Plik **`.github/workflows/main.yml`** z paczki wgraj **do `.github/workflows/`**, zastępując istniejący. Nie umieszczaj go wyłącznie w katalogu głównym repozytorium.

Zatwierdź (Commit changes) i otwórz **Actions**. Workflow automatycznie stosuje aktualizację 0.3.7, następnie katalog kategorii i uruchamia testy, po czym buduje EXE. Na ostatniej stronie pomyślnego runu pobierz artifact `RK-KANCELARIA-WINDOWS-PORTABLE`.

**Nie wrzucaj katalogu `Data` ani danych klientów do GitHuba.** Nie nadpisuj działającej wersji programu, dopóki paczka Portable i testy funkcjonalne nie zostaną sprawdzone. Przy przenoszeniu danych wykonaj kopię bazy i plików spraw.

## Zgodność

Instalatory działają na kompletnej wersji źródeł `0.3.6-dev1`; jeśli poprzednia paczka 0.3.7 została już zintegrowana, pierwszy instalator nie dubluje zmian, a drugi dodaje katalog kategorii. Ponowne uruchomienie instalatorów pozostawia gotową wersję bez kolejnych modyfikacji.

Migracja schematu: **327 → 328 → 329**, bez czyszczenia istniejących rekordów. Dawne wartości pola `cases.category` zostaną przeniesione do nowego katalogu. Kategorie sprawy można zmienić bez zmian w dokumentach, zadaniach i terminach. Nowe postępowania poboczne korzystają z tego samego katalogu.

## Ograniczenia

Kalendarz osobisty nie jest zewnętrzną synchronizacją Google/Outlook; działa na lokalnych danych programu. Terminy procesowe nadal wymagają ręcznej weryfikacji podstaw i obliczenia. Zbudowanie EXE nie zastępuje testów interfejsu na Windows.
