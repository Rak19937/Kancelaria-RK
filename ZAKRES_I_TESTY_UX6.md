# Rejestr zmian i weryfikacji UX6

Badana podstawa: repozytorium `Rak19937/Kancelaria-RK` gałąź `main`, źródło `0.4.0-dev5`, listopad 2026.

| Obszar | Zmiana | Lokalna weryfikacja | Weryfikacja wymagająca GitHub/Windows |
|---|---|---|---|
| Usuwanie sprawy | snapshot przed modyfikacją, sprawdzenie rozmiaru kopii, obsługa błędów SQL, FK; komunikat o roli administratora | testy syntetycznej SQLite i idempotencji instalatora | rzeczywisty usuwany przypadek tylko na testowej kopii danych |
| Sugestie dokumentów | duże rozwijane panele, większy font, pola edycji pozostają bez zmian | kontrola składni JS | interaktywne otwieranie i wybór sugestii w UI |
| Równoległe etapy | tabela dodatkowych etapów, wiele aktywnych równocześnie, formularz i status | testy SQLite | zapis i odczyt w interfejsie Windows |
| Lista własnych wartości | trwała tabela wyborów, walidacja, zapis i ponowne wczytanie, wybrane backendy dopuszczają własne wartości | testy SQLite, kontrola kodu JS | formularze i role w zbudowanym EXE |
| Boczne menu | centrowanie ikon złożonego paska w CSS | kontrola CSS | ręczny widok przy różnych szerokościach ekranu |
| Kalendarz | agregacja duplikatów tylko w widoku miesiąca, dzień z edycją alarmów, zadań, spotkań i zdarzeń | kontrola składni i istniejącego schematu | test kliknięć, kilka różnych typów wpisu tego samego dnia |
| Instalator i CI | idempotentny patcher, snapshot oryginalnego kodu, testy regresji, PyInstaller i self-test EXE przed commit | fikcyjny wzorzec źródeł, 15 testów SQLite | pełen przebieg GitHub Actions |

## Wyniki dotychczasowe

- 15 testów lokalnych `TEST_RK_UX6.py`: **PASS**.
- Wzorcowe zastosowanie instalatora: **dry-run PASS**, **patch PASS**, **verify PASS**, **ponowny patch bez zmian PASS**.
- Kompilacja składniowa trzech skryptów Python i walidacja skryptu JavaScript: **PASS**.
- Struktura YAML: **PASS**.
- Budowanie Windows Portable oraz regresja na rzeczywistym repo: **jeszcze nieprzeprowadzone dla UX6**. Te testy wykona workflow po wgraniu paczki.

## Co nadal jest ryzykiem

- Historyczne schematy klientów mogą mieć dodatkowe relacje blokujące usuwanie sprawy; ich agresywne kasowanie nie jest bezpieczne bez dokładnej znajomości danych.
- Równoczesna edycja tego samego rekordu przez wielu użytkowników nadal wymaga osobnych testów współbieżności.
- Zawężona kontrola uprawnień: nowy ekran całego kalendarza dnia oraz niestandardowe etapy są przeznaczone dla administratora; szczegółowe uprawnienia per sprawa to osobny etap.
- Zgrupowanie wizualnych dubletów nie oznacza usunięcia/połączenia rekordów. Szczegółowy dzień nadal je wymienia.
