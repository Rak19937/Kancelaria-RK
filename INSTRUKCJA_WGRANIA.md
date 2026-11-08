# RK KANCELARIA — stabilizacja dev5 i audyt całego repozytorium

**Punkt odniesienia:** repozytorium `Rak19937/Kancelaria-RK`, gałąź `main`, commit `1be024b092c75e310d165e292809a7ed7667ce34` (8 listopada 2026 r.).

## Co wgrać

Paczka zawiera komplet współpracujących skryptów dev5, ale większość jest już na GitHubie. **Wystarczy dodać lub zastąpić pięć plików:**

| Ścieżka w GitHub | Operacja |
|---|---|
| `ZASTOSUJ_040_DEV5_PELNA.py` | zastąpić w katalogu głównym |
| `RK_DEV5_AUDYT_REPO.py` | dodać do katalogu głównego |
| `TEST_RK_DEV5_CI.py` | dodać do katalogu głównego |
| `.github/workflows/main.yml` | zastąpić w katalogu `.github/workflows/` |
| `.github/workflows/aktualizacja-dev5.yml` | zastąpić w katalogu `.github/workflows/` |

Pozostałe pliki `.py` są częścią pełnej paczki na wypadek potrzeby odtworzenia wcześniejszej aktualizacji. Nie wgrywaj ich ponownie, jeśli już znajdują się w repozytorium.

**Nie przesyłaj samego ZIP-a do katalogu głównego GitHub.** Rozpakuj go; pliki muszą trafić do wskazanych katalogów. W szczególności dwóch plików YAML **nie** wolno umieszczać w głównym katalogu.

### Zalecana kolejność w serwisie GitHub

1. Wgraj trzy pliki `.py` do katalogu głównego i zatwierdź. Przejściowy czerwony wynik starego workflow `dev4` może się jeszcze pojawić — nie uruchamiaj „Re-run” dla starego przebiegu.
2. Otwórz `.github/workflows/` i zastąp **oba** pliki YAML. Najlepiej zatwierdź je razem jednym commitem.
3. Po tym commicie nowy `RK KANCELARIA - automatyczna naprawa DEV5 i Portable` uruchomi się automatycznie. Nie trzeba ręcznie uruchamiać starszego skryptu.
4. W `Actions` sprawdź wszystkie etapy: zastosowanie dev5, testy regresyjne, audyt całego repo, budowę Portable, test EXE i `git push` do `main`.
5. Gotowy ZIP znajduje się w artefaktach runu `RK-KANCELARIA-DEV5-PORTABLE`. Raport statyczny jest w `RK-DEV5-RAPORTY-I-LOGI` jako `RAPORT_DEV5_AUDYT_REPO.json`.

Jeśli podczas wgrywania plików YAML dojdzie do **dwóch osobnych commitów**, wcześniejszy może dać przejściowy czerwony wynik. Ostateczny status oceniaj po uruchomieniu na commicie zawierającym **oba** poprawione workflow.

## Jak działa naprawa

- Stary `main.yml` z dev4 nie uruchamia się już na każdą zmianę: jest wyłącznie ręcznym wejściem do nowego workflow.
- Główny workflow aktualizuje źródła dev4 do dev5, robi `--dry-run`, testy, pełny audyt, buduje EXE oraz udostępnia ZIP **przed** ewentualnym `git push`.
- Bot zapisuje **wyłącznie pliki źródłowe i testy**. Nie próbuje zapisywać `.github/workflows/main.yml` — GitHub odrzucał to bez uprawnienia `workflows`.
- W aktualizowanym `app.py` kontrola POST dev5 trafia do istniejącego bloku obsługi wyjątków, zamiast wykonywać się poza nim.
- Nowy `RK_DEV5_AUDYT_REPO.py` przegląda wszystkie źródła Pythona, kontroluje składnię, zduplikowane definicje, wybrane ryzykowne idiomy, śledzone pliki potencjalnie poufne oraz konflikty konfiguracji workflow.
- Znane niezgodności testów dev4/dev5 dotyczące sejfu i globalnej skrzynki wpływu pozostają naprawione w aktualizatorze.

## Bezpieczeństwo i ograniczenia

- Pakiet **nie** zawiera bazy `Data`, dokumentów klientów ani haseł.
- **Zrób oddzielną kopię aktualnego folderu Portable i `Data` przed uruchomieniem nowej wersji**. Nie podmieniaj danych działającego programu bez kopii.
- Sam zielony wynik CI **nie potwierdza** pełnego bezpieczeństwa, działania każdej ścieżki UI ani poprawnej pracy integracji Google/Outlook w rzeczywistym środowisku. Wrażliwe dane klientów wymagają dodatkowych prób na kopii testowej i kontroli uprawnień.
- Statyczne sygnały `high`/`medium` w raporcie nie są automatycznie dowodem exploita; błędy `critical` blokują build. Nie usuwamy zabezpieczeń tylko po to, aby testy przechodziły.
- W razie odmowy `git push` z innego powodu (np. ochrona gałęzi `main`) zaproponowany program jest już dostępny w artefakcie, ale **nie oznacza to, że źródła zostały zapisane na `main`**.

Zobacz również `RAPORT_AUDYTU_DEV5.md` oraz `MANIFEST_SHA256.txt` w paczce.
