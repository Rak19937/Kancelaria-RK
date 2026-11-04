# RK KANCELARIA 0.3.2-dev1 — instrukcja zbiorczej aktualizacji

**Paczka zastępuje wcześniejszy ZIP stabilizacyjny 0.3.1 i osobny skrypt czyszczący. Nie trzeba wgrywać wcześniejszych paczek.**

Punkt wyjścia: `Rak19937/Kancelaria-RK`, gałąź `main` z 4 listopada 2026 r. Pierwotną bazą rozwojową projektu była wersja Portable z 17 września 2026 r.; źródła `main` są w wersji 0.3.0-dev6 i zawierają osobno `rk_inbox.py` oraz `AKTUALIZUJ_KOD.py`. Zbiorcza aktualizacja wykorzystuje te istniejące pliki.

## Co zawiera aktualizacja

1. **Skrzynka wpływu** — uruchomienie istniejącego modułu `rk_inbox.py` i weryfikacja człowieka przed zapisaniem propozycji czynności.
2. **Pełnomocnictwa** — osobny rejestr dokumentów, mocodawców, pełnomocników, zakresu, dat i statusów; wpis rejestru opiera się na dokumencie już zapisanym w sprawie. Można go zmienić albo usunąć z rejestru bez kasowania pliku.
3. **Wiele spraw — jeden dokument** — tabela powiązań `document_case_links`: jedna kopia fizyczna dokumentu, wiele powiązanych spraw. Karta sprawy pokazuje dokumenty współdzielone. Strona dokumentu ma przycisk „Powiązania spraw”. Globalny katalog ma osobną sekcję współdzielonych dokumentów.
4. **Bezpieczne usuwanie** — brak możliwości przypadkowego skasowania dokumentu współdzielonego lub jego sprawy źródłowej bez wcześniejszego usunięcia powiązań. Odłączenie z dodatkowej sprawy nie usuwa oryginału.
5. **Wyszukiwanie** — dotychczasowa wyszukiwarka działa nadal, a trafienie dokumentu prowadzi bezpośrednio do jego podglądu. Rejestr pełnomocnictw ma własne pole wyszukiwania.
6. **Neutralne przykłady** — usunięcie rzeczywistych przykładów z formularza nowej sprawy, pola tagów oraz opcjonalnego zbioru demonstracyjnego; **nie usuwamy rzeczywistych wpisów z bazy użytkownika**.
7. **O programie i warunki korzystania** — widok o autorze, `LICENSE.txt`, aktualizacja README.
8. **Testy** — istniejące regresje programu, testy nowego katalogu, kontrola połączeń modułów i self-test Portable.

## Jak wgrać na GitHub — jeden pakiet

1. **Najpierw rozważ ustawienie repozytorium na PRIVATE.** W publicznej historii projektu są starsze przykłady oparte na rzeczywistych sprawach; oczyszczenie bieżącego kodu **nie usuwa historii Git**.
2. Rozpakuj ten ZIP. **Nie wrzucaj samego ZIP-a na `main`.**
3. Do głównego katalogu repozytorium `Rak19937/Kancelaria-RK` wgraj wszystkie poniższe pliki, zachowując ich nazwy:
   - `RK_AKTUALIZACJA_ZBIORCZA.py`
   - `RK_STABILIZACJA.py`
   - `RK_WYCZYSC_PODPOWIEDZI.py`
   - `rk_document_hub.py`
   - `TEST_STABILIZACJA.py`
   - `TEST_DOCUMENT_HUB.py`
   - `TEST_AKTUALIZACJA_ZBIORCZA.py`
   - `LICENSE.txt`
4. Otwórz istniejący `.github/workflows/main.yml` na GitHubie i **zamień całą jego treść** treścią pliku o tej samej ścieżce z archiwum. Nie myl go z `main.yml` w katalogu głównym.
5. Zatwierdź przesłane zmiany na `main`. Uruchomi się workflow **Build RK KANCELARIA Windows Portable**. Integrator wykona poprawki podczas jednego przebiegu; nie trzeba osobno uruchamiać skryptów z poprzedniej paczki.
6. Workflow spróbuje zapisać przetestowany i oczyszczony kod `app.py` oraz `README.md` do `main`. Jeżeli GitHub zablokuje zapis, kompilacja może się nadal udać, **ale kod źródłowy na `main` zostanie stary**. Sprawdź log tego kroku i ostatni commit.
7. Tylko jeśli wszystkie testy i kompilacja zakończą się sukcesem, pobierz z **Actions → Artifacts** paczkę `RK-KANCELARIA-WINDOWS-PORTABLE`.

## Bardzo ważne: wersja na laptopie i dane

- **Nie podmieniaj na razie wersji używanej na laptopie.** Nowy ZIP to wersja testowa.
- Przed uruchomieniem nowej wersji zachowaj poza testowanym katalogiem niezależną kopię całego folderu `Data` (baza, pliki, kopie).
- Testuj na osobnej kopii programu z odrębnym folderem `Data` i wyłącznie na danych fikcyjnych.
- Skrypt aktualizacyjny modyfikuje źródła (`app.py` i `README.md`), a nie dane klientów.
- Nowe tabele SQLite powstają przy pierwszym uruchomieniu nowszej wersji; starszy program nie musi rozumieć ich semantyki. **Nie zakładaj, że obie wersje mogą bezpiecznie pracować równolegle na jednej bazie.**
- Dopiero po udanych testach działania, powiązań i odtwarzania kopii można rozważyć zamianę wersji.

## Ważne ograniczenia

- Pełnomocnictwo dodajemy **najpierw do dokumentów wybranej sprawy**, potem wybieramy je w rejestrze „Pełnomocnictwa”. To nadal ten sam fizyczny plik.
- Połączenie ze sprawą **nie stwierdza automatycznie umocowania** w tej sprawie — prawnik musi zweryfikować zakres pełnomocnictwa.
- Współdzielone dokumenty pojawią się w głównym widoku karty sprawy i oddzielnej sekcji globalnego katalogu; starsze alternatywne widoki mogą nadal pokazywać tylko dokumenty źródłowe.
- Nie dodajemy AI ani funkcji oceny strategii procesowej.
- Testy w tym ZIP nie zastępują kompilacji na Windows i ręcznych testów aplikacji.
