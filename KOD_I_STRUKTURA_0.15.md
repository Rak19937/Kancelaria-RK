# RK KANCELARIA 0.15 — mapa kodu

Ta wersja celowo nie robi ryzykownego pełnego refaktoru backendu przed 1.0.
Największą poprawą utrzymania kodu jest wydzielenie wspólnej warstwy frontendu z `app.py`.

- `app.py` — backend HTTP, SQLite i funkcje kancelaryjne.
- `assets/rk_app.css` — wspólne style interfejsu.
- `assets/rk_app.js` — autosave, skróty i wspólne zachowania frontendu.
- `desktop.py` — natywne okno Qt, start/stop backendu, backup przy zamknięciu.
- `install_desktop.py` — izolowane środowisko Runtime.
- `ocr_setup.py` — opcjonalny OCR.
- `utworz_skrot.py` — skrót Windows bez konsoli.

## Zasada dalszego rozwoju

Przed rozbijaniem `app.py` na wiele modułów najpierw utrzymywać testy regresji dokumentów,
backup/recovery i głównych ekranów. Refaktor strukturalny najlepiej robić osobno, bez dokładania
w tym samym kroku nowych funkcji użytkowych. Dzięki temu łatwo wskazać źródło regresji.
