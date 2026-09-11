RK KANCELARIA 0.2.0-dev3 — TRUE PORTABLE

CEL
Gotowy build działa na Windows x64 bez zainstalowanego Pythona, pip i bibliotek.
Python oraz wszystkie zależności są zamknięte przez PyInstaller w katalogu _internal.

JAK ZBUDOWAĆ
1. Na prywatnym komputerze Windows z Pythonem 3.11–3.13 x64 rozpakuj tę paczkę.
2. Uruchom ZBUDUJ_PRAWDZIWE_PORTABLE.bat.
3. Skrypt utworzy folder: dist\RK KANCELARIA PORTABLE\
4. Przenieś CAŁY ten folder na docelowy komputer.
5. Uruchom RK KANCELARIA.exe.

NA KOMPUTERZE DOCELOWYM NIE TRZEBA
- instalować Pythona,
- uruchamiać pip,
- instalować PySide6,
- instalować RK KANCELARIA.

DANE PORTABLE
Baza, dokumenty i backupy są zapisywane w folderze Data obok RK KANCELARIA.exe.
Znacznik portable.flag musi pozostać obok EXE.

WAŻNE
- Nie kopiuj samego RK KANCELARIA.exe. Potrzebny jest cały katalog razem z _internal.
- Windows Defender / AppLocker / polityka firmowa może zablokować niepodpisany program.
  To nie oznacza braku Pythona — jest to osobna polityka bezpieczeństwa Windows/firmy.
- OCR nadal wymaga silnika Tesseract, jeżeli na komputerze docelowym chcesz wykonywać OCR.
  Sam podgląd PDF i zwykła praca aplikacji nie wymagają Tesseracta.

TRYB AWARYJNY
Jeżeli Qt WebEngine ma problem ze sterownikiem grafiki, uruchom TRYB_BEZPIECZNY.bat.

SYNCHRONIZACJA
SYNCHRONIZUJ.bat uruchamia okno synchronizacji Installed <-> Portable za pomocą tego samego EXE.
