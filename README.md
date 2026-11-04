# RK KANCELARIA 0.3.2-dev1

**CASE WORKSPACE** — zakładkowy warsztat prowadzenia sprawy.

## Najważniejsza zmiana
Po wejściu do sprawy domyślnie otwiera się **Pulpit sprawy**. Stały nagłówek pokazuje:

1. sygnatura,
2. strony / uczestnicy,
3. nazwa sprawy,
4. status, sąd/organ i kategorię.

Niżej znajduje się tylko jedna wybrana zakładka: **Pulpit, Historia, Dokumenty, Zadania, Terminy, Dowody, Strategia, Rozprawa, Finanse, Osoby albo Notatki**. Program pamięta ostatnią zakładkę osobno dla użytkownika i sprawy. Pełny dawny ekran pozostaje dostępny jako **Widok techniczny**.

## Nowe moduły 0.3
- globalna linia czasu,
- kalendarz kancelarii,
- alerty i monity,
- logiczne relacje „co z czego wynika”,
- automatyczne tagi,
- generowane podsumowanie etapu,
- biblioteka prawa KPC / KPK / KPA / PPSA,
- możliwość dodania innych aktów z oficjalnego ELI,
- przypinanie przepisów do sprawy,
- ostrożne wykrywanie terminów z treści dokumentu.

### Zasada bezpieczeństwa terminów
RK KANCELARIA **nie zakłada**, że każde pismo wyznacza 7, 14 lub inny termin. Program może wykryć literalne sformułowanie typu „w terminie 14 dni”, ale tworzy wtedy wyłącznie sugestię. Termin trafia do zadań dopiero po zatwierdzeniu przez użytkownika.

### Biblioteka prawa
W bazie startowo rejestrowane są oficjalne źródła ELI dla KPC, KPK, KPA i PPSA. Pełny tekst jest pobierany do lokalnej bazy przez przycisk **Aktualizuj z ELI**. W razie braku Internetu istniejąca lokalna wersja pozostaje bez zmian. Biblioteka jest pomocą warsztatową i nie zastępuje weryfikacji aktualności aktu ani doboru właściwej podstawy prawnej.


## DEV2 — codzienna obsługa sprawy
- zadanie, monit, termin procesowy i płatność są jednym elementem roboczym synchronizowanym z kalendarzem,
- zadanie można przypisać do aktywnego użytkownika,
- wykonanie zadania jednym kliknięciem ✓ usuwa je z domyślnego widoku otwartych,
- prosty widok sprawy pokazuje krótsze opisy i osobną listę „Do zrobienia”,
- historia sprawy nie dubluje zadań i alertów i jest grupowana według dat,
- dokument główny może mieć wiele załączników, pokazywanych pod pismem,
- biblioteka prawa najpierw pobiera bezpośredni HTML z ELI, a PDF traktuje jako fallback.

## DEV3 — warsztat sprawy
- Pulpit sprawy 2.0: stan, następny termin, najbliższe zadanie, alerty i ryzyka,
- strategia: cel, minimum, stanowiska, argumenty, odpowiedź, ryzyka, plan rozprawy i ugoda,
- mapa twierdzeń i dowodów ze statusem luk dowodowych,
- karta rozprawy generowana z danych sprawy i gotowa do druku/PDF,
- rejestr roszczeń przechowujący kwoty w groszach,
- wiele zdarzeń wynikających z jednego dokumentu,
- automatyczne wersjonowanie pliku przy jego podmianie,
- test odtworzenia pełnego snapshotu wraz z kontrolą kompletności dokumentów.

## Zgodność danych
Migracja DEV9/DEV2 → DEV3 jest addytywna. Nie usuwa starych spraw, dokumentów, zadań ani historii. Numer schematu: **320**.

Dokumentacja zmian: `CHANGELOG_0.3.0-dev3_CASE_WORKSPACE.txt`
Testy: `TESTY_0.3.0-dev3.txt`

## DEV4 — interfejs i wydajność
- naprawiony siedmiokolumnowy kalendarz w wersji Portable,
- jeden moduł **Pisma** obejmujący projekty i szablony,
- jedno źródło CSS/JS w katalogu `assets`, bez rozjeżdżających się duplikatów,
- cache zasobów, rzadsze żądania w tle i dodatkowe indeksy SQLite,
- uporządkowane repozytorium bez historycznych notatek i powielonych plików.

Dokumentacja zmian: `CHANGELOG_0.3.0-dev4_UI_PERFORMANCE.txt`
Test regresji: `TEST_UI_PERFORMANCE_DEV4.py`


## 0.3.1-dev1 — Skrzynka wpływu
- OCR lokalny i sugestie czynności na podstawie pisma (heurystyki, nie analiza prawna).
- Obowiązkowy wybór sprawy i ręczna weryfikacja danych, terminów, monitów oraz zadań.
- Zaznaczane i edytowalne działania zapisują się dopiero po wyraźnym zatwierdzeniu.
- Kalendarz otrzymuje zatwierdzone czynności z datą; terminy nie są obliczane automatycznie.
- Nie wysyła dokumentów do zewnętrznych usług.
- Testy: TEST_INBOX_REVIEW.py.


## Status projektu i zasady korzystania
RK KANCELARIA jest na etapie rozwoju i testów. Projekt i rozwój: Robert Kłosowski.
© 2026 Robert Kłosowski — w zakresie przysługujących praw.

Repozytorium nie jest obecnie udostępniane na licencji open source.
Nie jest udzielana ogólna zgoda na komercyjne rozpowszechnianie elementów
objętych prawami uprawnionego. Zewnętrzne biblioteki i narzędzia pozostają
objęte swoimi licencjami. Szczegóły: `LICENSE.txt`.

Odczyt pism może być niedokładny. Dane, daty, terminy i sugerowane czynności
wymagają każdorazowego sprawdzenia i zatwierdzenia przez użytkownika.


## 0.3.2-dev1 — Stabilizacja, dokumenty współdzielone i pełnomocnictwa
- Skrzynka wpływu: uruchomienie istniejącego modułu, ręczna weryfikacja, bez samoczynnej decyzji o terminach.
- Pełnomocnictwa: rejestr na podstawie już wgranych dokumentów; decyzja o umocowaniu należy do prawnika.
- Jeden dokument może być widoczny w wielu sprawach bez kopiowania oryginalnego pliku.
- Dokumenty współdzielone mają blokadę przypadkowego usunięcia ze sprawy źródłowej.
- Wyszukiwarka: wynik dokumentu otwiera bezpośrednio dokument.
- Podpowiedzi i dane demonstracyjne są neutralne; nie zawierają przykładów rzeczywistych spraw.
- Przed instalacją wykonaj kopię Data. Testy na osobnej kopii bazy.
