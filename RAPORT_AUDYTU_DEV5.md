# RK KANCELARIA — analiza błędów i plan naprawy dev5

**Stan danych z GitHub sprawdzony 8 listopada 2026 r.** Repozytorium: 212 śledzonych plików, 126 źródeł `.py`/`.pyw` (ok. 1,69 MB źródeł Pythona), `app.py` ok. 579 KB. Podczas ostatniego udanego etapu migracji GitHub Actions przeprowadził zestawy testów i kompilację, lecz **nie zapisał** dev5 na `main`.

## Potwierdzone usterki i ich rozwiązanie

| Priorytet | Plik / obszar | Dowód i objaw | Działanie w tej paczce |
|---|---|---|---|
| Krytyczny dla wydania | `.github/workflows/aktualizacja-dev5.yml` | Run #42439858578, błąd `refusing to allow a GitHub App to create or update workflow .github/workflows/main.yml without workflows permission` | Ominięcie workflow podczas patchowania i usunięcie go z `git add`; pliki YAML modyfikuje wyłącznie użytkownik |
| Wysoki dla CI | `.github/workflows/main.yml` i `aktualizacja-dev5.yml` | Po jednym commicie startowały dwa konkurencyjne buildy: dev4 i dev5, a stare testy dev5 na źródłach dev4 kończyły się błędem | Jeden automatyczny workflow dev5; `main.yml` wyłącznie na żądanie |
| Średni / obsługa HTTP | `ZASTOSUJ_040_DEV5_PELNA.py` → `app.py` | Sprawdzenie POST nowych uprawnień było wstawiane poza głównym blokiem `try` w `do_POST` | Przeniesienie wstrzykniętej kontroli do istniejącej obsługi błędów żądań |
| Średni / testy zgodności | `TEST_RK_DEV4.py` | Run #42439248334: `sqlite3.OperationalError: no such table: dev5_vault_journal` w starej bazie testowej | Wcześniejsza poprawka zachowana: test inicjuje nowy schemat sejfu |
| Średni / testy zgodności | `TEST_UI_HTTP_040_DEV2.py` | Run #42439248334: stary test oczekiwał HTTP 200 dla globalnej skrzynki zwykłego użytkownika | Wcześniejsza poprawka zachowana: oczekiwane 403 i dostęp do `/my-cases` |
| Niski / Windows | CI Python | Run #42436125424: `charmap codec can't encode character \u0142` | Ustawienie UTF-8 w istniejącym i nowym workflow; w ostatnim runie ten etap przeszedł |

**Potwierdzona zielona część runu #42439858578:** migracja źródeł do dev5, zestawy dev5, pełny audyt testowy dotychczasowego repozytorium, kompilacja Windows Portable, self-test EXE i udostępnienie artefaktu. Czerwony wynik pochodził z ostatniego `git push`.

## Ryzyka wymagające oddzielnej walidacji

1. `app.py` jest dużym, silnie zintegrowanym modułem. Testy regresji nie dowodzą poprawności każdej trasy HTTP i każdego widoku desktopowego. Zaplanować rozbicie na mniejsze, audytowalne komponenty.
2. `rk_sync.py`: synchronizacja bazy, załączników i operacje zastępowania katalogów wymagają testów awarii zasilania, blokad plików i równoczesnego działania wielu użytkowników na kopiach testowych.
3. `rk_cloud_server.py`: początkowe tworzenie jednego rekordu `office_id` przy dwóch równoczesnych zapisach może wymagać serializacji operacji oraz testów integracyjnych PostgreSQL. Nie wdrożono niezweryfikowanej zmiany schematu Cloud.
4. `rk_dev5_acl.py`: stare widoki dla zwykłych użytkowników są celowo blokowane. Nie należy przywracać globalnego dostępu bez pełnych kontroli uprawnień na poziomie rekordów. Nie sprawdzono ręcznie każdego ekranu i każdej interakcji na Windows.
5. `rk_dev5_calendar_reconcile.py`: integracje z realnym Google/Outlook, odwołania terminów, letni/zimowy czas i paginacja wymagają prób z prawdziwymi usługami; automatyzacja nie powinna samodzielnie zmieniać terminów sądowych.
6. Szyfrowanie, kopie archiwalne i sejf: sprawdzić odtwarzanie z kopii na drugim urządzeniu, limity zasobów, brak haseł i kont użytkowników w logach.
7. Program Portable nie ma gwarancji akceptacji przez Avast i inne antywirusy; brak podpisu Authenticode nie jest problemem, który można legalnie „ukryć” zmianą kodu.
8. W repozytorium występują historyczne pliki kompilacyjne `__pycache__` i osobny `main.yml` w katalogu głównym. Nowy audyt zgłasza je jako techniczny porządek do wykonania, nie jako błąd runtime.

## Zakres weryfikacji

- Odczytano drzewo repozytorium, konfigurację budowy, logi najnowszych przebiegów GitHub Actions oraz wybrane moduły bezpieczeństwa, Cloud, bazę, sejf i kalendarz.
- Dotychczasowe CI w runie #42439858578 wykonało testy i audyt składni całego kodu Python po migracji dev5, zakończone powodzeniem przed `git push`.
- Lokalnie sprawdzono składnię skryptów pakietu, poprawność obu YAML i pięć dodatkowych testów kontrolnych.
- **Nie przeprowadzono niezależnego wykonania wszystkich 126 modułów** ani audytu rzeczywistych danych klientów. Nowy plik `RK_DEV5_AUDYT_REPO.py` wykona przegląd statyczny wszystkich źródeł **na GitHubie po wgraniu** i udostępni szczegółowy raport JSON.

**Granica rzetelności:** sformułowanie „każdy możliwy błąd” jest technicznie nieweryfikowalne dla dowolnego niebanalnego programu. Usterki potwierdzone i blokujące wydanie naprawiono w opisywanej aktualizacji; pozostające ryzyka są nazwane, a nowe kontrole mają wykrywać regresje zamiast po cichu publikować wadliwe źródła.

### Źródła weryfikacji
- https://github.com/Rak19937/Kancelaria-RK/actions/runs/42439858578
- https://github.com/Rak19937/Kancelaria-RK/actions/runs/42439248334
- https://github.com/Rak19937/Kancelaria-RK/actions/runs/42436125424
