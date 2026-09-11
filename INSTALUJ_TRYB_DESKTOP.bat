@echo off
setlocal EnableExtensions
chcp 65001 >nul
title RK KANCELARIA 0.2.0-dev2 - instalacja Desktop

set "BASEDIR=%~dp0"
if not exist "%BASEDIR%app.py" goto :not_extracted
if not exist "%BASEDIR%install_desktop.py" goto :not_extracted

set "PYEXE="
set "PYARG="

where py.exe >nul 2>nul
if not errorlevel 1 (
  for %%V in (3.14 3.13 3.12 3.11 3.10) do (
    if not defined PYEXE (
      py -%%V -c "import sys; assert sys.maxsize > 2**32" >nul 2>nul
      if not errorlevel 1 (
        set "PYEXE=py.exe"
        set "PYARG=-%%V"
      )
    )
  )
  if not defined PYEXE (
    py -3 -c "import sys; assert (3,10) <= sys.version_info[:2] < (3,15) and sys.maxsize > 2**32" >nul 2>nul
    if not errorlevel 1 (
      set "PYEXE=py.exe"
      set "PYARG=-3"
    )
  )
)

if not defined PYEXE (
  where python.exe >nul 2>nul
  if not errorlevel 1 (
    python.exe -c "import sys; assert (3,10) <= sys.version_info[:2] < (3,15) and sys.maxsize > 2**32" >nul 2>nul
    if not errorlevel 1 set "PYEXE=python.exe"
  )
)

if not defined PYEXE goto :nopython

echo Wykryto Pythona:
if defined PYARG (
  "%PYEXE%" %PYARG% --version
  "%PYEXE%" %PYARG% "%BASEDIR%install_desktop.py"
) else (
  "%PYEXE%" --version
  "%PYEXE%" "%BASEDIR%install_desktop.py"
)
if errorlevel 1 goto :err

echo.
echo GOTOWE. Uruchom "RK KANCELARIA DESKTOP.bat".
pause
exit /b 0

:not_extracted
echo BLAD: Nie znaleziono plikow programu obok instalatora.
echo Najpierw ROZPAKUJ caly ZIP do zwyklego folderu i dopiero wtedy uruchom ten plik BAT.
echo Nie uruchamiaj programu bezposrednio z podgladu ZIP w Eksploratorze Windows.
pause
exit /b 2

:nopython
echo BLAD: Nie znaleziono zgodnego 64-bitowego Python 3.10-3.14.
echo Sprawdz w CMD: py -3 --version
pause
exit /b 1

:err
echo.
echo BLAD instalacji. Log: %%LOCALAPPDATA%%\RK_KANCELARIA\Dane\instalacja_desktop.log
pause
exit /b 1
