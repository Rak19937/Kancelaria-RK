# RK KANCELARIA 0.3.0-dev2

**USABILITY & LINKED WORKFLOW** — dopracowanie prostego widoku, zadań, kalendarza, dokumentów i biblioteki prawa.

## Najważniejsza zmiana
Po wejściu do sprawy domyślnie otwiera się **Widok prosty**. Pierwsze informacje to:

1. sygnatura,
2. strony / uczestnicy,
3. nazwa sprawy,
4. automatyczny opis,
5. aktualny etap,
6. „co teraz”,
7. najbliższe terminy i alerty.

Pełne tabele, dokumenty, techniczna historia i dotychczasowe moduły pozostają dostępne przez **Widok zaawansowany**.

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

## Zgodność danych
Migracja DEV9 → 0.3 jest addytywna. Nie usuwa starych spraw, dokumentów, zadań ani historii. Numer schematu: **310**.

Dokumentacja zmian: `CHANGELOG_0.3.0-dev2_USABILITY.txt`  
Testy: `TESTY_0.3.0-dev2.txt`
