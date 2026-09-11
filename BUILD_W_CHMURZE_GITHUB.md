# RK KANCELARIA — build Windows bez kompilowania na Twoim komputerze

Ta wersja ma gotowy workflow GitHub Actions. Kompilacja odbywa się na prawdziwym Windowsie w chmurze GitHub, więc na Twoim komputerze nie musi być Python, PyInstaller ani Visual Studio.

## Najprościej
1. Utwórz prywatne repozytorium na GitHub.
2. Wgraj do niego całą zawartość tego katalogu (koniecznie również folder `.github`).
3. Wejdź w zakładkę **Actions**.
4. Wybierz **Build RK KANCELARIA Windows Portable**.
5. Kliknij **Run workflow**.
6. Po zakończeniu otwórz wykonany workflow i pobierz artefakt **RK-KANCELARIA-WINDOWS-PORTABLE**.
7. Rozpakuj ZIP. W środku jest `RK KANCELARIA.exe` oraz `_internal`, `Data` i `portable.flag`.
8. Cały rozpakowany katalog można przenieść na komputer bez zainstalowanego Pythona.

## Co workflow robi automatycznie
- uruchamia Windows x64;
- instaluje Python 3.13 tylko na maszynie budującej GitHub;
- instaluje wymagane biblioteki;
- wykonuje test źródeł i test ścieżek portable;
- buduje program przez PyInstaller w trybie `onedir`;
- uruchamia self-test już z gotowego `RK KANCELARIA.exe`;
- dopiero po poprawnym teście tworzy finalny ZIP.

## Ważne
`onedir` oznacza, że nie należy kopiować samego EXE. Należy przenosić cały katalog `RK KANCELARIA PORTABLE`, ponieważ `_internal` zawiera interpreter Pythona, Qt i pozostałe biblioteki.

Na służbowym komputerze nadal mogą zadziałać polityki bezpieczeństwa Windows/Defender/AppLocker blokujące niepodpisane programy. To nie jest brak Pythona — to osobna blokada administracyjna.
