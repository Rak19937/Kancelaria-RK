@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "BASEDIR=%~dp0"
set "RKPY=%BASEDIR%.venv\Scripts\python.exe"

echo ============================================
echo  RK KANCELARIA 0.2.0-dev2 - DIAGNOSTYKA DESKTOP
echo ============================================
echo Folder programu: %BASEDIR%
echo.

if not exist "%BASEDIR%app.py" (
  echo BLAD: app.py nie istnieje obok tego pliku.
  echo Rozpakuj CALY ZIP do zwyklego folderu. Nie uruchamiaj BAT bezposrednio z ZIP-a.
  pause
  exit /b 2
)

echo [1/4] Python systemowy
where py.exe >nul 2>nul
if not errorlevel 1 py -3 --version
where python.exe >nul 2>nul
if not errorlevel 1 python.exe --version

echo.
echo [2/4] Lokalne .venv
if not exist "%RKPY%" (
  echo BRAK: %RKPY%
  echo Uruchom INSTALUJ_TRYB_DESKTOP.bat.
  pause
  exit /b 1
)
"%RKPY%" --version

echo.
echo [3/4] Biblioteki Desktop
"%RKPY%" -c "import PySide6, fitz, pypdf, cryptography, openpyxl; from PySide6.QtWebEngineWidgets import QWebEngineView; print('PySide6',PySide6.__version__); print('IMPORTY: OK')"
if errorlevel 1 (
  echo BLAD bibliotek. Uruchom ponownie INSTALUJ_TRYB_DESKTOP.bat.
  pause
  exit /b 1
)

echo.
echo [4/4] Bezpieczny self-test programu
"%RKPY%" "%BASEDIR%desktop.py" --self-test
set "RC=%errorlevel%"
echo.
if "%RC%"=="0" (echo SELF-TEST: OK) else (echo SELF-TEST: BLAD ^(kod %RC%^))
echo Log instalatora: %%LOCALAPPDATA%%\RK_KANCELARIA\Dane\instalacja_desktop.log
pause
exit /b %RC%
