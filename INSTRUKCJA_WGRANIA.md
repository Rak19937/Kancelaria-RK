# RK KANCELARIA 0.3.4-dev1 — Centrum decyzji

## Zawartość paczki

| Plik | Miejsce w repozytorium GitHub |
|---|---|
| `rk_action_center.py` | główny katalog repozytorium |
| `ZASTOSUJ_OBIEG.py` | główny katalog repozytorium |
| `TEST_ACTION_CENTER.py` | główny katalog repozytorium |
| `TEST_AKTUALIZACJA_ZBIORCZA.py` | główny katalog repozytorium — **zastąpić** istniejący test |
| `.github/workflows/main.yml` | **właśnie ten katalog `.github/workflows/`** — zastąpić istniejący plik |

## Wgranie

1. **Nie modyfikuj obecnej wersji Portable i nie przenoś plików `Data`.** Zachowaj działającą wersję 0.3.3-dev1.
2. Otwórz repozytorium `Rak19937/Kancelaria-RK`, gałąź `main`.
3. Wgraj cztery pliki `.py` z paczki do **głównego katalogu repozytorium**, zastępując `TEST_AKTUALIZACJA_ZBIORCZA.py`. Zapisz commit.
4. W GitHubie wejdź do `.github/workflows/main.yml`. Zastąp **całą zawartość** zawartością pliku z paczki. Zapisz commit. **Nie wgrywaj `main.yml` do głównego katalogu repozytorium.**
5. Otwórz **Actions → Build RK KANCELARIA Windows Portable**, wybierz **najnowszy** przebieg (nie wcześniejszy uruchomiony po wgraniu czterech plików).
6. Po zielonym wyniku: **Artifacts → RK-KANCELARIA-WINDOWS-PORTABLE**. Nową paczkę rozpakuj do osobnego folderu.

## Co zmienia aktualizacja

- Nowy element menu **Centrum decyzji**: propozycje z dokumentów i projektów oraz oczekujące pisma ze Skrzynki wpływu.
- Na ekranach istniejących dokumentów i projektów pojawia się przycisk **Zaproponuj czynności**.
- Regułowe propozycje: sprawdzenie zobowiązań sądu, doręczeń, posiedzeń, płatności, mediacji, opinii biegłych i literalnych wzmianek o terminach.
- Możliwość edytowania opisów, rodzaju i priorytetu; wpisania źródła, dat i sposobu obliczenia; dodawania propozycji ręcznie, odrzucenia albo zatwierdzenia.
- Zapis zadania wyłącznie po zaznaczeniu propozycji i świadomym zatwierdzeniu; historia działań zachowana.
- **Brak automatycznego liczenia terminów.** Przy wyborze „Termin procesowy” program wymaga ręcznie zweryfikowanych dat początkowej i końcowej, podstawy i sposobu obliczenia.
- Jeśli dokument zmieni się po analizie, zatwierdzenie zostanie zablokowane do ponownej analizy.
- Migracja tworzy nowe tabele i zwiększa schemat SQLite do **325**. Integrator **nie dotyka danych użytkownika** na GitHubie; uruchamiany EXE doda tabele po uruchomieniu na danej bazie.

## Ograniczenia

To **lokalny silnik regułowy**, a nie językowy model AI czy samodzielna analiza prawna. Nie rozstrzyga o dopuszczalności środka zaskarżenia, nie oblicza terminu procesowego, nie wysyła korespondencji, nie wystawia monitów automatycznie. Dla nagrań nie zgaduje transkrypcji, a skany wymagają OCR. Gdy tekst nie jest dostępny, pokazuje propozycję ręcznej analizy.

Pierwsze testy najlepiej wykonać na przykładowej sprawie w **oddzielnym folderze Portable**. Dopiero po ich pomyślnym wyniku i wykonaniu pełnego backupu rozważ podłączenie bazy rzeczywistej.

**Testy lokalne:** `python TEST_ACTION_CENTER.py` (13 testów); pełny build Windows i testy integracyjne są wykonywane po commitach w Actions.
