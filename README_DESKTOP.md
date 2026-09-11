# RK KANCELARIA 0.15.2 — Desktop

Tryb Desktop używa **lokalnego `.venv` w folderze programu**, tak jak stabilna gałąź 0.14.
Dane użytkownika pozostają niezależnie w `%LOCALAPPDATA%\RK_KANCELARIA\Dane`.

## Start
1. Rozpakuj cały ZIP do zwykłego folderu.
2. Uruchom `INSTALUJ_TRYB_DESKTOP.bat`.
3. Uruchom `RK KANCELARIA DESKTOP.bat`.
4. W razie problemu: `SPRAWDZ_TRYB_DESKTOP.bat`.

0.15.2 nie korzysta z `%LOCALAPPDATA%\RK_KANCELARIA\Runtime\venv` do uruchamiania programu. Stary Runtime może pozostać na dysku, ale jest ignorowany.
