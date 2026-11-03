# RK KANCELARIA 0.3.1-dev1 — aktualizacja do wgrania na GitHub

Repozytorium: https://github.com/Rak19937/Kancelaria-RK  
Punkt wyjścia: wersja portable / źródła z 17 września 2026 r.

## Jak wgrać bez Pythona i bez Git na swoim komputerze

1. **Rozpakuj ZIP** na pulpicie.
2. Otwórz repozytorium na GitHub, gałąź **main**.
3. Wybierz **Add file → Upload files**.
4. Przeciągnij **zawartość rozpakowanego folderu**, razem z ukrytym katalogiem `.github` i jego podfolderem `workflows` (zachowaj dokładne ścieżki). Nie wgrywaj samego ZIP-a.
5. Zatwierdź zmiany przyciskiem **Commit changes**. Istniejący `.github/workflows/main.yml` ma zostać zastąpiony nowym.
6. Otwórz **Actions → Build RK KANCELARIA Windows Portable**. Po commitcie build powinien uruchomić się sam. Jeśli nie, kliknij **Run workflow**, wybierz `main`.
7. Gdy cały build będzie oznaczony na zielono, pobierz artefakt **RK-KANCELARIA-WINDOWS-PORTABLE**.
8. Rozpakuj artefakt jako **nowy folder** obok starej wersji. Nie usuwaj dotychczasowej wersji ani jej `Data`.

## Co robi automatycznie GitHub Actions?

- Podłącza `rk_inbox.py` do istniejącego `app.py` w środowisku budowania.
- Wykonuje dotychczasowe testy i 13 nowych testów Skrzynki wpływu.
- Próbuje zapisać zaktualizowany `app.py` i `README.md` na `main` (jeśli GitHub pozwala na zapis automatyczny).
- Buduje nowy ZIP portable z przyciskiem **Skrzynka wpływu**.

Jeśli repo blokuje automatyczny zapis do `main`, gotowy EXE **nadal będzie zawierać moduł**, bo patch jest nakładany przed kompilacją. Kod `app.py` w repo może pozostać w starej wersji; ponowne uruchomienie workflow znów dołączy moduł na potrzeby builda. Przeglądaj logi Actions, jeśli chcesz potwierdzić zapis źródeł.

## Ochrona danych

Nie wgrywaj na GitHub bazy `sprawnik.sqlite3`, folderu `Data`, dokumentów klientów, backupów ani prawdziwych pism. Repozytorium jest publiczne.

Testy na macOS/Linux i testy logiczne **nie są** testami gotowego EXE na Windows. Zanim zaczniesz używać programu na rzeczywistych danych, zrób kopię starego katalogu i przetestuj nową wersję na **kopii danych**. Nigdy nie podmieniaj samego EXE: potrzebny jest cały folder portable razem z `_internal`.

## Funkcje

Wgrywanie pisma, lokalny OCR, możliwa sygnatura, propozycje zadań, monitów i terminów, edycja/odrzucanie każdej propozycji oraz zatwierdzanie przed zapisaniem. Daty terminów nie są obliczane automatycznie.
