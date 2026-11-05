# RK KANCELARIA — 0.3.8-dev1

Aktualizacja obejmuje: uproszczoną nawigację i wyszukiwanie, zależności zadań,
centralne Centrum dowodowe, teczki dokumentów i pełną oś chronologiczną sprawy.

## Wymagane źródła

Repozytorium GitHub: `Rak19937/Kancelaria-RK`, gałąź `main`.
Stan wyjściowy: **0.3.7-dev1 / SCHEMA_VERSION=329**.

## Wgraj TYLKO cztery pliki Python do katalogu głównego

- `rk_caseflow.py`
- `ZASTOSUJ_CASEFLOW.py`
- `TEST_CASEFLOW.py`
- `TEST_INTEGRACJA_CASEFLOW.py`

Zastąp plik `.github/workflows/main.yml` z tej paczki w **tej samej ścieżce** na GitHubie.
Pozostałe pliki `.md` są do czytania i nie są wymagane w repozytorium.

## Uruchomienie

1. Zatwierdź nowe pliki (Commit changes) w `main`.
2. Otwórz `https://github.com/Rak19937/Kancelaria-RK/actions`.
3. Sprawdź najnowszy przebieg **z krokiem „Teczki, zależności, dowody i chronologia 0.3.8-dev1”**.
4. Zielony wynik potwierdza integrację i kompilację. Na dole kliknij `Artifacts` → `RK-KANCELARIA-WINDOWS-PORTABLE`.
5. Rozpakuj nowy ZIP do osobnego katalogu. Nie nadpisuj dotychczasowego `Data` ani działającego Portable bez kopii.
6. Przetestuj na kopii bazy; szczegółowe kroki są w `TESTY_MANUALNE.md`.

## Zasady bezpieczeństwa i zakres

- Skrypt nie otwiera i nie zmienia katalogu `Data`, bazy ani dokumentów. Zmienia wyłącznie `app.py` i `README.md` w drzewie źródeł.
- Migracja SQLite (schemat 330) wykonuje się przy uruchomieniu nowego EXE, a nie podczas budowania ZIP-a na GitHubie.
- Nowe zależności między zadaniami są jawnie wskazywane przez użytkownika; program nie wylicza prawa procesowego i nie ocenia ważności dokumentów.
- Standardowe wykonanie zadania mającego niespełnione zależności wymaga osobnego, uzasadnionego potwierdzenia.
- Centrum dowodowe czyta już istniejące `case_assertions` i `case_evidence`, nie tworzy drugiej bazy.
- `Dokumenty` pokazują na starcie wybór sprawy. Po wyborze wyświetlają dokumenty tylko tej sprawy i dokumenty jawnie z nią współdzielone.
- Oś sprawy używa dat merytorycznych (`doc_date`, `received_date`, `delivered_date`, `due_date`, `event_date`), odrębnie od dat audytu zmian. Przy braku jakiejkolwiek daty źródłowej dokument jest wyraźnie oznaczony jako dodany według daty wprowadzenia.
- **Nie wgrywaj pojedynczych modułów z wcześniejszego ZIP-a 0.3.7 ponownie** po przejściu na 0.3.8.
