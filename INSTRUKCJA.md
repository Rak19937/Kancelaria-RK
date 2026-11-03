# RK KANCELARIA — Skrzynka wpływu 0.3.1-dev1

**Punkt wyjścia:** źródła wersji portable z 17 września 2026 r. (commit `aa64d3bd50e6d71eae15ebcaabd41fa54e7ec4aa`, repo `Rak19937/Kancelaria-RK`).

Poprawka zawiera moduł `rk_inbox.py`, 13 testów w `TEST_INBOX_REVIEW.py` i bezpieczny skrypt dołączenia modułu do istniejącego `app.py`, nawigacji, inicjalizacji SQLite i workflow GitHub Actions.

## Zastosowanie do repozytorium

1. Zrób kopię źródeł i danych Portable. **Nie uruchamiaj skryptu w katalogu rozpakowanego programu `.exe`.** Skrypt wymaga katalogu źródeł repozytorium GitHub, z plikiem `app.py`.
2. Rozpakuj tę paczkę i na komputerze z Pythonem wykonaj (podmień ścieżkę):

   ```bat
   py ZASTOSUJ_POPRAWKE.py "C:\sciezka\do\Kancelaria-RK"
   ```

3. W repo uruchom testy:

   ```bat
   cd /d "C:\sciezka\do\Kancelaria-RK"
   py TEST_INBOX_REVIEW.py
   py -m py_compile app.py rk_inbox.py
   ```

4. Sprawdź zmiany (`git diff`) i wyślij wyłącznie **pliki źródłowe**, nie bazę, OCR prawdziwych klientów ani backupy. Skrypt doda `.rk_inbox_patch_backups/` do `.gitignore`.
5. Utwórz nowy build przez **Actions → Build RK KANCELARIA Windows Portable → Run workflow**. Workflow uruchamia też testy skrzynki. Pobierz nowy artefakt `RK-KANCELARIA-WINDOWS-PORTABLE`.
6. Przed produkcyjnym użyciem wykonaj dodatkową próbę na kopii bazy, wczytaj skan i sprawdź, czy podgląd, OCR, zatwierdzanie, monity i terminy działają poprawnie w gotowym `EXE`.

## Zachowanie funkcji

- Z menu **Skrzynka wpływu** wgrywasz dokument (PDF, DOCX, obraz, TXT/RTF), maksymalnie 20 MB.
- Oryginał trafia do lokalnej, oczekującej kolejki `_inbox`. Program odczytuje tekst przez istniejący mechanizm OCR, podpowiada sygnatury i typ dokumentu oraz sugeruje zadania, monity i weryfikację terminów.
- Otwierasz oryginał i tekst OCR, **wybierasz sprawę ręcznie**, poprawiasz tytuł, typ, daty i proponowane zadania. Każdą pozycję można odznaczyć, zmienić lub dopisać nowe.
- Terminy jawnie podane w piśmie są rozpoznawane jako propozycja do **ręcznego obliczenia i potwierdzenia**. Program nie dopisuje żadnej domyślnej daty ani samoczynnie nie tworzy wpisu w kalendarzu.
- Dopiero końcowy formularz i zaznaczenie potwierdzenia powodują zapis dokumentu w kartotece, wybranych czynności, alertów (tylko dla czynności z datą) i historii/audytu.
- Odrzucenie usuwa roboczy plik. Próba podwójnego zatwierdzenia nie duplikuje dokumentu ani zadań.
- Nie ma zewnętrznych zapytań AI ani wysyłania treści dokumentów do usług online. OCR obrazów wymaga lokalnego Tesseracta, zgodnie z dotychczasową aplikacją.

## Granice rozwiązania

Reguły wykrywania są **heurystyczne**. Mogą przeoczyć niestandardowe sformułowanie albo potraktować cytat jako zobowiązanie. Nie ustalają biegu terminów według przepisów, nie rozpoznają wiarygodnie adresata zobowiązania i nie zastępują oceny prawnika. Ekran wymusza ręczny wybór sprawy i potwierdzenie kontroli, ale nie może zagwarantować poprawności tej kontroli.

**Status:** kod modułu i testy zostały sprawdzone lokalnie. Nie wykonano testów całego oryginalnego repozytorium ani builda Windows w tej sesji; po nałożeniu poprawki uruchom GitHub Actions i test na kopii danych.
