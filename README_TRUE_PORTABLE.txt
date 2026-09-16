RK KANCELARIA 0.3.0-dev1 — SMART CASE & LAW / TRUE PORTABLE

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


DEV8 — OFFICE SUITE & CLOUD FOUNDATION
- Dokumenty 2.0: statusy, daty wpływu/doręczenia, nadawca, autor, tagi, zadanie/termin, podgląd i naprawa pliku.
- Oś czasu 2.0: dokumenty, zadania, notatki, projekty i zdarzenia w jednym widoku.
- Projekty pism: szablony z polami sprawy, historia wersji i przywracanie.
- Recovery: 30 kopii, pełny integrity_check, pełny snapshot baza+dokumenty+projekty.
- PWA + Cloud Bridge: bezpieczne, wersjonowane snapshoty z blokadą konfliktu; opcjonalny backend PostgreSQL.


DEV9 — UX & DESIGN REFRESH
- treść przed formularzem i uproszczone ekrany,
- aktywny zegar na pulpicie,
- jasny przedmiot sprawy na pierwszym planie,
- status wykonania z datą i autorem,
- oddzielna Historia procesu, Historia sprawy i Historia zmian,
- prostszy sidebar, onboarding, tryb kompaktowy i lepsza responsywność.
