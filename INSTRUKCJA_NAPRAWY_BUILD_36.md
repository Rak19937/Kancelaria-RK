# RK KANCELARIA 0.3.7-dev1 — naprawa kompilacji #36

Błąd: `invalid syntax. Perhaps you forgot a comma? (app.py, line 3709)` podczas kroku „Terminy, kalendarz osobisty, zespoły i sprawy poboczne 0.3.7-dev1”.

Przyczyna: integrator ZASTOSUJ_WORKSPACE_PLUS.py w trzech miejscach generował wywołania `sync_task_alert` bez nawiasu kończącego `)` (dla terminu, nowego zadania i edycji zadania). Naprawiono wszystkie trzy miejsca.

## Wgranie
1. W repozytorium `Rak19937/Kancelaria-RK` na gałęzi **main** zastąp plik **ZASTOSUJ_WORKSPACE_PLUS.py** poprawionym z tej paczki.
2. Zastąp również **TEST_WORKSPACE_PLUS.py** — zawiera regresyjny test składni wstrzykiwanego kodu, oprócz pozostałych testów.
3. Zatwierdź zmiany przez „Commit changes”. Workflow uruchomi się automatycznie.
4. Otwórz kartę **Actions** i monitoruj nową kompilację. Samo zielone Actions nie zastępuje testów funkcjonalnych w Windows.

**Nie wgrywaj na nowo** plików kategorii, kalendarza ani `main.yml`: poprzednia zbiorcza aktualizacja jest w repozytorium i pozostaje właściwa. Nie zmieniaj katalogu `Data` ani aktualnej instalacji Portable do uzyskania zielonej kompilacji i przeprowadzenia testów.

## Weryfikacja
- Zintegruj terminarz 0.3.7 — sukces
- Zintegruj katalog kategorii 0.3.7 — sukces
- Testy źródeł — sukces
- Build EXE, self-test, Artefakt Portable — sukces

Jeśli dalszy krok workflow ujawni nowy błąd, odczytaj jego log; ten hotfix dotyczy konkretnie błędu składni #36.
