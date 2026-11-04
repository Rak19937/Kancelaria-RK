# RK KANCELARIA 0.3.4-dev1 — testy użytkowe

Testuj w nowym katalogu Portable, z danymi przykładowymi, bez prawdziwych danych klientów.

1. Dodaj testową sprawę i dokument z tekstem „Sąd zobowiązuje do przedłożenia dokumentów w terminie 14 dni”. Kliknij **Zaproponuj czynności**.
2. Sprawdź, że **bez potwierdzenia** w zadaniach nie pojawiło się nic nowego.
3. Zaznacz jedną propozycję jako **Zadanie**, popraw jej opis i zatwierdź. Sprawdź obecność zadania i wpisu w historii sprawy.
4. Zaznacz drugą propozycję jako **Termin procesowy**, nie wpisując dat i podstawy. Program musi **odmówić** zapisu.
5. Wpisz poprawnie ręcznie zweryfikowane: datę początkową, datę końcową, podstawę i sposób obliczenia, zaznacz potwierdzenia. Dopiero wtedy termin powinien się zapisać.
6. Odrzuć trzecią propozycję. Nie powinno powstać zadanie.
7. Edytuj dokument po analizie i spróbuj zatwierdzić propozycję ze starej analizy. Zapis powinien być zablokowany do ponownej analizy.
8. Sprawdź **Centrum decyzji**: lista analiz i oczekujących pism ze Skrzynki wpływu.
9. Sprawdź **Projekt pisma → Zaproponuj czynności** i przypadek projektu bez przypisanej sprawy.
10. Uruchom program ponownie — istniejące sprawy, projekty, dokumenty, wersje i multimedia muszą pozostać dostępne.

Jeśli którykolwiek test zawiedzie, zachowaj starą wersję Portable i nie przenoś do nowej wersji prawdziwej bazy danych.
