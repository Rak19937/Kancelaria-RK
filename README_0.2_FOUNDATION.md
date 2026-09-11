# RK KANCELARIA 0.2.0-dev1 — Foundation

Ta paczka jest **gałęzią rozwojową** stabilnej 0.15.2. Nie zastępuje jeszcze 0.15.2 jako wydania produkcyjnego.

## Co zmieniono

- wydzielono centralną warstwę ścieżek do `rk_paths.py`,
- zachowano dotychczasowy tryb Installed i katalog danych użytkownika,
- dodano fundament trybu Portable: plik `portable.flag` obok programu kieruje dane do `Data\`,
- `SPRAWNIK_DATA_DIR` nadal ma najwyższy priorytet (LAN, testy, konfiguracje specjalne),
- Desktop pokazuje oznaczenie `Portable` w tytule okna, gdy ten tryb jest aktywny,
- instalator korzysta z tej samej centralnej logiki ścieżek,
- dodano bezpieczną diagnostykę `DIAGNOSTYKA_0.2.py`.

## Czego ta wersja jeszcze NIE robi

- nie jest jeszcze prawdziwym portable EXE z własnym niezależnym runtime,
- nie synchronizuje automatycznie Installed ↔ Portable,
- nie migruje jeszcze rekordów na UUID,
- klucz zaszyfrowanych backupów w Windows nadal opiera się na dotychczasowym DPAPI,
- nie wykonano jeszcze strukturalnego podziału `app.py` na `database.py`, `documents.py`, `backup.py` i `sync.py`.

## Zasada bezpieczeństwa

0.15.2 pozostaje wersją odniesienia. Rozwój 0.2 ma być wykonywany etapami i dopiero po testach regresji może zastąpić wersję stabilną.
