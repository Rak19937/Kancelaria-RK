# RK KANCELARIA dev3 R2 — test odbiorczy na kopii danych

Zaznacz wszystkie poniższe przypadki w **gotowym Windows Portable**. Nie podłączaj na razie produkcyjnego kalendarza ani nie testuj na realnych dokumentach klientów.

## Nawigacja (testy ręczne)
- [ ] Otwórz program w szerokim oknie: na lewo widzisz tylko wąską listwę z ikonami.
- [ ] Najedź na lewy bok i zaczekaj krótką chwilę: panel rozwija się bez przesuwania treści sprawy.
- [ ] Kliknij pinezkę: panel pozostaje otwarty po odsunięciu kursora.
- [ ] **Kliknij pinezkę ponownie, nie przesuwając wcześniej kursora:** panel zwija się.
- [ ] Przypnij ponownie i kliknij przycisk ☰: panel zwija się od razu.
- [ ] Kliknij ☰, aby rozwinąć menu; ponowny klik je chowa.
- [ ] Wciśnij `Alt+M` dwa razy: otwórz i zamknij menu.
- [ ] Wciśnij `Esc` w otwartym menu: panel się zwija.
- [ ] Wpisz nazwę zakładki w wyszukiwarce; wyczyść: wcześniejsze grupy wracają.
- [ ] Sprawdź panel na oknie o szerokości ok. 800 px i na małym ekranie; na mobile działa nawigacja bez panelu overlay.
- [ ] Przejdź do sprawy, dokumentów, skrzynki wpływu, kalendarza i pulpitu.

## Ewidencja czasu
- [ ] Uruchom stoper na testowej sprawie; licznik odlicza czas.
- [ ] Odśwież stronę: pomiar trwa, a licznik pokazuje upływający czas.
- [ ] Naciśnij anulowanie i odmów w oknie potwierdzenia: stoper dalej działa.
- [ ] Potwierdź anulowanie: nie powstaje wpis czasu.
- [ ] Uruchom stoper ponownie, zatrzymaj i zapisz: wpis powstaje we właściwej sprawie.
- [ ] Dodaj 30 minut ręcznie, sprawdź stawkę i eksport CSV; nie ma przesunięcia daty.
- [ ] Użytkownik nie-admin nie widzi cudzych wpisów i nie może ich usuwać.

## Sejf
- [ ] Dodaj fikcyjny plik i zabezpiecz go hasłem testowym o długości >= 12 znaków.
- [ ] Pobierz go przez podanie hasła; z błędnym hasłem pobranie się nie udaje.
- [ ] Nadaj dostęp drugiemu użytkownikowi; sprawdź widoczność pliku.
- [ ] Cofnij dostęp; drugi użytkownik nie może już otworzyć pliku w systemie.
- [ ] Fizyczny plik zaszyfrowany pozostaje w sejfie, a odzyskany dokument ma prawidłową treść.

## Integracje i bezpieczeństwo
- [ ] Wczytaj fikcyjny CSV Portalu Informacyjnego: wpis nie tworzy automatycznie doręczenia ani terminu.
- [ ] Zweryfikuj wpis, popraw przypisaną sprawę, następnie cofnij weryfikację.
- [ ] Kalendarz: testowo pobierz propozycję z właściwie autoryzowanego konta testowego, nie z konta zawodowego.
- [ ] Odrzuć propozycję: nie tworzy lokalnego terminu.
- [ ] Zatwierdź inną propozycję: powstaje dokładnie jeden termin, data i godzina są poprawne dla Europe/Warsaw.
- [ ] Zrestartuj Portable: sprawy, dokumenty i wpisy czasu nie znikają.
- [ ] Sprawdź backup/restore na KOPII danych. Nie wykonuj przywracania nad produkcyjną bazą.
- [ ] Zapisz wersję antywirusa i nazwę ewentualnego alertu, bez automatycznych wyjątków.

**Uwaga:** testy realizacji funkcji po rzeczywistych integracjach API wymagają dostępu do ich testowych kont. Zielony wynik GitHub Actions nie potwierdza tych przypadków.
