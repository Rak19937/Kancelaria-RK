# RK KANCELARIA 0.3.10-dev1 — JEDNA AKTUALIZACJA UX + ARCHITEKTURA

**Punkt wyjścia:** `Rak19937/Kancelaria-RK`, `main`, commit `d32bde00292adfc0ef118ae121b9a9af2f0e17a0` (wersja `0.3.8-dev1`).

Paczka jest **jednym instalatorem aktualizacji źródeł**, a nie samodzielnym plikiem EXE. Zawiera komplet zmian UX z poprzednich paczek 0.3.9 oraz pierwszą, nieinwazyjną refaktoryzację architektury. Jeżeli zainstalowano wcześniej UX 0.3.9-dev1/dev2, można przejść bezpośrednio do 0.3.10-dev1. **Nie trzeba nakładać starszych ZIP-ów.**

## Co zmienia się w programie

- „Moja praca”: wygodniejszy pulpit z widokiem skoncentrowanym na codziennych zadaniach.
- **Ctrl+F** uruchamia wyszukiwanie RK KANCELARIA (zamiast Ctrl+K); działa też `/` poza formularzami. **Ctrl+F przejmuje standardowe wyszukiwanie przeglądarki**, zgodnie z życzeniem użytkownika.
- Podgląd dokumentu otrzymuje panel pracy z tej samej sprawy i szybkie dodanie zadania.
- Chronologia ma filtry, zależności zyskują czytelny ciąg czynności.
- Menu „Więcej” jest zwijane; uproszczony widok i gęstość są preferencjami przeglądarki (bez przenoszenia danych spraw).

## Jak uporządkowano kod

- `rk_navigation.py`: wspólna definicja menu i rendering nawigacji; usunięto powielanie definicji z `layout()`.
- `rk_routes.py`: rejestr **36 prostych tras GET** i **20 tras POST**. Pozostałe trasy dynamiczne są nadal obsługiwane w `app.py`.
- `rk_dashboard_data.py`: odczyty SQL pulpitu oddzielone od prezentacji HTML.
- `rk_search_data.py`: zapytania wyszukiwarki nawigacyjnej oddzielone od widoku.
- `rk_document_data.py`: pobieranie zadań na panel dokumentu oddzielone od budowania HTML w `rk_ux.py`.
- Dostosowano trzy historyczne testy wymagające dosłownej obecności tras/menu w `app.py` i dodano nowe testy regresyjne. Zmieniono CI Windows, by je uruchamiało przed budową.

**Granica tej aktualizacji:** nie jest to przepisanie wszystkich 7551 linii `app.py`. Metody parametryczne i duże formularze pozostają w starej implementacji do późniejszych etapów, żeby nie łączyć zmiany architektury ze zmianą zasad biznesowych.

## Instalacja na Windows — źródła, NIE katalog gotowego Portable EXE

1. Zamknij RK KANCELARIA i zrób osobną kopię katalogu `Data` oraz źródeł repozytorium.
2. Rozpakuj **całą paczkę** do oddzielnego folderu, np. `C:\RK_AKTUALIZACJA`. Nie kopiuj plików paczki do `Data`.
3. Otwórz wiersz polecenia w folderze rozpakowanej paczki i sprawdź zgodność:

   ```bat
   py ZASTOSUJ_AKTUALIZACJE.py "C:\SCIEZKA\Kancelaria-RK" --dry-run
   ```

4. Jeśli kontrola się powiedzie, zainstaluj:

   ```bat
   py ZASTOSUJ_AKTUALIZACJE.py "C:\SCIEZKA\Kancelaria-RK"
   ```

   Instalator najpierw sprawdza wersję i kotwice kodu, kompiluje zmieniane moduły Python, a dopiero później zapisuje pliki. Poprzednie źródła trafiają do `C:\SCIEZKA\Kancelaria-RK\.rk_backup_before_0310`. Katalog `Data` nie jest czytany ani modyfikowany przez instalator.

5. Uruchom przynajmniej testy modułów oraz dotychczasowe testy regresji w katalogu repozytorium:

   ```bat
   cd /d "C:\SCIEZKA\Kancelaria-RK"
   py TEST_UX_039.py
   py TEST_ARCHITEKTURA_0310.py
   py TEST_STABILIZACJA.py
   py TEST_AKTUALIZACJA_ZBIORCZA.py
   py TEST_UI_PERFORMANCE_DEV4.py
   py TEST_CASEFLOW.py
   py TEST_DOCUMENT_HUB.py
   ```

6. Wykonaj pozostałe testy repozytorium i kompilację Windows Portable przez GitHub Actions. **Na końcu przetestuj gotowy EXE na kopii bazy**, szczególnie otwarcie sprawy, odczyt dokumentu, utworzenie zadania, terminarz, formularze i obsługę kont bez uprawnień administratora.

## Wgranie do GitHub

Aktualizacja **nie została wgrana automatycznie**; połączenie GitHub wcześniej zwracało `403 Resource not accessible by integration`. Po przejściu testów można zapisać zmiany ze źródłowego folderu repozytorium:

```bat
cd /d "C:\SCIEZKA\Kancelaria-RK"
git status
git add app.py rk_caseflow.py rk_ux.py rk_navigation.py rk_routes.py rk_dashboard_data.py rk_search_data.py rk_document_data.py assets/rk_app.js assets/rk_ux.js assets/rk_ux.css TEST_UX_039.py TEST_ARCHITEKTURA_0310.py TEST_STABILIZACJA.py TEST_AKTUALIZACJA_ZBIORCZA.py TEST_UI_PERFORMANCE_DEV4.py .github/workflows/main.yml
git commit -m "RK KANCELARIA 0.3.10-dev1: UX and architecture refactor"
git push origin main
```

Nie używaj `git add .`, jeśli katalog repozytorium zawiera rzeczywiste akta, OCR, `Data` albo kopie bezpieczeństwa. Najbezpieczniej pracować w osobnej gałęzi i scalić dopiero po pozytywnych testach.

## Wycofanie aktualizacji

Otwórz folder paczki i uruchom:

```bat
py PRZYWROC_0310.py "C:\SCIEZKA\Kancelaria-RK"
py PRZYWROC_0310.py "C:\SCIEZKA\Kancelaria-RK" --restore
```

Pierwsze polecenie tylko wyświetla plan. Drugie przywraca pliki istniejące przed aktualizacją i usuwa nowe moduły wyłącznie, jeśli nie zostały później zmodyfikowane. Katalog `Data` pozostaje nietknięty. Jeśli od czasu aktualizacji ręcznie edytowano pliki źródłowe, przygotuj osobną kopię przed wycofaniem.

## Wynik kontroli paczki

- Lokalnie: kompilacja skryptów Python i składnia JavaScript; testy nowego routera, nawigacji, odczytów SQL, wyszukiwania oraz instalacji i wycofania na **syntetycznych** źródłach/bazach.
- Zabezpieczenie: identyfikacja commita bazowego i kontrola blobów, zatrzymanie przed zmianą plików przy niezgodności.
- **Nie wykonano** w tej sesji pełnego zestawu testów oryginalnego repozytorium ani builda Windows Portable; ich wykonanie jest warunkiem uznania aktualizacji za produkcyjnie sprawdzoną.

Szczegóły techniczne i następne etapy: `RAPORT_ARCHITEKTURA.md`.
