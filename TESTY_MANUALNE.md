# Testy ręczne po kompilacji RK KANCELARIA 0.3.8-dev1

Wykonaj na kopii danych, nie na jedynej bazie kancelarii.

1. Uruchom program i sprawdź `O programie` — oczekiwana wersja 0.3.8-dev1.
2. Kliknij `Dokumenty`. Sprawdź, że najpierw widzisz listę teczek spraw i wyszukiwarkę, a nie wszystkie pliki wszystkich spraw naraz.
3. Wyszukaj sprawę po sygnaturze lub kliencie, kliknij nazwę. Dokumenty powinny być wyświetlone chronologicznie. Zmień sortowanie na najnowsze/najstarsze.
4. Wejdź w `Centrum dowodowe`. Wybierz sprawę; sprawdź twierdzenia i powiązane dowody, potem przejdź do istniejącej zakładki `Dowody` w sprawie.
5. Otwórz zadanie A. Wejdź w `Zarządzaj zależnościami`. Dodaj zadanie B z tej samej sprawy jako wymagane. Zapisz. Spróbuj oznaczyć A jako wykonane: program powinien ostrzec i zażądać uzasadnienia świadomego obejścia.
6. Zakończ B. Spróbuj zakończyć A ponownie: bez ostrzeżenia. Cofnij oba zadania i sprawdź, czy odnośniki nadal działają.
7. Spróbuj utworzyć cykl A → B i B → A. Program powinien odrzucić drugie powiązanie.
8. Sprawdź zależność od postępowania pobocznego. Dopóki ma status „oczekujemy”, główne zadanie powinno być oznaczone jako zależne. Po zmianie statusu na „uzyskano” — odblokowane.
9. Utwórz dwa zdarzenia z datami w odwrotnej kolejności wprowadzania. `Chronologia` powinna ustawić je według dat wydarzeń.
10. Dodaj dokument z wcześniejszą datą niż ostatnie dokumenty. Sprawdź chronologię oraz różnicę między datą dokumentu, wpływu i doręczenia.
11. Sprawdź `Historia zmian` — powinna zachowywać rzeczywisty czas wykonania operacji, nawet dla wydarzeń datowanych wstecz.
12. Sprawdź szybkie wyszukiwanie na górze strony, kliknięcie nazw oraz powrót do kart spraw, dokumentów i zadań.
13. Sprawdź starsze dane 0.3.7: kalendarz, terminy, przypisania kilku osób, kategorie i korespondencję.
14. Nie przełączaj jedynej bazy produkcyjnej przed wykonaniem kopii i tych testów.
