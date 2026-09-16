# RK KANCELARIA 0.3.0-dev3

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
