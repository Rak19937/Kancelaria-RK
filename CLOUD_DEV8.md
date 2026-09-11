# RK KANCELARIA DEV8 — Cloud / PWA

DEV8 ma dwa bezpieczne modele pracy wielourządzeniowej:

## 1. Jedna żywa aplikacja — zalecane do równoczesnej pracy
Uruchom RK KANCELARIA na jednym komputerze/serwerze i wystaw ją użytkownikom przez HTTPS/VPN.
Telefon/tablet może dodać aplikację do ekranu głównego jako PWA. Wszyscy pracują wtedy na tej
samej bazie serwera. Nie wystawiaj zwykłego HTTP bezpośrednio do Internetu.

## 2. Cloud Bridge — Portable/backup/synchronizacja pełnego stanu
`rk_cloud_server.py` przechowuje w PostgreSQL wersjonowane snapshoty całej kancelarii.
Klient DEV8 porównuje numer wersji. Jeżeli serwer zmienił się od ostatniej synchronizacji,
push jest blokowany kodem konfliktu zamiast cicho nadpisać dane.

### Serwer
```text
pip install -r requirements_cloud.txt
DATABASE_URL=postgresql://... \
RK_CLOUD_TOKEN=dlugi-losowy-token \
python rk_cloud_server.py
```
W produkcji postaw przed serwerem reverse proxy HTTPS i ogranicz dostęp zaporą/VPN.

### Klient
Administrator: `System -> Cloud / PWA`.
Można też użyć zmiennych:
- `RK_CLOUD_URL`
- `RK_CLOUD_OFFICE_ID`
- `RK_CLOUD_TOKEN`

Token nie jest umieszczany w eksportowanym pełnym snapshotcie.

## PWA i prywatność
Service Worker DEV8 cache'uje wyłącznie statyczne CSS/JS/logo/manifest.
HTML spraw, dokumenty, wyszukiwarka i dane klienta są zawsze pobierane z sieci i nie są
zapisywane w cache offline przez Service Worker.
