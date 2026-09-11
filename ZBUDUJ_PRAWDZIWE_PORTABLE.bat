@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

title RK KANCELARIA - budowa TRUE PORTABLE

echo ============================================================
echo   RK KANCELARIA 0.2.0-dev3 - TRUE PORTABLE BUILDER
echo ============================================================
echo.
echo Ten skrypt wymaga Pythona TYLKO na komputerze, na ktorym budujesz paczke.
echo Gotowy folder z dist NIE wymaga Pythona ani pip.
echo.

set "PYEXE="
where py >nul 2>nul
if not errorlevel 1 (
    py -3.13 -c "import sys; print(sys.version)" >nul 2>nul && set "PYEXE=py -3.13"
    if not defined PYEXE py -3.12 -c "import sys; print(sys.version)" >nul 2>nul && set "PYEXE=py -3.12"
    if not defined PYEXE py -3.11 -c "import sys; print(sys.version)" >nul 2>nul && set "PYEXE=py -3.11"
)
if not defined PYEXE (
    where python >nul 2>nul
    if not errorlevel 1 set "PYEXE=python"
)

if not defined PYEXE (
    echo [BLAD] Nie znaleziono Pythona 3.11-3.13 na komputerze budujacym.
    echo Zainstaluj Python x64 na SWOIM komputerze, zbuduj paczke, a potem
    echo przenies gotowy folder na komputer bez Pythona.
    pause
    exit /b 2
)

echo [1/7] Python: %PYEXE%
%PYEXE% -c "import sys,struct; assert struct.calcsize('P')*8==64, 'Wymagany Python x64'; print(sys.version)"
if errorlevel 1 goto :fail

if not exist ".buildvenv\Scripts\python.exe" (
    echo [2/7] Tworzenie izolowanego srodowiska budowania...
    %PYEXE% -m venv .buildvenv
    if errorlevel 1 goto :fail
) else (
    echo [2/7] Srodowisko budowania juz istnieje.
)

set "BPY=.buildvenv\Scripts\python.exe"

echo [3/7] Aktualizacja narzedzi...
"%BPY%" -m pip install --disable-pip-version-check --upgrade pip setuptools wheel
if errorlevel 1 goto :fail

echo [4/7] Instalacja bibliotek RK KANCELARIA i PyInstaller...
"%BPY%" -m pip install --disable-pip-version-check -r requirements.txt -r requirements_desktop.txt "pyinstaller>=6.15,<7"
if errorlevel 1 goto :fail

echo [5/7] Czyszczenie starego buildu...
if exist build rmdir /s /q build
if exist "dist\RK KANCELARIA PORTABLE" rmdir /s /q "dist\RK KANCELARIA PORTABLE"

echo [6/7] Budowanie samodzielnej aplikacji Windows...
"%BPY%" -m PyInstaller --noconfirm --clean RK_KANCELARIA_PORTABLE.spec
if errorlevel 1 goto :fail

set "DIST=dist\RK KANCELARIA PORTABLE"
if not exist "%DIST%\RK KANCELARIA.exe" (
    echo [BLAD] PyInstaller nie utworzyl pliku EXE.
    goto :fail
)

rem Pliki, ktore MUSZA byc obok EXE - nie w _internal.
> "%DIST%\portable.flag" echo RK KANCELARIA TRUE PORTABLE
> "%DIST%\auto_sync.flag" echo auto sync enabled
if not exist "%DIST%\Data" mkdir "%DIST%\Data"
copy /y "Data\README.txt" "%DIST%\Data\README.txt" >nul 2>nul
copy /y "README_TRUE_PORTABLE.txt" "%DIST%\README_TRUE_PORTABLE.txt" >nul

> "%DIST%\SYNCHRONIZUJ.bat" echo @echo off
>> "%DIST%\SYNCHRONIZUJ.bat" echo cd /d "%%~dp0"
>> "%DIST%\SYNCHRONIZUJ.bat" echo start "" "RK KANCELARIA.exe" --sync-gui

> "%DIST%\TRYB_BEZPIECZNY.bat" echo @echo off
>> "%DIST%\TRYB_BEZPIECZNY.bat" echo cd /d "%%~dp0"
>> "%DIST%\TRYB_BEZPIECZNY.bat" echo start "" "RK KANCELARIA.exe" --safe-gpu

> "%DIST%\URUCHOM_RK_KANCELARIA.bat" echo @echo off
>> "%DIST%\URUCHOM_RK_KANCELARIA.bat" echo cd /d "%%~dp0"
>> "%DIST%\URUCHOM_RK_KANCELARIA.bat" echo start "" "RK KANCELARIA.exe"

echo [7/7] Kontrola struktury...
if not exist "%DIST%\_internal" (
    echo [BLAD] Brak katalogu _internal.
    goto :fail
)
if not exist "%DIST%\portable.flag" (
    echo [BLAD] Brak portable.flag.
    goto :fail
)

echo.
echo ============================================================
echo GOTOWE.
echo.
echo Folder do przeniesienia na komputer bez Pythona:
echo   %CD%\%DIST%
echo.
echo Na drugim komputerze uruchamiasz:
echo   RK KANCELARIA.exe
echo.
echo NIE przenos samego EXE - przenies caly folder "RK KANCELARIA PORTABLE".
echo ============================================================
explorer "%DIST%"
pause
exit /b 0

:fail
echo.
echo ============================================================
echo BUDOWANIE NIE POWIODLO SIE.
echo Zostaw okno otwarte i zachowaj komunikat bledu.
echo ============================================================
pause
exit /b 1
