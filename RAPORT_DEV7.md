# RK KANCELARIA — raport wykonanej stabilizacji dev7

**Podstawa:** `main` repozytorium `Rak19937/Kancelaria-RK` (ostatni sprawdzony commit `7ac4a5f13ffc56f93e55122fd5bf2ce420cc2b21`, z poprawką UX6). 
**Zakres:** etap 1 planu stabilizacji prywatnej aplikacji Windows.

## Zaimplementowane poprawki

1. **Usuwanie spraw** — testowe usunięcie w transakcyjnym `SAVEPOINT` z bezwarunkowym wycofaniem; komunikat o tabelach blokujących; wstrzymanie przy wyłączonej kontroli kluczy obcych.
2. **Weryfikacja backupu przed kasowaniem** — kontrola kompletności zapisu, identyczności SHA-256 pliku, zawartości ZIP-a i manifestu, sum wszystkich plików oraz limitów przywracania.
3. **Potwierdzenie integralności SQLite po DELETE** — kontrola FK przed zatwierdzeniem transakcji; usuwanie katalogów plików następuje dopiero po zakończeniu transakcji.
4. **Formularze spraw** — walidacja nazwy, statusu, daty i przedmiotu nowej sprawy; czytelna informacja o błędzie zamiast zapisu nieprawidłowych danych.
5. **Kalendarz dnia** — odwołane i zakończone terminy nie są pokazywane wśród planowanych spotkań.
6. **Obsługa błędów POST** — usunięto nieuzasadnioną obietnicę, że wyjątek na pewno nie zmienił danych; użytkownik otrzymuje bezpieczne wskazanie, by sprawdzić stan przed ponowną próbą.
7. **Instalator fail-closed** — sprawdza wersję i precyzyjne punkty modyfikacji, analizuje składnię, obsługuje `--dry-run` i `--verify`, zachowuje kopie oraz odtwarza kod po błędzie zapisu.

## Kontrole

- **22 lokalne testy jednostkowe i regresyjne:** zaliczone (SQLite i dokumenty testowe, bez danych klientów).
- Identyczność bazowego `rk_ux6.py` z GitHub: sprawdzona na podstawie Git blob SHA-1 `cb987b0a6fb040dd7900b7b78969bc99ef5544dc`.
- Punkty instalacji w aktualnym `app.py`: sprawdzone tekstowo na GitHubie.
- Workflow: walidacja składni YAML lokalnie.
- **Nie wykonano jeszcze:** kompilacji Windows i wszystkich testów repozytorium po zastosowaniu tej paczki — wykona je GitHub Actions po wgraniu.

## Znane ograniczenia

- Bez kopii realnej bazy użytkownika nie można potwierdzić przyczyny wcześniejszej awarii usuwania konkretnej sprawy.
- Preflight nie usuwa wymogu administracyjnego konta ani zasady wcześniejszego zakończenia sprawy.
- Gwarantujemy wykrycie wielu błędów integralności snapshotu, nie pełne przetestowanie przywracania na innym komputerze.
- `VERSION` pozostaje `0.4.0-dev5`, a DEV7 jest oznaczeniem pakietu stabilizacyjnego; nie zmieniano wszystkich historycznych skryptów zależnych od wersji.
- Następne etapy stabilizacji nadal pozostają do wykonania.
