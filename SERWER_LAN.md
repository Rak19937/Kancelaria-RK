# RK KANCELARIA 0.12 — serwer wewnętrzny / LAN

Aplikacja może działać lokalnie albo jako serwer dla kilku komputerów w sieci wewnętrznej.


## Trwałość danych między wersjami

Od 0.11 kod aplikacji i dane są rozdzielone. Na serwerze zdecydowanie ustaw stały katalog, np.:

`SPRAWNIK_DATA_DIR=D:\RK_KANCELARIA_DATA`

Przy aktualizacji podmieniasz wyłącznie kod programu. Baza i dokumenty pozostają w stałym katalogu danych. Nie umieszczaj właściwej bazy wewnątrz folderu wersji aplikacji.

## Konta użytkowników

Od wersji 0.7 nie używa się już jednego wspólnego hasła HTTP Basic. Każda osoba ma własne konto w RK KANCELARIA.

Przy pierwszym uruchomieniu programu utwórz konto administratora. Administrator może później wejść w **Użytkownicy** i tworzyć kolejne konta.

Każde konto ma:
- login,
- hasło,
- przypisaną nazwę **Autora wpisów**,
- rolę Administrator lub Użytkownik,
- status aktywne/nieaktywne.

Autor jest przypisywany automatycznie do nowych wpisów na podstawie zalogowanego konta.

## Najważniejsze zmienne środowiskowe

Nazwy `SPRAWNIK_*` są zachowane technicznie dla zgodności z wcześniejszymi wersjami.

- `SPRAWNIK_HOST=0.0.0.0` — nasłuch w LAN.
- `SPRAWNIK_PORT=8765` — port aplikacji.
- `SPRAWNIK_DATA_DIR=D:\RKKancelariaData` — baza i dokumenty poza katalogiem kodu.
- `SPRAWNIK_OPEN_BROWSER=0` — nie otwieraj przeglądarki na serwerze.
- `SPRAWNIK_AUTO_SHUTDOWN=0` — serwer nie wyłącza się po zamknięciu kart użytkowników.
- `RK_SESSION_HOURS=12` — czas ważności sesji logowania (domyślnie 12 godzin).
- `SPRAWNIK_PDF_FONT=...` — opcjonalna ścieżka do fontu dla PDF.

Zmienne `SPRAWNIK_USER` oraz `SPRAWNIK_PASSWORD` z wersji 0.6 nie są już używane.

## Windows

```bat
set SPRAWNIK_HOST=0.0.0.0
set SPRAWNIK_PORT=8765
set SPRAWNIK_DATA_DIR=D:\RKKancelariaData
set SPRAWNIK_OPEN_BROWSER=0
set SPRAWNIK_AUTO_SHUTDOWN=0
start_server_windows.bat
```

Użytkownicy wchodzą na adres IP serwera, np. `http://192.168.1.20:8765/` i logują się własnym kontem.

## Linux

```bash
export SPRAWNIK_HOST=0.0.0.0
export SPRAWNIK_PORT=8765
export SPRAWNIK_DATA_DIR=/srv/rk-kancelaria/data
export SPRAWNIK_OPEN_BROWSER=0
export SPRAWNIK_AUTO_SHUTDOWN=0
./start_server_linux_mac.sh
```

## Wielu użytkowników

SQLite pracuje w trybie WAL i aplikacja otwiera osobne połączenia na żądanie. Jest to rozwiązanie odpowiednie do lekkiej pracy kilku osób w małej kancelarii. Przy dużej liczbie jednoczesnych użytkowników kolejnym krokiem powinno być przejście na PostgreSQL.

## Dokumenty

Pliki znajdują się w `dokumenty/` w katalogu danych. Użytkownicy nie potrzebują bezpośredniego udziału sieciowego — dokumenty są otwierane i pobierane przez aplikację po zalogowaniu.

## Bezpieczeństwo sieciowe

Hasła są przechowywane jako hashe PBKDF2-SHA256 z indywidualnymi solami. Sesja wykorzystuje losowy token w ciasteczku `HttpOnly` i `SameSite=Lax`.

Nie wystawiaj aplikacji bezpośrednio do publicznego Internetu. Zwykły HTTP nie szyfruje ruchu, więc dla dostępu wykraczającego poza zaufany LAN użyj VPN lub reverse proxy z HTTPS. Ogranicz port zaporą i regularnie wykonuj kopie całego katalogu danych.
