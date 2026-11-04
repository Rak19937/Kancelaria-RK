# RK KANCELARIA 0.3.3-dev1 — wspólny podgląd załączników

Aktualizacja **nakłada się na sprawdzoną wersję 0.3.2-dev1**. NIE kopiuj ZIP bezpośrednio do katalogu `Data`. Oryginały dokumentów, projekty i baza SQLite pozostają bez zmian.

## Dokładne wgranie przez stronę GitHub

Repozytorium: `Rak19937/Kancelaria-RK`, gałąź `main`.

1. Rozpakuj ten ZIP na komputerze.
2. W **głównym katalogu repozytorium**, przez `Add file` → `Upload files`, wgraj **TRZY** pliki Python (obok `app.py`):
   - `rk_unified_preview.py` — obsługa formatów i bezpieczne strumieniowanie;
   - `ZASTOSUJ_PODGLAD.py` — jednorazowy, idempotentny integrator;
   - `TEST_UNIFIED_PREVIEW.py` — dodatkowe testy.
3. Zatwierdź zmiany (`Commit changes`). **Może wystartować stary workflow** — wynik tej przejściowej kompilacji nie jest wynikiem aktualizacji podglądu.
4. W GitHubie otwórz **`.github/workflows/main.yml`** (wewnątrz folderu `.github/workflows`, **NIE `main.yml` w katalogu głównym**). Kliknij ołówek i **zastąp całą zawartość** tekstem pliku `.github/workflows/main.yml` z tej paczki. Zatwierdź `Commit changes`.
5. Otwórz zakładkę `Actions`. W nowym przebiegu mają pojawić się kroki **`Zintegruj lokalny podglad zalacznikow`** i test **`TEST_UNIFIED_PREVIEW.py`**. Po zielonym przebiegu pobierz artefakt `RK-KANCELARIA-WINDOWS-PORTABLE`.
6. Rozpakuj na próbę do osobnego folderu, bez podmieniania używanego na co dzień Portable. Przetestuj na niesensytywnych plikach.

## Obsługiwane podglądy

- **PDF**: wyświetlanie stron, nawigacja i powiększanie; wszystkie trzy moduły.
- **Word DOCX**: czytelny podgląd akapitów, pogrubień, nagłówków i tabel (bez gwarancji identycznej paginacji, przypisów i obrazów Worda). **Starszy DOC**: informacja o ograniczeniu + oryginał do otwarcia.
- **ODT, RTF, TXT, MD, CSV, JSON, XML, EML**: bezpieczny podgląd tekstu; HTML nigdy nie jest wykonywany jako strona.
- **Excel XLSX/XLSM, ODS**: tabele (limit 4 arkusze, 120 wierszy i 18 kolumn); bez wykonywania makr/formuł.
- **PowerPoint PPTX**: tekst slajdów, nie pełna grafika.
- **Obrazy**: PNG, JPG/JPEG, GIF, WebP, BMP oraz TIFF (lokalna konwersja do PNG).
- **Audio**: MP3, WAV, OGG/OGA, M4A, AAC, FLAC, OPUS, WMA. Odtwarzanie wbudowane zależy od kodeków dostępnych w Qt/Windows.
- **Wideo**: MP4/M4V, WebM, MOV, AVI, MKV, WMV, MPEG/MPG. Największą zgodność mają MP4 (H.264/AAC) i WebM; inne pliki pozostają dostępne jako oryginały.
- **ZIP**: bezpieczny spis plików, bez ich rozpakowywania.
- **Inne formaty**: komunikat i pobranie oryginału.

## Ograniczenia i bezpieczeństwo

- Podgląd jest **lokalny**, nie wymaga Microsoft Office ani usług chmurowych. Oryginały nie są modyfikowane, a do nowych podglądów nie są dodawane kopie do bazy.
- Przeglądarka w oknie programu pobiera fragmenty pliku lokalnie w celu wyświetlenia/odtworzenia; nie oznacza to ręcznego zapisywania drugiej kopii na dysku.
- Obowiązuje dotychczasowy limit formularza serwera: **256 MB** na żądanie, a w `Skrzynce wpływu` **20 MB** na plik. Duże filmy nie mogą być importowane tą metodą bez osobnej aktualizacji mechanizmu uploadu.
- Testów Python jest 10 i przeszły lokalnie. Przed opublikowaniem nie wykonano pełnej kompilacji EXE ani pełnego testu manualnego na Windows — potwierdzi je dopiero GitHub Actions.
- Nie dodawaj rzeczywistych akt, nagrań i danych klientów do repozytorium GitHub. Pliki spraw mają pozostać w lokalnym `Data`.

## W razie błędu kompilacji

W `Actions` → nieudany przebieg → krok z czerwonym `X` → skopiuj 20–40 ostatnich linii logu. Błąd kompilacji nie oznacza usunięcia danych lokalnych. Gdy nowy workflow działa poprawnie, zapisuje zintegrowane `app.py` i `rk_inbox.py` do `main` (gdy uprawnienia repozytorium na to pozwalają).
