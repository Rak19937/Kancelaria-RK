RK KANCELARIA 0.2.0-dev2 — PORTABLE

Dane tej kopii są przechowywane w folderze Data obok programu.

PIERWSZE URUCHOMIENIE NA DANYM KOMPUTERZE:
- uruchom START_PORTABLE.bat albo RK KANCELARIA DESKTOP.bat;
- jeżeli lokalne .venv nie działa, launcher uruchomi przygotowanie komponentów Desktop;
- wymagany jest Python 3.10-3.14 x64 na danym komputerze.

SYNCHRONIZACJA:
- gdy istnieje Installed, Portable synchronizuje się z nią przed startem;
- po zamknięciu synchronizuje zmiany z powrotem;
- przy zmianach po obu stronach synchronizator zgłasza konflikt zamiast cicho nadpisywać dane;
- przed nadpisaniem powstaje pełny backup celu (maks. 10 ostatnich backupów synchronizacji);
- ręcznie: SYNCHRONIZUJ.bat / SYNCHRONIZUJ.vbs.

WAŻNE:
Ta paczka ma przenośny kod i dane, ale nie zawiera jeszcze wbudowanego samodzielnego runtime Windows.
Na nowym komputerze wymaga Pythona i jednorazowego utworzenia/naprawy lokalnego .venv w folderze Portable.
