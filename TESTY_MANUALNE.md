# RK KANCELARIA 0.3.2-dev1 — kontrola przed zastąpieniem starej wersji

Zaznaczaj wyłącznie na **osobnej kopii danych testowych**.

- [ ] Program uruchamia się po kompilacji bez błędów i pokazuje nową wersję.
- [ ] „Skrzynka wpływu” jest widoczna w menu PRACA.
- [ ] Sztuczny PDF trafia do skrzynki; odczytane dane można skorygować.
- [ ] Odrzucenie propozycji czynności nie tworzy zadania ani terminu.
- [ ] Zatwierdzenie wybranej propozycji zapisuje ją do właściwej sprawy; ponowne kliknięcie nie duplikuje.
- [ ] Po restarcie programu dokument i zatwierdzone zadania nadal istnieją.
- [ ] Nowa zakładka „Pełnomocnictwa” działa i pozwala wyszukiwać wpisy.
- [ ] Dodanie/edycja wpisu pełnomocnictwa nie kopiuje oryginalnego pliku.
- [ ] Usunięcie z rejestru pełnomocnictw nie usuwa dokumentu w sprawie.
- [ ] Dokument można przypisać do dwóch innych spraw bez ponownego wgrywania.
- [ ] Ten sam dokument jest widoczny w kartach wszystkich trzech spraw.
- [ ] Odłączenie dokumentu z dodatkowej sprawy nie usuwa pliku z pozostałych.
- [ ] Usunięcie dokumentu źródłowego z aktywnymi powiązaniami jest zablokowane.
- [ ] Globalna wyszukiwarka prowadzi z wyniku bezpośrednio do dokumentu.
- [ ] „Tagi” i „Nowa sprawa” nie ujawniają nazwisk ani sygnatur z rzeczywistych spraw.
- [ ] Zakładka „O programie” pokazuje status rozwojowy i informację o autorze.
- [ ] Kopia zapasowa testowej bazy daje się odtworzyć; po restarcie nie ma ubytków danych.
- [ ] W `main` nie ma przypadkowo dodanych baz SQLite, folderu Data ani dokumentów klientów.

Jeżeli którykolwiek test nie przechodzi, **nie podmieniaj starej wersji**.
