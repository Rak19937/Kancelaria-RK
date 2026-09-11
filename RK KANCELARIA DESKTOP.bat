@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "BASEDIR=%~dp0"
set "RKPYC=%BASEDIR%.venv\Scripts\python.exe"
set "RKPYW=%BASEDIR%.venv\Scripts\pythonw.exe"

if not exist "%BASEDIR%desktop.py" goto :not_extracted

if exist "%RKPYC%" if exist "%RKPYW%" (
  "%RKPYC%" -c "import PySide6, fitz, pypdf, cryptography, openpyxl; from PySide6.QtWebEngineWidgets import QWebEngineView" >nul 2>nul
  if not errorlevel 1 goto :start
)

echo Brak lub niepelne lokalne .venv. Uruchamiam instalator...
call "%BASEDIR%INSTALUJ_TRYB_DESKTOP.bat"
if errorlevel 1 goto :error
if not exist "%RKPYW%" goto :error

:start
start "" /D "%BASEDIR%" "%RKPYW%" "%BASEDIR%desktop.py"
exit /b 0

:not_extracted
echo BLAD: Brak desktop.py. Rozpakuj caly ZIP do zwyklego folderu.
pause
exit /b 2

:error
echo.
echo Nie udalo sie uruchomic RK KANCELARIA Desktop.
echo Uruchom SPRAWDZ_TRYB_DESKTOP.bat.
pause
exit /b 1
