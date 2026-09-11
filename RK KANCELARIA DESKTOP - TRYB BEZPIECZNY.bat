@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "BASEDIR=%~dp0"
set "RKPYC=%BASEDIR%.venv\Scripts\python.exe"
set "RKPYW=%BASEDIR%.venv\Scripts\pythonw.exe"
if not exist "%RKPYC%" call "%BASEDIR%INSTALUJ_TRYB_DESKTOP.bat"
if not exist "%RKPYW%" goto :error
start "" /D "%BASEDIR%" "%RKPYW%" "%BASEDIR%desktop.py" --safe-gpu
exit /b 0
:error
echo Nie udalo sie uruchomic trybu bezpiecznego.
pause
exit /b 1
