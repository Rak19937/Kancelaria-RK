# RK KANCELARIA 0.4.0-dev2 — hotfix testów po podziale schematu

Dotyczy nieudanego GitHub Actions: https://github.com/Rak19937/Kancelaria-RK/actions/runs/42223670328

Przyczyna: `TEST_STABILIZACJA.py` szukał wywołania `ensure_inbox_schema(con)` w `app.py`, mimo że w dev2 właściwa logika została wydzielona do `rk_core/schema.py`. Drugi test `TEST_AKTUALIZACJA_ZBIORCZA.py` zawiera podobne nieaktualne założenie, a `TEST_ARCHITEKTURA_040.py` sprawdzał na sztywno wcześniejszą wersję dev1.

## Wgranie

Wgraj do katalogu GŁÓWNEGO repozytorium (nadpisując):
- `TEST_STABILIZACJA.py`
- `TEST_AKTUALIZACJA_ZBIORCZA.py`
- `TEST_ARCHITEKTURA_040.py`

Nie zmieniaj `.github/workflows/main.yml`, instalatora dev2 ani istniejących katalogów danych. Po commit GitHub Actions uruchomi instalator dev2, testy i próbę budowania Portable.

## Co zmieniono

Testy nadal kontrolują klasę Handler, rejestr tras, wpięcie modułów, nazwy funkcji i wywołania `ensure_*`. Teraz sprawdzają je we właściwych plikach: `app.py` oraz `rk_core/schema.py`.

Test architektury porównuje wersję `0.4.0-dev2`, zachowując wszystkie pozostałe testy (m.in. transakcje, multipart, OCR, przepływ skrzynki, daty).

## Weryfikacja

- Sprawdzono składnię trzech plików (`py_compile`).
- Porównano bazowy `TEST_ARCHITEKTURA_040.py` z dokładnym SHA pliku na GitHub: `0da71151a9b203d8e68bf272a052ab7954c22fcf`.
- Sprawdzono na podstawie instalatora dev2, że przeniesiona inicjalizacja zawiera wymagane wywołania, a `app.py` deleguje do `initialize_database`.

Uwaga: po wcześniejszym błędzie CI zatrzymało się na TEST_STABILIZACJA.py. Dalsze testy i Windows EXE jeszcze nie zostały zweryfikowane w bieżącym runie. Kolejny run pokaże pełny wynik.
