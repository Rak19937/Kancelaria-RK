# RK KANCELARIA — poprawka GitHub Actions dla 0.3.10-dev1

Przygotowano na podstawie repozytorium `Rak19937/Kancelaria-RK`, gałąź `main`, którego kod aplikacji w chwili przeglądu miał wersję **0.3.8-dev1**, choć pliki modułów 0.3.10 były już w repozytorium.

## Do repozytorium wrzuć TYLKO dwa pliki

| Plik z paczki | Gdzie ma trafić w repozytorium |
|---|---|
| `ZASTOSUJ_AKTUALIZACJE.py` | `ZASTOSUJ_AKTUALIZACJE.py` — katalog główny, **zastąp istniejący** |
| `.github/workflows/main.yml` | `.github/workflows/main.yml` — katalog workflow, **zastąp istniejący** |

Instrukcję (`INSTRUKCJA_WRZUCENIA.md`) zachowaj dla siebie; nie jest wymagana w repozytorium.

## Wgrywanie w przeglądarce GitHub

1. Otwórz `https://github.com/Rak19937/Kancelaria-RK` (gałąź **main**).
2. Otwórz `ZASTOSUJ_AKTUALIZACJE.py`, kliknij ołówek **Edit this file**. Zastąp **całą zawartość** zawartością nowego pliku o tej samej nazwie. Kliknij **Commit changes**.
3. Otwórz `.github/workflows/main.yml`, kliknij ołówek. Zastąp **całą zawartość** zawartością nowego `main.yml`. Kliknij **Commit changes**. Ten drugi commit uruchomi właściwy workflow 0.3.10.
4. Otwórz zakładkę **Actions** → **Build RK KANCELARIA Windows Portable** i sprawdź, czy krok **Aktywuj RK KANCELARIA 0.3.10 - UX i architektura** jest zielony, a potem czy zielone są testy i budowanie EXE.
5. Po sukcesie sprawdź w `app.py` na gałęzi `main` napis `VERSION = "0.3.10-dev1"` (workflow zapisuje poprawione źródła na `main` przy push). Dopiero wtedy pobierz artefakt **RK-KANCELARIA-WINDOWS-PORTABLE**.

**Nie wrzucaj ZIP-u jako pojedynczego pliku do `main`.** Rozpakuj go i użyj dwóch plików z odpowiednich ścieżek. Nie wrzucaj `Data`, baz SQLite ani dokumentów klientów na GitHub.

## Co zostało poprawione

- Wcześniejszy instalator przerywał aktualizację, jeśli pliki nowych modułów istniały już w `main`. Teraz porównuje zawartość i akceptuje tylko dokładnie zgodne pliki; nieznane wersje nadal blokuje.
- `main.yml` uruchamia instalator 0.3.10 **przed testami i budowaniem EXE**, zamiast bezwarunkowo uruchamiać stare integratory.
- GitHub Actions uruchamia pełen wcześniejszy zestaw testów, testy UX/architektury i test instalacji, a po sukcesie zapisuje do `main` także poprawione `rk_caseflow.py`, JavaScript oraz testy. Nie zapisuje `Data`.
- Ponowne uruchomienie na poprawnej wersji 0.3.10 niczego nie nadpisuje.

## Ograniczenia

Zmiany zostały przetestowane lokalnie na syntetycznych źródłach i przykładowych danych. Nie uruchomiono tu pełnego builda Windows. Rzeczywisty wynik GitHub Actions należy sprawdzić po wgraniu obu plików. Sam zielony workflow nie zastępuje testu nowego EXE na kopii bazy kancelarii.
