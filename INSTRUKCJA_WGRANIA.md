# RK KANCELARIA — 0.3.6-dev1: terminy i odnośniki

**Ta paczka zawiera także pliki aktualizacji 0.3.5 (Obieg korespondencji), ponieważ w sprawdzonym repozytorium na GitHubie nadal była wersja 0.3.4-dev1.** Dzięki temu nie trzeba szukać poprzedniego ZIP.

## Wgraj do GitHuba

Repozytorium: https://github.com/Rak19937/Kancelaria-RK

**Do katalogu głównego gałęzi `main`** wgraj siedem plików `.py`:

- `rk_correspondence.py`
- `ZASTOSUJ_KORESPONDENCJE.py`
- `TEST_KORESPONDENCJE.py`
- `rk_record_navigation.py`
- `ZASTOSUJ_NAWIGACJE.py`
- `TEST_NAWIGACJA.py`
- `TEST_INTEGRACJA_NAWIGACJI.py`

Trzy dotyczą wcześniejszego obiegu korespondencji, cztery nowej nawigacji.

**W folderze `.github/workflows/`** zastąp dotychczasowy plik `main.yml` wersją z paczki. Nie wgrywaj `main.yml` do katalogu głównego.

Zatwierdź zmiany. Wejdź w `Actions` i śledź **najnowszy przebieg**, a nie starsze uruchomienia: https://github.com/Rak19937/Kancelaria-RK/actions.

Workflow sam zastosuje aktualizacje po kolei: istniejące 0.3.4 → korespondencja 0.3.5 → nawigacja 0.3.6. Gdy integrator jest już zastosowany, pominie ponowną podmianę.

Po pełnym zielonym przebiegu w sekcji `Artifacts` będzie `RK-KANCELARIA-WINDOWS-PORTABLE`. Pobierz i rozpakuj w nowym katalogu. Zachowaj starą wersję i jej folder `Data`.

## Co zmieniono

- W zakładce sprawy **Terminy** każdy termin będący zadaniem ma klikalny tytuł, przycisk **Otwórz** i **Do kosza**.
- Alerty są odrębne od zadań; automatycznego alertu do istniejącego zadania nie pokazujemy jako osobnego terminu.
- Pole „następna czynność w sprawie” to nie zadanie. Ma osobny przycisk **Wyczyść datę**, bez kasowania sprawy.
- Na ekranie edycji zadania/terminu jest także przycisk przeniesienia do Kosza.
- Kliknięcie tytułu zadania na Pulpicie, w widoku Dzisiaj, na liście zadań, w karcie sprawy i w kalendarzu prowadzi do konkretnego zadania.
- Kalendarz odsyła do odpowiedniego zadania, zdarzenia procesowego lub zdarzenia kancelarii, nie tylko do sprawy.
- Dokumenty, projekty i zadania pokazują odnośniki do rzeczywistych powiązanych rekordów, w tym do korespondencji 0.3.5.

Nie jest to automatyczne dopasowanie tytułów po tekście (np. każde wystąpienie słowa „mediacja” nie stanie się linkiem). Linki wynikają z identyfikatorów powiązań już zapisanych w bazie.

## Bezpieczeństwo

- Integratory modyfikują tylko kod (`app.py` i `README.md`), nie otwierają danych użytkownika.
- Zmiana numeru schematu do `327` jest addytywna; nowe widoki korzystają z istniejących tabel.
- Usunięcie zadania/terminu przez przycisk przenosi rekord do **Kosza**, a nie usuwa go bezpowrotnie.
- Data „następna czynność” jest czyszczona osobno i rejestrowana w dzienniku zmian.
- Najpierw przeprowadź testy na fikcyjnych danych.

Jeśli GitHub pokaże `failure`, zachowaj stary program i podaj numer przebiegu. Lokalnie wykonano testy logiki oraz integratora; **pełnej kompilacji Windows nowej wersji jeszcze nie wykonano**.
