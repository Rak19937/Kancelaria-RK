# RK KANCELARIA 0.4.0-dev2 — stabilizacja bezpieczeństwa i danych

Stan wejściowy: repozytorium `Rak19937/Kancelaria-RK`, `main`, `0.4.0-dev1`.
To **aktualizacja źródeł do GitHub Actions**, nie gotowy EXE. Bezpośrednie
zapisanie zmian do GitHub nie było możliwe z uwagi na prawa dostępu integracji.

## Wgrywanie (5 plików)

W repozytorium, w **katalogu głównym** dodaj lub nadpisz:

1. `ZASTOSUJ_040_DEV2.py`
2. `TEST_STABILIZACJA_040_DEV2.py`
3. `TEST_UI_HTTP_040_DEV2.py`
4. `TEST_MIGRATOR_040_DEV2.py`

**Jako ostatni plik**, nadpisz zawartość `.github/workflows/main.yml` plikiem z paczki.
Nie dodawaj katalogu `RK_KANCELARIA_040_DEV2` do repozytorium — wklej pliki do
wskazanych miejsc. Nowy workflow wykona preflight, instalację, wszystkie
starsze testy, testy dev2, kompilację EXE i test EXE na Windows.

Instalator tworzy/aktualizuje automatycznie `rk_core/*`, `rk_domains/*`,
`assets/rk_csrf.js` i skrypt odzyskania przerwanej synchronizacji. Przed
zapisywaniem źródeł sprawdza składnię całego zestawu, zapisuje kopie
zmienianego kodu w `.rk_backup_before_040_dev2`, a przy błędzie zapisu źródeł
wycofuje zmiany. **Nie dotyka `Data` ani baz użytkowników.**

## Co jest naprawiane

- **Synchronizacja:** `SCHEMA_VERSION` jest wspólny (330); synchronizacja
  zapisuje dziennik w `Data`, ma backup i próbuje wycofać wszystkie części
  stanu przy niepowodzeniu. Po nagłym przerwaniu operacji uruchomienie programu
  jest blokowane, by nie otwierać niespójnych danych.
- **Cloud:** klient wymaga HTTPS, z wyjątkiem lokalnego `localhost`;
  snapshot jest szyfrowany na komputerze użytkownika przez AES-256-GCM,
  przy użyciu **osobnego hasła wprowadzanego przy każdym transferze**;
  Cloud Bridge odmawia przyjęcia niezaszyfrowanych nowych snapshotów.
- **OCR:** trwała kolejka w lokalnym SQLite, nie blokuje żądania upload.
  Po restarcie ponawiane są przerwane zadania; użytkownik widzi status
  analizy i może ponowić błąd. Pismo nadal wymaga ręcznej weryfikacji.
- **Formaty:** dodany odczyt ODT, ODS, PPTX i EML (tekst); DOCX ma limit
  rozpakowania XML; stare binarne DOC, ZIP, audio/wideo można dołączyć, ale
  program jawnie informuje, że **nie przeprowadził transkrypcji**.
- **HTTP:** CSRF na chronionych formularzach POST i fetch, Origin/Referer,
  mniejszy limit żądań (64 MB), ochrona WebSocket sesją, nagłówki przeglądarki,
  dodatkowe sprawdzanie administratora przy pobieraniu surowej bazy,
  trwałym usuwaniu i odblokowaniu zamkniętych spraw.
- **Architektura:** wydzielona inicjalizacja bazy (`rk_core/schema.py`),
  osobne komponenty bezpieczeństwa, Cloud, synchronizacji i kolejki OCR.
- **Testy:** 7 testów jednostkowych nowych mechanizmów, 2 testy migratora,
  dodatkowy rzeczywisty test HTTP przez działający proces aplikacji na
  syntetycznej bazie, oraz cały wcześniejszy zestaw testów.

## WAŻNE: Cloud i stary serwer

Nowy klient i nowy Cloud Bridge **muszą mieć zgodne wersje**. Jeśli masz
uruchomiony serwer `rk_cloud_server.py` poza repo, wdrożenie go trzeba wykonać
osobno. Stare **niezaszyfrowane** snapshoty na serwerze nie są automatycznie
migrowane i nie można ich odczytać przez nową ścieżkę szyfrowania.
**Przed aktualizacją Cloud zachowaj starą bezpieczną kopię i plan jej
odtworzenia.** Każdy komputer musi używać tego samego hasła szyfrowania
snapshotów; utrata hasła uniemożliwi odszyfrowanie kopii. Hasło nie jest
zapisywane w bazie ani przesyłane do Cloud Bridge. W dostępie przez LAN
używaj HTTPS/VPN, nie zwykłego HTTP.

## Gdy pojawi się dziennik niedokończonej synchronizacji

Nie uruchamiaj ani Installed, ani Portable. Zachowaj pełną dodatkową kopię
katalogu `Data` w oddzielnym miejscu. Dziennik
`Data/.rk_sync_incomplete.json` zawiera ścieżkę do backupu.
W repozytorium źródłowym (z zainstalowanym Pythonem):

```powershell
python ODZYSKAJ_SYNCHRONIZACJE_040.py "D:\\RK_KANCELARIA_DATA"
python ODZYSKAJ_SYNCHRONIZACJE_040.py "D:\\RK_KANCELARIA_DATA" --restore
```

Druga komenda przywraca **poprzednią** bazę i katalogi z dokumentami.
Zewnętrzny backup powinien zostać zachowany także po przywróceniu.
Przerwanie zasilania w trakcie wieloplikowej synchronizacji nie może być
zwykłą atomową transakcją systemu plików; dziennik i fail-closed są konieczne.

## Przed użyciem z rzeczywistymi sprawami

1. Pobierz Portable wyłącznie z **zielonego najnowszego** uruchomienia Actions.
2. Uruchom go z **kopią** katalogu `Data`, nie z oryginałem.
3. Sprawdź logowanie, otwarcie spraw, dokumenty, zadania, terminy, upload
   tekstowego pliku do skrzynki wpływu, OCR skanu PDF, zatwierdzenie oraz
   synchronizację Installed ↔ Portable (na kopiach).
4. Upewnij się, że potrafisz przywrócić backup, i zachowaj poprzednią działającą
   wersję programu.

## Granice zapewnień

Lokalnie sprawdzono 7 testów bezpieczeństwa/rollback/OCR i 2 testy migratora
na syntetycznych danych. **Nie** wykonano jeszcze pełnego uruchomienia tej
aktualizacji na rzeczywistym repo i Windows Portable — to zrobi GitHub Actions
po przesłaniu plików. Pozostają duże metody interfejsu w `app.py`; przeniesienie
całego UI do niezależnych modułów oraz pełne automatyczne testy kliknięć
Qt WebEngine wymagają kolejnych prac i nie są deklarowane jako zakończone.
