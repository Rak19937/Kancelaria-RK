# RK KANCELARIA 0.4.0-dev3 — Nowa nawigacja i moduły LegalTech

**Status: wydanie rozwojowe / testowe.** Punkt startowy: `0.4.0-dev2`, commit `3e683c3ab27edb17b27114851f8cf370693c0e94`.

## Jak wgrać na GitHub

Rozpakuj całą paczkę i wgraj pliki do głównego katalogu `Rak19937/Kancelaria-RK`, zachowując foldery:

- Główny katalog: `ZASTOSUJ_040_DEV3.py`, `rk_dev3.py`, `rk_dev3_core.py`, `rk_dev3_calendar.py`, `TEST_RK_DEV3.py`, `TEST_MIGRATOR_040_DEV3.py`.
- `assets/`: `rk_dev3_nav.js` i `rk_dev3_nav.css`.
- `.github/workflows/main.yml`: **zastąp aktywny workflow** w tej lokalizacji (nie plik `main.yml` w korzeniu).
- Dokumentacja `.md` jest opcjonalna, ale zalecana.

Zapisz wszystkie pliki **w jednym commicie**. GitHub Actions najpierw zastosuje migrator dev3, przeprowadzi testy, zbuduje EXE i uruchomi self-test. Przy pozytywnym wyniku umieści paczkę w artefakcie `RK-KANCELARIA-WINDOWS-PORTABLE`.

**Nie przenoś katalogu `Data` do GitHub.** Po kompilacji utwórz nowy katalog Portable, a do testowania wykorzystaj kopię istniejących danych. Zachowaj oryginalną wersję Portable z jej `Data` jako niezależny backup. Migracja bazy podnosi `user_version` do **331**, więc powrót do dev2 na tej samej bazie bez przywrócenia kopii nie jest wspierany.

### Tryb lokalny migratora

W katalogu pełnych źródeł:

```powershell
python ZASTOSUJ_040_DEV3.py . --dry-run
python ZASTOSUJ_040_DEV3.py .
python ZASTOSUJ_040_DEV3.py . --verify
python TEST_RK_DEV3.py
python TEST_MIGRATOR_040_DEV3.py
```

Migrator jest idempotentny, tworzy kopię zmienianych **źródeł** w `.rk_backup_before_040_dev3`, nie otwiera i nie modyfikuje `Data`. Same nowe tabele zostaną utworzone przy pierwszym uruchomieniu programu.

## Funkcje dostępne po instalacji

1. **Wysuwana lewa nawigacja:** wąski pasek ikon, rozwijanie po najechaniu lub focusie, przycisk pinezki, wyszukiwarka pozycji, skrót `Alt+M`; bez przesuwania głównej części ekranu.
2. **Etapy spraw:** nowa zakładka „Etapy postępowań”, etapy od przyjęcia do egzekucji, osobna historia zmian. Istniejące statusy spraw pozostają bez zmian.
3. **Czas pracy:** stoper przypisany do sprawy i zalogowanego pracownika, rejestr ręczny, stawki PLN/h, czas nierozliczalny, CSV dla klienta. Jeden aktywny stoper na pracownika. Wpisy zaokrąglają czas stopera do pełnej rozpoczętej minuty.
4. **Sejf dokumentów:** **nowa, oddzielna przestrzeń** na pliki AES-256-GCM, indywidualne hasło min. 12 znaków i dostęp właściciela lub upoważnionych użytkowników. Pliki przechowywane w `Data/dokumenty/_vault`, więc są objęte dotychczasową kopią dokumentów. Hasło **nie jest przechowywane ani odzyskiwane**.
5. **Google Calendar / Outlook:** ręczna, dwukierunkowa wymiana wydarzeń — pobranie jako propozycje do przypisania do sprawy i świadome wysłanie wybranego terminu. Przed każdą operacją wymagany jest ważny OAuth. Domyślnie tytuł sprawy **nie jest przesyłany** do zewnętrznego kalendarza.
6. **Portal Informacyjny:** kontrolowany import ręcznie wyeksportowanej listy CSV (UTF-8) i powiązanie jej ze sprawą. Żadna pozycja nie jest automatycznie traktowana jako doręczenie ani używana do wyliczenia terminu.

## Konfiguracja Google Calendar i Outlook

Funkcja synchronizacji z zewnętrznym kalendarzem **nie uruchamia się bez autoryzacji OAuth** i świadomego polecenia administratora. Program nie przechowuje tokenów OAuth w bazie; dostarcz je przez bezpieczne zmienne środowiskowe procesu aplikacji.

Google: `RK_GOOGLE_CLIENT_ID`, `RK_GOOGLE_REFRESH_TOKEN`, opcjonalnie `RK_GOOGLE_CLIENT_SECRET`, `RK_GOOGLE_CALENDAR_ID` (domyślnie `primary`). Zakres OAuth z prawem odczytu/zapisu wydarzeń: `https://www.googleapis.com/auth/calendar.events`.

Outlook: `RK_MS_CLIENT_ID`, `RK_MS_REFRESH_TOKEN`, opcjonalnie `RK_MS_TENANT` (domyślnie `common`). Delegowany zakres OAuth: `offline_access Calendars.ReadWrite`.

**To są wymagania konfiguracji aplikacji OAuth należącej do kancelarii.** Paczka nie zawiera interaktywnego kreatora pierwszej zgody OAuth ani poświadczeń. Potrzebne jest wcześniejsze uzyskanie refresh tokenów przez autoryzowany klient OAuth. Nigdy nie wgrywaj haseł ani tokenów do repozytorium czy publicznych workflow GitHub.

Wydarzenia zewnętrzne są propozycjami. Po zatwierdzeniu stają się terminami w `case_appointments`, a ich identyfikatory zapisują się w `dev3_calendar_links`. Przy aktualizacji wydarzenia po stronie API jest używany `ETag` (jeśli zwrócony), co zapobiega części przypadków niejawnego nadpisania. Nie jest to jeszcze automatyczna synchronizacja w tle.

## Integracja z Portalem Informacyjnym Sądów Powszechnych

Wskazanie funkcjonalności API w komunikatach NRA **nie zastępuje** uzyskania dokumentacji, uprawnień i wymaganej konfiguracji. Ten patch **nie wykonuje automatycznego logowania, pobierania pism ani odbioru doręczeń**; nie używa scrapingu i nie obchodzi ograniczeń portalu.

Do ręcznego importu CSV przygotuj kolumny:

`identyfikator;sygnatura;data;tytul;opis`

Taki import nie stanowi dowodu doręczenia. Data doręczenia i bieg terminów muszą być sprawdzone w oficjalnym Portalu.

## Ograniczenia bezpieczeństwa

- Sejf szyfruje **nowo dodawane pliki sejfu**, a nie automatycznie całą dotychczasową bazę i katalog `Data/dokumenty`. Dotychczasowy mechanizm dostępu do zwykłych dokumentów **nie otrzymuje pełnego ACL** w tym wydaniu. Nie używaj testowej dev3 jako potwierdzenia pełnej izolacji wszystkich spraw między użytkownikami.
- Tytuł i przypisanie pliku sejfu do sprawy pozostają metadanymi w lokalnym SQLite. Poufna treść dokumentu jest zaszyfrowana.
- Zapomnianego hasła sejfu nie da się odzyskać z programu. Sprawdź procedurę bezpiecznego przechowywania haseł przed wprowadzeniem danych produkcyjnych.
- Nie było testu integracyjnego z rzeczywistymi kontami Google, Microsoft ani sądowymi portalami. Przed użyciem produkcyjnym konieczne są testy na odizolowanych kontach i dokumentach.
- Program wspomaga organizację pracy i **nie zastępuje weryfikacji terminów przez prawnika**.
