# RK KANCELARIA — raport architektury po 0.3.10-dev1

**Źródło:** aktualny `main` z 5 listopada 2026, `d32bde00292adfc0ef118ae121b9a9af2f0e17a0`. **Ocena:** przegląd kodu i kontrola opracowanego instalatora; nie pełny audyt bezpieczeństwa.

## Co rzeczywiście poprawiono

| Odpowiedzialność | Przed aktualizacją | Po aktualizacji |
|---|---|---|
| Definicja menu | Konstrukcja w `layout()` w `app.py` | Jedna definicja w `rk_navigation.py`, bez zmian adresów URL |
| Proste trasy HTTP | Kilkadziesiąt `if path ==` w `do_GET` i `do_POST` | 36 tras GET i 20 POST w rejestrze `rk_routes.py`, wywoływanym po istniejącej kontroli logowania/odczytu |
| Pulpit | SQL i HTML w jednej metodzie | SQL w `rk_dashboard_data.py`, HTML pozostał w oryginalnym widoku |
| Przejście do sprawy / dokumentu | SQL w `rk_caseflow.py` | SQL tej wyszukiwarki w `rk_search_data.py` |
| Panel zadań przy dokumencie | SQL i HTML razem w `rk_ux.py` | SQL w `rk_document_data.py`, HTML w `rk_ux.py` |
| CI | Nie znało nowej struktury | `py_compile` nowych modułów i testy UX/architektury w Windows workflow |

Są to **realne rozdzielenia odpowiedzialności**, a nie tylko podział plików. Dane, terminy procesowe, decyzje prawne i uprawnienia nie są migrowane ani ponownie implementowane w tym etapie.

## Co nadal jest obciążeniem („spaghetti code”)

1. `app.py` nadal jest duży — początkowo 7551 linii, ponad 200 metod z wcięciem klasy, łączących obsługę HTTP, HTML i logikę spraw. Zmniejszono go tylko o wydzielone fragmenty.
2. Parametryczne GET/POST oraz mapowanie modyfikacji do spraw (`mutation_case_id`) nadal opiera się na ręcznym routerze. **Celowo nie przenoszono** ich w pierwszej aktualizacji, żeby nie osłabić kontroli uprawnień.
3. Ekrany `case_workspace()` i `document_view()` nadal są dużymi metodami opartymi na f-stringach HTML. Wymagają osobnej, starannie testowanej ekstrakcji komponentów.
4. `Handler` korzysta z licznych mixinów; przyszłe konflikty nazw należy wykrywać automatycznie.
5. Nadal brak pełnych testów przeglądarkowych interakcji klawiaturowych na gotowym Windows Portable.

## Co dalej — w kolejności bezpiecznej

**Etap 2:** wydzielać pojedyncze widoki na komponenty renderowania, np. `case_workspace` i `document_view`. Wymaga to zachowania stabilnych HTML ID i URL dla istniejącego JS.

**Etap 3:** ujednolicić dostęp do SQLite (transakcje, obiekty danych, filtry statusów). Tylko jeden punkt liczenia tego samego KPI.

**Etap 4:** parametryczne trasy i scentralizowane reguły uprawnień z testami dla każdego typu działania. Nie zmieniać autoryzacji jednocześnie z kosmetyką interfejsu.

**Etap 5:** wyodrębnić szablony HTML z domyślnym escapowaniem, a następnie rozdzielić szczegółowe reguły zadań, dokumentów i terminów do serwisów.

## Bezpieczeństwo i granice testów

W tym etapie nie zmieniono numeru schematu SQLite, plików klienta, reguł obliczania terminów, sposobu przechowywania dokumentów ani uprawnień administracyjnych. Zachowano poprzednie endpointy i kontrolę `require_auth()` oraz blokadę edycji sprawy przed statycznym dispatch POST.

**Testy lokalne korzystały z próbnych tabel i syntetycznych fragmentów źródeł**, nie z rzeczywistego repo uruchomionego w całości. Wynik pozytywny nie dowodzi braku regresji runtime — pozostają pełny zestaw testów w CI i Windows Portable.
