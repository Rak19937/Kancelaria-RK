@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "BASEDIR=%~dp0"
title RK KANCELARIA 0.2.0-dev2 - pelna instalacja
call "%BASEDIR%INSTALUJ_TRYB_DESKTOP.bat"
if errorlevel 1 exit /b 1
set "RKPY=%BASEDIR%.venv\Scripts\python.exe"
if exist "%RKPY%" "%RKPY%" "%BASEDIR%ocr_setup.py" --interactive
echo.
echo Instalacja zakonczona. Uruchom "RK KANCELARIA DESKTOP.bat".
pause
