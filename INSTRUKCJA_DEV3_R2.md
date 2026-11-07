# RK KANCELARIA 0.4.0-dev3 — poprawki ergonomii R2

Paczka zawiera wyłącznie zmienione pliki i niezależne testy. **Nie zastępuje całego programu ani folderu Data**. Podstawą jest działająca kompilacja `0.4.0-dev3` z repozytorium `Rak19937/Kancelaria-RK`.

## Instalacja przez GitHub

1. Zachowaj kopię obecnej wersji Portable wraz z jej katalogiem `Data` na prywatnym nośniku.
2. Rozpakuj tę paczkę. **Zachowując ścieżki**, wgraj pięć plików z paczki do głównego katalogu repozytorium (dwa pliki JS/CSS muszą trafić do `assets/`). Do repozytorium możesz też wgrać instrukcję i plan testów.
3. W GitHub `main` użyj jednego commita, np. `RK KANCELARIA dev3 R2: sidebar and workflow fixes`. Nie wgrywaj do GitHub żadnych rzeczywistych akt, danych osobowych, bazy SQLite ani sekretów OAuth.
4. Poczekaj na finalny wynik GitHub Actions (wszystkie testy, build Windows EXE i self-test). Nie zastępuj stabilnej instalacji, jeśli workflow się zatrzyma.
5. Rozpakuj nową paczkę Portable do **nowego katalogu**, uruchom na kopii danych i przejdź plan testów użytkowych.

## Zakres

- **Menu:** osobny stan `otwarte` i `przypięte`; ponowne kliknięcie pinezki lub przycisku ☰ zamyka menu bez konieczności przesuwania myszy; `Alt+M`, `Esc`, hover z opóźnieniem, filtrowanie grup menu; poprawione `aria-expanded` i `aria-pressed`.
- **Stoper:** odliczanie czasu na ekranie, przycisk anulowania bez zapisywania (z potwierdzeniem), dotychczasowy przycisk zatrzymania i zapisania bez zmian.
- **Sejf:** właściciel lub administrator może cofnąć wcześniej nadany dostęp do zaszyfrowanego pliku. Odszyfrowanie nadal wymaga hasła.
- **Kalendarz:** można odrzucić propozycję wydarzenia przed zapisaniem jej do sprawy. Nie zostanie ona dodana do kalendarza kancelarii.
- **Portal Informacyjny:** można skorygować przypisaną sprawę lub cofnąć oznaczenie ręcznie zaimportowanego wpisu jako zweryfikowanego.

## Czego paczka nie robi

- Nie zmienia tabel SQLite, wersji schematu (`331`) ani istniejących danych w `Data`.
- Nie wprowadza automatycznego pobierania doręczeń sądowych; nadal wymagałoby to oficjalnego dostępu API.
- Nie usuwa konieczności konfiguracji OAuth Google i Microsoft.
- Nie zastępuje przeglądu uprawnień do istniejących dokumentów poza odrębnym sejfem.
- Nie gwarantuje 100% poprawności całego programu. Testy nie zastępują manualnego przeglądu rzeczywistych ekranów na Windows.

## Testy

Automatycznie w GitHub Actions uruchomi się nowy `TEST_RK_DEV3_POLISH.py` wraz z dotychczasowymi plikami `TEST_*.py`. Test Node.js `TEST_NAV_DEV3_NODE.cjs` nie wymaga npm; wykonywany jest z testu Python (gdy Node jest dostępny). Ręcznie: `python TEST_RK_DEV3_POLISH.py`, `node TEST_NAV_DEV3_NODE.cjs`.

**Podpis EXE i alerty Avast:** ten patch dotyczy funkcjonalności i nie wyłącza ani nie obchodzi antywirusa. Ewentualne wykrycie analizować oddzielnie na podstawie nazwy alertu i hashy pliku.
