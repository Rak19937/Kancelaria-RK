# RK KANCELARIA — dev5 FULL (pakiet naprawczy)

**Bazowy kod:** `Rak19937/Kancelaria-RK`, commit `661612a318bffa0f61b3e8db6b6ab63992fbe21a`, `0.4.0-dev4` (8 listopada 2026 r.).

**Stan wydania:** pakiet źródłowy do zastosowania w GitHub Actions; **nie jest gotowym EXE**. W tej rozmowie integracja GitHub odmówiła utworzenia gałęzi (HTTP 403), więc nie zmieniono `main`. Tutejsze testy wykonano na danych syntetycznych; **pełna kompilacja Windows i testy repozytorium muszą jeszcze przejść w GitHub Actions**. Nie używaj jeszcze do produkcyjnej obsługi rzeczywistych danych klientów bez sprawdzenia wyniku i kopii zapasowej.

## Co wgrać

**Zawartość pakietu** (wgraj **pliki rozpakowane**, nie ZIP):

Do **głównego katalogu** repozytorium:

1. `ZASTOSUJ_040_DEV5.py` — pierwotny aktualizator (jego uruchomienie automatycznie przekazuje wykonanie do pełnej aktualizacji).
2. `rk_dev5_snapshot.py` — sumy kontrolne danych w archiwach.
3. `TEST_RK_DEV5.py` — poprzednie testy dev5, uzupełnione o nowy dziennik sejfu.
4. `ZASTOSUJ_040_DEV5_PELNA.py` — właściwy aktualizator łączący oba etapy w jednej operacji.
5. `rk_dev5_acl.py` — ograniczenie dostępu do spraw i dokumentów.
6. `rk_dev5_vault.py` — dziennik odzyskiwania po przerwaniu operacji sejfu.
7. `rk_dev5_calendar_reconcile.py` — propozycje aktualizacji/anulowania/wydarzeń nieodnalezionych.
8. `TEST_RK_DEV5_SECURITY.py` — testy izolacji spraw, sejfu i kalendarza.

Do katalogu **`.github/workflows/`**:

- `aktualizacja-dev5.yml` — jednorazowa aktualizacja na Windows, testy, budowanie EXE, a następnie commit przy sukcesie.

Plik `INSTRUKCJA_DEV5.md` jest dokumentacją — nie trzeba go wgrywać.

## Instalacja najprostszą drogą

1. Utwórz **pełną kopię** obecnego katalogu Portable, zwłaszcza `Data`, i zachowaj ją poza repozytorium. Nie wgrywaj dokumentów klientów do publicznego GitHuba.
2. Wgraj osiem plików Pythona do katalogu głównego GitHub przez `Add file → Upload files`; dodatkowo wgraj plik YAML do `.github/workflows/`.
3. W `Actions` wybierz **RK KANCELARIA - pelna naprawa dev5 (bezpieczny test)** i kliknij **Run workflow** na gałęzi `main`.
4. Workflow sprawdzi wersję dev4, wykona aktualizację **tylko plików źródłowych**, uruchomi testy dev5 i stare testy, zbuduje Portable i wykona self-test EXE **przed commitem**.
5. Dopiero po pełnym sukcesie workflow spróbuje zapisać zmiany na `main`. Główny workflow zbuduje następnie artefakt `RK-KANCELARIA-WINDOWS-PORTABLE` do pobrania w Actions.
6. Przed pierwszym uruchomieniem nowego Portable zachowaj kopię poprzedniej wersji i danych. Przy pierwszym starcie nowej wersji poczekaj na migrację schematu oraz ewentualne odzyskiwanie sejfu. Nie uruchamiaj równolegle dwóch kopii na tej samej bazie.

Jeśli workflow zgłasza **403 / Resource not accessible by integration** przy `git push`, sprawdź w `Settings → Actions → General → Workflow permissions` opcję `Read and write permissions`. Jeżeli obowiązuje ochrona `main`, wykonaj tę samą aktualizację w osobnej gałęzi i użyj pull requestu. **Nie obchodź testów ręcznym commitem w połowie operacji.**

## Alternatywa: lokalnie w checkout repozytorium

```powershell
git checkout -b fix/dev5-full
python ZASTOSUJ_040_DEV5_PELNA.py . --dry-run
python ZASTOSUJ_040_DEV5_PELNA.py .
python ZASTOSUJ_040_DEV5_PELNA.py . --verify
python TEST_RK_DEV5.py
python TEST_RK_DEV5_SECURITY.py
python AUDYT_I_TESTY_RK_040_DEV2.py --root . --out RAPORT_AUDYT_040_DEV2.json
python RK_KANCELARIA_DESKTOP.pyw --self-test
```

Powyższe polecenia uruchamiaj **na kopii źródeł dev4**, nie w katalogu działającej instalacji Portable i nie w folderze `Data`.

## Naprawy i zachowanie programu

### Ochrona danych

- Role i dezaktywacja konta są sprawdzane w bazie przy każdym żądaniu — bez 8-sekundowego cache dawnych uprawnień.
- Administrator może przypisywać sprawę użytkownikowi w `Sprawa → Uprawnienia`. Prowadzący sprawę automatycznie uzyskuje uprawnienia do niej. Nadany dostęp może być tylko do odczytu albo do ograniczonej edycji.
- Konta inne niż administrator korzystają z **oddzielnego, ograniczonego pulpitu** `/my-cases`. Mogą odczytywać przypisane sprawy, dokumenty, terminy i zadania; uprawnienie do edycji pozwala dodawać notatki i zmieniać status zadań.
- Istniejące, niezweryfikowane ekrany globalnych list, wyszukiwarki, eksportów, stare dokumentowe adresy i inne trasy są **blokowane dla kont zwykłych**, zamiast ujawniać sprawy innych klientów. To jest świadome ograniczenie funkcjonalne na rzecz poufności. **Nie oznacza jeszcze pełnego wdrożenia ACL we wszystkich starszych modułach.**
- Udostępnienie aplikacji w sieci wymaga HTTPS (`RK_HTTPS_PROXY=1` przy poprawnym reverse proxy). Instalacja lokalna nadal może działać na loopback.
- Pełny snapshot pobiera się po podaniu własnego hasła, a pliki mają SHA-256 w manifeście. Przy imporcie weryfikowane są sumy; stare snapshoty ZIP są dopuszczalne tylko w trybie zgodności.
- Jeżeli szyfrowanie **już skonfigurowanego** backupu dziennego się nie powiedzie, program nie tworzy po cichu jawnej kopii zamiast szyfrowanej.

### Sejf

- Operacje zmiany hasła i usuwania pliku zapisują **dziennik odzyskiwania**, którego status rozstrzyga po przerwaniu pracy, czy odtworzyć stary plik, czy dokończyć zatwierdzoną operację.
- Usunięcie konta jest blokowane, jeżeli konto nadal posiada pliki sejfu. Zapobiega to ich pozornemu przejęciu bez znajomości haseł; przed usunięciem trzeba rozwiązać kwestię dokumentów.
- Cofnięcie działania po błędzie logowania jest testowane; przerwanie przed zakończeniem operacji jest objęte procedurą wznowienia przy starcie.

### Kalendarz i inne poprawki

- Poprawiono granice zakresów pobierania według polskiego czasu zimowego i letniego.
- Identyfikatory prób publikacji ograniczają duplikację po awarii zapisu lokalnego.
- Brak ETag nie powoduje niechronionego nadpisania; dalsza operacja wymaga ustalenia wersji zdalnej.
- Zmiany i anulowania istniejących wydarzeń, a także ich brak w pełnym pobranym zakresie, mogą utworzyć **propozycję do ręcznej weryfikacji**. Nie kasują automatycznie terminów sądowych.
- Obsługa błędnego CSV, walidacja dat, adres portalu, historia korekt czasu, strony starszych wpisów czasu i wybór przyszłych terminów są objęte pierwotnym pakietem dev5.

## Granice naprawy / co nadal wymaga kontroli

1. **Wszystkie ekrany starego interfejsu dla zwykłych użytkowników** nie zostały przepisane pod ACL — są blokowane. Administrator ma dotychczasowe funkcjonalności. Rozszerzanie widoków użytkownika powinno następować stopniowo, razem z testami autoryzacji każdej trasy i każdej relacji między sprawami.
2. **Kalendarze:** dostępne jest pobieranie, publikacja i ręczne zatwierdzanie części zmian; to nie jest bezobsługowe pełne dwukierunkowe kopiowanie wydarzeń. Dodatkowo integracja wymaga skonfigurowania własnego OAuth — kreator nie jest dołączony.
3. **Kopie historyczne** `.sqlite3`, w tym kopia przed aktualizacją oraz kopie automatyczne powstałe przed ustawieniem klucza, mogą pozostać jawne. Skonfiguruj klucz w ekranie bezpieczeństwa programu; zabezpiecz dysk uprawnieniami systemowymi/BitLockerem i zadbaj o kopię klucza poza komputerem.
4. **Sejf:** hasła do poszczególnych plików nadal nie mają bezpiecznego centralnego mechanizmu odzyskiwania. Bez hasła nie można ich odszyfrować.
5. **Avast i inne AV:** brak gwarancji, że Portable przestanie wywoływać fałszywe alarmy. Budowanie bez UPX i metadane produktu to nie to samo co podpis certyfikatem Authenticode.
6. Nie przeprowadzono testu graficznego interfejsu na Twoim komputerze, integracji z prawdziwym Google/Outlook, testu obciążenia wielu użytkowników ani audytu niezależnego eksperta. Po udanym CI należy przeprowadzić ręczne próby na kopii danych.

## Testy wykonane przy przygotowaniu pakietu

- **13/13** testów w `TEST_RK_DEV5_SECURITY.py` na syntetycznej SQLite z izolowanymi odpowiednikami wybranych zależności — zaliczone.
- Przykładowy snapshot: prawidłowy manifest przechodzi weryfikację SHA-256, uszkodzony jest odrzucany.
- Zgodność kilkunastu kluczowych fragmentów źródeł z `main` sprawdzono przez GitHub; ich występowanie jest unikatowe.
- Składnia ośmiu skryptów Python w pakiecie została sprawdzona.
- **Nie zaliczono jeszcze** pełnego zestawu `TEST_RK_DEV5.py`, pozostałych testów źródeł repo, builda i self-testu rzeczywistego Windows EXE. Wymaga to uruchomienia przygotowanego workflow.

**Zasada bezpieczeństwa:** nie pomijaj testów, nie wgrywaj zmian bezpośrednio do działającej instalacji i nie korzystaj z publicznego GitHuba do przechowywania bazy klientów.
