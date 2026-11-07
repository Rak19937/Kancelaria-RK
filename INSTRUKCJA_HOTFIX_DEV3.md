# RK KANCELARIA 0.4.0-dev3 — hotfix historycznego testu 0.3.10

Błąd wykryty w GitHub Actions run 42377336869:
`TEST_INTEGRACJA_PACZKI_0310.py` -> `RuntimeError: rk_navigation.py zmieniono po instalacji`.

Przyczyna: historyczny test rollbacku 0.3.10 porównywał pliki
z bieżącym repo, które ma już nową nawigację dev3. Na Windows
różne zakończenia linii CRLF/LF mogły dodatkowo powodować rozbieżność
przy porównywaniu bajtów.

NAPRAWA: test zamraża oczekiwane bajty plików wygenerowanych w
izolowanej, syntetycznej instalacji 0.3.10. Następnie sprawdza
ich zgodność za pomocą oryginalnego PRZYWROC_0310.py. Kontrola
odmawiająca cofnięcia modyfikowanych plików pozostaje aktywna.
Dodano test celowego zmodyfikowania modułu — cofnięcie musi zostać
zablokowane.

## Jak zainstalować

1. Rozpakuj ZIP.
2. Zastąp na GitHubie jeden plik w katalogu głównym:
   `TEST_INTEGRACJA_PACZKI_0310.py`.
3. Nie zmieniaj `ZASTOSUJ_040_DEV3.py`, `.github/workflows/main.yml`,
   `app.py` ani katalogu `Data`.
4. Wykonaj jeden commit. GitHub Actions uruchomi kompilację ponownie.

## Weryfikacja

- GitHub (przed naprawą): 31/32 plików testów przechodziło.
- Lokalnie: odtworzono ten sam wyjątek na CRLF po instalacji.
- Po naprawie: 5/5 testów testu historycznego OK.
- Sprawdzono, że celowo zmieniony plik nadal blokuje rollback.
- Pełna kompilacja Windows EXE po tej poprawce nie była jeszcze uruchomiona.
